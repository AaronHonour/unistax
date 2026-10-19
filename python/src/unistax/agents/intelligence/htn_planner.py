"""Hierarchical Task Network (HTN) Planning for agent task decomposition.

Provides HTN planning capabilities for complex task decomposition:
- Hierarchical task breakdown
- Method selection for task decomposition
- Precondition checking and state management
- Plan generation and validation
- Multi-step plan execution

HTN planning enables agents to:
- Break complex tasks into achievable subtasks
- Select appropriate decomposition methods
- Plan multi-step workflows
- Adapt plans based on world state
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from unistax.logging import get_logger

logger = get_logger(__name__)


class TaskType(Enum):
    """Types of HTN tasks."""

    PRIMITIVE = "primitive"  # Directly executable action
    COMPOUND = "compound"  # Needs decomposition into subtasks


class PlanStatus(Enum):
    """Status of HTN plan."""

    PLANNING = "planning"
    READY = "ready"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class HTNTask:
    """Task in HTN hierarchy.

    Can be primitive (directly executable) or compound (needs decomposition).
    """

    name: str
    task_type: TaskType
    parameters: dict[str, Any] = field(default_factory=dict)
    preconditions: dict[str, Any] = field(default_factory=dict)
    effects: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        """String representation of task."""
        params = ", ".join(f"{k}={v}" for k, v in self.parameters.items())
        return f"{self.name}({params})"


@dataclass
class HTNMethod:
    """Method for decomposing compound task into subtasks.

    A compound task may have multiple methods for decomposition.
    The planner selects the first applicable method.
    """

    name: str
    task_name: str  # Which compound task this method decomposes
    preconditions: dict[str, Any] = field(default_factory=dict)
    subtasks: list[HTNTask] = field(default_factory=list)
    ordering_constraints: list[tuple[int, int]] = field(
        default_factory=list
    )  # (before, after) indices

    def is_applicable(self, state: dict[str, Any]) -> bool:
        """Check if method is applicable in current state.

        Args:
            state: Current world state

        Returns:
            True if all preconditions are met
        """
        for key, expected_value in self.preconditions.items():
            if key not in state or state[key] != expected_value:
                return False
        return True


@dataclass
class HTNOperator:
    """Primitive operator (executable action).

    Operators are the atomic actions that agents can execute.
    """

    name: str
    preconditions: dict[str, Any] = field(default_factory=dict)
    effects: dict[str, Any] = field(default_factory=dict)
    cost: float = 1.0
    executor: Callable | None = None  # Function to execute this operator

    def is_applicable(self, state: dict[str, Any]) -> bool:
        """Check if operator is applicable in current state.

        Args:
            state: Current world state

        Returns:
            True if all preconditions are met
        """
        for key, expected_value in self.preconditions.items():
            if key not in state or state[key] != expected_value:
                return False
        return True

    def apply(self, state: dict[str, Any]) -> dict[str, Any]:
        """Apply operator effects to state.

        Args:
            state: Current world state

        Returns:
            New state after applying effects
        """
        new_state = state.copy()
        new_state.update(self.effects)
        return new_state


@dataclass
class HTNPlan:
    """HTN plan consisting of ordered primitive operators."""

    operators: list[HTNOperator] = field(default_factory=list)
    status: PlanStatus = PlanStatus.PLANNING
    total_cost: float = 0.0
    current_step: int = 0

    def add_operator(self, operator: HTNOperator):
        """Add operator to plan.

        Args:
            operator: Operator to add
        """
        self.operators.append(operator)
        self.total_cost += operator.cost

    def get_next_operator(self) -> HTNOperator | None:
        """Get next operator to execute.

        Returns:
            Next operator or None if plan complete
        """
        if self.current_step < len(self.operators):
            return self.operators[self.current_step]
        return None

    def advance(self):
        """Advance to next step in plan."""
        self.current_step += 1
        if self.current_step >= len(self.operators):
            self.status = PlanStatus.COMPLETED

    def is_complete(self) -> bool:
        """Check if plan is complete.

        Returns:
            True if all operators executed
        """
        return self.current_step >= len(self.operators)


class HTNPlanner:
    """Hierarchical Task Network planner.

    Uses HTN planning to decompose complex tasks into executable operators.

    HTN planning works by:
    1. Starting with high-level goal task
    2. Finding applicable methods to decompose compound tasks
    3. Recursively decomposing until all tasks are primitive
    4. Generating ordered sequence of primitive operators

    Examples:
        >>> # Define domain
        >>> planner = HTNPlanner()
        >>>
        >>> # Define primitive operators
        >>> fetch_data = HTNOperator(
        ...     name="fetch_data",
        ...     preconditions={"data_source": "available"},
        ...     effects={"data": "fetched"},
        ... )
        >>> planner.add_operator(fetch_data)
        >>>
        >>> # Define compound tasks and methods
        >>> analyze_task = HTNTask(
        ...     name="analyze_data",
        ...     task_type=TaskType.COMPOUND,
        ... )
        >>> planner.add_task(analyze_task)
        >>>
        >>> method = HTNMethod(
        ...     name="standard_analysis",
        ...     task_name="analyze_data",
        ...     subtasks=[fetch_task, process_task, report_task],
        ... )
        >>> planner.add_method(method)
        >>>
        >>> # Plan for goal
        >>> initial_state = {"data_source": "available"}
        >>> plan = planner.plan(analyze_task, initial_state)
        >>>
        >>> # Execute plan
        >>> state = initial_state
        >>> while not plan.is_complete():
        ...     op = plan.get_next_operator()
        ...     if op.is_applicable(state):
        ...         state = op.apply(state)
        ...         plan.advance()
    """

    def __init__(self):
        """Initialize HTN planner."""
        self.tasks: dict[str, HTNTask] = {}
        self.operators: dict[str, HTNOperator] = {}
        self.methods: dict[str, list[HTNMethod]] = {}  # task_name -> methods

        logger.info("Initialized HTN planner")

    def add_task(self, task: HTNTask):
        """Add task to domain.

        Args:
            task: Task to add
        """
        self.tasks[task.name] = task
        logger.debug(f"Added HTN task: {task.name} (type={task.task_type.value})")

    def add_operator(self, operator: HTNOperator):
        """Add operator to domain.

        Args:
            operator: Operator to add
        """
        self.operators[operator.name] = operator
        logger.debug(f"Added HTN operator: {operator.name}")

    def add_method(self, method: HTNMethod):
        """Add method for decomposing compound tasks.

        Args:
            method: Method to add
        """
        if method.task_name not in self.methods:
            self.methods[method.task_name] = []

        self.methods[method.task_name].append(method)
        logger.debug(
            f"Added HTN method: {method.name} for task {method.task_name} "
            f"({len(method.subtasks)} subtasks)"
        )

    def plan(
        self,
        goal_task: HTNTask,
        initial_state: dict[str, Any],
        max_depth: int = 10,
    ) -> HTNPlan | None:
        """Generate plan to achieve goal task.

        Uses depth-first HTN planning algorithm.

        Args:
            goal_task: Goal task to achieve
            initial_state: Initial world state
            max_depth: Maximum decomposition depth

        Returns:
            HTN plan or None if no plan found
        """
        logger.info(f"Planning for goal: {goal_task}")

        plan = HTNPlan()
        state = initial_state.copy()

        # Decompose goal task
        success = self._decompose(
            tasks=[goal_task],
            state=state,
            plan=plan,
            depth=0,
            max_depth=max_depth,
        )

        if success:
            plan.status = PlanStatus.READY
            logger.info(
                f"Plan generated: {len(plan.operators)} operators, cost={plan.total_cost:.2f}"
            )
            return plan
        else:
            logger.warning(f"Failed to generate plan for {goal_task}")
            return None

    def _decompose(
        self,
        tasks: list[HTNTask],
        state: dict[str, Any],
        plan: HTNPlan,
        depth: int,
        max_depth: int,
    ) -> bool:
        """Recursively decompose tasks into operators.

        Args:
            tasks: List of tasks to decompose
            state: Current world state
            plan: Plan being built
            depth: Current decomposition depth
            max_depth: Maximum allowed depth

        Returns:
            True if decomposition successful
        """
        if depth > max_depth:
            logger.warning(f"Max decomposition depth {max_depth} exceeded")
            return False

        if not tasks:
            # No more tasks - success
            return True

        # Process first task
        current_task = tasks[0]
        remaining_tasks = tasks[1:]

        logger.debug(f"{'  ' * depth}Decomposing: {current_task}")

        if current_task.task_type == TaskType.PRIMITIVE:
            # Primitive task - find corresponding operator
            operator = self.operators.get(current_task.name)

            if not operator:
                logger.warning(f"No operator found for primitive task: {current_task.name}")
                return False

            if not operator.is_applicable(state):
                logger.debug(
                    f"{'  ' * depth}Operator {operator.name} not applicable in current state"
                )
                return False

            # Add operator to plan and update state
            plan.add_operator(operator)
            new_state = operator.apply(state)

            # Continue with remaining tasks
            return self._decompose(remaining_tasks, new_state, plan, depth, max_depth)

        elif current_task.task_type == TaskType.COMPOUND:
            # Compound task - try methods for decomposition
            methods = self.methods.get(current_task.name, [])

            if not methods:
                logger.warning(f"No methods found for compound task: {current_task.name}")
                return False

            # Try each method until one succeeds
            for method in methods:
                if not method.is_applicable(state):
                    logger.debug(
                        f"{'  ' * depth}Method {method.name} not applicable in current state"
                    )
                    continue

                logger.debug(
                    f"{'  ' * depth}Trying method: {method.name} "
                    f"({len(method.subtasks)} subtasks)"
                )

                # Try decomposing with this method
                # Insert subtasks before remaining tasks
                new_tasks = method.subtasks + remaining_tasks

                if self._decompose(new_tasks, state.copy(), plan, depth + 1, max_depth):
                    return True

            # No method succeeded
            logger.debug(f"{'  ' * depth}All methods failed for {current_task.name}")
            return False

        return False

    def execute_plan(
        self,
        plan: HTNPlan,
        initial_state: dict[str, Any],
        executor: Callable | None = None,
    ) -> dict[str, Any]:
        """Execute HTN plan.

        Args:
            plan: Plan to execute
            initial_state: Initial world state
            executor: Optional custom executor function

        Returns:
            Final state after plan execution
        """
        logger.info(f"Executing HTN plan: {len(plan.operators)} operators")

        plan.status = PlanStatus.EXECUTING
        state = initial_state.copy()
        executed = 0

        while not plan.is_complete():
            operator = plan.get_next_operator()

            if not operator:
                break

            logger.debug(
                f"Executing operator {executed + 1}/{len(plan.operators)}: {operator.name}"
            )

            # Check preconditions
            if not operator.is_applicable(state):
                logger.error(f"Operator {operator.name} not applicable in state: {state}")
                plan.status = PlanStatus.FAILED
                break

            # Execute operator
            if executor:
                # Use custom executor
                state = executor(operator, state)
            elif operator.executor:
                # Use operator's executor
                state = operator.executor(state)
            else:
                # Just apply effects
                state = operator.apply(state)

            plan.advance()
            executed += 1

        if plan.is_complete():
            logger.info(f"Plan execution completed: {executed} operators executed")
            plan.status = PlanStatus.COMPLETED
        else:
            logger.warning(f"Plan execution incomplete: {executed}/{len(plan.operators)}")

        return state

    def get_statistics(self) -> dict[str, Any]:
        """Get planner statistics.

        Returns:
            Statistics dictionary
        """
        primitive_tasks = sum(1 for t in self.tasks.values() if t.task_type == TaskType.PRIMITIVE)
        compound_tasks = sum(1 for t in self.tasks.values() if t.task_type == TaskType.COMPOUND)

        return {
            "total_tasks": len(self.tasks),
            "primitive_tasks": primitive_tasks,
            "compound_tasks": compound_tasks,
            "operators": len(self.operators),
            "methods": sum(len(methods) for methods in self.methods.values()),
            "avg_methods_per_task": (
                sum(len(methods) for methods in self.methods.values()) / len(self.methods)
                if self.methods
                else 0
            ),
        }


class HTNAgent:
    """Mixin to add HTN planning capabilities to agents.

    Usage:
        >>> class MyAgent(HTNAgent, Agent):
        ...     def __init__(self, agent_id: str, **kwargs):
        ...         Agent.__init__(self, agent_id, **kwargs)
        ...         HTNAgent.__init__(self)
        ...         self._setup_htn_domain()
        ...
        ...     def _setup_htn_domain(self):
        ...         # Define operators
        ...         self.htn_planner.add_operator(...)
        ...         # Define tasks
        ...         self.htn_planner.add_task(...)
        ...         # Define methods
        ...         self.htn_planner.add_method(...)
        ...
        ...     async def execute_task(self, task: Task):
        ...         # Use HTN planning
        ...         goal = HTNTask(name=task.type, task_type=TaskType.COMPOUND)
        ...         state = self._get_current_state()
        ...         plan = self.htn_planner.plan(goal, state)
        ...         if plan:
        ...             result = self.htn_planner.execute_plan(plan, state)
        ...             return result
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize HTN planning for agent (cooperative with other mixins)."""
        super().__init__(*args, **kwargs)
        self.htn_planner = HTNPlanner()
        logger.info("HTN planning enabled for agent")

    def get_htn_stats(self) -> dict[str, Any]:
        """Get HTN planning statistics.

        Returns:
            Statistics dictionary
        """
        return self.htn_planner.get_statistics()
