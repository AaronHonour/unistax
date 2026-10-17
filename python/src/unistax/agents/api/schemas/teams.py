"""Team schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from unistax.agents.api.schemas.common import IdStr, NameStr


class CreateTeamRequest(BaseModel):
    name: NameStr
    team_type: str = Field(
        "functional", description="division | functional | cross_functional | task_force"
    )
    parent_team_id: IdStr | None = None
    leader_id: IdStr | None = None


class UpdateTeamRequest(BaseModel):
    name: NameStr | None = None
    parent_team_id: IdStr | None = Field(
        None, description="New parent; send an explicit null to make this a root team"
    )


class TeamResponse(BaseModel):
    team_id: str
    name: str
    team_type: str
    parent_team_id: str | None
    leader_id: str | None
    member_ids: list[str]
    child_team_ids: list[str]
