"""Workflow orchestration endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from unistax.agents.api.auth import Principal, require_operator, require_viewer
from unistax.agents.api.db.models import WorkflowRecord
from unistax.agents.api.deps import Paging, Runtime
from unistax.agents.api.limits import expensive_rate_limit
from unistax.agents.api.presenters import workflow_response, workflow_status_response
from unistax.agents.api.schemas import (
    CreateWorkflowRequest,
    WorkflowResponse,
    WorkflowStatusResponse,
    paginate,
)
from unistax.agents.api.services.workflows import WorkflowError
from unistax.api import APIResponse, PaginatedResponse

router = APIRouter(prefix="/workflows", tags=["Workflow Orchestration"])


async def _get_record(runtime: Runtime, workflow_id: str) -> WorkflowRecord:
    record = await runtime.store.get_workflow(workflow_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Workflow '{workflow_id}' not found")
    return record


def _http(exc: WorkflowError) -> HTTPException:
    return HTTPException(exc.status_code, str(exc))


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[WorkflowResponse],
    summary="Create workflow",
    description="Validates the step graph (unknown dependencies, cycles, unsupported "
    "task types) and stores the workflow. Start it with `POST /workflows/{id}/execute`.",
)
async def create_workflow(
    body: CreateWorkflowRequest,
    runtime: Runtime,
    principal: Principal = Depends(require_operator),
) -> APIResponse[WorkflowResponse]:
    try:
        record = await runtime.workflows.create(body, principal.subject)
    except WorkflowError as exc:
        raise _http(exc) from None
    return APIResponse(data=workflow_response(record), message="Workflow created")


@router.get(
    "",
    response_model=PaginatedResponse[WorkflowResponse],
    summary="List workflows",
    dependencies=[Depends(require_viewer)],
)
async def list_workflows(
    runtime: Runtime, paging: Paging, workflow_status: str | None = Query(None, alias="status")
) -> PaginatedResponse[Any]:
    records, total = await runtime.store.list_workflows(
        status=workflow_status, offset=paging.offset, limit=paging.page_size
    )
    return paginate(
        WorkflowResponse,
        [workflow_response(r) for r in records],
        paging.page,
        paging.page_size,
        total,
    )


@router.get(
    "/{workflow_id}",
    response_model=APIResponse[WorkflowResponse],
    summary="Get workflow",
    dependencies=[Depends(require_viewer)],
)
async def get_workflow(workflow_id: str, runtime: Runtime) -> APIResponse[WorkflowResponse]:
    return APIResponse(data=workflow_response(await _get_record(runtime, workflow_id)))


@router.get(
    "/{workflow_id}/status",
    response_model=APIResponse[WorkflowStatusResponse],
    summary="Workflow progress",
    dependencies=[Depends(require_viewer)],
)
async def get_workflow_status(
    workflow_id: str, runtime: Runtime
) -> APIResponse[WorkflowStatusResponse]:
    return APIResponse(data=workflow_status_response(await _get_record(runtime, workflow_id)))


@router.post(
    "/{workflow_id}/execute",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=APIResponse[WorkflowResponse],
    summary="Start workflow",
    dependencies=[Depends(require_operator), Depends(expensive_rate_limit)],
)
async def execute_workflow(workflow_id: str, runtime: Runtime) -> APIResponse[WorkflowResponse]:
    try:
        record = await runtime.workflows.start(workflow_id)
    except WorkflowError as exc:
        raise _http(exc) from None
    return APIResponse(data=workflow_response(record), message="Workflow started")


@router.post(
    "/{workflow_id}/cancel",
    response_model=APIResponse[WorkflowResponse],
    summary="Cancel a running workflow",
    dependencies=[Depends(require_operator)],
)
async def cancel_workflow(workflow_id: str, runtime: Runtime) -> APIResponse[WorkflowResponse]:
    await _get_record(runtime, workflow_id)
    if not await runtime.workflows.cancel(workflow_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Workflow is not running")
    return APIResponse(
        data=workflow_response(await _get_record(runtime, workflow_id)),
        message="Workflow cancelled",
    )


@router.delete(
    "/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete workflow",
    dependencies=[Depends(require_operator)],
)
async def delete_workflow(workflow_id: str, runtime: Runtime) -> Response:
    await _get_record(runtime, workflow_id)
    if runtime.workflows.is_running(workflow_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Workflow is running; cancel it first")
    await runtime.store.delete_workflow(workflow_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
