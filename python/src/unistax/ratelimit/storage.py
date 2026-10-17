"""Storage backends for rate limiting."""

from abc import ABC, abstractmethod
from typing import Any


class Storage(ABC):
    """Abstract storage backend for rate limiting."""

    @abstractmethod
    def increment(self, key: str, window: int) -> int:
        """Increment counter for key within window."""
        pass

    @abstractmethod
    def get(self, key: str) -> int:
        """Get current count for key."""
        pass

    @abstractmethod
    def reset(self, key: str) -> None:
        """Reset counter for key."""
        pass


class InMemoryStorage(Storage):
    """In-memory storage backend (not suitable for distributed systems)."""

    def __init__(self) -> None:
        """Initialize in-memory storage."""
        self._store: dict[str, int] = {}

    def increment(self, key: str, window: int) -> int:
        """Increment counter for key."""
        self._store[key] = self._store.get(key, 0) + 1
        return self._store[key]

    def get(self, key: str) -> int:
        """Get current count for key."""
        return self._store.get(key, 0)

    def reset(self, key: str) -> None:
        """Reset counter for key."""
        if key in self._store:
            del self._store[key]

    def delete(self, key: str) -> None:
        """Delete the counter for key."""
        self.reset(key)

    def clear(self) -> None:
        """Delete all counters."""
        self._store.clear()


class RedisStorage(Storage):
    """Redis storage backend for distributed rate limiting."""

    def __init__(self, host: str = "localhost", port: int = 6379, **kwargs: Any) -> None:
        """Initialize Redis storage."""
        try:
            import redis  # type: ignore[import-untyped]

            self._redis = redis.Redis(host=host, port=port, **kwargs)
        except ImportError as e:
            raise ImportError("Redis support requires 'redis' package") from e

    def increment(self, key: str, window: int) -> int:
        """Increment counter for key within window."""
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window)
        result = pipe.execute()
        return int(result[0])

    def get(self, key: str) -> int:
        """Get current count for key."""
        value = self._redis.get(key)
        return int(value) if value else 0

    def reset(self, key: str) -> None:
        """Reset counter for key."""
        self._redis.delete(key)
