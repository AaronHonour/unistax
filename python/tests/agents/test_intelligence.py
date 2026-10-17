"""Tests for agent intelligence features.

Tests for Phase 3 intelligence capabilities:
- Reinforcement Learning (Q-learning)
- Knowledge Graph
- HTN Planning
- Swarm Intelligence (ACO, PSO)
"""

import numpy as np
import pytest

from unistax.agents.intelligence import (
    ACOAnt,
    ACOEdge,
    AgentKnowledgeGraph,
    AgentRLPolicy,
    AntColonyOptimizer,
    Experience,
    HTNAgent,
    HTNMethod,
    HTNOperator,
    HTNPlan,
    HTNPlanner,
    HTNTask,
    KnowledgeEdge,
    KnowledgeNode,
    NodeType,
    Particle,
    ParticleSwarmOptimizer,
    PlanStatus,
    RelationType,
    RLAgent,
    SwarmAgent,
    TaskType,
)

# ============================================================================
# Reinforcement Learning Tests
# ============================================================================


class TestAgentRLPolicy:
    """Test Reinforcement Learning policy."""

    def test_rl_policy_initialization(self):
        policy = AgentRLPolicy(agent_id="a1")

        assert policy.agent_id == "a1"
        assert policy.learning_rate == 0.1
        assert policy.discount_factor == 0.95
        assert len(policy.q_table) == 0

    def test_get_and_update_q_value(self):
        policy = AgentRLPolicy(agent_id="a1")
        state = {"load": 0.5}

        assert policy.get_q_value(state, "action_a") == 0.0

        policy.update_q_value(state, "action_a", 1.5)
        assert policy.get_q_value(state, "action_a") == 1.5

    def test_action_selection_exploit(self):
        policy = AgentRLPolicy(agent_id="a1", exploration_rate=0.0)
        state = {"load": 0.5}

        policy.update_q_value(state, "action_a", 0.5)
        policy.update_q_value(state, "action_b", 1.5)
        policy.update_q_value(state, "action_c", 0.8)

        actions = ["action_a", "action_b", "action_c"]
        assert policy.select_action(state, actions, training=False) == "action_b"

    def test_select_action_requires_actions(self):
        policy = AgentRLPolicy(agent_id="a1")

        with pytest.raises(ValueError):
            policy.select_action({"load": 0.5}, [])

    def test_learn_from_experience(self):
        policy = AgentRLPolicy(agent_id="a1", learning_rate=0.1, discount_factor=0.9)
        state = {"load": 0.5}
        next_state = {"load": 0.3}

        policy.update_q_value(state, "action_a", 1.0)
        policy.update_q_value(next_state, "action_b", 2.0)

        policy.learn_from_experience(
            Experience(
                state=state,
                action="action_a",
                reward=1.0,
                next_state=next_state,
                done=False,
            )
        )

        # Q = 1.0 + 0.1 * (1.0 + 0.9 * 2.0 - 1.0) = 1.18
        assert abs(policy.get_q_value(state, "action_a") - 1.18) < 1e-9

    def test_terminal_experience_ignores_future_value(self):
        policy = AgentRLPolicy(agent_id="a1", learning_rate=0.5, discount_factor=0.9)
        state = {"s": 1}
        next_state = {"s": 2}
        policy.update_q_value(next_state, "x", 100.0)

        policy.learn_from_experience(
            Experience(state=state, action="a", reward=1.0, next_state=next_state, done=True)
        )

        assert abs(policy.get_q_value(state, "a") - 0.5) < 1e-9

    def test_experience_replay_memory_is_bounded(self):
        policy = AgentRLPolicy(agent_id="a1", memory_size=3)
        state = {"load": 0.5}

        for i in range(5):
            policy.record_experience(state, "a", float(i), state)

        assert len(policy.memory) == 3
        assert {e.reward for e in policy.memory} == {2.0, 3.0, 4.0}
        assert policy.total_experiences == 5

    def test_train_on_batch(self):
        policy = AgentRLPolicy(agent_id="a1")
        state = {"s": 1}

        assert policy.train_on_batch(batch_size=4)["trained"] is False

        for _ in range(10):
            policy.record_experience(state, "a", 1.0, state)

        result = policy.train_on_batch(batch_size=4)
        assert result["trained"] is True
        assert policy.get_q_value(state, "a") > 0.0

    def test_save_and_load_policy(self, tmp_path):
        policy = AgentRLPolicy(agent_id="a1")
        policy.update_q_value({"s": 1}, "a", 0.7)
        path = str(tmp_path / "policy.json")
        policy.save_policy(path)

        restored = AgentRLPolicy(agent_id="a1")
        restored.load_policy(path)
        assert restored.get_q_value({"s": 1}, "a") == 0.7


