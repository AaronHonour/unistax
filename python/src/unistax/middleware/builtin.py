"""Built-in middleware implementations."""

import time
from typing import Any

from .pipeline import Middleware, NextHandler, Request, Response


class LoggingMiddleware(Middleware):
    """Logs request/response information.

    Logs method, path, status code, and duration.
    """

    def __init__(self, logger: Any | None = None) -> None:
        """Initialize LoggingMiddleware.

        Args:
            logger: Logger instance to use (optional)
        """
        self.logger = logger

    async def process(self, request: Request, next_handler: NextHandler) -> Response:
        """Process request with logging.

        Args:
            request: Request to process
            next_handler: Next handler in chain

        Returns:
            Response from handler
        """
        start_time = time.time()

        # Log request
        if self.logger:
            self.logger.info(
                f"Request: {request.method} {request.path}",
                extra={"method": request.method, "path": request.path},
            )

        # Process request
        try:
            response = await next_handler(request)

            # Log response
            duration = time.time() - start_time
            if self.logger:
                self.logger.info(
                    f"Response: {response.status_code} ({duration:.3f}s)",
                    extra={
                        "status_code": response.status_code,
                        "duration_ms": duration * 1000,
                    },
                )

            return response

        except Exception as e:
            duration = time.time() - start_time
            if self.logger:
                self.logger.error(
                    f"Error: {str(e)} ({duration:.3f}s)",
                    extra={"error": str(e), "duration_ms": duration * 1000},
                )
            raise


class MetricsMiddleware(Middleware):
    """Collects request metrics.

    Tracks request count, duration, and status codes.
    """

    def __init__(self, metrics: Any | None = None) -> None:
        """Initialize MetricsMiddleware.

        Args:
            metrics: Metrics collector instance (optional)
        """
        self.metrics = metrics

    async def process(self, request: Request, next_handler: NextHandler) -> Response:
        """Process request with metrics collection.

        Args:
            request: Request to process
            next_handler: Next handler in chain

        Returns:
            Response from handler
        """
        start_time = time.time()

        # Track request
        if self.metrics:
            self.metrics.counter(
                "http.requests.total",
                labels={"method": request.method, "path": request.path},
            )

        try:
            response = await next_handler(request)

            # Track response
            duration = time.time() - start_time
            if self.metrics:
                self.metrics.histogram(
                    "http.request.duration",
                    duration,
                    labels={
                        "method": request.method,
                        "path": request.path,
                        "status": str(response.status_code),
                    },
                )
                self.metrics.counter(
                    "http.responses.total",
                    labels={
                        "method": request.method,
                        "status": str(response.status_code),
                    },
                )

            return response

        except Exception as e:
            duration = time.time() - start_time
            if self.metrics:
                self.metrics.histogram("http.request.duration", duration)
                self.metrics.counter("http.errors.total", labels={"error_type": type(e).__name__})
            raise


class ErrorHandlerMiddleware(Middleware):
    """Handles exceptions and converts to responses.

    Catches exceptions and returns appropriate error responses.
    """

    async def process(self, request: Request, next_handler: NextHandler) -> Response:
        """Process request with error handling.

        Args:
            request: Request to process
            next_handler: Next handler in chain

        Returns:
            Response from handler or error response
        """
        try:
            return await next_handler(request)

        except Exception as e:
            # Convert exception to response
            # In production, you'd map specific exceptions to status codes
            return Response(
                status_code=500,
                body={"error": type(e).__name__, "message": str(e)},
            )


