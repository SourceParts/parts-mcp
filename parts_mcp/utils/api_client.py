"""
Source Parts API client for electronic component searching.
"""
import logging
import time
from typing import Any
from urllib.parse import urljoin

import httpx
from httpx import HTTPStatusError, RequestError, TimeoutException

from parts_mcp.config import (
    DEFAULT_PAGE_SIZE,
    MAX_RESULTS,
    SEARCH_TIMEOUT,
    SOURCE_PARTS_API_KEY,
    SOURCE_PARTS_API_URL,
)

logger = logging.getLogger(__name__)


class SourcePartsAPIError(Exception):
    """Base exception for Source Parts API errors."""
    pass


class SourcePartsAuthError(SourcePartsAPIError):
    """Authentication error with Source Parts API."""
    pass


class SourcePartsRateLimitError(SourcePartsAPIError):
    """Rate limit exceeded error."""
    pass


class SourcePartsClient:
    """Client for interacting with Source Parts API."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        """Initialize the Source Parts API client.

        Args:
            api_key: API key for authentication (uses config if not provided)
            base_url: Base URL for API (uses config if not provided)
        """
        self.api_key = api_key or SOURCE_PARTS_API_KEY
        self.base_url = base_url or SOURCE_PARTS_API_URL

        if not self.api_key:
            raise SourcePartsAuthError("No API key provided. Set SOURCE_PARTS_API_KEY in .env")

        # Initialize HTTP client
        self.client = httpx.Client(
            timeout=SEARCH_TIMEOUT,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "PARTS-MCP/1.0"
            }
        )

        # Rate limiting
        self._last_request_time = 0
        self._min_request_interval = 0.1  # 100ms between requests

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close the HTTP client."""
        self.client.close()

    def _rate_limit(self):
        """Implement rate limiting between requests."""
        current_time = time.time()
        time_since_last = current_time - self._last_request_time

        if time_since_last < self._min_request_interval:
            sleep_time = self._min_request_interval - time_since_last
            time.sleep(sleep_time)

        self._last_request_time = time.time()

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        retry_count: int = 3
    ) -> dict[str, Any]:
        """Make an API request with error handling and retries.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            params: Query parameters
            json_data: JSON body data
            retry_count: Number of retries on failure

        Returns:
            API response data

        Raises:
            SourcePartsAPIError: On API errors
        """
        # Ensure base_url ends with / for proper urljoin behavior
        base = self.base_url if self.base_url.endswith('/') else self.base_url + '/'
        url = urljoin(base, endpoint.lstrip('/'))

        for attempt in range(retry_count):
            try:
                # Rate limiting
                self._rate_limit()

                # Make request
                response = self.client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_data
                )

                # Check for rate limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 60))
                    if attempt < retry_count - 1:
                        logger.warning(f"Rate limited, waiting {retry_after}s")
                        time.sleep(retry_after)
                        continue
                    raise SourcePartsRateLimitError(f"Rate limit exceeded, retry after {retry_after}s")

                # Check for auth errors
                if response.status_code == 401:
                    raise SourcePartsAuthError("Invalid API key")
                elif response.status_code == 403:
                    raise SourcePartsAuthError("Access forbidden - check API permissions")

                # Raise for other HTTP errors
                response.raise_for_status()

                # Parse JSON response
                raw_response = response.json()

                # Unwrap envelope if present (v1 API uses {"status": "success", "data": {...}})
                if isinstance(raw_response, dict):
                    if raw_response.get("status") == "success" and "data" in raw_response:
                        return raw_response["data"]
                    elif raw_response.get("status") == "error":
                        error_msg = raw_response.get("error", "Unknown error")
                        raise SourcePartsAPIError(f"API error: {error_msg}")

                return raw_response

            except TimeoutException as e:
                if attempt < retry_count - 1:
                    logger.warning(f"Request timeout, retry {attempt + 1}/{retry_count}")
                    time.sleep(2 ** attempt)  # Exponential backoff
                    continue
                raise SourcePartsAPIError("Request timeout") from e

            except RequestError as e:
                if attempt < retry_count - 1:
                    logger.warning(f"Request error: {e}, retry {attempt + 1}/{retry_count}")
                    time.sleep(2 ** attempt)
                    continue
                raise SourcePartsAPIError(f"Request error: {e}") from e

            except HTTPStatusError as e:
                error_detail = ""
                try:
                    error_data = e.response.json()
                    error_detail = error_data.get('message', error_data.get('error', ''))
                except Exception:
                    error_detail = e.response.text

                raise SourcePartsAPIError(
                    f"API error {e.response.status_code}: {error_detail or e}"
                ) from e

    def search_parts(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0
    ) -> dict[str, Any]:
        """Search for electronic parts.

        Args:
            query: Search query string
            filters: Optional filters (category, manufacturer, etc.)
            limit: Maximum number of results (default: 20, max: 100)
            offset: Number of results to skip (default: 0)

        Returns:
            Search results with parts data
        """
        params = {
            'q': query,
            'limit': min(limit, MAX_RESULTS),
            'offset': offset
        }

        # Add filters if provided
        if filters:
            for key, value in filters.items():
                if value is not None:
                    params[key] = value

        logger.info(f"Searching parts: query='{query}', limit={limit}, offset={offset}")

        try:
            response = self._make_request('GET', '/parts/search', params=params)

            # Response is already unwrapped by _make_request
            # v1 API returns: {"parts": [...], "total": N, "limit": N, "offset": N, "query": "..."}
            return {
                'results': response.get('parts', []),
                'total': response.get('total', len(response.get('parts', []))),
                'limit': response.get('limit', limit),
                'offset': response.get('offset', offset),
                'query': query,
                'filters': filters or {}
            }

        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise

    def get_part_details(self, sku: str) -> dict[str, Any]:
        """Get detailed information about a specific part.

        Args:
            sku: Part number or SKU

        Returns:
            Detailed part information
        """
        logger.info(f"Getting details for part: {sku}")

        try:
            return self._make_request('GET', f'/parts/{sku}')
        except Exception as e:
            logger.error(f"Failed to get part details: {e}")
            raise

    def get_part_pricing(
        self,
        part_id: str,
        quantity: int = 1,
        currency: str = 'USD'
    ) -> dict[str, Any]:
        """Get pricing information for a part.

        Args:
            part_id: Part identifier
            quantity: Quantity for pricing
            currency: Currency code

        Returns:
            Pricing information from suppliers
        """
        params = {
            'quantity': quantity,
            'currency': currency
        }

        logger.info(f"Getting pricing for part {part_id}, qty={quantity}")

        try:
            return self._make_request('GET', f'/parts/{part_id}/pricing', params=params)
        except Exception as e:
            logger.error(f"Failed to get pricing: {e}")
            raise

    def get_part_inventory(self, sku: str) -> dict[str, Any]:
        """Get inventory information for a part.

        Args:
            sku: Part number or SKU

        Returns:
            Inventory data including quantity and location
        """
        logger.info(f"Getting inventory for part: {sku}")

        try:
            return self._make_request('GET', f'/parts/{sku}/inventory')
        except Exception as e:
            logger.error(f"Failed to get inventory: {e}")
            raise

    def get_part_availability(self, sku: str) -> dict[str, Any]:
        """Get availability information for a part (alias for get_part_inventory).

        Args:
            sku: Part number or SKU

        Returns:
            Inventory/availability data
        """
        return self.get_part_inventory(sku)

    def search_by_parameters(
        self,
        category: str,
        parameters: dict[str, Any],
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0
    ) -> dict[str, Any]:
        """Search parts by parametric specifications.

        Args:
            category: Part category
            parameters: Parameter filters
            limit: Maximum results
            offset: Results to skip

        Returns:
            Matching parts
        """
        # Build query from parameters
        query_parts = []
        for param, value in parameters.items():
            if isinstance(value, (list, tuple)):
                # Range query
                query_parts.append(f"{param}:[{value[0]} TO {value[1]}]")
            else:
                query_parts.append(f"{param}:{value}")

        query = f"category:{category} " + " ".join(query_parts)

        return self.search_parts(query, limit=limit, offset=offset)

    def find_alternatives(
        self,
        part_number: str,
        match_parameters: list[str] | None = None
    ) -> dict[str, Any]:
        """Find alternative parts for a given part number.

        Uses a search-based approach since the v1 API doesn't have a dedicated
        alternatives endpoint. Searches for the part first to get its category
        and parameters, then searches for similar parts.

        Args:
            part_number: Original part number
            match_parameters: Parameters that must match (e.g., ["value", "package"])

        Returns:
            Alternative parts suggestions
        """
        logger.info(f"Finding alternatives for: {part_number}")

        try:
            # First, get the original part details
            original_part = None
            try:
                original_part = self.get_part_details(part_number)
            except SourcePartsAPIError:
                # Part not found by SKU, try searching
                search_result = self.search_parts(part_number, limit=1)
                if search_result.get('results'):
                    original_part = search_result['results'][0]

            if not original_part:
                return {
                    'original': None,
                    'alternatives': [],
                    'message': f"Part '{part_number}' not found"
                }

            # Build search query based on part attributes
            search_terms = []

            # Use category if available
            category = original_part.get('category')
            if category:
                search_terms.append(category)

            # Use manufacturer for cross-reference
            original_part.get('manufacturer')

            # Use key parameters if specified
            if match_parameters:
                for param in match_parameters:
                    value = original_part.get(param)
                    if value:
                        search_terms.append(str(value))

            # Search for alternatives
            query = ' '.join(search_terms) if search_terms else part_number
            filters = {}
            if category:
                filters['category'] = category

            search_result = self.search_parts(query, filters=filters, limit=20)

            # Filter out the original part
            alternatives = [
                p for p in search_result.get('results', [])
                if p.get('part_number', '').upper() != part_number.upper()
            ]

            return {
                'original': original_part,
                'alternatives': alternatives[:10],  # Limit to 10 alternatives
                'query': query,
                'total_found': len(alternatives)
            }

        except Exception as e:
            logger.error(f"Failed to find alternatives: {e}")
            raise

    def batch_search(self, part_numbers: list[str]) -> dict[str, Any]:
        """Search for multiple parts.

        The v1 API doesn't have a batch endpoint, so this performs sequential
        searches with rate limiting. For large batches, consider caching results.

        Args:
            part_numbers: List of part numbers to search

        Returns:
            Results for each part number with found/not_found status
        """
        logger.info(f"Batch searching {len(part_numbers)} parts")

        results = {}
        found = []
        not_found = []

        for part_number in part_numbers:
            try:
                # Try exact lookup first
                part = self.get_part_details(part_number)
                results[part_number] = part
                found.append(part_number)
            except SourcePartsAPIError:
                # Part not found by exact SKU, try search
                try:
                    search_result = self.search_parts(part_number, limit=1)
                    if search_result.get('results'):
                        results[part_number] = search_result['results'][0]
                        found.append(part_number)
                    else:
                        results[part_number] = None
                        not_found.append(part_number)
                except Exception:
                    results[part_number] = None
                    not_found.append(part_number)

        return {
            'results': results,
            'found': found,
            'not_found': not_found,
            'total_requested': len(part_numbers),
            'total_found': len(found)
        }

    # =========================================================================
    # Component Matching Endpoints (offloaded business logic from MCP)
    # =========================================================================

    def match_component(
        self,
        component: dict[str, Any],
        max_results: int = 5,
        search_depth: str = "standard"
    ) -> dict[str, Any]:
        """Match a single BOM component to database parts with confidence scoring.

        This offloads matching logic to the API instead of doing it locally.

        Args:
            component: Component data with reference, value, footprint, manufacturer
            max_results: Maximum number of matches to return
            search_depth: Search depth: "quick", "standard", or "deep"

        Returns:
            Match result with confidence scores and breakdown
        """
        logger.info(f"Matching component: {component.get('reference', 'unknown')}")

        json_data = {
            "component": component,
            "max_results": max_results,
            "search_depth": search_depth
        }

        try:
            return self._make_request('POST', '/components/match', json_data=json_data)
        except Exception as e:
            logger.error(f"Component match failed: {e}")
            raise

    def match_components_batch(
        self,
        components: list[dict[str, Any]],
        search_depth: str = "standard"
    ) -> dict[str, Any]:
        """Batch match BOM components to database parts with confidence scoring.

        This offloads batch matching logic to the API instead of doing it locally.
        The API handles confidence scoring using weights:
        - MPN: 40%
        - Value: 25%
        - Footprint: 20%
        - Manufacturer: 10%
        - Description: 5%

        Args:
            components: List of components with reference, value, footprint, manufacturer
            search_depth: Search depth: "quick", "standard", or "deep"

        Returns:
            Batch match results with statistics
        """
        logger.info(f"Batch matching {len(components)} components")

        json_data = {
            "components": components,
            "search_depth": search_depth
        }

        try:
            return self._make_request('POST', '/components/match/batch', json_data=json_data)
        except Exception as e:
            logger.error(f"Batch component match failed: {e}")
            raise

    def get_part_alternatives(
        self,
        sku: str,
        match_parameters: bool = True,
        max_results: int = 10
    ) -> dict[str, Any]:
        """Find alternative/substitute parts for a given SKU.

        Uses the v1 API alternatives endpoint which provides compatibility levels:
        - drop-in: Direct replacement
        - similar: Similar specs, may need verification
        - functional: Same function, different specs

        Args:
            sku: Part SKU to find alternatives for
            match_parameters: Whether to match electrical parameters
            max_results: Maximum alternatives to return

        Returns:
            Alternatives with compatibility information
        """
        logger.info(f"Finding alternatives for: {sku}")

        params = {
            'match_parameters': str(match_parameters).lower(),
            'max_results': max_results
        }

        try:
            return self._make_request('GET', f'/parts/{sku}/alternatives', params=params)
        except Exception as e:
            logger.error(f"Failed to get alternatives: {e}")
            raise

    def get_footprint_compatible(self, footprint: str) -> dict[str, Any]:
        """Get compatible footprint sizes for a given footprint.

        Returns imperial/metric equivalences and compatible sizes.
        E.g., 0603 imperial ↔ 1608 metric

        Args:
            footprint: Footprint string (e.g., "0603", "1608", "SOT-23")

        Returns:
            Compatible footprints with type information
        """
        logger.info(f"Getting compatible footprints for: {footprint}")

        try:
            return self._make_request('GET', f'/footprints/{footprint}/compatible')
        except Exception as e:
            logger.error(f"Failed to get compatible footprints: {e}")
            raise

    def normalize_value(self, value: str) -> dict[str, Any]:
        """Normalize a component value string.

        Converts values like "4k7", "10n", "100u" to normalized form.

        Args:
            value: Value string to normalize

        Returns:
            Normalized value with numeric and formatted representations
        """
        logger.info(f"Normalizing value: {value}")

        params = {'value': value}

        try:
            return self._make_request('GET', '/values/normalize', params=params)
        except Exception as e:
            logger.error(f"Failed to normalize value: {e}")
            raise


# Singleton instance for reuse
_client_instance: SourcePartsClient | None = None


def get_client() -> SourcePartsClient:
    """Get or create a singleton Source Parts API client.

    Returns:
        Source Parts API client instance
    """
    global _client_instance

    if _client_instance is None:
        _client_instance = SourcePartsClient()

    return _client_instance


def close_client():
    """Close the singleton client instance."""
    global _client_instance

    if _client_instance:
        _client_instance.close()
        _client_instance = None
