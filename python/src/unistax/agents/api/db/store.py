"""Persistence operations for agent API state."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select, update

from unistax.agents.api.db.database import Database
from unistax.agents.api.db.models import (
    AgentRecord,
    KnowledgeEdgeRecord,
    KnowledgeNodeRecord,
    SwarmRecord,
    TaskRecord,
    TeamRecord,
    WorkflowRecord,
    utcnow,
)

ACTIVE_TASK_STATUSES = ("pending", "assigned", "in_progress")
ACTIVE_WORKFLOW_STATUSES = ("pending", "running", "paused")


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=str)
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(value)
    return str(value)


def to_jsonable(value: Any) -> Any:
    """Convert arbitrary agent output into JSON-storable data."""
    return json.loads(json.dumps(value, default=_json_default))


class Store:
    """Thin async repository over the API tables."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # -- agents ---------------------------------------------------------
    async def save_agent(self, **values: Any) -> None:
        async with self.db.session() as s:
            await s.merge(AgentRecord(**values))

    async def delete_agent(self, agent_id: str) -> None:
        async with self.db.session() as s:
            await s.execute(delete(AgentRecord).where(AgentRecord.agent_id == agent_id))

    async def load_agents(self) -> list[AgentRecord]:
        async with self.db.session() as s:
            return list(
                (await s.scalars(select(AgentRecord).order_by(AgentRecord.created_at))).all()
            )

    # -- teams ----------------------------------------------------------
    async def save_team(self, **values: Any) -> None:
        async with self.db.session() as s:
            await s.merge(TeamRecord(**values))

    async def delete_team(self, team_id: str) -> None:
        async with self.db.session() as s:
            await s.execute(delete(TeamRecord).where(TeamRecord.id == team_id))

    async def load_teams(self) -> list[TeamRecord]:
        async with self.db.session() as s:
            return list((await s.scalars(select(TeamRecord).order_by(TeamRecord.created_at))).all())

    # -- tasks ----------------------------------------------------------
    async def create_task(self, **values: Any) -> TaskRecord:
        record = TaskRecord(**values)
        async with self.db.session() as s:
            s.add(record)
        return record

    async def update_task(self, task_id: str, **values: Any) -> None:
        async with self.db.session() as s:
            await s.execute(update(TaskRecord).where(TaskRecord.id == task_id).values(**values))

    async def get_task(self, task_id: str) -> TaskRecord | None:
        async with self.db.session() as s:
            return await s.get(TaskRecord, task_id)

    async def list_tasks(
        self,
        *,
        status: str | None = None,
        agent_id: str | None = None,
        task_type: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[TaskRecord], int]:
        filters = []
        if status:
            filters.append(TaskRecord.status == status)
        if agent_id:
            filters.append(TaskRecord.assigned_agent == agent_id)
        if task_type:
            filters.append(TaskRecord.type == task_type)
        async with self.db.session() as s:
            total = await s.scalar(select(func.count()).select_from(TaskRecord).where(*filters))
            rows = await s.scalars(
                select(TaskRecord)
                .where(*filters)
                .order_by(TaskRecord.created_at.desc(), TaskRecord.id)
                .offset(offset)
                .limit(limit)
            )
            return list(rows.all()), int(total or 0)

    async def count_by_status(
        self, model: type[TaskRecord] | type[WorkflowRecord]
    ) -> dict[str, int]:
        async with self.db.session() as s:
            rows = await s.execute(select(model.status, func.count()).group_by(model.status))
            return {status: int(count) for status, count in rows.all()}

    async def has_active_tasks_for(self, agent_id: str) -> bool:
        async with self.db.session() as s:
            count = await s.scalar(
                select(func.count())
                .select_from(TaskRecord)
                .where(
                    TaskRecord.assigned_agent == agent_id,
                    TaskRecord.status.in_(ACTIVE_TASK_STATUSES),
                )
            )
            return bool(count)

    async def fail_interrupted_tasks(self, reason: str) -> int:
        async with self.db.session() as s:
            result = await s.execute(
                update(TaskRecord)
                .where(TaskRecord.status.in_(ACTIVE_TASK_STATUSES))
                .values(status="failed", error=reason, completed_at=utcnow())
            )
            return int(cast(CursorResult[Any], result).rowcount or 0)

    # -- workflows ------------------------------------------------------
    async def create_workflow(self, **values: Any) -> WorkflowRecord:
        record = WorkflowRecord(**values)
        async with self.db.session() as s:
            s.add(record)
        return record

    async def update_workflow(self, workflow_id: str, **values: Any) -> None:
        async with self.db.session() as s:
            await s.execute(
                update(WorkflowRecord).where(WorkflowRecord.id == workflow_id).values(**values)
            )

    async def get_workflow(self, workflow_id: str) -> WorkflowRecord | None:
        async with self.db.session() as s:
            return await s.get(WorkflowRecord, workflow_id)

    async def list_workflows(
        self, *, status: str | None = None, offset: int = 0, limit: int = 50
    ) -> tuple[list[WorkflowRecord], int]:
        filters = [WorkflowRecord.status == status] if status else []
        async with self.db.session() as s:
            total = await s.scalar(select(func.count()).select_from(WorkflowRecord).where(*filters))
            rows = await s.scalars(
                select(WorkflowRecord)
                .where(*filters)
                .order_by(WorkflowRecord.created_at.desc(), WorkflowRecord.id)
                .offset(offset)
                .limit(limit)
            )
            return list(rows.all()), int(total or 0)

    async def delete_workflow(self, workflow_id: str) -> None:
        async with self.db.session() as s:
            await s.execute(delete(WorkflowRecord).where(WorkflowRecord.id == workflow_id))

    async def fail_interrupted_workflows(self, reason: str) -> int:
        in_flight = ("ready", "assigned", "running", "pending")
        async with self.db.session() as s:
            records = (
                await s.scalars(
                    select(WorkflowRecord).where(WorkflowRecord.status.in_(("running", "paused")))
                )
            ).all()
            for record in records:
                record.status = "failed"
                record.completed_at = utcnow()
                record.progress = {
                    step_id: (
                        {**step, "status": "failed", "error": reason}
                        if step.get("status") in in_flight
                        else step
                    )
                    for step_id, step in (record.progress or {}).items()
                }
            return len(records)

    # -- swarms ---------------------------------------------------------
    async def create_swarm(self, **values: Any) -> SwarmRecord:
        record = SwarmRecord(**values)
        async with self.db.session() as s:
            s.add(record)
        return record

    async def update_swarm(self, swarm_id: str, **values: Any) -> None:
        async with self.db.session() as s:
            await s.execute(update(SwarmRecord).where(SwarmRecord.id == swarm_id).values(**values))

    async def get_swarm(self, swarm_id: str) -> SwarmRecord | None:
        async with self.db.session() as s:
            return await s.get(SwarmRecord, swarm_id)

    async def list_swarms(
        self, *, status: str | None = None, offset: int = 0, limit: int = 50
    ) -> tuple[list[SwarmRecord], int]:
        filters = [SwarmRecord.status == status] if status else []
        async with self.db.session() as s:
            total = await s.scalar(select(func.count()).select_from(SwarmRecord).where(*filters))
            rows = await s.scalars(
                select(SwarmRecord)
                .where(*filters)
                .order_by(SwarmRecord.created_at.desc(), SwarmRecord.id)
                .offset(offset)
                .limit(limit)
            )
            return list(rows.all()), int(total or 0)

    async def fail_interrupted_swarms(self, reason: str) -> int:
        async with self.db.session() as s:
            result = await s.execute(
                update(SwarmRecord)
                .where(SwarmRecord.status.in_(("planning", "running")))
                .values(status="failed", error=reason, completed_at=utcnow())
            )
            return int(cast(CursorResult[Any], result).rowcount or 0)

    # -- knowledge graph ------------------------------------------------
    async def upsert_node(self, **values: Any) -> None:
        async with self.db.session() as s:
            await s.merge(KnowledgeNodeRecord(**values))

    async def add_edge(self, **values: Any) -> None:
        async with self.db.session() as s:
            s.add(KnowledgeEdgeRecord(**values))

    async def load_knowledge(self) -> tuple[list[KnowledgeNodeRecord], list[KnowledgeEdgeRecord]]:
        async with self.db.session() as s:
            nodes = (await s.scalars(select(KnowledgeNodeRecord))).all()
            edges = (
                await s.scalars(select(KnowledgeEdgeRecord).order_by(KnowledgeEdgeRecord.id))
            ).all()
            return list(nodes), list(edges)


def duration_seconds(started: datetime | None, completed: datetime | None) -> float | None:
    if started and completed:
        return max(0.0, (completed - started).total_seconds())
    return None


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc)
