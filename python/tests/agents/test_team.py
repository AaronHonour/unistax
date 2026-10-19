"""Tests for team hierarchy management."""

import pytest

from unistax.agents.team import Team, TeamHierarchy, TeamType


@pytest.mark.unit
@pytest.mark.agents
class TestTeam:
    """Test Team class."""

    def test_team_creation(self):
        """Test creating a team."""
        team = Team(
            name="Engineering",
            team_type=TeamType.FUNCTIONAL,
            leader_id="eng_lead_001",
        )

        assert team.name == "Engineering"
        assert team.team_type == TeamType.FUNCTIONAL
        assert team.leader_id == "eng_lead_001"
        assert len(team.members) == 0
        assert len(team.child_teams) == 0

    def test_team_add_member(self):
        """Test adding members to a team."""
        team = Team(name="Analytics", team_type=TeamType.FUNCTIONAL)

        team.add_member("analyst_001")
        team.add_member("analyst_002")

        assert len(team.members) == 2
        assert "analyst_001" in team.members
        assert "analyst_002" in team.members

    def test_team_remove_member(self):
        """Test removing members from a team."""
        team = Team(name="Analytics")
        team.add_member("analyst_001")
        team.add_member("analyst_002")

        team.remove_member("analyst_001")

        assert len(team.members) == 1
        assert "analyst_001" not in team.members
        assert "analyst_002" in team.members

    def test_team_set_leader(self):
        """Test setting team leader."""
        team = Team(name="Engineering")
        team.add_member("eng_001")
        team.add_member("eng_002")

        team.set_leader("eng_001")

        assert team.leader_id == "eng_001"
        assert "eng_001" not in team.members  # Leader removed from members
        assert "eng_002" in team.members

    def test_team_change_leader(self):
        """Test changing team leader."""
        team = Team(name="Engineering")
        team.set_leader("eng_001")

        # Change leader
        team.set_leader("eng_002")

        assert team.leader_id == "eng_002"
        assert "eng_001" in team.members  # Previous leader becomes member
        assert "eng_002" not in team.members

    def test_team_all_members(self):
        """Test getting all team members."""
        team = Team(name="Engineering")
        team.add_member("eng_001")
        team.add_member("eng_002")
        team.set_leader("eng_lead")

        # With leader
        all_members = team.all_members(include_leader=True)
        assert len(all_members) == 3
        assert "eng_lead" in all_members
        assert "eng_001" in all_members
        assert "eng_002" in all_members

        # Without leader
        members_only = team.all_members(include_leader=False)
        assert len(members_only) == 2
        assert "eng_lead" not in members_only

    def test_team_add_child_team(self):
        """Test adding child teams."""
        parent = Team(name="Data Platform", team_type=TeamType.DIVISION)
        parent.add_child_team("child_team_1")
        parent.add_child_team("child_team_2")

        assert len(parent.child_teams) == 2
        assert "child_team_1" in parent.child_teams
        assert "child_team_2" in parent.child_teams

    def test_team_size(self):
        """Test team size calculation."""
        team = Team(name="Engineering")

        # Empty team
        assert team.size() == 0

        # Add members
        team.add_member("eng_001")
        team.add_member("eng_002")
        assert team.size() == 2

        # Add leader
        team.set_leader("eng_lead")
        assert team.size() == 3

    def test_team_representation(self):
        """Test team string representation."""
        team = Team(name="Analytics", team_type=TeamType.FUNCTIONAL)
        team.add_member("analyst_001")
        team.set_leader("analyst_lead")

        repr_str = repr(team)
        assert "Analytics" in repr_str
        assert "functional" in repr_str
        assert "analyst_lead" in repr_str


