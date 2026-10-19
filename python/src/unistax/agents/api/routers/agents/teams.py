"""Team management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from unistax.agents.api.auth import Principal, require_admin, require_viewer
from unistax.agents.api.deps import Paging, Runtime
from unistax.agents.api.presenters import team_response
from unistax.agents.api.schemas import (
    CreateTeamRequest,
    TeamResponse,
    UpdateTeamRequest,
    paginate,
)
from unistax.agents.team import Team, TeamType
from unistax.api import APIResponse, PaginatedResponse

router = APIRouter(prefix="/teams", tags=["Team Management"])


def _get_team(runtime: Runtime, team_id: str) -> Team:
    team = runtime.registry.get_team(team_id)
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Team '{team_id}' not found")
    return team


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[TeamResponse],
    summary="Create team",
)
async def create_team(
    body: CreateTeamRequest, runtime: Runtime, _: Principal = Depends(require_admin)
) -> APIResponse[TeamResponse]:
    try:
        team_type = TeamType(body.team_type.lower())
    except ValueError:
        raise _unprocessable(
            f"Unknown team type '{body.team_type}'; use one of {[t.value for t in TeamType]}"
        ) from None
    if body.parent_team_id and runtime.registry.get_team(body.parent_team_id) is None:
        raise _unprocessable(f"Parent team '{body.parent_team_id}' not found")
    if body.leader_id and runtime.registry.get(body.leader_id) is None:
        raise _unprocessable(f"Leader agent '{body.leader_id}' not found")

    team = runtime.registry.create_team(
        name=body.name,
        team_type=team_type,
        leader_id=body.leader_id,
        parent_id=body.parent_team_id,
    )
    try:
        await runtime.save_team(team)
    except Exception:
        runtime.registry.remove_team(team.id)
        raise
    return APIResponse(data=team_response(runtime, team), message="Team created")


@router.get(
    "",
    response_model=PaginatedResponse[TeamResponse],
    summary="List teams",
    dependencies=[Depends(require_viewer)],
)
async def list_teams(runtime: Runtime, paging: Paging) -> PaginatedResponse[Any]:
    teams = sorted(runtime.registry.team_hierarchy.teams.values(), key=lambda t: (t.name, t.id))
    page = teams[paging.offset : paging.offset + paging.page_size]
    return paginate(
        TeamResponse,
        [team_response(runtime, t) for t in page],
        paging.page,
        paging.page_size,
        len(teams),
    )


@router.get(
    "/{team_id}",
    response_model=APIResponse[TeamResponse],
    summary="Get team",
    dependencies=[Depends(require_viewer)],
)
async def get_team(team_id: str, runtime: Runtime) -> APIResponse[TeamResponse]:
    return APIResponse(data=team_response(runtime, _get_team(runtime, team_id)))


@router.patch(
    "/{team_id}",
    response_model=APIResponse[TeamResponse],
    summary="Rename or move a team",
)
async def update_team(
    team_id: str,
    body: UpdateTeamRequest,
    runtime: Runtime,
    _: Principal = Depends(require_admin),
) -> APIResponse[TeamResponse]:
    _get_team(runtime, team_id)
    try:
        team = runtime.registry.update_team(
            team_id,
            name=body.name,
            parent_id=body.parent_team_id,
            reparent="parent_team_id" in body.model_fields_set,
        )
    except KeyError:
        raise _unprocessable(f"Parent team '{body.parent_team_id}' not found") from None
    except ValueError as exc:
        raise _unprocessable(str(exc)) from None

    await runtime.save_team(team)
    return APIResponse(data=team_response(runtime, team), message="Team updated")


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete team")
async def delete_team(
    team_id: str, runtime: Runtime, _: Principal = Depends(require_admin)
) -> Response:
    _get_team(runtime, team_id)
    try:
        runtime.registry.remove_team(team_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    await runtime.store.delete_team(team_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{team_id}/members",
    response_model=APIResponse[list[str]],
    summary="List team member ids",
    dependencies=[Depends(require_viewer)],
)
async def team_members(team_id: str, runtime: Runtime) -> APIResponse[list[str]]:
    team = _get_team(runtime, team_id)
    return APIResponse(data=sorted(team.all_members(include_leader=True)))
