"""Base agent framework for unistax agent swarm.

Provides core agent classes with:
- Hierarchical team structure
- Task execution
- Inter-agent communication
- Skill-based capabilities
- State management

Integrates with unistax infrastructure:
- unistax.logging for structured logging
- unistax.events for inter-agent messaging
- unistax.queue for task distribution
- unistax.metrics for performance tracking
- unistax.audit for action auditing
"""

import asyncio
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from unistax.events import Event, EventBus
from unistax.logging import get_logger
from unistax.metrics import MetricsManager, timer


# Note: audit decorator has circular import issue in unistax.audit
# Placeholder decorator for now
def audit(action: str):
    """Placeholder audit decorator until circular import is fixed."""

    def decorator(func):
        return func

    return decorator


logger = get_logger(__name__)


class AgentState(Enum):
    """Agent operational states."""

    IDLE = "idle"
    THINKING = "thinking"
    WORKING = "working"
    WAITING = "waiting"
    BLOCKED = "blocked"
    COLLABORATING = "collaborating"
    ERROR = "error"
    SHUTDOWN = "shutdown"


class TaskStatus(Enum):
    """Task execution states."""

    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    WAITING_REVIEW = "waiting_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TeamRole(Enum):
    """Agent roles within a team."""

    LEADER = "leader"  # Team lead, coordinates work
    MEMBER = "member"  # Regular team member
    SPECIALIST = "specialist"  # Domain expert consultant
    OBSERVER = "observer"  # Observes but doesn't execute


@dataclass
class Skill:
    """Agent capability/skill definition.

    Examples:
        >>> sql_skill = Skill("sql", proficiency=0.9, category="database")
        >>> python_skill = Skill("python", proficiency=0.85, category="programming")
    """

    name: str
    proficiency: float  # 0.0 to 1.0
    category: str  # e.g., "database", "ml", "etl"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate skill parameters."""
        if not 0.0 <= self.proficiency <= 1.0:
            raise ValueError(f"Proficiency must be 0.0-1.0, got {self.proficiency}")

    def can_perform(self, required_proficiency: float = 0.5) -> bool:
        """Check if skill meets minimum proficiency requirement."""
        return self.proficiency >= required_proficiency

    def __str__(self) -> str:
        """Return ``name (proficiency)``."""
        return f"{self.name} ({self.proficiency:.2f})"


@dataclass
class Task:
    """Work item for agent execution.

    Examples:
        >>> task = Task(
        ...     type="build_pipeline",
        ...     description="Create customer ETL pipeline",
        ...     required_skills={"sql": 0.7, "etl": 0.8},
        ...     priority=8
        ... )
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    type: str = ""
    description: str = ""
    priority: int = 5  # 1-10, higher = more urgent
    required_skills: dict[str, float] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    deadline: datetime | None = None
    assigned_to: str | None = None
    reviewed_by: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: Any | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    parent_task_id: str | None = None  # For task decomposition
    subtasks: list[str] = field(default_factory=list)

    def duration(self) -> float | None:
        """Calculate task duration in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def is_complete(self) -> bool:
        """Check if task is in a terminal state."""
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        )


