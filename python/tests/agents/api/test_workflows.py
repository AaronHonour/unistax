"""Workflow creation, validation, execution and cancellation."""

from __future__ import annotations

import asyncio

import pytest

from unistax.agents import DataAnalystAgent, DataEngineerAgent

from .conftest import API, create_agent, wait_for

pytestmark = pytest.mark.api


def step(step_id, task_type="quality_check", persona="data_engineer", deps=(), **extra):
    return {
        "step_id": step_id,
        "task_type": task_type,
        "agent_persona": persona,
        "dependencies": list(deps),
        "context": {"table": "t"},
        **extra,
    }


def create_workflow(client, headers, steps, name="wf"):
    return client.post(f"{API}/workflows", json={"name": name, "steps": steps}, headers=headers)


def wf_state(client, headers, workflow_id):
    return client.get(f"{API}/workflows/{workflow_id}", headers=headers).json()["data"]


def wait_workflow(client, headers, workflow_id, timeout=15.0):
    return wait_for(
        lambda: wf_state(client, headers, workflow_id),
        lambda w: w["status"] in ("completed", "failed", "cancelled"),
        timeout,
    )


class TestValidation:
    @pytest.mark.parametrize(
        "steps,fragment",
        [
            ([step("a"), step("a")], "unique"),
            ([step("a", deps=["ghost"])], "unknown step"),
            ([step("a", deps=["a"])], "itself"),
            ([step("a", deps=["b"]), step("b", deps=["a"])], "cycle"),
            ([step("a", task_type="train_model")], "cannot run"),
            ([step("a", persona="wizard")], "unknown persona"),
            ([step("a", persona=None, agent_id="ghost")], "not found"),
        ],
    )
    def test_invalid_definitions_are_422(self, client, admin, steps, fragment):
        for s in steps:
            if s.get("agent_persona") is None:
                s.pop("agent_persona")
        r = create_workflow(client, admin, steps)
        assert r.status_code == 422, r.text
        assert fragment in str(r.json()["detail"]).lower()

    def test_step_needs_a_target(self, client, admin):
        s = step("a")
        del s["agent_persona"]
        assert create_workflow(client, admin, [s]).status_code == 422

    def test_empty_workflow_is_422(self, client, admin):
        assert create_workflow(client, admin, []).status_code == 422


