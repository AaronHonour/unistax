"""Secrets Management Module.

Provides secure secret storage and retrieval with:
- Multiple backend support (environment, file, cloud)
- In-memory caching with TTL
- Type conversion (string, int, bool, JSON, list)
- Secret validation and required secrets checking
- Fallback mechanism across multiple backends
- Comprehensive logging for audit trails

Security Benefits:
- Never logs secret values
- Supports secure file permissions
- Environment variable isolation
- Type safety and validation
- Access control and audit logging

Backends:
- EnvironmentBackend: Load from environment variables or .env files
- FileBackend: Load from JSON files with secure permissions
- (Future: AWS Secrets Manager, GCP Secret Manager, Azure Key Vault)

Examples:
    >>> # Environment variables (development)
    >>> from unistax.secrets import SecretManager, EnvironmentBackend
    >>>
    >>> backend = EnvironmentBackend.from_dotenv(".env")
    >>> manager = SecretManager(backend)
    >>> db_password = manager.get("DATABASE_PASSWORD")
    >>>
    >>> # File-based (local deployment)
    >>> from unistax.secrets import SecretManager, FileBackend
    >>>
    >>> backend = FileBackend("secrets.json", mode=0o600)
    >>> manager = SecretManager(backend, cache_ttl=300)
    >>> api_key = manager.get("API_KEY")
    >>>
    >>> # Multiple backends with fallback
    >>> from unistax.secrets import SecretManager, EnvironmentBackend, FileBackend
    >>>
    >>> manager = SecretManager([
    ...     EnvironmentBackend(),  # Try environment first
    ...     FileBackend("secrets.json"),  # Fallback to file
    ... ])
    >>> secret = manager.get("SECRET_KEY")
    >>>
    >>> # Type conversion
    >>> debug = manager.get_bool("DEBUG", default=False)
    >>> max_connections = manager.get_int("MAX_CONNECTIONS", default=10)
    >>> config = manager.get_json("APP_CONFIG", default={})
    >>> allowed_hosts = manager.get_list("ALLOWED_HOSTS")
    >>>
    >>> # Required secrets validation
    >>> manager = SecretManager(
    ...     backend,
    ...     required_secrets=["DATABASE_URL", "SECRET_KEY"],
    ... )
    >>> # Raises SecretNotFound if any are missing

Best Practices:
    1. **Development:**
       - Use EnvironmentBackend with .env files
       - Add .env to .gitignore
       - Never commit secrets to version control

    2. **Local Deployment:**
       - Use FileBackend with mode=0o600
       - Store secrets file outside application directory
       - Use encryption for highly sensitive secrets

    3. **Production:**
       - Use cloud secret managers (AWS, GCP, Azure)
       - Enable secret rotation
       - Use IAM roles for access control
       - Enable audit logging

    4. **General:**
       - Use required_secrets to validate configuration on startup
       - Use type conversion methods for type safety
       - Enable caching for frequently accessed secrets
       - Never log secret values

Security Considerations:
    - Environment variables may be visible in process listings
    - File-based secrets need proper file permissions (0600 or 0400)
    - Always use HTTPS for cloud secret managers
    - Implement secret rotation policies
    - Use separate secrets for different environments
    - Monitor secret access for suspicious activity
"""

from .adapters import EnvironmentBackend, FileBackend
from .base import SecretBackend
from .exceptions import (
    SecretAccessDenied,
    SecretError,
    SecretInvalidFormat,
    SecretNotFound,
)
from .manager import SecretManager

__all__ = [
    # Main classes
    "SecretManager",
    "SecretBackend",
    # Adapters
    "EnvironmentBackend",
    "FileBackend",
    # Exceptions
    "SecretError",
    "SecretNotFound",
    "SecretAccessDenied",
    "SecretInvalidFormat",
]
