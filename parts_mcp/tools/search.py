"""
Parts search tools for finding electronic components.
"""
import logging
from typing import Dict, Any, List, Optional
from fastmcp import FastMCP

from parts_mcp.utils.api_client import (
    get_client, 
    SourcePartsAPIError,
    SourcePartsAuthError
)
from parts_mcp.utils.cache import cache_search_results, cache_part_details

logger = logging.getLogger(__name__)


def register_search_tools(mcp: FastMCP) -> None:
    """Register search tools with the MCP server.
    
    Args:
        mcp: The FastMCP server instance
    """
    
    @mcp.tool()
    @cache_search_results()
    async def search_parts(
        query: str,
        category: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Search for electronic parts across suppliers.
        
        Args:
            query: Search query (part number, description, or keywords)
            category: Optional category filter (e.g., "resistor", "capacitor")
            filters: Optional parametric filters (e.g., {"resistance": "10k", "tolerance": "1%"})
            limit: Maximum number of results to return
            
        Returns:
            Search results with part information
        """
        try:
            client = get_client()
            
            # Build filters
            search_filters = filters or {}
            if category:
                search_filters['category'] = category
            
            # Perform search
            results = client.search_parts(
                query=query,
                filters=search_filters,
                page=1,
                page_size=limit
            )
            
            # Format results
            formatted_results = {
                "query": query,
                "category": category,
                "filters": filters or {},
                "results": results.get('results', []),
                "total_results": results.get('total', 0),
                "success": True
            }
            
            logger.info(f"Found {formatted_results['total_results']} results for query: {query}")
            return formatted_results
            
        except SourcePartsAuthError as e:
            logger.error(f"Authentication error: {e}")
            return {
                "query": query,
                "error": "Authentication failed. Please check your API key.",
                "success": False
            }
            
        except SourcePartsAPIError as e:
            logger.error(f"API error during search: {e}")
            return {
                "query": query,
                "error": f"Search failed: {str(e)}",
                "success": False
            }
            
        except Exception as e:
            logger.error(f"Unexpected error during search: {e}")
            return {
                "query": query,
                "error": f"An unexpected error occurred: {str(e)}",
                "success": False
            }
    
    @mcp.tool()
    @cache_search_results()
    async def search_by_parameters(
        parameters: Dict[str, Any],
        category: str,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Search parts by specific parameters.
        
        Args:
            parameters: Parametric search criteria
            category: Part category
            limit: Maximum results
            
        Returns:
            Matching parts
        """
        try:
            client = get_client()
            
            # Perform parametric search
            results = client.search_by_parameters(
                category=category,
                parameters=parameters,
                page=1,
                page_size=limit
            )
            
            return {
                "category": category,
                "parameters": parameters,
                "results": results.get('results', []),
                "total_results": results.get('total', 0),
                "success": True
            }
            
        except SourcePartsAPIError as e:
            logger.error(f"Parametric search error: {e}")
            return {
                "category": category,
                "parameters": parameters,
                "error": f"Search failed: {str(e)}",
                "success": False
            }
    
    @mcp.tool()
    @cache_part_details()
    async def get_part_details(
        part_number: str,
        manufacturer: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get detailed information about a specific part.
        
        Args:
            part_number: The part number to look up
            manufacturer: Optional manufacturer name
            
        Returns:
            Detailed part information
        """
        try:
            client = get_client()
            
            # First search for the part
            search_query = part_number
            if manufacturer:
                search_query = f"{manufacturer} {part_number}"
                
            search_results = client.search_parts(search_query, page_size=1)
            
            if not search_results.get('results'):
                return {
                    "part_number": part_number,
                    "manufacturer": manufacturer,
                    "error": "Part not found",
                    "success": False
                }
                
            # Get the first result's ID
            part_data = search_results['results'][0]
            part_id = part_data.get('id', part_data.get('part_id'))
            
            if part_id:
                # Get detailed information
                details = client.get_part_details(part_id)
                
                return {
                    "part_number": part_number,
                    "manufacturer": manufacturer,
                    "details": details,
                    "success": True
                }
            else:
                # Return search result as details
                return {
                    "part_number": part_number,
                    "manufacturer": manufacturer,
                    "details": part_data,
                    "success": True
                }
                
        except SourcePartsAPIError as e:
            logger.error(f"Error getting part details: {e}")
            return {
                "part_number": part_number,
                "manufacturer": manufacturer,
                "error": f"Failed to get details: {str(e)}",
                "success": False
            }