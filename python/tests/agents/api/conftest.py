"""Shared fixtures for the agent API tests."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable, Iterator
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from unistax.agents.api import AgentAPISettings, Role, create_access_token, create_agent_api
from unistax.agents.api.db.database import Database
from unistax.agents.api.db.models import ApiBase

SECRET = "test-secret-" + "x" * 32
API = "/api/v1"

pytestmark = pytest.mark.api


# Set to run the whole suite against another database (e.g. PostgreSQL):
#   AGENT_API_TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host/db pytest tests/agents/api
EXTERNAL_DATABASE_URL = os.environ.get("AGENT_API_TEST_DATABASE_URL")


async def _reset_database(url: str) -> None:
    db = Database(url)
    async with db.engine.begin() as conn:
        await conn.run_sync(ApiBase.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS agent_api_alembic_version"))
    await db.dispose()


@pytest.fixture
def settings(tmp_path) -> AgentAPISettings:
    if EXTERNAL_DATABASE_URL:
        asyncio.run(_reset_database(EXTERNAL_DATABASE_URL))
    return AgentAPISettings(
        database_url=EXTERNAL_DATABASE_URL or f"sqlite+aiosqlite:///{tmp_path}/agents.db",
        jwt_secret=SECRET,
        rate_limit=10_000,
        expensive_rate_limit=10_000,
        shutdown_timeout=2.0,
    )


@pytest.fixture
def make_client(settings) -> Iterator[Callable[..., TestClient]]:
    """Factory so tests can start several apps against one database (restart tests)."""
    clients: list[TestClient] = []

    def factory(**overrides) -> TestClient:
        client = TestClient(create_agent_api(replace(settings, **overrides)))
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for client in reversed(clients):
        try:
            client.__exit__(None, None, None)
        except Exception:
            pass


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


def headers_for(settings: AgentAPISettings, role: Role | str, subject: str = "tester") -> dict:
    return {"Authorization": f"Bearer {create_access_token(settings, subject, role)}"}


@pytest.fixture
def admin(settings) -> dict:
    return headers_for(settings, Role.ADMIN, "admin-user")


@pytest.fixture
def operator(settings) -> dict:
    return headers_for(settings, Role.OPERATOR, "operator-user")


@pytest.fixture
def viewer(settings) -> dict:
    return headers_for(settings, Role.VIEWER, "viewer-user")


def wait_for(
    fetch: Callable[[], dict], done: Callable[[dict], bool], timeout: float = 10.0
) -> dict:
    """Poll until ``done(fetch())`` or fail with the last value."""
    deadline = time.monotonic() + timeout
    value = fetch()
    while not done(value):
        if time.monotonic() > deadline:
            raise AssertionError(f"Timed out waiting; last value: {value}")
        time.sleep(0.03)
        value = fetch()
    return value


def create_agent(client, admin, agent_id="eng_1", persona="data_engineer", **extra) -> dict:
    response = client.post(
        f"{API}/agents", json={"agent_id": agent_id, "persona": persona, **extra}, headers=admin
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def submit_task(client, headers, task_type="quality_check", **extra) -> dict:
    body = {"task_type": task_type, "context": {"table": "t"}, **extra}
    response = client.post(f"{API}/tasks", json=body, headers=headers)
    assert response.status_code == 202, response.text
    return response.json()["data"]


def task_state(client, headers, task_id) -> dict:
    return client.get(f"{API}/tasks/{task_id}", headers=headers).json()["data"]


TERMINAL = ("completed", "failed", "cancelled")


def wait_task(client, headers, task_id, timeout=10.0) -> dict:
    return wait_for(
        lambda: task_state(client, headers, task_id), lambda t: t["status"] in TERMINAL, timeout
    )
