"""
KiCad Schematic Editing & Review — MCP Thin Client Tools

Uploads .kicad_sch files to the Source Parts API for server-side processing.
All editing, parsing, and rendering happens on the server. These tools are
thin wrappers that handle file I/O and return structured results.
"""
import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import get_client, with_user_context
from parts_mcp.utils.roles import require_role

logger = logging.getLogger(__name__)


def _find_sch_file(path: str) -> str:
    """Resolve a .kicad_sch file from a path, project, or directory."""
    p = Path(path)
    if p.suffix == ".kicad_sch":
        return str(p)
    if p.suffix == ".kicad_pro":
        sch = p.with_suffix(".kicad_sch")
        if sch.exists():
            return str(sch)
    if p.is_dir():
        schs = list(p.glob("*.kicad_sch"))
        if schs:
            return str(schs[0])
    raise FileNotFoundError(f"No .kicad_sch found at {path}")


def _find_pcb_file(path: str) -> str:
    """Resolve a .kicad_pcb file from a path, project, or directory."""
    p = Path(path)
    if p.suffix == ".kicad_pcb":
        return str(p)
    if p.suffix == ".kicad_pro":
        pcb = p.with_suffix(".kicad_pcb")
        if pcb.exists():
            return str(pcb)
    if p.is_dir():
        pcbs = list(p.glob("*.kicad_pcb"))
        if pcbs:
            return str(pcbs[0])
    raise FileNotFoundError(f"No .kicad_pcb found at {path}")


def _save_output(data: str, directory: str, filename: str) -> str:
    """Save output data to a file, return the path."""
    os.makedirs(directory, exist_ok=True)
    out_path = os.path.join(directory, filename)
    with open(out_path, "w") as f:
        f.write(data)
    return out_path


def _save_pdf(data_b64: str, directory: str, filename: str) -> str:
    """Decode base64 PDF and save, return the path."""
    os.makedirs(directory, exist_ok=True)
    out_path = os.path.join(directory, filename)
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(data_b64))
    return out_path


