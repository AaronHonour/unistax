"""Secrets management exceptions."""


class SecretError(Exception):
    """Base exception for secrets-related errors."""

    pass


class SecretNotFound(SecretError):
    """Raised when a secret is not found."""

    pass


class SecretAccessDenied(SecretError):
    """Raised when access to a secret is denied."""

    pass


class SecretInvalidFormat(SecretError):
    """Raised when a secret has an invalid format."""

    pass
