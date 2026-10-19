"""Local secret storage adapters for development and deployment."""

import json
import logging
import os
from pathlib import Path
from typing import Any

from .base import SecretBackend
from .exceptions import SecretAccessDenied, SecretInvalidFormat, SecretNotFound

logger = logging.getLogger(__name__)


class EnvironmentBackend(SecretBackend):
    """Environment variable-based secret storage.

    Reads secrets from environment variables. Useful for local development
    and containerized deployments.

    Security Features:
        - No secrets stored on disk (except in .env files)
        - Works with docker-compose, kubernetes secrets, etc.
        - Simple and widely supported
        - Can use .env files for local development

    Security Considerations:
        - Environment variables may be visible in process listings
        - Not suitable for highly sensitive secrets in production
        - Use encryption at rest for .env files
        - Never commit .env files to version control

    Examples:
        >>> # Basic usage
        >>> backend = EnvironmentBackend()
        >>> db_password = backend.get_secret("DATABASE_PASSWORD")
        >>>
        >>> # With prefix (namespace)
        >>> backend = EnvironmentBackend(prefix="MYAPP_")
        >>> # Looks for MYAPP_DATABASE_PASSWORD
        >>> db_password = backend.get_secret("DATABASE_PASSWORD")
        >>>
        >>> # Load from .env file
        >>> backend = EnvironmentBackend.from_dotenv(".env")
        >>> api_key = backend.get_secret("API_KEY")
    """

    def __init__(self, prefix: str = "", case_sensitive: bool = False) -> None:
        """Initialize environment backend.

        Args:
            prefix: Prefix for all environment variable names
            case_sensitive: Whether to preserve case (default: False, convert to uppercase)

        Example:
            >>> backend = EnvironmentBackend(prefix="MYAPP_")
            >>> secret = backend.get_secret("database_password")
            >>> # Looks for MYAPP_DATABASE_PASSWORD
        """
        self.prefix = prefix
        self.case_sensitive = case_sensitive
        logger.info(
            "EnvironmentBackend initialized: prefix=%s, case_sensitive=%s",
            prefix or "(none)",
            case_sensitive,
        )

    @classmethod
    def from_dotenv(cls, dotenv_path: str = ".env", **kwargs: Any) -> "EnvironmentBackend":
        """Create backend and load .env file.

        Args:
            dotenv_path: Path to .env file (default: ".env")
            **kwargs: Additional arguments for EnvironmentBackend

        Returns:
            EnvironmentBackend instance

        Security Warning:
            Never commit .env files to version control!
            Add .env to .gitignore

        Example:
            >>> backend = EnvironmentBackend.from_dotenv(".env.local")
            >>> db_url = backend.get_secret("DATABASE_URL")
        """
        # Load .env file if it exists
        dotenv_file = Path(dotenv_path)
        if dotenv_file.exists():
            logger.info("Loading environment variables from %s", dotenv_path)
            with open(dotenv_file) as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith("#"):
                        continue
                    # Parse KEY=VALUE
                    if "=" in line:
                        key, value = line.split("=", 1)
                        # Remove quotes if present
                        value = value.strip().strip("\"'")
                        os.environ[key.strip()] = value
            logger.info("Loaded environment variables from %s", dotenv_path)
        else:
            logger.warning(".env file not found: %s", dotenv_path)

        return cls(**kwargs)

    def _make_env_key(self, key: str) -> str:
        """Convert secret key to environment variable name.

        Args:
            key: Secret key

        Returns:
            Environment variable name

        Example:
            >>> backend = EnvironmentBackend(prefix="APP_")
            >>> backend._make_env_key("database/password")
            'APP_DATABASE_PASSWORD'
        """
        # Replace slashes and dots with underscores
        env_key = key.replace("/", "_").replace(".", "_").replace("-", "_")

        # Convert to uppercase unless case sensitive
        if not self.case_sensitive:
            env_key = env_key.upper()

        # Add prefix
        return f"{self.prefix}{env_key}"

    def get_secret(self, key: str, default: Any = None) -> str | None:
        """Retrieve secret from environment variable.

        Args:
            key: Secret key (will be converted to ENV_VAR_NAME)
            default: Default value if not found

        Returns:
            Secret value or default

        Raises:
            SecretNotFound: If secret not found and no default

        Example:
            >>> backend = EnvironmentBackend()
            >>> db_password = backend.get_secret("DATABASE_PASSWORD")
        """
        env_key = self._make_env_key(key)
        value = os.environ.get(env_key)

        if value is None:
            if default is not None:
                logger.debug("Secret not found: %s (using default)", key)
                return default
            logger.warning("Secret not found: %s (env: %s)", key, env_key)
            raise SecretNotFound(f"Secret not found: {key} (env: {env_key})")

        logger.debug("Secret retrieved: %s", key)
        return value

    def set_secret(self, key: str, value: str) -> None:
        """Set environment variable.

        Args:
            key: Secret key
            value: Secret value

        Note:
            This only affects the current process. Changes are not persistent.

        Example:
            >>> backend = EnvironmentBackend()
            >>> backend.set_secret("API_KEY", "secret-value")
        """
        env_key = self._make_env_key(key)
        os.environ[env_key] = value
        logger.info("Secret set: %s", key)

    def delete_secret(self, key: str) -> None:
        """Delete environment variable.

        Args:
            key: Secret key

        Raises:
            SecretNotFound: If secret not found

        Example:
            >>> backend = EnvironmentBackend()
            >>> backend.delete_secret("OLD_API_KEY")
        """
        env_key = self._make_env_key(key)
        if env_key not in os.environ:
            raise SecretNotFound(f"Secret not found: {key} (env: {env_key})")

        del os.environ[env_key]
        logger.info("Secret deleted: %s", key)

    def list_secrets(self, prefix: str = "") -> list[str]:
        """List all environment variables with optional prefix.

        Args:
            prefix: Optional prefix to filter keys

        Returns:
            List of secret keys (converted back from env var names)

        Example:
            >>> backend = EnvironmentBackend(prefix="MYAPP_")
            >>> keys = backend.list_secrets("DATABASE")
            >>> # Returns keys like 'DATABASE_PASSWORD', 'DATABASE_USERNAME'
        """
        env_prefix = prefix.replace("/", "_").replace(".", "_").replace("-", "_")
        if not self.case_sensitive:
            env_prefix = env_prefix.upper()
        full_prefix = f"{self.prefix}{env_prefix}"

        keys = []
        for env_key in os.environ:
            if env_key.startswith(full_prefix):
                # Convert back to secret key format
                secret_key = env_key[len(self.prefix) :]
                if not self.case_sensitive:
                    secret_key = secret_key.lower()
                keys.append(secret_key)

        logger.debug("Listed %d secrets with prefix: %s", len(keys), prefix)
        return sorted(keys)


