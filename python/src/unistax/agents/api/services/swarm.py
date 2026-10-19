"""Running swarms: plan a goal, run the plan as a workflow of LLM workers, assemble the result."""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from unistax.agents.api.db.models import SwarmRecord
from unistax.agents.api.db.store import Store
from unistax.agents.api.schemas.swarms import CreateSwarmRequest
from unistax.agents.api.schemas.workflows import CreateWorkflowRequest, WorkflowStepRequest
from unistax.agents.api.services.workflows import WorkflowError, WorkflowRunner
from unistax.agents.llm import LLMError, LLMGateway, Usage
from unistax.agents.registry import AgentRegistry
from unistax.agents.swarm import PlanError, SwarmFinishedEvent, make_plan, prompts
from unistax.agents.swarm.plan import Plan
from unistax.events import EventBus

if TYPE_CHECKING:
    from unistax.agents.api.settings import AgentAPISettings

logger = logging.getLogger(__name__)

WORKER_PERSONA = "claude_worker"
MAX_STORED_OUTPUT_CHARS = 100_000
NO_BACKEND_MESSAGE = (
    "No language-model backend is configured (set UNISTAX_AGENT_API_LLM_BACKEND=claude_cli)"
)
INTERRUPTED = "Interrupted by server restart"
SHUTDOWN = "Interrupted by server shutdown"


