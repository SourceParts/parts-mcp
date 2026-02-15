"""
Parts search tools for finding electronic components.
"""
import logging
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import SourcePartsAPIError, SourcePartsAuthError, get_client, with_user_context
from parts_mcp.utils.cache import cache_part_details, cache_search_results

logger = logging.getLogger(__name__)


def register_search_tools(mcp: FastMCP) -> None:
    """Register search tools with the MCP server.

    Args:
        mcp: The FastMCP server instance
    """

    @mcp.tool()
    @cache_search_results()
    @with_user_context
    async def search_parts(
        query: str,
        category: str | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 20
    ) -> dict[str, Any]:
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
                limit=limit,
                offset=0
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
            error_str = str(e)

            # Provide user-friendly messages for common errors
            if "404" in error_str:
                return {
                    "query": query,
                    "error": "Parts search endpoint not found.",
                    "message": "This may indicate a configuration issue. Please contact support.",
                    "success": False
                }

            if "503" in error_str or "unavailable" in error_str.lower():
                return {
                    "query": query,
                    "error": "Search service temporarily unavailable.",
                    "message": "The service is experiencing high load or maintenance. Please try again in a few minutes.",
                    "success": False
                }

            return {
                "query": query,
                "error": f"Search failed: {error_str}",
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
    @with_user_context
    async def search_by_parameters(
        parameters: dict[str, Any],
        category: str,
        limit: int = 20
    ) -> dict[str, Any]:
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
                limit=limit,
                offset=0
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
            error_str = str(e)

            if "404" in error_str:
                return {
                    "category": category,
                    "parameters": parameters,
                    "error": "Parametric search endpoint not found.",
                    "message": "This may indicate a configuration issue. Please contact support.",
                    "success": False
                }

            return {
                "category": category,
                "parameters": parameters,
                "error": f"Search failed: {error_str}",
                "success": False
            }

    @mcp.tool()
    @cache_part_details()
    @with_user_context
    async def get_part_details(
        part_number: str,
        manufacturer: str | None = None
    ) -> dict[str, Any]:
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

            search_results = client.search_parts(search_query, limit=1)

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
            error_str = str(e)

            if "404" in error_str:
                return {
                    "part_number": part_number,
                    "manufacturer": manufacturer,
                    "error": "Part details endpoint not found.",
                    "message": "This may indicate a configuration issue. Please contact support.",
                    "success": False
                }

            return {
                "part_number": part_number,
                "manufacturer": manufacturer,
                "error": f"Failed to get details: {error_str}",
                "success": False
            }
