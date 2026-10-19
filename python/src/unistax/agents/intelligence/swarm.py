"""Swarm Intelligence algorithms for multi-agent optimization.

Provides swarm intelligence capabilities for collaborative problem-solving:
- Ant Colony Optimization (ACO) for path finding and task allocation
- Particle Swarm Optimization (PSO) for continuous optimization
- Collective decision making
- Emergent behaviors from simple agent interactions

Swarm algorithms enable agents to:
- Solve complex optimization problems collaboratively
- Find optimal paths through task networks
- Tune hyperparameters collectively
- Make distributed decisions
"""

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from unistax.logging import get_logger

logger = get_logger(__name__)


# ============================================================================
# Ant Colony Optimization (ACO)
# ============================================================================


@dataclass
class ACOEdge:
    """Edge in ACO graph."""

    source: str
    target: str
    distance: float = 1.0  # Cost/distance of edge
    pheromone: float = 1.0  # Pheromone level
    heuristic: float = 1.0  # Heuristic information (e.g., 1/distance)


@dataclass
class ACOAnt:
    """Ant in ACO algorithm."""

    ant_id: int
    current_node: str
    path: list[str] = field(default_factory=list)
    path_cost: float = 0.0
    visited: set[str] = field(default_factory=set)

    def visit(self, node: str, cost: float):
        """Visit a node.

        Args:
            node: Node to visit
            cost: Cost to reach node
        """
        self.current_node = node
        self.path.append(node)
        self.visited.add(node)
        self.path_cost += cost

    def reset(self, start_node: str):
        """Reset ant to start position.

        Args:
            start_node: Starting node
        """
        self.current_node = start_node
        self.path = [start_node]
        self.path_cost = 0.0
        self.visited = {start_node}


