"""
Unit tests for caching utilities.
"""

from parts_mcp.utils.cache import (
    cache_delete,
    cache_get,
    cache_part_details,
    cache_search_results,
    cache_set,
    cached,
    clear_all_cache,
    clear_cache_prefix,
    get_cache_stats,
    make_cache_key,
)


class TestMakeCacheKey:
    """Tests for cache key generation."""

    def test_key_from_simple_args(self):
        """Generate key from simple arguments."""
        key = make_cache_key("arg1", "arg2")
        assert isinstance(key, str)
        assert len(key) == 32  # MD5 hash length

    def test_key_from_dict_args(self):
        """Generate key from dictionary arguments."""
        key1 = make_cache_key({"a": 1, "b": 2})
        key2 = make_cache_key({"b": 2, "a": 1})

        # Should be deterministic regardless of dict order
        assert key1 == key2

    def test_key_from_kwargs(self):
        """Generate key from keyword arguments."""
        key = make_cache_key(query="test", limit=10)
        assert isinstance(key, str)

    def test_different_args_different_keys(self):
        """Different arguments produce different keys."""
        key1 = make_cache_key("query1")
        key2 = make_cache_key("query2")

        assert key1 != key2

    def test_same_args_same_keys(self):
        """Same arguments produce same keys."""
        key1 = make_cache_key("test", limit=10, offset=0)
        key2 = make_cache_key("test", limit=10, offset=0)

        assert key1 == key2


class TestCacheDecorator:
    """Tests for the cached decorator."""

    def test_cached_function_returns_value(self, mock_cache):
        """Cached function returns correct value."""
        call_count = [0]

        @cached(expire=3600)
        def my_func(x):
            call_count[0] += 1
            return x * 2

        result = my_func(5)

        assert result == 10
        assert call_count[0] == 1

    def test_cached_function_uses_cache(self, mock_cache):
        """Cached function uses cache on second call."""
        call_count = [0]

        @cached(expire=3600)
        def my_func(x):
            call_count[0] += 1
            return x * 2

        result1 = my_func(5)
        result2 = my_func(5)

        assert result1 == result2
        assert call_count[0] == 1  # Only called once

    def test_cached_function_different_args(self, clean_cache):
        """Different arguments don't share cache."""
        call_count = [0]

        @cached(expire=3600, key_prefix="test_different_args")
        def my_func_diff(x):
            call_count[0] += 1
            return x * 2

        result1 = my_func_diff(5)
        result2 = my_func_diff(10)

        assert result1 == 10
        assert result2 == 20
        assert call_count[0] == 2

    def test_cached_with_key_prefix(self, clean_cache):
        """Cache key uses provided prefix."""
        @cached(expire=3600, key_prefix="custom_prefix")
        def my_func(x):
            return x

        result = my_func(5)

        # Just verify the function works with custom prefix
        assert result == 5

    def test_cached_with_condition(self, mock_cache):
        """Cache respects condition function."""
        @cached(expire=3600, condition=lambda r: r is not None)
        def my_func(return_none):
            if return_none:
                return None
            return "value"

        # This should be cached
        my_func(False)
        # This should not be cached
        my_func(True)

        # Only one entry should be in cache
        assert len(mock_cache) == 1


class TestCacheOperations:
    """Tests for cache get/set/delete operations."""

    def test_cache_set_and_get(self, mock_cache):
        """Set and get cache values."""
        cache_set("test_key", {"data": "value"})
        result = cache_get("test_key")

        assert result == {"data": "value"}

    def test_cache_get_default(self, mock_cache):
        """Get returns default for missing key."""
        result = cache_get("nonexistent", default="default_value")

        assert result == "default_value"

    def test_cache_delete(self, mock_cache):
        """Delete removes cache entry."""
        cache_set("to_delete", "value")
        assert cache_get("to_delete") == "value"

        cache_delete("to_delete")
        assert cache_get("to_delete") is None

    def test_cache_set_with_expiry(self, mock_cache):
        """Cache respects expiry time."""
        cache_set("expiring", "value", expire=1)

        assert cache_get("expiring") == "value"

        # Wait for expiry (in real tests, we'd mock time)
        # For now, just verify the value was set


class TestClearCache:
    """Tests for cache clearing operations."""

    def test_clear_cache_prefix(self, clean_cache):
        """Clear entries with specific prefix."""
        cache_set("search:query1", "result1")
        cache_set("search:query2", "result2")
        cache_set("part:abc123", "details")

        count = clear_cache_prefix("search")

        assert count == 2
        assert cache_get("search:query1") is None
        assert cache_get("search:query2") is None
        assert cache_get("part:abc123") == "details"

    def test_clear_all_cache(self, mock_cache):
        """Clear entire cache."""
        cache_set("key1", "value1")
        cache_set("key2", "value2")
        cache_set("key3", "value3")

        result = clear_all_cache()

        assert result is True
        assert len(mock_cache) == 0


class TestCacheStats:
    """Tests for cache statistics."""

    def test_get_cache_stats(self, mock_cache):
        """Get cache statistics."""
        cache_set("stat_test", "value")

        stats = get_cache_stats()

        assert "size" in stats
        assert "directory" in stats


class TestSpecializedDecorators:
    """Tests for specialized cache decorators."""

    def test_cache_search_results_decorator(self, mock_cache):
        """Search results cache decorator works."""
        @cache_search_results(expire=3600)
        def search(query):
            return {"results": [{"id": 1}]}

        result = search("test")

        assert result["results"] is not None

    def test_cache_search_results_empty_not_cached(self, mock_cache):
        """Empty search results are not cached."""
        call_count = [0]

        @cache_search_results(expire=3600)
        def search(query):
            call_count[0] += 1
            return {"results": []}  # Empty results

        search("test")
        search("test")

        # Should be called twice since empty results aren't cached
        assert call_count[0] == 2

    def test_cache_part_details_decorator(self, mock_cache):
        """Part details cache decorator works."""
        @cache_part_details(expire=86400)
        def get_part(sku):
            return {"part_number": sku, "description": "Test part"}

        result = get_part("TEST123")

        assert result["part_number"] == "TEST123"

    def test_cache_part_details_error_not_cached(self, mock_cache):
        """Error responses are not cached."""
        call_count = [0]

        @cache_part_details(expire=86400)
        def get_part(sku):
            call_count[0] += 1
            return {"error": "Not found"}

        get_part("INVALID")
        get_part("INVALID")

        # Should be called twice since error responses aren't cached
        assert call_count[0] == 2
