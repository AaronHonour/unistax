"""Swarm endpoints: give a goal, get a plan carried out by LLM workers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from unistax.agents.api.auth import Principal, require_operator, require_viewer
from unistax.agents.api.db.models import SwarmRecord
from unistax.agents.api.deps import Paging, Runtime
from unistax.agents.api.limits import expensive_rate_limit
from unistax.agents.api.presenters import swarm_response, swarm_summary
from unistax.agents.api.schemas import (
    CreateSwarmRequest,
    SwarmResponse,
    SwarmSummary,
    paginate,
)
from unistax.agents.api.services.swarm import NO_BACKEND_MESSAGE, SwarmError, SwarmRunner
from unistax.api import APIResponse, PaginatedResponse

router = APIRouter(prefix="/swarms", tags=["Swarms"])


def _runner(runtime: Runtime) -> SwarmRunner:
    if runtime.swarms is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            NO_BACKEND_MESSAGE,
        )
    return runtime.swarms


async def _get(runtime: Runtime, swarm_id: str) -> SwarmRecord:
    record = await runtime.store.get_swarm(swarm_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Swarm '{swarm_id}' not found")
    return record


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=APIResponse[SwarmResponse],
    summary="Start a swarm",
    description="Plans the goal, runs the plan with parallel LLM workers, and synthesizes an "
    "answer. Returns immediately; poll `GET /swarms/{id}` or watch the `swarm_finished` event. "
    "Every swarm spends model calls from the operator's Claude plan, up to a per-run budget.",
    dependencies=[Depends(expensive_rate_limit)],
)
async def start_swarm(
    body: CreateSwarmRequest,
    runtime: Runtime,
    principal: Principal = Depends(require_operator),
) -> APIResponse[SwarmResponse]:
    runner = _runner(runtime)
    try:
        record = await runner.submit(body, principal.subject)
    except SwarmError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    return APIResponse(data=swarm_response(record, None), message="Swarm started")


@router.get(
    "",
    response_model=PaginatedResponse[SwarmSummary],
    summary="List swarms",
    dependencies=[Depends(require_viewer)],
)
async def list_swarms(
    runtime: Runtime, paging: Paging, swarm_status: str | None = Query(None, alias="status")
) -> PaginatedResponse[Any]:
    records, total = await runtime.store.list_swarms(
        status=swarm_status, offset=paging.offset, limit=paging.page_size
    )
    return paginate(
        SwarmSummary, [swarm_summary(r) for r in records], paging.page, paging.page_size, total
    )


@router.get(
    "/{swarm_id}",
    response_model=APIResponse[SwarmResponse],
    summary="Get a swarm (live progress while running)",
    dependencies=[Depends(require_viewer)],
)
async def get_swarm(swarm_id: str, runtime: Runtime) -> APIResponse[SwarmResponse]:
    record = await _get(runtime, swarm_id)
    workflow = await runtime.store.get_workflow(record.workflow_id) if record.workflow_id else None
    return APIResponse(data=swarm_response(record, workflow))


@router.post(
    "/{swarm_id}/cancel",
    response_model=APIResponse[SwarmResponse],
    summary="Cancel a running swarm",
    dependencies=[Depends(require_operator)],
)
async def cancel_swarm(swarm_id: str, runtime: Runtime) -> APIResponse[SwarmResponse]:
    runner = _runner(runtime)
    await _get(runtime, swarm_id)
    if not await runner.cancel(swarm_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Swarm is not running")
    record = await _get(runtime, swarm_id)
    workflow = await runtime.store.get_workflow(record.workflow_id) if record.workflow_id else None
    return APIResponse(data=swarm_response(record, workflow), message="Swarm cancelled")
