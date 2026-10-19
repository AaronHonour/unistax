"""Hierarchical team management for agent swarm.

Supports:
- Multi-level team hierarchies
- Team leaders and members
- Cross-team collaboration
- Team metrics and performance tracking
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import uuid4

from unistax.logging import get_logger

logger = get_logger(__name__)


class TeamType(Enum):
    """Team organization types."""

    FUNCTIONAL = "functional"  # e.g., all data engineers
    CROSS_FUNCTIONAL = "cross_functional"  # Mixed roles working on project
    TASK_FORCE = "task_force"  # Temporary team for specific goal
    DIVISION = "division"  # High-level organizational unit


@dataclass
class Team:
    """Team of collaborating agents.

    Teams can be hierarchical with parent-child relationships,
    enabling organizational structures like:
    - Data Platform Division
      - Data Engineering Team
      - Data Science Team
      - Data Analytics Team

    Examples:
        >>> engineering_team = Team(
        ...     name="Data Engineering",
        ...     team_type=TeamType.FUNCTIONAL,
        ...     leader_id="senior_engineer_1"
        ... )
        >>> engineering_team.add_member("engineer_1")
        >>> engineering_team.add_member("engineer_2")
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    team_type: TeamType = TeamType.FUNCTIONAL
    leader_id: str | None = None  # Team lead agent
    members: set[str] = field(default_factory=set)
    parent_team_id: str | None = None  # For hierarchical structure
    child_teams: set[str] = field(default_factory=set)
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)

    # Performance metrics
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_collaborations: int = 0

    def add_member(self, agent_id: str):
        """Add agent to team."""
        if agent_id == self.leader_id:
            logger.warning(f"Agent {agent_id} is already team leader")
            return

        self.members.add(agent_id)
        logger.info(f"Added {agent_id} to team {self.name}")

    def remove_member(self, agent_id: str):
        """Remove agent from team."""
        if agent_id in self.members:
            self.members.remove(agent_id)
            logger.info(f"Removed {agent_id} from team {self.name}")

    def set_leader(self, agent_id: str):
        """Set team leader."""
        # Add previous leader as regular member if exists
        if self.leader_id:
            self.members.add(self.leader_id)

        # Remove new leader from members if present
        if agent_id in self.members:
            self.members.remove(agent_id)

        self.leader_id = agent_id
        logger.info(f"Set {agent_id} as leader of team {self.name}")

    def all_members(self, include_leader: bool = True) -> set[str]:
        """Get all team members including leader."""
        members = self.members.copy()
        if include_leader and self.leader_id:
            members.add(self.leader_id)
        return members

    def add_child_team(self, team_id: str):
        """Add child team (for hierarchical structure)."""
        self.child_teams.add(team_id)
        logger.info(f"Team {self.name} added child team {team_id}")

    def size(self) -> int:
        """Get total team size including leader."""
        return len(self.all_members(include_leader=True))

    def __repr__(self) -> str:
        """Return a concise debug representation."""
        return (
            f"Team(name={self.name}, type={self.team_type.value}, "
            f"size={self.size()}, leader={self.leader_id})"
        )


