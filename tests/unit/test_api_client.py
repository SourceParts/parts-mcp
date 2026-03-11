"""
Unit tests for the Source Parts API client.
"""
import time
from unittest.mock import MagicMock, patch

import pytest

from parts_mcp.utils.api_client import (
    SourcePartsAPIError,
    SourcePartsAuthError,
    SourcePartsClient,
    SourcePartsRateLimitError,
    close_client,
    get_client,
)


class TestSourcePartsClientInit:
    """Tests for client initialization."""

    def test_init_with_api_key(self):
        """Client initializes with provided API key."""
        with patch('parts_mcp.utils.api_client.httpx.Client'):
            client = SourcePartsClient(api_key="test-key")
            assert client.api_key == "test-key"

    def test_init_without_api_key_raises_error(self):
        """Client raises error when no API key is provided."""
        with patch.dict('os.environ', {'SOURCE_PARTS_API_KEY': ''}):
            with pytest.raises(SourcePartsAuthError, match="No API key"):
                SourcePartsClient(api_key="")

    def test_init_uses_correct_base_url(self):
        """Client uses the correct default base URL."""
        with patch('parts_mcp.utils.api_client.httpx.Client'):
            client = SourcePartsClient(api_key="test-key")
            assert "api.source.parts" in client.base_url

    def test_init_custom_base_url(self):
        """Client accepts custom base URL."""
        with patch('parts_mcp.utils.api_client.httpx.Client'):
            client = SourcePartsClient(
                api_key="test-key",
                base_url="https://custom.api.com/v1"
            )
            assert client.base_url == "https://custom.api.com/v1"


class TestAPIRequestHandling:
    """Tests for API request handling."""

    def test_envelope_unwrapping_success(self, mock_api_client, mock_api_response):
        """API response envelope is properly unwrapped."""
        mock_api_client._mock_response.json.return_value = {
            "status": "success",
            "data": {"parts": [], "total": 0}
        }

        result = mock_api_client._make_request('GET', '/parts/search')

        assert "parts" in result
        assert result["total"] == 0
        # Verify envelope is unwrapped (no "status" or "data" keys at top level)
        assert "status" not in result
        assert "data" not in result

    def test_envelope_unwrapping_error(self, mock_api_client):
        """API error responses raise appropriate exceptions."""
        mock_api_client._mock_response.json.return_value = {
            "status": "error",
            "error": "Invalid request"
        }

        with pytest.raises(SourcePartsAPIError, match="Invalid request"):
            mock_api_client._make_request('GET', '/parts/search')

    def test_rate_limiting_applied(self, mock_api_client):
        """Rate limiting enforces minimum interval between requests."""
        mock_api_client._mock_response.json.return_value = {"status": "success", "data": {}}
        mock_api_client._min_request_interval = 0.05  # 50ms for testing

        start = time.time()
        mock_api_client._make_request('GET', '/test1')
        mock_api_client._make_request('GET', '/test2')
        elapsed = time.time() - start

        assert elapsed >= 0.05

    def test_rate_limit_response_429(self, mock_api_client):
        """429 responses trigger rate limit handling."""
        mock_api_client._mock_response.status_code = 429
        mock_api_client._mock_response.headers = {'Retry-After': '1'}

        with pytest.raises(SourcePartsRateLimitError):
            mock_api_client._make_request('GET', '/parts/search', retry_count=1)

    def test_auth_error_401(self, mock_api_client):
        """401 responses raise auth error."""
        mock_api_client._mock_response.status_code = 401

        with pytest.raises(SourcePartsAuthError, match="Invalid API key"):
            mock_api_client._make_request('GET', '/parts/search')

    def test_auth_error_403(self, mock_api_client):
        """403 responses raise auth error."""
        mock_api_client._mock_response.status_code = 403

        with pytest.raises(SourcePartsAuthError, match="Access forbidden"):
            mock_api_client._make_request('GET', '/parts/search')


class TestSearchParts:
    """Tests for search_parts method."""

    def test_search_parts_basic(self, mock_api_client, mock_api_response, sample_parts):
        """Basic part search returns results."""
        mock_api_client._mock_response.json.return_value = mock_api_response.search_results(
            parts=sample_parts,
            query="STM32"
        )

        result = mock_api_client.search_parts("STM32")

        assert "results" in result
        assert len(result["results"]) == len(sample_parts)
        assert result["query"] == "STM32"

    def test_search_parts_with_filters(self, mock_api_client, mock_api_response):
        """Search with filters passes them to API."""
        mock_api_client._mock_response.json.return_value = mock_api_response.search_results(
            parts=[],
            query="test"
        )

        mock_api_client.search_parts(
            "resistor",
            filters={"category": "Resistors", "manufacturer": "Yageo"}
        )

        # Verify filters were passed in request params
        call_kwargs = mock_api_client._mock_http.request.call_args
        params = call_kwargs.kwargs.get('params', {})
        assert params.get('category') == "Resistors"
        assert params.get('manufacturer') == "Yageo"

    def test_search_parts_pagination(self, mock_api_client, mock_api_response):
        """Search uses offset/limit pagination."""
        mock_api_client._mock_response.json.return_value = mock_api_response.search_results(
            parts=[],
            query="test",
            limit=50,
            offset=100
        )

        mock_api_client.search_parts("test", limit=50, offset=100)

        call_kwargs = mock_api_client._mock_http.request.call_args
        params = call_kwargs.kwargs.get('params', {})
        assert params.get('limit') == 50
        assert params.get('offset') == 100


