"""Connectors that let agents work on real data sources.

Import the concrete connector explicitly (it needs optional dependencies)::

    from unistax.agents.connectors.postgres import PostgresConfig, PostgresDataSource
"""

from unistax.agents.connectors.errors import (
    DataSourceError,
    DataSourceUnavailable,
    DataSourceUnsafe,
    QueryTimeout,
    TableNotFound,
    TableNotPermitted,
)

__all__ = [
    "DataSourceError",
    "DataSourceUnavailable",
    "DataSourceUnsafe",
    "QueryTimeout",
    "TableNotFound",
    "TableNotPermitted",
]