class TestRLAgent:
    """Test RL agent mixin (used cooperatively with a real agent class)."""

    def _make_agent(self):
        from unistax.agents import DataEngineerAgent

        class SmartEngineer(RLAgent, DataEngineerAgent):
            pass

        return SmartEngineer("eng_rl")

    def test_rl_disabled_by_default(self):
        agent = self._make_agent()
        assert agent.rl_policy is None
        assert agent.rl_enabled is False

    def test_enable_rl_learning(self):
        agent = self._make_agent()
        agent.enable_rl_learning(learning_rate=0.2)

        assert agent.rl_enabled is True
        assert agent.rl_policy.agent_id == "eng_rl"
        assert agent.rl_policy.learning_rate == 0.2

        agent.disable_rl_learning()
        assert agent.rl_enabled is False

    def test_current_state_features(self):
        agent = self._make_agent()
        state = agent.get_current_state()

        assert state["tasks_pending"] == 0
        assert "success_rate" in state


# ============================================================================
# Knowledge Graph Tests
# ============================================================================


class TestKnowledgeGraph:
    """Test agent knowledge graph."""

    def test_knowledge_graph_initialization(self):
        """Test knowledge graph creation."""
        kg = AgentKnowledgeGraph()

        assert len(kg.nodes) == 0
        assert len(kg.edges) == 0

    def test_add_node(self):
        """Test adding nodes to graph."""
        kg = AgentKnowledgeGraph()

        node = kg.add_node(
            node_id="dataset_001",
            node_type=NodeType.DATASET,
            properties={"size_mb": 500},
            agent_id="agent_001",
        )

        assert node.id == "dataset_001"
        assert node.node_type == NodeType.DATASET
        assert node.properties["size_mb"] == 500
        assert node.created_by == "agent_001"
        assert len(kg.nodes) == 1

    def test_update_existing_node(self):
        """Test updating existing node."""
        kg = AgentKnowledgeGraph()

        # Add node
        kg.add_node(
            node_id="dataset_001",
            node_type=NodeType.DATASET,
            properties={"size_mb": 500},
        )

        # Update node
        node = kg.add_node(
            node_id="dataset_001",
            node_type=NodeType.DATASET,
            properties={"size_mb": 600, "rows": 1000},
        )

        # Should have updated properties
        assert node.properties["size_mb"] == 600
        assert node.properties["rows"] == 1000

        # Should still be only one node
        assert len(kg.nodes) == 1

    def test_add_edge(self):
        """Test adding edges to graph."""
        kg = AgentKnowledgeGraph()

        # Add nodes
        kg.add_node("pipeline_001", NodeType.PIPELINE)
        kg.add_node("dataset_001", NodeType.DATASET)

        # Add edge
        edge = kg.add_edge(
            source_id="pipeline_001",
            target_id="dataset_001",
            relation_type=RelationType.PRODUCES,
            agent_id="agent_001",
        )

        assert edge.source_id == "pipeline_001"
        assert edge.target_id == "dataset_001"
        assert edge.relation_type == RelationType.PRODUCES
        assert len(kg.edges) == 1

    def test_get_outgoing_edges(self):
        """Test getting outgoing edges."""
        kg = AgentKnowledgeGraph()

        kg.add_node("A", NodeType.PIPELINE)
        kg.add_node("B", NodeType.DATASET)
        kg.add_node("C", NodeType.DATASET)

        kg.add_edge("A", "B", RelationType.PRODUCES)
        kg.add_edge("A", "C", RelationType.PRODUCES)
        kg.add_edge("B", "C", RelationType.DEPENDS_ON)

        # Get outgoing edges from A
        edges = kg.get_outgoing_edges("A")
        assert len(edges) == 2

        # Filter by relation type
        edges = kg.get_outgoing_edges("A", RelationType.PRODUCES)
        assert len(edges) == 2

    def test_get_incoming_edges(self):
        """Test getting incoming edges."""
        kg = AgentKnowledgeGraph()

        kg.add_node("A", NodeType.PIPELINE)
        kg.add_node("B", NodeType.DATASET)

        kg.add_edge("A", "B", RelationType.PRODUCES)

        # Get incoming edges to B
        edges = kg.get_incoming_edges("B")
        assert len(edges) == 1
        assert edges[0].source_id == "A"

    def test_get_dependencies(self):
        """Test getting transitive dependencies."""
        kg = AgentKnowledgeGraph()

        # Create dependency chain: A -> B -> C
        kg.add_node("A", NodeType.DATASET)
        kg.add_node("B", NodeType.DATASET)
        kg.add_node("C", NodeType.DATASET)

        kg.add_edge("A", "B", RelationType.DEPENDS_ON)
        kg.add_edge("B", "C", RelationType.DEPENDS_ON)

        # A depends on B and C (transitive)
        deps = kg.get_dependencies("A")
        assert set(deps) == {"B", "C"}

    def test_get_consumers(self):
        """Test getting consumers."""
        kg = AgentKnowledgeGraph()

        kg.add_node("dataset", NodeType.DATASET)
        kg.add_node("pipeline_a", NodeType.PIPELINE)
        kg.add_node("pipeline_b", NodeType.PIPELINE)

        kg.add_edge("pipeline_a", "dataset", RelationType.CONSUMES)
        kg.add_edge("pipeline_b", "dataset", RelationType.CONSUMES)

        consumers = kg.get_consumers("dataset")
        assert set(consumers) == {"pipeline_a", "pipeline_b"}

    def test_query_by_type(self):
        """Test querying nodes by type."""
        kg = AgentKnowledgeGraph()

        kg.add_node("dataset_1", NodeType.DATASET)
        kg.add_node("dataset_2", NodeType.DATASET)
        kg.add_node("pipeline_1", NodeType.PIPELINE)

        datasets = kg.query_by_type(NodeType.DATASET)
        assert len(datasets) == 2

        pipelines = kg.query_by_type(NodeType.PIPELINE)
        assert len(pipelines) == 1

    def test_add_best_practice(self):
        """Test adding best practices."""
        kg = AgentKnowledgeGraph()

        kg.add_node("dataset_1", NodeType.DATASET)

        practice = kg.add_best_practice(
            practice_id="bp_001",
            topic="data_quality",
            description="Always validate input data",
            agent_id="agent_001",
            related_nodes=["dataset_1"],
        )

        assert practice.node_type == NodeType.BEST_PRACTICE
        assert practice.properties["topic"] == "data_quality"

        # Check relationship was created
        edges = kg.get_outgoing_edges("bp_001", RelationType.RELATED_TO)
        assert len(edges) == 1

    def test_record_issue(self):
        """Test recording issues."""
        kg = AgentKnowledgeGraph()

        kg.add_node("dataset_1", NodeType.DATASET)
        kg.add_node("pipeline_1", NodeType.PIPELINE)

        issue = kg.record_issue(
            issue_id="issue_001",
            description="Data quality degradation",
            severity="high",
            affected_nodes=["dataset_1", "pipeline_1"],
            agent_id="agent_001",
        )

        assert issue.node_type == NodeType.ISSUE
        assert issue.properties["severity"] == "high"
        assert issue.properties["status"] == "open"

        # Check relationships
        edges = kg.get_outgoing_edges("issue_001")
        assert len(edges) == 2


