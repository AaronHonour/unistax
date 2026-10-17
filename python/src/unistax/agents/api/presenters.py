"""Convert domain objects and records into API response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from unistax.agents.api.db.models import (
    KnowledgeEdgeRecord,
    TaskRecord,
    WorkflowRecord,
)
from unistax.agents.api.db.store import as_utc, duration_seconds
from unistax.agents.api.runtime import AgentRuntime
from unistax.agents.api.schemas import (
    AgentResponse,
    KnowledgeEdgeResponse,
    KnowledgeNodeResponse,
    TaskResponse,
    TeamResponse,
    WorkflowResponse,
    WorkflowStatusResponse,
    WorkflowStepResponse,
)
from unistax.agents.base import Agent
from unistax.agents.intelligence.knowledge_graph import KnowledgeEdge, KnowledgeNode, RelationType
from unistax.agents.team import Team


def agent_response(runtime: AgentRuntime, agent: Agent) -> AgentResponse:
    task_types = getattr(agent, "TASK_TYPES", None)
    return AgentResponse(
        agent_id=agent.agent_id,
        persona=agent.persona,
        state=agent.state.value,
        team_id=agent.team_id,
        skills={name: skill.proficiency for name, skill in agent.skills.items()},
        max_concurrent_tasks=agent.max_concurrent_tasks,
        active_tasks=[t.id for t in agent.current_tasks],
        queued_tasks=runtime.executor.load(agent.agent_id),
        supported_task_types=sorted(task_types) if task_types else [],
        metrics=agent.get_metrics(),
    )


def task_response(record: TaskRecord) -> TaskResponse:
    return TaskResponse(
        task_id=record.id,
        task_type=record.type,
        description=record.description or "",
        status=record.status,
        priority=record.priority,
        assigned_agent=record.assigned_agent,
        required_skills=record.required_skills or {},
        context=record.context or {},
        result=record.result,
        error=record.error,
        submitted_by=record.submitted_by,
        created_at=as_utc(record.created_at),  # type: ignore[arg-type]
        started_at=as_utc(record.started_at),
        completed_at=as_utc(record.completed_at),
        duration_seconds=duration_seconds(record.started_at, record.completed_at),
    )


def team_response(runtime: AgentRuntime, team: Team) -> TeamResponse:
    return TeamResponse(
        team_id=team.id,
        name=team.name,
        team_type=team.team_type.value,
        parent_team_id=team.parent_team_id,
        leader_id=team.leader_id,
        member_ids=sorted(team.members),
        child_team_ids=sorted(team.child_teams),
    )


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def workflow_response(record: WorkflowRecord) -> WorkflowResponse:
    progress: dict[str, Any] = record.progress or {}
    steps = []
    for d in record.definition:
        state = progress.get(d["step_id"], {})
        steps.append(
            WorkflowStepResponse(
                step_id=d["step_id"],
                name=d["name"],
                task_type=d["task_type"],
                status=state.get("status", "pending"),
                dependencies=d["dependencies"],
                agent_persona=d.get("agent_persona"),
                agent_id=state.get("agent_id") or d.get("agent_id"),
                retry_count=state.get("retry_count", 0),
                result=state.get("result"),
                error=state.get("error"),
                started_at=_parse(state.get("started_at")),
                completed_at=_parse(state.get("completed_at")),
            )
        )
    return WorkflowResponse(
        workflow_id=record.id,
        name=record.name,
        description=record.description or "",
        status=record.status,
        submitted_by=record.submitted_by,
        steps=steps,
        created_at=as_utc(record.created_at),  # type: ignore[arg-type]
        started_at=as_utc(record.started_at),
        completed_at=as_utc(record.completed_at),
        duration_seconds=duration_seconds(record.started_at, record.completed_at),
    )


def workflow_status_response(record: WorkflowRecord) -> WorkflowStatusResponse:
    states = [s.get("status") for s in (record.progress or {}).values()]
    total = len(record.definition)
    completed = states.count("completed")
    return WorkflowStatusResponse(
        workflow_id=record.id,
        status=record.status,
        total_steps=total,
        completed_steps=completed,
        failed_steps=states.count("failed"),
        skipped_steps=states.count("skipped"),
        running_steps=[
            step_id
            for step_id, s in (record.progress or {}).items()
            if s.get("status") in ("ready", "assigned", "running")
        ],
        progress_percent=round(completed / total * 100, 1) if total else 0.0,
    )


def node_response(node: KnowledgeNode) -> KnowledgeNodeResponse:
    return KnowledgeNodeResponse(
        node_id=node.id,
        node_type=node.node_type.value,
        properties=node.properties,
        created_by=node.created_by,
        created_at=as_utc(node.created_at),  # type: ignore[arg-type]
        updated_at=as_utc(node.updated_at),  # type: ignore[arg-type]
    )


def edge_response(edge: KnowledgeEdge | KnowledgeEdgeRecord) -> KnowledgeEdgeResponse:
    relation = (
        edge.relation_type.value
        if isinstance(edge.relation_type, RelationType)
        else str(edge.relation_type)
    )
    return KnowledgeEdgeResponse(
        source_id=edge.source_id,
        target_id=edge.target_id,
        relation_type=relation,
        properties=edge.properties or {},
        weight=edge.weight,
        created_by=edge.created_by,
        created_at=as_utc(edge.created_at),  # type: ignore[arg-type]
    )
