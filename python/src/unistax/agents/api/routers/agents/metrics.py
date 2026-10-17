"""Metrics endpoints (JSON and Prometheus text format)."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Mapping

from fastapi import APIRouter, Depends, HTTPException, Response, status

from unistax.agents.api.auth import require_viewer
from unistax.agents.api.db.models import TaskRecord, WorkflowRecord
from unistax.agents.api.deps import Runtime
from unistax.agents.api.schemas import AgentMetricsResponse, SystemMetricsResponse
from unistax.api import APIResponse

router = APIRouter(
    prefix="/metrics", tags=["Metrics & Monitoring"], dependencies=[Depends(require_viewer)]
)


async def _system_metrics(runtime: Runtime) -> SystemMetricsResponse:
    agents = list(runtime.registry.agents.values())
    stats = runtime.knowledge_graph.get_graph_statistics()
    return SystemMetricsResponse(
        uptime_seconds=round(time.time() - runtime.started_at, 1),
        agents_total=len(agents),
        agents_by_state=dict(Counter(a.state.value for a in agents)),
        agents_by_persona=dict(Counter(a.persona for a in agents)),
        teams_total=len(runtime.registry.team_hierarchy.teams),
        tasks_by_status=await runtime.store.count_by_status(TaskRecord),
        tasks_running_now=runtime.executor.running_count,
        workflows_by_status=await runtime.store.count_by_status(WorkflowRecord),
        workflows_running_now=runtime.workflows.running_count,
        knowledge_nodes=stats["total_nodes"],
        knowledge_edges=stats["total_edges"],
        websocket_connections=runtime.hub.connection_count,
    )


@router.get("/system", response_model=APIResponse[SystemMetricsResponse], summary="System metrics")
async def system_metrics(runtime: Runtime) -> APIResponse[SystemMetricsResponse]:
    return APIResponse(data=await _system_metrics(runtime))


@router.get(
    "/agents/{agent_id}", response_model=APIResponse[AgentMetricsResponse], summary="Agent metrics"
)
async def agent_metrics(agent_id: str, runtime: Runtime) -> APIResponse[AgentMetricsResponse]:
    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Agent '{agent_id}' not found")
    return APIResponse(
        data=AgentMetricsResponse(
            agent_id=agent.agent_id,
            persona=agent.persona,
            state=agent.state.value,
            metrics=agent.get_metrics(),
            queued_tasks=runtime.executor.load(agent_id),
        )
    )


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


@router.get("/prometheus", summary="Prometheus exposition format", response_class=Response)
async def prometheus(runtime: Runtime) -> Response:
    m = await _system_metrics(runtime)
    lines: list[str] = []

    def gauge(
        name: str, help_text: str, samples: Mapping[str, float] | float, label: str | None = None
    ) -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        if isinstance(samples, Mapping):
            for key, value in sorted(samples.items()):
                lines.append(f'{name}{{{label}="{_label(key)}"}} {value}')
        else:
            lines.append(f"{name} {samples}")

    gauge("agent_api_uptime_seconds", "Seconds since the service started", m.uptime_seconds)
    gauge("agent_api_agents", "Registered agents by persona", m.agents_by_persona, "persona")
    gauge("agent_api_agents_by_state", "Registered agents by state", m.agents_by_state, "state")
    gauge("agent_api_teams", "Teams", m.teams_total)
    gauge("agent_api_tasks", "Stored tasks by status", m.tasks_by_status, "status")
    gauge("agent_api_tasks_running", "Tasks queued or running in this process", m.tasks_running_now)
    gauge("agent_api_workflows", "Stored workflows by status", m.workflows_by_status, "status")
    gauge(
        "agent_api_workflows_running", "Workflows running in this process", m.workflows_running_now
    )
    gauge("agent_api_knowledge_nodes", "Knowledge graph nodes", m.knowledge_nodes)
    gauge("agent_api_knowledge_edges", "Knowledge graph edges", m.knowledge_edges)
    gauge("agent_api_websocket_connections", "Open WebSocket connections", m.websocket_connections)

    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
