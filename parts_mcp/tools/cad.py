"""
CAD pipeline MCP tools — parametric STEP/BREP edits via cadquery.

Wraps the API's /v1/cad/step/* family:
  POST /v1/cad/step/inspect    → JSON metadata
  POST /v1/cad/step/pipeline   → binary in chosen output format (chain of ops)
  POST /v1/cad/step/convert    → binary in target format

Three tools are exposed (kept narrow on purpose — single-op routes on the
API side are also reachable via cad_modify_step with a one-element ops list):

    cad_inspect_step(file_path)
        -> {bounding_box, topology, volume_mm3, center_of_mass}

    cad_modify_step(file_path, operations, output_format='step')
        -> {output_path, output_format, size_bytes}

    cad_convert_step(file_path, target_format)
        -> {output_path, target_format, size_bytes}
"""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

import httpx
from fastmcp import FastMCP

from parts_mcp.utils.api_client import (
    SourcePartsAPIError,
    SourcePartsAuthError,
    SourcePartsRateLimitError,
    get_client,
    with_user_context,
)

logger = logging.getLogger(__name__)

# Match the API's MAX_CAD_BYTES.
MAX_FILE_SIZE = 100 * 1024 * 1024

# Same as the API blueprint allowlists. Keep in sync with
# Source_Parts/API/blueprints/v1/cad.py if those change.
INPUT_FORMATS = {"step", "stp", "brep", "stl"}
OUTPUT_FORMATS = {"step", "stl", "obj", "amf", "dxf", "gltf"}

# Where to drop result files. /tmp is the conventional MCP-tool scratch dir.
TMP_PREFIX = "cad-mcp-"


def _ext_to_format(filename: str) -> str:
    """Infer source format from file extension. Falls back to 'step'."""
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix in {"stp"}:
        return "step"
    if suffix in INPUT_FORMATS:
        return suffix
    return "step"


def _validate_local_file(file_path: str) -> tuple[Path | None, str | None]:
    """Resolve, validate, and size-check a local file path."""
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return None, f"File not found: {path}"
    if not path.is_file():
        return None, f"Not a file: {path}"
    if path.stat().st_size > MAX_FILE_SIZE:
        return None, f"File too large: {path.stat().st_size:,} bytes (max {MAX_FILE_SIZE:,})"
    return path, None


def _upload_to_cad_endpoint(
    endpoint: str,
    file_path: Path,
    form_fields: dict[str, str],
    *,
    expect_json: bool,
) -> tuple[dict | bytes | None, str | None]:
    """POST a multipart file to /v1/cad/step/<endpoint> and return either
    parsed JSON or raw bytes depending on expect_json.

    Returns (payload, error). Either payload or error is None.
    """
    client = get_client()
    url = client._resolve_url(endpoint)
    headers = client._context_headers()
    # Don't set Content-Type — httpx adds the multipart boundary for us.
    headers.pop("Content-Type", None)

    files = {"file": (file_path.name, file_path.read_bytes(), "application/octet-stream")}

    try:
        response = httpx.request(
            method="POST",
            url=url,
            files=files,
            data=form_fields,
            headers=headers,
            timeout=120.0,  # generous — pipeline of 100s of ops still completes well within this
        )
    except httpx.RequestError as exc:
        return None, f"network error: {exc}"

    if response.status_code == 401:
        return None, "auth failed (check SOURCE_PARTS_API_KEY)"
    if response.status_code == 429:
        return None, "rate limit exceeded"
    if response.status_code >= 400:
        try:
            err = response.json().get("error", response.text[:300])
        except Exception:  # noqa: BLE001
            err = response.text[:300]
        return None, f"API error {response.status_code}: {err}"

    if expect_json:
        try:
            return response.json(), None
        except Exception as exc:  # noqa: BLE001
            return None, f"unexpected non-JSON response: {exc}"
    return response.content, None


def _write_result(content: bytes, base_name: str, ext: str) -> Path:
    """Write binary CAD result to a unique temp path and return it."""
    fd, name = tempfile.mkstemp(prefix=f"{TMP_PREFIX}{base_name}-", suffix=f".{ext}")
    with open(fd, "wb") as fh:
        fh.write(content)
    return Path(name)


