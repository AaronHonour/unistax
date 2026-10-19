"""Integration between agent framework and unistax.tasks.

Provides:
- Celery task wrappers for agent task execution
- Task queue management for agent workloads
- Task prioritization and scheduling
- Result tracking and callbacks
"""

from typing import Any

from unistax.agents.base import Task, TaskStatus
from unistax.agents.registry import AgentRegistry
from unistax.logging import get_logger
from unistax.tasks import CeleryManager, task

logger = get_logger(__name__)


class AgentTaskQueue:
    """Manages task queue integration for agents.

    Connects the agent framework with unistax.tasks (Celery) to enable:
    - Distributed task execution across multiple workers
    - Task prioritization and scheduling
    - Retry logic and error handling
    - Result storage and callbacks

    Examples:
        >>> # Create task queue with Celery
        >>> celery = CeleryManager(broker="redis://localhost:6379")
        >>> task_queue = AgentTaskQueue(registry, celery)
        >>>
        >>> # Submit task to queue
        >>> task = Task(type="build_pipeline", ...)
        >>> task_id = task_queue.submit_task("eng_001", task)
        >>>
        >>> # Check status
        >>> status = task_queue.get_task_status(task_id)
    """

    def __init__(
        self,
        registry: AgentRegistry,
        celery_manager: CeleryManager | None = None,
    ):
        """Initialize agent task queue.

        Args:
            registry: Agent registry for agent lookup
            celery_manager: Optional Celery manager (creates if None)
        """
        self.registry = registry
        self.celery = celery_manager or CeleryManager()

        # Task tracking
        self.pending_tasks: dict[str, tuple[str, Task]] = {}  # task_id -> (agent_id, task)
        self.results: dict[str, Any] = {}  # task_id -> result

        logger.info("Agent task queue initialized")

    def submit_task(
        self,
        agent_id: str,
        task: Task,
        priority: int = 5,
        countdown: int | None = None,
    ) -> str:
        """Submit a task to the queue for agent execution.

        Args:
            agent_id: ID of agent to execute task
            task: Task to execute
            priority: Task priority (1-10, higher = more urgent)
            countdown: Delay in seconds before execution

        Returns:
            Celery task ID

        Raises:
            ValueError: If agent not found

        Examples:
            >>> task = Task(type="analyze_data", ...)
            >>> task_id = queue.submit_task("analyst_001", task, priority=8)
        """
        agent = self.registry.get(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} not found in registry")

        # Check if agent can do task
        can_do, confidence = agent.can_do(task)
        if not can_do:
            logger.warning(
                f"Agent {agent_id} cannot execute task {task.id} "
                f"(missing skills or at capacity)"
            )
            raise ValueError(f"Agent {agent_id} cannot execute task {task.type}")

        logger.info(
            f"Submitting task {task.id} to agent {agent_id} "
            f"(confidence: {confidence:.2%}, priority: {priority})"
        )

        # Submit to Celery with priority
        celery_task = execute_agent_task.apply_async(
            args=[agent_id, task.id, task.type, task.context],
            priority=priority,
            countdown=countdown,
        )

        # Track task
        self.pending_tasks[celery_task.id] = (agent_id, task)

        return celery_task.id

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        """Get status of a submitted task.

        Args:
            task_id: Celery task ID

        Returns:
            Task status dictionary

        Examples:
            >>> status = queue.get_task_status(task_id)
            >>> print(status["state"])  # PENDING, SUCCESS, FAILURE
        """
        result = self.celery.app.AsyncResult(task_id)

        status = {
            "task_id": task_id,
            "state": result.state,
            "ready": result.ready(),
            "successful": result.successful() if result.ready() else None,
            "failed": result.failed() if result.ready() else None,
        }

        if task_id in self.pending_tasks:
            agent_id, task = self.pending_tasks[task_id]
            status["agent_id"] = agent_id
            status["task_type"] = task.type
            status["task_description"] = task.description

        if result.ready():
            if result.successful():
                status["result"] = result.result
                self.results[task_id] = result.result
            elif result.failed():
                status["error"] = str(result.info)

            # Remove from pending
            self.pending_tasks.pop(task_id, None)

        return status

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending task.

        Args:
            task_id: Celery task ID

        Returns:
            True if cancelled, False if not found or already completed

        Examples:
            >>> success = queue.cancel_task(task_id)
        """
        result = self.celery.app.AsyncResult(task_id)

        if result.ready():
            logger.warning(f"Task {task_id} already completed, cannot cancel")
            return False

        # Revoke task
        result.revoke(terminate=True)

        # Update task status
        if task_id in self.pending_tasks:
            agent_id, task = self.pending_tasks[task_id]
            task.status = TaskStatus.CANCELLED
            self.pending_tasks.pop(task_id)

        logger.info(f"Cancelled task {task_id}")
        return True

    def get_pending_tasks(self, agent_id: str | None = None) -> list[tuple[str, Task]]:
        """Get all pending tasks, optionally filtered by agent.

        Args:
            agent_id: Optional agent ID to filter by

        Returns:
            List of (task_id, task) tuples

        Examples:
            >>> # All pending tasks
            >>> all_tasks = queue.get_pending_tasks()
            >>>
            >>> # Pending tasks for specific agent
            >>> agent_tasks = queue.get_pending_tasks("eng_001")
        """
        if agent_id:
            return [
                (tid, task) for tid, (aid, task) in self.pending_tasks.items() if aid == agent_id
            ]
        return list(self.pending_tasks.values())

    def get_queue_stats(self) -> dict[str, Any]:
        """Get task queue statistics.

        Returns:
            Statistics dictionary

        Examples:
            >>> stats = queue.get_queue_stats()
            >>> print(f"Pending: {stats['pending_tasks']}")
        """
        # Count tasks by agent
        tasks_by_agent: dict[str, int] = {}
        for agent_id, _ in self.pending_tasks.values():
            tasks_by_agent[agent_id] = tasks_by_agent.get(agent_id, 0) + 1

        return {
            "pending_tasks": len(self.pending_tasks),
            "completed_results": len(self.results),
            "tasks_by_agent": tasks_by_agent,
        }


# Celery task for executing agent tasks
@task
def execute_agent_task(
    agent_id: str,
    task_id: str,
    task_type: str,
    task_context: dict[str, Any],
) -> dict[str, Any]:
    """Celery task to execute an agent task.

    This is the Celery worker entry point for agent task execution.

    Args:
        agent_id: Agent to execute task
        task_id: Task identifier
        task_type: Type of task
        task_context: Task context/parameters

    Returns:
        Task execution result

    Note:
        This function is executed by Celery workers, not directly called.
    """
    logger.info(f"Executing task {task_id} for agent {agent_id}")

    # This would need access to the registry to get the agent
    # In a real implementation, you'd need to either:
    # 1. Pass registry as a thread-local or global
    # 2. Reconstruct agent from configuration
    # 3. Use a service locator pattern

    # For now, this is a placeholder that shows the pattern
    try:
        # In production, would execute: await agent.execute_task(task)
        # For now, return success
        return {
            "status": "success",
            "task_id": task_id,
            "agent_id": agent_id,
            "result": "Task executed successfully (placeholder)",
        }

    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}", exc_info=True)
        raise


class AgentTaskScheduler:
    """Scheduler for periodic agent tasks.

    Enables scheduling of recurring agent tasks like:
    - Periodic data quality checks
    - Regular report generation
    - Scheduled pipeline runs
    - Proactive monitoring

    Examples:
        >>> scheduler = AgentTaskScheduler(task_queue)
        >>>
        >>> # Schedule daily report
        >>> scheduler.schedule_recurring(
        ...     agent_id="analyst_001",
        ...     task=Task(type="generate_report", ...),
        ...     schedule="0 9 * * *",  # 9 AM daily
        ... )
    """

    def __init__(self, task_queue: AgentTaskQueue):
        """Initialize agent task scheduler.

        Args:
            task_queue: Agent task queue for submission
        """
        self.task_queue = task_queue
        self.scheduled_tasks: dict[str, dict[str, Any]] = {}

        logger.info("Agent task scheduler initialized")

    def schedule_recurring(
        self,
        agent_id: str,
        task: Task,
        schedule: str,
        name: str | None = None,
    ) -> str:
        """Schedule a recurring task.

        Args:
            agent_id: Agent to execute task
            task: Task template
            schedule: Cron schedule string
            name: Optional name for scheduled task

        Returns:
            Schedule ID

        Examples:
            >>> # Daily at 9 AM
            >>> schedule_id = scheduler.schedule_recurring(
            ...     agent_id="eng_001",
            ...     task=Task(type="quality_check", ...),
            ...     schedule="0 9 * * *",
            ...     name="daily_quality_check",
            ... )
        """
        schedule_id = name or f"scheduled_{agent_id}_{task.type}"

        self.scheduled_tasks[schedule_id] = {
            "agent_id": agent_id,
            "task": task,
            "schedule": schedule,
            "enabled": True,
        }

        logger.info(
            f"Scheduled recurring task {schedule_id} for agent {agent_id} "
            f"(schedule: {schedule})"
        )

        return schedule_id

    def cancel_schedule(self, schedule_id: str) -> bool:
        """Cancel a scheduled task.

        Args:
            schedule_id: Schedule identifier

        Returns:
            True if cancelled, False if not found
        """
        if schedule_id in self.scheduled_tasks:
            self.scheduled_tasks.pop(schedule_id)
            logger.info(f"Cancelled schedule {schedule_id}")
            return True

        logger.warning(f"Schedule {schedule_id} not found")
        return False

    def get_schedules(self, agent_id: str | None = None) -> dict[str, dict[str, Any]]:
        """Get all scheduled tasks, optionally filtered by agent.

        Args:
            agent_id: Optional agent ID to filter by

        Returns:
            Dictionary of schedule_id -> schedule_info
        """
        if agent_id:
            return {
                sid: info
                for sid, info in self.scheduled_tasks.items()
                if info["agent_id"] == agent_id
            }
        return self.scheduled_tasks.copy()
