"""Tests for agent registry."""

import pytest

from unistax.agents.base import AgentState, Skill
from unistax.agents.personas.data_analyst import DataAnalystAgent
from unistax.agents.personas.data_engineer import DataEngineerAgent
from unistax.agents.registry import AgentRegistry
from unistax.agents.team import TeamType


@pytest.mark.unit
@pytest.mark.agents
class TestAgentRegistry:
    """Test AgentRegistry class."""

    def test_registry_initialization(self):
        """Test creating a registry."""
        registry = AgentRegistry()

        assert len(registry.agents) == 0
        assert registry.event_bus is not None
        assert registry.team_hierarchy is not None

    def test_register_agent(self):
        """Test registering an agent."""
        registry = AgentRegistry()

        agent = DataEngineerAgent(
            agent_id="eng_001",
            event_bus=registry.event_bus,
        )

        registry.register(agent)

        assert "eng_001" in registry.agents
        assert registry.agents["eng_001"] is agent

    def test_register_multiple_agents(self):
        """Test registering multiple agents."""
        registry = AgentRegistry()

        eng1 = DataEngineerAgent("eng_001", event_bus=registry.event_bus)
        eng2 = DataEngineerAgent("eng_002", event_bus=registry.event_bus)
        analyst1 = DataAnalystAgent("analyst_001", event_bus=registry.event_bus)

        registry.register(eng1)
        registry.register(eng2)
        registry.register(analyst1)

        assert len(registry.agents) == 3

    def test_unregister_agent(self):
        """Test unregistering an agent."""
        registry = AgentRegistry()

        agent = DataEngineerAgent("eng_001", event_bus=registry.event_bus)
        registry.register(agent)

        registry.unregister("eng_001")

        assert "eng_001" not in registry.agents

    def test_get_agent(self):
        """Test getting an agent by ID."""
        registry = AgentRegistry()

        agent = DataEngineerAgent("eng_001", event_bus=registry.event_bus)
        registry.register(agent)

        retrieved = registry.get("eng_001")

        assert retrieved is agent

    def test_get_nonexistent_agent(self):
        """Test getting nonexistent agent returns None."""
        registry = AgentRegistry()

        retrieved = registry.get("nonexistent")

        assert retrieved is None

    def test_find_by_persona(self):
        """Test finding agents by persona."""
        registry = AgentRegistry()

        eng1 = DataEngineerAgent("eng_001", event_bus=registry.event_bus)
        eng2 = DataEngineerAgent("eng_002", event_bus=registry.event_bus)
        analyst1 = DataAnalystAgent("analyst_001", event_bus=registry.event_bus)

        registry.register(eng1)
        registry.register(eng2)
        registry.register(analyst1)

        engineers = registry.find_by_persona("data_engineer")
        analysts = registry.find_by_persona("data_analyst")

        assert len(engineers) == 2
        assert eng1 in engineers
        assert eng2 in engineers

        assert len(analysts) == 1
        assert analyst1 in analysts

    def test_find_by_team(self):
        """Test finding agents by team."""
        registry = AgentRegistry()

        team = registry.create_team("Engineering", TeamType.FUNCTIONAL)

        eng1 = DataEngineerAgent("eng_001", event_bus=registry.event_bus, team_id=team.id)
        eng2 = DataEngineerAgent("eng_002", event_bus=registry.event_bus, team_id=team.id)
        analyst1 = DataAnalystAgent("analyst_001", event_bus=registry.event_bus)

        registry.register(eng1)
        registry.register(eng2)
        registry.register(analyst1)

        team_agents = registry.find_by_team(team.id)

        assert len(team_agents) == 2
        assert eng1 in team_agents
        assert eng2 in team_agents

    def test_find_by_skill(self):
        """Test finding agents by skill."""
        registry = AgentRegistry()

        # Engineer has SQL 0.90
        eng1 = DataEngineerAgent("eng_001", event_bus=registry.event_bus)

        # Analyst has SQL 0.90
        analyst1 = DataAnalystAgent("analyst_001", event_bus=registry.event_bus)

        registry.register(eng1)
        registry.register(analyst1)

        # Find agents with SQL >= 0.85
        sql_agents = registry.find_by_skill("sql", min_proficiency=0.85)

        assert len(sql_agents) == 2
        assert eng1 in sql_agents
        assert analyst1 in sql_agents

        # Find agents with SQL >= 0.95 (none should match)
        expert_sql = registry.find_by_skill("sql", min_proficiency=0.95)

        assert len(expert_sql) == 0

    def test_find_available_agents(self):
        """Test finding available agents."""
        registry = AgentRegistry()

        eng1 = DataEngineerAgent("eng_001", event_bus=registry.event_bus, max_concurrent_tasks=2)
        eng2 = DataEngineerAgent("eng_002", event_bus=registry.event_bus, max_concurrent_tasks=2)

        registry.register(eng1)
        registry.register(eng2)

        # Both should be available initially
        available = registry.find_available()
        assert len(available) == 2

        # Add tasks to eng1 up to capacity
        from unistax.agents.base import Task

        eng1.current_tasks.append(Task(type="task1"))
        eng1.current_tasks.append(Task(type="task2"))

        # Only eng2 should be available
        available = registry.find_available()
        assert len(available) == 1
        assert eng2 in available

    def test_find_available_by_persona(self):
        """Test finding available agents filtered by persona."""
        registry = AgentRegistry()

        eng1 = DataEngineerAgent("eng_001", event_bus=registry.event_bus)
        analyst1 = DataAnalystAgent("analyst_001", event_bus=registry.event_bus)

        registry.register(eng1)
        registry.register(analyst1)

        available_engineers = registry.find_available(persona="data_engineer")
        available_analysts = registry.find_available(persona="data_analyst")

        assert len(available_engineers) == 1
        assert eng1 in available_engineers

        assert len(available_analysts) == 1
        assert analyst1 in available_analysts

    def test_create_team(self):
        """Test creating a team via registry."""
        registry = AgentRegistry()

        team = registry.create_team(
            name="Engineering",
            team_type=TeamType.FUNCTIONAL,
        )

        assert team.name == "Engineering"
        assert team.team_type == TeamType.FUNCTIONAL
        assert team.id in registry.team_hierarchy.teams

    def test_create_hierarchical_teams(self):
        """Test creating hierarchical teams."""
        registry = AgentRegistry()

        parent = registry.create_team("Division", TeamType.DIVISION)
        child = registry.create_team("Team", TeamType.FUNCTIONAL, parent_id=parent.id)

        assert child.parent_team_id == parent.id
        assert child.id in parent.child_teams

    def test_get_team(self):
        """Test getting a team from registry."""
        registry = AgentRegistry()

        team = registry.create_team("Engineering")
        retrieved = registry.get_team(team.id)

        assert retrieved is team

    def test_get_registry_stats(self):
        """Test getting registry statistics."""
        registry = AgentRegistry()

        eng1 = DataEngineerAgent("eng_001", event_bus=registry.event_bus)
        analyst1 = DataAnalystAgent("analyst_001", event_bus=registry.event_bus)

        registry.register(eng1)
        registry.register(analyst1)

        team = registry.create_team("Engineering")

        stats = registry.get_registry_stats()

        assert stats["total_agents"] == 2
        assert stats["active_agents"] == 2
        assert stats["total_teams"] == 1
        assert "data_engineer" in stats["personas"]
        assert "data_analyst" in stats["personas"]
        assert stats["total_current_tasks"] == 0
        assert stats["avg_tasks_per_agent"] == 0.0

    def test_registry_stats_with_tasks(self):
        """Test registry stats with tasks."""
        registry = AgentRegistry()

        from unistax.agents.base import Task

        eng1 = DataEngineerAgent("eng_001", event_bus=registry.event_bus)
        eng1.current_tasks.append(Task(type="task1"))
        eng1.current_tasks.append(Task(type="task2"))

        registry.register(eng1)

        stats = registry.get_registry_stats()

        assert stats["total_current_tasks"] == 2
        assert stats["avg_tasks_per_agent"] == 2.0

    def test_registry_stats_with_shutdown_agents(self):
        """Test registry stats excludes shutdown agents."""
        registry = AgentRegistry()

        eng1 = DataEngineerAgent("eng_001", event_bus=registry.event_bus)
        eng2 = DataEngineerAgent("eng_002", event_bus=registry.event_bus)

        registry.register(eng1)
        registry.register(eng2)

        # Shutdown one agent
        eng2.state = AgentState.SHUTDOWN

        stats = registry.get_registry_stats()

        assert stats["total_agents"] == 2
        assert stats["active_agents"] == 1

    def test_registry_representation(self):
        """Test registry string representation."""
        registry = AgentRegistry()

        eng1 = DataEngineerAgent("eng_001", event_bus=registry.event_bus)
        registry.register(eng1)
        registry.create_team("Engineering")

        repr_str = repr(registry)
        assert "agents=1" in repr_str
        assert "teams=1" in repr_str
