"""
KiCad-Ctrl: AOI-style operator-approved PCB editing pipeline.

Thin client MCP tools that upload .kicad_pcb files to the Source Parts API
and return results for operator review. Every step requires explicit approval
before proceeding to the next.

Pipeline:
  1. kicad_ctrl_analyze      — identify affected nets
  2. kicad_ctrl_propose_ripup — enumerate tracks/vias to remove
  3. kicad_ctrl_execute_ripup — remove tracks, return diff to apply locally
  4. kicad_ctrl_validate      — run DRC on modified board
  5. kicad_ctrl_export        — export gerbers + drill + positions
"""
import base64
import logging
import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import get_client, with_user_context
from parts_mcp.utils.roles import require_role

logger = logging.getLogger(__name__)


def _find_pcb_file(project_path: str) -> str:
    """Find the .kicad_pcb file from a project path or direct file path."""
    p = Path(project_path)
    if p.suffix == ".kicad_pcb":
        return str(p)
    if p.suffix == ".kicad_pro":
        pcb = p.with_suffix(".kicad_pcb")
        if pcb.exists():
            return str(pcb)
    # Search in directory
    if p.is_dir():
        pcbs = list(p.glob("*.kicad_pcb"))
        if pcbs:
            return str(pcbs[0])
    raise FileNotFoundError(f"No .kicad_pcb found at {project_path}")


def _save_pdf(data_b64: str | None, output_dir: str, name: str) -> str | None:
    """Decode base64 PDF and save to output directory."""
    if not data_b64:
        return None
    out_path = os.path.join(output_dir, name)
    os.makedirs(output_dir, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(data_b64))
    return out_path


def _find_sch_file(project_path: str) -> str:
    """Find the top-level .kicad_sch file from a project path."""
    p = Path(project_path)
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
    raise FileNotFoundError(f"No .kicad_sch found at {project_path}")


