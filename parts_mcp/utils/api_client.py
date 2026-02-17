"""
Source Parts API client for electronic component searching.
"""
import hashlib
import logging
import time
from contextvars import ContextVar
from functools import wraps
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

# Auth0 user sub for the current MCP request. Set by with_user_context
# decorator, read by SourcePartsClient._make_request to forward as a header.
_mcp_user_sub: ContextVar[str | None] = ContextVar("_mcp_user_sub", default=None)


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

                # Forward MCP user identity if available
                extra_headers = {}
                user_sub = _mcp_user_sub.get()
                if user_sub:
                    extra_headers["X-MCP-User-Sub"] = user_sub

                # Make request
                response = self.client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_data,
                    headers=extra_headers,
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

    def _make_upload_request(
        self,
        endpoint: str,
        file_data: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
        form_fields: dict[str, str] | None = None,
        retry_count: int = 3,
    ) -> dict[str, Any]:
        """Make a multipart file upload request with error handling and retries.

        Args:
            endpoint: API endpoint path
            file_data: Raw file bytes
            filename: Name of the file being uploaded
            content_type: MIME type of the file
            form_fields: Additional form fields to include
            retry_count: Number of retries on failure

        Returns:
            API response data

        Raises:
            SourcePartsAPIError: On API errors
        """
        base = self.base_url if self.base_url.endswith('/') else self.base_url + '/'
        url = urljoin(base, endpoint.lstrip('/'))

        for attempt in range(retry_count):
            try:
                self._rate_limit()

                extra_headers = {}
                user_sub = _mcp_user_sub.get()
                if user_sub:
                    extra_headers["X-MCP-User-Sub"] = user_sub

                # Use a separate client without Content-Type header so httpx
                # sets the multipart boundary automatically.
                upload_headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "User-Agent": "PARTS-MCP/1.0",
                    **extra_headers,
                }

                files = {"file": (filename, file_data, content_type)}

                response = httpx.request(
                    method="POST",
                    url=url,
                    files=files,
                    data=form_fields or {},
                    headers=upload_headers,
                    timeout=SEARCH_TIMEOUT,
                )

                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 60))
                    if attempt < retry_count - 1:
                        logger.warning(f"Rate limited, waiting {retry_after}s")
                        time.sleep(retry_after)
                        continue
                    raise SourcePartsRateLimitError(f"Rate limit exceeded, retry after {retry_after}s")

                if response.status_code == 401:
                    raise SourcePartsAuthError("Invalid API key")
                elif response.status_code == 403:
                    raise SourcePartsAuthError("Access forbidden - check API permissions")

                response.raise_for_status()

                raw_response = response.json()

                if isinstance(raw_response, dict):
                    if raw_response.get("status") == "success" and "data" in raw_response:
                        return raw_response["data"]
                    elif raw_response.get("status") == "error":
                        error_msg = raw_response.get("error", "Unknown error")
                        raise SourcePartsAPIError(f"API error: {error_msg}")

                return raw_response

            except TimeoutException as e:
                if attempt < retry_count - 1:
                    logger.warning(f"Upload timeout, retry {attempt + 1}/{retry_count}")
                    time.sleep(2 ** attempt)
                    continue
                raise SourcePartsAPIError("Upload request timeout") from e

            except RequestError as e:
                if attempt < retry_count - 1:
                    logger.warning(f"Upload error: {e}, retry {attempt + 1}/{retry_count}")
                    time.sleep(2 ** attempt)
                    continue
                raise SourcePartsAPIError(f"Upload request error: {e}") from e

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

        Uses the search endpoint with category/manufacturer as proper filters
        and remaining parameters as search query terms.

        Args:
            category: Part category
            parameters: Parameter filters
            limit: Maximum results
            offset: Results to skip

        Returns:
            Matching parts
        """
        # Extract known filter fields, pass rest as query terms
        filters: dict[str, Any] = {'category': category}
        query_parts = []

        for param, value in parameters.items():
            if param == 'manufacturer':
                filters['manufacturer'] = value
            elif value is not None:
                query_parts.append(str(value))

        # Use parameter values as search query (e.g., "10k 0603 1%")
        query = ' '.join(query_parts) if query_parts else category

        return self.search_parts(query, filters=filters, limit=limit, offset=offset)

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

    # =========================================================================
    # BOM Endpoints
    # =========================================================================

    def upload_bom(
        self,
        file_data: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        """Upload a BOM file for processing and part matching.

        Args:
            file_data: Raw file bytes
            filename: Original filename (used for format detection)
            content_type: MIME type of the file

        Returns:
            Upload result with job_id and status_url
        """
        logger.info(f"Uploading BOM: {filename}")

        try:
            return self._make_upload_request(
                '/bom',
                file_data=file_data,
                filename=filename,
                content_type=content_type,
            )
        except Exception as e:
            logger.error(f"BOM upload failed: {e}")
            raise

    def get_bom_status(self, job_id: str) -> dict[str, Any]:
        """Check BOM processing status.

        Args:
            job_id: Job ID returned from upload_bom

        Returns:
            Status with progress, summary, and bom_id when complete
        """
        logger.info(f"Checking BOM status: {job_id}")

        try:
            return self._make_request('GET', f'/bom/{job_id}/status')
        except Exception as e:
            logger.error(f"Failed to get BOM status: {e}")
            raise

    def get_bom(
        self,
        bom_id: str,
        include_pricing: bool = False,
        include_inventory: bool = False,
    ) -> dict[str, Any]:
        """Get a processed BOM with matched/unmatched parts.

        Args:
            bom_id: BOM ID (from completed job status)
            include_pricing: Include pricing data for matched parts
            include_inventory: Include inventory data for matched parts

        Returns:
            Full BOM with lines and match status
        """
        logger.info(f"Getting BOM: {bom_id}")

        params: dict[str, Any] = {}
        if include_pricing:
            params['include_pricing'] = 'true'
        if include_inventory:
            params['include_inventory'] = 'true'

        try:
            return self._make_request('GET', f'/bom/{bom_id}', params=params or None)
        except Exception as e:
            logger.error(f"Failed to get BOM: {e}")
            raise

    # =========================================================================
    # Manufacturing / DFM Endpoints
    # =========================================================================

    def submit_dfm(
        self,
        project_id: str,
        bom_id: str | None = None,
        revision: str | None = None,
        notes: str | None = None,
        priority: str = "normal",
    ) -> dict[str, Any]:
        """Submit a DFM analysis for a project (project-reference mode).

        Args:
            project_id: Project ID to analyze
            bom_id: Optional BOM ID to include in analysis
            revision: Optional revision identifier
            notes: Optional notes for the analysis
            priority: Priority level ("low", "normal", "high")

        Returns:
            Submission result with job_id and status_url
        """
        logger.info(f"Submitting DFM analysis for project: {project_id}")

        json_data: dict[str, Any] = {
            "project_id": project_id,
            "priority": priority,
        }
        if bom_id:
            json_data["bom_id"] = bom_id
        if revision:
            json_data["revision"] = revision
        if notes:
            json_data["notes"] = notes

        try:
            return self._make_request('POST', '/manufacturing/dfm', json_data=json_data)
        except Exception as e:
            logger.error(f"DFM submission failed: {e}")
            raise

    def upload_dfm(
        self,
        file_data: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
        options: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Upload a gerber package for DFM analysis (file upload mode).

        Args:
            file_data: Raw file bytes (typically a ZIP of gerbers)
            filename: Original filename
            content_type: MIME type of the file
            options: Additional form fields (project_id, bom_id, priority, etc.)

        Returns:
            Submission result with job_id and status_url
        """
        logger.info(f"Uploading DFM file: {filename}")

        try:
            return self._make_upload_request(
                '/manufacturing/dfm',
                file_data=file_data,
                filename=filename,
                content_type=content_type,
                form_fields=options,
            )
        except Exception as e:
            logger.error(f"DFM upload failed: {e}")
            raise

    def get_manufacturing_status(self, job_id: str) -> dict[str, Any]:
        """Check manufacturing job status (DFM, AOI, QC, etc.).

        Args:
            job_id: Job ID returned from submit_dfm or upload_dfm

        Returns:
            Status with job_type, progress, and result when complete
        """
        logger.info(f"Checking manufacturing status: {job_id}")

        try:
            return self._make_request('GET', f'/manufacturing/{job_id}/status')
        except Exception as e:
            logger.error(f"Failed to get manufacturing status: {e}")
            raise

    # =========================================================================
    # Fabrication Endpoints
    # =========================================================================

    def create_fab_order(
        self,
        file_data: bytes | None = None,
        filename: str | None = None,
        content_type: str = "application/zip",
        project_id: str | None = None,
        quantity: int = 5,
        layers: int = 2,
        thickness: float = 1.6,
        surface_finish: str = "HASL",
        color: str = "green",
        priority: str = "normal",
    ) -> dict[str, Any]:
        """Create a fabrication order (file upload or project reference).

        Args:
            file_data: Raw gerber zip bytes (file upload mode)
            filename: Original filename (file upload mode)
            content_type: MIME type of the file
            project_id: Project ID (project reference mode)
            quantity: Number of boards
            layers: Number of PCB layers
            thickness: Board thickness in mm
            surface_finish: Surface finish type
            color: Solder mask color
            priority: Priority level

        Returns:
            Fab order result with job_id and status_url
        """
        specs = {
            "quantity": str(quantity),
            "layers": str(layers),
            "thickness": str(thickness),
            "surface_finish": surface_finish,
            "color": color,
            "priority": priority,
        }

        if file_data is not None and filename is not None:
            logger.info(f"Creating fab order with file upload: {filename}")
            try:
                return self._make_upload_request(
                    '/manufacturing/fab',
                    file_data=file_data,
                    filename=filename,
                    content_type=content_type,
                    form_fields=specs,
                )
            except Exception as e:
                logger.error(f"Fab order upload failed: {e}")
                raise
        elif project_id is not None:
            logger.info(f"Creating fab order for project: {project_id}")
            json_data = {"project_id": project_id, **specs}
            try:
                return self._make_request('POST', '/manufacturing/fab', json_data=json_data)
            except Exception as e:
                logger.error(f"Fab order creation failed: {e}")
                raise
        else:
            raise ValueError("Either file_data+filename or project_id must be provided")

    # =========================================================================
    # Cost Endpoints
    # =========================================================================

    def estimate_cost(
        self,
        parts: list[dict[str, Any]],
        currency: str = "USD",
    ) -> dict[str, Any]:
        """Get a quick cost estimate for a list of parts.

        Args:
            parts: List of parts with part_number and quantity
            currency: Currency code

        Returns:
            Cost estimate breakdown
        """
        logger.info(f"Estimating cost for {len(parts)} parts")

        json_data = {"parts": parts, "currency": currency}

        try:
            return self._make_request('POST', '/costs/estimate', json_data=json_data)
        except Exception as e:
            logger.error(f"Cost estimation failed: {e}")
            raise

    def calculate_cogs(
        self,
        source_type: str,
        source_value: str,
        build_quantity: int = 1,
        currency: str = "USD",
    ) -> dict[str, Any]:
        """Calculate Cost of Goods Sold.

        Args:
            source_type: Source type ("bom_id", "project_id", "part_number")
            source_value: The ID or value for the source type
            build_quantity: Number of assemblies to build
            currency: Currency code

        Returns:
            COGS breakdown with per-unit and total costs
        """
        logger.info(f"Calculating COGS: {source_type}={source_value}, qty={build_quantity}")

        json_data = {
            "source_type": source_type,
            "source_value": source_value,
            "build_quantity": build_quantity,
            "currency": currency,
        }

        try:
            return self._make_request('POST', '/costs/cogs', json_data=json_data)
        except Exception as e:
            logger.error(f"COGS calculation failed: {e}")
            raise

    # =========================================================================
    # Ingest / Identification Endpoints
    # =========================================================================

    def _make_ingest_request(
        self,
        file_data: bytes,
        filename: str,
        content_type: str = "image/jpeg",
        form_fields: dict[str, str] | None = None,
        retry_count: int = 3,
    ) -> dict[str, Any]:
        """Make a multipart ingest upload request with indexed file fields.

        The ingest API expects file_0, hash_0, file_count fields rather than
        a single 'file' field.

        Args:
            file_data: Raw file bytes
            filename: Name of the file being uploaded
            content_type: MIME type of the file
            form_fields: Additional form fields (project_id, box_id, etc.)
            retry_count: Number of retries on failure

        Returns:
            API response data
        """
        base = self.base_url if self.base_url.endswith('/') else self.base_url + '/'
        url = urljoin(base, 'ingest')

        file_hash = hashlib.sha256(file_data).hexdigest()

        for attempt in range(retry_count):
            try:
                self._rate_limit()

                extra_headers = {}
                user_sub = _mcp_user_sub.get()
                if user_sub:
                    extra_headers["X-MCP-User-Sub"] = user_sub

                upload_headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "User-Agent": "PARTS-MCP/1.0",
                    **extra_headers,
                }

                files = {"file_0": (filename, file_data, content_type)}
                data = {
                    "hash_0": file_hash,
                    "file_count": "1",
                    **(form_fields or {}),
                }

                response = httpx.request(
                    method="POST",
                    url=url,
                    files=files,
                    data=data,
                    headers=upload_headers,
                    timeout=SEARCH_TIMEOUT,
                )

                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 60))
                    if attempt < retry_count - 1:
                        logger.warning(f"Rate limited, waiting {retry_after}s")
                        time.sleep(retry_after)
                        continue
                    raise SourcePartsRateLimitError(f"Rate limit exceeded, retry after {retry_after}s")

                if response.status_code == 401:
                    raise SourcePartsAuthError("Invalid API key")
                elif response.status_code == 403:
                    raise SourcePartsAuthError("Access forbidden - check API permissions")

                response.raise_for_status()

                raw_response = response.json()

                if isinstance(raw_response, dict):
                    if raw_response.get("status") == "success" and "data" in raw_response:
                        return raw_response["data"]
                    elif raw_response.get("status") == "error":
                        error_msg = raw_response.get("error", "Unknown error")
                        raise SourcePartsAPIError(f"API error: {error_msg}")

                return raw_response

            except TimeoutException as e:
                if attempt < retry_count - 1:
                    logger.warning(f"Ingest upload timeout, retry {attempt + 1}/{retry_count}")
                    time.sleep(2 ** attempt)
                    continue
                raise SourcePartsAPIError("Ingest upload timeout") from e

            except RequestError as e:
                if attempt < retry_count - 1:
                    logger.warning(f"Ingest upload error: {e}, retry {attempt + 1}/{retry_count}")
                    time.sleep(2 ** attempt)
                    continue
                raise SourcePartsAPIError(f"Ingest upload error: {e}") from e

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

    def upload_for_identification(
        self,
        file_data: bytes,
        filename: str,
        content_type: str = "image/jpeg",
        project_id: str | None = None,
        box_id: str | None = None,
    ) -> dict[str, Any]:
        """Upload an image for PCB/component identification.

        Args:
            file_data: Raw image bytes
            filename: Original filename
            content_type: MIME type of the image
            project_id: Optional project ID to associate
            box_id: Optional box/shipment ID to associate

        Returns:
            Identification results with barcodes, OCR, metadata
        """
        logger.info(f"Uploading for identification: {filename}")

        form_fields: dict[str, str] = {}
        if project_id:
            form_fields["project_id"] = project_id
        if box_id:
            form_fields["box_id"] = box_id

        try:
            return self._make_ingest_request(
                file_data=file_data,
                filename=filename,
                content_type=content_type,
                form_fields=form_fields or None,
            )
        except Exception as e:
            logger.error(f"Identification upload failed: {e}")
            raise

    def get_ingest_status(self, job_id: str) -> dict[str, Any]:
        """Check ingest/identification job status.

        Args:
            job_id: Job ID returned from upload_for_identification

        Returns:
            Status with progress and items when complete
        """
        logger.info(f"Checking ingest status: {job_id}")

        try:
            return self._make_request('GET', f'/ingest/{job_id}/status')
        except Exception as e:
            logger.error(f"Failed to get ingest status: {e}")
            raise

    def get_ingest_item(self, short_code: str) -> dict[str, Any]:
        """Get details for an identified item by short code.

        Args:
            short_code: Item short code (e.g., SP-XXXXXX)

        Returns:
            Item details with barcodes, OCR text, metadata
        """
        logger.info(f"Getting ingest item: {short_code}")

        try:
            return self._make_request('GET', f'/ingest/items/{short_code}')
        except Exception as e:
            logger.error(f"Failed to get ingest item: {e}")
            raise


def with_user_context(fn):
    """Decorator for MCP tool handlers — propagates Auth0 sub to API requests."""
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            from fastmcp.server.dependencies import get_access_token
            token = get_access_token()
            sub = token.claims.get("sub") if token else None
        except Exception:
            sub = None

        if sub:
            reset_token = _mcp_user_sub.set(sub)
            try:
                return await fn(*args, **kwargs)
            finally:
                _mcp_user_sub.reset(reset_token)
        else:
            return await fn(*args, **kwargs)
    return wrapper


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
