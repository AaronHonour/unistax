"""State survives restarts; interrupted work is surfaced, not silently lost."""

from __future__ import annotations

import pytest

from .conftest import API, create_agent, submit_task, wait_task

pytestmark = pytest.mark.api


def test_agents_teams_and_tasks_survive_restart(make_client, admin):
    first = make_client()
    team = first.post(
        f"{API}/teams", json={"name": "Platform", "team_type": "division"}, headers=admin
    ).json()["data"]
    child = first.post(
        f"{API}/teams", json={"name": "Eng", "parent_team_id": team["team_id"]}, headers=admin
    ).json()["data"]
    create_agent(
        first,
        admin,
        "eng_1",
        team_id=child["team_id"],
        skills={"sql": 0.77},
        max_concurrent_tasks=4,
    )
    task_id = submit_task(first, admin)["task_id"]
    wait_task(first, admin, task_id)
    first.__exit__(None, None, None)

    second = make_client()
    agent = second.get(f"{API}/agents/eng_1", headers=admin).json()["data"]
    assert agent["team_id"] == child["team_id"]
    assert agent["skills"] == {"sql": 0.77}
    assert agent["max_concurrent_tasks"] == 4

    restored = second.get(f"{API}/teams/{team['team_id']}", headers=admin).json()["data"]
    assert restored["child_team_ids"] == [child["team_id"]]
    assert second.get(f"{API}/teams/{child['team_id']}/members", headers=admin).json()["data"] == [
        "eng_1"
    ]

    kept = second.get(f"{API}/tasks/{task_id}", headers=admin).json()["data"]
    assert kept["status"] == "completed" and kept["result"]["status"] == "success"

    # The restored agent is fully functional.
    assert wait_task(second, admin, submit_task(second, admin)["task_id"])["status"] == "completed"


def test_deleted_agents_stay_deleted(make_client, admin):
    first = make_client()
    create_agent(first, admin)
    first.delete(f"{API}/agents/eng_1", headers=admin)
    first.__exit__(None, None, None)
    assert make_client().get(f"{API}/agents/eng_1", headers=admin).status_code == 404


def test_restore_can_be_disabled(make_client, admin):
    first = make_client()
    create_agent(first, admin)
    first.__exit__(None, None, None)
    assert (
        make_client(restore_on_start=False).get(f"{API}/agents", headers=admin).json()["total"] == 0
    )


def test_tasks_in_flight_at_crash_are_marked_failed_on_restart(make_client, admin):
    first = make_client()
    create_agent(first, admin)
    store = first.app.state.runtime.store

    async def plant():
        await store.create_task(
            id="stuck-1", type="quality_check", status="in_progress", assigned_agent="eng_1"
        )
        await store.create_task(
            id="stuck-2", type="quality_check", status="pending", assigned_agent="eng_1"
        )

    first.portal.call(plant)  # simulate a hard crash that left active rows behind
    first.__exit__(None, None, None)

    second = make_client()
    for task_id in ("stuck-1", "stuck-2"):
        state = second.get(f"{API}/tasks/{task_id}", headers=admin).json()["data"]
        assert state["status"] == "failed"
        assert "restart" in state["error"]
