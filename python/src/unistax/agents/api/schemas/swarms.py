"""Swarm schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

ModelName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:\-\[\]]{0,63}$")]


class CreateSwarmRequest(BaseModel):
    goal: str = Field(
        ..., min_length=10, max_length=4000, description="What the swarm should achieve"
    )
    context: str = Field(
        "",
        max_length=100_000,
        description="Source material the workers may use (treated as untrusted data)",
    )
    max_subtasks: int | None = Field(
        None, ge=1, le=20, description="Cap on planned steps (server limit applies)"
    )
    review: bool = Field(False, description="Add a final critic step that reviews the answer")
    model: ModelName | None = Field(
        None, description="Model alias for every call, e.g. sonnet, haiku, opus"
    )
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None


class SwarmStepResponse(BaseModel):
    step_id: str
    role: str
    title: str
    status: str
    depends_on: list[str]
    output: str | None = None
    structured: Any | None = None
    error: str | None = None
    usage: dict[str, int] | None = None


class SwarmSummary(BaseModel):
    swarm_id: str
    goal: str
    status: str
    workflow_id: str | None
    error: str | None
    submitted_by: str | None
    usage: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: float | None


class SwarmResponse(SwarmSummary):
    plan_rationale: str | None = None
    steps: list[SwarmStepResponse] = []
    final: str | None = None
    review: Any | None = None
    partial: bool = False
