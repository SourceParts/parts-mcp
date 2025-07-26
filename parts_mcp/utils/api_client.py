"""
Source Parts API client for electronic component searching.
"""
import logging
import time
from typing import Dict, List, Any, Optional
from urllib.parse import urljoin, urlencode
import httpx
from httpx import HTTPStatusError, RequestError, TimeoutException

from parts_mcp.config import (
    SOURCE_PARTS_API_KEY,
    SOURCE_PARTS_API_URL,
    SEARCH_TIMEOUT,
    DEFAULT_PAGE_SIZE,
    MAX_RESULTS
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
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
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
                "User-Agent": "parts-mcp/1.0"
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
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        retry_count: int = 3
    ) -> Dict[str, Any]:
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
        url = urljoin(self.base_url, endpoint.lstrip('/'))
        
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
                return response.json()
                
            except TimeoutException:
                if attempt < retry_count - 1:
                    logger.warning(f"Request timeout, retry {attempt + 1}/{retry_count}")
                    time.sleep(2 ** attempt)  # Exponential backoff
                    continue
                raise SourcePartsAPIError("Request timeout")
                
            except RequestError as e:
                if attempt < retry_count - 1:
                    logger.warning(f"Request error: {e}, retry {attempt + 1}/{retry_count}")
                    time.sleep(2 ** attempt)
                    continue
                raise SourcePartsAPIError(f"Request error: {e}")
                
            except HTTPStatusError as e:
                error_detail = ""
                try:
                    error_data = e.response.json()
                    error_detail = error_data.get('message', error_data.get('error', ''))
                except:
                    error_detail = e.response.text
                    
                raise SourcePartsAPIError(
                    f"API error {e.response.status_code}: {error_detail or e}"
                )
                
    def search_parts(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE
    ) -> Dict[str, Any]:
        """Search for electronic parts.
        
        Args:
            query: Search query string
            filters: Optional filters (category, parameters, etc.)
            page: Page number (1-indexed)
            page_size: Results per page
            
        Returns:
            Search results with parts data
        """
        params = {
            'q': query,
            'page': page,
            'limit': min(page_size, MAX_RESULTS)
        }
        
        # Add filters if provided
        if filters:
            for key, value in filters.items():
                if value is not None:
                    params[key] = value
                    
        logger.info(f"Searching parts: query='{query}', page={page}")
        
        try:
            response = self._make_request('GET', '/parts/search', params=params)
            
            # Standardize response format
            return {
                'results': response.get('parts', response.get('results', [])),
                'total': response.get('total', len(response.get('parts', []))),
                'page': page,
                'page_size': page_size,
                'query': query,
                'filters': filters or {}
            }
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise
            
    def get_part_details(self, part_id: str) -> Dict[str, Any]:
        """Get detailed information about a specific part.
        
        Args:
            part_id: Part identifier
            
        Returns:
            Detailed part information
        """
        logger.info(f"Getting details for part: {part_id}")
        
        try:
            return self._make_request('GET', f'/parts/{part_id}')
        except Exception as e:
            logger.error(f"Failed to get part details: {e}")
            raise
            
    def get_part_pricing(
        self,
        part_id: str,
        quantity: int = 1,
        currency: str = 'USD'
    ) -> Dict[str, Any]:
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
            
    def get_part_availability(self, part_id: str) -> Dict[str, Any]:
        """Get availability information for a part.
        
        Args:
            part_id: Part identifier
            
        Returns:
            Stock and availability data
        """
        logger.info(f"Getting availability for part: {part_id}")
        
        try:
            return self._make_request('GET', f'/parts/{part_id}/availability')
        except Exception as e:
            logger.error(f"Failed to get availability: {e}")
            raise
            
    def search_by_parameters(
        self,
        category: str,
        parameters: Dict[str, Any],
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE
    ) -> Dict[str, Any]:
        """Search parts by parametric specifications.
        
        Args:
            category: Part category
            parameters: Parameter filters
            page: Page number
            page_size: Results per page
            
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
        
        return self.search_parts(query, page=page, page_size=page_size)
        
    def find_alternatives(
        self,
        part_number: str,
        match_parameters: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Find alternative parts for a given part number.
        
        Args:
            part_number: Original part number
            match_parameters: Parameters that must match
            
        Returns:
            Alternative parts suggestions
        """
        logger.info(f"Finding alternatives for: {part_number}")
        
        params = {
            'part_number': part_number
        }
        
        if match_parameters:
            params['match'] = ','.join(match_parameters)
            
        try:
            return self._make_request('GET', '/parts/alternatives', params=params)
        except Exception as e:
            logger.error(f"Failed to find alternatives: {e}")
            raise
            
    def batch_search(self, part_numbers: List[str]) -> Dict[str, Any]:
        """Search for multiple parts in one request.
        
        Args:
            part_numbers: List of part numbers to search
            
        Returns:
            Results for each part number
        """
        logger.info(f"Batch searching {len(part_numbers)} parts")
        
        try:
            return self._make_request(
                'POST',
                '/parts/batch-search',
                json_data={'part_numbers': part_numbers}
            )
        except Exception as e:
            logger.error(f"Batch search failed: {e}")
            raise


# Singleton instance for reuse
_client_instance: Optional[SourcePartsClient] = None


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