class TeamHierarchy:
    """Manages hierarchical team structure.

    Provides:
    - Team creation and management
    - Hierarchy navigation (parent/child relationships)
    - Team member lookup
    - Cross-team collaboration routing

    Examples:
        >>> hierarchy = TeamHierarchy()
        >>> division = hierarchy.create_team("Data Platform", TeamType.DIVISION)
        >>> eng_team = hierarchy.create_team(
        ...     "Data Engineering",
        ...     TeamType.FUNCTIONAL,
        ...     parent_id=division.id
        ... )
    """

    def __init__(self):
        """Initialize team hierarchy."""
        self.teams: dict[str, Team] = {}
        self.agent_to_team: dict[str, str] = {}  # agent_id -> team_id
        logger.info("Team hierarchy initialized")

    def create_team(
        self,
        name: str,
        team_type: TeamType = TeamType.FUNCTIONAL,
        leader_id: str | None = None,
        parent_id: str | None = None,
    ) -> Team:
        """Create a new team.

        Args:
            name: Team name
            team_type: Type of team
            leader_id: Optional team leader
            parent_id: Optional parent team for hierarchy

        Returns:
            Created team

        Examples:
            >>> hierarchy = TeamHierarchy()
            >>> team = hierarchy.create_team("Analytics", leader_id="analyst_lead_1")
        """
        team = Team(
            name=name,
            team_type=team_type,
            leader_id=leader_id,
            parent_team_id=parent_id,
        )

        self.teams[team.id] = team

        # Set up leader mapping
        if leader_id:
            self.agent_to_team[leader_id] = team.id

        # Add to parent's children
        if parent_id and parent_id in self.teams:
            self.teams[parent_id].add_child_team(team.id)

        logger.info(
            f"Created team {name} (id={team.id}, type={team_type.value}, " f"parent={parent_id})"
        )

        return team

    def get_team(self, team_id: str) -> Team | None:
        """Get team by ID."""
        return self.teams.get(team_id)

    def add_agent_to_team(self, agent_id: str, team_id: str):
        """Add agent to team.

        Args:
            agent_id: Agent identifier
            team_id: Team identifier
        """
        if team_id not in self.teams:
            logger.error(f"Team {team_id} not found")
            return

        # Remove from previous team if exists
        if agent_id in self.agent_to_team:
            old_team_id = self.agent_to_team[agent_id]
            if old_team_id in self.teams:
                self.teams[old_team_id].remove_member(agent_id)

        # Add to new team
        self.teams[team_id].add_member(agent_id)
        self.agent_to_team[agent_id] = team_id

    def get_agent_team(self, agent_id: str) -> Team | None:
        """Get team for an agent."""
        team_id = self.agent_to_team.get(agent_id)
        return self.teams.get(team_id) if team_id else None

    def get_team_leader(self, team_id: str) -> str | None:
        """Get leader of a team."""
        team = self.get_team(team_id)
        return team.leader_id if team else None

    def get_parent_team(self, team_id: str) -> Team | None:
        """Get parent team."""
        team = self.get_team(team_id)
        if team and team.parent_team_id:
            return self.get_team(team.parent_team_id)
        return None

    def get_child_teams(self, team_id: str) -> list[Team]:
        """Get all child teams."""
        team = self.get_team(team_id)
        if not team:
            return []

        return [self.teams[child_id] for child_id in team.child_teams if child_id in self.teams]

    def get_all_team_members(self, team_id: str, recursive: bool = False) -> set[str]:
        """Get all members of a team.

        Args:
            team_id: Team identifier
            recursive: If True, include members of child teams

        Returns:
            Set of agent IDs
        """
        team = self.get_team(team_id)
        if not team:
            return set()

        members = team.all_members(include_leader=True)

        if recursive:
            for child_id in team.child_teams:
                members.update(self.get_all_team_members(child_id, recursive=True))

        return members

    def find_teams_by_type(self, team_type: TeamType) -> list[Team]:
        """Find all teams of a specific type."""
        return [t for t in self.teams.values() if t.team_type == team_type]

    def get_organizational_path(self, team_id: str) -> list[Team]:
        """Get path from team to root (for hierarchical display).

        Examples:
            >>> path = hierarchy.get_organizational_path("eng_team_1")
            >>> print(" > ".join(t.name for t in path))
            Data Platform > Engineering > Backend Team
        """
        path = []
        current_id = team_id

        while current_id:
            team = self.get_team(current_id)
            if not team:
                break

            path.insert(0, team)
            current_id = team.parent_team_id

        return path

    def get_metrics(self, team_id: str, recursive: bool = False) -> dict:
        """Get team performance metrics.

        Args:
            team_id: Team identifier
            recursive: Include child team metrics

        Returns:
            Dictionary of metrics
        """
        team = self.get_team(team_id)
        if not team:
            return {}

        metrics = {
            "team_id": team_id,
            "team_name": team.name,
            "team_type": team.team_type.value,
            "size": team.size(),
            "tasks_completed": team.tasks_completed,
            "tasks_failed": team.tasks_failed,
            "total_collaborations": team.total_collaborations,
            "success_rate": (
                team.tasks_completed / (team.tasks_completed + team.tasks_failed)
                if (team.tasks_completed + team.tasks_failed) > 0
                else 0.0
            ),
        }

        if recursive:
            child_metrics = []
            for child_id in team.child_teams:
                child_metrics.append(self.get_metrics(child_id, recursive=True))
            metrics["child_teams"] = child_metrics

        return metrics

    def visualize_hierarchy(self, root_team_id: str | None = None, indent: int = 0) -> str:
        """Generate text visualization of team hierarchy.

        Args:
            root_team_id: Starting team (None for top-level teams)
            indent: Current indentation level

        Returns:
            Multi-line string visualization
        """
        lines = []

        if root_team_id:
            # Visualize specific team and children
            team = self.get_team(root_team_id)
            if team:
                prefix = "  " * indent
                lines.append(
                    f"{prefix}📁 {team.name} ({team.team_type.value}) " f"[{team.size()} members]"
                )

                for child_id in team.child_teams:
                    lines.append(self.visualize_hierarchy(child_id, indent + 1))
        else:
            # Visualize all top-level teams
            top_level_teams = [t for t in self.teams.values() if t.parent_team_id is None]

            for team in top_level_teams:
                lines.append(self.visualize_hierarchy(team.id, indent))

        return "\n".join(lines)

    def __repr__(self) -> str:
        """Return a concise debug representation."""
        return f"TeamHierarchy(teams={len(self.teams)}, agents={len(self.agent_to_team)})"
