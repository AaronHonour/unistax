"""Task submission and monitoring endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from unistax.agents.api.auth import Principal, require_operator, require_viewer
from unistax.agents.api.db.models import TaskRecord
from unistax.agents.api.deps import Paging, Runtime
from unistax.agents.api.limits import expensive_rate_limit
from unistax.agents.api.presenters import task_response
from unistax.agents.api.schemas import TaskRequest, TaskResponse, paginate
from unistax.agents.api.services.assignment import rank_agents, supported_types
from unistax.agents.api.services.executor import ExecutorClosed
from unistax.agents.base import Task
from unistax.api import APIResponse, PaginatedResponse

router = APIRouter(prefix="/tasks", tags=["Task Management"])

TERMINAL = {"completed", "failed", "cancelled"}


async def _fetch(runtime: Runtime, task_id: str) -> TaskRecord:
    record = await runtime.store.get_task(task_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Task '{task_id}' not found")
    return record


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=APIResponse[TaskResponse],
    summary="Submit task",
    description="Queues the task for an agent and returns immediately. Poll "
    "`GET /tasks/{id}` or subscribe to the WebSocket event stream for progress.",
    dependencies=[Depends(expensive_rate_limit)],
)
async def submit_task(
    body: TaskRequest,
    runtime: Runtime,
    principal: Principal = Depends(require_operator),
) -> APIResponse[TaskResponse]:
    task = Task(
        type=body.task_type,
        description=body.description,
        priority=body.priority,
        required_skills=body.required_skills or {},
        context=body.context,
    )

    pinned = None
    if body.agent_id:
        pinned = runtime.registry.get(body.agent_id)
        if pinned is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Agent '{body.agent_id}' not found")

    candidates = rank_agents(runtime.registry, task, runtime.executor.load, only=pinned)
    if not candidates:
        if pinned:
            detail = f"Agent '{pinned.agent_id}' cannot run '{task.type}' with the required skills"
        else:
            detail = (
                f"No registered agent can run '{task.type}' with the required skills. "
                f"Supported task types: {supported_types(runtime.registry)}"
            )
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail)

    try:
        await runtime.executor.submit(task, candidates[0].agent.agent_id, principal.subject)
    except ExecutorClosed:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Service is shutting down"
        ) from None

    return APIResponse(data=task_response(await _fetch(runtime, task.id)), message="Task accepted")


@router.get(
    "",
    response_model=PaginatedResponse[TaskResponse],
    summary="List tasks",
    dependencies=[Depends(require_viewer)],
)
async def list_tasks(
    runtime: Runtime,
    paging: Paging,
    task_status: str | None = Query(None, alias="status"),
    agent_id: str | None = Query(None),
    task_type: str | None = Query(None),
) -> PaginatedResponse[Any]:
    records, total = await runtime.store.list_tasks(
        status=task_status,
        agent_id=agent_id,
        task_type=task_type,
        offset=paging.offset,
        limit=paging.page_size,
    )
    return paginate(
        TaskResponse, [task_response(r) for r in records], paging.page, paging.page_size, total
    )


@router.get(
    "/{task_id}",
    response_model=APIResponse[TaskResponse],
    summary="Get task",
    dependencies=[Depends(require_viewer)],
)
async def get_task(task_id: str, runtime: Runtime) -> APIResponse[TaskResponse]:
    record = await runtime.store.get_task(task_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Task '{task_id}' not found")
    return APIResponse(data=task_response(record))


@router.post(
    "/{task_id}/cancel",
    response_model=APIResponse[TaskResponse],
    summary="Cancel task",
    dependencies=[Depends(require_operator)],
)
async def cancel_task(task_id: str, runtime: Runtime) -> APIResponse[TaskResponse]:
    record = await runtime.store.get_task(task_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Task '{task_id}' not found")
    if record.status in TERMINAL:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Task is already {record.status}")
    if not await runtime.executor.cancel(task_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Task is not active on this server")

    return APIResponse(data=task_response(await _fetch(runtime, task_id)), message="Task cancelled")
