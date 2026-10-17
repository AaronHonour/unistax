"""Read-only PostgreSQL data source.

Safety model (every layer is independent; any one of them stops a write):

1. **Role.** ``verify()`` refuses superusers and members of ``pg_write_all_data``,
   and warns when the role holds write privileges. Give agents a dedicated
   ``SELECT``-only role (see AGENTS.md).
2. **Session.** Every transaction starts with ``SET TRANSACTION READ ONLY`` and,
   unless disabled for connection poolers, connections also start with
   ``default_transaction_read_only=on``.
3. **Scope.** Only configured schemas / table patterns are reachable. Pure
   metadata queries use bound parameters.
4. **No caller SQL.** The only SQL text is built in this package, and the only
   identifiers interpolated into it come from the database catalog (never from
   task input) and are quoted. Callers cannot submit a query.
5. **Limits.** Per-transaction ``statement_timeout`` / ``lock_timeout``; scans are
   capped to ``max_scan_rows`` rows; samples to ``sample_rows``.

Errors raised to callers never contain the connection string or driver text.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import re
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError, DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from unistax.agents.connectors.errors import (
    DataSourceError,
    DataSourceUnavailable,
    DataSourceUnsafe,
    QueryTimeout,
    TableNotFound,
    TableNotPermitted,
)

logger = logging.getLogger(__name__)

APPLICATION_NAME = "unistax-agent-api"
KINDS = {"r": "table", "p": "partitioned_table", "v": "view", "m": "materialized_view"}
_NAME = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
MAX_IDENTIFIER_LENGTH = 255


@dataclass(frozen=True)
class PostgresConfig:
    """Connection and scope settings for one PostgreSQL data source."""

    url: str = field(repr=False)
    name: str = "warehouse"
    schemas: tuple[str, ...] = ("public",)
    table_patterns: tuple[str, ...] = ("*",)
    catalog_timeout_ms: int = 5_000
    scan_timeout_ms: int = 10_000
    sample_rows: int = 1_000
    max_scan_rows: int = 100_000
    max_tables: int = 200
    pool_size: int = 3
    connect_timeout: float = 10.0
    session_defaults: bool = True

    def validate(self) -> None:
        """Raise ``ValueError`` for settings that are unsafe or unusable."""
        if not self.url:
            raise ValueError("a data source URL is required")
        if not _NAME.match(self.name):
            raise ValueError("data source name must be 1-32 characters of letters, digits, . _ -")
        if not self.schemas:
            raise ValueError("at least one schema must be allowed")
        for schema in self.schemas:
            if schema.startswith("pg_") or schema == "information_schema" or not schema:
                raise ValueError(f"schema '{schema}' cannot be exposed to agents")
        if not self.table_patterns:
            raise ValueError("table_patterns must not be empty (use '*' to allow all)")
        for field_name in (
            "catalog_timeout_ms",
            "scan_timeout_ms",
            "sample_rows",
            "max_scan_rows",
            "max_tables",
            "pool_size",
        ):
            if getattr(self, field_name) < 1:
                raise ValueError(f"{field_name} must be >= 1")


@dataclass(frozen=True)
class TableRef:
    """A resolved, permitted relation."""

    schema: str
    name: str
    kind: str
    oid: int
    row_estimate: int | None

    @property
    def qualified_name(self) -> str:
        """``schema.name`` for display and identifiers."""
        return f"{self.schema}.{self.name}"


@dataclass(frozen=True)
class VerificationReport:
    """What ``verify()`` found."""

    server_version: str
    role: str
    warnings: tuple[str, ...] = ()


def translate_error(exc: BaseException) -> DataSourceError:
    """Map a driver/network exception to a caller-safe error."""
    code = _sqlstate(exc)
    if code in {"28P01", "28000"}:
        return DataSourceUnavailable("authentication to the data source failed")
    if code == "3D000":
        return DataSourceUnavailable("the data source database does not exist")
    if code == "57014":
        return QueryTimeout("the query exceeded its time limit and was cancelled")
    if code == "55P03":
        return QueryTimeout("could not obtain a lock in time (the table is busy)")
    if code == "42501":
        return DataSourceError("permission denied: the data source role cannot read that table")
    if code == "25006":
        return DataSourceError("the data source session is read-only")
    if isinstance(exc, PoolTimeout):
        return DataSourceUnavailable(
            "the data source is busy (no free connection); try again later"
        )
    if code is None or code.startswith(("08", "57P", "53", "58")):
        return DataSourceUnavailable("could not connect to the data source")
    return DataSourceError(f"data source error (SQLSTATE {code})")


def _sqlstate(exc: BaseException) -> str | None:
    orig = getattr(exc, "orig", exc)
    for candidate in (orig, getattr(orig, "__cause__", None)):
        code = getattr(candidate, "sqlstate", None) or getattr(candidate, "pgcode", None)
        if code:
            return str(code)
    return None


def _asyncpg_url(raw: str) -> URL:
    candidate = (
        raw.replace("postgres://", "postgresql://", 1) if raw.startswith("postgres://") else raw
    )
    try:
        url = make_url(candidate)
    except ArgumentError:
        raise DataSourceError("the data source URL is not valid") from None
    if url.get_backend_name() != "postgresql":
        raise DataSourceError("the data source URL must be a PostgreSQL URL")
    if url.drivername != "postgresql+asyncpg":
        url = url.set(drivername="postgresql+asyncpg")
    return url


class PostgresDataSource:
    """Introspection and bounded sampling of one PostgreSQL database, read-only."""

    kind = "postgres"

    def __init__(self, config: PostgresConfig) -> None:
        """Validate ``config`` and prepare (but do not open) the connection pool."""
        config.validate()
        self.config = config
        url = _asyncpg_url(config.url)
        connect_args: dict[str, Any] = {"timeout": config.connect_timeout}
        if config.session_defaults:
            connect_args["server_settings"] = {
                "application_name": APPLICATION_NAME,
                "default_transaction_read_only": "on",
            }
        self._engine: AsyncEngine = create_async_engine(
            url,
            pool_size=config.pool_size,
            max_overflow=0,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args=connect_args,
        )
        self._quote = self._engine.dialect.identifier_preparer.quote_identifier
        self._report: VerificationReport | None = None
        self._verify_lock = asyncio.Lock()
        # Callers queue here instead of timing out on an exhausted connection pool.
        self._slots = asyncio.Semaphore(config.pool_size)

    def __repr__(self) -> str:
        """Name and scope only: never the connection string."""
        return f"PostgresDataSource(name={self.config.name!r}, schemas={self.config.schemas!r})"

    @property
    def name(self) -> str:
        """Short identifier used in results and knowledge-graph ids."""
        return self.config.name

    @property
    def label(self) -> str:
        """``postgres:<name>``, shown as the ``data_source`` of results."""
        return f"postgres:{self.config.name}"

    @property
    def verified(self) -> bool:
        """Whether ``verify()`` has succeeded (no network access)."""
        return self._report is not None

    # -- lifecycle -----------------------------------------------------------
    async def close(self) -> None:
        """Release all pooled connections."""
        await self._engine.dispose()

    async def verify(self) -> VerificationReport:
        """Check connectivity and that the role is safe to use (cached once it passes).

        Raises:
            DataSourceUnsafe: The role could write (superuser / ``pg_write_all_data``) or
                a read-only session could not be established. Never cached: fixing the
                role takes effect on the next call.
            DataSourceUnavailable: The database could not be reached.
        """
        if self._report is not None:
            return self._report
        async with self._verify_lock:
            if self._report is not None:
                return self._report
            schemas = list(self.config.schemas)
            async with self.read() as conn:
                row = (
                    (
                        await conn.execute(
                            text("""
                                SELECT current_setting('transaction_read_only') AS read_only,
                                       current_setting('server_version')         AS version,
                                       current_user::text                        AS role,
                                       COALESCE((SELECT rolsuper FROM pg_roles
                                                 WHERE rolname = current_user), false) AS superuser,
                                       COALESCE((SELECT pg_has_role(current_user, oid, 'MEMBER')
                                                 FROM pg_roles
                                                 WHERE rolname = 'pg_write_all_data'), false) AS write_all,
                                       (SELECT count(*) FROM pg_namespace n
                                         WHERE n.nspname = ANY(CAST(:schemas AS text[]))
                                           AND has_schema_privilege(current_user, n.oid, 'CREATE')) AS can_create,
                                       (SELECT count(*) FROM pg_class c
                                          JOIN pg_namespace n ON n.oid = c.relnamespace
                                         WHERE n.nspname = ANY(CAST(:schemas AS text[]))
                                           AND c.relkind IN ('r', 'p')
                                           AND (has_table_privilege(current_user, c.oid, 'INSERT')
                                             OR has_table_privilege(current_user, c.oid, 'UPDATE')
                                             OR has_table_privilege(current_user, c.oid, 'DELETE')
                                             OR has_table_privilege(current_user, c.oid, 'TRUNCATE'))
                                       ) AS writable_tables
                                """),
                            {"schemas": schemas},
                        )
                    )
                    .mappings()
                    .one()
                )

            if row["read_only"] != "on":
                raise DataSourceUnsafe("could not establish a read-only session on the data source")
            if row["superuser"] or row["write_all"]:
                raise DataSourceUnsafe(
                    f"role '{row['role']}' is a superuser or can write all data; "
                    "configure a dedicated SELECT-only role for agents"
                )

            warnings: list[str] = []
            if row["writable_tables"]:
                warnings.append(
                    f"role '{row['role']}' holds write privileges on {row['writable_tables']} "
                    "table(s); sessions are read-only, but a SELECT-only role is safer"
                )
            if row["can_create"]:
                warnings.append(f"role '{row['role']}' can create objects in an exposed schema")
            for warning in warnings:
                logger.warning("data source %s: %s", self.config.name, warning)

            self._report = VerificationReport(row["version"], row["role"], tuple(warnings))
            return self._report

    # -- the only door to the database --------------------------------------------
    @asynccontextmanager
    async def read(self, *, scan: bool = False) -> AsyncIterator[AsyncConnection]:
        """A read-only, snapshot-consistent, time-limited transaction.

        Args:
            scan: Use the (longer) data-scan timeout instead of the catalog timeout.
        """
        timeout_ms = self.config.scan_timeout_ms if scan else self.config.catalog_timeout_ms
        try:
            async with self._slots, self._engine.connect() as conn, conn.begin():
                await conn.execute(
                    text("SET TRANSACTION READ ONLY, ISOLATION LEVEL REPEATABLE READ")
                )
                await conn.execute(
                    text(
                        "SELECT set_config('statement_timeout', :statement, true),"
                        "       set_config('lock_timeout', '2000', true),"
                        "       set_config('idle_in_transaction_session_timeout', '60000', true)"
                    ),
                    {"statement": str(timeout_ms)},
                )
                yield conn
        except DataSourceError:
            raise
        except (DBAPIError, PoolTimeout, OSError, TimeoutError, asyncio.TimeoutError) as exc:
            logger.debug("data source %s error: %s", self.config.name, type(exc).__name__)
            raise translate_error(exc) from None

    # -- identifiers ----------------------------------------------------------------
    def quote(self, identifier: str) -> str:
        """Quote a catalog-derived identifier for use inside SQL text.

        Colons are escaped because SQLAlchemy's ``text()`` would otherwise read
        ``:name`` inside an identifier as a bind parameter.
        """
        return self._quote(identifier).replace(":", "\\:")

    def qualified(self, ref: TableRef) -> str:
        """Quoted ``schema.table`` for a resolved relation."""
        return f"{self.quote(ref.schema)}.{self.quote(ref.name)}"

    def is_permitted(self, schema: str, name: str) -> bool:
        """Whether ``schema.name`` is inside the configured scope."""
        if schema not in self.config.schemas:
            return False
        qualified = f"{schema}.{name}"
        return any(fnmatch.fnmatchcase(qualified, p) for p in self.config.table_patterns)

    def _split(self, table: str, schema: str | None) -> tuple[str, str]:
        if not isinstance(table, str) or not table.strip():
            raise DataSourceError("a table name is required")
        table = table.strip()
        if len(table) > MAX_IDENTIFIER_LENGTH or (
            schema is not None and len(schema) > MAX_IDENTIFIER_LENGTH
        ):
            raise DataSourceError("table name is too long")
        if schema is None and "." in table:
            schema, table = table.split(".", 1)
        return (schema or self.config.schemas[0]), table

    # -- discovery -------------------------------------------------------------------
    async def resolve(self, table: str, schema: str | None = None) -> TableRef:
        """Find a permitted table/view by name.

        Raises:
            TableNotPermitted: Outside the configured scope (existence is not revealed).
            TableNotFound: In scope but absent.
        """
        await self.verify()
        schema_name, name = self._split(table, schema)
        if not self.is_permitted(schema_name, name):
            raise TableNotPermitted(
                f"'{schema_name}.{name}' is not available to agents (outside the configured scope)"
            )
        async with self.read() as conn:
            row = (
                (
                    await conn.execute(
                        text("""
                            SELECT c.oid::bigint AS oid, n.nspname AS schema, c.relname AS name,
                                   c.relkind::text AS kind, c.reltuples::bigint AS tuples
                              FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                             WHERE n.nspname = :schema AND c.relname = :name
                               AND c.relkind IN ('r', 'p', 'v', 'm')
                            """),
                        {"schema": schema_name, "name": name},
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise TableNotFound(f"table '{schema_name}.{name}' was not found")
        return TableRef(
            row["schema"], row["name"], KINDS[row["kind"]], row["oid"], _estimate(row["tuples"])
        )

    async def list_tables(self) -> tuple[list[TableRef], bool]:
        """Permitted tables and views (partitions excluded), capped at ``max_tables``.

        Returns:
            ``(tables, truncated)``
        """
        await self.verify()
        async with self.read() as conn:
            rows = (
                (
                    await conn.execute(
                        text("""
                            SELECT c.oid::bigint AS oid, n.nspname AS schema, c.relname AS name,
                                   c.relkind::text AS kind, c.reltuples::bigint AS tuples
                              FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                             WHERE n.nspname = ANY(CAST(:schemas AS text[]))
                               AND c.relkind IN ('r', 'p', 'v', 'm')
                               AND NOT c.relispartition
                             ORDER BY n.nspname, c.relname
                             LIMIT 10000
                            """),
                        {"schemas": list(self.config.schemas)},
                    )
                )
                .mappings()
                .all()
            )
        refs = [
            TableRef(r["schema"], r["name"], KINDS[r["kind"]], r["oid"], _estimate(r["tuples"]))
            for r in rows
            if self.is_permitted(r["schema"], r["name"])
        ]
        limit = self.config.max_tables
        return refs[:limit], len(refs) > limit

    # -- metadata ----------------------------------------------------------------------
    async def describe(self, ref: TableRef) -> dict[str, Any]:
        """Columns, keys, indexes, constraints and relationships of ``ref`` (metadata only)."""
        async with self.read() as conn:
            params = {"oid": ref.oid}
            comment = (
                await conn.execute(
                    text("SELECT obj_description(CAST(:oid AS oid), 'pg_class')"), params
                )
            ).scalar()
            columns = [
                dict(r)
                for r in (
                    await conn.execute(
                        text("""
                            SELECT a.attnum AS position, a.attname AS name,
                                   format_type(a.atttypid, a.atttypmod) AS type,
                                   t.typcategory::text AS category,
                                   a.attnotnull AS not_null,
                                   pg_get_expr(d.adbin, d.adrelid) AS default_expr,
                                   a.attidentity::text AS identity,
                                   a.attgenerated::text AS generated,
                                   col_description(a.attrelid, a.attnum) AS comment
                              FROM pg_attribute a
                              JOIN pg_type t ON t.oid = a.atttypid
                              LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
                             WHERE a.attrelid = CAST(:oid AS oid) AND a.attnum > 0 AND NOT a.attisdropped
                             ORDER BY a.attnum
                            """),
                        params,
                    )
                )
                .mappings()
                .all()
            ]
            constraints = (
                (
                    await conn.execute(
                        text("""
                            SELECT con.conname AS name, con.contype::text AS kind,
                                   con.convalidated AS validated,
                                   con.confupdtype::text AS on_update, con.confdeltype::text AS on_delete,
                                   con.conrelid = CAST(:oid AS oid) AS outgoing,
                                   ARRAY(SELECT a.attname::text
                                           FROM unnest(con.conkey) WITH ORDINALITY k(num, ord)
                                           JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.num
                                          ORDER BY k.ord) AS columns,
                                   cn.nspname AS local_schema, cc.relname AS local_table,
                                   rn.nspname AS ref_schema, rc.relname AS ref_table,
                                   ARRAY(SELECT a.attname::text
                                           FROM unnest(con.confkey) WITH ORDINALITY k(num, ord)
                                           JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.num
                                          ORDER BY k.ord) AS ref_columns,
                                   CASE WHEN con.contype = 'c' THEN pg_get_constraintdef(con.oid) END AS definition
                              FROM pg_constraint con
                              JOIN pg_class cc ON cc.oid = con.conrelid
                              JOIN pg_namespace cn ON cn.oid = cc.relnamespace
                              LEFT JOIN pg_class rc ON rc.oid = con.confrelid
                              LEFT JOIN pg_namespace rn ON rn.oid = rc.relnamespace
                             WHERE (con.conrelid = CAST(:oid AS oid) AND con.contype IN ('p', 'u', 'f', 'c'))
                                OR (con.confrelid = CAST(:oid AS oid) AND con.contype = 'f')
                             ORDER BY con.conname
                            """),
                        params,
                    )
                )
                .mappings()
                .all()
            )
            indexes = [
                dict(r)
                for r in (
                    await conn.execute(
                        text("""
                            SELECT ic.relname AS name, i.indisunique AS "unique",
                                   i.indisprimary AS "primary", pg_get_indexdef(i.indexrelid) AS definition
                              FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid
                             WHERE i.indrelid = CAST(:oid AS oid)
                             ORDER BY ic.relname
                            """),
                        params,
                    )
                )
                .mappings()
                .all()
            ]
            size = None
            if ref.kind in {"table", "partitioned_table", "materialized_view"}:
                size = (
                    await conn.execute(
                        text("SELECT pg_total_relation_size(CAST(:oid AS oid))"), params
                    )
                ).scalar()

        primary_key: list[str] = []
        unique: list[dict[str, Any]] = []
        checks: list[dict[str, Any]] = []
        foreign_keys: list[dict[str, Any]] = []
        referenced_by: list[dict[str, Any]] = []
        for c in constraints:
            if c["outgoing"] and c["kind"] == "p":
                primary_key = list(c["columns"])
            elif c["outgoing"] and c["kind"] == "u":
                unique.append({"name": c["name"], "columns": list(c["columns"])})
            elif c["outgoing"] and c["kind"] == "c":
                checks.append({"name": c["name"], "definition": c["definition"]})
            elif c["outgoing"] and c["kind"] == "f":
                foreign_keys.append(
                    {
                        "name": c["name"],
                        "columns": list(c["columns"]),
                        "references": {
                            "schema": c["ref_schema"],
                            "table": c["ref_table"],
                            "columns": list(c["ref_columns"]),
                            "in_scope": self.is_permitted(c["ref_schema"], c["ref_table"]),
                        },
                        "on_update": _ACTIONS.get(c["on_update"], c["on_update"]),
                        "on_delete": _ACTIONS.get(c["on_delete"], c["on_delete"]),
                        "validated": c["validated"],
                    }
                )
            elif not c["outgoing"] and c["kind"] == "f":
                # Only tables inside the configured scope are reported as referencing this one.
                if self.is_permitted(c["local_schema"], c["local_table"]):
                    referenced_by.append(
                        {
                            "name": c["name"],
                            "schema": c["local_schema"],
                            "table": c["local_table"],
                            "columns": list(c["columns"]),
                            "references_columns": list(c["ref_columns"]),
                        }
                    )

        return {
            "comment": comment,
            "columns": columns,
            "primary_key": primary_key,
            "unique_constraints": unique,
            "check_constraints": checks,
            "indexes": indexes,
            "foreign_keys": foreign_keys,
            "referenced_by": referenced_by,
            "size_bytes": size,
        }

    # -- bounded data access --------------------------------------------------------------
    async def sample_text(
        self, ref: TableRef, columns: Sequence[str], limit: int
    ) -> dict[str, list[str | None]]:
        """Up to ``limit`` rows of ``columns`` as (truncated) text, per column.

        ``columns`` must come from ``describe()``; values are meant to be analysed in
        memory and discarded, never stored or returned.
        """
        if not columns:
            return {}
        limit = max(1, min(limit, self.config.sample_rows))
        select_list = ", ".join(f"left({self.quote(c)}::text, 256)" for c in columns)
        sql = f"SELECT {select_list} FROM {self.qualified(ref)} LIMIT :n"
        async with self.read(scan=True) as conn:
            rows = (await conn.execute(text(sql), {"n": limit})).all()
        return {column: [row[i] for row in rows] for i, column in enumerate(columns)}


_ACTIONS = {
    "a": "no action",
    "r": "restrict",
    "c": "cascade",
    "n": "set null",
    "d": "set default",
}


def _estimate(tuples: int | None) -> int | None:
    """``reltuples`` is -1 for tables PostgreSQL has never analysed."""
    return None if tuples is None or tuples < 0 else int(tuples)
