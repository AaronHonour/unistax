"""Tests for base agent framework."""

import asyncio

import pytest

from unistax.agents.base import (
    Agent,
    AgentState,
    Message,
    Skill,
    Task,
    TaskStatus,
    TeamRole,
)
from unistax.events import EventBus


class TestAgent(Agent):
    """Simple test agent implementation."""

    async def decide(self):
        """Simple decision logic."""
        if self.current_tasks:
            return f"execute_task:{self.current_tasks[0].id}"
        return None

    async def execute_task(self, task: Task):
        """Simple task execution."""
        await asyncio.sleep(0.01)  # Simulate work
        return {"status": "completed", "result": "test_result"}


@pytest.mark.unit
@pytest.mark.agents
class TestSkill:
    """Test Skill class."""

    def test_skill_creation(self):
        """Test creating a skill."""
        skill = Skill("python", 0.85, "programming")
        assert skill.name == "python"
        assert skill.proficiency == 0.85
        assert skill.category == "programming"

    def test_skill_proficiency_validation(self):
        """Test skill proficiency validation."""
        with pytest.raises(ValueError, match="Proficiency must be 0.0-1.0"):
            Skill("invalid", 1.5, "test")

        with pytest.raises(ValueError, match="Proficiency must be 0.0-1.0"):
            Skill("invalid", -0.1, "test")

    def test_skill_can_perform(self):
        """Test skill proficiency check."""
        skill = Skill("sql", 0.80, "database")

        assert skill.can_perform(0.70) is True
        assert skill.can_perform(0.80) is True
        assert skill.can_perform(0.90) is False

    def test_skill_string_representation(self):
        """Test skill string representation."""
        skill = Skill("etl", 0.92, "data_engineering")
        assert str(skill) == "etl (0.92)"


@pytest.mark.unit
@pytest.mark.agents
class TestTask:
    """Test Task class."""

    def test_task_creation(self):
        """Test creating a task."""
        task = Task(
            type="test_task",
            description="Test task description",
            priority=7,
            required_skills={"python": 0.8, "sql": 0.7},
        )

        assert task.type == "test_task"
        assert task.description == "Test task description"
        assert task.priority == 7
        assert task.required_skills == {"python": 0.8, "sql": 0.7}
        assert task.status == TaskStatus.PENDING

    def test_task_duration_calculation(self):
        """Test task duration calculation."""
        task = Task(type="test")

        # No duration before started
        assert task.duration() is None

        # Set start and end times
        from datetime import datetime, timedelta

        task.started_at = datetime.now()
        task.completed_at = task.started_at + timedelta(seconds=5)

        duration = task.duration()
        assert duration is not None
        assert 4.9 <= duration <= 5.1  # Allow small timing variations

    def test_task_is_complete(self):
        """Test task completion status check."""
        task = Task(type="test")

        assert task.is_complete() is False

        task.status = TaskStatus.IN_PROGRESS
        assert task.is_complete() is False

        task.status = TaskStatus.COMPLETED
        assert task.is_complete() is True

        task.status = TaskStatus.FAILED
        assert task.is_complete() is True

        task.status = TaskStatus.CANCELLED
        assert task.is_complete() is True


@pytest.mark.unit
@pytest.mark.agents
class TestMessage:
    """Test Message class."""

    def test_message_creation(self):
        """Test creating a message."""
        msg = Message(
            from_agent="agent1",
            to_agent="agent2",
            msg_type="request",
            content={"action": "help"},
            priority=8,
        )

        assert msg.from_agent == "agent1"
        assert msg.to_agent == "agent2"
        assert msg.msg_type == "request"
        assert msg.content == {"action": "help"}
        assert msg.priority == 8

    def test_message_broadcast_detection(self):
        """Test broadcast message detection."""
        # Single recipient
        msg1 = Message(from_agent="a1", to_agent="a2", msg_type="request")
        assert msg1.is_broadcast() is False

        # Multiple recipients
        msg2 = Message(from_agent="a1", to_agent=["a2", "a3", "a4"], msg_type="broadcast")
        assert msg2.is_broadcast() is True


