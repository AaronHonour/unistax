"""Agent discovery endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from unistax.agents.api.auth import require_viewer
from unistax.agents.api.deps import Runtime
from unistax.agents.api.presenters import agent_response
from unistax.agents.api.schemas import AgentResponse
from unistax.agents.api.schemas.common import SkillsMixin, TypeStr
from unistax.agents.api.services.agents import resolve_persona
from unistax.agents.api.services.assignment import rank_agents
from unistax.agents.base import Task
from unistax.api import APIResponse

router = APIRouter(
    prefix="/discovery", tags=["Agent Discovery"], dependencies=[Depends(require_viewer)]
)


class TaskMatchRequest(SkillsMixin):
    task_type: TypeStr
    required_skills: dict[str, float] | None = None


class AgentMatch(BaseModel):
    agent_id: str
    persona: str
    confidence: float
    queued_tasks: int


@router.get(
    "/by-persona/{persona}",
    response_model=APIResponse[list[AgentResponse]],
    summary="Find agents by persona",
)
async def by_persona(persona: str, runtime: Runtime) -> APIResponse[list[AgentResponse]]:
    agents = runtime.registry.find_by_persona(resolve_persona(persona) or persona)
    return APIResponse(
        data=[agent_response(runtime, a) for a in sorted(agents, key=lambda a: a.agent_id)]
    )


@router.get(
    "/by-skill", response_model=APIResponse[list[AgentResponse]], summary="Find agents by skill"
)
async def by_skill(
    runtime: Runtime,
    skill: str = Query(..., min_length=1, max_length=64),
    min_proficiency: float = Query(0.0, ge=0.0, le=1.0),
) -> APIResponse[list[AgentResponse]]:
    agents = runtime.registry.find_by_skill(skill, min_proficiency=min_proficiency)
    return APIResponse(
        data=[agent_response(runtime, a) for a in sorted(agents, key=lambda a: a.agent_id)]
    )


@router.get(
    "/by-team/{team_id}",
    response_model=APIResponse[list[AgentResponse]],
    summary="Find agents by team",
)
async def by_team(team_id: str, runtime: Runtime) -> APIResponse[list[AgentResponse]]:
    agents = runtime.registry.find_by_team(team_id)
    return APIResponse(
        data=[agent_response(runtime, a) for a in sorted(agents, key=lambda a: a.agent_id)]
    )


@router.post(
    "/for-task",
    response_model=APIResponse[list[AgentMatch]],
    summary="Rank agents able to run a task",
    description="Same matching the scheduler uses when a task is submitted without an agent_id.",
)
async def for_task(body: TaskMatchRequest, runtime: Runtime) -> APIResponse[list[AgentMatch]]:
    task = Task(type=body.task_type, required_skills=body.required_skills or {})
    ranked = rank_agents(runtime.registry, task, runtime.executor.load)
    return APIResponse(
        data=[
            AgentMatch(
                agent_id=c.agent.agent_id,
                persona=c.agent.persona,
                confidence=round(c.confidence, 4),
                queued_tasks=c.load,
            )
            for c in ranked
        ]
    )


@router.get(
    "/statistics", response_model=APIResponse[dict[str, Any]], summary="Registry statistics"
)
async def statistics(runtime: Runtime) -> APIResponse[dict[str, Any]]:
    return APIResponse(data=runtime.registry.get_registry_stats())
