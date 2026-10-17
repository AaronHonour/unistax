"""Task submission, scheduling, cancellation and failure handling."""

from __future__ import annotations

import asyncio
import threading

import pytest

from unistax.agents import DataEngineerAgent

from .conftest import API, create_agent, submit_task, task_state, wait_for, wait_task

pytestmark = pytest.mark.api


class TestSubmission:
    def test_task_runs_to_completion(self, client, admin):
        create_agent(client, admin)
        queued = submit_task(client, admin)
        assert queued["status"] in ("pending", "in_progress", "completed")
        assert queued["assigned_agent"] == "eng_1"

        done = wait_task(client, admin, queued["task_id"])
        assert done["status"] == "completed"
        assert done["result"]["status"] == "success"
        assert done["submitted_by"] == "admin-user"
        assert done["duration_seconds"] is not None

    def test_agent_metrics_and_state_after_task(self, client, admin):
        create_agent(client, admin)
        wait_task(client, admin, submit_task(client, admin)["task_id"])

        wait_for(
            lambda: client.get(f"{API}/agents/eng_1", headers=admin).json()["data"],
            lambda a: a["state"] == "idle" and a["metrics"]["tasks_completed"] == 1,
        )
        metrics = client.get(f"{API}/metrics/agents/eng_1", headers=admin).json()["data"]
        assert metrics["metrics"]["success_rate"] == 1.0

    def test_unsupported_task_type_is_422(self, client, admin):
        create_agent(client, admin)
        r = client.post(f"{API}/tasks", json={"task_type": "train_model"}, headers=admin)
        assert r.status_code == 422
        assert "build_pipeline" in r.json()["detail"]

    def test_no_agents_registered_is_422(self, client, admin):
        assert (
            client.post(
                f"{API}/tasks", json={"task_type": "quality_check"}, headers=admin
            ).status_code
            == 422
        )

    def test_pinned_agent_must_exist_and_be_capable(self, client, admin):
        create_agent(client, admin, "eng_1")
        create_agent(client, admin, "ana_1", "analyst")
        missing = client.post(
            f"{API}/tasks", json={"task_type": "quality_check", "agent_id": "ghost"}, headers=admin
        )
        incapable = client.post(
            f"{API}/tasks", json={"task_type": "quality_check", "agent_id": "ana_1"}, headers=admin
        )
        assert (missing.status_code, incapable.status_code) == (404, 422)

    def test_required_skills_must_be_met(self, client, admin):
        create_agent(client, admin, skills={"sql": 0.4})
        r = client.post(
            f"{API}/tasks",
            json={"task_type": "quality_check", "required_skills": {"sql": 0.9}},
            headers=admin,
        )
        assert r.status_code == 422

    @pytest.mark.parametrize(
        "body",
        [
            {"task_type": "Bad Type"},
            {"task_type": "quality_check", "priority": 11},
            {"task_type": "quality_check", "required_skills": {"sql": 2}},
        ],
    )
    def test_invalid_body_is_422(self, client, admin, body):
        create_agent(client, admin)
        assert client.post(f"{API}/tasks", json=body, headers=admin).status_code == 422

    def test_auto_assignment_prefers_best_skill_match(self, client, admin):
        create_agent(client, admin, "weak", skills={"sql": 0.6})
        create_agent(client, admin, "strong", skills={"sql": 0.95})
        task = submit_task(client, admin, required_skills={"sql": 0.5})
        assert task["assigned_agent"] == "strong"

    def test_equal_agents_share_load(self, client, admin, monkeypatch):
        async def slow(self, context):
            await asyncio.sleep(0.5)
            return {"status": "success"}

        monkeypatch.setattr(DataEngineerAgent, "_run_quality_check", slow)
        create_agent(client, admin, "eng_a")
        create_agent(client, admin, "eng_b")
        first = submit_task(client, admin)
        second = submit_task(client, admin)
        assert {first["assigned_agent"], second["assigned_agent"]} == {"eng_a", "eng_b"}

    def test_discovery_matches_scheduler(self, client, admin):
        create_agent(client, admin, "weak", skills={"sql": 0.6})
        create_agent(client, admin, "strong", skills={"sql": 0.95})
        r = client.post(
            f"{API}/discovery/for-task",
            json={"task_type": "quality_check", "required_skills": {"sql": 0.5}},
            headers=admin,
        )
        assert [m["agent_id"] for m in r.json()["data"]] == ["strong", "weak"]


class TestListing:
    def test_filters_and_pagination(self, client, admin):
        create_agent(client, admin)
        ids = [submit_task(client, admin)["task_id"] for _ in range(3)]
        for task_id in ids:
            wait_task(client, admin, task_id)

        all_tasks = client.get(f"{API}/tasks?page_size=2", headers=admin).json()
        assert all_tasks["total"] == 3 and len(all_tasks["data"]) == 2 and all_tasks["has_next"]
        assert client.get(f"{API}/tasks?status=completed", headers=admin).json()["total"] == 3
        assert client.get(f"{API}/tasks?status=failed", headers=admin).json()["total"] == 0
        assert (
            client.get(f"{API}/tasks?agent_id=eng_1&task_type=quality_check", headers=admin).json()[
                "total"
            ]
            == 3
        )

    def test_unknown_task_is_404(self, client, viewer):
        assert client.get(f"{API}/tasks/nope", headers=viewer).status_code == 404