class AntColonyOptimizer:
    """Ant Colony Optimization for path finding and task allocation.

    ACO uses artificial ants to find optimal paths through graphs.
    Ants deposit pheromones on edges, and paths with more pheromone
    are more likely to be chosen by future ants.

    Applications:
    - Task allocation in agent teams
    - Workflow path optimization
    - Resource routing
    - Job shop scheduling

    Examples:
        >>> # Create ACO optimizer
        >>> aco = AntColonyOptimizer(
        ...     n_ants=10,
        ...     alpha=1.0,  # Pheromone importance
        ...     beta=2.0,   # Heuristic importance
        ...     evaporation_rate=0.1,
        ... )
        >>>
        >>> # Add graph edges
        >>> aco.add_edge("A", "B", distance=2.0)
        >>> aco.add_edge("B", "C", distance=3.0)
        >>> aco.add_edge("A", "C", distance=6.0)
        >>>
        >>> # Find best path
        >>> best_path, best_cost = aco.optimize(
        ...     start="A",
        ...     goal="C",
        ...     n_iterations=100,
        ... )
    """

    def __init__(
        self,
        n_ants: int = 10,
        alpha: float = 1.0,
        beta: float = 2.0,
        evaporation_rate: float = 0.1,
        pheromone_deposit: float = 1.0,
        initial_pheromone: float = 1.0,
    ):
        """Initialize ACO.

        Args:
            n_ants: Number of ants
            alpha: Pheromone importance (higher = more pheromone influence)
            beta: Heuristic importance (higher = more heuristic influence)
            evaporation_rate: Pheromone evaporation rate (0-1)
            pheromone_deposit: Amount of pheromone deposited
            initial_pheromone: Initial pheromone level
        """
        self.n_ants = n_ants
        self.alpha = alpha
        self.beta = beta
        self.evaporation_rate = evaporation_rate
        self.pheromone_deposit = pheromone_deposit
        self.initial_pheromone = initial_pheromone

        self.edges: dict[tuple[str, str], ACOEdge] = {}
        self.nodes: set[str] = set()
        self.ants: list[ACOAnt] = []

        self.best_path: list[str] | None = None
        self.best_cost: float = float("inf")
        self.iteration_count: int = 0

        logger.info(f"Initialized ACO: {n_ants} ants, α={alpha}, β={beta}, ρ={evaporation_rate}")

    def add_edge(
        self,
        source: str,
        target: str,
        distance: float = 1.0,
        bidirectional: bool = True,
    ):
        """Add edge to graph.

        Args:
            source: Source node
            target: Target node
            distance: Edge distance/cost
            bidirectional: Add reverse edge too
        """
        # Calculate heuristic (inverse of distance)
        heuristic = 1.0 / distance if distance > 0 else 1.0

        edge = ACOEdge(
            source=source,
            target=target,
            distance=distance,
            pheromone=self.initial_pheromone,
            heuristic=heuristic,
        )

        self.edges[(source, target)] = edge
        self.nodes.add(source)
        self.nodes.add(target)

        if bidirectional:
            reverse_edge = ACOEdge(
                source=target,
                target=source,
                distance=distance,
                pheromone=self.initial_pheromone,
                heuristic=heuristic,
            )
            self.edges[(target, source)] = reverse_edge

        logger.debug(f"Added ACO edge: {source} -> {target} (distance={distance})")

    def _get_neighbors(self, node: str) -> list[str]:
        """Get neighbor nodes.

        Args:
            node: Current node

        Returns:
            List of neighbor nodes
        """
        neighbors = []
        for source, target in self.edges:
            if source == node:
                neighbors.append(target)
        return neighbors

    def _select_next_node(self, ant: ACOAnt, goal: str | None = None) -> str | None:
        """Select next node for ant using pheromone and heuristic.

        Uses probability: p = (pheromone^α * heuristic^β) / Σ(...)

        Args:
            ant: Ant selecting next node
            goal: Optional goal node

        Returns:
            Selected node or None if no options
        """
        current = ant.current_node

        # Get unvisited neighbors
        neighbors = [n for n in self._get_neighbors(current) if n not in ant.visited]

        if not neighbors:
            return None

        # Calculate probabilities
        probabilities = []
        total = 0.0

        for neighbor in neighbors:
            edge = self.edges[(current, neighbor)]

            # Probability based on pheromone and heuristic
            value = (edge.pheromone**self.alpha) * (edge.heuristic**self.beta)
            probabilities.append(value)
            total += value

        if total == 0:
            # Random selection
            return random.choice(neighbors)

        # Normalize probabilities
        probabilities = [p / total for p in probabilities]

        # Select node based on probabilities
        return random.choices(neighbors, weights=probabilities)[0]

    def _evaporate_pheromones(self):
        """Evaporate pheromones on all edges."""
        for edge in self.edges.values():
            edge.pheromone *= 1 - self.evaporation_rate

    def _deposit_pheromones(self, ant: ACOAnt):
        """Deposit pheromones on ant's path.

        Args:
            ant: Ant that completed path
        """
        if len(ant.path) < 2:
            return

        # Amount to deposit (inversely proportional to path cost)
        deposit = (
            self.pheromone_deposit / ant.path_cost if ant.path_cost > 0 else self.pheromone_deposit
        )

        # Deposit on each edge in path
        for i in range(len(ant.path) - 1):
            source = ant.path[i]
            target = ant.path[i + 1]

            if (source, target) in self.edges:
                self.edges[(source, target)].pheromone += deposit

    def optimize(
        self,
        start: str,
        goal: str,
        n_iterations: int = 100,
        max_steps: int = 100,
    ) -> tuple[list[str] | None, float]:
        """Run ACO optimization.

        Args:
            start: Start node
            goal: Goal node
            n_iterations: Number of iterations
            max_steps: Maximum steps per ant

        Returns:
            Tuple of (best_path, best_cost)
        """
        logger.info(f"ACO optimizing path: {start} -> {goal} ({n_iterations} iterations)")

        # Create ants
        self.ants = [ACOAnt(ant_id=i, current_node=start) for i in range(self.n_ants)]

        for ant in self.ants:
            ant.path = [start]
            ant.visited = {start}

        for iteration in range(n_iterations):
            # Reset ants
            for ant in self.ants:
                ant.reset(start)

            # Move ants
            for ant in self.ants:
                for _ in range(max_steps):
                    next_node = self._select_next_node(ant, goal)

                    if not next_node:
                        break

                    # Move ant
                    edge = self.edges[(ant.current_node, next_node)]
                    ant.visit(next_node, edge.distance)

                    # Check if reached goal
                    if next_node == goal:
                        # Update best path
                        if ant.path_cost < self.best_cost:
                            self.best_path = ant.path.copy()
                            self.best_cost = ant.path_cost
                            logger.debug(
                                f"Iteration {iteration}: New best path found "
                                f"(cost={self.best_cost:.2f})"
                            )
                        break

            # Evaporate pheromones
            self._evaporate_pheromones()

            # Deposit pheromones from ants that reached goal
            for ant in self.ants:
                if ant.path and ant.path[-1] == goal:
                    self._deposit_pheromones(ant)

            self.iteration_count += 1

        logger.info(
            f"ACO completed: best_cost={self.best_cost:.2f}, "
            f"path_length={len(self.best_path) if self.best_path else 0}"
        )

        return self.best_path, self.best_cost


# ============================================================================
# Particle Swarm Optimization (PSO)
# ============================================================================


