"""CSRF protection middleware for HTTP requests."""

import logging
import re
from collections.abc import Callable

from ..middleware.pipeline import Middleware, NextHandler, Request, Response
from .exceptions import CSRFError, CSRFTokenExpired, CSRFTokenInvalid, CSRFTokenMissing
from .protect import CSRFProtect

logger = logging.getLogger(__name__)


class CSRFProtectMiddleware(Middleware):
    """Middleware for CSRF protection using double-submit cookie pattern.

    Protects against Cross-Site Request Forgery attacks by validating
    CSRF tokens on state-changing requests (POST, PUT, DELETE, PATCH).

    Security Features:
        - Double-submit cookie pattern (stateless)
        - Automatic token generation and cookie setting
        - Configurable safe methods (GET, HEAD, OPTIONS)
        - Exempt endpoint patterns (e.g., /api/webhook, /health)
        - Secure cookie settings (httponly, samesite, secure)
        - User-specific token binding (optional)
        - Comprehensive logging for security monitoring

    How It Works:
        1. For all responses: Set CSRF token in cookie
        2. For state-changing requests: Validate token from cookie matches header
        3. For exempt endpoints: Skip validation
        4. On validation failure: Return 403 Forbidden

    Examples:
        >>> from unistax.middleware import MiddlewarePipeline
        >>> from unistax.csrf import CSRFProtectMiddleware
        >>>
        >>> # Basic usage
        >>> csrf = CSRFProtectMiddleware(secret="your-secret-key")
        >>> pipeline = MiddlewarePipeline()
        >>> pipeline.use(csrf)
        >>>
        >>> # With custom configuration
        >>> csrf = CSRFProtectMiddleware(
        ...     secret="your-secret-key",
        ...     cookie_name="csrf_token",
        ...     header_name="X-CSRF-Token",
        ...     token_expiration=3600,  # 1 hour
        ...     exempt_patterns=[r"^/api/webhook", r"^/health"],
        ...     cookie_secure=True,  # HTTPS only
        ...     cookie_samesite="strict",
        ... )
        >>>
        >>> # With user binding for additional security
        >>> def get_user_id(request):
        ...     return request.context.get("user_id")
        >>> csrf = CSRFProtectMiddleware(
        ...     secret="your-secret-key",
        ...     user_id_func=get_user_id,
        ... )
    """

    def __init__(
        self,
        secret: str,
        cookie_name: str = "csrf_token",
        header_name: str = "X-CSRF-Token",
        form_field_name: str = "csrf_token",
        safe_methods: set[str] | None = None,
        exempt_patterns: list[str] | None = None,
        token_expiration: int | None = None,
        cookie_path: str = "/",
        cookie_domain: str | None = None,
        cookie_secure: bool = False,
        cookie_httponly: bool = True,
        cookie_samesite: str = "lax",
        user_id_func: Callable[[Request], str | None] | None = None,
        error_message: str = "CSRF validation failed",
    ) -> None:
        """Initialize CSRF protection middleware.

        Args:
            secret: Secret key for token generation (use app secret)
            cookie_name: Name of CSRF cookie (default: "csrf_token")
            header_name: Name of CSRF header (default: "X-CSRF-Token")
            form_field_name: Name of form field (default: "csrf_token")
            safe_methods: HTTP methods that don't require CSRF protection
                         (default: {"GET", "HEAD", "OPTIONS"})
            exempt_patterns: List of regex patterns for exempt endpoints
                           (e.g., [r"^/api/webhook", r"^/health"])
            token_expiration: Token lifetime in seconds (None = no expiration)
            cookie_path: Cookie path (default: "/")
            cookie_domain: Cookie domain (None = current domain)
            cookie_secure: Set Secure flag (HTTPS only, default: False)
            cookie_httponly: Set HttpOnly flag (default: True)
            cookie_samesite: SameSite policy (default: "lax", options: "strict", "lax", "none")
            user_id_func: Function to extract user ID from request (for user binding)
            error_message: Error message for CSRF failures

        Security Notes:
            - Set cookie_secure=True in production (requires HTTPS)
            - Use cookie_samesite="strict" for maximum security
            - Set cookie_httponly=True to prevent XSS token theft
            - Exempt only public endpoints (webhooks, health checks)
            - Use user_id_func for additional security (binds token to user)
            - Rotate secret periodically (requires session invalidation)

        Example:
            >>> # Production configuration
            >>> csrf = CSRFProtectMiddleware(
            ...     secret=os.environ["SECRET_KEY"],
            ...     token_expiration=3600,  # 1 hour
            ...     cookie_secure=True,  # HTTPS only
            ...     cookie_samesite="strict",  # Maximum protection
            ...     exempt_patterns=[r"^/api/webhook/stripe"],
            ... )
        """
        self.csrf_protect = CSRFProtect(secret=secret, token_expiration=token_expiration)
        self.cookie_name = cookie_name
        self.header_name = header_name
        self.form_field_name = form_field_name
        self.safe_methods = safe_methods or {"GET", "HEAD", "OPTIONS"}
        self.exempt_patterns = [re.compile(p) for p in (exempt_patterns or [])]
        self.cookie_path = cookie_path
        self.cookie_domain = cookie_domain
        self.cookie_secure = cookie_secure
        self.cookie_httponly = cookie_httponly
        self.cookie_samesite = cookie_samesite
        self.user_id_func = user_id_func
        self.error_message = error_message

        logger.info(
            "CSRFProtectMiddleware initialized: cookie=%s, header=%s, "
            "safe_methods=%s, exempt_patterns=%d, expiration=%s",
            cookie_name,
            header_name,
            safe_methods,
            len(self.exempt_patterns),
            f"{token_expiration}s" if token_expiration else "none",
        )

    def _is_exempt(self, path: str) -> bool:
        """Check if endpoint is exempt from CSRF protection.

        Args:
            path: Request path

        Returns:
            True if endpoint is exempt
        """
        for pattern in self.exempt_patterns:
            if pattern.match(path):
                logger.debug("CSRF check skipped for exempt path: %s", path)
                return True
        return False

    def _get_cookie_value(self, request: Request, name: str) -> str | None:
        """Extract cookie value from request.

        Args:
            request: HTTP request
            name: Cookie name

        Returns:
            Cookie value or None
        """
        # Check if cookies are available in request
        cookies = getattr(request, "cookies", {})
        return cookies.get(name)

    def _get_token_from_request(self, request: Request) -> str | None:
        """Extract CSRF token from request header or form.

        Args:
            request: HTTP request

        Returns:
            CSRF token or None

        Note:
            Checks header first, then form field (for HTML forms).
        """
        # Try header first
        token = request.headers.get(self.header_name)
        if token:
            return token

        # Try form field (for HTML forms)
        if hasattr(request, "form"):
            form = getattr(request, "form", {})
            token = form.get(self.form_field_name)
            if token:
                return token

        # Try body for JSON requests
        if hasattr(request, "body") and isinstance(request.body, dict):
            token = request.body.get(self.form_field_name)
            if token:
                return token

        return None

    def _set_csrf_cookie(self, response: Response, token: str) -> None:
        """Set CSRF token in response cookie.

        Args:
            response: HTTP response
            token: CSRF token to set
        """
        # Build cookie header value
        cookie_parts = [f"{self.cookie_name}={token}"]
        cookie_parts.append(f"Path={self.cookie_path}")

        if self.cookie_domain:
            cookie_parts.append(f"Domain={self.cookie_domain}")

        if self.cookie_secure:
            cookie_parts.append("Secure")

        if self.cookie_httponly:
            cookie_parts.append("HttpOnly")

        if self.cookie_samesite:
            cookie_parts.append(f"SameSite={self.cookie_samesite.capitalize()}")

        cookie_value = "; ".join(cookie_parts)
        response.headers["Set-Cookie"] = cookie_value

        logger.debug("CSRF cookie set: %s", self.cookie_name)

    async def process(self, request: Request, next_handler: NextHandler) -> Response:
        """Process request with CSRF protection.

        Args:
            request: HTTP request
            next_handler: Next handler in middleware chain

        Returns:
            HTTP response with CSRF cookie

        Response Headers:
            - Set-Cookie: CSRF token cookie
            - X-CSRF-Token: CSRF token (for client access)

        HTTP Status Codes:
            - 403: Forbidden - CSRF validation failed

        Security Flow:
            1. Check if request method is safe (GET, HEAD, OPTIONS) → skip validation
            2. Check if endpoint is exempt → skip validation
            3. Extract CSRF token from cookie and header/form
            4. Validate tokens match and signature is valid
            5. Process request if valid
            6. Set/refresh CSRF cookie on response

        Example Response (CSRF failure):
            Status: 403 Forbidden
            {
                "error": "CSRF validation failed",
                "detail": "CSRF token missing from header/form"
            }
        """
        # Skip CSRF check for safe methods
        if request.method in self.safe_methods:
            logger.debug(
                "CSRF check skipped for safe method: %s %s",
                request.method,
                request.path,
            )
            response = await next_handler(request)
            # Still set CSRF cookie for future requests
            token = self.csrf_protect.generate_token()
            self._set_csrf_cookie(response, token)
            # Add token to response header for client access
            response.headers[self.header_name] = token
            return response

        # Skip CSRF check for exempt endpoints
        if self._is_exempt(request.path):
            return await next_handler(request)

        # Extract user ID if configured
        user_id = None
        if self.user_id_func:
            user_id = self.user_id_func(request)

        # Get CSRF token from cookie
        cookie_token = self._get_cookie_value(request, self.cookie_name)

        # Get CSRF token from header/form
        header_token = self._get_token_from_request(request)

        # Validate CSRF tokens
        try:
            self.csrf_protect.validate_token(cookie_token, header_token, user_id)
        except CSRFTokenMissing as e:
            logger.warning(
                "CSRF validation failed for %s %s: %s",
                request.method,
                request.path,
                str(e),
            )
            return Response(
                status_code=403,
                headers={"Content-Type": "application/json"},
                body={
                    "error": self.error_message,
                    "detail": str(e),
                },
            )
        except CSRFTokenInvalid as e:
            logger.warning(
                "CSRF validation failed for %s %s: %s (possible attack!)",
                request.method,
                request.path,
                str(e),
            )
            return Response(
                status_code=403,
                headers={"Content-Type": "application/json"},
                body={
                    "error": self.error_message,
                    "detail": str(e),
                },
            )
        except CSRFTokenExpired as e:
            logger.warning(
                "CSRF validation failed for %s %s: %s",
                request.method,
                request.path,
                str(e),
            )
            return Response(
                status_code=403,
                headers={"Content-Type": "application/json"},
                body={
                    "error": self.error_message,
                    "detail": str(e),
                },
            )
        except CSRFError as e:
            logger.error(
                "Unexpected CSRF error for %s %s: %s",
                request.method,
                request.path,
                str(e),
            )
            return Response(
                status_code=403,
                headers={"Content-Type": "application/json"},
                body={
                    "error": self.error_message,
                    "detail": "CSRF validation error",
                },
            )

        # Process request
        response = await next_handler(request)

        # Refresh CSRF cookie on response
        new_token = self.csrf_protect.generate_token(user_id)
        self._set_csrf_cookie(response, new_token)
        # Add token to response header for client access
        response.headers[self.header_name] = new_token

        logger.debug("CSRF validation successful for %s %s", request.method, request.path)

        return response
