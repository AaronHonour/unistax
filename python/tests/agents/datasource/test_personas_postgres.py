"""Steward and Engineer personas working on a real PostgreSQL database."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from unistax.agents import DataEngineerAgent, DataStewardAgent, Task, TaskStatus
from unistax.agents.connectors.knowledge import dataset_node_id
from unistax.agents.connectors.postgres import PostgresConfig, PostgresDataSource
from unistax.agents.intelligence.knowledge_graph import (
    AgentKnowledgeGraph,
    NodeType,
    RelationType,
)

pytestmark = pytest.mark.agents

SAMPLE_VALUES = [
    "user1@example.com",
    "4111111111111111",
    "100-45-6001",
    "+44 20 7946 0001",
    "10.0.0.1",
]


@pytest.fixture
async def ds(warehouse):
    source = PostgresDataSource(
        PostgresConfig(url=warehouse.reader_url, name="wh", schemas=(warehouse.schema,))
    )
    yield source
    await source.close()


@pytest.fixture
def kg() -> AgentKnowledgeGraph:
    return AgentKnowledgeGraph()


@pytest.fixture
def persisted() -> list:
    return []


def attach(agent, kg, persisted):
    agent.knowledge_graph = kg

    async def persister(nodes, edges):
        persisted.append((list(nodes), list(edges)))

    agent.knowledge_persister = persister
    return agent


@pytest.fixture
def steward(ds, kg, persisted):
    return attach(DataStewardAgent("steward", datasource=ds), kg, persisted)


@pytest.fixture
def engineer(ds, kg, persisted):
    return attach(DataEngineerAgent("engineer", datasource=ds), kg, persisted)


def run(agent, task_type, **context):
    return agent.execute_task(Task(type=task_type, context=context))


def node_id(warehouse, table):
    return dataset_node_id("wh", warehouse.schema, table)


class TestCatalog:
    async def test_catalogs_a_table(self, steward, warehouse):
        result = await run(steward, "catalog_dataset", name="orders")

        assert result["data_source"] == "postgres:wh"
        assert result["dataset_name"] == f"{warehouse.schema}.orders"
        assert result["schema"]["column_names"] == [
            "id",
            "customer_id",
            "amount",
            "status",
            "created_at",
        ]
        assert result["schema"]["primary_key"] == ["id"]
        assert result["schema"]["size_bytes"] > 0
        assert result["metadata"]["referenced_by"] == [f"{warehouse.schema}.order_items"]
        assert "has_primary_key" in result["tags"]
        assert result["knowledge_graph"] == "updated"
        assert f"{warehouse.schema}.orders" in steward.datasets_cataloged

    async def test_accepts_table_and_dataset_as_aliases_and_a_schema(self, steward, warehouse):
        for key in ("table", "dataset"):
            assert (await run(steward, "catalog_dataset", **{key: "orders"}))[
                "dataset_name"
            ].endswith(".orders")
        explicit = await run(steward, "catalog_dataset", name="orders", schema=warehouse.schema)
        assert explicit["dataset_name"] == f"{warehouse.schema}.orders"

    async def test_without_a_name_it_catalogs_everything_in_scope(self, steward, warehouse):
        result = await run(steward, "catalog_dataset")
        names = {t["dataset_name"] for t in result["tables"]}
        assert {f"{warehouse.schema}.customers", f"{warehouse.schema}.big_orders"} <= names
        assert not any(warehouse.other_schema in n for n in names)
        assert result["table_count"] == len(names) and result["truncated"] is False
        assert {t["kind"] for t in result["tables"]} >= {"table", "view"}

    async def test_the_knowledge_graph_gets_datasets_and_lineage(self, steward, kg, warehouse):
        await run(steward, "catalog_dataset", name="orders")

        orders, customers = node_id(warehouse, "orders"), node_id(warehouse, "customers")
        node = kg.get_node(orders)
        assert node.node_type == NodeType.DATASET
        assert node.properties["rows_estimate"] is None or node.properties["rows_estimate"] >= 0
        assert node.properties["primary_key"] == ["id"] and node.properties["columns"] == 5
        assert node.created_by == "steward"
        assert kg.get_node(customers) is not None  # stub for the referenced parent
        assert [(e.target_id, e.relation_type) for e in kg.get_outgoing_edges(orders)] == [
            (customers, RelationType.DEPENDS_ON)
        ]
        assert kg.get_dependencies(orders) == [customers]

    async def test_repeating_a_task_does_not_duplicate_anything(self, steward, kg):
        await run(steward, "catalog_dataset", name="orders")
        nodes, edges = len(kg.nodes), len(kg.edges)
        for _ in range(3):
            await run(steward, "catalog_dataset", name="orders")
        assert (len(kg.nodes), len(kg.edges)) == (nodes, edges)

    async def test_only_new_edges_are_handed_to_the_persister(self, steward, persisted):
        await run(steward, "catalog_dataset", name="orders")
        await run(steward, "catalog_dataset", name="orders")
        assert (
            len(persisted[0][1]) == 1 and persisted[1][1] == []
        )  # nodes refresh, edges do not repeat

    async def test_out_of_scope_parents_get_no_edges(self, warehouse, kg):
        scoped = PostgresDataSource(
            PostgresConfig(
                url=warehouse.reader_url,
                name="wh",
                schemas=(warehouse.schema,),
                table_patterns=(f"{warehouse.schema}.orders",),
            )
        )
        agent = DataStewardAgent("s", datasource=scoped)
        agent.knowledge_graph = kg
        try:
            await run(agent, "catalog_dataset", name="orders")
            assert kg.get_outgoing_edges(node_id(warehouse, "orders")) == []
            assert kg.get_node(node_id(warehouse, "customers")) is None
        finally:
            await scoped.close()

    async def test_works_without_a_knowledge_graph(self, ds):
        result = await run(DataStewardAgent("s", datasource=ds), "catalog_dataset", name="orders")
        assert result["knowledge_graph"] == "not_attached" and result["status"] == "success"

    async def test_a_failing_persister_never_fails_the_task(self, ds, kg):
        agent = DataStewardAgent("s", datasource=ds)
        agent.knowledge_graph = kg

        async def broken(nodes, edges):
            raise RuntimeError("database down")

        agent.knowledge_persister = broken
        result = await run(agent, "catalog_dataset", name="orders")
        assert result["status"] == "success" and result["knowledge_graph"] == "failed"

    async def test_errors_become_failed_tasks_with_safe_messages(self, steward, warehouse):
        for context, fragment in [
            ({"name": f"{warehouse.other_schema}.secrets"}, "not available to agents"),
            ({"name": "nope"}, "was not found"),
            ({"name": 5}, "must be a string"),
        ]:
            task = Task(type="catalog_dataset", context=context)
            await steward.accept_task(task)
            await steward.run_task(task)
            assert task.status == TaskStatus.FAILED and fragment in task.error, task.error


class TestDocumentSchema:
    async def test_documents_columns_keys_and_relationships(self, steward, warehouse):
        result = await run(steward, "document_schema", table="customers")
        docs = result["documentation"]

        assert result["table_comment"] == "Customer master data"
        assert docs["id"]["tags"] == ["primary_key"] and docs["id"]["nullable"] is False
        assert docs["email"]["description"] == "Primary contact address"
        assert "possible_pii.email" in docs["email"]["tags"]
        assert docs["id"]["default"].startswith("nextval")
        assert result["columns_documented"] == len(docs) == 11
        assert {r["table"] for r in result["relationships"]} == {
            f"{warehouse.schema}.orders",
            f"{warehouse.schema}.orphans",
        }
        assert all(r["type"] == "one_to_many" for r in result["relationships"])

    async def test_foreign_keys_show_as_many_to_one(self, steward, warehouse):
        result = await run(steward, "document_schema", table="orders")
        (parent,) = [r for r in result["relationships"] if r["type"] == "many_to_one"]
        assert parent["table"] == f"{warehouse.schema}.customers" and parent["key"] == [
            "customer_id"
        ]
        assert result["documentation"]["customer_id"]["tags"] == ["foreign_key"]
        assert any(i["unique"] for i in result["indexes"])

    async def test_views_and_composite_keys(self, steward):
        view = await run(steward, "document_schema", table="big_orders")
        assert view["kind"] == "view" and view["columns_documented"] == 5
        items = await run(steward, "document_schema", table="order_items")
        assert items["primary_key"] == ["order_id", "line"]
        assert items["documentation"]["order_id"]["tags"] == ["primary_key", "foreign_key"]

    async def test_records_the_table_in_the_graph(self, steward, kg, warehouse):
        await run(steward, "document_schema", table="orders")
        assert kg.get_node(node_id(warehouse, "orders")) is not None


class TestClassification:
    async def test_finds_sensitive_columns_from_names_and_values(self, steward):
        result = await run(steward, "classify_data", dataset="customers")
        found = result["column_classifications"]

        assert found["email"]["label"] == "pii.email" and found["email"]["confidence"] == 0.95
        assert (
            found["ssn"]["label"] == "government_id" and found["ssn"]["sensitivity"] == "restricted"
        )
        assert found["card"]["label"] == "financial.card"
        assert found["phone"]["label"] == "pii.phone"
        assert found["ip"]["label"] == "pii.ip"
        assert found["full_name"]["evidence"] == [
            "column_name"
        ]  # values 'Person 1' match no pattern
        assert {"id", "legacy", "notes", "score", "signup_ts"} <= set(
            result["unclassified_columns"]
        )

        summary = result["classification"]
        assert summary["sensitivity_level"] == "restricted" and summary["contains_pii"] is True
        assert {"GDPR", "PCI-DSS"} <= set(summary["regulations_to_review"])
        assert "Encrypt at rest" in result["required_controls"]

    async def test_results_never_contain_the_sampled_values(self, steward):
        result = await run(steward, "classify_data", dataset="customers")
        dumped = json.dumps(result)
        for value in SAMPLE_VALUES:
            assert value not in dumped
        assert "example.com" not in dumped

    async def test_values_reveal_badly_named_columns(self, steward):
        result = await run(steward, "classify_data", dataset="misc")
        found = result["column_classifications"]
        assert set(found) == {"contact"}  # `handle` and `hits` are ordinary
        assert found["contact"]["label"] == "pii.email"
        assert (
            found["contact"]["evidence"] == ["sample_values"]
            and found["contact"]["match_rate"] == 1.0
        )
        assert found["contact"]["confidence"] == 0.8
        assert "corp.example" not in json.dumps(result)

    async def test_the_reported_sample_is_what_was_actually_read(self, steward):
        assert (await run(steward, "classify_data", dataset="misc", sample_rows=7))[
            "sample_rows"
        ] == 7
        assert (await run(steward, "classify_data", dataset="customers"))[
            "sample_rows"
        ] == 60  # whole table
        assert (await run(steward, "classify_data", dataset="strict_table"))["sample_rows"] == 2
        no_text_columns = await run(steward, "classify_data", dataset="empty_table")
        assert no_text_columns["sample_rows"] == 0 and no_text_columns["sampled_columns"] == 0

    async def test_unreadable_tables_fall_back_to_names(self, steward):
        result = await run(steward, "classify_data", dataset="no_access")
        assert result["sample_rows"] == 0 and "not sampled" in result["sampling_note"]
        assert "permission denied" in result["sampling_note"]
        assert result["column_classifications"]["secret"]["label"] == "credential"  # by name alone
        assert result["column_classifications"]["secret"]["evidence"] == ["column_name"]

    async def test_ordinary_tables_come_back_clean(self, steward):
        result = await run(steward, "classify_data", dataset="orders")
        assert result["column_classifications"] == {}
        assert result["classification"]["sensitivity_level"] == "internal"
        assert result["classification"]["contains_pii"] is False

    @pytest.mark.parametrize("rows", [0, -1, "10", True])
    async def test_sample_rows_must_be_a_positive_integer(self, steward, rows):
        with pytest.raises(ValueError, match="sample_rows"):
            await run(steward, "classify_data", dataset="customers", sample_rows=rows)

    async def test_the_graph_learns_the_sensitivity(self, steward, kg, warehouse):
        await run(steward, "classify_data", dataset="customers")
        props = kg.get_node(node_id(warehouse, "customers")).properties
        assert props["sensitivity_level"] == "restricted" and props["contains_pii"] is True
        assert {"email", "ssn", "card"} <= set(props["sensitive_columns"])
        assert "4111111111111111" not in json.dumps(props)

    async def test_classifying_does_not_clobber_catalog_data(self, steward, kg, warehouse):
        await run(steward, "catalog_dataset", name="customers")
        await run(steward, "classify_data", dataset="customers")
        props = kg.get_node(node_id(warehouse, "customers")).properties
        assert props["columns"] == 11 and props["sensitivity_level"] == "restricted"


class TestQualityCheck:
    async def test_reports_findings_without_failing_the_task(self, engineer, warehouse):
        result = await run(
            engineer, "quality_check", table="orphans", checks=["row_count", "foreign_keys"]
        )

        assert result["status"] == "success" and result["healthy"] is False
        assert result["checks"] == {"row_count": "passed", "foreign_keys": "failed"}
        assert (result["checks_passed"], result["checks_failed"], result["checks_errored"]) == (
            1,
            1,
            0,
        )
        assert result["issues"][0]["severity"] == "error"
        assert result["table"] == f"{warehouse.schema}.orphans" and engineer.quality_checks_run == 1

    async def test_a_healthy_table(self, engineer):
        result = await run(engineer, "quality_check", table="orders")
        assert result["healthy"] is True and result["issues"] == []
        assert result["checks_passed"] == 3

    async def test_invalid_options_fail_the_task_clearly(self, engineer):
        with pytest.raises(ValueError, match="unknown checks"):
            await run(engineer, "quality_check", table="orders", checks=["magic"])

    async def test_findings_become_issues_linked_to_the_dataset(self, engineer, kg, warehouse):
        await run(engineer, "quality_check", table="orphans", checks=["foreign_keys"])

        dataset = node_id(warehouse, "orphans")
        issues = [kg.get_node(e.source_id) for e in kg.get_incoming_edges(dataset)]
        (issue,) = issues
        assert issue.node_type == NodeType.ISSUE and issue.properties["status"] == "open"
        assert (
            issue.properties["severity"] == "high" and issue.properties["check"] == "foreign_keys"
        )
        assert "no matching row" in issue.properties["description"]
        assert kg.get_node(dataset).properties["last_quality_check"]["healthy"] is False

    async def test_repeated_runs_update_the_same_issue(self, engineer, kg, warehouse):
        for _ in range(3):
            await run(engineer, "quality_check", table="orphans", checks=["foreign_keys"])
        issues = [n for n in kg.nodes.values() if n.node_type == NodeType.ISSUE]
        assert len(issues) == 1
        assert "first_seen" in issues[0].properties and "last_seen" in issues[0].properties
        assert len(kg.get_incoming_edges(node_id(warehouse, "orphans"))) == 1

    async def test_fixed_problems_are_marked_resolved(self, engineer, kg, warehouse):
        table = "fixme"
        engine = create_async_engine(warehouse.admin_url)
        async with engine.begin() as conn:
            await conn.execute(
                text(f"CREATE TABLE {warehouse.schema}.{table} (id serial PRIMARY KEY, c bigint)")
            )
            await conn.execute(
                text(f"INSERT INTO {warehouse.schema}.{table} (c) VALUES (1), (999)")
            )
            await conn.execute(
                text(f"GRANT SELECT ON {warehouse.schema}.{table} TO {warehouse.reader}")
            )
            await conn.execute(
                text(
                    f"ALTER TABLE {warehouse.schema}.{table} ADD CONSTRAINT fixme_fk FOREIGN KEY (c) "
                    f"REFERENCES {warehouse.schema}.customers(id) NOT VALID"
                )
            )
        try:
            first = await run(
                engineer, "quality_check", table=table, checks=["foreign_keys", "nulls"]
            )
            assert first["healthy"] is False
            (issue,) = [n for n in kg.nodes.values() if n.node_type == NodeType.ISSUE]
            assert issue.properties["status"] == "open"

            # a run that did not include the failing check proves nothing about it
            await run(engineer, "quality_check", table=table, checks=["nulls"])
            assert issue.properties["status"] == "open"

            async with engine.begin() as conn:
                await conn.execute(text(f"DELETE FROM {warehouse.schema}.{table} WHERE c = 999"))
            fixed = await run(engineer, "quality_check", table=table, checks=["foreign_keys"])
            assert fixed["healthy"] is True
            assert issue.properties["status"] == "resolved" and "resolved_at" in issue.properties
        finally:
            async with engine.begin() as conn:
                await conn.execute(text(f"DROP TABLE {warehouse.schema}.{table}"))
            await engine.dispose()

    async def test_an_errored_check_does_not_resolve_issues(
        self, engineer, kg, warehouse, monkeypatch
    ):
        from unistax.agents.connectors import quality
        from unistax.agents.connectors.errors import QueryTimeout

        await run(engineer, "quality_check", table="orphans", checks=["foreign_keys"])

        async def timed_out(*a, **k):
            raise QueryTimeout("the query exceeded its time limit and was cancelled")

        monkeypatch.setattr(quality, "_foreign_keys", timed_out)
        result = await run(engineer, "quality_check", table="orphans", checks=["foreign_keys"])

        assert result["checks"] == {"foreign_keys": "errored"} and result["healthy"] is False
        (issue,) = [n for n in kg.nodes.values() if n.node_type == NodeType.ISSUE]
        assert issue.properties["status"] == "open"


class TestSimulatedWhenNoDataSourceIsConfigured:
    @pytest.mark.parametrize(
        ("cls", "task_type", "context"),
        [
            (DataStewardAgent, "catalog_dataset", {"name": "x"}),
            (DataStewardAgent, "document_schema", {"table": "x"}),
            (DataStewardAgent, "classify_data", {"dataset": "x"}),
            (DataEngineerAgent, "quality_check", {"table": "x", "checks": ["a"]}),
        ],
    )
    async def test_results_are_labelled_simulated(self, cls, task_type, context):
        result = await run(cls("a"), task_type, **context)
        assert result["data_source"] == "simulated" and result["status"] == "success"

    async def test_other_task_types_are_untouched_by_a_data_source(self, engineer):
        result = await run(engineer, "monitor_pipeline", pipeline="p")
        assert "data_source" not in result and result["pipeline"] == "p"
