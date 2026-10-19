"""Rate limiting middleware for HTTP requests."""

import logging
from collections.abc import Callable

from ..middleware.pipeline import Middleware, NextHandler, Request, Response
from .limiter import RateLimiter, RateLimitExceeded

logger = logging.getLogger(__name__)


class RateLimitMiddleware(Middleware):
    """Middleware for rate limiting HTTP requests.

    Adds rate limit headers to responses and returns 429 Too Many Requests
    when limits are exceeded.

    Security Features:
        - Per-IP rate limiting by default
        - Customizable key extraction (per-user, per-endpoint, etc.)
        - Standard rate limit headers (X-RateLimit-*)
        - Retry-After header when limit exceeded
        - Security event logging

    Examples:
        >>> from unistax.middleware import MiddlewarePipeline
        >>> from unistax.ratelimit import RateLimitMiddleware, RateLimiter
        >>>
        >>> # Basic IP-based rate limiting
        >>> limiter = RateLimiter(limit=100, window=60)  # 100 req/min
        >>> rate_limit_mw = RateLimitMiddleware(limiter)
        >>> pipeline = MiddlewarePipeline()
        >>> pipeline.use(rate_limit_mw)
        >>>
        >>> # Per-user rate limiting
        >>> def get_user_key(request):
        ...     user_id = request.context.get("user_id")
        ...     if user_id:
        ...         return f"user:{user_id}"
        ...     return f"ip:{request.headers.get('X-Real-IP', 'unknown')}"
        >>> rate_limit_mw = RateLimitMiddleware(limiter, key_func=get_user_key)
        >>>
        >>> # Per-endpoint rate limiting
        >>> def get_endpoint_key(request):
        ...     ip = request.headers.get("X-Real-IP", "unknown")
        ...     return f"endpoint:{request.path}:ip:{ip}"
        >>> rate_limit_mw = RateLimitMiddleware(limiter, key_func=get_endpoint_key)
    """

    def __init__(
        self,
        limiter: RateLimiter,
        key_func: Callable[[Request], str] | None = None,
        error_message: str = "Rate limit exceeded. Please try again later.",
        include_headers: bool = True,
    ) -> None:
        """Initialize RateLimitMiddleware.

        Args:
            limiter: RateLimiter instance to use
            key_func: Function to extract rate limit key from request.
                     If None, uses client IP address from X-Real-IP or X-Forwarded-For headers.
            error_message: Error message to return when rate limit exceeded
            include_headers: Whether to include rate limit headers in responses

        Security Notes:
            - Default key_func uses X-Real-IP/X-Forwarded-For headers
            - Ensure reverse proxy is configured to set these headers correctly
            - Consider using authenticated user ID for better accuracy
            - Log rate limit violations for security monitoring

        Example:
            >>> limiter = RateLimiter(limit=10, window=60)
            >>> middleware = RateLimitMiddleware(
            ...     limiter=limiter,
            ...     key_func=lambda req: req.context.get("user_id", "anonymous"),
            ...     include_headers=True
            ... )
        """
        self.limiter = limiter
        self.key_func = key_func or self._default_key_func
        self.error_message = error_message
        self.include_headers = include_headers

        logger.info(
            "RateLimitMiddleware initialized: limit=%d, window=%ds",
            limiter.limit,
            limiter.window,
        )

    def _default_key_func(self, request: Request) -> str:
        """Extract client IP address from request.

        Args:
            request: HTTP request

        Returns:
            Rate limit key (IP address)

        Security Note:
            Checks X-Real-IP and X-Forwarded-For headers set by reverse proxy.
            If not found, returns "unknown" (which may rate limit all clients together).
        """
        # Try X-Real-IP first (set by nginx, others)
        ip = request.headers.get("X-Real-IP")
        if ip:
            return f"ip:{ip}"

        # Try X-Forwarded-For (may contain multiple IPs, use first)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Get first IP (client IP)
            ip = forwarded_for.split(",")[0].strip()
            return f"ip:{ip}"

        # Fallback to "unknown" (WARNING: will rate limit all clients together!)
        logger.warning(
            "No client IP found in request headers. "
            "All clients will share the same rate limit. "
            "Ensure reverse proxy sets X-Real-IP or X-Forwarded-For headers."
        )
        return "ip:unknown"

    async def process(self, request: Request, next_handler: NextHandler) -> Response:
        """Process request with rate limiting.

        Args:
            request: HTTP request
            next_handler: Next handler in middleware chain

        Returns:
            HTTP response with rate limit headers

        Response Headers:
            - X-RateLimit-Limit: Maximum requests allowed in window
            - X-RateLimit-Remaining: Remaining requests in current window
            - X-RateLimit-Reset: Unix timestamp when limit resets
            - Retry-After: Seconds to wait before retrying (if exceeded)

        HTTP Status Codes:
            - 200-299: Request successful, rate limit headers included
            - 429: Too Many Requests - rate limit exceeded

        Example Response (rate limit exceeded):
            {
                "error": "Rate limit exceeded. Please try again later.",
                "retry_after": 45
            }
            Headers:
                X-RateLimit-Limit: 100
                X-RateLimit-Remaining: 0
                X-RateLimit-Reset: 1699887654
                Retry-After: 45
        """
        # Extract rate limit key
        key = self.key_func(request)

        try:
            # Check rate limit
            info = self.limiter.check_limit(key)

            # Process request
            response = await next_handler(request)

            # Add rate limit headers to successful response
            if self.include_headers:
                response.headers.update(
                    {
                        "X-RateLimit-Limit": str(info.limit),
                        "X-RateLimit-Remaining": str(info.remaining),
                        "X-RateLimit-Reset": str(info.reset),
                    }
                )

            return response

        except RateLimitExceeded as e:
            # Rate limit exceeded - return 429
            logger.warning(
                "Rate limit exceeded for key=%s, limit=%d/%ds",
                key,
                e.limit,
                e.window,
            )

            # Get current limit info
            info = self.limiter.get_limit_info(key)

            # Build error response
            response = Response(
                status_code=429,
                headers={
                    "X-RateLimit-Limit": str(info.limit),
                    "X-RateLimit-Remaining": str(info.remaining),
                    "X-RateLimit-Reset": str(info.reset),
                },
                body={
                    "error": self.error_message,
                    "retry_after": info.retry_after or 0,
                },
            )

            # Add Retry-After header
            if info.retry_after is not None:
                response.headers["Retry-After"] = str(info.retry_after)

            return response