class FileBackend(SecretBackend):
    """File-based secret storage for local deployments.

    Stores secrets in a JSON file on disk. Useful for local deployments,
    testing, and development environments.

    Security Features:
        - Optional file permissions checking (0600 recommended)
        - JSON format for easy management
        - File-based access control
        - Optional encryption (requires cryptography library)

    Security Considerations:
        - File should have restrictive permissions (0600 or 0400)
        - Use encryption for sensitive secrets
        - Not suitable for distributed systems
        - Secrets are stored in plaintext by default (use encryption!)
        - Never commit secrets file to version control

    Examples:
        >>> # Basic usage
        >>> backend = FileBackend("secrets.json")
        >>> db_password = backend.get_secret("database/password")
        >>>
        >>> # Create with strict permissions
        >>> backend = FileBackend("secrets.json", mode=0o600)
        >>> backend.set_secret("api/key", "secret-value")
        >>>
        >>> # Read-only mode
        >>> backend = FileBackend("secrets.json", readonly=True)
        >>> api_key = backend.get_secret("api/key")
    """

    def __init__(
        self,
        file_path: str,
        mode: int = 0o600,
        readonly: bool = False,
        create_if_missing: bool = True,
    ) -> None:
        """Initialize file backend.

        Args:
            file_path: Path to secrets file
            mode: File permissions (default: 0o600 = rw-------)
            readonly: Whether to allow writes (default: False)
            create_if_missing: Create file if it doesn't exist (default: True)

        Security Note:
            Use mode=0o600 (rw-------) or 0o400 (r--------) for production.
            Never use world-readable permissions!

        Example:
            >>> backend = FileBackend("secrets.json", mode=0o600)
        """
        self.file_path = Path(file_path)
        self.mode = mode
        self.readonly = readonly
        self._secrets: dict[str, str] = {}

        # Create file if it doesn't exist
        if not self.file_path.exists():
            if create_if_missing and not readonly:
                logger.info("Creating secrets file: %s", file_path)
                self.file_path.parent.mkdir(parents=True, exist_ok=True)
                self.file_path.write_text("{}")
                self.file_path.chmod(mode)
            elif not create_if_missing:
                raise SecretNotFound(f"Secrets file not found: {file_path}")
        else:
            # Check file permissions
            current_mode = self.file_path.stat().st_mode & 0o777
            if current_mode & 0o077:  # Check if group/other have any permissions
                logger.warning(
                    "Secrets file has insecure permissions: %s (mode: %o). "
                    "Recommended: 0600 or 0400",
                    file_path,
                    current_mode,
                )

        # Load secrets
        self._load()

        logger.info(
            "FileBackend initialized: file=%s, mode=%o, readonly=%s, secrets=%d",
            file_path,
            mode,
            readonly,
            len(self._secrets),
        )

    def _load(self) -> None:
        """Load secrets from file."""
        try:
            content = self.file_path.read_text()
            self._secrets = json.loads(content) if content.strip() else {}
            logger.debug("Loaded %d secrets from %s", len(self._secrets), self.file_path)
        except json.JSONDecodeError as e:
            raise SecretInvalidFormat(f"Invalid JSON in secrets file: {self.file_path}") from e
        except PermissionError as e:
            raise SecretAccessDenied(
                f"Permission denied reading secrets file: {self.file_path}"
            ) from e

    def _save(self) -> None:
        """Save secrets to file."""
        if self.readonly:
            raise SecretAccessDenied("Backend is read-only")

        try:
            # Write with secure permissions
            content = json.dumps(self._secrets, indent=2)
            self.file_path.write_text(content)
            self.file_path.chmod(self.mode)
            logger.debug("Saved %d secrets to %s", len(self._secrets), self.file_path)
        except PermissionError as e:
            raise SecretAccessDenied(
                f"Permission denied writing secrets file: {self.file_path}"
            ) from e

    def get_secret(self, key: str, default: Any = None) -> str | None:
        """Retrieve secret from file.

        Args:
            key: Secret key
            default: Default value if not found

        Returns:
            Secret value or default

        Raises:
            SecretNotFound: If secret not found and no default

        Example:
            >>> backend = FileBackend("secrets.json")
            >>> db_password = backend.get_secret("database/password")
        """
        value = self._secrets.get(key)

        if value is None:
            if default is not None:
                logger.debug("Secret not found: %s (using default)", key)
                return default
            logger.warning("Secret not found: %s", key)
            raise SecretNotFound(f"Secret not found: {key}")

        logger.debug("Secret retrieved: %s", key)
        return value

    def set_secret(self, key: str, value: str) -> None:
        """Store secret in file.

        Args:
            key: Secret key
            value: Secret value

        Raises:
            SecretAccessDenied: If backend is read-only

        Example:
            >>> backend = FileBackend("secrets.json")
            >>> backend.set_secret("api/key", "secret-value")
        """
        if self.readonly:
            raise SecretAccessDenied("Backend is read-only")

        self._secrets[key] = value
        self._save()
        logger.info("Secret set: %s", key)

    def delete_secret(self, key: str) -> None:
        """Delete secret from file.

        Args:
            key: Secret key

        Raises:
            SecretNotFound: If secret not found
            SecretAccessDenied: If backend is read-only

        Example:
            >>> backend = FileBackend("secrets.json")
            >>> backend.delete_secret("old/key")
        """
        if self.readonly:
            raise SecretAccessDenied("Backend is read-only")

        if key not in self._secrets:
            raise SecretNotFound(f"Secret not found: {key}")

        del self._secrets[key]
        self._save()
        logger.info("Secret deleted: %s", key)

    def list_secrets(self, prefix: str = "") -> list[str]:
        """List all secret keys with optional prefix filter.

        Args:
            prefix: Optional prefix to filter keys

        Returns:
            List of secret keys

        Example:
            >>> backend = FileBackend("secrets.json")
            >>> keys = backend.list_secrets("database/")
            >>> # Returns ['database/password', 'database/username']
        """
        if prefix:
            keys = [k for k in self._secrets.keys() if k.startswith(prefix)]
        else:
            keys = list(self._secrets.keys())

        logger.debug("Listed %d secrets with prefix: %s", len(keys), prefix)
        return sorted(keys)

    def reload(self) -> None:
        """Reload secrets from file.

        Useful if the file has been modified externally.

        Example:
            >>> backend = FileBackend("secrets.json")
            >>> # ... file modified externally ...
            >>> backend.reload()
        """
        self._load()
        logger.info("Reloaded secrets from %s", self.file_path)