class SwarmError(Exception):
    """A swarm request that cannot be honoured (maps to HTTP 4xx/5xx)."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        """Create the error with the HTTP status it should map to."""
        super().__init__(message)
        self.status_code = status_code


def _utc(value: datetime | None) -> datetime | None:
    return value.astimezone(timezone.utc) if value else None


class SwarmRunner:
    """Creates swarm runs and drives them in the background."""

    def __init__(
        self,
        *,
        registry: AgentRegistry,
        workflows: WorkflowRunner,
        store: Store,
        gateway: LLMGateway,
        settings: AgentAPISettings,
        event_bus: EventBus,
    ) -> None:
        """Wire the runner to the shared services."""
        self._registry = registry
        self._workflows = workflows
        self._store = store
        self._gateway = gateway
        self._settings = settings
        self._event_bus = event_bus
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._reserved = 0
        self._closing = False

    @property
    def running_count(self) -> int:
        """Swarms currently planning or running in this process."""
        return len(self._jobs)

    def is_running(self, swarm_id: str) -> bool:
        """Whether ``swarm_id`` is active in this process."""
        return swarm_id in self._jobs

    # -- lifecycle -----------------------------------------------------------------
    async def submit(self, request: CreateSwarmRequest, submitted_by: str | None) -> SwarmRecord:
        """Validate, store and start a swarm run.

        Raises:
            SwarmError: Not allowed right now (no workers, too many active, shutting down).
        """
        if self._closing:
            raise SwarmError("Service is shutting down", 503)
        if not self._registry.find_by_persona(WORKER_PERSONA):
            raise SwarmError(
                f"No '{WORKER_PERSONA}' agent is registered, so there is nobody to do the work", 409
            )
        if len(request.context) > self._settings.swarm_max_context_chars:
            raise SwarmError(
                f"context is limited to {self._settings.swarm_max_context_chars} characters", 422
            )
        if len(self._jobs) + self._reserved >= self._settings.swarm_max_active:
            raise SwarmError(
                f"{self._settings.swarm_max_active} swarms are already running; "
                "wait for one to finish or cancel it",
                429,
            )

        self._reserved += 1
        try:
            max_subtasks = min(
                request.max_subtasks or self._settings.swarm_max_subtasks,
                self._settings.swarm_max_subtasks,
            )
            record = await self._store.create_swarm(
                id=str(uuid4()),
                goal=request.goal,
                context=request.context,
                status="planning",
                options={
                    "max_subtasks": max_subtasks,
                    "review": request.review,
                    "model": request.model or self._settings.llm_model,
                    "effort": request.effort or self._settings.llm_effort,
                    "max_calls": self._settings.swarm_max_calls,
                },
                usage={},
                submitted_by=submitted_by,
            )
            job = asyncio.create_task(self._run(record.id), name=f"swarm:{record.id}")
            self._jobs[record.id] = job
            job.add_done_callback(functools.partial(self._on_done, record.id))
        finally:
            self._reserved -= 1
        return record

    def _on_done(self, swarm_id: str, _job: asyncio.Task[None]) -> None:
        self._jobs.pop(swarm_id, None)

    async def cancel(self, swarm_id: str) -> bool:
        """Stop a running swarm. False if it is not running here."""
        job = self._jobs.get(swarm_id)
        if job is None or job.done():
            return False
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)
        return True

    async def shutdown(self, timeout: float) -> None:
        """Let running swarms finish up to ``timeout``, then cancel them."""
        self._closing = True
        jobs = list(self._jobs.values())
        if not jobs:
            return
        _, pending = await asyncio.wait(jobs, timeout=timeout)
        for job in pending:
            job.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    # -- the run -----------------------------------------------------------------------
    async def _run(self, swarm_id: str) -> None:
        record = await self._store.get_swarm(swarm_id)
        assert record is not None
        started = time.monotonic()
        options = record.options
        budget = self._gateway.open_budget(swarm_id, int(options["max_calls"]))
        plan_usage = Usage()
        workflow_id: str | None = None
        plan: Plan | None = None
        status, error, result = "failed", None, None
        cancelled = False
        try:
            planned = await make_plan(
                self._gateway,
                goal=record.goal,
                material=record.context,
                max_steps=int(options["max_subtasks"]),
                run_id=swarm_id,
                model=options.get("model"),
                effort=options.get("effort"),
                max_chars=self._settings.swarm_max_context_chars,
            )
            plan, plan_usage = planned.plan, planned.usage
            await self._store.update_swarm(
                swarm_id,
                status="running",
                plan=plan.as_dict(),
                started_at=datetime.now(timezone.utc),
            )

            request = self._workflow_request(record, plan)
            workflow = await self._workflows.create(request, record.submitted_by)
            workflow_id = workflow.id
            await self._store.update_swarm(swarm_id, workflow_id=workflow_id)
            await self._workflows.start(workflow_id)
            await self._workflows.wait(workflow_id)

            finished = await self._store.get_workflow(workflow_id)
            assert finished is not None
            result = assemble_result(plan, finished.progress or {}, plan_usage, budget.used)
            status = "completed" if finished.status == "completed" else finished.status
            if status != "completed":
                error = _first_error(result) or f"workflow {finished.status}"
                status = "cancelled" if finished.status == "cancelled" else "failed"
        except asyncio.CancelledError:
            cancelled = True
            status = "failed" if self._closing else "cancelled"
            error = SHUTDOWN if self._closing else None
            if workflow_id:
                await self._workflows.cancel(workflow_id)
            raise
        except (LLMError, PlanError, WorkflowError, SwarmError) as exc:
            status, error = "failed", str(exc)
        except Exception:
            logger.error("Swarm %s crashed", swarm_id, exc_info=True)
            status, error = "failed", "internal error"
        finally:
            if plan is not None and result is None and workflow_id:
                # Keep whatever finished before a failure or cancellation
                finished = await self._store.get_workflow(workflow_id)
                if finished is not None:
                    result = assemble_result(plan, finished.progress or {}, plan_usage, budget.used)
            self._gateway.close_budget(swarm_id)
            usage = dict((result or {}).get("usage") or plan_usage.as_dict())
            usage["calls_used"] = budget.used
            usage["calls_allowed"] = budget.max_calls
            duration = time.monotonic() - started
            await self._store.update_swarm(
                swarm_id,
                status=status,
                error=error,
                result=result,
                usage=usage,
                completed_at=datetime.now(timezone.utc),
            )
            await self._event_bus.publish(
                SwarmFinishedEvent(
                    swarm_id=swarm_id,
                    status=status,
                    duration_seconds=round(duration, 2),
                    calls_used=budget.used,
                )
            )
            if cancelled:
                logger.info("Swarm %s ended: %s", swarm_id, status)

    # -- building and reading workflows ---------------------------------------------------
    def _workflow_request(self, record: SwarmRecord, plan: Plan) -> CreateWorkflowRequest:
        options = record.options
        shared = {
            "goal": record.goal,
            "material": record.context,
            "swarm_id": record.id,
            "model": options.get("model"),
            "effort": options.get("effort"),
            "max_input_chars": self._settings.swarm_max_context_chars,
        }

        def step(
            step_id: str, role: str, title: str, instructions: str, deps: list[str], **extra: Any
        ) -> WorkflowStepRequest:
            return WorkflowStepRequest(
                step_id=step_id,
                name=title,
                task_type="llm_task",
                description="",
                priority=5,
                agent_persona=WORKER_PERSONA,
                dependencies=deps,
                max_retries=1,  # the gateway already retries what is worth retrying
                context={
                    **shared,
                    "role": role,
                    "title": title,
                    "instructions": instructions,
                    **extra,
                },
            )

        steps = [step(s.id, s.role, s.title, s.instructions, s.depends_on) for s in plan.steps]
        steps.append(
            step(
                "synthesize", "synthesizer", "Synthesize the final answer",
                prompts.SYNTHESIS_INSTRUCTIONS, [s.id for s in plan.steps],
            )  # fmt: skip
        )
        if options.get("review"):
            steps.append(
                step(
                    "review", "critic", "Review the final answer",
                    prompts.REVIEW_INSTRUCTIONS, ["synthesize"],
                    output_schema=prompts.REVIEW_SCHEMA,
                )  # fmt: skip
            )
        return CreateWorkflowRequest(
            name=f"swarm: {record.goal[:150]}",
            description=f"Created by swarm {record.id}",
            steps=steps,
        )


def assemble_result(
    plan: Plan, progress: dict[str, Any], plan_usage: Usage, calls_attempted: int
) -> dict[str, Any]:
    """Per-step outputs, the final answer and usage, from a workflow's ``progress``."""
    planned = {s.id: s for s in plan.steps}
    order = [*planned, "synthesize", *(["review"] if "review" in progress else [])]

    steps: dict[str, Any] = {}
    total = plan_usage
    for step_id in order:
        state = progress.get(step_id, {})
        output = state.get("result") or {}
        usage = output.get("usage") if isinstance(output, dict) else None
        if usage:
            total = total + Usage(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cache_read_tokens=usage.get("cache_read_tokens", 0),
                cache_creation_tokens=usage.get("cache_creation_tokens", 0),
                calls=usage.get("calls", 0),
            )
        text = output.get("text") if isinstance(output, dict) else None
        known = step_id in planned
        steps[step_id] = {
            "role": planned[step_id].role if known else _fixed_role(step_id),
            "title": planned[step_id].title if known else _fixed_title(step_id),
            "depends_on": planned[step_id].depends_on if known else _fixed_deps(step_id, plan),
            "status": state.get("status", "pending"),
            "output": text[:MAX_STORED_OUTPUT_CHARS] if isinstance(text, str) else None,
            "structured": output.get("structured") if isinstance(output, dict) else None,
            "error": state.get("error"),
            "usage": usage,
        }
    final = steps["synthesize"]["output"]
    completed = [s for s in steps.values() if s["status"] == "completed"]
    return {
        "final": final,
        "review": steps.get("review", {}).get("structured"),
        "steps": steps,
        "partial": final is None and bool(completed),
        "usage": {**total.as_dict(), "calls_attempted": calls_attempted},
    }


def _fixed_role(step_id: str) -> str:
    return "synthesizer" if step_id == "synthesize" else "critic"


def _fixed_title(step_id: str) -> str:
    return "Synthesize the final answer" if step_id == "synthesize" else "Review the final answer"


def _fixed_deps(step_id: str, plan: Plan) -> list[str]:
    return [s.id for s in plan.steps] if step_id == "synthesize" else ["synthesize"]


def _first_error(result: dict[str, Any]) -> str | None:
    for step_id, step in result["steps"].items():
        if step.get("error"):
            return f"step '{step_id}' failed: {step['error']}"
    return None