class CORSMiddleware(Middleware):
    """Adds CORS headers to responses.

    Handles preflight requests and adds CORS headers.

    SECURITY WARNING: Do not use wildcard origins ("*") in production!
    Always specify exact allowed origins to prevent unauthorized access.
    """

    def __init__(
        self,
        allow_origins: list[str] | None = None,
        allow_methods: list[str] | None = None,
        allow_headers: list[str] | None = None,
        allow_credentials: bool = False,
        max_age: int = 3600,
    ) -> None:
        """Initialize CORSMiddleware.

        Args:
            allow_origins: Allowed origins. REQUIRED - no default for security.
                          Examples: ["https://example.com", "https://app.example.com"]
                          Never use ["*"] in production!
            allow_methods: Allowed HTTP methods
            allow_headers: Allowed headers
            allow_credentials: Allow credentials (cookies, auth headers).
                             Cannot be used with wildcard origins.
            max_age: Max age for preflight cache in seconds

        Raises:
            ValueError: If origins not specified or invalid configuration

        Security Notes:
            - Always specify exact origins in production
            - Only use wildcard ("*") for development/testing
            - Cannot use credentials with wildcard origins
            - Validate origins match your application domains

        Example:
            >>> # Production (SECURE)
            >>> cors = CORSMiddleware(
            ...     allow_origins=["https://example.com", "https://app.example.com"],
            ...     allow_credentials=True
            ... )
            >>>
            >>> # Development only (INSECURE)
            >>> cors = CORSMiddleware(allow_origins=["*"])
        """
        if not allow_origins:
            raise ValueError(
                "allow_origins is required. Specify exact origins for production, "
                "or ['*'] for development only. Never use ['*'] in production!"
            )

        # Validate credentials + wildcard combination
        if allow_credentials and "*" in allow_origins:
            raise ValueError(
                "Cannot use allow_credentials=True with wildcard origins ('*'). "
                "Specify exact origins or disable credentials."
            )

        # Warn about wildcard usage
        if "*" in allow_origins and len(allow_origins) == 1:
            import warnings

            warnings.warn(
                "Using wildcard CORS origins ['*'] is INSECURE and should only be used "
                "in development. In production, specify exact allowed origins.",
                UserWarning,
                stacklevel=2,
            )

        self.allow_origins = allow_origins
        self.allow_methods = allow_methods or ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
        self.allow_headers = allow_headers or ["Content-Type", "Authorization"]
        self.allow_credentials = allow_credentials
        self.max_age = max_age

    async def process(self, request: Request, next_handler: NextHandler) -> Response:
        """Process request with CORS headers.

        Args:
            request: Request to process
            next_handler: Next handler in chain

        Returns:
            Response with CORS headers
        """
        # Handle preflight request
        if request.method == "OPTIONS":
            return Response(
                status_code=200,
                headers=self._get_cors_headers(request),
            )

        # Process request
        response = await next_handler(request)

        # Add CORS headers to response
        response.headers.update(self._get_cors_headers(request))

        return response

    def _get_cors_headers(self, request: Request) -> dict[str, str]:
        """Get CORS headers."""
        origin = request.headers.get("Origin", "*")

        # Check if origin is allowed
        if "*" not in self.allow_origins and origin not in self.allow_origins:
            origin = self.allow_origins[0] if self.allow_origins else "*"

        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": ", ".join(self.allow_methods),
            "Access-Control-Allow-Headers": ", ".join(self.allow_headers),
            "Access-Control-Max-Age": str(self.max_age),
        }