@pytest.mark.unit
@pytest.mark.agents
class TestTeamHierarchy:
    """Test TeamHierarchy class."""

    def test_hierarchy_initialization(self):
        """Test creating a team hierarchy."""
        hierarchy = TeamHierarchy()

        assert len(hierarchy.teams) == 0
        assert len(hierarchy.agent_to_team) == 0

    def test_create_team(self):
        """Test creating a team in hierarchy."""
        hierarchy = TeamHierarchy()

        team = hierarchy.create_team(
            name="Engineering",
            team_type=TeamType.FUNCTIONAL,
            leader_id="eng_lead",
        )

        assert team.name == "Engineering"
        assert team.team_type == TeamType.FUNCTIONAL
        assert team.leader_id == "eng_lead"
        assert team.id in hierarchy.teams
        assert hierarchy.agent_to_team["eng_lead"] == team.id

    def test_create_child_team(self):
        """Test creating hierarchical teams."""
        hierarchy = TeamHierarchy()

        # Create parent team
        parent = hierarchy.create_team(
            name="Data Platform",
            team_type=TeamType.DIVISION,
        )

        # Create child team
        child = hierarchy.create_team(
            name="Engineering",
            team_type=TeamType.FUNCTIONAL,
            parent_id=parent.id,
        )

        assert child.parent_team_id == parent.id
        assert child.id in parent.child_teams

    def test_get_team(self):
        """Test getting a team by ID."""
        hierarchy = TeamHierarchy()

        team = hierarchy.create_team(name="Analytics")
        retrieved = hierarchy.get_team(team.id)

        assert retrieved is team
        assert retrieved.name == "Analytics"

    def test_add_agent_to_team(self):
        """Test adding agents to teams."""
        hierarchy = TeamHierarchy()

        team = hierarchy.create_team(name="Engineering")

        hierarchy.add_agent_to_team("eng_001", team.id)
        hierarchy.add_agent_to_team("eng_002", team.id)

        assert "eng_001" in team.members
        assert "eng_002" in team.members
        assert hierarchy.agent_to_team["eng_001"] == team.id
        assert hierarchy.agent_to_team["eng_002"] == team.id

    def test_move_agent_between_teams(self):
        """Test moving agent from one team to another."""
        hierarchy = TeamHierarchy()

        team1 = hierarchy.create_team(name="Team 1")
        team2 = hierarchy.create_team(name="Team 2")

        # Add agent to team1
        hierarchy.add_agent_to_team("agent_001", team1.id)
        assert "agent_001" in team1.members
        assert "agent_001" not in team2.members

        # Move to team2
        hierarchy.add_agent_to_team("agent_001", team2.id)
        assert "agent_001" not in team1.members
        assert "agent_001" in team2.members

    def test_get_agent_team(self):
        """Test getting agent's team."""
        hierarchy = TeamHierarchy()

        team = hierarchy.create_team(name="Engineering")
        hierarchy.add_agent_to_team("eng_001", team.id)

        agent_team = hierarchy.get_agent_team("eng_001")

        assert agent_team is team
        assert agent_team.name == "Engineering"

    def test_get_team_leader(self):
        """Test getting team leader."""
        hierarchy = TeamHierarchy()

        team = hierarchy.create_team(
            name="Engineering",
            leader_id="eng_lead",
        )

        leader = hierarchy.get_team_leader(team.id)
        assert leader == "eng_lead"

    def test_get_parent_team(self):
        """Test getting parent team."""
        hierarchy = TeamHierarchy()

        parent = hierarchy.create_team(name="Division")
        child = hierarchy.create_team(name="Team", parent_id=parent.id)

        parent_team = hierarchy.get_parent_team(child.id)

        assert parent_team is parent
        assert parent_team.name == "Division"

    def test_get_child_teams(self):
        """Test getting child teams."""
        hierarchy = TeamHierarchy()

        parent = hierarchy.create_team(name="Division")
        child1 = hierarchy.create_team(name="Team 1", parent_id=parent.id)
        child2 = hierarchy.create_team(name="Team 2", parent_id=parent.id)

        children = hierarchy.get_child_teams(parent.id)

        assert len(children) == 2
        assert child1 in children
        assert child2 in children

    def test_get_all_team_members(self):
        """Test getting all team members."""
        hierarchy = TeamHierarchy()

        team = hierarchy.create_team(name="Engineering", leader_id="eng_lead")
        hierarchy.add_agent_to_team("eng_001", team.id)
        hierarchy.add_agent_to_team("eng_002", team.id)

        # Non-recursive
        members = hierarchy.get_all_team_members(team.id, recursive=False)
        assert len(members) == 3  # 2 members + 1 leader
        assert "eng_lead" in members
        assert "eng_001" in members
        assert "eng_002" in members

    def test_get_all_team_members_recursive(self):
        """Test getting all team members recursively."""
        hierarchy = TeamHierarchy()

        parent = hierarchy.create_team(name="Division", leader_id="div_lead")
        child1 = hierarchy.create_team(name="Team 1", parent_id=parent.id, leader_id="team1_lead")
        child2 = hierarchy.create_team(name="Team 2", parent_id=parent.id, leader_id="team2_lead")

        hierarchy.add_agent_to_team("eng_001", child1.id)
        hierarchy.add_agent_to_team("eng_002", child2.id)

        # Recursive - should include all descendants
        all_members = hierarchy.get_all_team_members(parent.id, recursive=True)

        assert len(all_members) == 5  # div_lead + 2 team leads + 2 engineers
        assert "div_lead" in all_members
        assert "team1_lead" in all_members
        assert "team2_lead" in all_members
        assert "eng_001" in all_members
        assert "eng_002" in all_members

    def test_find_teams_by_type(self):
        """Test finding teams by type."""
        hierarchy = TeamHierarchy()

        div1 = hierarchy.create_team(name="Division 1", team_type=TeamType.DIVISION)
        div2 = hierarchy.create_team(name="Division 2", team_type=TeamType.DIVISION)
        func1 = hierarchy.create_team(name="Functional 1", team_type=TeamType.FUNCTIONAL)
        func2 = hierarchy.create_team(name="Functional 2", team_type=TeamType.FUNCTIONAL)

        divisions = hierarchy.find_teams_by_type(TeamType.DIVISION)
        functionals = hierarchy.find_teams_by_type(TeamType.FUNCTIONAL)

        assert len(divisions) == 2
        assert div1 in divisions
        assert div2 in divisions

        assert len(functionals) == 2
        assert func1 in functionals
        assert func2 in functionals

    def test_get_organizational_path(self):
        """Test getting organizational path."""
        hierarchy = TeamHierarchy()

        # Create hierarchy: Company > Division > Department > Team
        company = hierarchy.create_team(name="Company", team_type=TeamType.DIVISION)
        division = hierarchy.create_team(name="Division", parent_id=company.id)
        department = hierarchy.create_team(name="Department", parent_id=division.id)
        team = hierarchy.create_team(name="Team", parent_id=department.id)

        path = hierarchy.get_organizational_path(team.id)

        assert len(path) == 4
        assert path[0] is company
        assert path[1] is division
        assert path[2] is department
        assert path[3] is team

    def test_get_metrics(self):
        """Test getting team metrics."""
        hierarchy = TeamHierarchy()

        team = hierarchy.create_team(name="Engineering")
        hierarchy.add_agent_to_team("eng_001", team.id)
        hierarchy.add_agent_to_team("eng_002", team.id)

        # Set some metrics
        team.tasks_completed = 10
        team.tasks_failed = 2

        metrics = hierarchy.get_metrics(team.id)

        assert metrics["team_name"] == "Engineering"
        assert metrics["size"] == 2
        assert metrics["tasks_completed"] == 10
        assert metrics["tasks_failed"] == 2
        assert metrics["success_rate"] == 10 / 12

    def test_get_metrics_recursive(self):
        """Test getting team metrics recursively."""
        hierarchy = TeamHierarchy()

        parent = hierarchy.create_team(name="Division")
        child1 = hierarchy.create_team(name="Team 1", parent_id=parent.id)
        child2 = hierarchy.create_team(name="Team 2", parent_id=parent.id)

        metrics = hierarchy.get_metrics(parent.id, recursive=True)

        assert metrics["team_name"] == "Division"
        assert "child_teams" in metrics
        assert len(metrics["child_teams"]) == 2

    def test_hierarchy_representation(self):
        """Test team hierarchy string representation."""
        hierarchy = TeamHierarchy()

        hierarchy.create_team(name="Team 1")
        hierarchy.create_team(name="Team 2")

        repr_str = repr(hierarchy)
        assert "teams=2" in repr_str