def register_cad_tools(mcp: FastMCP) -> None:
    """Register /v1/cad/step/* MCP tools with the FastMCP server."""

    @mcp.tool()
    @with_user_context
    async def cad_inspect_step(file_path: str) -> dict[str, Any]:
        """Inspect a STEP / BREP / STL file and return its geometry summary.

        Hits POST /v1/cad/step/inspect (synchronous, sub-second for typical
        product files).

        Args:
            file_path: Local path to a .step / .stp / .brep / .stl file
                (<=100 MB).

        Returns:
            { success, bounding_box: {x_min/max/len, y_..., z_..., center},
              topology: {solids, shells, faces, edges, vertices},
              volume_mm3, center_of_mass: [x, y, z] }
        """
        path, err = _validate_local_file(file_path)
        if err:
            return {"success": False, "error": err}
        payload, err = _upload_to_cad_endpoint(
            "/v1/cad/step/inspect",
            path,
            form_fields={},
            expect_json=True,
        )
        if err:
            return {"success": False, "error": err}
        if not isinstance(payload, dict) or payload.get("status") != "success":
            return {"success": False, "error": "unexpected response shape", "raw": payload}
        data = payload.get("data", {})
        return {
            "success": True,
            "bounding_box": data.get("bounding_box"),
            "topology": data.get("topology"),
            "volume_mm3": data.get("volume_mm3"),
            "center_of_mass": data.get("center_of_mass"),
        }

    @mcp.tool()
    @with_user_context
    async def cad_modify_step(
        file_path: str,
        operations: list[dict[str, Any]],
        output_format: str = "step",
    ) -> dict[str, Any]:
        """Apply a chain of parametric operations to a STEP/BREP file.

        Hits POST /v1/cad/step/pipeline. The result is written to a local
        temp file and the path is returned — chain calls by passing the
        previous output_path back in.

        Operation kinds supported (see Source Parts API docs for params):
            translate, rotate, drill, boss, fillet, chamfer,
            cut, union, intersect, mirror_y, linear_pattern

        Example — drill four corner holes:
            cad_modify_step(
                file_path="/tmp/plate.step",
                operations=[
                    {"kind": "drill", "radius": 1.35, "depth": 10, "at": [57.59, 43.90, 0]},
                    {"kind": "drill", "radius": 1.35, "depth": 10, "at": [124.59, 43.90, 0]},
                    {"kind": "drill", "radius": 1.35, "depth": 10, "at": [57.59, 140.90, 0]},
                    {"kind": "drill", "radius": 1.35, "depth": 10, "at": [124.59, 140.90, 0]},
                ],
                output_format="step",
            )

        Args:
            file_path: Local path to the input file (<=100 MB).
            operations: Non-empty list of operation dicts (each with a "kind"
                field plus op-specific params). Max 256 ops per call.
            output_format: One of step | stl | obj | amf | dxf | gltf.
                Defaults to "step".

        Returns:
            { success, output_path, output_format, size_bytes }
        """
        path, err = _validate_local_file(file_path)
        if err:
            return {"success": False, "error": err}

        if not isinstance(operations, list) or not operations:
            return {"success": False, "error": "operations must be a non-empty list"}
        if len(operations) > 256:
            return {"success": False, "error": f"too many operations: {len(operations)} > 256"}

        fmt = output_format.lower()
        if fmt not in OUTPUT_FORMATS:
            return {"success": False, "error": f"output_format must be one of: {sorted(OUTPUT_FORMATS)}"}

        pipeline_doc = {"operations": operations, "output_format": fmt}
        payload, err = _upload_to_cad_endpoint(
            "/v1/cad/step/pipeline",
            path,
            form_fields={"pipeline": json.dumps(pipeline_doc)},
            expect_json=False,
        )
        if err:
            return {"success": False, "error": err}
        out_path = _write_result(payload, path.stem, fmt)
        return {
            "success": True,
            "output_path": str(out_path),
            "output_format": fmt,
            "size_bytes": len(payload),
        }

    @mcp.tool()
    @with_user_context
    async def cad_convert_step(
        file_path: str,
        target_format: str,
    ) -> dict[str, Any]:
        """Convert a CAD file between formats (STEP ↔ STL / OBJ / glTF / AMF / DXF).

        Hits POST /v1/cad/step/convert. Result written to a local temp file.

        Args:
            file_path: Local path to .step/.stp/.brep/.stl file (<=100 MB).
            target_format: One of step | stl | obj | amf | dxf | gltf.

        Returns:
            { success, output_path, target_format, size_bytes }
        """
        path, err = _validate_local_file(file_path)
        if err:
            return {"success": False, "error": err}
        fmt = target_format.lower()
        if fmt not in OUTPUT_FORMATS:
            return {"success": False, "error": f"target_format must be one of: {sorted(OUTPUT_FORMATS)}"}

        payload, err = _upload_to_cad_endpoint(
            "/v1/cad/step/convert",
            path,
            form_fields={"target_format": fmt},
            expect_json=False,
        )
        if err:
            return {"success": False, "error": err}
        out_path = _write_result(payload, path.stem, fmt)
        return {
            "success": True,
            "output_path": str(out_path),
            "target_format": fmt,
            "size_bytes": len(payload),
        }