class SecurityHeadersMiddleware(Middleware):
    """Adds security headers to all responses.

    Implements OWASP recommended security headers to protect against common attacks:
    - XSS (Cross-Site Scripting)
    - Clickjacking
    - MIME type sniffing
    - Man-in-the-middle attacks
    - Information disclosure

    References:
        - OWASP Secure Headers Project
        - https://owasp.org/www-project-secure-headers/
        - https://securityheaders.com/
    """

    def __init__(
        self,
        content_security_policy: str | None = None,
        x_frame_options: str = "DENY",
        x_content_type_options: str = "nosniff",
        strict_transport_security: str | None = None,
        referrer_policy: str = "strict-origin-when-cross-origin",
        permissions_policy: str | None = None,
        x_xss_protection: str = "1; mode=block",
        custom_headers: dict[str, str] | None = None,
    ) -> None:
        """Initialize SecurityHeadersMiddleware.

        Args:
            content_security_policy: Content-Security-Policy header value.
                Default: Restrictive policy (see _get_default_csp)
                Example: "default-src 'self'; script-src 'self' 'unsafe-inline'"
            x_frame_options: X-Frame-Options header. Options: DENY, SAMEORIGIN.
                Default: DENY (prevents all framing)
            x_content_type_options: X-Content-Type-Options header.
                Default: nosniff (prevents MIME type sniffing)
            strict_transport_security: Strict-Transport-Security (HSTS) header.
                Default: max-age=31536000; includeSubDomains (1 year, include subdomains)
                Set to None to disable (not recommended for production)
                Example: "max-age=63072000; includeSubDomains; preload"
            referrer_policy: Referrer-Policy header.
                Default: strict-origin-when-cross-origin
                Options: no-referrer, no-referrer-when-downgrade, origin,
                         origin-when-cross-origin, same-origin, strict-origin,
                         strict-origin-when-cross-origin, unsafe-url
            permissions_policy: Permissions-Policy header (formerly Feature-Policy).
                Default: Restrictive policy disabling sensitive features
                Example: "geolocation=(), microphone=(), camera=()"
            x_xss_protection: X-XSS-Protection header (legacy, for older browsers).
                Default: 1; mode=block
                Note: Modern browsers use CSP instead
            custom_headers: Additional custom security headers

        Security Notes:
            - CSP should be tailored to your application's needs
            - HSTS should only be enabled over HTTPS
            - Test CSP in report-only mode before enforcing
            - Use security scanners to validate configuration

        Example:
            >>> # Production configuration
            >>> security = SecurityHeadersMiddleware(
            ...     content_security_policy=(
            ...         "default-src 'self'; "
            ...         "script-src 'self' https://cdn.example.com; "
            ...         "style-src 'self' 'unsafe-inline'; "
            ...         "img-src 'self' data: https:; "
            ...         "font-src 'self' data:; "
            ...         "connect-src 'self' https://api.example.com; "
            ...         "frame-ancestors 'none'; "
            ...         "base-uri 'self'; "
            ...         "form-action 'self'"
            ...     ),
            ...     strict_transport_security="max-age=63072000; includeSubDomains; preload",
            ...     x_frame_options="DENY",
            ... )
            >>>
            >>> # Development configuration (more permissive CSP)
            >>> security = SecurityHeadersMiddleware(
            ...     content_security_policy=(
            ...         "default-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            ...         "img-src 'self' data: https:; "
            ...         "connect-src 'self' ws: wss:"
            ...     ),
            ...     strict_transport_security=None,  # Disable HSTS for HTTP dev
            ... )
        """
        self.csp = content_security_policy or self._get_default_csp()
        self.x_frame_options = x_frame_options
        self.x_content_type_options = x_content_type_options
        self.hsts = strict_transport_security or "max-age=31536000; includeSubDomains"
        self.referrer_policy = referrer_policy
        self.permissions_policy = permissions_policy or self._get_default_permissions_policy()
        self.x_xss_protection = x_xss_protection
        self.custom_headers = custom_headers or {}

    def _get_default_csp(self) -> str:
        """Get default Content Security Policy.

        Returns a restrictive CSP that should work for most applications.
        Customize based on your application's specific needs.
        """
        return (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "upgrade-insecure-requests"
        )

    def _get_default_permissions_policy(self) -> str:
        """Get default Permissions Policy.

        Disables sensitive features by default.
        """
        return (
            "geolocation=(), "
            "microphone=(), "
            "camera=(), "
            "payment=(), "
            "usb=(), "
            "magnetometer=(), "
            "gyroscope=(), "
            "accelerometer=()"
        )

    async def process(self, request: Request, next_handler: NextHandler) -> Response:
        """Process request and add security headers to response.

        Args:
            request: Request to process
            next_handler: Next handler in chain

        Returns:
            Response with security headers added
        """
        response = await next_handler(request)

        # Add security headers
        security_headers = {
            "Content-Security-Policy": self.csp,
            "X-Frame-Options": self.x_frame_options,
            "X-Content-Type-Options": self.x_content_type_options,
            "Referrer-Policy": self.referrer_policy,
            "Permissions-Policy": self.permissions_policy,
        }

        # Add HSTS only if explicitly set (should only be used over HTTPS)
        if self.hsts:
            security_headers["Strict-Transport-Security"] = self.hsts

        # Add X-XSS-Protection for legacy browser support
        if self.x_xss_protection:
            security_headers["X-XSS-Protection"] = self.x_xss_protection

        # Add custom headers
        security_headers.update(self.custom_headers)

        # Update response headers
        response.headers.update(security_headers)

        return response


class CompressionMiddleware(Middleware):
    """Compresses response bodies.

    Uses gzip compression for large responses.
    """

    def __init__(self, min_size: int = 1024) -> None:
        """Initialize CompressionMiddleware.

        Args:
            min_size: Minimum response size in bytes for compression
        """
        self.min_size = min_size

    async def process(self, request: Request, next_handler: NextHandler) -> Response:
        """Process request with response compression.

        Args:
            request: Request to process
            next_handler: Next handler in chain

        Returns:
            Compressed or uncompressed response
        """
        response = await next_handler(request)

        # Check if client accepts gzip
        accept_encoding = request.headers.get("Accept-Encoding", "")
        if "gzip" not in accept_encoding:
            return response

        # Check response size
        if response.body and isinstance(response.body, (str, bytes)):
            body_size = len(
                response.body if isinstance(response.body, bytes) else response.body.encode()
            )  # noqa: E501

            if body_size >= self.min_size:
                import gzip

                # Compress body
                if isinstance(response.body, str):
                    compressed = gzip.compress(response.body.encode())
                else:
                    compressed = gzip.compress(response.body)

                response.body = compressed
                response.headers["Content-Encoding"] = "gzip"
                response.headers["Content-Length"] = str(len(compressed))

        return response
