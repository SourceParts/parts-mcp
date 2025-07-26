"""
Parts database resources for read-only access.
"""
import logging
from typing import Dict, Any, List
from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_parts_resources(mcp: FastMCP) -> None:
    """Register parts-related resources with the MCP server.
    
    Args:
        mcp: The FastMCP server instance
    """
    
    @mcp.resource("parts://categories")
    async def list_part_categories() -> Dict[str, Any]:
        """List available part categories."""
        categories = {
            "passive": ["Resistors", "Capacitors", "Inductors"],
            "semiconductor": ["Diodes", "Transistors", "ICs"],
            "electromechanical": ["Connectors", "Switches", "Relays"],
            "power": ["Voltage Regulators", "Power Supplies", "Batteries"],
            "sensors": ["Temperature", "Pressure", "Motion", "Light"],
            "display": ["LEDs", "LCDs", "OLEDs"],
        }
        
        return {
            "categories": categories,
            "total_categories": len(categories),
            "description": "Electronic component categories for searching"
        }
    
    @mcp.resource("parts://parameters")
    async def list_search_parameters() -> Dict[str, Any]:
        """List available search parameters for parts."""
        parameters = {
            "electrical": [
                "resistance", "capacitance", "inductance",
                "voltage_rating", "current_rating", "power_rating",
                "tolerance", "temperature_coefficient"
            ],
            "physical": [
                "package_type", "mounting_type", "dimensions",
                "pin_count", "pitch", "height"
            ],
            "environmental": [
                "operating_temperature", "storage_temperature",
                "moisture_sensitivity", "rohs_compliant"
            ],
            "commercial": [
                "manufacturer", "part_number", "series",
                "lifecycle_status", "minimum_quantity"
            ]
        }
        
        return {
            "parameters": parameters,
            "description": "Searchable parameters for electronic components"
        }