def register_kicad_ctrl_tools(mcp: FastMCP) -> None:
    """Register KiCad-Ctrl pipeline tools with the MCP server."""

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def kicad_ctrl_erc(
        project_path: str,
    ) -> dict[str, Any]:
        """Station 0a: Run Electrical Rules Check on the schematic.

        Uploads the .kicad_sch to the API, which runs kicad-cli sch erc
        and returns a violation report + schematic PDF for review.

        IMPORTANT: Review ERC results before proceeding to netlist diff.

        Args:
            project_path: Path to .kicad_pro, .kicad_sch, or project directory

        Returns:
            ERC report with violation counts and schematic PDF path.
        """
        try:
            sch_path = _find_sch_file(project_path)
            client = get_client()

            with open(sch_path, "rb") as f:
                sch_data = f.read()

            result = client.upload_file(
                "eda/erc",
                file_data=sch_data,
                filename=os.path.basename(sch_path),
                content_type="application/octet-stream",
            )

            # Save schematic PDF locally
            pdf_path = None
            if result.get("schematic_pdf"):
                output_dir = os.path.join(os.path.dirname(sch_path), "eda_ctrl_output")
                pdf_path = _save_pdf(result["schematic_pdf"], output_dir, "schematic.pdf")

            errors = result.get("error_count", 0)
            warnings = result.get("warning_count", 0)
            status = "PASS" if errors == 0 else "FAIL"

            return {
                "success": True,
                "status": status,
                "error_count": errors,
                "warning_count": warnings,
                "total_violations": result.get("total_violations", 0),
                "violations": result.get("violations", [])[:20],
                "schematic_pdf": pdf_path,
                "summary": f"ERC {status}: {errors} errors, {warnings} warnings.",
                "next_step": "Review ERC results. If passing, call kicad_ctrl_netlist_diff to compare connectivity changes."
                if errors == 0 else "Fix ERC errors in the schematic, then run kicad_ctrl_erc again.",
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def kicad_ctrl_netlist_diff(
        project_path: str,
        old_schematic: str | None = None,
    ) -> dict[str, Any]:
        """Station 0b: Compare old and new schematic netlists.

        Shows what connectivity changed — added/removed/modified nets and
        components. This tells you exactly which PCB traces need rerouting.

        IMPORTANT: Review the diff before proceeding to PCB analysis.

        Args:
            project_path: Path to the NEW .kicad_sch (current version)
            old_schematic: Path to the OLD .kicad_sch (previous version).
                          If not provided, uses git to find the previous version.

        Returns:
            Net and component diff with added/removed/changed details.
        """
        try:
            new_sch_path = _find_sch_file(project_path)
            client = get_client()

            # If no old schematic provided, try git for the previous version
            if not old_schematic:
                import subprocess as sp
                try:
                    old_content = sp.run(
                        ["git", "show", f"HEAD~1:{os.path.relpath(new_sch_path)}"],
                        capture_output=True, text=True,
                        cwd=os.path.dirname(new_sch_path),
                    )
                    if old_content.returncode == 0:
                        # Write to temp file
                        old_schematic = new_sch_path + ".old"
                        with open(old_schematic, "w") as f:
                            f.write(old_content.stdout)
                except Exception:
                    pass

            if not old_schematic or not os.path.exists(old_schematic):
                return {"error": "Could not find old schematic. Provide --old-schematic path or ensure git history exists."}

            with open(old_schematic, "rb") as f:
                old_data = f.read()
            with open(new_sch_path, "rb") as f:
                new_data = f.read()

            result = client.upload_files(
                "eda/netlist/diff",
                files={
                    "old_file": (os.path.basename(old_schematic), old_data, "application/octet-stream"),
                    "new_file": (os.path.basename(new_sch_path), new_data, "application/octet-stream"),
                },
            )

            nets = result.get("nets", {})
            comps = result.get("components", {})

            summary_lines = [result.get("summary", "")]
            if nets.get("changed_detail"):
                summary_lines.append("\nChanged nets:")
                for name, info in list(nets["changed_detail"].items())[:10]:
                    added = info.get("added_connections", [])
                    removed = info.get("removed_connections", [])
                    summary_lines.append(f"  {name}: +{len(added)} -{len(removed)} connections")

            return {
                "success": True,
                "nets_added": nets.get("added", 0),
                "nets_removed": nets.get("removed", 0),
                "nets_changed": nets.get("changed", 0),
                "components_added": comps.get("added", 0),
                "components_removed": comps.get("removed", 0),
                "components_changed": comps.get("changed", 0),
                "changed_nets": nets.get("changed_detail", {}),
                "summary": "\n".join(summary_lines),
                "next_step": "Review connectivity changes. The changed nets are the ones that need PCB rerouting. Call kicad_ctrl_analyze with those net names.",
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def kicad_ctrl_analyze(
        project_path: str,
        ecn_id: str | None = None,
        net_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """Station 1: Analyze a PCB for affected nets.

        Uploads the .kicad_pcb to the API, which parses all nets and returns
        an inventory of tracks/vias per net, plus a highlight overlay PDF.

        IMPORTANT: Review the results before proceeding. Ask the operator
        to approve before calling kicad_ctrl_propose_ripup.

        Args:
            project_path: Path to .kicad_pro, .kicad_pcb, or project directory
            ecn_id: Optional ECN identifier to extract affected nets
            net_names: Optional explicit list of net names to analyze

        Returns:
            Net inventory with track/via counts and highlight PDF path.
        """
        try:
            pcb_path = _find_pcb_file(project_path)
            client = get_client()

            with open(pcb_path, "rb") as f:
                pcb_data = f.read()

            form_data = {}
            if ecn_id:
                form_data["ecn_id"] = ecn_id
            if net_names:
                import json
                form_data["net_names_json"] = json.dumps(net_names)

            result = client.upload_file(
                "eda/analyze",
                file_data=pcb_data,
                filename=os.path.basename(pcb_path),
                content_type="application/octet-stream",
                options=form_data,
            )

            # Save highlight PDF locally if returned
            pdf_path = None
            if result.get("highlight_pdf"):
                output_dir = os.path.join(os.path.dirname(pcb_path), "eda_ctrl_output")
                pdf_path = _save_pdf(
                    result["highlight_pdf"], output_dir, "analyze_highlight.pdf"
                )

            nets = result.get("nets", {})
            summary_lines = []
            for name, info in nets.items():
                summary_lines.append(
                    f"  {name}: {info['tracks']} tracks, {info['vias']} vias "
                    f"on {', '.join(info.get('layers', []))}"
                )

            return {
                "success": True,
                "pcb_file": pcb_path,
                "nets": nets,
                "total_nets": result.get("total_nets", 0),
                "highlight_pdf": pdf_path,
                "summary": f"Found {len(nets)} nets with traces:\n" + "\n".join(summary_lines),
                "next_step": "Review the affected nets. If correct, call kicad_ctrl_propose_ripup with the net names to remove.",
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def kicad_ctrl_propose_ripup(
        project_path: str,
        net_names: list[str],
    ) -> dict[str, Any]:
        """Station 2: Propose rip-up — enumerate what would be removed.

        IMPORTANT: Review the proposal before proceeding. Ask the operator
        to approve before calling kicad_ctrl_execute_ripup.

        Args:
            project_path: Path to .kicad_pro, .kicad_pcb, or project directory
            net_names: Net names to rip up

        Returns:
            Track/via inventory per net with totals.
        """
        try:
            pcb_path = _find_pcb_file(project_path)
            client = get_client()

            with open(pcb_path, "rb") as f:
                pcb_data = f.read()

            import json
            result = client.upload_file(
                "eda/ripup/propose",
                file_data=pcb_data,
                filename=os.path.basename(pcb_path),
                content_type="application/octet-stream",
                options={"net_names_json": json.dumps(net_names)},
            )

            proposal = result.get("proposal", {})
            total_t = result.get("total_tracks", 0)
            total_v = result.get("total_vias", 0)

            return {
                "success": True,
                "proposal": proposal,
                "total_tracks": total_t,
                "total_vias": total_v,
                "summary": f"Will remove {total_t} tracks and {total_v} vias across {len(net_names)} nets.",
                "next_step": "If approved, call kicad_ctrl_execute_ripup to perform the rip-up and receive a diff.",
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def kicad_ctrl_execute_ripup(
        project_path: str,
        net_names: list[str],
        apply_diff: bool = False,
    ) -> dict[str, Any]:
        """Station 3: Execute rip-up — remove tracks and return a diff.

        The API removes the tracks/vias and returns a unified diff. If apply_diff
        is True, the diff is applied to the local .kicad_pcb file. Otherwise, the
        diff is returned for review.

        IMPORTANT: After applying, open the PCB in KiCad for manual rerouting.

        Args:
            project_path: Path to .kicad_pro, .kicad_pcb, or project directory
            net_names: Net names to rip up
            apply_diff: If True, apply the diff to the local file

        Returns:
            Unified diff text + removal stats.
        """
        try:
            pcb_path = _find_pcb_file(project_path)
            client = get_client()

            with open(pcb_path, "rb") as f:
                pcb_data = f.read()

            import json
            result = client.upload_file(
                "eda/ripup/execute",
                file_data=pcb_data,
                filename=os.path.basename(pcb_path),
                content_type="application/octet-stream",
                options={"net_names_json": json.dumps(net_names)},
            )

            diff_text = result.get("diff", "")
            tracks_removed = result.get("tracks_removed", 0)
            vias_removed = result.get("vias_removed", 0)

            applied = False
            if apply_diff and diff_text:
                # Apply diff using patch command
                import subprocess
                proc = subprocess.run(
                    ["patch", "-p1", "--no-backup-if-mismatch"],
                    input=diff_text, capture_output=True, text=True,
                    cwd=os.path.dirname(pcb_path),
                )
                applied = proc.returncode == 0
                if not applied:
                    logger.warning(f"patch failed: {proc.stderr}")

            return {
                "success": True,
                "diff": diff_text if not apply_diff else "(applied locally)",
                "diff_lines": result.get("diff_lines", 0),
                "tracks_removed": tracks_removed,
                "vias_removed": vias_removed,
                "applied": applied,
                "summary": f"Removed {tracks_removed} tracks and {vias_removed} vias."
                + (" Diff applied to local file." if applied else " Diff returned for review."),
                "next_step": "Open the PCB in KiCad, manually reroute the affected nets, save, then call kicad_ctrl_validate.",
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def kicad_ctrl_validate(
        project_path: str,
    ) -> dict[str, Any]:
        """Station 5: Run DRC validation on the PCB.

        IMPORTANT: Review DRC results before proceeding to export.

        Args:
            project_path: Path to .kicad_pro, .kicad_pcb, or project directory

        Returns:
            DRC report with violation counts and details.
        """
        try:
            pcb_path = _find_pcb_file(project_path)
            client = get_client()

            with open(pcb_path, "rb") as f:
                pcb_data = f.read()

            result = client.upload_file(
                "eda/drc",
                file_data=pcb_data,
                filename=os.path.basename(pcb_path),
                content_type="application/octet-stream",
            )

            errors = result.get("error_count", 0)
            warnings = result.get("warning_count", 0)
            unconnected = result.get("unconnected_count", 0)

            status = "PASS" if errors == 0 else "FAIL"

            return {
                "success": True,
                "status": status,
                "error_count": errors,
                "warning_count": warnings,
                "unconnected_count": unconnected,
                "violations": result.get("violations", [])[:20],
                "summary": f"DRC {status}: {errors} errors, {warnings} warnings, {unconnected} unconnected nets.",
                "next_step": "If DRC passes, call kicad_ctrl_export to generate gerbers." if errors == 0
                else "Fix DRC errors in KiCad, then run kicad_ctrl_validate again.",
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def kicad_ctrl_export(
        project_path: str,
        output_dir: str | None = None,
    ) -> dict[str, Any]:
        """Station 6: Export gerbers, drill files, and positions.

        Downloads a ZIP from the API containing all fabrication files.

        Args:
            project_path: Path to .kicad_pro, .kicad_pcb, or project directory
            output_dir: Local directory to save the export (default: CAM/ next to PCB)

        Returns:
            Path to the exported ZIP and file list.
        """
        try:
            pcb_path = _find_pcb_file(project_path)
            client = get_client()

            with open(pcb_path, "rb") as f:
                pcb_data = f.read()

            # This endpoint returns a ZIP binary
            zip_data = client.upload_file_raw(
                "eda/export",
                file_data=pcb_data,
                filename=os.path.basename(pcb_path),
                content_type="application/octet-stream",
            )

            # Determine output directory
            if not output_dir:
                from datetime import datetime
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_dir = os.path.join(
                    os.path.dirname(pcb_path), "..", "CAM", f"{ts}_export"
                )

            os.makedirs(output_dir, exist_ok=True)
            zip_path = os.path.join(output_dir, "gerbers.zip")
            with open(zip_path, "wb") as f:
                f.write(zip_data)

            # Extract
            import zipfile
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(output_dir)
                file_list = zf.namelist()

            return {
                "success": True,
                "output_dir": output_dir,
                "zip_path": zip_path,
                "files": file_list,
                "file_count": len(file_list),
                "summary": f"Exported {len(file_list)} files to {output_dir}",
                "next_step": "Review the gerber files and commit to repo if ready.",
            }
        except Exception as e:
            return {"error": str(e)}