class TestExecution:
    def test_dag_runs_in_dependency_order(self, client, admin):
        create_agent(client, admin, "eng_1")
        create_agent(client, admin, "ana_1", "analyst")
        created = create_workflow(
            client,
            admin,
            [
                step("fetch"),
                step("analyze", "analyze_data", "data_analyst", deps=["fetch"]),
            ],
        ).json()["data"]
        assert created["status"] == "pending"

        started = client.post(f"{API}/workflows/{created['workflow_id']}/execute", headers=admin)
        assert started.status_code == 202

        done = wait_workflow(client, admin, created["workflow_id"])
        assert done["status"] == "completed"
        steps = {s["step_id"]: s for s in done["steps"]}
        assert steps["fetch"]["agent_id"] == "eng_1" and steps["analyze"]["agent_id"] == "ana_1"
        assert steps["fetch"]["completed_at"] <= steps["analyze"]["started_at"]
        assert done["duration_seconds"] is not None

        progress = client.get(
            f"{API}/workflows/{created['workflow_id']}/status", headers=admin
        ).json()["data"]
        assert progress["progress_percent"] == 100.0 and progress["completed_steps"] == 2

    def test_workflow_steps_emit_agent_metrics(self, client, admin):
        create_agent(client, admin, "eng_1")
        wf = create_workflow(client, admin, [step("a")]).json()["data"]["workflow_id"]
        client.post(f"{API}/workflows/{wf}/execute", headers=admin)
        wait_workflow(client, admin, wf)
        metrics = client.get(f"{API}/metrics/agents/eng_1", headers=admin).json()["data"]["metrics"]
        assert metrics["tasks_completed"] == 1

    def test_failed_step_skips_dependents_instead_of_hanging(self, client, admin, monkeypatch):
        async def boom(self, context):
            raise RuntimeError("source offline")

        monkeypatch.setattr(DataEngineerAgent, "_run_quality_check", boom)
        create_agent(client, admin, "eng_1")
        create_agent(client, admin, "ana_1", "analyst")
        wf = create_workflow(
            client,
            admin,
            [
                step("fetch", max_retries=1),
                step("analyze", "analyze_data", "data_analyst", deps=["fetch"]),
                step("independent", "analyze_data", "data_analyst"),
            ],
        ).json()["data"]["workflow_id"]
        client.post(f"{API}/workflows/{wf}/execute", headers=admin)

        done = wait_workflow(client, admin, wf)
        by_id = {s["step_id"]: s for s in done["steps"]}
        assert done["status"] == "failed"
        assert by_id["fetch"]["status"] == "failed" and "source offline" in by_id["fetch"]["error"]
        assert by_id["analyze"]["status"] == "skipped"
        assert by_id["independent"]["status"] == "completed"

    def test_step_without_matching_agent_fails_the_workflow(self, client, admin):
        wf = create_workflow(client, admin, [step("a", max_retries=1)]).json()["data"][
            "workflow_id"
        ]
        client.post(f"{API}/workflows/{wf}/execute", headers=admin)
        done = wait_workflow(client, admin, wf)
        assert done["status"] == "failed"
        assert "No suitable agent" in done["steps"][0]["error"]

    def test_cannot_execute_twice(self, client, admin, monkeypatch):
        async def slow(self, context):
            await asyncio.sleep(0.5)
            return {}

        monkeypatch.setattr(DataEngineerAgent, "_run_quality_check", slow)
        create_agent(client, admin)
        wf = create_workflow(client, admin, [step("a")]).json()["data"]["workflow_id"]
        assert client.post(f"{API}/workflows/{wf}/execute", headers=admin).status_code == 202
        assert client.post(f"{API}/workflows/{wf}/execute", headers=admin).status_code == 409
        wait_workflow(client, admin, wf)
        assert (
            client.post(f"{API}/workflows/{wf}/execute", headers=admin).status_code == 409
        )  # not pending

    def test_cancel_running_workflow(self, client, admin, monkeypatch):
        async def hang(self, context):
            await asyncio.sleep(30)

        monkeypatch.setattr(DataEngineerAgent, "_run_quality_check", hang)
        create_agent(client, admin)
        wf = create_workflow(client, admin, [step("a"), step("b", deps=["a"])]).json()["data"][
            "workflow_id"
        ]
        client.post(f"{API}/workflows/{wf}/execute", headers=admin)
        wait_for(
            lambda: client.get(f"{API}/agents/eng_1", headers=admin).json()["data"],
            lambda a: a["state"] == "working",
        )

        assert client.delete(f"{API}/workflows/{wf}", headers=admin).status_code == 409
        cancelled = client.post(f"{API}/workflows/{wf}/cancel", headers=admin)
        assert cancelled.status_code == 200 and cancelled.json()["data"]["status"] == "cancelled"
        assert {s["status"] for s in wf_state(client, admin, wf)["steps"]} == {"skipped"}

        agent = client.get(f"{API}/agents/eng_1", headers=admin).json()["data"]
        assert agent["active_tasks"] == [] or agent["state"] in ("idle", "working")
        assert client.post(f"{API}/workflows/{wf}/cancel", headers=admin).status_code == 409
        assert client.delete(f"{API}/workflows/{wf}", headers=admin).status_code == 204

    def test_listing_and_unknown_ids(self, client, admin):
        create_workflow(client, admin, [step("a")])
        create_workflow(client, admin, [step("a")])
        assert client.get(f"{API}/workflows", headers=admin).json()["total"] == 2
        assert client.get(f"{API}/workflows?status=completed", headers=admin).json()["total"] == 0
        assert client.get(f"{API}/workflows/ghost", headers=admin).status_code == 404
        assert client.post(f"{API}/workflows/ghost/execute", headers=admin).status_code == 404

    def test_workflow_survives_restart_and_running_ones_fail(self, make_client, admin, monkeypatch):
        async def hang(self, context):
            await asyncio.sleep(30)

        monkeypatch.setattr(DataEngineerAgent, "_run_quality_check", hang)
        first = make_client(shutdown_timeout=0.2)
        create_agent(first, admin)
        wf = create_workflow(first, admin, [step("a")]).json()["data"]["workflow_id"]
        first.post(f"{API}/workflows/{wf}/execute", headers=admin)
        wait_for(
            lambda: first.get(f"{API}/agents/eng_1", headers=admin).json()["data"],
            lambda a: a["state"] == "working",
        )
        first.__exit__(None, None, None)

        second = make_client()
        state = wf_state(second, admin, wf)
        assert state["status"] == "failed"
        assert state["steps"][0]["status"] in ("failed", "skipped")


class TestAllPersonasThroughTheAPI:
    def test_each_persona_runs_its_task_types_via_the_api(self, client, admin):
        from .conftest import submit_task, wait_task

        for agent_id, persona in [
            ("eng", "engineer"),
            ("ana", "analyst"),
            ("sci", "scientist"),
            ("stw", "steward"),
        ]:
            create_agent(client, admin, agent_id, persona)

        expected = {
            "quality_check": "eng",
            "analyze_data": "ana",
            "train_model": "sci",
            "check_compliance": "stw",
        }
        for task_type, agent_id in expected.items():
            queued = submit_task(client, admin, task_type)
            done = wait_task(client, admin, queued["task_id"])
            assert done["status"] == "completed", (task_type, done)
            assert done["assigned_agent"] == agent_id

    def test_four_persona_workflow(self, client, admin):
        for agent_id, persona in [("eng", "engineer"), ("sci", "scientist"), ("stw", "steward")]:
            create_agent(client, admin, agent_id, persona)

        steps = [
            step("ingest", "build_pipeline", "data_engineer"),
            step("catalog", "catalog_dataset", "data_steward", deps=["ingest"]),
            step("train", "train_model", "data_scientist", deps=["ingest"]),
            step("comply", "check_compliance", "data_steward", deps=["catalog", "train"]),
        ]
        wf = create_workflow(client, admin, steps).json()["data"]["workflow_id"]
        client.post(f"{API}/workflows/{wf}/execute", headers=admin)

        done = wait_workflow(client, admin, wf)
        assert done["status"] == "completed"
        agents = {s["step_id"]: s["agent_id"] for s in done["steps"]}
        assert agents == {"ingest": "eng", "catalog": "stw", "train": "sci", "comply": "stw"}

        comply = {s["step_id"]: s for s in done["steps"]}["comply"]
        train = {s["step_id"]: s for s in done["steps"]}["train"]
        assert comply["started_at"] >= train["completed_at"]
