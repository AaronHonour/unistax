"""Agent Orchestrator for coordinating multi-agent workflows.

Provides workflow orchestration capabilities:
- Coordinate complex multi-agent tasks
- Manage task dependencies
- Handle agent failures and retries
- Track workflow progress
- Enable collaboration patterns
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from unistax.agents.base import Task, TaskStatus
from unistax.agents.registry import AgentRegistry
from unistax.events import Event, EventBus
from unistax.logging import get_logger

logger = get_logger(__name__)


class WorkflowStatus(Enum):
    """Workflow execution states."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(Enum):
    """Workflow step states."""

    PENDING = "pending"
    READY = "ready"  # Dependencies met
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class WorkflowStep:
    """Single step in a workflow.

    Represents a task that needs to be executed by an agent,
    with dependencies and execution metadata.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    task: Task = field(default_factory=Task)
    agent_persona: str | None = None  # Required agent type
    agent_id: str | None = None  # Specific agent (if assigned)
    dependencies: list[str] = field(default_factory=list)  # Step IDs
    status: StepStatus = StepStatus.PENDING
    result: Any | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    retry_count: int = 0
    max_retries: int = 3


@dataclass
class Workflow:
    """Multi-agent workflow definition.

    Represents a DAG of tasks to be executed by multiple agents
    in a coordinated manner.

    Examples:
        >>> workflow = Workflow(
        ...     name="Customer Analytics Pipeline",
        ...     steps=[
        ...         WorkflowStep(
        ...             name="Build Pipeline",
        ...             task=Task(type="build_pipeline", ...),
        ...             agent_persona="data_engineer",
        ...         ),
        ...         WorkflowStep(
        ...             name="Analyze Data",
        ...             task=Task(type="analyze_data", ...),
        ...             agent_persona="data_analyst",
        ...             dependencies=["step1_id"],
        ...         ),
        ...     ]
        ... )
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    description: str = ""
    steps: list[WorkflowStep] = field(default_factory=list)
    status: WorkflowStatus = WorkflowStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_step(self, step_id: str) -> WorkflowStep | None:
        """Get workflow step by ID."""
        return next((s for s in self.steps if s.id == step_id), None)

    def get_ready_steps(self) -> list[WorkflowStep]:
        """Get steps that are ready to execute (dependencies met)."""
        ready = []
        for step in self.steps:
            if step.status != StepStatus.PENDING:
                continue

            # Check if all dependencies are completed
            deps_met = all(
                self.get_step(dep_id).status == StepStatus.COMPLETED
                for dep_id in step.dependencies
                if self.get_step(dep_id)
            )

            if deps_met:
                ready.append(step)

        return ready

    def is_complete(self) -> bool:
        """Check if workflow is in terminal state."""
        return self.status in (
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        )


@dataclass
class WorkflowExecutedEvent(Event):
    """Event published when workflow completes."""

    workflow_id: str = ""
    workflow_name: str = ""
    status: str = ""
    duration_seconds: float = 0.0


