"""Agent Swarm Module.

Provides autonomous agents for data platform operations with:
- Hierarchical team structures
- Inter-agent communication via EventBus
- Task execution with skill-based matching
- Metrics and audit logging
- Proactive and reactive behaviors

Integrates with unistax infrastructure:
- unistax.logging for structured logging
- unistax.events for inter-agent messaging
- unistax.queue for task distribution
- unistax.metrics for performance tracking
- unistax.audit for action auditing
- unistax.security for JWT authentication
- unistax.ratelimit for message rate limiting
- unistax.secrets for secure credential management
"""

from unistax.agents.base import (
    Agent,
    AgentMessageEvent,
    AgentState,
    AgentStateChangeEvent,
    CollaborationRequestEvent,
    Message,
    Skill,
    Task,
    TaskAssignedEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
    TaskStatus,
    TeamRole,
)

# Intelligence features
from unistax.agents.intelligence import (
    AgentKnowledgeGraph,
    AgentRLPolicy,
    AntColonyOptimizer,
    HTNAgent,
    HTNPlanner,
    ParticleSwarmOptimizer,
    RLAgent,
    SwarmAgent,
)
from unistax.agents.orchestrator import (
    AgentOrchestrator,
    StepStatus,
    Workflow,
    WorkflowStatus,
    WorkflowStep,
)
from unistax.agents.personas.data_analyst import DataAnalystAgent
from unistax.agents.personas.data_engineer import DataEngineerAgent
from unistax.agents.personas.data_scientist import DataScientistAgent
from unistax.agents.personas.data_steward import DataStewardAgent
from unistax.agents.registry import AgentRegistry
from unistax.agents.team import Team, TeamHierarchy, TeamType

# Optional Celery integration (requires celery package)
try:
    from unistax.agents.task_integration import AgentTaskQueue, AgentTaskScheduler

    _HAS_CELERY = True
except ImportError:
    AgentTaskQueue = None  # type: ignore
    AgentTaskScheduler = None  # type: ignore
    _HAS_CELERY = False

__all__ = [
    # Base agent classes
    "Agent",
    "AgentState",
    "Skill",
    "Task",
    "TaskStatus",
    "Message",
    "TeamRole",
    # Events
    "AgentMessageEvent",
    "TaskAssignedEvent",
    "TaskCompletedEvent",
    "TaskFailedEvent",
    "AgentStateChangeEvent",
    "CollaborationRequestEvent",
    # Team classes
    "Team",
    "TeamType",
    "TeamHierarchy",
    # Registry
    "AgentRegistry",
    # Task Integration
    "AgentTaskQueue",
    "AgentTaskScheduler",
    # Orchestration
    "AgentOrchestrator",
    "Workflow",
    "WorkflowStatus",
    "WorkflowStep",
    "StepStatus",
    # Personas
    "DataEngineerAgent",
    "DataAnalystAgent",
    "DataScientistAgent",
    "DataStewardAgent",
    # Intelligence
    "AgentRLPolicy",
    "RLAgent",
    "AgentKnowledgeGraph",
    "HTNPlanner",
    "HTNAgent",
    "AntColonyOptimizer",
    "ParticleSwarmOptimizer",
    "SwarmAgent",
]