# ============================================================================
# HTN Planning Tests
# ============================================================================


class TestHTNPlanner:
    """Test HTN planner."""

    def test_htn_planner_initialization(self):
        """Test HTN planner creation."""
        planner = HTNPlanner()

        assert len(planner.tasks) == 0
        assert len(planner.operators) == 0
        assert len(planner.methods) == 0

    def test_add_task(self):
        """Test adding tasks."""
        planner = HTNPlanner()

        task = HTNTask(
            name="analyze_data",
            task_type=TaskType.COMPOUND,
        )

        planner.add_task(task)
        assert len(planner.tasks) == 1
        assert "analyze_data" in planner.tasks

    def test_add_operator(self):
        """Test adding operators."""
        planner = HTNPlanner()

        operator = HTNOperator(
            name="fetch_data",
            preconditions={"data_source": "available"},
            effects={"data": "fetched"},
        )

        planner.add_operator(operator)
        assert len(planner.operators) == 1
        assert "fetch_data" in planner.operators

    def test_add_method(self):
        """Test adding decomposition methods."""
        planner = HTNPlanner()

        # Create subtasks
        fetch = HTNTask("fetch_data", TaskType.PRIMITIVE)
        process = HTNTask("process_data", TaskType.PRIMITIVE)

        method = HTNMethod(
            name="standard_analysis",
            task_name="analyze_data",
            subtasks=[fetch, process],
        )

        planner.add_method(method)
        assert "analyze_data" in planner.methods
        assert len(planner.methods["analyze_data"]) == 1

    def test_simple_planning(self):
        """Test simple HTN planning."""
        planner = HTNPlanner()

        # Define operators
        fetch_op = HTNOperator(
            name="fetch_data",
            preconditions={"source": "ready"},
            effects={"data": "fetched"},
        )
        planner.add_operator(fetch_op)

        # Define compound task
        analyze_task = HTNTask("analyze_data", TaskType.COMPOUND)
        planner.add_task(analyze_task)

        # Define method to decompose analyze_data
        fetch_task = HTNTask("fetch_data", TaskType.PRIMITIVE)
        method = HTNMethod(
            name="simple_analysis",
            task_name="analyze_data",
            subtasks=[fetch_task],
        )
        planner.add_method(method)

        # Plan
        initial_state = {"source": "ready"}
        plan = planner.plan(analyze_task, initial_state)

        assert plan is not None
        assert plan.status == PlanStatus.READY
        assert len(plan.operators) == 1
        assert plan.operators[0].name == "fetch_data"

    def test_hierarchical_planning(self):
        """Test hierarchical task decomposition."""
        planner = HTNPlanner()

        # Define primitive operators
        fetch_op = HTNOperator("fetch_data", effects={"data": "fetched"})
        clean_op = HTNOperator(
            "clean_data", preconditions={"data": "fetched"}, effects={"data": "clean"}
        )
        analyze_op = HTNOperator(
            "analyze_data", preconditions={"data": "clean"}, effects={"result": "ready"}
        )

        planner.add_operator(fetch_op)
        planner.add_operator(clean_op)
        planner.add_operator(analyze_op)

        # Define compound task
        full_analysis = HTNTask("full_analysis", TaskType.COMPOUND)
        planner.add_task(full_analysis)

        # Define method
        method = HTNMethod(
            name="complete_analysis",
            task_name="full_analysis",
            subtasks=[
                HTNTask("fetch_data", TaskType.PRIMITIVE),
                HTNTask("clean_data", TaskType.PRIMITIVE),
                HTNTask("analyze_data", TaskType.PRIMITIVE),
            ],
        )
        planner.add_method(method)

        # Plan
        plan = planner.plan(full_analysis, {})

        assert plan is not None
        assert len(plan.operators) == 3
        assert plan.operators[0].name == "fetch_data"
        assert plan.operators[1].name == "clean_data"
        assert plan.operators[2].name == "analyze_data"

    def test_plan_execution(self):
        """Test HTN plan execution."""
        planner = HTNPlanner()

        # Define operators
        op1 = HTNOperator("step1", effects={"step1": "done"})
        op2 = HTNOperator("step2", preconditions={"step1": "done"}, effects={"step2": "done"})

        planner.add_operator(op1)
        planner.add_operator(op2)

        # Create plan manually
        plan = HTNPlan()
        plan.add_operator(op1)
        plan.add_operator(op2)
        plan.status = PlanStatus.READY

        # Execute plan
        initial_state = {}
        final_state = planner.execute_plan(plan, initial_state)

        assert final_state["step1"] == "done"
        assert final_state["step2"] == "done"
        assert plan.is_complete()
        assert plan.status == PlanStatus.COMPLETED