@dataclass
class Message:
    """Inter-agent communication message.

    Examples:
        >>> msg = Message(
        ...     from_agent="engineer_1",
        ...     to_agent="analyst_1",
        ...     msg_type="request",
        ...     content={"action": "provide_data", "table": "customers"}
        ... )
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    from_agent: str = ""
    to_agent: str | list[str] = ""  # Single or broadcast
    msg_type: str = ""  # request, response, broadcast, notification
    content: dict[str, Any] = field(default_factory=dict)
    priority: int = 5
    reply_to: str | None = None
    conversation_id: str | None = None
    requires_response: bool = False
    timestamp: datetime = field(default_factory=datetime.now)

    def is_broadcast(self) -> bool:
        """Check if message is broadcast to multiple agents."""
        return isinstance(self.to_agent, list)


# ============================================================================
# Agent-specific Events for EventBus integration
# ============================================================================


@dataclass
class AgentMessageEvent(Event):
    """Event published when an agent sends a message."""

    message: Message = field(default_factory=lambda: Message())


@dataclass
class TaskAssignedEvent(Event):
    """Event published when a task is assigned to an agent."""

    task_id: str = ""
    agent_id: str = ""
    task_type: str = ""


@dataclass
class TaskCompletedEvent(Event):
    """Event published when an agent completes a task."""

    task_id: str = ""
    agent_id: str = ""
    task_type: str = ""
    duration_seconds: float = 0.0
    success: bool = True


@dataclass
class TaskFailedEvent(Event):
    """Event published when a task fails."""

    task_id: str = ""
    agent_id: str = ""
    task_type: str = ""
    error: str = ""


@dataclass
class AgentStateChangeEvent(Event):
    """Event published when an agent changes state."""

    agent_id: str = ""
    old_state: str = ""
    new_state: str = ""


@dataclass
class CollaborationRequestEvent(Event):
    """Event published when an agent requests collaboration."""

    requester_id: str = ""
    required_skills: dict[str, float] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)


class Agent(ABC):
    """Base class for all agents in the swarm.

    Agents are autonomous entities that:
    - Execute tasks based on their skills
    - Communicate with other agents
    - Collaborate in teams
    - Learn from experience
    - Make decisions autonomously

    Security:
        - Agents authenticate using JWT tokens (from unistax.security)
        - Rate limiting prevents message spam (from unistax.ratelimit)
        - Secrets managed securely (from unistax.secrets)
    """

    def __init__(
        self,
        agent_id: str,
        persona: str,
        skills: list[Skill],
        event_bus: EventBus | None = None,
        metrics_manager: MetricsManager | None = None,
        team_id: str | None = None,
        team_role: TeamRole = TeamRole.MEMBER,
        max_concurrent_tasks: int = 3,
        max_history: int = 1000,
    ):
        """Initialize agent.

        Args:
            agent_id: Unique identifier for agent
            persona: Agent type (e.g., "data_engineer", "data_analyst")
            skills: List of agent capabilities
            event_bus: Shared EventBus for inter-agent communication
            metrics_manager: Shared MetricsManager for performance tracking
            team_id: Team this agent belongs to
            team_role: Role within the team
            max_concurrent_tasks: Maximum parallel tasks
            max_history: Finished tasks to remember (oldest are dropped). Used for
                experience-based confidence; counters in ``metrics`` are unaffected.
        """
        self.agent_id = agent_id
        self.persona = persona
        self.skills = {s.name: s for s in skills}
        self.team_id = team_id
        self.team_role = team_role
        self.max_concurrent_tasks = max_concurrent_tasks

        # State management
        self.state = AgentState.IDLE
        self.current_tasks: list[Task] = []
        self.task_history: deque[Task] = deque(maxlen=max(1, max_history))
        self.start_time = datetime.now()

        # Communication via unistax.events
        self.event_bus = event_bus or EventBus()
        self.inbox: asyncio.Queue[Message] = asyncio.Queue()
        self.message_handlers: dict[str, Callable] = self._setup_message_handlers()

        # Subscribe to agent messages on event bus
        if self.event_bus:
            self._subscribe_to_events()

        # Metrics via unistax.metrics
        self.metrics_manager = metrics_manager
        self._metrics_prefix = f"agent.{agent_id}"

        # Collaboration
        self.team_members: set[str] = set()
        self.subordinates: set[str] = set()  # For hierarchical teams
        self.manager: str | None = None  # For hierarchical teams
        self.reputation: float = 1.0  # Peer rating, adjusted by feedback

        # Memory and learning
        self.short_term_memory: dict[str, Any] = {}
        self.observations: list[dict[str, Any]] = []

        # References to shared systems (injected by registry)
        self.knowledge_graph: Any = None
        self.blackboard: Any = None
        # Async callback ``(nodes, edges)`` that stores graph changes durably (set by the host).
        self.knowledge_persister: Callable[[list[Any], list[Any]], Awaitable[None]] | None = None

        # Local metrics counters (also tracked in MetricsManager if available)
        self.metrics = {
            "tasks_completed": 0,
            "tasks_failed": 0,
            "tasks_helped_with": 0,
            "messages_sent": 0,
            "messages_received": 0,
            "collaborations": 0,
        }

        logger.info(
            f"Agent {agent_id} ({persona}) initialized: "
            f"{len(skills)} skills, team={team_id}, role={team_role.value}"
        )

    def _setup_message_handlers(self) -> dict[str, Callable]:
        """Setup default message handlers.

        Can be overridden by subclasses to add custom handlers.
        """
        return {
            "request": self._handle_request,
            "response": self._handle_response,
            "broadcast": self._handle_broadcast,
            "notification": self._handle_notification,
            "task_assignment": self._handle_task_assignment,
            "help_request": self._handle_help_request,
            "peer_review": self._handle_peer_review,
        }

    def _subscribe_to_events(self):
        """Subscribe to relevant events on the event bus."""
        self._event_subscriptions: list[tuple[type, Callable]] = []

        def _sub(event_type: type) -> Callable:
            def decorator(func: Callable) -> Callable:
                self.event_bus.subscribe(event_type)(func)
                self._event_subscriptions.append((event_type, func))
                return func

            return decorator

        @_sub(AgentMessageEvent)
        async def on_agent_message(event: AgentMessageEvent):
            """Handle messages sent via event bus."""
            msg = event.message
            # Only process messages intended for this agent
            if msg.to_agent == self.agent_id or (
                isinstance(msg.to_agent, list) and self.agent_id in msg.to_agent
            ):
                await self.receive_message(msg)

        @_sub(TaskAssignedEvent)
        async def on_task_assigned(event: TaskAssignedEvent):
            """Handle task assignment events."""
            if event.agent_id == self.agent_id:
                logger.debug(f"{self.agent_id} notified of task assignment: {event.task_id}")

        @_sub(CollaborationRequestEvent)
        async def on_collaboration_request(event: CollaborationRequestEvent):
            """Handle collaboration requests."""
            # Check if this agent can help with the requested skills
            can_help = all(
                skill in self.skills and self.skills[skill].proficiency >= prof
                for skill, prof in event.required_skills.items()
            )
            if can_help and event.requester_id != self.agent_id:
                logger.info(
                    f"{self.agent_id} can help {event.requester_id} with "
                    f"{list(event.required_skills.keys())}"
                )

    def _track_counter(self, name: str) -> None:
        """Increment a metric; reporting problems must never affect task outcome."""
        if not self.metrics_manager:
            return
        try:
            self.metrics_manager.counter(f"{self._metrics_prefix}.{name}")
        except Exception:
            logger.warning("Failed to record metric %s", name, exc_info=True)

    def _track_histogram(self, name: str, value: float) -> None:
        if not self.metrics_manager:
            return
        try:
            self.metrics_manager.histogram(f"{self._metrics_prefix}.{name}", value)
        except Exception:
            logger.warning("Failed to record metric %s", name, exc_info=True)

    def unsubscribe_from_events(self) -> None:
        """Detach this agent's handlers from the event bus.

        Must be called when an agent is discarded, otherwise the bus keeps the
        agent (and its inbox) alive and keeps delivering messages to it.
        """
        for event_type, handler in getattr(self, "_event_subscriptions", []):
            self.event_bus.unsubscribe(event_type, handler)
        self._event_subscriptions = []

    def can_do(self, task: Task, check_capacity: bool = True) -> tuple[bool, float]:
        """Check if agent can perform task.

        Args:
            task: Task to evaluate
            check_capacity: Reject when the agent is already at its concurrency
                limit (pass False when tasks are queued for later execution)

        Returns:
            (can_do, confidence_score)

        Examples:
            >>> agent = DataEngineerAgent("eng_1")
            >>> task = Task(type="sql_query", required_skills={"sql": 0.7})
            >>> can_do, confidence = agent.can_do(task)
            >>> print(f"Can do: {can_do}, Confidence: {confidence:.2f}")
        """
        # Check if has required skills
        for skill_name, min_prof in task.required_skills.items():
            if skill_name not in self.skills:
                logger.debug(f"{self.agent_id} missing skill: {skill_name} for task {task.id}")
                return False, 0.0
            if not self.skills[skill_name].can_perform(min_prof):
                logger.debug(
                    f"{self.agent_id} insufficient proficiency in {skill_name} "
                    f"({self.skills[skill_name].proficiency} < {min_prof})"
                )
                return False, 0.0

        # Check capacity
        if check_capacity and len(self.current_tasks) >= self.max_concurrent_tasks:
            logger.debug(f"{self.agent_id} at capacity ({self.max_concurrent_tasks} tasks)")
            return False, 0.0

        # Calculate confidence (weighted average of skill match)
        if task.required_skills:
            confidence = sum(
                self.skills[skill].proficiency * weight
                for skill, weight in task.required_skills.items()
            ) / sum(task.required_skills.values())
        else:
            confidence = 0.5

        # Adjust confidence based on experience
        relevant_history = [
            t for t in self.task_history if t.type == task.type and t.status == TaskStatus.COMPLETED
        ]
        if relevant_history:
            success_rate = len(relevant_history) / (len(relevant_history) + 1)
            confidence = (confidence + success_rate) / 2

        return True, confidence

    async def record_knowledge(self, nodes: Iterable[Any], edges: Iterable[Any]) -> str:
        """Share what this agent learned through the knowledge graph.

        Args:
            nodes: Objects with ``id``, ``node_type`` and ``properties`` (created or updated)
            edges: Objects with ``source``, ``target``, ``relation`` and ``properties``
                (added only if that relationship does not already exist)

        Returns:
            ``"updated"``, ``"not_attached"`` (no graph is connected), or ``"failed"``.
            Never raises: recording knowledge must not fail the task that produced it.
        """
        graph = self.knowledge_graph
        if graph is None:
            return "not_attached"
        from unistax.agents.intelligence.knowledge_graph import NodeType, RelationType

        try:
            changed_nodes = [
                graph.add_node(
                    n.id, NodeType(n.node_type), dict(n.properties), agent_id=self.agent_id
                )
                for n in nodes
            ]
            new_edges = []
            for e in edges:
                relation = RelationType(e.relation)
                existing = graph.get_outgoing_edges(e.source, relation)
                if any(x.target_id == e.target for x in existing):
                    continue
                new_edges.append(
                    graph.add_edge(
                        e.source, e.target, relation, dict(e.properties), agent_id=self.agent_id
                    )
                )
            if self.knowledge_persister is not None:
                await self.knowledge_persister(changed_nodes, new_edges)
        except Exception:
            logger.warning("%s could not record knowledge", self.agent_id, exc_info=True)
            return "failed"
        return "updated"

    async def receive_message(self, message: Message):
        """Receive message from another agent or system."""
        await self.inbox.put(message)
        self.metrics["messages_received"] += 1
        logger.debug(f"{self.agent_id} received {message.msg_type} from {message.from_agent}")

    async def send_message(
        self,
        to_agent: str | list[str],
        msg_type: str,
        content: dict[str, Any],
        priority: int = 5,
        requires_response: bool = False,
    ):
        """Send message to another agent via event bus.

        Args:
            to_agent: Target agent ID or list of IDs for broadcast
            msg_type: Message type (request, response, broadcast, etc.)
            content: Message payload
            priority: Message priority (1-10)
            requires_response: Whether response is expected
        """
        message = Message(
            from_agent=self.agent_id,
            to_agent=to_agent,
            msg_type=msg_type,
            content=content,
            priority=priority,
            requires_response=requires_response,
        )

        # Publish message via event bus
        if self.event_bus:
            await self.event_bus.publish(AgentMessageEvent(message=message))
            self.metrics["messages_sent"] += 1

            self._track_counter("messages_sent")

            logger.debug(f"{self.agent_id} sent {msg_type} to {to_agent}")
        else:
            logger.warning(f"{self.agent_id} has no event bus configured")

    async def broadcast_to_team(self, msg_type: str, content: dict[str, Any]):
        """Broadcast message to all team members."""
        if self.team_members:
            await self.send_message(
                to_agent=list(self.team_members),
                msg_type=msg_type,
                content=content,
            )

    async def process_messages(self):
        """Process all pending messages in inbox."""
        processed = 0
        while not self.inbox.empty() and processed < 10:  # Limit batch size
            try:
                message = await asyncio.wait_for(self.inbox.get(), timeout=0.1)

                # Route to appropriate handler
                handler = self.message_handlers.get(message.msg_type, self._default_message_handler)
                await handler(message)
                processed += 1

            except asyncio.TimeoutError:
                break
            except Exception as e:
                logger.error(
                    f"{self.agent_id} error processing message: {e}",
                    exc_info=True,
                )

    async def _default_message_handler(self, message: Message):
        """Default handler for unrecognized message types."""
        logger.warning(f"{self.agent_id} received unhandled message type: {message.msg_type}")

    async def _handle_request(self, message: Message):
        """Handle request from another agent."""
        logger.info(
            f"{self.agent_id} handling request from {message.from_agent}: "
            f"{message.content.get('action', 'unknown')}"
        )
        # To be implemented by subclasses
        pass

    async def _handle_response(self, message: Message):
        """Handle response to a previous request."""
        logger.debug(f"{self.agent_id} received response to {message.reply_to}")
        # To be implemented by subclasses
        pass

    async def _handle_broadcast(self, message: Message):
        """Handle broadcast message."""
        logger.debug(f"{self.agent_id} received broadcast: {message.content.get('topic')}")
        # To be implemented by subclasses
        pass

    async def _handle_notification(self, message: Message):
        """Handle notification message."""
        logger.debug(f"{self.agent_id} received notification")
        # To be implemented by subclasses
        pass

    async def _handle_task_assignment(self, message: Message):
        """Handle task assignment from manager or orchestrator."""
        task_data = message.content.get("task")
        if task_data:
            # Convert dict to Task object
            task = Task(**task_data)
            await self.accept_task(task)

    async def _handle_help_request(self, message: Message):
        """Handle help request from another agent."""
        logger.info(f"{self.agent_id} received help request from {message.from_agent}")
        # To be implemented by subclasses based on capabilities
        pass

    async def _handle_peer_review(self, message: Message):
        """Handle peer review request."""
        logger.info(f"{self.agent_id} received peer review request")
        # To be implemented by subclasses
        pass

    @audit(action="task_accepted")
    async def accept_task(self, task: Task):
        """Accept and queue a task for execution."""
        if len(self.current_tasks) >= self.max_concurrent_tasks:
            logger.warning(f"{self.agent_id} cannot accept task {task.id}: at capacity")
            return False

        task.assigned_to = self.agent_id
        task.status = TaskStatus.ASSIGNED
        self.current_tasks.append(task)

        # Publish task assignment event
        if self.event_bus:
            await self.event_bus.publish(
                TaskAssignedEvent(
                    task_id=task.id,
                    agent_id=self.agent_id,
                    task_type=task.type,
                )
            )

        logger.info(f"{self.agent_id} accepted task {task.id}: {task.description}")
        return True

    @abstractmethod
    async def decide(self) -> str | None:
        """Decide what action to take next.

        This is the "think" phase of the agent's cognitive cycle.
        Agents evaluate their current state, tasks, messages, and
        environment to decide the next action.

        Returns:
            Action identifier or None if nothing to do

        Examples:
            >>> return "execute_task:task_123"
            >>> return "request_help:agent_456"
            >>> return "proactive_monitor"
            >>> return None  # Nothing to do
        """
        pass

    @abstractmethod
    async def execute_task(self, task: Task) -> Any:
        """Execute a specific task.

        Args:
            task: Task to execute

        Returns:
            Task result

        Raises:
            Exception: If task execution fails
        """
        pass

    async def run(self):
        """Main agent execution loop.

        This is the agent's cognitive cycle:
        1. Sense: Process messages and environment
        2. Think: Decide what to do
        3. Act: Execute decision
        """
        logger.info(f"Agent {self.agent_id} starting main loop...")

        try:
            while self.state != AgentState.SHUTDOWN:
                try:
                    # 1. SENSE: Process messages
                    await self.process_messages()

                    # 2. THINK: Decide what to do
                    action = await self.decide()

                    # 3. ACT: Execute decision
                    if action:
                        await self._execute_action(action)
                    else:
                        self.state = AgentState.IDLE

                    # Small delay to prevent busy-waiting
                    await asyncio.sleep(0.1)

                except Exception as e:
                    logger.error(
                        f"Agent {self.agent_id} error in main loop: {e}",
                        exc_info=True,
                    )
                    self.state = AgentState.ERROR
                    await asyncio.sleep(1)  # Back off on error

        finally:
            logger.info(f"Agent {self.agent_id} shutting down...")
            await self._cleanup()

    async def _execute_action(self, action: str):
        """Execute a decided action.

        Args:
            action: Action string (e.g., "execute_task:task_123")
        """
        action_type, *params = action.split(":", 1)

        if action_type == "execute_task":
            task_id = params[0] if params else None
            if task_id:
                task = next((t for t in self.current_tasks if t.id == task_id), None)
                if task:
                    await self._run_task(task)

        elif action_type == "request_help":
            agent_id = params[0] if params else None
            if agent_id:
                await self.send_message(
                    to_agent=agent_id,
                    msg_type="help_request",
                    content={"requester": self.agent_id},
                )

        # Additional action types to be implemented
        else:
            logger.warning(f"{self.agent_id} unknown action type: {action_type}")

    async def run_task(self, task: Task) -> Task:
        """Run an accepted task through the full lifecycle.

        Handles state transitions, metrics and events. Failures are recorded on
        the task (status/error) rather than raised.
        """
        await self._run_task(task)
        return task

    def release_task(self, task: Task, status: TaskStatus = TaskStatus.CANCELLED) -> None:
        """Drop a task from the active list (e.g. after external cancellation)."""
        if task in self.current_tasks:
            self.current_tasks.remove(task)
        if not task.is_complete():
            task.status = status
            task.completed_at = datetime.now()
        if not self.current_tasks and self.state == AgentState.WORKING:
            self.state = AgentState.IDLE

    @timer(name="task_execution")
    async def _run_task(self, task: Task):
        """Execute a task with proper state management and error handling."""
        old_state = self.state
        self.state = AgentState.WORKING
        task.status = TaskStatus.IN_PROGRESS
        task.started_at = datetime.now()

        # Publish state change event
        if self.event_bus:
            await self.event_bus.publish(
                AgentStateChangeEvent(
                    agent_id=self.agent_id,
                    old_state=old_state.value,
                    new_state=self.state.value,
                )
            )

        try:
            logger.info(f"{self.agent_id} starting task {task.id}: {task.description}")
            result = await self.execute_task(task)

            task.result = result
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()

            self.metrics["tasks_completed"] += 1
            self.task_history.append(task)
            self.current_tasks.remove(task)

            self._track_counter("tasks_completed")
            self._track_histogram("task_duration", task.duration() or 0.0)

            # Publish completion event
            if self.event_bus:
                await self.event_bus.publish(
                    TaskCompletedEvent(
                        task_id=task.id,
                        agent_id=self.agent_id,
                        task_type=task.type,
                        duration_seconds=task.duration() or 0.0,
                        success=True,
                    )
                )

            logger.info(f"{self.agent_id} completed task {task.id} in " f"{task.duration():.2f}s")

        except Exception as e:
            logger.error(f"{self.agent_id} task {task.id} failed: {e}", exc_info=True)
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now()

            self.metrics["tasks_failed"] += 1
            self.task_history.append(task)
            self.current_tasks.remove(task)

            self._track_counter("tasks_failed")

            # Publish failure event
            if self.event_bus:
                await self.event_bus.publish(
                    TaskFailedEvent(
                        task_id=task.id,
                        agent_id=self.agent_id,
                        task_type=task.type,
                        error=str(e),
                    )
                )

        finally:
            await self._return_to_idle()

    async def _return_to_idle(self) -> None:
        """Leave WORKING once no tasks remain (the run loop does this itself)."""
        if self.current_tasks or self.state != AgentState.WORKING:
            return
        self.state = AgentState.IDLE
        if self.event_bus:
            await self.event_bus.publish(
                AgentStateChangeEvent(
                    agent_id=self.agent_id,
                    old_state=AgentState.WORKING.value,
                    new_state=AgentState.IDLE.value,
                )
            )

    async def _cleanup(self):
        """Cleanup resources before shutdown."""
        # Cancel remaining tasks
        for task in self.current_tasks:
            task.status = TaskStatus.CANCELLED

        # Clear queues
        while not self.inbox.empty():
            try:
                self.inbox.get_nowait()
            except asyncio.QueueEmpty:
                break

    def get_metrics(self) -> dict[str, Any]:
        """Get agent performance metrics."""
        uptime = (datetime.now() - self.start_time).total_seconds()
        total_tasks = self.metrics["tasks_completed"] + self.metrics["tasks_failed"]
        success_rate = self.metrics["tasks_completed"] / total_tasks if total_tasks > 0 else 0.0

        return {
            **self.metrics,
            "uptime_seconds": uptime,
            "success_rate": success_rate,
            "current_tasks": len(self.current_tasks),
            "state": self.state.value,
            "reputation": self.reputation,
        }

    def __repr__(self) -> str:
        """Return a concise debug representation."""
        return (
            f"Agent(id={self.agent_id}, persona={self.persona}, "
            f"state={self.state.value}, tasks={len(self.current_tasks)})"
        )
