"""Agent Intelligence Module.

Provides advanced intelligence capabilities for autonomous agents:
- Reinforcement Learning (Q-learning) for decision making
- Knowledge Graph for collaborative learning and knowledge sharing
- HTN (Hierarchical Task Network) planning for task decomposition
- Swarm Intelligence (ACO, PSO) for optimization and pathfinding

These intelligence features enable agents to:
- Learn optimal behaviors from experience (RL)
- Share knowledge and best practices (Knowledge Graph)
- Plan complex multi-step tasks (HTN)
- Solve optimization problems collaboratively (Swarm)
"""

from unistax.agents.intelligence.htn_planner import (
    HTNAgent,
    HTNMethod,
    HTNOperator,
    HTNPlan,
    HTNPlanner,
    HTNTask,
    PlanStatus,
    TaskType,
)
from unistax.agents.intelligence.knowledge_graph import (
    AgentKnowledgeGraph,
    KnowledgeEdge,
    KnowledgeNode,
    NodeType,
    RelationType,
)
from unistax.agents.intelligence.rl_policy import (
    AgentRLPolicy,
    Experience,
    RLAgent,
)
from unistax.agents.intelligence.swarm import (
    ACOAnt,
    ACOEdge,
    AntColonyOptimizer,
    Particle,
    ParticleSwarmOptimizer,
    SwarmAgent,
)

__all__ = [
    # Reinforcement Learning
    "AgentRLPolicy",
    "Experience",
    "RLAgent",
    # Knowledge Graph
    "AgentKnowledgeGraph",
    "KnowledgeNode",
    "KnowledgeEdge",
    "NodeType",
    "RelationType",
    # HTN Planning
    "HTNPlanner",
    "HTNTask",
    "HTNMethod",
    "HTNOperator",
    "HTNPlan",
    "HTNAgent",
    "TaskType",
    "PlanStatus",
    # Swarm Intelligence
    "AntColonyOptimizer",
    "ACOAnt",
    "ACOEdge",
    "ParticleSwarmOptimizer",
    "Particle",
    "SwarmAgent",
]
