"""Task logic for agents backed by a PostgreSQL data source.

Each function validates its input, does read-only work through the data source, and
returns a :class:`TaskOutcome`: the task result plus the knowledge-graph updates it
implies. Nothing here writes to the database being inspected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from unistax.agents.connectors import classification
from unistax.agents.connectors.errors import (
    DataSourceError,
    DataSourceUnavailable,
    DataSourceUnsafe,
)
from unistax.agents.connectors.knowledge import (
    EdgeSpec,
    NodeSpec,
    dataset_node_id,
    dataset_specs,
    issue_node_id,
    now_iso,
)
from unistax.agents.connectors.postgres import PostgresDataSource, TableRef
from unistax.agents.connectors.quality import QualityOptions, run_quality_checks

if TYPE_CHECKING:
    from unistax.agents.intelligence.knowledge_graph import AgentKnowledgeGraph

MAX_CLASSIFY_COLUMNS = 100
SAMPLEABLE_CATEGORIES = {"S", "I"}  # string and network-address types
_SEVERITY = {"error": "high", "warning": "low"}


@dataclass
class TaskOutcome:
    """A task result and the knowledge it produced."""

    result: dict[str, Any]
    nodes: list[NodeSpec] = field(default_factory=list)
    edges: list[EdgeSpec] = field(default_factory=list)


def table_argument(context: dict[str, Any], *keys: str) -> str | None:
    """First non-empty table name among ``keys`` in ``context``.

    Raises:
        ValueError: The value is present but not a string.
    """
    for key in keys:
        value = context.get(key)
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        return value
    return None


def _schema_argument(context: dict[str, Any]) -> str | None:
    schema = context.get("schema")
    if schema is not None and not isinstance(schema, str):
        raise ValueError("schema must be a string")
    return schema or None


async def _resolve_and_describe(
    ds: PostgresDataSource, context: dict[str, Any], *keys: str
) -> tuple[TableRef, dict[str, Any]]:
    table = table_argument(context, *keys)
    if table is None:
        raise ValueError(f"{keys[0]} is required")
    ref = await ds.resolve(table, schema=_schema_argument(context))
    return ref, await ds.describe(ref)


# --------------------------------------------------------------------------
# Steward tasks
# --------------------------------------------------------------------------
def _catalog_entry(ds: PostgresDataSource, ref: TableRef, meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "dataset_name": ref.qualified_name,
        "kind": ref.kind,
        "columns": len(meta["columns"]),
        "rows_estimate": ref.row_estimate,
        "size_bytes": meta["size_bytes"],
        "primary_key": meta["primary_key"],
        "foreign_keys": len(meta["foreign_keys"]),
        "referenced_by": len(meta["referenced_by"]),
        "comment": meta["comment"],
        "knowledge_node": dataset_node_id(ds.name, ref.schema, ref.name),
    }


async def catalog_dataset(ds: PostgresDataSource, context: dict[str, Any]) -> TaskOutcome:
    """Catalog one table, or every in-scope table when no name is given."""
    name = table_argument(context, "name", "table", "dataset")
    if name is None:
        return await _catalog_everything(ds)

    ref, meta = await _resolve_and_describe(ds, context, "name", "table", "dataset")
    nodes, edges = dataset_specs(ds.name, ref.schema, ref.name, ref.kind, meta, ref.row_estimate)
    entry = _catalog_entry(ds, ref, meta)
    return TaskOutcome(
        {
            "status": "success",
            "data_source": ds.label,
            "dataset_name": ref.qualified_name,
            "kind": ref.kind,
            "schema": {
                "columns": entry["columns"],
                "column_names": [c["name"] for c in meta["columns"]],
                "rows_estimate": ref.row_estimate,
                "rows_estimate_source": "pg_class.reltuples (planner statistics, not exact)",
                "size_bytes": meta["size_bytes"],
                "primary_key": meta["primary_key"],
            },
            "metadata": {
                "comment": meta["comment"],
                "foreign_keys": [
                    f"{fk['columns']} -> {fk['references']['schema']}.{fk['references']['table']}"
                    for fk in meta["foreign_keys"]
                ],
                "referenced_by": [f"{r['schema']}.{r['table']}" for r in meta["referenced_by"]],
                "indexes": len(meta["indexes"]),
            },
            "tags": [
                ref.kind,
                *(["has_primary_key"] if meta["primary_key"] else ["no_primary_key"]),
            ],
            "knowledge_node": entry["knowledge_node"],
        },
        nodes,
        edges,
    )


async def _catalog_everything(ds: PostgresDataSource) -> TaskOutcome:
    refs, truncated = await ds.list_tables()
    entries: list[dict[str, Any]] = []
    nodes: list[NodeSpec] = []
    edges: list[EdgeSpec] = []
    for ref in refs:
        meta = await ds.describe(ref)
        entries.append(_catalog_entry(ds, ref, meta))
        n, e = dataset_specs(ds.name, ref.schema, ref.name, ref.kind, meta, ref.row_estimate)
        nodes.extend(n)
        edges.extend(e)
    return TaskOutcome(
        {
            "status": "success",
            "data_source": ds.label,
            "table_count": len(entries),
            "truncated": truncated,
            "tables": entries,
        },
        nodes,
        edges,
    )


async def document_schema(ds: PostgresDataSource, context: dict[str, Any]) -> TaskOutcome:
    """Describe every column, key, index and relationship of a table."""
    ref, meta = await _resolve_and_describe(ds, context, "table", "name", "dataset")
    primary = set(meta["primary_key"])
    foreign = {c for fk in meta["foreign_keys"] for c in fk["columns"]}
    unique = {c for u in meta["unique_constraints"] for c in u["columns"]}

    documentation: dict[str, Any] = {}
    for column in meta["columns"]:
        tags = []
        if column["name"] in primary:
            tags.append("primary_key")
        if column["name"] in foreign:
            tags.append("foreign_key")
        if column["name"] in unique:
            tags.append("unique")
        hint = classification.classify_by_name(column["name"])
        if hint:
            tags.append(f"possible_{hint.label}")
        documentation[column["name"]] = {
            "type": column["type"],
            "nullable": not column["not_null"],
            "default": (column["default_expr"] or None) and column["default_expr"][:200],
            "identity": {"a": "always", "d": "by default"}.get(column["identity"]),
            "generated": bool(column["generated"]),
            "description": column["comment"],
            "tags": tags,
        }

    relationships = [
        {
            "type": "many_to_one",
            "table": f"{fk['references']['schema']}.{fk['references']['table']}",
            "key": fk["columns"],
            "references": fk["references"]["columns"],
            "on_delete": fk["on_delete"],
            "in_scope": fk["references"]["in_scope"],
        }
        for fk in meta["foreign_keys"]
    ] + [
        {
            "type": "one_to_many",
            "table": f"{r['schema']}.{r['table']}",
            "key": r["references_columns"],
            "references": r["columns"],
            "in_scope": True,
        }
        for r in meta["referenced_by"]
    ]

    nodes, edges = dataset_specs(ds.name, ref.schema, ref.name, ref.kind, meta, ref.row_estimate)
    return TaskOutcome(
        {
            "status": "success",
            "data_source": ds.label,
            "table": ref.qualified_name,
            "kind": ref.kind,
            "table_comment": meta["comment"],
            "columns_documented": len(documentation),
            "documentation": documentation,
            "primary_key": meta["primary_key"],
            "unique_constraints": meta["unique_constraints"],
            "check_constraints": meta["check_constraints"],
            "indexes": [
                {"name": i["name"], "unique": i["unique"], "definition": i["definition"]}
                for i in meta["indexes"]
            ],
            "relationships": relationships,
            "knowledge_node": dataset_node_id(ds.name, ref.schema, ref.name),
        },
        nodes,
        edges,
    )


async def classify_data(ds: PostgresDataSource, context: dict[str, Any]) -> TaskOutcome:
    """Label columns that look sensitive, from names and a bounded sample of values.

    Sampled values are analysed in memory and discarded; results hold labels and rates only.
    """
    ref, meta = await _resolve_and_describe(ds, context, "dataset", "table", "name")

    sample_rows = context.get("sample_rows", ds.config.sample_rows)
    if not isinstance(sample_rows, int) or isinstance(sample_rows, bool) or sample_rows < 1:
        raise ValueError("sample_rows must be a positive integer")
    sample_rows = min(sample_rows, ds.config.sample_rows)

    candidates = [c["name"] for c in meta["columns"] if c["category"] in SAMPLEABLE_CATEGORIES]
    candidates = candidates[:MAX_CLASSIFY_COLUMNS]
    samples: dict[str, list[str | None]] = {}
    sampling_note: str | None = None
    try:
        samples = await ds.sample_text(ref, candidates, sample_rows)
    except (DataSourceUnavailable, DataSourceUnsafe):
        raise
    except DataSourceError as exc:
        # e.g. the role may read metadata but not the data: still classify by name.
        sampling_note = f"values were not sampled: {exc}"

    found: dict[str, classification.ColumnClassification] = {}
    for column in meta["columns"]:
        result = classification.classify_column(column["name"], samples.get(column["name"]))
        if result:
            found[column["name"]] = result

    summary = classification.summarise(found)
    controls = summary.pop("required_controls")
    node_id = dataset_node_id(ds.name, ref.schema, ref.name)
    sensitive = sorted(found)
    node = NodeSpec(
        node_id,
        "dataset",
        {
            "source": "postgres",
            "data_source": ds.name,
            "schema": ref.schema,
            "table": ref.name,
            "sensitivity_level": summary["sensitivity_level"],
            "contains_pii": summary["contains_pii"],
            "sensitive_columns": sensitive,
            "classified_at": now_iso(),
        },
    )
    return TaskOutcome(
        {
            "status": "success",
            "data_source": ds.label,
            "dataset": ref.qualified_name,
            "classification": summary,
            "column_classifications": {name: c.as_dict() for name, c in found.items()},
            "unclassified_columns": [c["name"] for c in meta["columns"] if c["name"] not in found],
            "required_controls": controls,
            "sampled_columns": 0 if sampling_note else len(candidates),
            "sample_rows": max((len(v) for v in samples.values()), default=0),
            "sampling_note": sampling_note,
            "method": "rules over column names and sampled values; a starting point for review",
            "knowledge_node": node_id,
        },
        [node],
        [],
    )


# --------------------------------------------------------------------------
# Engineer task
# --------------------------------------------------------------------------
async def quality_check(
    ds: PostgresDataSource, context: dict[str, Any], kg: AgentKnowledgeGraph | None = None
) -> TaskOutcome:
    """Run bounded quality checks and record findings as issues in the knowledge graph."""
    options = QualityOptions.from_context(context, ds.config.max_scan_rows)
    ref, meta = await _resolve_and_describe(ds, context, "table", "name", "dataset")
    report = await run_quality_checks(ds, ref, meta, options)

    outcomes = report["checks"]
    failed = [name for name, o in outcomes.items() if o == "failed"]
    errored = [name for name, o in outcomes.items() if o == "errored"]
    issues = report["issues"]
    nodes, edges = _issue_specs(ds, ref, issues, outcomes, kg)

    return TaskOutcome(
        {
            "status": "success",
            "data_source": ds.label,
            "table": ref.qualified_name,
            "healthy": not failed and not errored,
            "checks": outcomes,
            "checks_passed": sum(1 for o in outcomes.values() if o == "passed"),
            "checks_failed": len(failed),
            "checks_errored": len(errored),
            "issues": issues,
            "details": report["details"],
            "scan_limit_rows": options.scan_rows,
            "possibly_partial": report["possibly_partial"],
            "knowledge_node": dataset_node_id(ds.name, ref.schema, ref.name),
        },
        nodes,
        edges,
    )


def _issue_specs(
    ds: PostgresDataSource,
    ref: TableRef,
    issues: list[dict[str, Any]],
    outcomes: dict[str, str],
    kg: AgentKnowledgeGraph | None,
) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    """Open issues for current findings; resolve earlier ones this run proved fixed."""
    dataset_id = dataset_node_id(ds.name, ref.schema, ref.name)
    stamp = now_iso()
    nodes = [
        NodeSpec(
            dataset_id,
            "dataset",
            {
                "source": "postgres",
                "data_source": ds.name,
                "schema": ref.schema,
                "table": ref.name,
                "last_quality_check": {
                    "at": stamp,
                    "healthy": all(o == "passed" for o in outcomes.values()),
                    "issues": len(issues),
                },
            },
        )
    ]
    edges: list[EdgeSpec] = []

    current: set[str] = set()
    for item in issues:
        node_id = issue_node_id(dataset_id, item["check"], item["column"])
        current.add(node_id)
        properties: dict[str, Any] = {
            "description": item["message"],
            "severity": _SEVERITY[item["severity"]],
            "status": "open",
            "check": item["check"],
            "column": item["column"],
            "dataset": dataset_id,
            "last_seen": stamp,
        }
        if kg is None or kg.get_node(node_id) is None:
            properties["first_seen"] = stamp
        nodes.append(NodeSpec(node_id, "issue", properties))
        edges.append(EdgeSpec(node_id, dataset_id, "related_to"))

    # Only checks that actually completed can prove an earlier issue is gone.
    completed = {name for name, outcome in outcomes.items() if outcome in {"passed", "failed"}}
    if kg is not None:
        for edge in kg.get_incoming_edges(dataset_id):
            node = kg.get_node(edge.source_id)
            if (
                node is not None
                and node.id.startswith("pgq:")
                and node.id not in current
                and node.properties.get("status") == "open"
                and node.properties.get("check") in completed
            ):
                nodes.append(
                    NodeSpec(node.id, "issue", {"status": "resolved", "resolved_at": stamp})
                )
    return nodes, edges