# ============================================================================
# Swarm Intelligence Tests
# ============================================================================


class TestAntColonyOptimizer:
    """Test Ant Colony Optimization."""

    def test_aco_initialization(self):
        """Test ACO creation."""
        aco = AntColonyOptimizer(
            n_ants=10,
            alpha=1.0,
            beta=2.0,
            evaporation_rate=0.1,
        )

        assert aco.n_ants == 10
        assert aco.alpha == 1.0
        assert aco.beta == 2.0
        assert aco.evaporation_rate == 0.1

    def test_add_edge(self):
        """Test adding edges to ACO graph."""
        aco = AntColonyOptimizer(n_ants=5)

        aco.add_edge("A", "B", distance=2.0)

        assert ("A", "B") in aco.edges
        assert ("B", "A") in aco.edges  # Bidirectional
        assert aco.edges[("A", "B")].distance == 2.0

    def test_simple_path_finding(self):
        """Test ACO path finding."""
        aco = AntColonyOptimizer(n_ants=5)

        # Create simple graph: A -> B -> C
        aco.add_edge("A", "B", distance=1.0)
        aco.add_edge("B", "C", distance=1.0)

        # Find path
        path, cost = aco.optimize(start="A", goal="C", n_iterations=10)

        assert path is not None
        assert path[0] == "A"
        assert path[-1] == "C"
        assert cost == 2.0

    def test_optimal_path_selection(self):
        """Test ACO selects shorter path."""
        aco = AntColonyOptimizer(n_ants=20)

        # Create graph with two paths:
        # A -> B -> C (cost 2)
        # A -> C (cost 5)
        aco.add_edge("A", "B", distance=1.0)
        aco.add_edge("B", "C", distance=1.0)
        aco.add_edge("A", "C", distance=5.0)

        # Find path
        path, cost = aco.optimize(start="A", goal="C", n_iterations=50)

        # Should prefer shorter path
        assert cost <= 2.0


