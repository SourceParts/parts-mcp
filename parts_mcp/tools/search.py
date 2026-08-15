"""
Parts search tools for finding electronic components.
"""
import logging
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import (
    SourcePartsAPIError,
    SourcePartsAuthError,
    get_client,
    with_user_context,
)
from parts_mcp.utils.cache import cache_part_details, cache_search_results
from parts_mcp.utils.matching import verify_mpn_match

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

            # Annotate every result with match_verified so callers can tell
            # an exact part-number hit from a fuzzy suggestion — the search
            # backend scores fuzzily and returns no quality signal of its own.
            result_rows = results.get('results', [])
            for row in result_rows:
                if isinstance(row, dict):
                    row['match_verified'] = verify_mpn_match(query, row)

            # Format results
            formatted_results = {
                "query": query,
                "category": category,
                "filters": filters or {},
                "results": result_rows,
                "total_results": results.get('total', 0),
                "match_verified": bool(result_rows)
                and bool(result_rows[0].get('match_verified')),
                "success": True
            }

            if result_rows and not formatted_results["match_verified"]:
                formatted_results["match_warning"] = (
                    f"No result is an exact match for '{query}' — these are "
                    "fuzzy suggestions. Verify the part number before pricing "
                    "or ordering."
                )

            # Surface external supplier search status to AI assistants
            if results.get('sync_status'):
                formatted_results['sync_status'] = results['sync_status']
                formatted_results['message'] = (
                    "No results in local database. External supplier search triggered — "
                    "results from LCSC, Digikey, and Mouser typically appear within 5-15 seconds. "
                    "Retry the search shortly."
                )

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
    @cache_search_results()
    @with_user_context
    async def search_by_marking(
        code: str,
        limit: int = 10
    ) -> dict[str, Any]:
        """Resolve an IC/SMD top-marking code to candidate parts.

        The code printed on a package (e.g. "F407VG" on an STM32, "UADD" on
        a SOT-23) goes in; ranked candidate parts come out. Markings are not
        unique across vendors, so treat the answer as candidates to confirm
        against package and pinout, not a definitive ID. Each candidate
        carries a "match" lane:

            catalog    — a part whose stored marking equals the code
            identified — a prior identify.parts photo recognition that read
                         this code (returns its mpn_candidates)
            mpn        — a part whose MPN starts or ends with the code
                         (many markings are MPN fragments; vendor-assigned
                         codes will not hit this lane)

        Use search_parts for MPNs and keywords; use this when all you have
        is the code on the chip.

        Args:
            code: The marking as printed on the package
            limit: Maximum candidates per match lane (max 25)

        Returns:
            Candidates grouped in one ranked list, with per-lane counts
        """
        try:
            client = get_client()
            result = client.search_by_marking(code=code, limit=limit)

            candidates = result.get("candidates", [])
            return {
                "code": result.get("code", code),
                "candidates": candidates,
                "counts": result.get("counts", {}),
                "total_candidates": len(candidates),
                "success": True,
            }

        except SourcePartsAuthError as e:
            logger.error(f"Authentication error: {e}")
            return {
                "code": code,
                "error": "Authentication failed. Please check your API key.",
                "success": False,
            }

        except SourcePartsAPIError as e:
            logger.error(f"Marking search error: {e}")
            error_str = str(e)

            if "404" in error_str:
                return {
                    "code": code,
                    "candidates": [],
                    "error": f"No candidate parts known for marking '{code}'.",
                    "message": (
                        "No stored marking, prior identification, or MPN "
                        "fragment matched. A photo run through identify_pcb "
                        "adds this marking to the identification history for "
                        "future lookups."
                    ),
                    "success": False,
                }

            return {
                "code": code,
                "error": f"Marking search failed: {error_str}",
                "success": False,
            }

        except Exception as e:
            logger.error(f"Unexpected error during marking search: {e}")
            return {
                "code": code,
                "error": f"An unexpected error occurred: {str(e)}",
                "success": False,
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

            # Get the first result's SKU
            part_data = search_results['results'][0]
            sku = part_data.get('sku', part_data.get('part_number'))

            match_verified = verify_mpn_match(part_number, part_data)

            if sku:
                # Get detailed information
                details = client.get_part_details(sku)

                return {
                    "part_number": part_number,
                    "manufacturer": manufacturer,
                    "details": details,
                    "match_verified": match_verified,
                    "success": True
                }
            else:
                # Return search result as details
                return {
                    "part_number": part_number,
                    "manufacturer": manufacturer,
                    "details": part_data,
                    "match_verified": match_verified,
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
