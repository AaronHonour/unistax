"""Workflow definition validation, execution and persistence."""

from __future__ import annotations

import asyncio
import functools
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from unistax.agents.api.db.models import WorkflowRecord
from unistax.agents.api.db.store import Store, to_jsonable
from unistax.agents.api.schemas.workflows import CreateWorkflowRequest
from unistax.agents.api.services.agents import resolve_persona, supported_task_types
from unistax.agents.base import Task
from unistax.agents.orchestrator import (
    AgentOrchestrator,
    StepStatus,
    Workflow,
    WorkflowStatus,
    WorkflowStep,
)
from unistax.agents.registry import AgentRegistry
from unistax.logging import get_logger

logger = get_logger(__name__)

SNAPSHOT_INTERVAL = 1.0


class WorkflowError(Exception):
    """A workflow request that cannot be honoured (maps to HTTP 4xx)."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def _iso(value: datetime | None) -> str | None:
    # The orchestrator uses naive local timestamps; astimezone() assumes local time.
    return value.astimezone(timezone.utc).isoformat() if value else None


def validate_definition(
    request: CreateWorkflowRequest, registry: AgentRegistry
) -> list[dict[str, Any]]:
    """Check a workflow request and return its normalised step definitions."""
    ids = [step.step_id for step in request.steps]
    if len(set(ids)) != len(ids):
        raise WorkflowError("Step ids must be unique")

    definition: list[dict[str, Any]] = []
    for step in request.steps:
        persona = None
        if step.agent_persona:
            persona = resolve_persona(step.agent_persona)
            if persona is None:
                raise WorkflowError(
                    f"Step '{step.step_id}': unknown persona '{step.agent_persona}'"
                )
            allowed = supported_task_types(persona)
            if allowed is not None and step.task_type not in allowed:
                raise WorkflowError(
                    f"Step '{step.step_id}': persona '{persona}' cannot run '{step.task_type}'"
                )
        if step.agent_id and registry.get(step.agent_id) is None:
            raise WorkflowError(f"Step '{step.step_id}': agent '{step.agent_id}' not found")
        for dep in step.dependencies:
            if dep == step.step_id:
                raise WorkflowError(f"Step '{step.step_id}' cannot depend on itself")
            if dep not in ids:
                raise WorkflowError(f"Step '{step.step_id}' depends on unknown step '{dep}'")

        definition.append(
            {
                "step_id": step.step_id,
                "name": step.name or step.step_id,
                "task_type": step.task_type,
                "description": step.description,
                "priority": step.priority,
                "required_skills": step.required_skills or {},
                "context": to_jsonable(step.context),
                "dependencies": list(dict.fromkeys(step.dependencies)),
                "agent_persona": persona,
                "agent_id": step.agent_id,
                "max_retries": step.max_retries,
            }
        )

    _ensure_acyclic(definition)
    return definition


def _ensure_acyclic(definition: list[dict[str, Any]]) -> None:
    remaining = {d["step_id"]: set(d["dependencies"]) for d in definition}
    while remaining:
        ready = [step for step, deps in remaining.items() if not deps]
        if not ready:
            raise WorkflowError(f"Dependency cycle among steps: {sorted(remaining)}")
        for step in ready:
            del remaining[step]
        for deps in remaining.values():
            deps.difference_update(ready)


def build_workflow(record: WorkflowRecord) -> Workflow:
    steps = []
    for d in record.definition:
        task = Task(
            id=f"{record.id}:{d['step_id']}",
            type=d["task_type"],
            description=d["description"],
            priority=d["priority"],
            required_skills=dict(d["required_skills"]),
            context=dict(d["context"]),
        )
        steps.append(
            WorkflowStep(
                id=d["step_id"],
                name=d["name"],
                task=task,
                agent_persona=d["agent_persona"],
                agent_id=d["agent_id"],
                dependencies=list(d["dependencies"]),
                max_retries=d["max_retries"],
            )
        )
    return Workflow(id=record.id, name=record.name, description=record.description, steps=steps)


def snapshot_progress(workflow: Workflow) -> dict[str, Any]:
    return {
        step.id: {
            "status": step.status.value,
            "agent_id": step.agent_id,
            "retry_count": step.retry_count,
            "result": to_jsonable(step.result),
            "error": step.error,
            "started_at": _iso(step.started_at),
            "completed_at": _iso(step.completed_at),
        }
        for step in workflow.steps
    }


class WorkflowRunner:
    """Creates workflows and runs them in the background."""

    def __init__(
        self, registry: AgentRegistry, orchestrator: AgentOrchestrator, store: Store
    ) -> None:
        self._registry = registry
        self._orchestrator = orchestrator
        self._store = store
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._starting: set[str] = set()
        self._closing = False

    @property
    def running_count(self) -> int:
        return len(self._jobs)

    def is_running(self, workflow_id: str) -> bool:
        return workflow_id in self._jobs or workflow_id in self._starting

    async def create(
        self, request: CreateWorkflowRequest, submitted_by: str | None
    ) -> WorkflowRecord:
        definition = validate_definition(request, self._registry)
        return await self._store.create_workflow(
            id=str(uuid4()),
            name=request.name,
            description=request.description,
            status="pending",
            definition=definition,
            progress={
                d["step_id"]: {
                    "status": "pending",
                    "retry_count": 0,
                    "result": None,
                    "error": None,
                    "agent_id": d["agent_id"],
                    "started_at": None,
                    "completed_at": None,
                }
                for d in definition
            },
            submitted_by=submitted_by,
        )

    async def start(self, workflow_id: str) -> WorkflowRecord:
        """Begin background execution of a pending workflow."""
        if self._closing:
            raise WorkflowError("Service is shutting down", 503)
        if self.is_running(workflow_id):
            raise WorkflowError("Workflow is already running", 409)

        self._starting.add(workflow_id)
        try:
            record = await self._store.get_workflow(workflow_id)
            if record is None:
                raise WorkflowError("Workflow not found", 404)
            if record.status != "pending":
                raise WorkflowError(
                    f"Workflow is {record.status}; only pending workflows can start", 409
                )

            started_at = datetime.now(timezone.utc)
            await self._store.update_workflow(workflow_id, status="running", started_at=started_at)
            record.status = "running"
            record.started_at = started_at

            job = asyncio.create_task(
                self._run(build_workflow(record)), name=f"workflow:{workflow_id}"
            )
            self._jobs[workflow_id] = job
            job.add_done_callback(functools.partial(self._on_done, workflow_id))
            return record
        finally:
            self._starting.discard(workflow_id)

    def _on_done(self, workflow_id: str, _job: asyncio.Task[None]) -> None:
        self._jobs.pop(workflow_id, None)

    async def wait(self, workflow_id: str) -> None:
        """Return once ``workflow_id`` is no longer running (immediately if it is not).

        Cancelling the caller does not cancel the workflow.
        """
        job = self._jobs.get(workflow_id)
        if job is not None:
            await asyncio.wait([job])

    async def cancel(self, workflow_id: str) -> bool:
        job = self._jobs.get(workflow_id)
        if job is None or job.done():
            return False
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)
        return True

    async def shutdown(self, timeout: float) -> None:
        self._closing = True
        jobs = list(self._jobs.values())
        if not jobs:
            return
        _, pending = await asyncio.wait(jobs, timeout=timeout)
        for job in pending:
            job.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _run(self, workflow: Workflow) -> None:
        snapshotter = asyncio.create_task(self._snapshot_loop(workflow))
        cancelled = False
        try:
            await self._orchestrator.execute_workflow(workflow)
        except asyncio.CancelledError:
            cancelled = True
            workflow.status = WorkflowStatus.CANCELLED
            workflow.completed_at = datetime.now()
            for step in workflow.steps:
                if step.status not in (StepStatus.COMPLETED, StepStatus.FAILED):
                    step.status = StepStatus.SKIPPED
                    step.error = step.error or "Workflow cancelled"
        except Exception:
            logger.error("Workflow %s crashed", workflow.id, exc_info=True)
            workflow.status = WorkflowStatus.FAILED
            workflow.completed_at = datetime.now()
        finally:
            snapshotter.cancel()
            await asyncio.gather(snapshotter, return_exceptions=True)
            self._orchestrator.workflows.pop(workflow.id, None)
            if self._closing and cancelled:
                workflow.status = WorkflowStatus.FAILED
            await self._persist(workflow)
        if cancelled:
            raise asyncio.CancelledError

    async def _snapshot_loop(self, workflow: Workflow) -> None:
        while True:
            await asyncio.sleep(SNAPSHOT_INTERVAL)
            await self._persist(workflow)

    async def _persist(self, workflow: Workflow) -> None:
        try:
            await self._store.update_workflow(
                workflow.id,
                status=workflow.status.value,
                progress=snapshot_progress(workflow),
                started_at=(
                    workflow.started_at.astimezone(timezone.utc) if workflow.started_at else None
                ),
                completed_at=(
                    workflow.completed_at.astimezone(timezone.utc)
                    if workflow.completed_at
                    else None
                ),
            )
        except Exception:
            logger.error("Failed to persist workflow %s", workflow.id, exc_info=True)