def register_kicad_sch_tools(mcp: FastMCP) -> None:
    """Register schematic editing and review tools."""

    # ── Schematic Editing Tools ──────────────────────────────────────────

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def edit_schematic_place(
        file_path: str,
        symbol: str,
        reference: str,
        x: float,
        y: float,
        properties: dict | None = None,
    ) -> dict[str, Any]:
        """Place a symbol instance in a KiCad schematic.

        Uploads the schematic to the API for server-side modification.
        Returns the unified diff of changes for review.

        Args:
            file_path: Path to .kicad_sch file or project directory
            symbol: KiCad lib_id (e.g., "Device:R")
            reference: Reference designator (e.g., "R1")
            x: X position in mm
            y: Y position in mm
            properties: Optional property overrides {"Value": "10K", ...}
        """
        try:
            sch_path = _find_sch_file(file_path)
            client = get_client()

            with open(sch_path, "rb") as f:
                sch_data = f.read()

            params = {"symbol": symbol, "ref": reference,
                      "x": x, "y": y, "properties": properties or {}}

            result = client._make_upload_request(
                "eda/schematic/place",
                file_data=sch_data,
                filename=os.path.basename(sch_path),
                form_fields={"params": json.dumps(params)},
            )

            return {
                "success": True,
                "summary": f"Placed {symbol} as {reference} at ({x}, {y})",
                "diff_lines": result.get("diff_lines", 0),
                "diff": result.get("diff", ""),
                "next_step": "Review the diff. Use edit_schematic_wire to connect the symbol.",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def edit_schematic_wire(
        file_path: str,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
    ) -> dict[str, Any]:
        """Add a wire segment between two points in a schematic.

        Args:
            file_path: Path to .kicad_sch file
            start_x, start_y: Wire start coordinates (mm)
            end_x, end_y: Wire end coordinates (mm)
        """
        try:
            sch_path = _find_sch_file(file_path)
            client = get_client()

            with open(sch_path, "rb") as f:
                sch_data = f.read()

            params = {"start_x": start_x, "start_y": start_y,
                      "end_x": end_x, "end_y": end_y}

            result = client._make_upload_request(
                "eda/schematic/wire",
                file_data=sch_data,
                filename=os.path.basename(sch_path),
                form_fields={"params": json.dumps(params)},
            )

            return {
                "success": True,
                "summary": f"Added wire from ({start_x},{start_y}) to ({end_x},{end_y})",
                "diff_lines": result.get("diff_lines", 0),
                "diff": result.get("diff", ""),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def edit_schematic_value(
        file_path: str,
        reference: str,
        property_name: str,
        new_value: str,
    ) -> dict[str, Any]:
        """Update a component property value in a schematic.

        Args:
            file_path: Path to .kicad_sch file
            reference: Component reference designator (e.g., "R47")
            property_name: Property to update (e.g., "Value", "Footprint")
            new_value: New value to set
        """
        try:
            sch_path = _find_sch_file(file_path)
            client = get_client()

            with open(sch_path, "rb") as f:
                sch_data = f.read()

            params = {"ref": reference, "property": property_name,
                      "new_value": new_value}

            result = client._make_upload_request(
                "eda/schematic/annotate",
                file_data=sch_data,
                filename=os.path.basename(sch_path),
                form_fields={"params": json.dumps(params)},
            )

            return {
                "success": True,
                "summary": f"Updated {reference}.{property_name} = {new_value}",
                "diff_lines": result.get("diff_lines", 0),
                "diff": result.get("diff", ""),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def edit_schematic_remove(
        file_path: str,
        reference: str,
    ) -> dict[str, Any]:
        """Remove a component from a schematic by reference designator.

        Args:
            file_path: Path to .kicad_sch file
            reference: Component reference to remove (e.g., "R47")
        """
        try:
            sch_path = _find_sch_file(file_path)
            client = get_client()

            with open(sch_path, "rb") as f:
                sch_data = f.read()

            params = {"ref": reference}

            result = client._make_upload_request(
                "eda/schematic/remove",
                file_data=sch_data,
                filename=os.path.basename(sch_path),
                form_fields={"params": json.dumps(params)},
            )

            return {
                "success": True,
                "summary": f"Removed {reference} from schematic",
                "diff_lines": result.get("diff_lines", 0),
                "diff": result.get("diff", ""),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Schematic Review Tools ───────────────────────────────────────────

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def review_schematic(
        old_file_path: str,
        new_file_path: str,
    ) -> dict[str, Any]:
        """Compare two schematic versions and return structured diff.

        Shows added/removed components, changed values, and net changes.

        Args:
            old_file_path: Path to the old/baseline .kicad_sch file
            new_file_path: Path to the new/modified .kicad_sch file
        """
        try:
            old_path = _find_sch_file(old_file_path)
            new_path = _find_sch_file(new_file_path)
            client = get_client()

            with open(old_path, "rb") as f:
                old_data = f.read()
            with open(new_path, "rb") as f:
                new_data = f.read()

            # Upload both files — API expects old_file and new_file
            import httpx
            url = client.base_url.rstrip('/') + '/eda/schematic/diff'
            headers = {
                "Authorization": f"Bearer {client.api_key}",
                "User-Agent": "PARTS-MCP/1.0",
            }
            files = {
                "old_file": (os.path.basename(old_path), old_data, "application/octet-stream"),
                "new_file": (os.path.basename(new_path), new_data, "application/octet-stream"),
            }
            response = httpx.post(url, files=files, headers=headers, timeout=60)
            response.raise_for_status()
            result = response.json()
            if result.get("status") == "success":
                result = result["data"]

            changes = result.get("changes", {})
            added = len(changes.get("added_components", []))
            removed = len(changes.get("removed_components", []))
            changed = len(changes.get("changed_properties", []))

            return {
                "success": True,
                "summary": f"Diff: +{added} components, -{removed} components, ~{changed} property changes",
                "changes": changes,
                "unified_diff_lines": result.get("unified_diff_lines", 0),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def render_schematic(
        file_path: str,
        save_to: str | None = None,
    ) -> dict[str, Any]:
        """Render a schematic as PDF for visual review.

        Uses kicad-cli on the server to export the schematic as a PDF.

        Args:
            file_path: Path to .kicad_sch file
            save_to: Optional directory to save the PDF locally
        """
        try:
            sch_path = _find_sch_file(file_path)
            client = get_client()

            with open(sch_path, "rb") as f:
                sch_data = f.read()

            result = client._make_upload_request(
                "eda/schematic/render",
                file_data=sch_data,
                filename=os.path.basename(sch_path),
            )

            pdf_path = None
            if result.get("pdf_base64") and save_to:
                pdf_path = _save_pdf(
                    result["pdf_base64"],
                    save_to,
                    f"{Path(sch_path).stem}.pdf",
                )

            return {
                "success": True,
                "summary": f"Rendered schematic ({result.get('pdf_size_bytes', 0)} bytes)",
                "pdf_path": pdf_path,
                "pdf_size_bytes": result.get("pdf_size_bytes", 0),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Reroute Tool ─────────────────────────────────────────────────────

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def suggest_reroute(
        file_path: str,
        nets: list[str],
        grid_step: float = 0.25,
        layer: str = "F.Cu",
        width: float = 0.25,
    ) -> dict[str, Any]:
        """Suggest routing paths for disconnected nets after rip-up.

        Runs an A* pathfinder on the server and returns suggested track
        segments as KiCad S-expressions for operator review.

        Args:
            file_path: Path to .kicad_pcb file
            nets: List of net names to route
            grid_step: Routing grid resolution in mm (default 0.25)
            layer: Copper layer to route on (default "F.Cu")
            width: Track width in mm (default 0.25)
        """
        try:
            pcb_path = _find_pcb_file(file_path)
            client = get_client()

            with open(pcb_path, "rb") as f:
                pcb_data = f.read()

            params = {"nets": nets, "grid_step": grid_step,
                      "layer": layer, "width": width}

            result = client._make_upload_request(
                "eda/reroute/suggest",
                file_data=pcb_data,
                filename=os.path.basename(pcb_path),
                form_fields={"params": json.dumps(params)},
            )

            successful = result.get("successful_nets", 0)
            failed = result.get("failed_nets", 0)
            total_segs = result.get("total_segments", 0)

            return {
                "success": True,
                "summary": f"Routed {successful}/{successful + failed} nets, {total_segs} segments suggested",
                "results": result.get("results", []),
                "kicad_segments": result.get("kicad_segments", ""),
                "next_step": "Review suggested segments. Apply to PCB file if acceptable.",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