class AgentOrchestrator:
    """Orchestrates multi-agent workflows.

    Coordinates execution of complex workflows involving multiple
    agents, handling task dependencies, failures, and collaboration.

    Examples:
        >>> registry = AgentRegistry()
        >>> orchestrator = AgentOrchestrator(registry)
        >>>
        >>> # Create workflow
        >>> workflow = Workflow(
        ...     name="Data Pipeline",
        ...     steps=[...]
        ... )
        >>>
        >>> # Execute workflow
        >>> result = await orchestrator.execute_workflow(workflow)
    """

    def __init__(
        self,
        registry: AgentRegistry,
        event_bus: EventBus | None = None,
    ):
        """Initialize orchestrator.

        Args:
            registry: Agent registry for agent lookup
            event_bus: Optional EventBus for events
        """
        self.registry = registry
        self.event_bus = event_bus or registry.event_bus

        # Workflow tracking
        self.workflows: dict[str, Workflow] = {}
        self.active_workflows: set[str] = set()

        logger.info("Agent orchestrator initialized")

    async def execute_workflow(
        self,
        workflow: Workflow,
        max_concurrent_steps: int = 5,
    ) -> dict[str, Any]:
        """Execute a workflow.

        Args:
            workflow: Workflow to execute
            max_concurrent_steps: Maximum steps to run in parallel

        Returns:
            Workflow execution result

        Examples:
            >>> result = await orchestrator.execute_workflow(workflow)
            >>> print(result["status"])  # completed, failed
        """
        logger.info(f"Executing workflow: {workflow.name} (id={workflow.id})")

        # Track workflow
        self.workflows[workflow.id] = workflow
        self.active_workflows.add(workflow.id)

        workflow.status = WorkflowStatus.RUNNING
        workflow.started_at = datetime.now()

        try:
            # Execute workflow steps
            await self._execute_workflow_steps(workflow, max_concurrent_steps)

            # Determine final status
            failed_steps = [s for s in workflow.steps if s.status == StepStatus.FAILED]
            if failed_steps:
                workflow.status = WorkflowStatus.FAILED
                logger.error(
                    f"Workflow {workflow.name} failed: " f"{len(failed_steps)} steps failed"
                )
            else:
                workflow.status = WorkflowStatus.COMPLETED
                logger.info(f"Workflow {workflow.name} completed successfully")

        except Exception as e:
            workflow.status = WorkflowStatus.FAILED
            logger.error(f"Workflow {workflow.name} failed with exception: {e}", exc_info=True)

        finally:
            workflow.completed_at = datetime.now()
            self.active_workflows.discard(workflow.id)

            # Publish completion event
            if self.event_bus:
                duration = (workflow.completed_at - workflow.started_at).total_seconds()
                await self.event_bus.publish(
                    WorkflowExecutedEvent(
                        workflow_id=workflow.id,
                        workflow_name=workflow.name,
                        status=workflow.status.value,
                        duration_seconds=duration,
                    )
                )

        # Build result
        return {
            "workflow_id": workflow.id,
            "workflow_name": workflow.name,
            "status": workflow.status.value,
            "steps_total": len(workflow.steps),
            "steps_completed": len([s for s in workflow.steps if s.status == StepStatus.COMPLETED]),
            "steps_failed": len([s for s in workflow.steps if s.status == StepStatus.FAILED]),
            "duration_seconds": (workflow.completed_at - workflow.started_at).total_seconds(),
        }

    async def _execute_workflow_steps(
        self,
        workflow: Workflow,
        max_concurrent: int,
    ):
        """Execute workflow steps respecting dependencies.

        Args:
            workflow: Workflow to execute
            max_concurrent: Max parallel steps
        """
        running_tasks: dict[str, asyncio.Task] = {}

        try:
            await self._drive_steps(workflow, max_concurrent, running_tasks)
        except asyncio.CancelledError:
            for step_task in running_tasks.values():
                step_task.cancel()
            await asyncio.gather(*running_tasks.values(), return_exceptions=True)
            raise

    def _skip_blocked_steps(self, workflow: Workflow) -> None:
        """Skip pending steps that can never run because a dependency did not complete."""
        for step in workflow.steps:
            if step.status != StepStatus.PENDING:
                continue
            for dep_id in step.dependencies:
                dep = workflow.get_step(dep_id)
                if dep and dep.status in (StepStatus.FAILED, StepStatus.SKIPPED):
                    step.status = StepStatus.SKIPPED
                    step.error = f"Skipped: dependency '{dep_id}' did not complete"
                    break

    async def _drive_steps(
        self,
        workflow: Workflow,
        max_concurrent: int,
        running_tasks: dict[str, "asyncio.Task[Any]"],
    ):
        while not self._all_steps_done(workflow):
            self._skip_blocked_steps(workflow)
            if self._all_steps_done(workflow):
                break

            # Get steps ready to execute
            ready_steps = workflow.get_ready_steps()

            # Limit concurrent execution
            available_slots = max_concurrent - len(running_tasks)
            steps_to_start = ready_steps[:available_slots]

            # Start new steps
            for step in steps_to_start:
                step.status = StepStatus.READY
                task = asyncio.create_task(self._execute_step(workflow, step))
                running_tasks[step.id] = task

            # Wait for at least one task to complete
            if running_tasks:
                done, pending = await asyncio.wait(
                    running_tasks.values(),
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=1.0,
                )

                # Remove completed tasks
                for task in done:
                    step_id = next(sid for sid, t in running_tasks.items() if t == task)
                    running_tasks.pop(step_id)

            # Small delay if no work to do
            if not running_tasks and not ready_steps:
                await asyncio.sleep(0.1)

        # Wait for remaining tasks
        if running_tasks:
            await asyncio.gather(*running_tasks.values())

    def _all_steps_done(self, workflow: Workflow) -> bool:
        """Check if all steps are in terminal state."""
        terminal_states = {
            StepStatus.COMPLETED,
            StepStatus.FAILED,
            StepStatus.SKIPPED,
        }
        return all(step.status in terminal_states for step in workflow.steps)

    async def _execute_step(self, workflow: Workflow, step: WorkflowStep):
        """Execute a single workflow step.

        Args:
            workflow: Parent workflow
            step: Step to execute
        """
        logger.info(f"Executing step: {step.name} (workflow={workflow.name})")

        step.status = StepStatus.ASSIGNED
        step.started_at = datetime.now()

        try:
            # Find agent to execute step
            agent = await self._find_agent_for_step(step)
            if not agent:
                raise ValueError(
                    f"No suitable agent found for step {step.name} "
                    f"(persona={step.agent_persona})"
                )

            step.agent_id = agent.agent_id
            step.status = StepStatus.RUNNING

            # Run through the full task lifecycle (capacity, state, metrics, events)
            task = step.task
            task.error = None
            task.completed_at = None
            if not await agent.accept_task(task):
                raise RuntimeError(f"Agent {agent.agent_id} is at capacity")
            await agent.run_task(task)
            if task.status != TaskStatus.COMPLETED:
                raise RuntimeError(task.error or "Task did not complete")

            result = task.result
            step.result = result
            step.status = StepStatus.COMPLETED
            step.completed_at = datetime.now()

            logger.info(
                f"Step {step.name} completed by {agent.agent_id} " f"(workflow={workflow.name})"
            )

        except Exception as e:
            logger.error(
                f"Step {step.name} failed: {e} (workflow={workflow.name})",
                exc_info=True,
            )

            step.error = str(e)
            step.retry_count += 1

            # Retry if allowed
            if step.retry_count < step.max_retries:
                logger.info(
                    f"Retrying step {step.name} "
                    f"(attempt {step.retry_count + 1}/{step.max_retries})"
                )
                step.status = (
                    StepStatus.ASSIGNED
                )  # not PENDING: keeps the main loop from re-starting it
                await asyncio.sleep(2**step.retry_count)  # Exponential backoff
                await self._execute_step(workflow, step)
            else:
                step.status = StepStatus.FAILED
                step.completed_at = datetime.now()

    async def _find_agent_for_step(self, step: WorkflowStep):
        """Find suitable agent for workflow step.

        Args:
            step: Workflow step

        Returns:
            Agent instance or None
        """
        # Use specific agent if assigned
        if step.agent_id:
            return self.registry.get(step.agent_id)

        # Find by persona and availability
        if step.agent_persona:
            agents = self.registry.find_available(persona=step.agent_persona)
            if agents:
                # Find best match based on task requirements
                best_agent = None
                best_confidence = 0.0

                for agent in agents:
                    can_do, confidence = agent.can_do(step.task)
                    if can_do and confidence > best_confidence:
                        best_agent = agent
                        best_confidence = confidence

                return best_agent

        return None

    def get_workflow(self, workflow_id: str) -> Workflow | None:
        """Get workflow by ID.

        Args:
            workflow_id: Workflow identifier

        Returns:
            Workflow or None if not found
        """
        return self.workflows.get(workflow_id)

    def get_workflow_status(self, workflow_id: str) -> dict[str, Any]:
        """Get workflow execution status.

        Args:
            workflow_id: Workflow identifier

        Returns:
            Status dictionary

        Examples:
            >>> status = orchestrator.get_workflow_status(workflow_id)
            >>> print(status["progress"])  # 0.75 (75% complete)
        """
        workflow = self.workflows.get(workflow_id)
        if not workflow:
            return {"error": "Workflow not found"}

        completed_steps = len([s for s in workflow.steps if s.status == StepStatus.COMPLETED])
        total_steps = len(workflow.steps)

        return {
            "workflow_id": workflow.id,
            "workflow_name": workflow.name,
            "status": workflow.status.value,
            "progress": completed_steps / total_steps if total_steps > 0 else 0,
            "steps_total": total_steps,
            "steps_completed": completed_steps,
            "steps_running": len([s for s in workflow.steps if s.status == StepStatus.RUNNING]),
            "steps_failed": len([s for s in workflow.steps if s.status == StepStatus.FAILED]),
            "started_at": workflow.started_at.isoformat() if workflow.started_at else None,
            "is_active": workflow.id in self.active_workflows,
        }

    async def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel a running workflow.

        Args:
            workflow_id: Workflow identifier

        Returns:
            True if cancelled, False if not found or already complete

        Examples:
            >>> success = await orchestrator.cancel_workflow(workflow_id)
        """
        workflow = self.workflows.get(workflow_id)
        if not workflow or workflow.is_complete():
            return False

        workflow.status = WorkflowStatus.CANCELLED
        workflow.completed_at = datetime.now()
        self.active_workflows.discard(workflow_id)

        # Mark running/pending steps as skipped
        for step in workflow.steps:
            if step.status in {StepStatus.PENDING, StepStatus.READY, StepStatus.RUNNING}:
                step.status = StepStatus.SKIPPED

        logger.info(f"Cancelled workflow: {workflow.name}")
        return True

    def get_orchestrator_stats(self) -> dict[str, Any]:
        """Get orchestrator statistics.

        Returns:
            Statistics dictionary
        """
        return {
            "total_workflows": len(self.workflows),
            "active_workflows": len(self.active_workflows),
            "completed_workflows": len(
                [w for w in self.workflows.values() if w.status == WorkflowStatus.COMPLETED]
            ),
            "failed_workflows": len(
                [w for w in self.workflows.values() if w.status == WorkflowStatus.FAILED]
            ),
        }
