"""CSRF protection exceptions."""


class CSRFError(Exception):
    """Base exception for CSRF-related errors."""

    pass


class CSRFTokenMissing(CSRFError):
    """Raised when CSRF token is missing from request."""

    pass


class CSRFTokenInvalid(CSRFError):
    """Raised when CSRF token is invalid or doesn't match."""

    pass


class CSRFTokenExpired(CSRFError):
    """Raised when CSRF token has expired."""

    pass