class TestParticleSwarmOptimizer:
    """Test Particle Swarm Optimization."""

    def test_pso_initialization(self):
        """Test PSO creation."""

        def sphere(x):
            return np.sum(x**2)

        pso = ParticleSwarmOptimizer(
            n_particles=10,
            dimensions=3,
            bounds=[(-5, 5)] * 3,
            objective_func=sphere,
        )

        assert pso.n_particles == 10
        assert pso.dimensions == 3
        assert len(pso.particles) == 10

    def test_pso_sphere_optimization(self):
        """Test PSO on sphere function."""

        # Sphere function: f(x) = sum(x^2), minimum at x=[0,0,0]
        def sphere(x):
            return np.sum(x**2)

        pso = ParticleSwarmOptimizer(
            n_particles=20,
            dimensions=3,
            bounds=[(-5, 5)] * 3,
            objective_func=sphere,
            minimize=True,
        )

        # Optimize
        best_pos, best_score = pso.optimize(n_iterations=50)

        # Should find minimum near [0, 0, 0]
        assert best_score < 0.1
        assert all(abs(x) < 0.5 for x in best_pos)

    def test_pso_statistics(self):
        """Test PSO statistics."""

        def simple(x):
            return x[0]

        pso = ParticleSwarmOptimizer(
            n_particles=5,
            dimensions=1,
            bounds=[(-10, 10)],
            objective_func=simple,
        )

        stats = pso.get_statistics()

        assert "iteration" in stats
        assert "global_best_score" in stats
        assert "mean_score" in stats

    def test_pso_maximization(self):
        """Test PSO maximization mode."""

        # Negative sphere: maximize by finding maximum
        def neg_sphere(x):
            return -np.sum(x**2)

        pso = ParticleSwarmOptimizer(
            n_particles=20,
            dimensions=2,
            bounds=[(-5, 5)] * 2,
            objective_func=neg_sphere,
            minimize=False,  # Maximize
        )

        best_pos, best_score = pso.optimize(n_iterations=50)

        # Maximum is at [0, 0] with score 0
        assert best_score > -0.1
        assert all(abs(x) < 0.5 for x in best_pos)


class TestMixinComposition:
    """The intelligence mixins combine with each other and with a persona."""

    def test_all_mixins_on_a_real_persona(self):
        from unistax.agents import DataEngineerAgent

        class FullStack(RLAgent, HTNAgent, SwarmAgent, DataEngineerAgent):
            pass

        agent = FullStack("eng_full", team_id=None)

        assert agent.agent_id == "eng_full" and agent.persona == "data_engineer"
        agent.enable_rl_learning()
        agent.setup_aco(n_ants=3)
        assert agent.rl_enabled and agent.aco is not None
        assert agent.htn_planner.get_statistics()["operators"] == 0
        assert agent.get_swarm_stats()["aco"]["n_ants"] == 3

    def test_mixin_order_does_not_matter(self):
        from unistax.agents import DataAnalystAgent

        class Reordered(SwarmAgent, HTNAgent, RLAgent, DataAnalystAgent):
            pass

        agent = Reordered("ana_full")
        assert agent.persona == "data_analyst" and agent.htn_planner is not None


class TestSwarmAgent:
    """Test swarm agent mixin."""

    def test_swarm_agent_initialization(self):
        """Test swarm agent setup."""

        class TestAgent(SwarmAgent):
            def __init__(self):
                SwarmAgent.__init__(self)

        agent = TestAgent()
        assert agent.aco is None
        assert agent.pso is None

    def test_setup_aco(self):
        """Test ACO setup on agent."""

        class TestAgent(SwarmAgent):
            def __init__(self):
                SwarmAgent.__init__(self)

        agent = TestAgent()
        agent.setup_aco(n_ants=10)

        assert agent.aco is not None
        assert agent.aco.n_ants == 10

    def test_setup_pso(self):
        """Test PSO setup on agent."""

        class TestAgent(SwarmAgent):
            def __init__(self):
                SwarmAgent.__init__(self)

        agent = TestAgent()

        def objective(x):
            return np.sum(x**2)

        agent.setup_pso(
            n_particles=10,
            dimensions=2,
            bounds=[(-5, 5)] * 2,
            objective_func=objective,
        )

        assert agent.pso is not None
        assert agent.pso.n_particles == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
