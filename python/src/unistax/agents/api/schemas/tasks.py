"""Task schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from unistax.agents.api.schemas.common import IdStr, SkillsMixin, TypeStr


class TaskRequest(SkillsMixin):
    task_type: TypeStr = Field(..., description="e.g. build_pipeline, analyze_data, train_model")
    description: str = Field("", max_length=2000)
    context: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(5, ge=1, le=10)
    required_skills: dict[str, float] | None = None
    agent_id: IdStr | None = Field(None, description="Pin to an agent; otherwise auto-assigned")


class TaskResponse(BaseModel):
    task_id: str
    task_type: str
    description: str
    status: str
    priority: int
    assigned_agent: str | None
    required_skills: dict[str, float]
    context: dict[str, Any]
    result: Any | None
    error: str | None
    submitted_by: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: float | None
