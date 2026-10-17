"""Initial schema for the agent API.

Tables that already exist are left alone, so a database that was created by the
earlier ``create_all`` start-up path is adopted as-is rather than failing.

Revision ID: 0001
Revises:
"""

from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def _create(name: str, *columns: sa.Column[Any], indexes: tuple[str, ...] = ()) -> None:
    if sa.inspect(op.get_bind()).has_table(name):
        return
    op.create_table(name, *columns)
    for column in indexes:
        op.create_index(op.f(f"ix_{name}_{column}"), name, [column])


def upgrade() -> None:
    _create(
        "agent_api_agents",
        sa.Column("agent_id", sa.String(64), primary_key=True),
        sa.Column("persona", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=True),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column("max_concurrent_tasks", sa.Integer(), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
    )
    _create(
        "agent_api_teams",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("team_type", sa.String(32), nullable=False),
        sa.Column("parent_team_id", sa.String(64), nullable=True),
        sa.Column("leader_id", sa.String(64), nullable=True),
        sa.Column("created_at", TZ, nullable=False),
    )
    _create(
        "agent_api_tasks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("required_skills", sa.JSON(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("assigned_agent", sa.String(64), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("submitted_by", sa.String(200), nullable=True),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("started_at", TZ, nullable=True),
        sa.Column("completed_at", TZ, nullable=True),
        indexes=("type", "status", "assigned_agent", "created_at"),
    )
    _create(
        "agent_api_workflows",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("progress", sa.JSON(), nullable=False),
        sa.Column("submitted_by", sa.String(200), nullable=True),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("started_at", TZ, nullable=True),
        sa.Column("completed_at", TZ, nullable=True),
        indexes=("status", "created_at"),
    )
    _create(
        "agent_api_knowledge_nodes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("node_type", sa.String(32), nullable=False),
        sa.Column("properties", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=True),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("updated_at", TZ, nullable=False),
        indexes=("node_type",),
    )
    _create(
        "agent_api_knowledge_edges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("properties", sa.JSON(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=True),
        sa.Column("created_at", TZ, nullable=False),
        indexes=("source_id", "target_id"),
    )


def downgrade() -> None:
    for name in (
        "agent_api_knowledge_edges",
        "agent_api_knowledge_nodes",
        "agent_api_workflows",
        "agent_api_tasks",
        "agent_api_teams",
        "agent_api_agents",
    ):
        op.drop_table(name)
