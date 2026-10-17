"""Agent management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from unistax.agents.api.auth import Principal, require_admin, require_viewer
from unistax.agents.api.deps import Paging, Runtime
from unistax.agents.api.presenters import agent_response
from unistax.agents.api.schemas import (
    AgentResponse,
    CreateAgentRequest,
    UpdateAgentRequest,
    paginate,
)
from unistax.agents.api.services.agents import resolve_persona, to_skills
from unistax.agents.base import Agent
from unistax.api import APIResponse, PaginatedResponse

router = APIRouter(prefix="/agents", tags=["Agent Management"])


def _get_agent(runtime: Runtime, agent_id: str) -> Agent:
    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Agent '{agent_id}' not found")
    return agent


def _require_team(runtime: Runtime, team_id: str | None) -> None:
    if team_id and runtime.registry.get_team(team_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Team '{team_id}' not found")


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[AgentResponse],
    summary="Create agent",
)
async def create_agent(
    body: CreateAgentRequest,
    runtime: Runtime,
    _: Principal = Depends(require_admin),
) -> APIResponse[AgentResponse]:
    persona = resolve_persona(body.persona)
    if persona is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown persona '{body.persona}'"
        )
    if runtime.registry.get(body.agent_id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Agent '{body.agent_id}' already exists")
    _require_team(runtime, body.team_id)

    agent = runtime.new_agent(
        agent_id=body.agent_id,
        persona=persona,
        team_id=body.team_id,
        skills=body.skills,
        max_concurrent_tasks=body.max_concurrent_tasks,
    )
    runtime.registry.register(agent)
    try:
        await runtime.save_agent(agent)
    except Exception:
        runtime.registry.unregister(agent.agent_id)
        raise
    return APIResponse(data=agent_response(runtime, agent), message="Agent created")


@router.get(
    "",
    response_model=PaginatedResponse[AgentResponse],
    summary="List agents",
    dependencies=[Depends(require_viewer)],
)
async def list_agents(
    runtime: Runtime,
    paging: Paging,
    persona: str | None = Query(None),
    team_id: str | None = Query(None),
    state: str | None = Query(None),
) -> PaginatedResponse[Any]:
    agents = sorted(runtime.registry.agents.values(), key=lambda a: a.agent_id)
    if persona:
        canonical = resolve_persona(persona) or persona
        agents = [a for a in agents if a.persona == canonical]
    if team_id:
        agents = [a for a in agents if a.team_id == team_id]
    if state:
        agents = [a for a in agents if a.state.value == state]

    page = agents[paging.offset : paging.offset + paging.page_size]
    return paginate(
        AgentResponse,
        [agent_response(runtime, a) for a in page],
        paging.page,
        paging.page_size,
        len(agents),
    )


@router.get(
    "/{agent_id}",
    response_model=APIResponse[AgentResponse],
    summary="Get agent",
    dependencies=[Depends(require_viewer)],
)
async def get_agent(agent_id: str, runtime: Runtime) -> APIResponse[AgentResponse]:
    return APIResponse(data=agent_response(runtime, _get_agent(runtime, agent_id)))


@router.patch(
    "/{agent_id}",
    response_model=APIResponse[AgentResponse],
    summary="Update agent",
)
async def update_agent(
    agent_id: str,
    body: UpdateAgentRequest,
    runtime: Runtime,
    _: Principal = Depends(require_admin),
) -> APIResponse[AgentResponse]:
    agent = _get_agent(runtime, agent_id)
    fields = body.model_fields_set

    if "team_id" in fields:
        _require_team(runtime, body.team_id)
    if body.skills is not None and not body.skills:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "skills must not be empty")

    runtime.registry.update_agent(
        agent_id,
        team_id=body.team_id,
        set_team="team_id" in fields,
        skills=to_skills(body.skills) if body.skills is not None else None,
    )
    if body.max_concurrent_tasks is not None:
        agent.max_concurrent_tasks = body.max_concurrent_tasks
        runtime.executor.reset_slots(agent_id)

    await runtime.save_agent(agent)
    return APIResponse(data=agent_response(runtime, agent), message="Agent updated")


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete agent",
)
async def delete_agent(
    agent_id: str, runtime: Runtime, _: Principal = Depends(require_admin)
) -> Response:
    agent = _get_agent(runtime, agent_id)
    if agent.current_tasks or runtime.executor.load(agent_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Agent has queued or running tasks; cancel them first"
        )
    runtime.registry.unregister(agent_id)
    runtime.executor.reset_slots(agent_id)
    await runtime.store.delete_agent(agent_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
