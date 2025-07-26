"""
Caching utilities for Parts MCP using diskcache.
"""
import logging
import hashlib
import json
from typing import Any, Optional, Callable
from functools import wraps
import diskcache

from parts_mcp.config import CACHE_DIR, CACHE_EXPIRY_HOURS

logger = logging.getLogger(__name__)

# Initialize cache
cache = diskcache.Cache(str(CACHE_DIR))

# Cache expiry in seconds
DEFAULT_EXPIRY = CACHE_EXPIRY_HOURS * 3600


def make_cache_key(*args, **kwargs) -> str:
    """Generate a cache key from function arguments.
    
    Args:
        *args: Positional arguments
        **kwargs: Keyword arguments
        
    Returns:
        Cache key string
    """
    # Create a string representation of all arguments
    key_parts = []
    
    # Add positional arguments
    for arg in args:
        if isinstance(arg, (dict, list)):
            key_parts.append(json.dumps(arg, sort_keys=True))
        else:
            key_parts.append(str(arg))
            
    # Add keyword arguments
    for k, v in sorted(kwargs.items()):
        if isinstance(v, (dict, list)):
            key_parts.append(f"{k}={json.dumps(v, sort_keys=True)}")
        else:
            key_parts.append(f"{k}={v}")
            
    # Create hash of the key
    key_string = "|".join(key_parts)
    return hashlib.md5(key_string.encode()).hexdigest()


def cached(
    expire: Optional[int] = DEFAULT_EXPIRY,
    key_prefix: Optional[str] = None,
    condition: Optional[Callable] = None
):
    """Decorator to cache function results.
    
    Args:
        expire: Cache expiry in seconds
        key_prefix: Prefix for cache keys
        condition: Optional function to determine if result should be cached
        
    Returns:
        Decorated function
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            cache_key = make_cache_key(*args[1:], **kwargs)  # Skip 'self' if present
            
            if key_prefix:
                cache_key = f"{key_prefix}:{cache_key}"
            else:
                cache_key = f"{func.__name__}:{cache_key}"
                
            # Try to get from cache
            try:
                cached_value = cache.get(cache_key)
                if cached_value is not None:
                    logger.debug(f"Cache hit for {cache_key}")
                    return cached_value
            except Exception as e:
                logger.warning(f"Cache get error: {e}")
                
            # Call the function
            result = func(*args, **kwargs)
            
            # Cache the result if it meets conditions
            try:
                if condition is None or condition(result):
                    cache.set(cache_key, result, expire=expire)
                    logger.debug(f"Cached result for {cache_key}")
            except Exception as e:
                logger.warning(f"Cache set error: {e}")
                
            return result
            
        # Add cache management methods
        wrapper.cache_clear = lambda: clear_cache_prefix(
            key_prefix or func.__name__
        )
        wrapper.cache_key = lambda *a, **kw: f"{key_prefix or func.__name__}:{make_cache_key(*a, **kw)}"
        
        return wrapper
    return decorator


def cache_get(key: str, default: Any = None) -> Any:
    """Get a value from cache.
    
    Args:
        key: Cache key
        default: Default value if not found
        
    Returns:
        Cached value or default
    """
    try:
        value = cache.get(key)
        return value if value is not None else default
    except Exception as e:
        logger.error(f"Cache get error for {key}: {e}")
        return default


def cache_set(key: str, value: Any, expire: Optional[int] = DEFAULT_EXPIRY) -> bool:
    """Set a value in cache.
    
    Args:
        key: Cache key
        value: Value to cache
        expire: Expiry time in seconds
        
    Returns:
        True if successful
    """
    try:
        cache.set(key, value, expire=expire)
        return True
    except Exception as e:
        logger.error(f"Cache set error for {key}: {e}")
        return False


def cache_delete(key: str) -> bool:
    """Delete a value from cache.
    
    Args:
        key: Cache key
        
    Returns:
        True if successful
    """
    try:
        cache.delete(key)
        return True
    except Exception as e:
        logger.error(f"Cache delete error for {key}: {e}")
        return False


def clear_cache_prefix(prefix: str) -> int:
    """Clear all cache entries with a given prefix.
    
    Args:
        prefix: Key prefix to clear
        
    Returns:
        Number of entries cleared
    """
    try:
        count = 0
        for key in list(cache.keys()):
            if key.startswith(prefix):
                cache.delete(key)
                count += 1
        logger.info(f"Cleared {count} cache entries with prefix '{prefix}'")
        return count
    except Exception as e:
        logger.error(f"Error clearing cache prefix {prefix}: {e}")
        return 0


def clear_all_cache() -> bool:
    """Clear entire cache.
    
    Returns:
        True if successful
    """
    try:
        cache.clear()
        logger.info("Cleared entire cache")
        return True
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        return False


def get_cache_stats() -> dict:
    """Get cache statistics.
    
    Returns:
        Dictionary with cache stats
    """
    try:
        return {
            'size': len(cache),
            'volume': cache.volume(),
            'directory': str(CACHE_DIR),
            'hits': cache.stats(enable=True)[0],
            'misses': cache.stats(enable=True)[1]
        }
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        return {
            'size': 0,
            'volume': 0,
            'directory': str(CACHE_DIR),
            'error': str(e)
        }


# Specific cache decorators for different data types

def cache_search_results(expire: int = 3600):
    """Cache search results for 1 hour by default."""
    return cached(
        expire=expire,
        key_prefix="search",
        condition=lambda r: r and r.get('results')
    )


def cache_part_details(expire: int = 86400):
    """Cache part details for 24 hours by default."""
    return cached(
        expire=expire,
        key_prefix="part",
        condition=lambda r: r and not r.get('error')
    )


def cache_pricing_data(expire: int = 1800):
    """Cache pricing data for 30 minutes by default."""
    return cached(
        expire=expire,
        key_prefix="pricing",
        condition=lambda r: r and r.get('suppliers')
    )


def cache_bom_analysis(expire: int = 3600):
    """Cache BOM analysis for 1 hour by default."""
    return cached(
        expire=expire,
        key_prefix="bom",
        condition=lambda r: r and r.get('success')
    )