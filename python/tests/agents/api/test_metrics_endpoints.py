"""Metrics, Prometheus exposition and the module entrypoint."""

from __future__ import annotations

import re

import pytest

from .conftest import API, create_agent, submit_task, wait_task

pytestmark = pytest.mark.api


def parse_prometheus(text: str) -> dict[str, float]:
    samples = {}
    for line in text.splitlines():
        if line and not line.startswith("#"):
            name, value = line.rsplit(" ", 1)
            samples[name] = float(value)
    return samples


def test_system_metrics_reflect_activity(client, admin):
    create_agent(client, admin, "eng_1")
    create_agent(client, admin, "ana_1", "analyst")
    wait_task(client, admin, submit_task(client, admin)["task_id"])

    data = client.get(f"{API}/metrics/system", headers=admin).json()["data"]

    assert data["agents_total"] == 2
    assert data["agents_by_persona"] == {"data_engineer": 1, "data_analyst": 1}
    assert data["tasks_by_status"] == {"completed": 1}
    assert data["tasks_running_now"] == 0 and data["uptime_seconds"] >= 0
    assert data["websocket_connections"] == 0 and data["websocket_pending_auth"] == 0


def test_agent_metrics(client, admin):
    create_agent(client, admin)
    wait_task(client, admin, submit_task(client, admin)["task_id"])

    data = client.get(f"{API}/metrics/agents/eng_1", headers=admin).json()["data"]
    assert data["persona"] == "data_engineer"
    assert data["metrics"]["tasks_completed"] == 1
    assert client.get(f"{API}/metrics/agents/ghost", headers=admin).status_code == 404


def test_prometheus_format_and_values(client, admin):
    create_agent(client, admin, "eng_1")
    create_agent(client, admin, "eng_2")
    create_agent(client, admin, "ana_1", "analyst")
    for _ in range(2):
        wait_task(client, admin, submit_task(client, admin)["task_id"])

    response = client.get(f"{API}/metrics/prometheus", headers=admin)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    text = response.text
    for line in text.splitlines():
        assert re.fullmatch(
            r'(# (HELP|TYPE) agent_api_\w+ .+)|(agent_api_\w+(\{\w+="[^"]*"\})? -?[0-9.e+]+)', line
        ), line
    assert text.endswith("\n")

    samples = parse_prometheus(text)
    assert samples['agent_api_agents{persona="data_engineer"}'] == 2
    assert samples['agent_api_agents{persona="data_analyst"}'] == 1
    assert samples['agent_api_tasks{status="completed"}'] == 2
    assert samples["agent_api_teams"] == 0
    assert samples["agent_api_tasks_running"] == 0
    assert samples["agent_api_websocket_connections"] == 0
    assert text.count("# TYPE agent_api_agents gauge") == 1


def test_prometheus_requires_authentication(client):
    assert client.get(f"{API}/metrics/prometheus").status_code == 401


def test_prometheus_escapes_label_values():
    from unistax.agents.api.routers.agents.metrics import _label

    assert _label('a"b\\c\nd') == 'a\\"b\\\\c\\nd'


def test_module_entrypoint_configures_uvicorn(monkeypatch):
    import sys

    import uvicorn

    from unistax.agents.api import __main__ as entry

    captured = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: captured.update(args=a, kwargs=k))
    monkeypatch.setattr(sys, "argv", ["prog", "--port", "9123", "--host", "127.0.0.1"])

    entry.main()

    assert captured["args"] == ("unistax.agents.api.app:create_agent_api",)
    kwargs = captured["kwargs"]
    assert kwargs["factory"] is True and kwargs["workers"] == 1
    assert kwargs["port"] == 9123 and kwargs["host"] == "127.0.0.1"
