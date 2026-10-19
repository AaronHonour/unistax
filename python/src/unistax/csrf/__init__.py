"""CSRF Protection Module.

Provides Cross-Site Request Forgery (CSRF) protection middleware
using the double-submit cookie pattern.

Features:
- Stateless CSRF protection (no server-side session required)
- Double-submit cookie pattern
- Token expiration support
- User-specific token binding
- Exempt endpoint patterns
- Configurable cookie settings
- Comprehensive logging for security monitoring

Security Benefits:
- Prevents CSRF attacks on state-changing operations
- Works with both API and web applications
- Integrates with middleware pipeline
- Follows OWASP recommendations

Examples:
    >>> # Basic usage with middleware pipeline
    >>> from unistax.middleware import MiddlewarePipeline
    >>> from unistax.csrf import CSRFProtectMiddleware
    >>>
    >>> csrf = CSRFProtectMiddleware(secret="your-secret-key")
    >>> pipeline = MiddlewarePipeline()
    >>> pipeline.use(csrf)
    >>>
    >>> # Standalone token generation/validation
    >>> from unistax.csrf import CSRFProtect
    >>>
    >>> csrf = CSRFProtect(secret="your-secret-key", token_expiration=3600)
    >>> token = csrf.generate_token()
    >>> csrf.validate_token(token, token)  # Validates successfully
    >>>
    >>> # Production configuration
    >>> csrf = CSRFProtectMiddleware(
    ...     secret="your-secret-key",
    ...     token_expiration=3600,  # 1 hour
    ...     cookie_secure=True,  # HTTPS only
    ...     cookie_samesite="strict",  # Maximum protection
    ...     exempt_patterns=[r"^/api/webhook"],  # Exempt webhooks
    ... )

Client-Side Usage:
    For JavaScript/API clients:

    ```javascript
    // 1. Extract CSRF token from cookie or response header
    const csrfToken = getCookie('csrf_token');
    // Or from response header after first request
    const csrfToken = response.headers.get('X-CSRF-Token');

    // 2. Include token in state-changing requests
    fetch('/api/update', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': csrfToken  // Include token here
        },
        body: JSON.stringify({ data: 'value' })
    });
    ```

    For HTML forms:

    ```html
    <form method="POST" action="/update">
        <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
        <!-- other fields -->
    </form>
    ```
"""

from .exceptions import CSRFError, CSRFTokenExpired, CSRFTokenInvalid, CSRFTokenMissing
from .middleware import CSRFProtectMiddleware
from .protect import CSRFProtect

__all__ = [
    # Main classes
    "CSRFProtect",
    "CSRFProtectMiddleware",
    # Exceptions
    "CSRFError",
    "CSRFTokenMissing",
    "CSRFTokenInvalid",
    "CSRFTokenExpired",
]
