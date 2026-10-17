"""Reinforcement Learning for agent decision making.

Provides ML-based decision making capabilities using RL:
- Q-learning for task selection
- Experience replay for learning
- Reward-based optimization
- Policy improvement over time
"""

import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from unistax.agents.base import Task, TaskStatus
from unistax.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Experience:
    """Single experience tuple for RL.

    Represents a state-action-reward-next_state tuple that
    the agent can learn from.
    """

    state: dict[str, Any]
    action: str
    reward: float
    next_state: dict[str, Any]
    done: bool
    timestamp: datetime = field(default_factory=datetime.now)


class AgentRLPolicy:
    """Reinforcement Learning policy for agent decision making.

    Uses Q-learning to learn optimal task selection and execution
    strategies based on experience.

    Examples:
        >>> policy = AgentRLPolicy(agent_id="eng_001")
        >>>
        >>> # Record experience
        >>> policy.record_experience(
        ...     state={"tasks_pending": 3, "success_rate": 0.85},
        ...     action="execute_task:task_123",
        ...     reward=1.0,
        ...     next_state={"tasks_pending": 2, "success_rate": 0.87},
        ... )
        >>>
        >>> # Get best action
        >>> action = policy.select_action(state)
    """

    def __init__(
        self,
        agent_id: str,
        learning_rate: float = 0.1,
        discount_factor: float = 0.95,
        exploration_rate: float = 0.3,
        exploration_decay: float = 0.995,
        min_exploration: float = 0.01,
        memory_size: int = 10000,
    ):
        """Initialize RL policy.

        Args:
            agent_id: Agent identifier
            learning_rate: Alpha for Q-learning
            discount_factor: Gamma for future rewards
            exploration_rate: Epsilon for epsilon-greedy
            exploration_decay: Rate of exploration decay
            min_exploration: Minimum exploration rate
            memory_size: Size of experience replay buffer
        """
        self.agent_id = agent_id
        self.learning_rate = learning_rate
        self.discount_factor = discount_factor
        self.exploration_rate = exploration_rate
        self.exploration_decay = exploration_decay
        self.min_exploration = min_exploration

        # Q-table: state -> action -> value
        self.q_table: dict[str, dict[str, float]] = {}

        # Experience replay
        self.memory: deque[Experience] = deque(maxlen=memory_size)

        # Statistics
        self.total_experiences = 0
        self.training_steps = 0
        self.avg_reward = 0.0

        logger.info(f"Initialized RL policy for agent {agent_id}")

    def _state_to_key(self, state: dict[str, Any]) -> str:
        """Convert state dict to hashable key.

        Args:
            state: State dictionary

        Returns:
            String key for state
        """
        # Sort keys for consistent hashing
        sorted_items = sorted(state.items())
        return json.dumps(sorted_items, sort_keys=True)

    def get_q_value(self, state: dict[str, Any], action: str) -> float:
        """Get Q-value for state-action pair.

        Args:
            state: Current state
            action: Action to evaluate

        Returns:
            Q-value (0.0 if not seen before)
        """
        state_key = self._state_to_key(state)

        if state_key not in self.q_table:
            self.q_table[state_key] = {}

        return self.q_table[state_key].get(action, 0.0)

    def update_q_value(
        self,
        state: dict[str, Any],
        action: str,
        value: float,
    ):
        """Update Q-value for state-action pair.

        Args:
            state: Current state
            action: Action taken
            value: New Q-value
        """
        state_key = self._state_to_key(state)

        if state_key not in self.q_table:
            self.q_table[state_key] = {}

        self.q_table[state_key][action] = value

    def select_action(
        self,
        state: dict[str, Any],
        available_actions: list[str],
        training: bool = True,
    ) -> str:
        """Select action using epsilon-greedy strategy.

        Args:
            state: Current state
            available_actions: List of valid actions
            training: Whether in training mode (explore) or not

        Returns:
            Selected action
        """
        if not available_actions:
            raise ValueError("No available actions")

        # Exploration: random action
        if training and np.random.random() < self.exploration_rate:
            action = np.random.choice(available_actions)
            logger.debug(f"Agent {self.agent_id} exploring: {action}")
            return action

        # Exploitation: best known action
        q_values = {action: self.get_q_value(state, action) for action in available_actions}

        best_action = max(q_values.items(), key=lambda x: x[1])[0]
        logger.debug(
            f"Agent {self.agent_id} exploiting: {best_action} " f"(Q={q_values[best_action]:.3f})"
        )

        return best_action

    def record_experience(
        self,
        state: dict[str, Any],
        action: str,
        reward: float,
        next_state: dict[str, Any],
        done: bool = False,
    ):
        """Record an experience for learning.

        Args:
            state: State before action
            action: Action taken
            reward: Reward received
            next_state: State after action
            done: Whether episode ended
        """
        experience = Experience(
            state=state,
            action=action,
            reward=reward,
            next_state=next_state,
            done=done,
        )

        self.memory.append(experience)
        self.total_experiences += 1

        # Update running average reward
        alpha = 0.1
        self.avg_reward = (1 - alpha) * self.avg_reward + alpha * reward

        logger.debug(
            f"Agent {self.agent_id} recorded experience: " f"action={action}, reward={reward:.2f}"
        )

    def learn_from_experience(self, experience: Experience):
        """Update Q-values from a single experience.

        Args:
            experience: Experience tuple
        """
        state = experience.state
        action = experience.action
        reward = experience.reward
        next_state = experience.next_state
        done = experience.done

        # Current Q-value
        current_q = self.get_q_value(state, action)

        # Best next Q-value
        if done:
            max_next_q = 0.0
        else:
            # Get all known actions for next state
            next_state_key = self._state_to_key(next_state)
            next_actions = self.q_table.get(next_state_key, {})

            if next_actions:
                max_next_q = max(next_actions.values())
            else:
                max_next_q = 0.0

        # Q-learning update: Q(s,a) = Q(s,a) + α[r + γ·max_a'Q(s',a') - Q(s,a)]
        new_q = current_q + self.learning_rate * (
            reward + self.discount_factor * max_next_q - current_q
        )

        self.update_q_value(state, action, new_q)
        self.training_steps += 1

    def train_on_batch(self, batch_size: int = 32) -> dict[str, float]:
        """Train on a batch of experiences from replay memory.

        Args:
            batch_size: Number of experiences to sample

        Returns:
            Training statistics
        """
        if len(self.memory) < batch_size:
            return {"trained": False, "reason": "insufficient_data"}

        # Sample random batch
        indices = np.random.choice(len(self.memory), batch_size, replace=False)
        batch = [self.memory[i] for i in indices]

        # Learn from each experience
        initial_steps = self.training_steps
        for experience in batch:
            self.learn_from_experience(experience)

        # Decay exploration
        self.exploration_rate = max(
            self.min_exploration,
            self.exploration_rate * self.exploration_decay,
        )

        return {
            "trained": True,
            "batch_size": batch_size,
            "training_steps": self.training_steps - initial_steps,
            "exploration_rate": self.exploration_rate,
            "avg_reward": self.avg_reward,
        }

    def get_statistics(self) -> dict[str, Any]:
        """Get RL policy statistics.

        Returns:
            Statistics dictionary
        """
        return {
            "agent_id": self.agent_id,
            "total_experiences": self.total_experiences,
            "training_steps": self.training_steps,
            "memory_size": len(self.memory),
            "q_table_states": len(self.q_table),
            "exploration_rate": self.exploration_rate,
            "avg_reward": self.avg_reward,
        }

    def save_policy(self, filepath: str):
        """Save Q-table to file.

        Args:
            filepath: Path to save file
        """
        policy_data = {
            "agent_id": self.agent_id,
            "q_table": self.q_table,
            "statistics": self.get_statistics(),
        }

        with open(filepath, "w") as f:
            json.dump(policy_data, f, indent=2)

        logger.info(f"Saved RL policy to {filepath}")

    def load_policy(self, filepath: str):
        """Load Q-table from file.

        Args:
            filepath: Path to load from
        """
        with open(filepath) as f:
            policy_data = json.load(f)

        self.q_table = policy_data["q_table"]

        logger.info(f"Loaded RL policy from {filepath}")