class TestGetPartDetails:
    """Tests for get_part_details method."""

    def test_get_part_by_sku(self, mock_api_client, mock_api_response):
        """Get part details by SKU."""
        mock_api_client._mock_response.json.return_value = mock_api_response.part_details(
            part_number="STM32F407VGT6"
        )

        result = mock_api_client.get_part_details("STM32F407VGT6")

        assert result["part_number"] == "STM32F407VGT6"

        # Verify correct endpoint called
        call_kwargs = mock_api_client._mock_http.request.call_args
        assert "/parts/STM32F407VGT6" in call_kwargs.kwargs.get('url', '')


class TestGetPartInventory:
    """Tests for get_part_inventory method."""

    def test_get_part_inventory(self, mock_api_client, mock_api_response):
        """Get inventory for a part."""
        mock_api_client._mock_response.json.return_value = mock_api_response.inventory(
            part_number="STM32F407VGT6",
            quantity=150
        )

        result = mock_api_client.get_part_inventory("STM32F407VGT6")

        assert result["part_number"] == "STM32F407VGT6"
        assert result["quantity"] == 150

    def test_get_part_availability_alias(self, mock_api_client, mock_api_response):
        """get_part_availability is an alias for get_part_inventory."""
        mock_api_client._mock_response.json.return_value = mock_api_response.inventory()

        mock_api_client.get_part_availability("TEST123")

        # Should call the inventory endpoint
        call_kwargs = mock_api_client._mock_http.request.call_args
        assert "/inventory" in call_kwargs.kwargs.get('url', '')


class TestBatchSearch:
    """Tests for batch_search method."""

    def test_batch_search_found_parts(self, mock_api_client, mock_api_response, sample_parts):
        """Batch search returns found and not found parts."""
        # Configure mock to return different responses based on part number
        def mock_request(method, url, **kwargs):
            response = MagicMock()
            response.status_code = 200
            if "STM32F407VGT6" in url:
                response.json.return_value = mock_api_response.part_details(
                    part_number="STM32F407VGT6"
                )
            else:
                response.json.return_value = mock_api_response.error("Not found")
            return response

        mock_api_client._mock_http.request.side_effect = mock_request

        result = mock_api_client.batch_search(["STM32F407VGT6", "INVALID123"])

        assert "STM32F407VGT6" in result["found"]
        assert "INVALID123" in result["not_found"]
        assert result["total_requested"] == 2


class TestFindAlternatives:
    """Tests for find_alternatives method."""

    def test_find_alternatives_with_category(self, mock_api_client, mock_api_response, sample_parts):
        """Find alternatives searches by category."""
        # First call returns part details
        # Second call returns search results
        call_count = [0]

        def mock_request(method, url, **kwargs):
            response = MagicMock()
            response.status_code = 200
            call_count[0] += 1
            if call_count[0] == 1:
                response.json.return_value = mock_api_response.part_details(
                    part_number="STM32F407VGT6",
                    category="Microcontrollers"
                )
            else:
                response.json.return_value = mock_api_response.search_results(
                    parts=sample_parts
                )
            return response

        mock_api_client._mock_http.request.side_effect = mock_request

        result = mock_api_client.find_alternatives("STM32F407VGT6")

        assert result["original"] is not None
        assert "alternatives" in result


class TestSingletonClient:
    """Tests for singleton client management."""

    def test_get_client_returns_same_instance(self):
        """get_client returns the same instance."""
        with patch('parts_mcp.utils.api_client.httpx.Client'):
            with patch('parts_mcp.utils.api_client.SOURCE_PARTS_API_KEY', 'test-key'):
                client1 = get_client()
                client2 = get_client()
                assert client1 is client2

    def test_close_client_clears_singleton(self):
        """close_client clears the singleton instance."""
        with patch('parts_mcp.utils.api_client.httpx.Client'):
            with patch('parts_mcp.utils.api_client.SOURCE_PARTS_API_KEY', 'test-key'):
                client1 = get_client()
                close_client()
                client2 = get_client()
                assert client1 is not client2
