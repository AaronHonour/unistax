"""Apply and inspect the agent API database migrations.

Command line::

    python -m unistax.agents.api.migrate upgrade    # apply pending migrations
    python -m unistax.agents.api.migrate current    # show the database's revision
    python -m unistax.agents.api.migrate check      # exit 1 unless the schema is current
    python -m unistax.agents.api.migrate downgrade  # revert the most recent migration

The database comes from ``UNISTAX_AGENT_API_DATABASE_URL``. Production deployments
should set ``UNISTAX_AGENT_API_AUTO_MIGRATE=false`` and run ``upgrade`` as a
deploy step, so the service never changes the schema on its own.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Connection

from unistax.agents.api.db.database import Database
from unistax.agents.api.db.models import ApiBase
from unistax.agents.api.settings import AgentAPISettings

VERSION_TABLE = "agent_api_alembic_version"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class SchemaOutOfDate(RuntimeError):
    """The database schema is not at the revision this version of the code expects."""


def _config(connection: Connection | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def head_revision() -> str:
    """The newest revision shipped with this version of the code."""
    head = ScriptDirectory.from_config(_config()).get_current_head()
    assert head is not None
    return head


def _current(connection: Connection) -> str | None:
    context = MigrationContext.configure(connection, opts={"version_table": VERSION_TABLE})
    return context.get_current_revision()


async def current_revision(db: Database) -> str | None:
    """The revision recorded in the database, or ``None`` if never migrated."""
    async with db.engine.connect() as conn:
        return await conn.run_sync(_current)


async def upgrade(db: Database, target: str = "head") -> None:
    """Apply migrations up to ``target`` (idempotent)."""

    def run(connection: Connection) -> None:
        command.upgrade(_config(connection), target)

    async with db.engine.begin() as conn:
        await conn.run_sync(run)


async def downgrade(db: Database, target: str = "-1") -> None:
    """Revert to ``target`` (by default, the single most recent migration)."""

    def run(connection: Connection) -> None:
        command.downgrade(_config(connection), target)

    async with db.engine.begin() as conn:
        await conn.run_sync(run)


async def missing_tables(db: Database) -> list[str]:
    """Tables the models need that the database does not have."""
    async with db.engine.connect() as conn:
        present = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
    return sorted(set(ApiBase.metadata.tables) - present)


async def ensure_current(db: Database) -> None:
    """Raise :class:`SchemaOutOfDate` unless the database is complete and at the head revision.

    Besides the recorded revision this checks that the tables really exist: dropping
    tables by hand leaves the history saying "current", which would otherwise only show
    up as errors on the first request.
    """
    current, head = await current_revision(db), head_revision()
    if current != head:
        raise SchemaOutOfDate(
            f"Database schema is at revision {current or 'none'} but this version needs "
            f"{head}. Run `python -m unistax.agents.api.migrate upgrade`, or set "
            "UNISTAX_AGENT_API_AUTO_MIGRATE=true to apply migrations at startup."
        )
    missing = await missing_tables(db)
    if missing:
        raise SchemaOutOfDate(
            f"Migration history says the schema is current but tables are missing: {missing}. "
            f"Someone dropped them by hand. Restore from backup, or drop the "
            f"{VERSION_TABLE} table and run `python -m unistax.agents.api.migrate upgrade`."
        )


async def _run(action: str) -> int:
    settings = AgentAPISettings.from_env()
    db = Database(settings.database_url)
    try:
        if action == "upgrade":
            await upgrade(db)
            print(f"Database is at revision {await current_revision(db)}")
        elif action == "downgrade":
            await downgrade(db)
            print(f"Database is at revision {await current_revision(db) or 'none'}")
        elif action == "current":
            print(await current_revision(db) or "none")
        else:  # check
            await ensure_current(db)
            print(f"OK: schema is current ({head_revision()})")
        return 0
    except SchemaOutOfDate as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        await db.dispose()


def main() -> None:
    """Command line entry point."""
    parser = argparse.ArgumentParser(description="Agent API database migrations")
    parser.add_argument("action", choices=["upgrade", "downgrade", "current", "check"])
    sys.exit(asyncio.run(_run(parser.parse_args().action)))


if __name__ == "__main__":
    main()