@dataclass
class Particle:
    """Particle in PSO algorithm."""

    particle_id: int
    position: np.ndarray
    velocity: np.ndarray
    best_position: np.ndarray
    best_score: float
    current_score: float = float("inf")


class ParticleSwarmOptimizer:
    """Particle Swarm Optimization for continuous optimization.

    PSO uses particles that move through search space, influenced by
    their own best position and the swarm's best position.

    Applications:
    - Hyperparameter tuning
    - Feature selection weights
    - Resource allocation optimization
    - Threshold optimization

    Examples:
        >>> # Define objective function (minimize)
        >>> def sphere(x):
        ...     return np.sum(x ** 2)
        >>>
        >>> # Create PSO optimizer
        >>> pso = ParticleSwarmOptimizer(
        ...     n_particles=20,
        ...     dimensions=5,
        ...     bounds=[(-5, 5)] * 5,
        ...     objective_func=sphere,
        ... )
        >>>
        >>> # Optimize
        >>> best_position, best_score = pso.optimize(n_iterations=100)
        >>> print(f"Best score: {best_score}")
    """

    def __init__(
        self,
        n_particles: int,
        dimensions: int,
        bounds: list[tuple[float, float]],
        objective_func: Callable[[np.ndarray], float],
        minimize: bool = True,
        w: float = 0.7,
        c1: float = 1.5,
        c2: float = 1.5,
        v_max: float | None = None,
    ):
        """Initialize PSO.

        Args:
            n_particles: Number of particles
            dimensions: Problem dimensions
            bounds: Bounds for each dimension [(min, max), ...]
            objective_func: Function to optimize
            minimize: True to minimize, False to maximize
            w: Inertia weight (velocity persistence)
            c1: Cognitive coefficient (personal best influence)
            c2: Social coefficient (global best influence)
            v_max: Maximum velocity (None for unbounded)
        """
        self.n_particles = n_particles
        self.dimensions = dimensions
        self.bounds = np.array(bounds)
        self.objective_func = objective_func
        self.minimize = minimize
        self.w = w
        self.c1 = c1
        self.c2 = c2
        self.v_max = v_max

        self.particles: list[Particle] = []
        self.global_best_position: np.ndarray | None = None
        self.global_best_score: float = float("inf") if minimize else float("-inf")
        self.iteration_count: int = 0

        # Initialize particles
        self._initialize_particles()

        logger.info(
            f"Initialized PSO: {n_particles} particles, {dimensions}D, " f"w={w}, c1={c1}, c2={c2}"
        )

    def _initialize_particles(self):
        """Initialize particle swarm."""
        for i in range(self.n_particles):
            # Random position within bounds
            position = np.random.uniform(
                self.bounds[:, 0],
                self.bounds[:, 1],
                size=self.dimensions,
            )

            # Random velocity
            velocity = np.random.uniform(
                -1.0,
                1.0,
                size=self.dimensions,
            )

            # Evaluate initial position
            score = self.objective_func(position)

            particle = Particle(
                particle_id=i,
                position=position,
                velocity=velocity,
                best_position=position.copy(),
                best_score=score,
                current_score=score,
            )

            self.particles.append(particle)

            # Update global best
            if self._is_better(score, self.global_best_score):
                self.global_best_score = score
                self.global_best_position = position.copy()

    def _is_better(self, score1: float, score2: float) -> bool:
        """Check if score1 is better than score2.

        Args:
            score1: First score
            score2: Second score

        Returns:
            True if score1 is better
        """
        if self.minimize:
            return score1 < score2
        else:
            return score1 > score2

    def _update_velocity(self, particle: Particle):
        """Update particle velocity.

        Velocity equation:
        v = w*v + c1*r1*(pbest - x) + c2*r2*(gbest - x)

        Args:
            particle: Particle to update
        """
        # Random factors
        r1 = np.random.random(self.dimensions)
        r2 = np.random.random(self.dimensions)

        # Velocity components
        inertia = self.w * particle.velocity
        cognitive = self.c1 * r1 * (particle.best_position - particle.position)
        social = self.c2 * r2 * (self.global_best_position - particle.position)

        # Update velocity
        particle.velocity = inertia + cognitive + social

        # Clamp velocity if max specified
        if self.v_max is not None:
            particle.velocity = np.clip(particle.velocity, -self.v_max, self.v_max)

    def _update_position(self, particle: Particle):
        """Update particle position.

        Args:
            particle: Particle to update
        """
        # Update position
        particle.position += particle.velocity

        # Enforce bounds
        particle.position = np.clip(
            particle.position,
            self.bounds[:, 0],
            self.bounds[:, 1],
        )

    def optimize(self, n_iterations: int = 100) -> tuple[np.ndarray, float]:
        """Run PSO optimization.

        Args:
            n_iterations: Number of iterations

        Returns:
            Tuple of (best_position, best_score)
        """
        logger.info(f"PSO optimizing ({n_iterations} iterations)")

        for iteration in range(n_iterations):
            for particle in self.particles:
                # Update velocity and position
                self._update_velocity(particle)
                self._update_position(particle)

                # Evaluate new position
                score = self.objective_func(particle.position)
                particle.current_score = score

                # Update personal best
                if self._is_better(score, particle.best_score):
                    particle.best_score = score
                    particle.best_position = particle.position.copy()

                # Update global best
                if self._is_better(score, self.global_best_score):
                    self.global_best_score = score
                    self.global_best_position = particle.position.copy()
                    logger.debug(
                        f"Iteration {iteration}: New best score: {self.global_best_score:.6f}"
                    )

            self.iteration_count += 1

        logger.info(f"PSO completed: best_score={self.global_best_score:.6f}")

        return self.global_best_position, self.global_best_score

    def get_particle_positions(self) -> np.ndarray:
        """Get current positions of all particles.

        Returns:
            Array of particle positions (n_particles x dimensions)
        """
        return np.array([p.position for p in self.particles])

    def get_statistics(self) -> dict[str, Any]:
        """Get PSO statistics.

        Returns:
            Statistics dictionary
        """
        scores = [p.current_score for p in self.particles]

        return {
            "iteration": self.iteration_count,
            "global_best_score": self.global_best_score,
            "mean_score": np.mean(scores),
            "std_score": np.std(scores),
            "min_score": np.min(scores),
            "max_score": np.max(scores),
        }


