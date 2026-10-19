"""Turning what an agent learned about a data source into knowledge-graph updates.

Pure helpers: they describe nodes and edges but never touch the graph or database.
Ids are deterministic so repeating a task updates the same nodes instead of piling
up duplicates.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

MAX_ID_LENGTH = 64
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]*$")


@dataclass(frozen=True)
class NodeSpec:
    """A knowledge-graph node to create or update."""

    id: str
    node_type: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EdgeSpec:
    """A knowledge-graph relationship to ensure exists."""

    source: str
    target: str
    relation: str
    properties: dict[str, Any] = field(default_factory=dict)


def now_iso() -> str:
    """Current UTC time, ISO-8601."""
    return datetime.now(timezone.utc).isoformat()


def dataset_node_id(source_name: str, schema: str, table: str) -> str:
    """Stable id for a table; hashed when the real name would not make a safe id."""
    raw = f"pg:{source_name}:{schema}.{table}"
    if len(raw) <= MAX_ID_LENGTH and _SAFE_ID.match(raw):
        return raw
    digest = hashlib.sha256(f"{schema}.{table}".encode()).hexdigest()[:16]
    return f"pg:{source_name}:{digest}"[:MAX_ID_LENGTH]


def issue_node_id(dataset_id: str, check: str, column: str | None) -> str:
    """Stable id for a quality finding about one check (and column) of a dataset."""
    digest = hashlib.sha256(f"{dataset_id}|{check}|{column or ''}".encode()).hexdigest()[:20]
    return f"pgq:{digest}"


def dataset_specs(
    source_name: str,
    schema: str,
    table: str,
    kind: str,
    meta: dict[str, Any],
    rows_estimate: int | None,
) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    """Node for a table plus ``depends_on`` edges to the in-scope tables it references."""
    node_id = dataset_node_id(source_name, schema, table)
    comment = meta.get("comment")
    nodes = [
        NodeSpec(
            node_id,
            "dataset",
            {
                "source": "postgres",
                "data_source": source_name,
                "schema": schema,
                "table": table,
                "kind": kind,
                "columns": len(meta["columns"]),
                "rows_estimate": rows_estimate,
                "size_bytes": meta.get("size_bytes"),
                "primary_key": meta.get("primary_key", []),
                "comment": comment[:500] if comment else None,
                "cataloged_at": now_iso(),
            },
        )
    ]
    edges: list[EdgeSpec] = []
    for fk in meta.get("foreign_keys", []):
        ref = fk["references"]
        if not ref["in_scope"]:
            continue
        parent_id = dataset_node_id(source_name, ref["schema"], ref["table"])
        if parent_id == node_id:
            continue
        nodes.append(
            NodeSpec(
                parent_id,
                "dataset",
                {
                    "source": "postgres",
                    "data_source": source_name,
                    "schema": ref["schema"],
                    "table": ref["table"],
                },
            )
        )
        edges.append(
            EdgeSpec(
                node_id, parent_id, "depends_on", {"via": fk["name"], "columns": fk["columns"]}
            )
        )
    return nodes, edges
