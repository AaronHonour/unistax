"""Knowledge graph schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from unistax.agents.api.schemas.common import IdStr


class AddNodeRequest(BaseModel):
    node_id: IdStr
    node_type: str = Field(
        ...,
        description="dataset | pipeline | model | agent | task | insight | best_practice | issue",
    )
    properties: dict[str, Any] = Field(default_factory=dict)


class AddEdgeRequest(BaseModel):
    source_id: IdStr
    target_id: IdStr
    relation_type: str = Field(
        ...,
        description=(
            "depends_on | produces | consumes | trained_by | executed_by | "
            "related_to | similar_to | learned_from"
        ),
    )
    properties: dict[str, Any] = Field(default_factory=dict)
    weight: float = Field(1.0, ge=0.0)


class BestPracticeRequest(BaseModel):
    practice_id: IdStr
    topic: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=5000)
    related_nodes: list[IdStr] = Field(default_factory=list, max_length=100)


class IssueRequest(BaseModel):
    issue_id: IdStr
    description: str = Field(..., min_length=1, max_length=5000)
    severity: str = Field(..., pattern="^(low|medium|high|critical)$")
    affected_nodes: list[IdStr] = Field(default_factory=list, max_length=100)


class KnowledgeNodeResponse(BaseModel):
    node_id: str
    node_type: str
    properties: dict[str, Any]
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class KnowledgeEdgeResponse(BaseModel):
    source_id: str
    target_id: str
    relation_type: str
    properties: dict[str, Any]
    weight: float
    created_by: str | None
    created_at: datetime
