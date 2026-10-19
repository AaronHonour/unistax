"""Knowledge graph API and its persistence."""

from __future__ import annotations

import pytest

from .conftest import API

pytestmark = pytest.mark.api


def node(client, headers, node_id, node_type="dataset", **props):
    r = client.post(
        f"{API}/knowledge/nodes",
        json={"node_id": node_id, "node_type": node_type, "properties": props},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


def edge(client, headers, source, target, relation):
    return client.post(
        f"{API}/knowledge/edges",
        json={"source_id": source, "target_id": target, "relation_type": relation},
        headers=headers,
    )


def test_nodes_are_upserted_and_typed(client, operator, viewer):
    node(client, operator, "customers", rows=10)
    updated = node(client, operator, "customers", quality=0.9)
    assert updated["properties"] == {"rows": 10, "quality": 0.9}

    conflict = client.post(
        f"{API}/knowledge/nodes",
        json={"node_id": "customers", "node_type": "model"},
        headers=operator,
    )
    assert conflict.status_code == 409
    assert (
        client.get(f"{API}/knowledge/nodes/customers", headers=viewer).json()["data"]["node_type"]
        == "dataset"
    )
    assert client.get(f"{API}/knowledge/nodes/ghost", headers=viewer).status_code == 404


def test_invalid_types_are_422(client, operator):
    assert (
        client.post(
            f"{API}/knowledge/nodes",
            json={"node_id": "x", "node_type": "spaceship"},
            headers=operator,
        ).status_code
        == 422
    )
    node(client, operator, "a")
    node(client, operator, "b")
    assert edge(client, operator, "a", "b", "teleports_to").status_code == 422


def test_edges_require_existing_nodes(client, operator):
    node(client, operator, "a")
    assert edge(client, operator, "a", "ghost", "depends_on").status_code == 422
    assert edge(client, operator, "ghost", "a", "depends_on").status_code == 422


def test_lineage_queries(client, operator, viewer):
    for name in ("raw", "clean", "report"):
        node(client, operator, name)
    node(client, operator, "etl", "pipeline")
    assert edge(client, operator, "report", "clean", "depends_on").status_code == 201
    assert edge(client, operator, "clean", "raw", "depends_on").status_code == 201
    assert edge(client, operator, "etl", "raw", "consumes").status_code == 201
    assert edge(client, operator, "etl", "clean", "produces").status_code == 201

    deps = client.get(f"{API}/knowledge/nodes/report/dependencies", headers=viewer).json()["data"]
    assert deps == ["clean", "raw"]
    shallow = client.get(
        f"{API}/knowledge/nodes/report/dependencies?max_depth=1", headers=viewer
    ).json()["data"]
    assert "clean" in shallow
    assert client.get(f"{API}/knowledge/nodes/raw/consumers", headers=viewer).json()["data"] == [
        "etl"
    ]
    assert client.get(f"{API}/knowledge/nodes/clean/producers", headers=viewer).json()["data"] == [
        "etl"
    ]
    assert len(client.get(f"{API}/knowledge/nodes/clean/edges", headers=viewer).json()["data"]) == 3


def test_dependency_cycles_do_not_hang(client, operator, viewer):
    node(client, operator, "a")
    node(client, operator, "b")
    edge(client, operator, "a", "b", "depends_on")
    edge(client, operator, "b", "a", "depends_on")
    r = client.get(f"{API}/knowledge/nodes/a/dependencies?max_depth=10", headers=viewer)
    assert r.status_code == 200 and set(r.json()["data"]) == {"a", "b"}


def test_best_practices_and_issues(client, operator, viewer):
    node(client, operator, "customers")
    bp = client.post(
        f"{API}/knowledge/best-practices",
        json={
            "practice_id": "bp1",
            "topic": "quality",
            "description": "Validate keys",
            "related_nodes": ["customers"],
        },
        headers=operator,
    )
    assert bp.status_code == 201 and bp.json()["data"]["created_by"] == "operator-user"
    assert [
        p["node_id"]
        for p in client.get(f"{API}/knowledge/best-practices?topic=quality", headers=viewer).json()[
            "data"
        ]
    ] == ["bp1"]
    assert (
        client.get(f"{API}/knowledge/best-practices?topic=other", headers=viewer).json()["data"]
        == []
    )

    bad = client.post(
        f"{API}/knowledge/best-practices",
        json={"practice_id": "bp2", "topic": "t", "description": "d", "related_nodes": ["ghost"]},
        headers=operator,
    )
    assert bad.status_code == 422

    issue = client.post(
        f"{API}/knowledge/issues",
        json={
            "issue_id": "i1",
            "description": "Nulls",
            "severity": "high",
            "affected_nodes": ["customers"],
        },
        headers=operator,
    )
    assert issue.status_code == 201 and issue.json()["data"]["properties"]["status"] == "open"
    assert (
        client.post(
            f"{API}/knowledge/issues",
            json={"issue_id": "i2", "description": "x", "severity": "apocalyptic"},
            headers=operator,
        ).status_code
        == 422
    )

    stats = client.get(f"{API}/knowledge/statistics", headers=viewer).json()["data"]
    assert stats["total_nodes"] == 3 and stats["total_edges"] == 2


def test_listing_by_type_is_paginated(client, operator, viewer):
    for i in range(5):
        node(client, operator, f"ds{i}")
    node(client, operator, "p", "pipeline")
    page = client.get(f"{API}/knowledge/nodes?node_type=dataset&page_size=2", headers=viewer).json()
    assert page["total"] == 5 and len(page["data"]) == 2 and page["has_next"]


def test_graph_survives_restart(make_client, operator, viewer):
    first = make_client()
    node(first, operator, "raw", rows=5)
    node(first, operator, "clean")
    edge(first, operator, "clean", "raw", "depends_on")
    first.post(
        f"{API}/knowledge/best-practices",
        json={"practice_id": "bp1", "topic": "q", "description": "d", "related_nodes": ["raw"]},
        headers=operator,
    )
    first.__exit__(None, None, None)

    second = make_client()
    assert second.get(f"{API}/knowledge/nodes/raw", headers=viewer).json()["data"][
        "properties"
    ] == {"rows": 5}
    assert second.get(f"{API}/knowledge/nodes/clean/dependencies", headers=viewer).json()[
        "data"
    ] == ["raw"]
    assert (
        second.get(f"{API}/knowledge/statistics", headers=viewer).json()["data"]["total_edges"] == 2
    )
