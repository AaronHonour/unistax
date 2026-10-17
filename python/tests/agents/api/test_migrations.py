"""Schema migrations: they build the schema, match the models, and protect production."""

from __future__ import annotations

import sys

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from unistax.agents.api import AgentAPISettings, create_agent_api, migrate
from unistax.agents.api.db.database import Database
from unistax.agents.api.db.models import ApiBase

from .conftest import API, EXTERNAL_DATABASE_URL, SECRET, headers_for

pytestmark = pytest.mark.api

TABLES = set(ApiBase.metadata.tables)


@pytest.fixture
async def db(tmp_path):
    url = EXTERNAL_DATABASE_URL or f"sqlite+aiosqlite:///{tmp_path}/m.db"
    database = Database(url)
    async with database.engine.begin() as conn:
        await conn.run_sync(ApiBase.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS agent_api_alembic_version"))
    yield database
    await database.dispose()


async def table_names(database: Database) -> set[str]:
    async with database.engine.connect() as conn:
        return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))


async def test_upgrade_builds_the_whole_schema(db):
    assert await migrate.current_revision(db) is None

    await migrate.upgrade(db)

    assert TABLES <= await table_names(db)
    assert await migrate.current_revision(db) == migrate.head_revision()


async def test_upgrade_is_idempotent(db):
    await migrate.upgrade(db)
    await migrate.upgrade(db)
    assert await migrate.current_revision(db) == migrate.head_revision()


async def test_migrations_match_the_models(db):
    """Fails when someone changes a model without writing a migration."""
    await migrate.upgrade(db)

    def diff(conn):

        ctx = MigrationContext.configure(
            conn,
            opts={
                "compare_type": True,
                "include_object": lambda obj, name, type_, reflected, compare_to: not (
                    type_ == "table" and reflected and name not in TABLES
                ),
            },
        )
        return compare_metadata(ctx, ApiBase.metadata)

    async with db.engine.connect() as conn:
        assert await conn.run_sync(diff) == []


async def test_adopts_a_database_created_by_the_old_create_all_path(db):
    await db.create_all()  # how earlier versions created the schema, with no history table
    async with db.session() as s:
        await s.execute(
            text(
                "INSERT INTO agent_api_agents (agent_id, persona, skills, max_concurrent_tasks, created_at)"
                " VALUES ('keep-me', 'data_engineer', '{}', 3, CURRENT_TIMESTAMP)"
            )
        )

    await migrate.upgrade(db)

    assert await migrate.current_revision(db) == migrate.head_revision()
    async with db.session() as s:
        rows = (await s.execute(text("SELECT agent_id FROM agent_api_agents"))).all()
    assert [r[0] for r in rows] == ["keep-me"]  # data untouched


async def test_downgrade_removes_the_tables_and_upgrade_restores_them(db):
    await migrate.upgrade(db)
    await migrate.downgrade(db)

    assert not (TABLES & await table_names(db))
    assert await migrate.current_revision(db) is None

    await migrate.upgrade(db)
    assert TABLES <= await table_names(db)


async def test_ensure_current_demands_migration(db):
    with pytest.raises(migrate.SchemaOutOfDate, match="migrate upgrade"):
        await migrate.ensure_current(db)

    await migrate.upgrade(db)
    await migrate.ensure_current(db)


async def test_hand_dropped_tables_are_detected_instead_of_failing_later(db):
    await migrate.upgrade(db)
    async with db.session() as s:
        await s.execute(text("DROP TABLE agent_api_teams"))

    assert await migrate.missing_tables(db) == ["agent_api_teams"]
    with pytest.raises(migrate.SchemaOutOfDate, match="agent_api_teams"):
        await migrate.ensure_current(db)


def test_service_refuses_to_start_when_tables_were_dropped_by_hand(tmp_path):
    import asyncio

    from fastapi.testclient import TestClient

    url = f"sqlite+aiosqlite:///{tmp_path}/d.db"
    settings = AgentAPISettings(database_url=url, jwt_secret=SECRET)

    async def break_it() -> None:
        database = Database(url)
        await migrate.upgrade(database)
        async with database.session() as s:
            await s.execute(text("DROP TABLE agent_api_tasks"))
        await database.dispose()

    asyncio.run(break_it())
    with pytest.raises(migrate.SchemaOutOfDate, match="agent_api_tasks"):
        with TestClient(create_agent_api(settings)):
            pass


