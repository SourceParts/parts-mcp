"""
KiCad integration tools for working with KiCad projects.
"""
import logging
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastmcp import FastMCP

from parts_mcp.config import KICAD_SEARCH_PATHS

logger = logging.getLogger(__name__)


def register_kicad_tools(mcp: FastMCP) -> None:
    """Register KiCad integration tools with the MCP server.
    
    Args:
        mcp: The FastMCP server instance
    """
    
    @mcp.tool()
    async def extract_bom_from_kicad(
        project_path: str
    ) -> Dict[str, Any]:
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
            
            # This is a placeholder - actual implementation would parse KiCad files
            return {
                "project": path.name,
                "components": [],
                "total_parts": 0,
                "message": "KiCad BOM extraction will be implemented"
            }
            
        except Exception as e:
            logger.error(f"Error extracting BOM: {e}")
            return {"error": str(e)}
    
    @mcp.tool()
    async def find_kicad_projects() -> Dict[str, Any]:
        """Find KiCad projects in configured search paths.
        
        Returns:
            List of found KiCad projects
        """
        projects = []
        
        for search_path in KICAD_SEARCH_PATHS:
            path = Path(search_path)
            if path.exists():
                # Find all .kicad_pro files
                for proj_file in path.rglob("*.kicad_pro"):
                    projects.append({
                        "name": proj_file.stem,
                        "path": str(proj_file),
                        "directory": str(proj_file.parent)
                    })
        
        return {
            "projects": projects,
            "total": len(projects),
            "search_paths": KICAD_SEARCH_PATHS
        }
    
    @mcp.tool()
    async def match_components_to_parts(
        components: List[Dict[str, Any]],
        auto_search: bool = True
    ) -> Dict[str, Any]:
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
    async def export_parts_to_kicad(
        parts: List[Dict[str, Any]],
        output_path: str,
        format: str = "csv"
    ) -> Dict[str, Any]:
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
                # Placeholder CSV export
                return {
                    "exported": True,
                    "path": output_path,
                    "format": format,
                    "parts_count": len(parts),
                    "message": "CSV export will be implemented"
                }
            elif format == "json":
                # Placeholder JSON export
                with open(path, 'w') as f:
                    json.dump({"parts": parts}, f, indent=2)
                return {
                    "exported": True,
                    "path": output_path,
                    "format": format,
                    "parts_count": len(parts)
                }
            else:
                return {"error": f"Unsupported format: {format}"}
                
        except Exception as e:
            logger.error(f"Export error: {e}")
            return {"error": str(e)}