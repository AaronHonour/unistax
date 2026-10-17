"""Runtime configuration for the agent API, read from environment variables.

All variables use the ``UNISTAX_AGENT_API_`` prefix, e.g.
``UNISTAX_AGENT_API_DATABASE_URL`` or ``UNISTAX_AGENT_API_JWT_SECRET``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from unistax.agents.connectors.postgres import PostgresConfig

ENV_PREFIX = "UNISTAX_AGENT_API_"

_MIN_HMAC_SECRET_LENGTH = {"HS256": 32, "HS384": 48, "HS512": 64}


def _to_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AgentAPISettings:
    """Configuration for the agent API service."""

    # Persistence
    database_url: str = field(default="sqlite+aiosqlite:///./agents.db", repr=False)
    auto_migrate: bool = True
    restore_on_start: bool = True

    # Authentication (fails closed: a secret is required unless auth is disabled)
    auth_enabled: bool = True
    jwt_secret: str | None = field(default=None, repr=False)
    jwt_public_key: str | None = None
    jwt_algorithm: str = "HS256"
    jwt_audience: str | None = None
    jwt_issuer: str | None = None

    # Data source the Steward/Engineer agents inspect (read-only PostgreSQL). Server-side
    # configuration only: callers can never supply or change a connection string.
    datasource_url: str | None = field(default=None, repr=False)
    datasource_name: str = "warehouse"
    datasource_schemas: tuple[str, ...] = ("public",)
    datasource_tables: tuple[str, ...] = ("*",)
    datasource_catalog_timeout_ms: int = 5_000
    datasource_scan_timeout_ms: int = 10_000
    datasource_sample_rows: int = 1_000
    datasource_max_scan_rows: int = 100_000
    datasource_max_tables: int = 200
    datasource_pool_size: int = 3
    datasource_session_defaults: bool = True

    # HTTP
    api_prefix: str = "/api/v1"
    cors_origins: tuple[str, ...] = ()
    docs_enabled: bool = True
    max_request_bytes: int = 1_048_576

    # Rate limiting (counters are per process)
    rate_limit_enabled: bool = True
    rate_limit: int = 120
    rate_limit_window: int = 60
    expensive_rate_limit: int = 30

    # Execution
    max_running_tasks: int = 20
    priority_aging_seconds: float = 30.0
    shutdown_timeout: float = 15.0

    # WebSocket
    ws_max_connections: int = 100
    ws_queue_size: int = 256
    ws_auth_timeout: float = 10.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **overrides: Any) -> AgentAPISettings:
        """Build settings from environment variables, then apply ``overrides``."""
        env = os.environ if env is None else env
        values: dict[str, Any] = {}

        for f in fields(cls):
            raw = env.get(ENV_PREFIX + f.name.upper())
            if raw is None or raw == "":
                continue
            default = getattr(cls, f.name)
            if isinstance(default, tuple):
                values[f.name] = tuple(o.strip() for o in raw.split(",") if o.strip())
            elif isinstance(default, bool):
                values[f.name] = _to_bool(raw)
            elif isinstance(default, int):
                values[f.name] = int(raw)
            elif isinstance(default, float):
                values[f.name] = float(raw)
            else:
                values[f.name] = raw

        return replace(cls(**values), **overrides)

    def datasource_config(self) -> PostgresConfig:
        """The data source settings as a connector config (requires ``datasource_url``)."""
        from unistax.agents.connectors.postgres import PostgresConfig

        return PostgresConfig(
            url=self.datasource_url or "",
            name=self.datasource_name,
            schemas=self.datasource_schemas,
            table_patterns=self.datasource_tables,
            catalog_timeout_ms=self.datasource_catalog_timeout_ms,
            scan_timeout_ms=self.datasource_scan_timeout_ms,
            sample_rows=self.datasource_sample_rows,
            max_scan_rows=self.datasource_max_scan_rows,
            max_tables=self.datasource_max_tables,
            pool_size=self.datasource_pool_size,
            session_defaults=self.datasource_session_defaults,
        )

    def validate(self) -> None:
        """Raise ``ValueError`` for configurations that are unsafe or unusable."""
        if self.auth_enabled:
            key = self.jwt_public_key or self.jwt_secret
            if not key:
                raise ValueError(
                    "Authentication is enabled but no key is configured. Set "
                    f"{ENV_PREFIX}JWT_SECRET (or {ENV_PREFIX}JWT_PUBLIC_KEY), or "
                    f"explicitly disable auth with {ENV_PREFIX}AUTH_ENABLED=false."
                )
            minimum = _MIN_HMAC_SECRET_LENGTH.get(self.jwt_algorithm)
            if minimum and len(key) < minimum:
                raise ValueError(
                    f"{self.jwt_algorithm} secret must be at least {minimum} characters"
                )
        if "*" in self.cors_origins:
            raise ValueError("Wildcard CORS origins are not allowed; list origins explicitly")
        if not self.api_prefix.startswith("/") or self.api_prefix.endswith("/"):
            raise ValueError("api_prefix must start with '/' and must not end with '/'")
        if self.max_running_tasks < 1:
            raise ValueError("max_running_tasks must be >= 1")
        if self.datasource_url:
            self.datasource_config().validate()
        if self.priority_aging_seconds < 0:
            raise ValueError("priority_aging_seconds must be >= 0 (0 = strict priority)")