class TestFailuresAndCancellation:
    def test_failing_task_is_recorded_as_failed(self, client, admin, monkeypatch):
        async def boom(self, context):
            raise RuntimeError("warehouse unreachable")

        monkeypatch.setattr(DataEngineerAgent, "_run_quality_check", boom)
        create_agent(client, admin)
        done = wait_task(client, admin, submit_task(client, admin)["task_id"])
        assert done["status"] == "failed"
        assert "warehouse unreachable" in done["error"]

        agent = wait_for(
            lambda: client.get(f"{API}/agents/eng_1", headers=admin).json()["data"],
            lambda a: a["state"] == "idle",
        )
        assert agent["metrics"]["tasks_failed"] == 1

    def test_cancel_running_task(self, client, admin, monkeypatch):
        async def hang(self, context):
            await asyncio.sleep(30)

        monkeypatch.setattr(DataEngineerAgent, "_run_quality_check", hang)
        create_agent(client, admin)
        task = submit_task(client, admin)
        wait_for(
            lambda: task_state(client, admin, task["task_id"]),
            lambda t: t["status"] == "in_progress",
        )

        r = client.post(f"{API}/tasks/{task['task_id']}/cancel", headers=admin)
        assert r.status_code == 200 and r.json()["data"]["status"] == "cancelled"

        agent = client.get(f"{API}/agents/eng_1", headers=admin).json()["data"]
        assert agent["active_tasks"] == [] and agent["state"] == "idle"
        assert (
            client.post(f"{API}/tasks/{task['task_id']}/cancel", headers=admin).status_code == 409
        )

    def test_cancel_finished_task_is_409(self, client, admin):
        create_agent(client, admin)
        done = wait_task(client, admin, submit_task(client, admin)["task_id"])
        assert (
            client.post(f"{API}/tasks/{done['task_id']}/cancel", headers=admin).status_code == 409
        )

    def test_excess_tasks_queue_instead_of_failing(self, client, admin, monkeypatch):
        running = 0
        peak = 0

        async def tracked(self, context):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.1)
            running -= 1
            return {"status": "success"}

        monkeypatch.setattr(DataEngineerAgent, "_run_quality_check", tracked)
        create_agent(client, admin, max_concurrent_tasks=1)
        ids = [submit_task(client, admin)["task_id"] for _ in range(4)]
        results = [wait_task(client, admin, i) for i in ids]
        assert [r["status"] for r in results] == ["completed"] * 4
        assert peak == 1

    def test_cancel_while_marking_in_progress_releases_the_agent(self, client, admin, monkeypatch):
        """A slow database must not strand an accepted task on the agent."""
        runtime = client.app.state.runtime
        original = runtime.store.update_task
        entered = threading.Event()

        async def slow_update(task_id, **values):
            if values.get("status") == "in_progress":
                entered.set()
                await asyncio.sleep(0.5)
            return await original(task_id, **values)

        monkeypatch.setattr(runtime.store, "update_task", slow_update)
        create_agent(client, admin)
        task = submit_task(client, admin)
        assert entered.wait(5)  # accepted by the agent, DB write still pending
        assert client.get(f"{API}/agents/eng_1", headers=admin).json()["data"]["active_tasks"]

        assert (
            client.post(f"{API}/tasks/{task['task_id']}/cancel", headers=admin).status_code == 200
        )

        agent = client.get(f"{API}/agents/eng_1", headers=admin).json()["data"]
        assert agent["active_tasks"] == [] and agent["queued_tasks"] == 0
        assert client.delete(f"{API}/agents/eng_1", headers=admin).status_code == 204

    def test_cannot_delete_agent_with_active_work(self, client, admin, monkeypatch):
        async def hang(self, context):
            await asyncio.sleep(30)

        monkeypatch.setattr(DataEngineerAgent, "_run_quality_check", hang)
        create_agent(client, admin)
        task = submit_task(client, admin)
        assert client.delete(f"{API}/agents/eng_1", headers=admin).status_code == 409
        client.post(f"{API}/tasks/{task['task_id']}/cancel", headers=admin)
        assert client.delete(f"{API}/agents/eng_1", headers=admin).status_code == 204

    def test_shutdown_interrupts_long_tasks_and_records_it(self, make_client, admin, monkeypatch):
        async def hang(self, context):
            await asyncio.sleep(30)

        monkeypatch.setattr(DataEngineerAgent, "_run_quality_check", hang)
        first = make_client(shutdown_timeout=0.2)
        create_agent(first, admin)
        task_id = submit_task(first, admin)["task_id"]
        wait_for(lambda: task_state(first, admin, task_id), lambda t: t["status"] == "in_progress")
        first.__exit__(None, None, None)  # graceful shutdown

        second = make_client()
        state = task_state(second, admin, task_id)
        assert state["status"] == "failed" and "shutdown" in state["error"].lower()
