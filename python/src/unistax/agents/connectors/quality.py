"""Bounded, read-only data quality checks for one table.

Every check scans at most ``scan_rows`` rows (a ``LIMIT`` inside the query), runs in
its own read-only transaction, and reports problems as *findings* rather than failing
the task. A check that times out or is denied is reported as ``errored`` and the
remaining checks still run.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from unistax.agents.connectors.errors import (
    DataSourceError,
    DataSourceUnavailable,
    DataSourceUnsafe,
)
from unistax.agents.connectors.postgres import PostgresDataSource, TableRef

CHECKS = ("row_count", "nulls", "foreign_keys", "duplicates", "freshness")
DEFAULT_CHECKS = ("row_count", "nulls", "foreign_keys")
MAX_COLUMNS = 200
MAX_LIST = 50


@dataclass(frozen=True)
class QualityOptions:
    """Validated settings for one run."""

    checks: tuple[str, ...]
    scan_rows: int
    max_null_rate: float | None = None
    unique_columns: tuple[str, ...] = ()
    timestamp_column: str | None = None
    max_age_hours: float | None = None

    @classmethod
    def from_context(cls, context: dict[str, Any], scan_cap: int) -> QualityOptions:
        """Parse and validate a task context.

        Raises:
            ValueError: Anything malformed. Messages are safe to return to callers.
        """
        requested = context.get("checks") or list(DEFAULT_CHECKS)
        if not isinstance(requested, list) or not all(isinstance(c, str) for c in requested):
            raise ValueError("checks must be a list of check names")
        unknown = sorted(set(requested) - set(CHECKS))
        if unknown:
            raise ValueError(f"unknown checks {unknown}; available: {list(CHECKS)}")
        checks = tuple(dict.fromkeys(requested))

        scan_rows = context.get("max_scan_rows", scan_cap)
        if not isinstance(scan_rows, int) or isinstance(scan_rows, bool) or scan_rows < 1:
            raise ValueError("max_scan_rows must be a positive integer")

        max_null_rate = context.get("max_null_rate")
        if max_null_rate is not None and (
            isinstance(max_null_rate, bool)
            or not isinstance(max_null_rate, (int, float))
            or not 0 <= max_null_rate <= 1
        ):
            raise ValueError("max_null_rate must be a number between 0 and 1")

        unique_columns = context.get("unique_columns") or []
        if not isinstance(unique_columns, list) or not all(
            isinstance(c, str) for c in unique_columns
        ):
            raise ValueError("unique_columns must be a list of column names")
        if len(unique_columns) > MAX_LIST:
            raise ValueError(f"at most {MAX_LIST} unique_columns are allowed")
        if "duplicates" in checks and not unique_columns:
            raise ValueError("the duplicates check needs unique_columns")

        timestamp_column = context.get("timestamp_column")
        max_age_hours = context.get("max_age_hours")
        if "freshness" in checks:
            if not isinstance(timestamp_column, str) or not timestamp_column:
                raise ValueError("the freshness check needs timestamp_column")
            if (
                isinstance(max_age_hours, bool)
                or not isinstance(max_age_hours, (int, float))
                or max_age_hours <= 0
            ):
                raise ValueError("the freshness check needs a positive max_age_hours")

        return cls(
            checks=checks,
            scan_rows=min(scan_rows, scan_cap),
            max_null_rate=None if max_null_rate is None else float(max_null_rate),
            unique_columns=tuple(unique_columns),
            timestamp_column=timestamp_column,
            max_age_hours=None if max_age_hours is None else float(max_age_hours),
        )


def issue(
    check: str, severity: str, message: str, column: str | None = None, **extra: Any
) -> dict[str, Any]:
    """A finding. ``severity`` is ``error`` (breaks an expectation) or ``warning``."""
    return {"check": check, "severity": severity, "column": column, "message": message, **extra}


async def run_quality_checks(
    ds: PostgresDataSource, ref: TableRef, meta: dict[str, Any], options: QualityOptions
) -> dict[str, Any]:
    """Run the requested checks and summarise.

    Returns:
        ``checks`` (name -> ``passed`` | ``failed`` | ``errored``), ``issues``,
        ``details`` (per check) and ``possibly_partial`` (a scan hit its row limit).
    """
    columns = {c["name"]: c for c in meta["columns"]}
    for name in (
        *options.unique_columns,
        *([options.timestamp_column] if options.timestamp_column else []),
    ):
        if name not in columns:
            raise ValueError(f"column '{name}' does not exist in {ref.qualified_name}")
    if options.timestamp_column:
        column_type = columns[options.timestamp_column]["type"]
        if not (column_type.startswith("timestamp") or column_type == "date"):
            raise ValueError(
                f"column '{options.timestamp_column}' is {column_type}, not a date/time type"
            )

    runners: dict[str, Callable[[], Awaitable[tuple[dict[str, Any], list[dict[str, Any]]]]]] = {
        "row_count": lambda: _row_count(ds, ref, options),
        "nulls": lambda: _nulls(ds, ref, meta, options),
        "foreign_keys": lambda: _foreign_keys(ds, ref, meta, options),
        "duplicates": lambda: _duplicates(ds, ref, options),
        "freshness": lambda: _freshness(ds, ref, options),
    }

    outcomes: dict[str, str] = {}
    details: dict[str, Any] = {}
    issues: list[dict[str, Any]] = []
    partial = False
    for name in options.checks:
        try:
            detail, found = await runners[name]()
        except (DataSourceUnavailable, DataSourceUnsafe):
            raise
        except DataSourceError as exc:
            outcomes[name] = "errored"
            details[name] = {"error": str(exc)}
            continue
        details[name] = detail
        issues.extend(found)
        partial = partial or bool(detail.pop("_partial", False))
        if any(i["severity"] == "error" for i in found) or detail.get("errored_items"):
            outcomes[name] = "failed" if any(i["severity"] == "error" for i in found) else "errored"
        else:
            outcomes[name] = "passed"
    return {"checks": outcomes, "issues": issues, "details": details, "possibly_partial": partial}


# --------------------------------------------------------------------------
# Individual checks. Each returns (details, issues).
# --------------------------------------------------------------------------
async def _row_count(
    ds: PostgresDataSource, ref: TableRef, options: QualityOptions
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sql = f"SELECT count(*) FROM (SELECT 1 FROM {ds.qualified(ref)} LIMIT :cap) s"
    async with ds.read(scan=True) as conn:
        counted = (await conn.execute(text(sql), {"cap": options.scan_rows + 1})).scalar() or 0
    capped = counted > options.scan_rows
    detail = {
        "rows_counted": min(counted, options.scan_rows),
        "at_least": capped,
        "estimate": ref.row_estimate,
    }
    found = []
    if counted == 0:
        found.append(issue("row_count", "warning", f"{ref.qualified_name} has no rows"))
    return detail, found


async def _nulls(
    ds: PostgresDataSource, ref: TableRef, meta: dict[str, Any], options: QualityOptions
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    # NOT NULL columns cannot contain nulls, so they are not scanned.
    candidates = [c["name"] for c in meta["columns"] if not c["not_null"]][:MAX_COLUMNS]
    if not candidates:
        return {
            "null_rates": {},
            "rows_scanned": 0,
            "columns_skipped_not_null": len(meta["columns"]),
        }, []

    inner = ", ".join(ds.quote(c) for c in candidates)
    counters = ", ".join(
        f"count(*) FILTER (WHERE {ds.quote(c)} IS NULL) AS n{i}" for i, c in enumerate(candidates)
    )
    sql = (
        f"SELECT count(*) AS total, {counters} "
        f"FROM (SELECT {inner} FROM {ds.qualified(ref)} LIMIT :cap) s"
    )
    async with ds.read(scan=True) as conn:
        row = (await conn.execute(text(sql), {"cap": options.scan_rows})).mappings().one()

    total = row["total"]
    rates = {c: (row[f"n{i}"] / total if total else 0.0) for i, c in enumerate(candidates)}
    found: list[dict[str, Any]] = []
    for column, rate in rates.items():
        if not total:
            break
        if options.max_null_rate is not None and rate > options.max_null_rate:
            found.append(
                issue(
                    "nulls",
                    "error",
                    f"{column} is {rate:.1%} NULL (limit {options.max_null_rate:.1%})",
                    column,
                    value=round(rate, 4),
                )
            )
        elif rate == 1.0:
            found.append(
                issue(
                    "nulls", "warning", f"{column} is NULL in every scanned row", column, value=1.0
                )
            )
    detail = {
        "null_rates": {c: round(r, 4) for c, r in rates.items()},
        "rows_scanned": total,
        "_partial": total >= options.scan_rows,
    }
    return detail, found


async def _foreign_keys(
    ds: PostgresDataSource, ref: TableRef, meta: dict[str, Any], options: QualityOptions
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    results: dict[str, Any] = {}
    found: list[dict[str, Any]] = []
    errored = 0
    partial = False
    for fk in meta["foreign_keys"]:
        target = fk["references"]
        if not target["in_scope"]:
            results[fk["name"]] = {
                "status": "skipped",
                "reason": "referenced table is outside the configured scope",
            }
            continue
        try:
            parent = await ds.resolve(target["table"], schema=target["schema"])
            child_cols, parent_cols = fk["columns"], target["columns"]
            not_null = " AND ".join(f"{ds.quote(c)} IS NOT NULL" for c in child_cols)
            join = " AND ".join(
                f"p.{ds.quote(pc)} = c.{ds.quote(cc)}"
                for cc, pc in zip(child_cols, parent_cols, strict=True)
            )
            sql = (
                f"WITH c AS (SELECT {', '.join(ds.quote(x) for x in child_cols)} "
                f"FROM {ds.qualified(ref)} WHERE {not_null} LIMIT :cap) "
                f"SELECT (SELECT count(*) FROM c) AS checked, "
                f"(SELECT count(*) FROM c WHERE NOT EXISTS "
                f"(SELECT 1 FROM {ds.qualified(parent)} p WHERE {join})) AS orphans"
            )
            async with ds.read(scan=True) as conn:
                row = (await conn.execute(text(sql), {"cap": options.scan_rows})).mappings().one()
        except (DataSourceUnavailable, DataSourceUnsafe):
            raise
        except DataSourceError as exc:
            results[fk["name"]] = {"status": "error", "error": str(exc)}
            errored += 1
            continue

        partial = partial or row["checked"] >= options.scan_rows
        entry = {
            "status": "ok" if not row["orphans"] else "orphans_found",
            "rows_checked": row["checked"],
            "orphans": row["orphans"],
            "references": f"{target['schema']}.{target['table']}",
            "constraint_validated": fk["validated"],
        }
        results[fk["name"]] = entry
        if row["orphans"]:
            found.append(
                issue(
                    "foreign_keys",
                    "error",
                    f"{row['orphans']} of {row['checked']} checked rows in {fk['columns']} "
                    f"have no matching row in {target['schema']}.{target['table']}",
                    ",".join(fk["columns"]),
                    constraint=fk["name"],
                    value=row["orphans"],
                )
            )
    return {"constraints": results, "errored_items": errored, "_partial": partial}, found


async def _duplicates(
    ds: PostgresDataSource, ref: TableRef, options: QualityOptions
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cols = ", ".join(ds.quote(c) for c in options.unique_columns)
    not_null = " AND ".join(f"{ds.quote(c)} IS NOT NULL" for c in options.unique_columns)
    sql = (
        f"WITH s AS (SELECT {cols} FROM {ds.qualified(ref)} WHERE {not_null} LIMIT :cap) "
        f"SELECT (SELECT count(*) FROM s) AS checked, "
        f"(SELECT count(*) FROM (SELECT DISTINCT {cols} FROM s) d) AS distinct_keys, "
        f"(SELECT count(*) FROM (SELECT 1 FROM s GROUP BY {cols} HAVING count(*) > 1) g) "
        f"AS duplicated_keys"
    )
    async with ds.read(scan=True) as conn:
        row = (await conn.execute(text(sql), {"cap": options.scan_rows})).mappings().one()

    surplus = row["checked"] - row["distinct_keys"]
    detail = {
        "columns": list(options.unique_columns),
        "rows_checked": row["checked"],
        "duplicate_rows": surplus,
        "duplicated_keys": row["duplicated_keys"],
        "note": "rows with a NULL in any key column are ignored",
        "_partial": row["checked"] >= options.scan_rows,
    }
    found = []
    if surplus:
        found.append(
            issue(
                "duplicates",
                "error",
                f"{row['duplicated_keys']} key value(s) in {list(options.unique_columns)} "
                f"occur more than once ({surplus} surplus rows among {row['checked']} checked)",
                ",".join(options.unique_columns),
                value=surplus,
            )
        )
    return detail, found


async def _freshness(
    ds: PostgresDataSource, ref: TableRef, options: QualityOptions
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    column = ds.quote(options.timestamp_column or "")
    sql = (
        f"SELECT {column}::timestamptz AS latest, now() AS db_now FROM {ds.qualified(ref)} "
        f"WHERE {column} IS NOT NULL ORDER BY {column} DESC LIMIT 1"
    )
    async with ds.read(scan=True) as conn:
        row = (await conn.execute(text(sql))).mappings().first()

    if row is None:
        return (
            {"column": options.timestamp_column, "latest": None},
            [
                issue(
                    "freshness",
                    "error",
                    f"{options.timestamp_column} has no non-NULL values",
                    options.timestamp_column,
                )
            ],
        )
    age_hours = (row["db_now"] - row["latest"]).total_seconds() / 3600
    detail = {
        "column": options.timestamp_column,
        "latest": row["latest"].isoformat(),
        "age_hours": round(age_hours, 2),
        "max_age_hours": options.max_age_hours,
    }
    found = []
    if options.max_age_hours is not None and age_hours > options.max_age_hours:
        found.append(
            issue(
                "freshness",
                "error",
                f"latest {options.timestamp_column} is {age_hours:.1f}h old "
                f"(limit {options.max_age_hours:g}h)",
                options.timestamp_column,
                value=round(age_hours, 2),
            )
        )
    return detail, found
