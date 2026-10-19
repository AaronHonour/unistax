"""Base interface for secrets management."""

from abc import ABC, abstractmethod
from typing import Any


class SecretBackend(ABC):
    """Abstract base class for secret storage backends.

    All secret backends must implement this interface to provide
    a consistent API for secret retrieval and management.

    Security Notes:
        - Secrets should never be logged or printed
        - Implement caching carefully to avoid memory leaks
        - Always use secure connections for remote backends
        - Validate secret format before returning
        - Implement proper access control
    """

    @abstractmethod
    def get_secret(self, key: str, default: Any = None) -> str | None:
        """Retrieve a secret by key.

        Args:
            key: Secret key/name
            default: Default value if secret not found

        Returns:
            Secret value or default

        Raises:
            SecretNotFound: If secret not found and no default
            SecretAccessDenied: If access denied
            SecretError: For other errors

        Security Note:
            Never log the returned secret value.

        Example:
            >>> backend = SomeBackend()
            >>> db_password = backend.get_secret("database/password")
        """
        pass

    @abstractmethod
    def set_secret(self, key: str, value: str) -> None:
        """Store a secret.

        Args:
            key: Secret key/name
            value: Secret value

        Raises:
            SecretAccessDenied: If access denied
            SecretError: For other errors

        Security Note:
            Ensure value is encrypted at rest.

        Example:
            >>> backend = SomeBackend()
            >>> backend.set_secret("api/key", "secret-value")
        """
        pass

    @abstractmethod
    def delete_secret(self, key: str) -> None:
        """Delete a secret.

        Args:
            key: Secret key/name

        Raises:
            SecretNotFound: If secret not found
            SecretAccessDenied: If access denied
            SecretError: For other errors

        Example:
            >>> backend = SomeBackend()
            >>> backend.delete_secret("old/key")
        """
        pass

    @abstractmethod
    def list_secrets(self, prefix: str = "") -> list[str]:
        """List all secret keys with optional prefix filter.

        Args:
            prefix: Optional prefix to filter keys

        Returns:
            List of secret keys (not values!)

        Raises:
            SecretAccessDenied: If access denied
            SecretError: For other errors

        Security Note:
            Only returns keys, never values.

        Example:
            >>> backend = SomeBackend()
            >>> keys = backend.list_secrets("database/")
            >>> print(keys)  # ['database/password', 'database/username']
        """
        pass

    def exists(self, key: str) -> bool:
        """Check if a secret exists.

        Args:
            key: Secret key/name

        Returns:
            True if secret exists, False otherwise

        Example:
            >>> backend = SomeBackend()
            >>> if backend.exists("api/key"):
            ...     key = backend.get_secret("api/key")
        """
        try:
            return self.get_secret(key) is not None
        except Exception:
            return False
