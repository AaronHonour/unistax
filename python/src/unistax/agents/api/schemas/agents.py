"""Agent schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from unistax.agents.api.schemas.common import IdStr, SkillsMixin


class CreateAgentRequest(SkillsMixin):
    agent_id: IdStr
    persona: str = Field(
        ..., description="data_engineer | data_analyst | data_scientist | data_steward"
    )
    team_id: IdStr | None = None
    skills: dict[str, float] | None = Field(
        None, description="Override default skills (name -> proficiency 0..1)"
    )
    max_concurrent_tasks: int = Field(3, ge=1, le=50)


class UpdateAgentRequest(SkillsMixin):
    team_id: IdStr | None = None
    skills: dict[str, float] | None = None
    max_concurrent_tasks: int | None = Field(None, ge=1, le=50)


class AgentResponse(BaseModel):
    agent_id: str
    persona: str
    state: str
    team_id: str | None
    skills: dict[str, float]
    max_concurrent_tasks: int
    active_tasks: list[str]
    queued_tasks: int
    supported_task_types: list[str]
    metrics: dict[str, Any]
