"""Errors raised by data source connectors.

Messages are written to be safe to return to API callers: they never contain
connection strings, credentials or driver internals.
"""

from __future__ import annotations


class DataSourceError(Exception):
    """A data source operation failed (the message is safe to show to callers)."""


class DataSourceUnavailable(DataSourceError):
    """The database could not be reached or refused the connection."""


class DataSourceUnsafe(DataSourceError):
    """The configured role is too powerful to use; the connector refuses to run."""


class TableNotPermitted(DataSourceError):
    """The table is outside the configured schemas/patterns."""


class TableNotFound(DataSourceError):
    """The table does not exist (or is not a kind the connector reads)."""


class QueryTimeout(DataSourceError):
    """A statement exceeded its time limit and was cancelled by the server."""
