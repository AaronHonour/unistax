"""Agent Registry for managing agent instances and shared resources.

The registry:
- Maintains a directory of all agents in the swarm
- Provides shared EventBus for inter-agent communication
- Manages team hierarchy
- Routes messages between agents
- Tracks agent availability and status
"""

from typing import Any

from unistax.agents.base import Agent, AgentState, Skill
from unistax.agents.team import Team, TeamHierarchy, TeamType
from unistax.events import EventBus
from unistax.logging import get_logger
from unistax.metrics import MetricsManager

logger = get_logger(__name__)


class AgentRegistry:
    """Central registry for all agents in the swarm.

    Provides:
    - Agent registration and discovery
    - Shared EventBus for communication
    - Shared MetricsManager for tracking
    - Team hierarchy management
    - Agent lookup by ID, persona, skills, or team

    Examples:
        >>> registry = AgentRegistry()
        >>> event_bus = registry.event_bus
        >>> metrics = registry.metrics_manager
        >>>
        >>> # Register an agent
        >>> agent = DataEngineerAgent(
        ...     "eng_1",
        ...     event_bus=event_bus,
        ...     metrics_manager=metrics
        ... )
        >>> registry.register(agent)
        >>>
        >>> # Find agents by skill
        >>> sql_agents = registry.find_by_skill("sql", min_proficiency=0.8)
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        metrics_manager: MetricsManager | None = None,
    ):
        """Initialize agent registry.

        Args:
            event_bus: Shared EventBus instance (creates new if None)
            metrics_manager: Shared MetricsManager instance
        """
        self.event_bus = event_bus or EventBus()
        self.metrics_manager = metrics_manager

        # Agent storage
        self.agents: dict[str, Agent] = {}

        # Team management
        self.team_hierarchy = TeamHierarchy()

        # Agent indexing for fast lookup
        self._agents_by_persona: dict[str, set[str]] = {}
        self._agents_by_team: dict[str, set[str]] = {}
        self._agents_by_skill: dict[str, set[str]] = {}

        logger.info("Agent registry initialized")

    def register(self, agent: Agent):
        """Register an agent in the registry.

        Args:
            agent: Agent instance to register
        """
        if agent.agent_id in self.agents:
            logger.warning(f"Agent {agent.agent_id} already registered, updating...")

        self.agents[agent.agent_id] = agent

        # Index by persona
        if agent.persona not in self._agents_by_persona:
            self._agents_by_persona[agent.persona] = set()
        self._agents_by_persona[agent.persona].add(agent.agent_id)

        # Index by team
        if agent.team_id:
            if agent.team_id not in self._agents_by_team:
                self._agents_by_team[agent.team_id] = set()
            self._agents_by_team[agent.team_id].add(agent.agent_id)

            # Add to team hierarchy
            self.team_hierarchy.add_agent_to_team(agent.agent_id, agent.team_id)

        # Index by skills
        for skill_name in agent.skills:
            if skill_name not in self._agents_by_skill:
                self._agents_by_skill[skill_name] = set()
            self._agents_by_skill[skill_name].add(agent.agent_id)

        logger.info(
            f"Registered agent {agent.agent_id} ({agent.persona}) "
            f"with {len(agent.skills)} skills"
        )

    def unregister(self, agent_id: str):
        """Unregister an agent from the registry.

        Args:
            agent_id: Agent identifier
        """
        if agent_id not in self.agents:
            logger.warning(f"Agent {agent_id} not found in registry")
            return

        agent = self.agents[agent_id]

        # Remove from persona index
        if agent.persona in self._agents_by_persona:
            self._agents_by_persona[agent.persona].discard(agent_id)

        # Remove from team index
        if agent.team_id and agent.team_id in self._agents_by_team:
            self._agents_by_team[agent.team_id].discard(agent_id)

        # Remove from skill index
        for skill_name in agent.skills:
            if skill_name in self._agents_by_skill:
                self._agents_by_skill[skill_name].discard(agent_id)

        # Remove from team membership
        team = self.team_hierarchy.get_agent_team(agent_id)
        if team:
            team.remove_member(agent_id)
            if team.leader_id == agent_id:
                team.leader_id = None
        self.team_hierarchy.agent_to_team.pop(agent_id, None)

        # Stop the agent receiving events
        agent.unsubscribe_from_events()

        # Remove from agents
        del self.agents[agent_id]

        logger.info(f"Unregistered agent {agent_id}")

    def update_agent(
        self,
        agent_id: str,
        team_id: str | None = None,
        set_team: bool = False,
        skills: list[Skill] | None = None,
    ) -> Agent:
        """Change an agent's team and/or skills, keeping all indexes consistent.

        Args:
            agent_id: Agent to update
            team_id: New team (only applied when ``set_team`` is True)
            set_team: Whether to apply ``team_id``
            skills: Replacement skills (unchanged if None)

        Raises:
            KeyError: If the agent is not registered.
        """
        agent = self.agents[agent_id]
        hierarchy = self.team_hierarchy

        for skill_name in agent.skills:
            self._agents_by_skill.get(skill_name, set()).discard(agent_id)
        if agent.team_id:
            self._agents_by_team.get(agent.team_id, set()).discard(agent_id)

        if set_team and team_id != agent.team_id:
            old_team = hierarchy.get_agent_team(agent_id)
            if old_team:
                old_team.remove_member(agent_id)
                if old_team.leader_id == agent_id:
                    old_team.leader_id = None
            hierarchy.agent_to_team.pop(agent_id, None)
            agent.team_id = team_id

        if skills is not None:
            agent.skills = {s.name: s for s in skills}

        for skill_name in agent.skills:
            self._agents_by_skill.setdefault(skill_name, set()).add(agent_id)
        if agent.team_id:
            self._agents_by_team.setdefault(agent.team_id, set()).add(agent_id)
            hierarchy.add_agent_to_team(agent_id, agent.team_id)

        return agent

    def get(self, agent_id: str) -> Agent | None:
        """Get agent by ID.

        Args:
            agent_id: Agent identifier

        Returns:
            Agent instance or None if not found
        """
        return self.agents.get(agent_id)

    def find_by_persona(self, persona: str) -> list[Agent]:
        """Find all agents with a specific persona.

        Args:
            persona: Agent persona (e.g., "data_engineer")

        Returns:
            List of matching agents
        """
        agent_ids = self._agents_by_persona.get(persona, set())
        return [self.agents[aid] for aid in agent_ids if aid in self.agents]

    def find_by_team(self, team_id: str) -> list[Agent]:
        """Find all agents in a specific team.

        Args:
            team_id: Team identifier

        Returns:
            List of agents in the team
        """
        agent_ids = self._agents_by_team.get(team_id, set())
        return [self.agents[aid] for aid in agent_ids if aid in self.agents]

    def find_by_skill(self, skill_name: str, min_proficiency: float = 0.0) -> list[Agent]:
        """Find agents with a specific skill.

        Args:
            skill_name: Skill name (e.g., "sql", "python")
            min_proficiency: Minimum proficiency level (0.0-1.0)

        Returns:
            List of agents with the skill meeting proficiency requirement
        """
        agent_ids = self._agents_by_skill.get(skill_name, set())
        matching_agents = []

        for aid in agent_ids:
            if aid in self.agents:
                agent = self.agents[aid]
                if (
                    skill_name in agent.skills
                    and agent.skills[skill_name].proficiency >= min_proficiency
                ):
                    matching_agents.append(agent)

        return matching_agents

    def find_available(
        self, persona: str | None = None, max_tasks: int | None = None
    ) -> list[Agent]:
        """Find available agents that are not at capacity.

        Args:
            persona: Optional filter by persona
            max_tasks: Optional filter by max current tasks

        Returns:
            List of available agents
        """
        candidates = self.find_by_persona(persona) if persona else list(self.agents.values())

        available = []
        for agent in candidates:
            if agent.state == AgentState.SHUTDOWN:
                continue

            if max_tasks is not None and len(agent.current_tasks) > max_tasks:
                continue

            if len(agent.current_tasks) < agent.max_concurrent_tasks:
                available.append(agent)

        return available

    def create_team(
        self,
        name: str,
        team_type: TeamType = TeamType.FUNCTIONAL,
        leader_id: str | None = None,
        parent_id: str | None = None,
    ) -> Team:
        """Create a new team in the hierarchy.

        Args:
            name: Team name
            team_type: Type of team
            leader_id: Optional team leader agent ID
            parent_id: Optional parent team for hierarchy

        Returns:
            Created team
        """
        team = self.team_hierarchy.create_team(
            name=name,
            team_type=team_type,
            leader_id=leader_id,
            parent_id=parent_id,
        )

        # Initialize team index
        if team.id not in self._agents_by_team:
            self._agents_by_team[team.id] = set()

        logger.info(f"Created team {name} (id={team.id}, type={team_type.value})")
        return team

    def add_team(self, team: Team) -> Team:
        """Add an existing team object (used when restoring persisted state)."""
        hierarchy = self.team_hierarchy
        hierarchy.teams[team.id] = team
        parent = hierarchy.teams.get(team.parent_team_id) if team.parent_team_id else None
        if parent:
            parent.add_child_team(team.id)
        self._agents_by_team.setdefault(team.id, set())
        return team

    def remove_team(self, team_id: str) -> bool:
        """Remove an empty, childless team.

        Raises:
            ValueError: If the team still has members or child teams.
        """
        hierarchy = self.team_hierarchy
        team = hierarchy.teams.get(team_id)
        if not team:
            return False
        if team.all_members() or self._agents_by_team.get(team_id):
            raise ValueError("Team still has members")
        if team.child_teams:
            raise ValueError("Team still has child teams")

        parent = hierarchy.teams.get(team.parent_team_id) if team.parent_team_id else None
        if parent:
            parent.child_teams.discard(team_id)
        del hierarchy.teams[team_id]
        self._agents_by_team.pop(team_id, None)
        return True

    def update_team(
        self,
        team_id: str,
        name: str | None = None,
        parent_id: str | None = None,
        reparent: bool = False,
    ) -> Team:
        """Rename and/or move a team.

        Args:
            team_id: Team to update
            name: New name (unchanged if None)
            parent_id: New parent (only applied when ``reparent`` is True;
                None then makes the team a root)
            reparent: Whether to apply ``parent_id``

        Raises:
            KeyError: If the team or new parent does not exist.
            ValueError: If the move would create a cycle.
        """
        hierarchy = self.team_hierarchy
        team = hierarchy.teams[team_id]

        if reparent and parent_id != team.parent_team_id:
            if parent_id is not None:
                if parent_id not in hierarchy.teams:
                    raise KeyError(parent_id)
                ancestor: str | None = parent_id
                while ancestor is not None:
                    if ancestor == team_id:
                        raise ValueError("Team cannot be moved under itself or a descendant")
                    ancestor = hierarchy.teams[ancestor].parent_team_id

            old_parent = hierarchy.teams.get(team.parent_team_id) if team.parent_team_id else None
            if old_parent:
                old_parent.child_teams.discard(team_id)
            team.parent_team_id = parent_id
            if parent_id is not None:
                hierarchy.teams[parent_id].add_child_team(team_id)

        if name is not None:
            team.name = name
        return team

    def get_team(self, team_id: str) -> Team | None:
        """Get team by ID.

        Args:
            team_id: Team identifier

        Returns:
            Team instance or None if not found
        """
        return self.team_hierarchy.get_team(team_id)

    def get_registry_stats(self) -> dict[str, Any]:
        """Get registry statistics.

        Returns:
            Dictionary of stats
        """
        active_agents = sum(1 for a in self.agents.values() if a.state != AgentState.SHUTDOWN)

        total_tasks = sum(len(a.current_tasks) for a in self.agents.values())

        return {
            "total_agents": len(self.agents),
            "active_agents": active_agents,
            "total_teams": len(self.team_hierarchy.teams),
            "personas": list(self._agents_by_persona.keys()),
            "total_current_tasks": total_tasks,
            "avg_tasks_per_agent": total_tasks / len(self.agents) if self.agents else 0,
        }

    def __repr__(self) -> str:
        """Return a concise debug representation."""
        return (
            f"AgentRegistry(agents={len(self.agents)}, " f"teams={len(self.team_hierarchy.teams)})"
        )