async def test_history_table_does_not_clash_with_a_host_applications_alembic(db):
    async with db.session() as s:
        await s.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await s.execute(text("INSERT INTO alembic_version VALUES ('host-app-rev')"))
    try:
        await migrate.upgrade(db)
        async with db.session() as s:
            host = (await s.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
        assert host == "host-app-rev"
    finally:
        async with db.session() as s:
            await s.execute(text("DROP TABLE alembic_version"))


async def test_foreign_tables_are_left_alone(db):
    async with db.session() as s:
        await s.execute(text("CREATE TABLE customers (id INTEGER PRIMARY KEY)"))
    try:
        await migrate.upgrade(db)
        await migrate.downgrade(db)
        assert "customers" in await table_names(db)
    finally:
        async with db.session() as s:
            await s.execute(text("DROP TABLE customers"))


class TestStartup:
    def _settings(self, db_url: str, **extra) -> AgentAPISettings:
        return AgentAPISettings(database_url=db_url, jwt_secret=SECRET, **extra)

    def test_auto_migrate_builds_a_fresh_database(self, tmp_path):
        from fastapi.testclient import TestClient

        settings = self._settings(f"sqlite+aiosqlite:///{tmp_path}/s.db")
        with TestClient(create_agent_api(settings)) as client:
            assert client.get("/health/ready").json()["status"] == "ready"
            response = client.get(f"{API}/agents", headers=headers_for(settings, "viewer"))
            assert response.status_code == 200

    def test_verify_mode_refuses_to_start_on_an_unmigrated_database(self, tmp_path):
        from fastapi.testclient import TestClient

        settings = self._settings(f"sqlite+aiosqlite:///{tmp_path}/s.db", auto_migrate=False)
        with pytest.raises(migrate.SchemaOutOfDate), TestClient(create_agent_api(settings)):
            pass

    def test_verify_mode_starts_once_migrated(self, tmp_path):
        import asyncio

        from fastapi.testclient import TestClient

        url = f"sqlite+aiosqlite:///{tmp_path}/s.db"

        async def prepare() -> None:
            database = Database(url)
            await migrate.upgrade(database)
            await database.dispose()

        asyncio.run(prepare())
        settings = self._settings(url, auto_migrate=False)
        with TestClient(create_agent_api(settings)) as client:
            assert client.get("/health/ready").status_code == 200


class TestCommandLine:
    def run_cli(self, monkeypatch, capsys, tmp_path, action: str) -> tuple[int, str, str]:
        monkeypatch.setenv("UNISTAX_AGENT_API_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/c.db")
        monkeypatch.setattr(sys, "argv", ["migrate", action])
        with pytest.raises(SystemExit) as exit_info:
            migrate.main()
        out = capsys.readouterr()
        return exit_info.value.code, out.out, out.err

    def test_check_fails_then_passes_after_upgrade(self, monkeypatch, capsys, tmp_path):
        code, _, err = self.run_cli(monkeypatch, capsys, tmp_path, "check")
        assert code == 1 and "upgrade" in err

        code, out, _ = self.run_cli(monkeypatch, capsys, tmp_path, "upgrade")
        assert code == 0 and migrate.head_revision() in out

        code, out, _ = self.run_cli(monkeypatch, capsys, tmp_path, "check")
        assert code == 0 and "OK" in out

        code, out, _ = self.run_cli(monkeypatch, capsys, tmp_path, "current")
        assert code == 0 and out.strip() == migrate.head_revision()

        code, out, _ = self.run_cli(monkeypatch, capsys, tmp_path, "downgrade")
        assert code == 0 and "none" in out


def test_head_revision_is_a_single_linear_head():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(migrate._config())
    assert len(script.get_heads()) == 1  # no diverging branches
    assert script.get_revision(migrate.head_revision()) is not None


def test_settings_use_the_new_flag_name():
    assert (
        AgentAPISettings.from_env({"UNISTAX_AGENT_API_AUTO_MIGRATE": "false"}).auto_migrate is False
    )
