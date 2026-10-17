"""Runs submitted tasks on agents with bounded concurrency and persistence."""

from __future__ import annotations

import asyncio
import functools
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from unistax.agents.api.db.store import Store, to_jsonable
from unistax.agents.base import Agent, Task, TaskStatus
from unistax.agents.registry import AgentRegistry
from unistax.logging import get_logger

if TYPE_CHECKING:
    from unistax.agents.api.settings import AgentAPISettings

logger = get_logger(__name__)


class ExecutorClosed(Exception):
    """Raised when work is submitted while the service is shutting down."""


def _utc(value: datetime | None) -> datetime | None:
    return value.astimezone(timezone.utc) if value else None


class TaskExecutor:
    """Queues tasks per agent and persists every state transition.

    Concurrency is bounded globally (``max_running_tasks``) and per agent
    (``agent.max_concurrent_tasks``); excess tasks wait instead of failing.
    """

    def __init__(self, registry: AgentRegistry, store: Store, settings: AgentAPISettings) -> None:
        self._registry = registry
        self._store = store
        self._global = asyncio.Semaphore(settings.max_running_tasks)
        self._slots: dict[str, asyncio.Semaphore] = {}
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._assigned: dict[str, str] = {}
        self._closing = False

    # -- introspection ---------------------------------------------------
    def load(self, agent_id: str) -> int:
        """Tasks queued or running for an agent."""
        return sum(1 for assigned in self._assigned.values() if assigned == agent_id)

    @property
    def running_count(self) -> int:
        return len(self._jobs)

    def reset_slots(self, agent_id: str) -> None:
        """Pick up a changed ``max_concurrent_tasks`` for new work."""
        self._slots.pop(agent_id, None)

    # -- lifecycle --------------------------------------------------------
    async def submit(self, task: Task, agent_id: str, submitted_by: str | None) -> None:
        if self._closing:
            raise ExecutorClosed()

        await self._store.create_task(
            id=task.id,
            type=task.type,
            description=task.description,
            priority=task.priority,
            status="pending",
            required_skills=task.required_skills,
            context=to_jsonable(task.context),
            assigned_agent=agent_id,
            submitted_by=submitted_by,
        )

        self._assigned[task.id] = agent_id
        job = asyncio.create_task(self._run(task, agent_id), name=f"agent-task:{task.id}")
        self._jobs[task.id] = job
        job.add_done_callback(functools.partial(self._on_done, task.id))

    def _on_done(self, task_id: str, _job: asyncio.Task[None]) -> None:
        self._jobs.pop(task_id, None)
        self._assigned.pop(task_id, None)

    async def cancel(self, task_id: str) -> bool:
        """Cancel a queued or running task. False if it is not active here."""
        job = self._jobs.get(task_id)
        if job is None or job.done():
            return False
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)
        return True

    async def shutdown(self, timeout: float) -> None:
        """Let running tasks finish up to ``timeout``, then cancel the rest."""
        self._closing = True
        jobs = list(self._jobs.values())
        if not jobs:
            return
        _, pending = await asyncio.wait(jobs, timeout=timeout)
        for job in pending:
            job.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    # -- execution ---------------------------------------------------------
    def _slot_for(self, agent: Agent) -> asyncio.Semaphore:
        slot = self._slots.get(agent.agent_id)
        if slot is None:
            slot = self._slots[agent.agent_id] = asyncio.Semaphore(
                max(1, agent.max_concurrent_tasks)
            )
        return slot

    async def _run(self, task: Task, agent_id: str) -> None:
        agent = self._registry.get(agent_id)
        try:
            if agent is None:
                await self._finish(task, TaskStatus.FAILED, f"Agent {agent_id} no longer exists")
                return

            async with self._slot_for(agent), self._global:
                agent = self._registry.get(agent_id)
                if agent is None:
                    await self._finish(
                        task, TaskStatus.FAILED, f"Agent {agent_id} no longer exists"
                    )
                    return
                if not await agent.accept_task(task):
                    await self._finish(task, TaskStatus.FAILED, "Agent is at capacity")
                    return

                try:
                    started = datetime.now(timezone.utc)
                    await self._store.update_task(task.id, status="in_progress", started_at=started)
                    await agent.run_task(task)
                except BaseException:
                    # Cancelled or failed after the agent accepted the task: release the
                    # slot so the agent does not keep a task nobody is running.
                    agent.release_task(task)
                    raise
                await self._finish(
                    task, task.status, task.error, started=_utc(task.started_at) or started
                )

        except asyncio.CancelledError:
            if self._closing:
                await self._finish(task, TaskStatus.FAILED, "Interrupted by server shutdown")
            else:
                await self._finish(task, TaskStatus.CANCELLED, "Cancelled")
            raise
        except Exception as exc:
            logger.error("Task %s crashed: %s", task.id, exc, exc_info=True)
            await self._finish(task, TaskStatus.FAILED, f"Internal error: {type(exc).__name__}")

    async def _finish(
        self,
        task: Task,
        status: TaskStatus,
        error: str | None = None,
        started: datetime | None = None,
    ) -> None:
        values: dict[str, Any] = {
            "status": status.value,
            "error": error,
            "completed_at": datetime.now(timezone.utc),
        }
        if status == TaskStatus.COMPLETED:
            values["result"] = to_jsonable(task.result)
            values["error"] = None
        if started:
            values["started_at"] = started
        try:
            await self._store.update_task(task.id, **values)
        except Exception:
            logger.error("Failed to persist final state of task %s", task.id, exc_info=True)
