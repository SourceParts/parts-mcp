"""
KiCad integration tools for working with KiCad projects.
"""
import json
import logging
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from parts_mcp.config import KICAD_SEARCH_PATHS
from parts_mcp.utils.bom_parser import analyze_bom_data, parse_bom_file
from parts_mcp.utils.kicad_utils import (
    extract_project_info,
    get_project_files,
    run_kicad_cli,
)
from parts_mcp.utils.kicad_utils import (
    find_kicad_projects as find_projects_util,
)
from parts_mcp.utils.kicad_utils import open_kicad_project as open_project_util
from parts_mcp.utils.netlist_parser import (
    NetlistParser,
    analyze_connectivity,
    extract_netlist_from_schematic,
)
from parts_mcp.utils.api_client import SourcePartsAPIError, get_client
from parts_mcp.utils.pcb_highlight import highlight_nets

logger = logging.getLogger(__name__)


def register_kicad_tools(mcp: FastMCP) -> None:
    """Register KiCad integration tools with the MCP server.

    Args:
        mcp: The FastMCP server instance
    """

    @mcp.tool()
    async def extract_bom_from_kicad(
        project_path: str
    ) -> dict[str, Any]:
        """Extract bill of materials from a KiCad project.

        Args:
            project_path: Path to KiCad project file (.kicad_pro)

        Returns:
            BOM data extracted from the project
        """
        try:
            path = Path(project_path)
            if not path.exists():
                return {"error": f"Project file not found: {project_path}"}

            if not path.suffix == ".kicad_pro":
                return {"error": "Please provide a .kicad_pro file"}

            # Get project files
            files = get_project_files(project_path)

            # Look for existing BOM files
            bom_results = []
            for file_type, file_path in files.items():
                if "bom" in file_type.lower() or (
                    file_path.endswith('.csv') and 'bom' in Path(file_path).stem.lower()
                ):
                    components, format_info = parse_bom_file(file_path)
                    if components:
                        analysis = analyze_bom_data(components)
                        bom_results.append({
                            "file": Path(file_path).name,
                            "format": format_info.get("detected_format", "unknown"),
                            "component_count": len(components),
                            "analysis": analysis
                        })

            # If no BOM found, try to generate one using KiCad CLI
            if not bom_results and "schematic" in files:
                logger.info("No BOM files found, attempting to generate using KiCad CLI")

                # Try to export BOM using CLI
                output_file = path.parent / f"{path.stem}_bom.csv"
                result = run_kicad_cli([
                    "sch", "export", "bom",
                    "--output", str(output_file),
                    files["schematic"]
                ])

                if result["success"] and output_file.exists():
                    components, format_info = parse_bom_file(str(output_file))
                    if components:
                        analysis = analyze_bom_data(components)
                        bom_results.append({
                            "file": output_file.name,
                            "format": "kicad_generated",
                            "component_count": len(components),
                            "analysis": analysis,
                            "generated": True
                        })

            if bom_results:
                return {
                    "project": path.name,
                    "bom_files": bom_results,
                    "total_files": len(bom_results),
                    "success": True
                }
            else:
                return {
                    "project": path.name,
                    "error": "No BOM files found and unable to generate",
                    "hint": "Export a BOM from KiCad or ensure schematic file exists"
                }

        except Exception as e:
            logger.error(f"Error extracting BOM: {e}")
            return {"error": str(e)}

    @mcp.tool()
    async def find_kicad_projects() -> dict[str, Any]:
        """Find KiCad projects in configured search paths.

        Returns:
            List of found KiCad projects
        """
        projects = find_projects_util()

        # Sort by modification time (newest first)
        projects.sort(key=lambda x: x.get('modified', 0), reverse=True)

        return {
            "projects": projects,
            "total": len(projects),
            "search_paths": KICAD_SEARCH_PATHS
        }

    @mcp.tool()
    async def match_components_to_parts(
        components: list[dict[str, Any]],
        auto_search: bool = True
    ) -> dict[str, Any]:
        """Match KiCad components to real parts.

        Args:
            components: List of components from KiCad
            auto_search: Whether to automatically search for parts

        Returns:
            Matched components with part suggestions
        """
        return {
            "components": components,
            "matched": 0,
            "unmatched": len(components),
            "suggestions": [],
            "message": "Component matching will be implemented"
        }

    @mcp.tool()
    async def analyze_kicad_project(
        project_path: str
    ) -> dict[str, Any]:
        """Analyze a KiCad project to extract detailed information.

        Args:
            project_path: Path to KiCad project file (.kicad_pro)

        Returns:
            Detailed project analysis
        """
        try:
            info = extract_project_info(project_path)

            # Add file counts
            info["file_counts"] = {
                "total": len(info["files"]),
                "schematics": sum(1 for f in info["files"].values() if f.endswith('.kicad_sch')),
                "pcbs": sum(1 for f in info["files"].values() if f.endswith('.kicad_pcb')),
                "data_files": sum(1 for f in info["files"].values()
                                if any(f.endswith(ext) for ext in ['.csv', '.pos', '.net']))
            }

            return info

        except Exception as e:
            logger.error(f"Error analyzing project: {e}")
            return {"error": str(e)}

    @mcp.tool()
    async def extract_netlist_from_project(
        project_path: str
    ) -> dict[str, Any]:
        """Extract netlist information from a KiCad project.

        Args:
            project_path: Path to KiCad project file (.kicad_pro)

        Returns:
            Netlist information
        """
        try:
            path = Path(project_path)
            if not path.exists():
                return {"error": f"Project file not found: {project_path}"}

            files = get_project_files(project_path)

            # Check for existing netlist file
            if "netlist_data" in files or "net" in files:
                netlist_file = files.get("netlist_data", files.get("net"))
                parser = NetlistParser(netlist_file)
                netlist_data = parser.parse()

                # Add connectivity analysis
                if "error" not in netlist_data:
                    netlist_data["analysis"] = analyze_connectivity(netlist_data)

                return netlist_data

            # Try to extract from schematic
            elif "schematic" in files:
                netlist_data = extract_netlist_from_schematic(files["schematic"])
                return netlist_data

            else:
                return {
                    "error": "No netlist or schematic file found",
                    "hint": "Generate a netlist from KiCad or ensure schematic exists"
                }

        except Exception as e:
            logger.error(f"Error extracting netlist: {e}")
            return {"error": str(e)}

    @mcp.tool()
    async def open_in_kicad(
        project_path: str
    ) -> dict[str, Any]:
        """Open a KiCad project in the KiCad application.

        Args:
            project_path: Path to KiCad project file

        Returns:
            Operation result
        """
        return open_project_util(project_path)

    @mcp.tool()
    async def highlight_net_traces(
        project_path: str,
        net_names: list[str],
        colors: dict[str, str] | None = None,
        mode: str = "both",
        output_dir: str | None = None,
    ) -> dict[str, Any]:
        """Highlight specific net traces on a PCB and generate PDF(s).

        Renders highlighted net traces as vector PDFs. Supports two output modes:
        - overlay: Full board with all traces in gray, highlighted nets in color
        - traces_only: Just the highlighted nets + board outline

        Args:
            project_path: Path to KiCad project directory or .kicad_pro/.kicad_pcb file
            net_names: Net names to highlight (e.g. ["nRF54_P", "nRF54_N"])
            colors: Optional color mapping {"net_name": "#rrggbb"}
            mode: "overlay", "traces_only", or "both" (default: "both")
            output_dir: Where to save PDFs (defaults to project dir)

        Returns:
            Result with file paths and metadata
        """
        try:
            result = await highlight_nets(
                project_path=project_path,
                net_names=net_names,
                colors=colors,
                mode=mode,
                output_dir=output_dir,
            )
            return result
        except Exception as e:
            logger.error(f"Error highlighting nets: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    async def convert_kicad_version(
        file_path: str,
        target_version: str,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """Convert a KiCad file to an older version.

        Downconverts .kicad_pcb, .kicad_sch, or project ZIP archives from
        KiCad 10 to version 7, 8, or 9 for fab shop compatibility.

        Rounded rectangles (gr_roundrect / fp_roundrect) introduced in KiCad 10
        are converted to right-angle rectangles. Hatched copper fills are removed.
        The file version header is updated to match the target version.

        Args:
            file_path: Path to .kicad_pcb, .kicad_sch, or .zip project archive
            target_version: Target version: "7", "8", or "9"
            output_path: Where to save the result (default: same dir, _v<N> suffix)

        Returns:
            Dict with success, output_path, and conversion summary
        """
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        if target_version not in ("7", "8", "9"):
            return {"success": False, "error": f"Invalid target_version '{target_version}'. Must be 7, 8, or 9"}

        file_data = path.read_bytes()

        try:
            client = get_client()
            result_bytes = client.convert_kicad_version(
                file_data=file_data,
                filename=path.name,
                target_version=target_version,
            )
        except SourcePartsAPIError as e:
            return {"success": False, "error": str(e)}

        if output_path:
            out = Path(output_path).expanduser().resolve()
        else:
            ext = path.suffix
            stem = path.stem
            out = path.with_name(f"{stem}_v{target_version}{ext}")

        out.write_bytes(result_bytes)

        return {
            "success": True,
            "output_path": str(out),
            "target_version": target_version,
            "source_file": str(path),
            "output_size_bytes": len(result_bytes),
        }

    @mcp.tool()
    async def convert_allegro(
        file_path: str,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """Convert a Cadence Allegro PCB board file to KiCad format.

        Imports a Cadence Allegro .brd binary file (versions 16-23) and
        converts it to a KiCad .kicad_pcb file. Uses KiCad 10's built-in
        Allegro importer — no Cadence software required.

        Board files only. Schematics are not supported. The .brd extension
        is also used by Eagle; KiCad auto-detects the format via magic bytes.

        Output is a ZIP archive containing the .kicad_pcb file and any
        extracted footprint libraries.

        Args:
            file_path: Path to Allegro .brd file or zip archive
            output_path: Where to save the output ZIP (default: <stem>_kicad.zip next to input)

        Returns:
            Dict with success, output_path, source_file, and output_size_bytes
        """
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        ext = path.suffix.lower()
        if ext not in (".brd", ".zip"):
            return {"success": False, "error": f"Expected .brd or .zip file, got {ext}"}

        file_data = path.read_bytes()

        try:
            client = get_client()
            result_bytes = client.convert_allegro(
                file_data=file_data,
                filename=path.name,
            )
        except SourcePartsAPIError as e:
            return {"success": False, "error": str(e)}

        if output_path:
            out = Path(output_path).expanduser().resolve()
        else:
            out = path.with_name(f"{path.stem}_kicad.zip")

        out.write_bytes(result_bytes)

        return {
            "success": True,
            "output_path": str(out),
            "source_file": str(path),
            "output_size_bytes": len(result_bytes),
        }

    @mcp.tool()
    async def convert_pads(
        file_path: str,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """Convert a PADS ASCII layout file to KiCad format.

        Imports a PADS ASCII .asc layout file using kicad-cli pcb import
        --format pads. Board files only — schematics are not supported.

        Output is a ZIP archive containing the .kicad_pcb file.

        Args:
            file_path: Path to PADS .asc file or zip archive
            output_path: Where to save the output ZIP (default: <stem>_kicad.zip next to input)

        Returns:
            Dict with success, output_path, source_file, and output_size_bytes
        """
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        ext = path.suffix.lower()
        if ext not in (".asc", ".zip"):
            return {"success": False, "error": f"Expected .asc or .zip file, got {ext}"}

        file_data = path.read_bytes()

        try:
            client = get_client()
            result_bytes = client.convert_pads(
                file_data=file_data,
                filename=path.name,
            )
        except SourcePartsAPIError as e:
            return {"success": False, "error": str(e)}

        if output_path:
            out = Path(output_path).expanduser().resolve()
        else:
            out = path.with_name(f"{path.stem}_kicad.zip")

        out.write_bytes(result_bytes)

        return {
            "success": True,
            "output_path": str(out),
            "source_file": str(path),
            "output_size_bytes": len(result_bytes),
        }

    @mcp.tool()
    async def convert_geda(
        file_path: str,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """Convert a gEDA PCB board file to KiCad format.

        Imports a gEDA .pcb board file using KiCad's pcbnew bindings.
        Board files only — schematic import is not available programmatically.

        Output is a ZIP archive containing the .kicad_pcb file.

        Args:
            file_path: Path to gEDA .pcb file or zip archive
            output_path: Where to save the output ZIP (default: <stem>_kicad.zip next to input)

        Returns:
            Dict with success, output_path, source_file, and output_size_bytes
        """
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        ext = path.suffix.lower()
        if ext not in (".pcb", ".zip"):
            return {"success": False, "error": f"Expected .pcb or .zip file, got {ext}"}

        file_data = path.read_bytes()

        try:
            client = get_client()
            result_bytes = client.convert_geda(
                file_data=file_data,
                filename=path.name,
            )
        except SourcePartsAPIError as e:
            return {"success": False, "error": str(e)}

        if output_path:
            out = Path(output_path).expanduser().resolve()
        else:
            out = path.with_name(f"{path.stem}_kicad.zip")

        out.write_bytes(result_bytes)

        return {
            "success": True,
            "output_path": str(out),
            "source_file": str(path),
            "output_size_bytes": len(result_bytes),
        }

    @mcp.tool()
    async def export_parts_to_kicad(
        parts: list[dict[str, Any]],
        output_path: str,
        format: str = "csv"
    ) -> dict[str, Any]:
        """Export parts data in KiCad-compatible format.

        Args:
            parts: List of parts to export
            output_path: Where to save the export
            format: Export format (csv, json)

        Returns:
            Export status
        """
        try:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)

            if format == "csv":
                # Create KiCad-compatible CSV
                import csv

                with open(path, 'w', newline='') as f:
                    # Define KiCad BOM headers
                    headers = [
                        'Reference', 'Value', 'Footprint', 'Datasheet',
                        'Manufacturer', 'MPN', 'Supplier', 'SPN',
                        'Quantity', 'Unit Price', 'Extended Price'
                    ]

                    writer = csv.DictWriter(f, fieldnames=headers)
                    writer.writeheader()

                    for part in parts:
                        row = {
                            'Reference': part.get('reference', ''),
                            'Value': part.get('value', ''),
                            'Footprint': part.get('footprint', ''),
                            'Datasheet': part.get('datasheet', ''),
                            'Manufacturer': part.get('manufacturer', ''),
                            'MPN': part.get('part_number', ''),
                            'Supplier': part.get('supplier', ''),
                            'SPN': part.get('supplier_part', ''),
                            'Quantity': part.get('quantity', 1),
                            'Unit Price': part.get('unit_price', ''),
                            'Extended Price': part.get('extended_price', '')
                        }
                        writer.writerow(row)

                return {
                    "exported": True,
                    "path": str(path),
                    "format": format,
                    "parts_count": len(parts),
                    "message": "Exported KiCad-compatible BOM"
                }

            elif format == "json":
                # Export as JSON with KiCad structure
                kicad_data = {
                    "source": "parts-mcp",
                    "version": "1.0",
                    "components": parts
                }

                with open(path, 'w') as f:
                    json.dump(kicad_data, f, indent=2)

                return {
                    "exported": True,
                    "path": str(path),
                    "format": format,
                    "parts_count": len(parts)
                }

            else:
                return {"error": f"Unsupported format: {format}"}

        except Exception as e:
            logger.error(f"Export error: {e}")
            return {"error": str(e)}
