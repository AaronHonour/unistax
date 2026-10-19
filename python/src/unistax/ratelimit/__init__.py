"""Rate Limiting Module.

Provides rate limiting middleware and storage backends for preventing
brute force attacks and API abuse.

Features:
- Multiple storage backends (memory, Redis)
- Sliding window and token bucket algorithms
- Per-IP, per-user, and custom key functions
- Configurable limits and time windows
- Standard rate limit headers (X-RateLimit-*)
- Integration with middleware pipeline
- Comprehensive logging for security monitoring

Security Use Cases:
- Protect authentication endpoints from brute force attacks
- Prevent API abuse and DoS attacks
- Limit resource-intensive operations
- Enforce fair usage policies

Examples:
    >>> # Basic rate limiting
    >>> from unistax.ratelimit import RateLimiter, RateLimitMiddleware
    >>> limiter = RateLimiter(limit=100, window=60)  # 100 req/min
    >>> middleware = RateLimitMiddleware(limiter)
    >>>
    >>> # With Redis for distributed systems
    >>> from unistax.ratelimit import RedisStorage
    >>> storage = RedisStorage(host="localhost")
    >>> limiter = RateLimiter(limit=10, window=60, storage=storage)
    >>>
    >>> # Protect authentication endpoint
    >>> auth_limiter = RateLimiter(limit=5, window=300)  # 5 req/5min
    >>> @auth_limiter.limit(key_func=lambda username: f"login:{username}")
    ... def login(username, password):
    ...     # Handle login
    ...     pass
"""

from .algorithms import SlidingWindow, TokenBucket
from .limiter import RateLimit, RateLimiter, RateLimitExceeded, RateLimitInfo
from .middleware import RateLimitMiddleware
from .storage import InMemoryStorage, RedisStorage, Storage

__all__ = [
    # Main classes
    "RateLimiter",
    "RateLimit",  # Alias for backward compatibility
    "RateLimitMiddleware",
    # Exceptions
    "RateLimitExceeded",
    # Data classes
    "RateLimitInfo",
    # Storage backends
    "Storage",
    "InMemoryStorage",
    "RedisStorage",
    # Algorithms
    "TokenBucket",
    "SlidingWindow",
]
