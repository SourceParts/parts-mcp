"""
Altium→KiCad ERC repair MCP tools.

Mirrors the `parts sch {check,clean,libsync,snap}` CLI surface and
the RFC at parts.sh/docs/sch-erc-tools.md §MCP Tools.

  sch_erc_categorize    — parse kicad-cli ERC JSON, group by type (local)
  sch_pin_position      — compute absolute pin coord from placement (local, pure math)
  sch_check_structure   — validate .kicad_sch via /v1/sch/check
  sch_remove_wires      — strip (wire ...) blocks by UUID via /v1/sch/clean
  sch_libsync           — consolidate lib_symbols from sub-sheets via /v1/sch/libsync

The HTTP-backed tools call api.source.parts/v1/* via the existing
SourcePartsClient (api_client.get_client). The local-only tools
replicate the same logic as the server's
API/processors/cad/kicad_sch_processor.py so an agent can
categorize/compute without a round-trip.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

import httpx
from fastmcp import FastMCP

# api_client is imported lazily inside _sch_v1_post so the
# local-only tools (sch_erc_categorize, sch_pin_position) can be
# imported and unit-tested without pulling in the full HTTP stack.


# ----- local helpers -----


def _categorize_erc(report_bytes: bytes) -> dict[str, Any]:
    """Parse a kicad-cli ERC JSON report into {total, by_type, by_sheet}.

    Mirror of API/processors/cad/kicad_sch_processor.py
    parse_erc_report — keep in sync.
    """
    data = json.loads(report_bytes)
    violations = data.get("violations", []) or []
    by_type: dict[str, dict] = {}
    by_sheet: dict[str, int] = {}

    for v in violations:
        vtype = v.get("type", "unknown")
        descr = v.get("description")
        items = v.get("items", []) or []
        if vtype not in by_type:
            by_type[vtype] = {
                "count": 0,
                "uuids": [],
                "sample_description": descr,
            }
        for it in items:
            uuid = it.get("uuid")
            if uuid:
                by_type[vtype]["uuids"].append(uuid)
                by_type[vtype]["count"] += 1
        sheet = v.get("sheet") or data.get("source", {}).get("sheet")
        if sheet:
            by_sheet[sheet] = by_sheet.get(sheet, 0) + 1

    total = sum(t["count"] for t in by_type.values())
    out: dict[str, Any] = {"total": total, "by_type": by_type}
    if by_sheet:
        out["by_sheet"] = by_sheet
    return out


def _compute_pin_position(
    sym_x: float,
    sym_y: float,
    sym_angle: float,
    pin_lib_x: float,
    pin_lib_y: float,
) -> tuple[float, float]:
    """Compute absolute schematic coord of a component pin.

    Formula (RFC §sch_pin_position):
      abs = rotate_CW(sym_angle, negate_Y(pin_lib_pos)) + sym_pos
      negate_Y(x, y) = (x, -y)
      CW by θ:   (x, y) → (x·cosθ + y·sinθ, -x·sinθ + y·cosθ)

    KiCad schematic uses Y-down coords; negate the lib Y first.
    """
    # negate Y on lib pin
    px, py = pin_lib_x, -pin_lib_y
    # CW rotation by sym_angle degrees
    theta = math.radians(sym_angle)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    rx = px * cos_t + py * sin_t
    ry = -px * sin_t + py * cos_t
    return (sym_x + rx, sym_y + ry)


def _sch_v1_post(
    endpoint: str,
    files: list[tuple[str, tuple[str, bytes, str]]],
    form_fields: dict[str, str] | None = None,
) -> dict[str, Any]:
    """POST to api.source.parts/v1/<endpoint> with multipart files.

    Uses httpx directly because the shared client._make_upload_request
    only supports a single file under the field name 'file', while
    these endpoints expect specific field names + sub_sheets arrays.
    """
    from parts_mcp.utils.api_client import get_client

    client = get_client()
    url = client._resolve_url(endpoint)
    headers = {
        "Authorization": f"Bearer {client.api_key}",
        "User-Agent": "PARTS-MCP/1.0",
    }
    response = httpx.post(
        url,
        files=files,
        data=form_fields or {},
        headers=headers,
        timeout=120.0,
    )
    response.raise_for_status()
    result = response.json()
    if isinstance(result, dict) and result.get("status") == "success" and "data" in result:
        result = result["data"]
    return result


def _load_file_bytes(path: str) -> tuple[str, bytes]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"not found: {path}")
    return (p.name, p.read_bytes())


# ----- MCP tool registration -----


def register_sch_repair_tools(mcp: FastMCP) -> None:
    """Register Altium→KiCad ERC repair tools."""

    @mcp.tool()
    async def sch_erc_categorize(erc_report_path: str) -> dict[str, Any]:
        """Parse a kicad-cli ERC JSON report, group violations by type.

        Pure-local (no API call). Entry point for an agent deciding
        what to fix and in what order.

        Args:
            erc_report_path: Path to the kicad-cli ERC JSON report

        Returns: {total, by_type: {type: {count, uuids, sample_description}}, by_sheet?}
        """
        try:
            p = Path(erc_report_path)
            if not p.exists():
                return {"success": False, "error": f"not found: {erc_report_path}"}
            return {"success": True, **_categorize_erc(p.read_bytes())}
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"invalid JSON: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    async def sch_pin_position(
        sym_x: float,
        sym_y: float,
        sym_angle: float,
        pin_lib_x: float,
        pin_lib_y: float,
    ) -> dict[str, Any]:
        """Compute the absolute schematic coordinate of a component pin.

        Pure math — no file I/O, no API call. Encodes the
        sym_pos + rotate_CW(angle, negate_Y(pin_lib_pos)) formula
        that's easy to get wrong by hand.

        Args:
            sym_x: Symbol placement X (mm)
            sym_y: Symbol placement Y (mm)
            sym_angle: Symbol rotation angle in degrees (CW)
            pin_lib_x: Pin X in library symbol definition (mm)
            pin_lib_y: Pin Y in library symbol definition (mm)

        Returns: {abs_x, abs_y, description}
        """
        try:
            abs_x, abs_y = _compute_pin_position(
                sym_x, sym_y, sym_angle, pin_lib_x, pin_lib_y
            )
            return {
                "success": True,
                "abs_x": abs_x,
                "abs_y": abs_y,
                "description": f"Wire endpoint must be exactly at ({abs_x:.4f}, {abs_y:.4f}) to connect to this pin",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    async def sch_check_structure(schematic_path: str) -> dict[str, Any]:
        """Validate structural integrity of a .kicad_sch file.

        Uploads to /v1/sch/check. Use this before and after edits to
        confirm the file is intact (paren balance, no premature close,
        no malformed placed-symbol blocks).

        Args:
            schematic_path: Path to .kicad_sch to validate
        """
        try:
            name, data = _load_file_bytes(schematic_path)
            result = _sch_v1_post(
                "sch/check",
                files=[("schematic", (name, data, "application/octet-stream"))],
            )
            return {"success": True, **result}
        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"API error {e.response.status_code}: {e.response.text[:300]}",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    async def sch_remove_wires(
        schematic_path: str,
        uuids: list[str],
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Remove (wire ...) blocks by UUID from a .kicad_sch.

        Uploads to /v1/sch/clean with an explicit UUID list. The
        server verifies paren balance after removal and refuses to
        return a broken file (returns HTTP 422 instead). On success,
        writes the modified file back to schematic_path (unless
        dry_run).

        Args:
            schematic_path: Path to .kicad_sch to modify
            uuids: List of wire UUIDs to remove
            dry_run: If true, don't write the modified file
        """
        try:
            name, data = _load_file_bytes(schematic_path)
            form = {"uuids": ",".join(uuids)}
            if dry_run:
                form["dry_run"] = "true"
            result = _sch_v1_post(
                "sch/clean",
                files=[("schematic", (name, data, "application/octet-stream"))],
                form_fields=form,
            )
            files_out = result.get("files", []) or []
            written: list[str] = []
            if not dry_run:
                import base64

                for fr in files_out:
                    b64 = fr.get("content_b64")
                    if not b64:
                        continue
                    out_data = base64.b64decode(b64)
                    Path(schematic_path).write_bytes(out_data)
                    written.append(schematic_path)
            return {
                "success": True,
                "removed_count": result.get("total_removed", 0),
                "removed_uuids": result.get("removed_uuids", []),
                "not_found": result.get("not_found_uuids", []),
                "files_written": written,
                "dry_run": dry_run,
            }
        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"API error {e.response.status_code}: {e.response.text[:300]}",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    async def sch_libsync(
        root_path: str,
        sub_sheet_paths: list[str],
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """Consolidate lib_symbols from sub-sheets into root .kicad_sch.

        Uploads root + sub-sheets to /v1/sch/libsync. Resolves the
        lib_symbol_issues class of ERC violations.

        On name collision, the root's version is kept and the conflict
        is reported.

        Args:
            root_path: Path to root .kicad_sch
            sub_sheet_paths: List of sub-sheet .kicad_sch paths (≥1)
            output_path: Output path (default: overwrite root_path)
        """
        try:
            if not sub_sheet_paths:
                return {
                    "success": False,
                    "error": "at least one sub_sheet_paths entry required",
                }
            root_name, root_data = _load_file_bytes(root_path)
            files: list[tuple[str, tuple[str, bytes, str]]] = [
                ("root", (root_name, root_data, "application/octet-stream"))
            ]
            for sp in sub_sheet_paths:
                sname, sdata = _load_file_bytes(sp)
                files.append(
                    ("sub_sheets", (sname, sdata, "application/octet-stream"))
                )
            result = _sch_v1_post("sch/libsync", files=files)

            import base64

            out_b64 = result.get("root_schematic", "")
            written: str | None = None
            if out_b64:
                target = output_path or root_path
                Path(target).write_bytes(base64.b64decode(out_b64))
                written = target

            return {
                "success": True,
                "added_count": result.get("added_count", 0),
                "added_symbols": result.get("added", []),
                "conflicts": result.get("conflicts", []),
                "already_present": result.get("already_present", 0),
                "file_written": written,
            }
        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"API error {e.response.status_code}: {e.response.text[:300]}",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
