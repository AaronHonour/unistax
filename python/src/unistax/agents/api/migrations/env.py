"""Alembic environment.

Migrations are always run through ``unistax.agents.api.migrate``, which passes in the
live (sync-adapted) connection. There is deliberately no offline/URL mode.
"""

from alembic import context

from unistax.agents.api.db.models import ApiBase

config = context.config
target_metadata = ApiBase.metadata

# A dedicated history table so this never collides with a host application's own
# Alembic history in the same database.
VERSION_TABLE = "agent_api_alembic_version"


def include_object(  # noqa: D103
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    # Only manage our own tables; ignore anything else living in the database.
    if type_ == "table" and reflected and name not in target_metadata.tables:
        return False
    return True


def run_migrations_online() -> None:
    """Run migrations on the connection supplied by the caller."""
    connection = config.attributes.get("connection")
    if connection is None:
        raise RuntimeError(
            "Run migrations with `python -m unistax.agents.api.migrate` "
            "(or unistax.agents.api.migrate.upgrade)."
        )
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Offline (SQL script) mode is not supported for the agent API migrations.")

run_migrations_online()