class RLAgent:
    """Mixin for agents with RL capabilities.

    Adds reinforcement learning decision making to agents.

    Examples:
        >>> class SmartDataEngineer(RLAgent, DataEngineerAgent):
        ...     pass
        >>>
        >>> agent = SmartDataEngineer("eng_001")
        >>> agent.enable_rl_learning()
    """

    def __init__(self, *args, **kwargs):
        """Initialize RL-capable agent."""
        super().__init__(*args, **kwargs)

        # RL policy
        self.rl_policy: AgentRLPolicy | None = None
        self.rl_enabled = False

        # Track current episode
        self.current_state: dict[str, Any] | None = None
        self.last_action: str | None = None

    def enable_rl_learning(self, **rl_kwargs):
        """Enable reinforcement learning.

        Args:
            **rl_kwargs: Arguments for AgentRLPolicy
        """
        self.rl_policy = AgentRLPolicy(
            agent_id=self.agent_id,
            **rl_kwargs,
        )
        self.rl_enabled = True

        logger.info(f"Enabled RL learning for agent {self.agent_id}")

    def disable_rl_learning(self):
        """Disable reinforcement learning."""
        self.rl_enabled = False
        logger.info(f"Disabled RL learning for agent {self.agent_id}")

    def get_current_state(self) -> dict[str, Any]:
        """Get current agent state for RL.

        Returns:
            State dictionary with relevant features
        """
        metrics = self.get_metrics()

        return {
            "tasks_pending": len(self.current_tasks),
            "success_rate": metrics["success_rate"],
            "tasks_completed": metrics["tasks_completed"],
            "tasks_failed": metrics["tasks_failed"],
            "state": self.state.value,
        }

    def calculate_reward(self, task: Task) -> float:
        """Calculate reward for task completion.

        Args:
            task: Completed task

        Returns:
            Reward value
        """
        if task.status == TaskStatus.COMPLETED:
            # Base reward for completion
            reward = 1.0

            # Bonus for high priority tasks
            if task.priority >= 8:
                reward += 0.5

            # Bonus for fast completion
            if task.duration():
                # Reward faster execution (assuming 60s baseline)
                time_factor = min(1.0, 60.0 / task.duration())
                reward += 0.3 * time_factor

            return reward

        elif task.status == TaskStatus.FAILED:
            # Penalty for failure
            return -1.0

        return 0.0

    async def rl_decide(self, available_actions: list[str]) -> str | None:
        """Make decision using RL policy.

        Args:
            available_actions: List of valid actions

        Returns:
            Selected action or None
        """
        if not self.rl_enabled or not self.rl_policy:
            return None

        if not available_actions:
            return None

        # Get current state
        state = self.get_current_state()

        # Select action
        action = self.rl_policy.select_action(
            state=state,
            available_actions=available_actions,
        )

        # Track for next reward
        self.current_state = state
        self.last_action = action

        return action

    async def rl_record_task_result(self, task: Task):
        """Record task result for RL learning.

        Args:
            task: Completed task
        """
        if not self.rl_enabled or not self.rl_policy:
            return

        if self.current_state is None or self.last_action is None:
            return

        # Calculate reward
        reward = self.calculate_reward(task)

        # Get new state
        next_state = self.get_current_state()

        # Record experience
        self.rl_policy.record_experience(
            state=self.current_state,
            action=self.last_action,
            reward=reward,
            next_state=next_state,
            done=(task.status == TaskStatus.FAILED),
        )

        # Train periodically
        if self.rl_policy.total_experiences % 10 == 0:
            stats = self.rl_policy.train_on_batch(batch_size=32)
            if stats.get("trained"):
                logger.info(
                    f"Agent {self.agent_id} trained: "
                    f"steps={stats['training_steps']}, "
                    f"ε={stats['exploration_rate']:.3f}"
                )

        # Reset episode tracking
        self.current_state = None
        self.last_action = None
