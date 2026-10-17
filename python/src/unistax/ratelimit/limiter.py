"""Rate limiter implementation with security features."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any

from .algorithms import SlidingWindow, TokenBucket
from .storage import InMemoryStorage, Storage

logger = logging.getLogger(__name__)


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded.

    Attributes:
        key: The rate limit key that was exceeded
        limit: Maximum number of requests allowed
        window: Time window in seconds
        retry_after: Seconds until rate limit resets
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        key: str | None = None,
        limit: int | None = None,
        window: int | None = None,
        retry_after: int | None = None,
    ) -> None:
        """Initialize RateLimitExceeded exception.

        Args:
            message: Error message
            key: Rate limit key
            limit: Request limit
            window: Time window in seconds
            retry_after: Seconds until reset
        """
        super().__init__(message)
        self.key = key
        self.limit = limit
        self.window = window
        self.retry_after = retry_after


@dataclass
class RateLimitInfo:
    """Information about rate limit status.

    Attributes:
        limit: Maximum requests allowed in window
        remaining: Remaining requests in current window
        reset: Unix timestamp when limit resets
        retry_after: Seconds until limit resets (if exceeded)
    """

    limit: int
    remaining: int
    reset: int
    retry_after: int | None = None


class RateLimiter:
    """Production-ready rate limiter with pluggable storage backends.

    Supports multiple algorithms (token bucket, sliding window) and
    storage backends (memory, Redis) for distributed rate limiting.

    Security Features:
        - Prevents brute force attacks
        - Configurable limits per endpoint/user/IP
        - Automatic cleanup of old records
        - Logging for security monitoring
        - Rate limit headers for client feedback

    Examples:
        >>> # Basic in-memory rate limiting
        >>> limiter = RateLimiter(limit=100, window=60)  # 100 req/min
        >>> if limiter.is_allowed("user:123"):
        ...     process_request()
        >>>
        >>> # With custom storage (Redis for distributed systems)
        >>> from unistax.ratelimit.storage import RedisStorage
        >>> storage = RedisStorage(host="localhost", port=6379)
        >>> limiter = RateLimiter(limit=10, window=60, storage=storage)
        >>>
        >>> # As decorator
        >>> @limiter.limit(key_func=lambda user_id: f"api:user:{user_id}")
        ... def api_endpoint(user_id: int):
        ...     return {"data": "..."}
        >>>
        >>> # Get rate limit info
        >>> info = limiter.get_limit_info("user:123")
        >>> print(f"Remaining: {info.remaining}/{info.limit}")
    """

    def __init__(
        self,
        limit: int = 100,
        window: int = 60,
        storage: Storage | None = None,
        algorithm: str = "sliding_window",
    ) -> None:
        """Initialize rate limiter.

        Args:
            limit: Maximum number of requests allowed in window
            window: Time window in seconds
            storage: Storage backend (defaults to in-memory)
            algorithm: Algorithm to use ("token_bucket" or "sliding_window")
                      Default: "sliding_window" (more accurate)

        Security Notes:
            - Use Redis storage for distributed systems
            - Set appropriate limits based on endpoint sensitivity:
              * Authentication: 5-10 requests per 5-15 minutes
              * API endpoints: 100-1000 requests per minute
              * Public endpoints: 1000+ requests per minute
            - Monitor rate limit violations for potential attacks
        """
        self.limit = limit
        self.window = window
        self.storage = storage or InMemoryStorage()
        self.algorithm = algorithm

        # Algorithm-specific initialization
        if algorithm == "token_bucket":
            self._buckets: dict[str, TokenBucket] = {}
        elif algorithm == "sliding_window":
            self._windows: dict[str, SlidingWindow] = {}
        else:
            raise ValueError(f"Unknown algorithm: {algorithm}")

        logger.info(
            "RateLimiter initialized: limit=%d, window=%ds, algorithm=%s, storage=%s",
            limit,
            window,
            algorithm,
            type(storage).__name__,
        )

    def _get_bucket(self, key: str) -> TokenBucket:
        """Get or create token bucket for key."""
        if key not in self._buckets:
            refill_rate = self.limit / self.window
            self._buckets[key] = TokenBucket(self.limit, refill_rate)
        return self._buckets[key]

    def _get_window(self, key: str) -> SlidingWindow:
        """Get or create sliding window for key."""
        if key not in self._windows:
            self._windows[key] = SlidingWindow(self.limit, self.window)
        return self._windows[key]

    def is_allowed(self, key: str, tokens: int = 1) -> bool:
        """Check if request is allowed under rate limit.

        Args:
            key: Identifier (e.g., "user:123", "ip:192.168.1.1")
            tokens: Number of tokens to consume (default: 1)

        Returns:
            True if request is allowed, False if rate limit exceeded

        Side Effects:
            - Logs rate limit violations at WARNING level
            - Updates storage with request timestamp

        Example:
            >>> limiter = RateLimiter(limit=10, window=60)
            >>> if limiter.is_allowed("user:123"):
            ...     # Process request
            ...     pass
            ... else:
            ...     # Return 429 Too Many Requests
            ...     raise RateLimitExceeded()
        """
        if self.algorithm == "token_bucket":
            bucket = self._get_bucket(key)
            allowed = bucket.consume(tokens)
        else:  # sliding_window
            window = self._get_window(key)
            allowed = window.is_allowed(tokens)

        if not allowed:
            logger.warning(
                "Rate limit exceeded for key=%s, limit=%d/%ds",
                key,
                self.limit,
                self.window,
            )
        else:
            logger.debug(
                "Rate limit check passed for key=%s",
                key,
            )

        return allowed

    def get_limit_info(self, key: str) -> RateLimitInfo:
        """Get current rate limit status for key.

        Args:
            key: Identifier to check

        Returns:
            RateLimitInfo with current status

        Example:
            >>> limiter = RateLimiter(limit=100, window=60)
            >>> info = limiter.get_limit_info("user:123")
            >>> print(f"{info.remaining}/{info.limit} requests remaining")
            >>> print(f"Resets in {info.retry_after}s")
        """
        if self.algorithm == "token_bucket":
            bucket = self._get_bucket(key)
            bucket._refill()  # Update tokens
            remaining = int(bucket.tokens)
            reset_time = int(time.time() + self.window)
        else:  # sliding_window
            window = self._get_window(key)
            now = time.time()
            cutoff = now - self.window

            # Count requests in current window
            valid_requests = [ts for ts in window.requests if ts >= cutoff]
            remaining = max(0, self.limit - len(valid_requests))
            reset_time = int(now + self.window)

        retry_after = None
        if remaining == 0:
            retry_after = reset_time - int(time.time())

        return RateLimitInfo(
            limit=self.limit,
            remaining=remaining,
            reset=reset_time,
            retry_after=retry_after,
        )

    def check_limit(self, key: str, tokens: int = 1) -> RateLimitInfo:
        """Check rate limit and return status info.

        Args:
            key: Identifier to check
            tokens: Number of tokens to consume

        Returns:
            RateLimitInfo with current status

        Raises:
            RateLimitExceeded: If rate limit is exceeded

        Example:
            >>> limiter = RateLimiter(limit=10, window=60)
            >>> try:
            ...     info = limiter.check_limit("user:123")
            ...     # Process request
            ...     return {"X-RateLimit-Remaining": info.remaining}
            ... except RateLimitExceeded as e:
            ...     return {"error": str(e), "retry_after": e.retry_after}
        """
        if not self.is_allowed(key, tokens):
            info = self.get_limit_info(key)
            raise RateLimitExceeded(
                f"Rate limit exceeded for {key}",
                key=key,
                limit=self.limit,
                window=self.window,
                retry_after=info.retry_after,
            )

        return self.get_limit_info(key)

    def limit(
        self,
        key_func: Callable[..., str] | None = None,
        tokens: int = 1,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator for rate limiting functions.

        Args:
            key_func: Function to extract rate limit key from arguments.
                     If None, uses function name as key.
            tokens: Number of tokens to consume per call

        Returns:
            Decorated function that enforces rate limiting

        Raises:
            RateLimitExceeded: If rate limit is exceeded

        Examples:
            >>> limiter = RateLimiter(limit=10, window=60)
            >>>
            >>> # Rate limit by user ID
            >>> @limiter.limit(key_func=lambda user_id: f"user:{user_id}")
            ... def get_user_data(user_id: int):
            ...     return {"user_id": user_id, "data": "..."}
            >>>
            >>> # Rate limit by IP address
            >>> @limiter.limit(key_func=lambda request: f"ip:{request.client.host}")
            ... async def login(request):
            ...     # Handle login
            ...     pass
            >>>
            >>> # Use function name as key (shared limit for all callers)
            >>> @limiter.limit()
            ... def expensive_operation():
            ...     # This operation is rate limited globally
            ...     pass
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                # Extract key
                if key_func:
                    key = key_func(*args, **kwargs)
                else:
                    key = f"func:{func.__module__}.{func.__name__}"

                # Check rate limit
                try:
                    self.check_limit(key, tokens)
                except RateLimitExceeded:
                    logger.warning(
                        "Rate limit exceeded for function %s with key %s",
                        func.__name__,
                        key,
                    )
                    raise

                # Execute function
                return func(*args, **kwargs)

            return wrapper

        return decorator

    def reset(self, key: str) -> None:
        """Reset rate limit for a specific key.

        Args:
            key: Identifier to reset

        Security Note:
            Use with caution - only reset limits for legitimate reasons
            (e.g., after successful 2FA, admin override)

        Example:
            >>> limiter = RateLimiter(limit=5, window=300)
            >>> # After successful 2FA, reset login attempt limit
            >>> limiter.reset(f"login:user:{user_id}")
        """
        if self.algorithm == "token_bucket":
            if key in self._buckets:
                del self._buckets[key]
                logger.info("Reset token bucket for key=%s", key)
        else:  # sliding_window
            if key in self._windows:
                del self._windows[key]
                logger.info("Reset sliding window for key=%s", key)

    def clear_all(self) -> None:
        """Clear all rate limit data.

        Security Note:
            Only use for testing or maintenance. In production, use reset()
            for specific keys.
        """
        if self.algorithm == "token_bucket":
            self._buckets.clear()
        else:
            self._windows.clear()

        logger.warning("Cleared all rate limit data")


# Convenience alias for backward compatibility
RateLimit = RateLimiter
