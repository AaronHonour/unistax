"""Unified secrets manager with caching and type conversion."""

import json
import logging
import time
from typing import Any

from .base import SecretBackend
from .exceptions import SecretError, SecretInvalidFormat, SecretNotFound

logger = logging.getLogger(__name__)


class SecretManager:
    """Unified secrets manager with caching, validation, and type conversion.

    Provides a high-level interface for managing secrets with:
    - Multiple backend support (environment, file, cloud)
    - In-memory caching with TTL
    - Type conversion (string, int, bool, JSON)
    - Secret validation
    - Fallback to default values
    - Automatic key normalization

    Security Features:
        - Never logs secret values
        - Secure caching with TTL
        - Type validation
        - Access logging for audit trails
        - Fallback mechanism for missing secrets

    Examples:
        >>> from unistax.secrets import SecretManager, EnvironmentBackend
        >>>
        >>> # Basic usage with environment variables
        >>> backend = EnvironmentBackend()
        >>> manager = SecretManager(backend)
        >>> db_password = manager.get("DATABASE_PASSWORD")
        >>>
        >>> # With caching (5 minute TTL)
        >>> manager = SecretManager(backend, cache_ttl=300)
        >>> api_key = manager.get("API_KEY")  # Cached for 5 minutes
        >>>
        >>> # Type conversion
        >>> debug_mode = manager.get_bool("DEBUG", default=False)
        >>> max_retries = manager.get_int("MAX_RETRIES", default=3)
        >>> config = manager.get_json("APP_CONFIG", default={})
        >>>
        >>> # Multiple backends with fallback
        >>> env_backend = EnvironmentBackend()
        >>> file_backend = FileBackend("secrets.json")
        >>> manager = SecretManager([env_backend, file_backend])
        >>> # Tries env first, then file
        >>> secret = manager.get("API_KEY")
    """

    def __init__(
        self,
        backend: SecretBackend | list[SecretBackend],
        cache_ttl: int | None = None,
        required_secrets: list[str] | None = None,
    ) -> None:
        """Initialize secrets manager.

        Args:
            backend: Secret backend(s) - single or list for fallback
            cache_ttl: Cache TTL in seconds (None = no caching)
            required_secrets: List of required secrets to validate on init

        Raises:
            SecretNotFound: If any required secrets are missing

        Example:
            >>> from unistax.secrets import SecretManager, EnvironmentBackend
            >>>
            >>> # Single backend
            >>> manager = SecretManager(EnvironmentBackend())
            >>>
            >>> # Multiple backends with fallback
            >>> manager = SecretManager([
            ...     EnvironmentBackend(),
            ...     FileBackend("secrets.json"),
            ... ])
            >>>
            >>> # With caching and required secrets
            >>> manager = SecretManager(
            ...     EnvironmentBackend(),
            ...     cache_ttl=300,
            ...     required_secrets=["DATABASE_URL", "SECRET_KEY"],
            ... )
        """
        self.backends = backend if isinstance(backend, list) else [backend]
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[str, float]] = {}  # key -> (value, timestamp)

        logger.info(
            "SecretManager initialized: backends=%d, cache_ttl=%s",
            len(self.backends),
            f"{cache_ttl}s" if cache_ttl else "disabled",
        )

        # Validate required secrets
        if required_secrets:
            self._validate_required_secrets(required_secrets)

    def _validate_required_secrets(self, required: list[str]) -> None:
        """Validate that all required secrets are available.

        Args:
            required: List of required secret keys

        Raises:
            SecretNotFound: If any required secrets are missing
        """
        missing = []
        for key in required:
            try:
                self.get(key)
            except SecretNotFound:
                missing.append(key)

        if missing:
            raise SecretNotFound(f"Missing required secrets: {', '.join(missing)}")

        logger.info("All required secrets validated: %d", len(required))

    def _get_from_cache(self, key: str) -> str | None:
        """Get secret from cache if available and not expired.

        Args:
            key: Secret key

        Returns:
            Cached value or None
        """
        if self.cache_ttl is None:
            return None

        if key in self._cache:
            value, timestamp = self._cache[key]
            age = time.time() - timestamp

            if age < self.cache_ttl:
                logger.debug("Cache hit: %s (age=%.1fs)", key, age)
                return value

            # Expired - remove from cache
            logger.debug("Cache expired: %s (age=%.1fs)", key, age)
            del self._cache[key]

        return None

    def _set_in_cache(self, key: str, value: str) -> None:
        """Store secret in cache.

        Args:
            key: Secret key
            value: Secret value
        """
        if self.cache_ttl is not None:
            self._cache[key] = (value, time.time())
            logger.debug("Cached secret: %s (ttl=%ds)", key, self.cache_ttl)

    def get(self, key: str, default: Any = None) -> str:
        """Get secret value.

        Tries backends in order until secret is found.
        Uses cache if available.

        Args:
            key: Secret key
            default: Default value if not found

        Returns:
            Secret value

        Raises:
            SecretNotFound: If secret not found and no default

        Example:
            >>> manager = SecretManager(EnvironmentBackend())
            >>> db_password = manager.get("DATABASE_PASSWORD")
            >>> api_key = manager.get("API_KEY", default="dev-key")
        """
        # Try cache first
        cached = self._get_from_cache(key)
        if cached is not None:
            return cached

        # Try backends in order
        last_error = None
        for backend in self.backends:
            try:
                value = backend.get_secret(key)
                if value is not None:
                    self._set_in_cache(key, value)
                    logger.debug("Secret retrieved: %s (backend=%s)", key, type(backend).__name__)
                    return value
            except SecretNotFound as e:
                last_error = e
                continue
            except SecretError as e:
                logger.warning(
                    "Error retrieving secret %s from %s: %s",
                    key,
                    type(backend).__name__,
                    e,
                )
                last_error = e
                continue

        # Not found in any backend
        if default is not None:
            logger.debug("Secret not found: %s (using default)", key)
            return default

        logger.warning("Secret not found in any backend: %s", key)
        raise last_error or SecretNotFound(f"Secret not found: {key}")

    def get_int(self, key: str, default: int | None = None) -> int:
        """Get secret as integer.

        Args:
            key: Secret key
            default: Default value if not found

        Returns:
            Secret value as integer

        Raises:
            SecretNotFound: If secret not found and no default
            SecretInvalidFormat: If value is not a valid integer

        Example:
            >>> manager = SecretManager(EnvironmentBackend())
            >>> max_connections = manager.get_int("MAX_CONNECTIONS", default=10)
        """
        value = self.get(key, default=default)
        if value is None:
            if default is not None:
                return default
            raise SecretNotFound(f"Secret not found: {key}")

        try:
            return int(value)
        except ValueError as e:
            raise SecretInvalidFormat(f"Secret {key} is not a valid integer: {value}") from e

    def get_float(self, key: str, default: float | None = None) -> float:
        """Get secret as float.

        Args:
            key: Secret key
            default: Default value if not found

        Returns:
            Secret value as float

        Raises:
            SecretNotFound: If secret not found and no default
            SecretInvalidFormat: If value is not a valid float

        Example:
            >>> manager = SecretManager(EnvironmentBackend())
            >>> timeout = manager.get_float("TIMEOUT_SECONDS", default=30.0)
        """
        value = self.get(key, default=default)
        if value is None:
            if default is not None:
                return default
            raise SecretNotFound(f"Secret not found: {key}")

        try:
            return float(value)
        except ValueError as e:
            raise SecretInvalidFormat(f"Secret {key} is not a valid float: {value}") from e

    def get_bool(self, key: str, default: bool | None = None) -> bool:
        """Get secret as boolean.

        Accepts: true/false, yes/no, 1/0, on/off (case-insensitive).

        Args:
            key: Secret key
            default: Default value if not found

        Returns:
            Secret value as boolean

        Raises:
            SecretNotFound: If secret not found and no default
            SecretInvalidFormat: If value is not a valid boolean

        Example:
            >>> manager = SecretManager(EnvironmentBackend())
            >>> debug_mode = manager.get_bool("DEBUG", default=False)
        """
        value = self.get(key, default=default)
        if value is None:
            if default is not None:
                return default
            raise SecretNotFound(f"Secret not found: {key}")

        if isinstance(value, bool):
            return value

        value_lower = str(value).lower()
        if value_lower in ("true", "yes", "1", "on"):
            return True
        if value_lower in ("false", "no", "0", "off"):
            return False

        raise SecretInvalidFormat(f"Secret {key} is not a valid boolean: {value}")

    def get_json(self, key: str, default: Any = None) -> Any:
        """Get secret as parsed JSON.

        Args:
            key: Secret key
            default: Default value if not found

        Returns:
            Parsed JSON value (dict, list, etc.)

        Raises:
            SecretNotFound: If secret not found and no default
            SecretInvalidFormat: If value is not valid JSON

        Example:
            >>> manager = SecretManager(EnvironmentBackend())
            >>> config = manager.get_json("APP_CONFIG", default={})
            >>> # APP_CONFIG='{"debug": true, "port": 8000}'
            >>> print(config["debug"])  # True
        """
        value = self.get(key, default=default)
        if value is None:
            if default is not None:
                return default
            raise SecretNotFound(f"Secret not found: {key}")

        if not isinstance(value, str):
            return value

        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            raise SecretInvalidFormat(f"Secret {key} is not valid JSON: {value}") from e

    def get_list(
        self, key: str, separator: str = ",", default: list[str] | None = None
    ) -> list[str]:
        """Get secret as list (split by separator).

        Args:
            key: Secret key
            separator: Separator character (default: ",")
            default: Default value if not found

        Returns:
            List of strings

        Raises:
            SecretNotFound: If secret not found and no default

        Example:
            >>> manager = SecretManager(EnvironmentBackend())
            >>> # ALLOWED_HOSTS="localhost,example.com,*.example.org"
            >>> hosts = manager.get_list("ALLOWED_HOSTS")
            >>> # ['localhost', 'example.com', '*.example.org']
        """
        value = self.get(key, default=default)
        if value is None:
            if default is not None:
                return default
            raise SecretNotFound(f"Secret not found: {key}")

        if isinstance(value, list):
            return value

        return [item.strip() for item in str(value).split(separator) if item.strip()]

    def set(self, key: str, value: str) -> None:
        """Set secret in first writable backend.

        Args:
            key: Secret key
            value: Secret value

        Raises:
            SecretError: If no writable backends available

        Example:
            >>> manager = SecretManager(FileBackend("secrets.json"))
            >>> manager.set("API_KEY", "new-secret-value")
        """
        for backend in self.backends:
            try:
                backend.set_secret(key, value)
                # Invalidate cache
                if key in self._cache:
                    del self._cache[key]
                logger.info("Secret set: %s (backend=%s)", key, type(backend).__name__)
                return
            except Exception as e:
                logger.warning("Error setting secret in %s: %s", type(backend).__name__, e)
                continue

        raise SecretError(f"Failed to set secret {key} in any backend")

    def delete(self, key: str) -> None:
        """Delete secret from all backends.

        Args:
            key: Secret key

        Example:
            >>> manager = SecretManager(FileBackend("secrets.json"))
            >>> manager.delete("OLD_API_KEY")
        """
        deleted = False
        for backend in self.backends:
            try:
                backend.delete_secret(key)
                deleted = True
                logger.info("Secret deleted: %s (backend=%s)", key, type(backend).__name__)
            except SecretNotFound:
                continue
            except Exception as e:
                logger.warning("Error deleting secret from %s: %s", type(backend).__name__, e)
                continue

        # Invalidate cache
        if key in self._cache:
            del self._cache[key]

        if not deleted:
            raise SecretNotFound(f"Secret not found: {key}")

    def list(self, prefix: str = "") -> list[str]:
        """List all secret keys with optional prefix.

        Combines keys from all backends (deduplicated).

        Args:
            prefix: Optional prefix to filter keys

        Returns:
            Sorted list of unique secret keys

        Example:
            >>> manager = SecretManager(FileBackend("secrets.json"))
            >>> database_secrets = manager.list("database/")
            >>> # ['database/password', 'database/username', 'database/host']
        """
        all_keys: set[str] = set()

        for backend in self.backends:
            try:
                keys = backend.list_secrets(prefix)
                all_keys.update(keys)
            except Exception as e:
                logger.warning("Error listing secrets from %s: %s", type(backend).__name__, e)
                continue

        return sorted(all_keys)

    def exists(self, key: str) -> bool:
        """Check if secret exists in any backend.

        Args:
            key: Secret key

        Returns:
            True if secret exists

        Example:
            >>> manager = SecretManager(EnvironmentBackend())
            >>> if manager.exists("API_KEY"):
            ...     api_key = manager.get("API_KEY")
        """
        try:
            self.get(key)
            return True
        except SecretNotFound:
            return False

    def clear_cache(self) -> None:
        """Clear the secret cache.

        Useful for testing or when secrets are updated externally.

        Example:
            >>> manager = SecretManager(backend, cache_ttl=300)
            >>> manager.clear_cache()
        """
        self._cache.clear()
        logger.info("Secret cache cleared")

    def require(self, *keys: str) -> None:
        """Validate that required secrets exist.

        Args:
            *keys: Required secret keys

        Raises:
            SecretNotFound: If any required secrets are missing

        Example:
            >>> manager = SecretManager(EnvironmentBackend())
            >>> manager.require("DATABASE_URL", "SECRET_KEY", "API_KEY")
        """
        self._validate_required_secrets(list(keys))
