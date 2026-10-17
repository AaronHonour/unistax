"""Workflow schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from unistax.agents.api.schemas.common import IdStr, NameStr, SkillsMixin, TypeStr


class WorkflowStepRequest(SkillsMixin):
    step_id: IdStr
    name: NameStr | None = None
    task_type: TypeStr
    description: str = Field("", max_length=2000)
    context: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(5, ge=1, le=10)
    required_skills: dict[str, float] | None = None
    dependencies: list[IdStr] = Field(default_factory=list)
    agent_persona: str | None = Field(None, description="Required persona, e.g. data_engineer")
    agent_id: IdStr | None = None
    max_retries: int = Field(3, ge=1, le=10)

    @model_validator(mode="after")
    def _needs_target(self) -> WorkflowStepRequest:
        if not self.agent_persona and not self.agent_id:
            raise ValueError("Each step needs an agent_persona or an agent_id")
        return self


class CreateWorkflowRequest(BaseModel):
    name: NameStr
    description: str = Field("", max_length=2000)
    steps: list[WorkflowStepRequest] = Field(..., min_length=1, max_length=200)


class WorkflowStepResponse(BaseModel):
    step_id: str
    name: str
    task_type: str
    status: str
    dependencies: list[str]
    agent_persona: str | None
    agent_id: str | None
    retry_count: int
    result: Any | None
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None


class WorkflowResponse(BaseModel):
    workflow_id: str
    name: str
    description: str
    status: str
    submitted_by: str | None
    steps: list[WorkflowStepResponse]
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: float | None


class WorkflowStatusResponse(BaseModel):
    workflow_id: str
    status: str
    total_steps: int
    completed_steps: int
    failed_steps: int
    skipped_steps: int
    running_steps: list[str]
    progress_percent: float
