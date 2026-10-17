"""Metrics and health schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class AgentMetricsResponse(BaseModel):
    agent_id: str
    persona: str
    state: str
    metrics: dict[str, Any]
    queued_tasks: int


class SystemMetricsResponse(BaseModel):
    uptime_seconds: float
    agents_total: int
    agents_by_state: dict[str, int]
    agents_by_persona: dict[str, int]
    teams_total: int
    tasks_by_status: dict[str, int]
    tasks_running_now: int
    workflows_by_status: dict[str, int]
    workflows_running_now: int
    knowledge_nodes: int
    knowledge_edges: int
    websocket_connections: int
