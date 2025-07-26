"""
Supplier information resources.
"""
import logging
from typing import Dict, Any, List
from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_supplier_resources(mcp: FastMCP) -> None:
    """Register supplier-related resources with the MCP server.
    
    Args:
        mcp: The FastMCP server instance
    """
    
    @mcp.resource("suppliers://list")
    async def list_suppliers() -> Dict[str, Any]:
        """List available electronic component suppliers through Source Parts API."""
        return {
            "api": "Source Parts API",
            "description": "Unified API for searching electronic components across multiple suppliers",
            "capabilities": [
                "Multi-supplier search",
                "Real-time pricing",
                "Stock availability",
                "Datasheet access",
                "Parametric search"
            ],
            "supported_suppliers": [
                "Digi-Key",
                "Mouser",
                "Arrow",
                "Newark",
                "RS Components",
                "And many more..."
            ]
        }
    
    @mcp.resource("suppliers://capabilities")
    async def supplier_capabilities() -> Dict[str, Any]:
        """Get capabilities provided by Source Parts API."""
        return {
            "search_features": {
                "keyword_search": True,
                "parametric_search": True,
                "datasheet_access": True,
                "image_access": True,
                "cross_reference": True,
                "barcode_search": True
            },
            "data_features": {
                "real_time_pricing": True,
                "stock_availability": True,
                "price_breaks": True,
                "lead_times": True,
                "minimum_quantities": True,
                "lifecycle_status": True
            },
            "api_features": {
                "rate_limit": "Based on subscription tier",
                "authentication": "API key",
                "response_format": "JSON",
                "batch_operations": True
            }
        }