@pytest.mark.unit
@pytest.mark.agents
class TestAgentBase:
    """Test Agent base class."""

    def test_agent_initialization(self):
        """Test agent initialization."""
        skills = [
            Skill("python", 0.90, "programming"),
            Skill("sql", 0.85, "database"),
        ]

        agent = TestAgent(
            agent_id="test_001",
            persona="test_agent",
            skills=skills,
            team_id="team_1",
            team_role=TeamRole.MEMBER,
            max_concurrent_tasks=5,
        )

        assert agent.agent_id == "test_001"
        assert agent.persona == "test_agent"
        assert len(agent.skills) == 2
        assert "python" in agent.skills
        assert "sql" in agent.skills
        assert agent.team_id == "team_1"
        assert agent.team_role == TeamRole.MEMBER
        assert agent.max_concurrent_tasks == 5
        assert agent.state == AgentState.IDLE

    def test_agent_with_event_bus(self):
        """Test agent with shared event bus."""
        event_bus = EventBus()
        skills = [Skill("python", 0.90, "programming")]

        agent = TestAgent(
            agent_id="test_001",
            persona="test_agent",
            skills=skills,
            event_bus=event_bus,
        )

        assert agent.event_bus is event_bus

    def test_agent_can_do_task(self):
        """Test agent task capability checking."""
        skills = [
            Skill("python", 0.90, "programming"),
            Skill("sql", 0.85, "database"),
        ]

        agent = TestAgent(
            agent_id="test_001",
            persona="test_agent",
            skills=skills,
        )

        # Task with matching skills
        task1 = Task(
            type="data_processing",
            required_skills={"python": 0.80, "sql": 0.70},
        )
        can_do, confidence = agent.can_do(task1)
        assert can_do is True
        assert 0.8 <= confidence <= 0.95

        # Task with missing skill
        task2 = Task(
            type="ml_model",
            required_skills={"python": 0.80, "ml": 0.90},
        )
        can_do, confidence = agent.can_do(task2)
        assert can_do is False
        assert confidence == 0.0

        # Task with insufficient proficiency
        task3 = Task(
            type="advanced_sql",
            required_skills={"sql": 0.95},
        )
        can_do, confidence = agent.can_do(task3)
        assert can_do is False
        assert confidence == 0.0

    def test_agent_at_capacity(self):
        """Test agent capacity limits."""
        skills = [Skill("python", 0.90, "programming")]

        agent = TestAgent(
            agent_id="test_001",
            persona="test_agent",
            skills=skills,
            max_concurrent_tasks=2,
        )

        # Add tasks up to capacity
        task1 = Task(type="task1", required_skills={"python": 0.80})
        task2 = Task(type="task2", required_skills={"python": 0.80})
        task3 = Task(type="task3", required_skills={"python": 0.80})

        # First two tasks should succeed
        can_do1, _ = agent.can_do(task1)
        assert can_do1 is True
        agent.current_tasks.append(task1)

        can_do2, _ = agent.can_do(task2)
        assert can_do2 is True
        agent.current_tasks.append(task2)

        # Third task should fail (at capacity)
        can_do3, _ = agent.can_do(task3)
        assert can_do3 is False

    @pytest.mark.asyncio
    async def test_agent_accept_task(self):
        """Test agent task acceptance."""
        skills = [Skill("python", 0.90, "programming")]
        event_bus = EventBus()

        agent = TestAgent(
            agent_id="test_001",
            persona="test_agent",
            skills=skills,
            event_bus=event_bus,
        )

        task = Task(type="test_task", description="Test task")

        result = await agent.accept_task(task)

        assert result is True
        assert task.status == TaskStatus.ASSIGNED
        assert task.assigned_to == "test_001"
        assert task in agent.current_tasks

    @pytest.mark.asyncio
    async def test_agent_reject_task_at_capacity(self):
        """Test agent rejects tasks when at capacity."""
        skills = [Skill("python", 0.90, "programming")]

        agent = TestAgent(
            agent_id="test_001",
            persona="test_agent",
            skills=skills,
            max_concurrent_tasks=1,
        )

        task1 = Task(type="task1")
        task2 = Task(type="task2")

        # Accept first task
        result1 = await agent.accept_task(task1)
        assert result1 is True

        # Reject second task (at capacity)
        result2 = await agent.accept_task(task2)
        assert result2 is False

    @pytest.mark.asyncio
    async def test_agent_message_sending(self):
        """Test agent message sending via event bus."""
        event_bus = EventBus()
        received_messages = []

        # Subscribe to messages
        from unistax.agents.base import AgentMessageEvent

        @event_bus.subscribe(AgentMessageEvent)
        async def capture_message(event):
            received_messages.append(event.message)

        # Create agent
        skills = [Skill("python", 0.90, "programming")]
        agent = TestAgent(
            agent_id="test_001",
            persona="test_agent",
            skills=skills,
            event_bus=event_bus,
        )

        # Send message
        await agent.send_message(
            to_agent="test_002",
            msg_type="request",
            content={"action": "help"},
        )

        # Wait for event processing
        await asyncio.sleep(0.01)

        # Verify message was sent
        assert len(received_messages) == 1
        msg = received_messages[0]
        assert msg.from_agent == "test_001"
        assert msg.to_agent == "test_002"
        assert msg.msg_type == "request"
        assert msg.content == {"action": "help"}

    @pytest.mark.asyncio
    async def test_agent_message_receiving(self):
        """Test agent message receiving."""
        skills = [Skill("python", 0.90, "programming")]

        agent = TestAgent(
            agent_id="test_001",
            persona="test_agent",
            skills=skills,
        )

        msg = Message(
            from_agent="test_002",
            to_agent="test_001",
            msg_type="request",
            content={"action": "collaborate"},
        )

        await agent.receive_message(msg)

        assert agent.inbox.qsize() == 1
        assert agent.metrics["messages_received"] == 1

    def test_agent_metrics(self):
        """Test agent metrics tracking."""
        skills = [Skill("python", 0.90, "programming")]

        agent = TestAgent(
            agent_id="test_001",
            persona="test_agent",
            skills=skills,
        )

        metrics = agent.get_metrics()

        assert "tasks_completed" in metrics
        assert "tasks_failed" in metrics
        assert "success_rate" in metrics
        assert "uptime_seconds" in metrics
        assert "current_tasks" in metrics
        assert "state" in metrics
        assert metrics["state"] == "idle"

    def test_agent_representation(self):
        """Test agent string representation."""
        skills = [Skill("python", 0.90, "programming")]

        agent = TestAgent(
            agent_id="test_001",
            persona="test_agent",
            skills=skills,
        )

        repr_str = repr(agent)
        assert "test_001" in repr_str
        assert "test_agent" in repr_str
        assert "idle" in repr_str
