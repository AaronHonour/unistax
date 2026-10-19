"""Swarm runs: a goal, its plan, its workflow and its result.

Revision ID: 0002
Revises: 0001
"""

from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)
TABLE = "agent_api_swarms"


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table(TABLE):
        return
    columns: list[Any] = [
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=True),
        sa.Column("workflow_id", sa.String(64), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("submitted_by", sa.String(200), nullable=True),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("started_at", TZ, nullable=True),
        sa.Column("completed_at", TZ, nullable=True),
    ]
    op.create_table(TABLE, *columns)
    op.create_index(op.f(f"ix_{TABLE}_status"), TABLE, ["status"])
    op.create_index(op.f(f"ix_{TABLE}_created_at"), TABLE, ["created_at"])


def downgrade() -> None:
    op.drop_table(TABLE)
