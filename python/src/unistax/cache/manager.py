"""Cache manager implementation.

Provides unified interface for caching with multiple backends.
"""

import json
import logging
import pickle
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .backends import CacheBackend, InMemoryCache, MemcachedBackend, RedisBackend

logger = logging.getLogger(__name__)


class CacheManager:
    """Unified cache manager supporting multiple backends.

    Examples:
        >>> cache = CacheManager(backend="redis")
        >>> cache.set("user:123", user_data, ttl=3600)
        >>> user = cache.get("user:123")
        >>> cache.delete("user:*")  # Pattern-based deletion
    """

    def __init__(
        self,
        backend: str | CacheBackend = "memory",
        prefix: str = "",
        serializer: str = "json",
        compress: bool = False,
    ) -> None:
        """Initialize cache manager.

        Args:
            backend: Backend type or instance ("redis", "memcached", "memory")
            prefix: Key prefix for all cache operations
            serializer: Serialization method ("json", "pickle")
            compress: Whether to compress cached values
        """
        if isinstance(backend, str):
            self._backend = self._create_backend(backend)
        else:
            self._backend = backend

        self._prefix = prefix
        self._serializer = serializer
        self._compress = compress

    @classmethod
    def from_yaml(cls, path: str | Path) -> "CacheManager":
        """Create cache manager from YAML configuration.

        Args:
            path: Path to YAML config

        Returns:
            Configured cache manager
        """
        from ..config import ConfigManager

        config = ConfigManager.from_yaml(path)
        backend_type = config.get("cache.backend", "memory")
        prefix = config.get("cache.prefix", "")
        serializer = config.get("cache.serializer", "json")
        compress = config.get_bool("cache.compress", False)

        # Backend-specific configuration
        backend_config = config.get_dict("cache.backend_config", {})

        backend: CacheBackend
        if backend_type == "redis":
            backend = RedisBackend(**backend_config)
        elif backend_type == "memcached":
            backend = MemcachedBackend(**backend_config)
        else:
            backend = InMemoryCache()

        return cls(backend=backend, prefix=prefix, serializer=serializer, compress=compress)

    def _create_backend(self, backend_type: str) -> CacheBackend:
        """Create cache backend by type."""
        if backend_type == "redis":
            return RedisBackend()
        elif backend_type == "memcached":
            return MemcachedBackend()
        else:
            return InMemoryCache()

    def _format_key(self, key: str) -> str:
        """Format key with prefix."""
        if self._prefix:
            return f"{self._prefix}:{key}"
        return key

    def _serialize(self, value: Any) -> bytes:
        """Serialize value."""
        if self._serializer == "pickle":
            data = pickle.dumps(value)
        else:  # json
            data = json.dumps(value).encode("utf-8")

        if self._compress:
            import gzip

            data = gzip.compress(data)

        return data

    def _deserialize(self, data: bytes) -> Any:
        """Deserialize value."""
        if self._compress:
            import gzip

            data = gzip.decompress(data)

        if self._serializer == "pickle":
            return pickle.loads(data)
        else:  # json
            return json.loads(data.decode("utf-8"))

    def get(self, key: str, default: Any = None) -> Any:
        """Get value from cache.

        Args:
            key: Cache key
            default: Default value if not found

        Returns:
            Cached value or default
        """
        formatted_key = self._format_key(key)
        data = self._backend.get(formatted_key)

        if data is None:
            return default

        try:
            return self._deserialize(data)
        except Exception as e:
            logger.warning(
                "Failed to deserialize cached value for key %s: %s",
                key,
                e,
                exc_info=True,
            )
            return default

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds

        Returns:
            True if successful
        """
        formatted_key = self._format_key(key)
        data = self._serialize(value)
        return self._backend.set(formatted_key, data, ttl)

    def delete(self, key: str) -> bool:
        """Delete value from cache.

        Args:
            key: Cache key (supports patterns like "user:*")

        Returns:
            True if deleted
        """
        formatted_key = self._format_key(key)
        return self._backend.delete(formatted_key)

    def exists(self, key: str) -> bool:
        """Check if key exists in cache.

        Args:
            key: Cache key

        Returns:
            True if exists
        """
        formatted_key = self._format_key(key)
        return self._backend.exists(formatted_key)

    def clear(self) -> bool:
        """Clear all cache entries.

        Returns:
            True if successful
        """
        return self._backend.clear()

    def memoize(
        self,
        ttl: int | None = None,
        key_prefix: str = "",
        key_func: Callable[..., Any] | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator for memoizing function results.

        Args:
            ttl: Time to live in seconds
            key_prefix: Prefix for cache keys
            key_func: Custom function to generate cache key

        Examples:
            >>> @cache.memoize(ttl=3600, key_prefix="user")
            ... def get_user(user_id):
            ...     return db.query(user_id)
        """
        from functools import wraps

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                # Generate cache key
                if key_func:
                    cache_key = key_func(*args, **kwargs)
                else:
                    # Use function name and arguments
                    key_parts = [key_prefix or func.__name__]
                    if args:
                        key_parts.extend(str(arg) for arg in args)
                    if kwargs:
                        key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                    cache_key = ":".join(key_parts)

                # Try to get from cache
                cached_value = self.get(cache_key)
                if cached_value is not None:
                    return cached_value

                # Call function and cache result
                result = func(*args, **kwargs)
                self.set(cache_key, result, ttl)
                return result

            # Add cache control methods
            wrapper.cache_clear = lambda: self.delete(f"{key_prefix or func.__name__}:*")  # type: ignore[attr-defined]
            wrapper.cache_info = lambda: {"backend": type(self._backend).__name__}  # type: ignore[attr-defined]

            return wrapper

        return decorator

    def get_or_set(self, key: str, factory: Callable[..., Any], ttl: int | None = None) -> Any:
        """Get value from cache or set it using factory function.

        Args:
            key: Cache key
            factory: Function to generate value if not cached
            ttl: Time to live in seconds

        Returns:
            Cached or generated value
        """
        value = self.get(key)
        if value is not None:
            return value

        value = factory()
        self.set(key, value, ttl)
        return value


# Global cache instance
_global_cache: CacheManager | None = None


def get_cache() -> CacheManager:
    """Get global cache instance."""
    global _global_cache
    if _global_cache is None:
        _global_cache = CacheManager()
    return _global_cache


def set_cache(cache: CacheManager) -> None:
    """Set global cache instance."""
    global _global_cache
    _global_cache = cache


# Convenience alias
Cache = get_cache
