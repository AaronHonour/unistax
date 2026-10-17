"""The Postgres data source through the REST API."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from unistax.agents.api import AgentAPISettings, create_agent_api

from .conftest import API, create_agent, headers_for, submit_task, wait_for, wait_task

pytestmark = pytest.mark.api


@pytest.fixture
def ds_settings(settings, warehouse) -> AgentAPISettings:
    return replace(
        settings,
        datasource_url=warehouse.reader_url,
        datasource_name="wh",
        datasource_schemas=(warehouse.schema,),
    )


@pytest.fixture
def ds_client(ds_settings):
    with TestClient(create_agent_api(ds_settings)) as client:
        yield client


def run_task(client, headers, task_type, agent_id=None, **context):
    body = {"task_type": task_type, "context": context}
    if agent_id:
        body["agent_id"] = agent_id
    queued = client.post(f"{API}/tasks", json=body, headers=headers)
    assert queued.status_code == 202, queued.text
    return wait_task(client, headers, queued.json()["data"]["task_id"])


class TestConfiguration:
    def test_agents_report_where_their_data_comes_from(self, ds_client, admin):
        steward = create_agent(ds_client, admin, "stw", "steward")
        engineer = create_agent(ds_client, admin, "eng", "engineer")
        analyst = create_agent(ds_client, admin, "ana", "analyst")

        assert steward["data_source"] == "postgres:wh"
        assert steward["data_source_tasks"] == [
            "catalog_dataset",
            "classify_data",
            "document_schema",
        ]
        assert engineer["data_source"] == "postgres:wh" and engineer["data_source_tasks"] == [
            "quality_check"
        ]
        assert analyst["data_source"] is None and analyst["data_source_tasks"] == []

    def test_without_a_data_source_agents_say_simulated(self, client, admin):
        assert create_agent(client, admin, "stw", "steward")["data_source"] == "simulated"
        result = run_task(client, admin, "classify_data", dataset="customers")
        assert result["status"] == "completed" and result["result"]["data_source"] == "simulated"

    def test_the_datasource_endpoint_reports_health_without_the_connection_string(
        self, ds_client, operator, ds_settings
    ):
        info = ds_client.get(f"{API}/datasource", headers=operator).json()["data"]

        assert (
            info["configured"] is True and info["status"] == "ok" and info["label"] == "postgres:wh"
        )
        assert info["schemas"] == list(ds_settings.datasource_schemas)
        assert info["role"].startswith("agent_reader") and info["warnings"] == []
        assert info["limits"]["max_scan_rows"] == 100_000
        dumped = json.dumps(info)
        assert "postgresql" not in dumped and "password" not in dumped.lower()

    def test_the_datasource_endpoint_when_nothing_is_configured(self, client, operator):
        info = client.get(f"{API}/datasource", headers=operator).json()["data"]
        assert info["configured"] is False and "simulated" in info["detail"]

    def test_the_datasource_endpoint_needs_the_operator_role(self, ds_client, viewer):
        assert ds_client.get(f"{API}/datasource", headers=viewer).status_code == 403
        assert ds_client.get(f"{API}/datasource").status_code == 401

    def test_readiness_reports_the_data_source_state(self, ds_client, client):
        assert ds_client.get("/health/ready").json()["datasource"] == "verified"
        assert client.get("/health/ready").json()["datasource"] == "not_configured"

    def test_a_superuser_data_source_refuses_to_start(self, ds_settings, warehouse):
        unsafe = replace(ds_settings, datasource_url=warehouse.admin_url)
        from unistax.agents.connectors import DataSourceUnsafe

        with (
            pytest.raises(DataSourceUnsafe, match="superuser"),
            TestClient(create_agent_api(unsafe)),
        ):
            pass

    def test_an_unreachable_data_source_does_not_stop_the_service(self, ds_settings, operator):
        down = replace(
            ds_settings,
            datasource_url="postgresql://u:topsecret@127.0.0.1:1/db",
        )
        with TestClient(create_agent_api(down)) as client:
            assert client.get("/health/ready").json() == {
                "status": "ready",
                "database": True,
                "datasource": "unverified",
            }
            info = client.get(f"{API}/datasource", headers=headers_for(down, "operator")).json()[
                "data"
            ]
            assert info["status"] == "unavailable" and "topsecret" not in json.dumps(info)

            create_agent(client, headers_for(down, "admin"), "stw", "steward")
            failed = run_task(client, headers_for(down, "admin"), "catalog_dataset", name="x")
            assert failed["status"] == "failed" and "could not connect" in failed["error"]
            assert "topsecret" not in json.dumps(failed)

    def test_invalid_data_source_settings_fail_at_startup(self, ds_settings):
        with pytest.raises(ValueError, match="cannot be exposed"):
            create_agent_api(replace(ds_settings, datasource_schemas=("pg_catalog",)))

    def test_settings_hide_secrets_from_repr(self, ds_settings):
        text = repr(ds_settings)
        assert ds_settings.datasource_url not in text and ds_settings.jwt_secret not in text
        assert ds_settings.database_url not in text

    def test_settings_parse_from_the_environment(self):
        s = AgentAPISettings.from_env(
            {
                "UNISTAX_AGENT_API_DATASOURCE_URL": "postgresql://u:p@h/db",
                "UNISTAX_AGENT_API_DATASOURCE_SCHEMAS": "public, analytics",
                "UNISTAX_AGENT_API_DATASOURCE_TABLES": "public.*,analytics.fact_*",
                "UNISTAX_AGENT_API_DATASOURCE_SCAN_TIMEOUT_MS": "2500",
                "UNISTAX_AGENT_API_DATASOURCE_SESSION_DEFAULTS": "false",
            }
        )
        assert s.datasource_schemas == ("public", "analytics")
        assert s.datasource_tables == ("public.*", "analytics.fact_*")
        assert s.datasource_scan_timeout_ms == 2500 and s.datasource_session_defaults is False


class TestStewardOverHttp:
    def test_catalog_document_and_classify(self, ds_client, admin, warehouse):
        create_agent(ds_client, admin, "stw", "steward")

        catalog = run_task(ds_client, admin, "catalog_dataset", name="orders")
        assert catalog["status"] == "completed" and catalog["assigned_agent"] == "stw"
        assert catalog["result"]["dataset_name"] == f"{warehouse.schema}.orders"
        assert catalog["result"]["knowledge_graph"] == "updated"

        doc = run_task(ds_client, admin, "document_schema", table="customers")["result"]
        assert doc["columns_documented"] == 11 and doc["table_comment"] == "Customer master data"

        classified = run_task(ds_client, admin, "classify_data", dataset="customers")["result"]
        assert classified["classification"]["sensitivity_level"] == "restricted"
        assert "4111111111111111" not in json.dumps(classified)

    def test_requests_for_other_schemas_fail_safely(self, ds_client, admin, warehouse):
        create_agent(ds_client, admin, "stw", "steward")
        failed = run_task(
            ds_client, admin, "catalog_dataset", name=f"{warehouse.other_schema}.secrets"
        )
        assert failed["status"] == "failed" and "not available to agents" in failed["error"]
        assert "top-secret-value" not in json.dumps(failed)

    def test_bad_input_is_reported_as_a_failed_task(self, ds_client, admin):
        create_agent(ds_client, admin, "stw", "steward")
        failed = run_task(ds_client, admin, "classify_data", dataset="customers", sample_rows=0)
        assert failed["status"] == "failed" and "sample_rows" in failed["error"]

    def test_injection_in_task_input_is_inert(self, ds_client, admin):
        create_agent(ds_client, admin, "stw", "steward")
        create_agent(ds_client, admin, "eng", "engineer")
        for attack in ['customers"; DROP TABLE customers; --', "customers; DELETE FROM orders"]:
            assert run_task(ds_client, admin, "catalog_dataset", name=attack)["status"] == "failed"
            failed = run_task(
                ds_client,
                admin,
                "quality_check",
                table="dups",
                checks=["duplicates"],
                unique_columns=[attack],
            )
            assert failed["status"] == "failed" and "does not exist" in failed["error"]
        ok = run_task(ds_client, admin, "catalog_dataset", name="customers")
        assert ok["status"] == "completed"


class TestEngineerOverHttp:
    def test_quality_check_finds_the_seeded_problems(self, ds_client, admin):
        create_agent(ds_client, admin, "eng", "engineer")
        done = run_task(
            ds_client, admin, "quality_check", table="orphans", checks=["row_count", "foreign_keys"]
        )
        result = done["result"]
        assert done["status"] == "completed"  # findings do not fail the task
        assert result["healthy"] is False and result["checks"]["foreign_keys"] == "failed"
        assert result["issues"][0]["severity"] == "error"

    def test_invalid_options_fail_the_task_with_a_clear_message(self, ds_client, admin):
        create_agent(ds_client, admin, "eng", "engineer")
        failed = run_task(ds_client, admin, "quality_check", table="orders", checks=["bogus"])
        assert failed["status"] == "failed" and "unknown checks" in failed["error"]


class TestKnowledgeGraphThroughTheApi:
    def test_agents_fill_the_graph_and_it_is_queryable(self, ds_client, admin, viewer, warehouse):
        create_agent(ds_client, admin, "stw", "steward")
        create_agent(ds_client, admin, "eng", "engineer")
        run_task(ds_client, admin, "catalog_dataset", name="orders")
        run_task(ds_client, admin, "quality_check", table="orphans", checks=["foreign_keys"])

        orders = f"pg:wh:{warehouse.schema}.orders"
        customers = f"pg:wh:{warehouse.schema}.customers"
        node = ds_client.get(f"{API}/knowledge/nodes/{orders}", headers=viewer).json()["data"]
        assert node["node_type"] == "dataset" and node["created_by"] == "stw"
        deps = ds_client.get(f"{API}/knowledge/nodes/{orders}/dependencies", headers=viewer).json()[
            "data"
        ]
        assert deps == [customers]

        issues = ds_client.get(f"{API}/knowledge/nodes?node_type=issue", headers=viewer).json()
        assert issues["total"] == 1 and issues["data"][0]["properties"]["status"] == "open"

    def test_what_agents_learn_survives_a_restart(
        self, make_client, admin, viewer, warehouse, ds_settings
    ):
        def start():
            c = TestClient(create_agent_api(ds_settings))
            c.__enter__()
            return c

        first = start()
        create_agent(first, admin, "stw", "steward")
        create_agent(first, admin, "eng", "engineer")
        run_task(first, admin, "catalog_dataset", name="orders")
        run_task(first, admin, "classify_data", dataset="customers")
        run_task(first, admin, "quality_check", table="orphans", checks=["foreign_keys"])
        stats = first.get(f"{API}/knowledge/statistics", headers=viewer).json()["data"]
        first.__exit__(None, None, None)

        second = start()
        try:
            again = second.get(f"{API}/knowledge/statistics", headers=viewer).json()["data"]
            assert (
                again["total_nodes"] == stats["total_nodes"]
                and again["total_edges"] == stats["total_edges"]
            )
            node = second.get(
                f"{API}/knowledge/nodes/pg:wh:{warehouse.schema}.customers", headers=viewer
            )
            assert node.json()["data"]["properties"]["sensitivity_level"] == "restricted"

            # restored agents are wired to the data source and the graph again
            run = run_task(second, admin, "catalog_dataset", name="orders")
            assert run["status"] == "completed" and run["result"]["knowledge_graph"] == "updated"
            assert second.get(f"{API}/knowledge/statistics", headers=viewer).json()["data"] == again
        finally:
            second.__exit__(None, None, None)

    def test_websocket_clients_see_data_tasks_complete(self, ds_client, admin):
        create_agent(ds_client, admin, "stw", "steward")
        with ds_client.websocket_connect(f"{API}/ws/events", headers=admin) as ws:
            ws.receive_json()
            ws.send_json({"action": "subscribe", "event_types": ["task_completed"]})
            ws.receive_json()
            queued = ds_client.post(
                f"{API}/tasks",
                json={"task_type": "catalog_dataset", "context": {"name": "orders"}},
                headers=admin,
            ).json()["data"]
            event = ws.receive_json()
        assert event["data"]["task_id"] == queued["task_id"] and event["data"]["success"] is True


class TestWorkflowAcrossTheData:
    def test_catalog_classify_and_check_as_one_workflow(self, ds_client, admin, warehouse):
        create_agent(ds_client, admin, "stw", "steward")
        create_agent(ds_client, admin, "eng", "engineer")
        steps = [
            {
                "step_id": "catalog",
                "task_type": "catalog_dataset",
                "agent_persona": "data_steward",
                "context": {"name": "customers"},
            },
            {
                "step_id": "classify",
                "task_type": "classify_data",
                "agent_persona": "data_steward",
                "dependencies": ["catalog"],
                "context": {"dataset": "customers"},
            },
            {
                "step_id": "quality",
                "task_type": "quality_check",
                "agent_persona": "data_engineer",
                "dependencies": ["catalog"],
                "context": {"table": "customers", "checks": ["nulls"]},
            },
        ]
        created = ds_client.post(
            f"{API}/workflows", json={"name": "wf", "steps": steps}, headers=admin
        )
        assert created.status_code == 201, created.text
        wf = created.json()["data"]["workflow_id"]
        assert ds_client.post(f"{API}/workflows/{wf}/execute", headers=admin).status_code == 202

        done = wait_for(
            lambda: ds_client.get(f"{API}/workflows/{wf}", headers=admin).json()["data"],
            lambda w: w["status"] in ("completed", "failed"),
            20,
        )
        assert done["status"] == "completed", done
        by_step = {s["step_id"]: s for s in done["steps"]}
        assert by_step["classify"]["result"]["classification"]["sensitivity_level"] == "restricted"
        assert by_step["quality"]["result"]["checks"] == {"nulls": "passed"}


class TestSecretsNeverLeak:
    def test_the_password_is_absent_from_logs_errors_and_responses(
        self, settings, warehouse, caplog, admin
    ):
        password = "Sup3r-S3cret-Pw"
        url = f"postgresql://someone:{password}@127.0.0.1:1/db"
        config = replace(settings, datasource_url=url, datasource_name="wh")
        with caplog.at_level(logging.DEBUG):
            with TestClient(create_agent_api(config)) as client:
                create_agent(client, headers_for(config, "admin"), "stw", "steward")
                task = run_task(client, headers_for(config, "admin"), "catalog_dataset", name="x")
                everything = [
                    json.dumps(task),
                    json.dumps(
                        client.get(
                            f"{API}/datasource", headers=headers_for(config, "operator")
                        ).json()
                    ),
                    json.dumps(
                        client.get(f"{API}/agents", headers=headers_for(config, "viewer")).json()
                    ),
                    client.get("/health/ready").text,
                ]
        assert task["status"] == "failed"
        assert all(password not in blob for blob in everything)
        log_text = "\n".join(
            f"{r.getMessage()} {r.exc_text or ''}" + "".join(map(str, r.args or ()))
            for r in caplog.records
        )
        assert password not in log_text
