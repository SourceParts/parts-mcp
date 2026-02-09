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
from parts_mcp.utils.kicad_utils import open_kicad_project as open_project_util
from parts_mcp.utils.netlist_parser import (
    NetlistParser,
    analyze_connectivity,
    extract_netlist_from_schematic,
)

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
        projects = find_kicad_projects()

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