class SwarmAgent:
    """Mixin to add swarm intelligence capabilities to agents.

    Usage:
        >>> class MyAgent(SwarmAgent, Agent):
        ...     def __init__(self, agent_id: str, **kwargs):
        ...         Agent.__init__(self, agent_id, **kwargs)
        ...         SwarmAgent.__init__(self)
        ...
        ...     async def optimize_path(self, start, goal):
        ...         # Use ACO for path finding
        ...         path, cost = self.aco.optimize(start, goal, n_iterations=50)
        ...         return path
        ...
        ...     async def tune_parameters(self, objective_func):
        ...         # Use PSO for hyperparameter tuning
        ...         best_params, score = self.pso.optimize(n_iterations=100)
        ...         return best_params
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize swarm intelligence for agent (cooperative with other mixins)."""
        super().__init__(*args, **kwargs)
        self.aco: AntColonyOptimizer | None = None
        self.pso: ParticleSwarmOptimizer | None = None
        logger.info("Swarm intelligence enabled for agent")

    def setup_aco(
        self,
        n_ants: int = 10,
        alpha: float = 1.0,
        beta: float = 2.0,
        evaporation_rate: float = 0.1,
    ):
        """Setup Ant Colony Optimization.

        Args:
            n_ants: Number of ants
            alpha: Pheromone importance
            beta: Heuristic importance
            evaporation_rate: Pheromone evaporation rate
        """
        self.aco = AntColonyOptimizer(
            n_ants=n_ants,
            alpha=alpha,
            beta=beta,
            evaporation_rate=evaporation_rate,
        )
        logger.info("ACO initialized for agent")

    def setup_pso(
        self,
        n_particles: int,
        dimensions: int,
        bounds: list[tuple[float, float]],
        objective_func: Callable[[np.ndarray], float],
        minimize: bool = True,
    ):
        """Setup Particle Swarm Optimization.

        Args:
            n_particles: Number of particles
            dimensions: Problem dimensions
            bounds: Bounds for each dimension
            objective_func: Function to optimize
            minimize: True to minimize, False to maximize
        """
        self.pso = ParticleSwarmOptimizer(
            n_particles=n_particles,
            dimensions=dimensions,
            bounds=bounds,
            objective_func=objective_func,
            minimize=minimize,
        )
        logger.info("PSO initialized for agent")

    def get_swarm_stats(self) -> dict[str, Any]:
        """Get swarm intelligence statistics.

        Returns:
            Statistics dictionary
        """
        stats = {}

        if self.aco:
            stats["aco"] = {
                "n_ants": self.aco.n_ants,
                "iterations": self.aco.iteration_count,
                "best_cost": self.aco.best_cost,
                "best_path_length": len(self.aco.best_path) if self.aco.best_path else 0,
            }

        if self.pso:
            stats["pso"] = self.pso.get_statistics()

        return stats
