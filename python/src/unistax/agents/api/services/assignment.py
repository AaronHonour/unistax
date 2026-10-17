"""Choosing which agent should run a task."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from unistax.agents.base import Agent, AgentState, Task
from unistax.agents.registry import AgentRegistry


@dataclass(frozen=True)
class Candidate:
    agent: Agent
    confidence: float
    load: int


def rank_agents(
    registry: AgentRegistry,
    task: Task,
    load_of: Callable[[str], int],
    only: Agent | None = None,
) -> list[Candidate]:
    """Agents able to run ``task``, best first (confidence, then least loaded).

    Capacity is deliberately ignored: tasks queue for a busy agent rather than
    being rejected.
    """
    agents = [only] if only else list(registry.agents.values())
    ranked: list[Candidate] = []
    for agent in agents:
        if agent.state == AgentState.SHUTDOWN:
            continue
        allowed = getattr(agent, "TASK_TYPES", None)
        if allowed is not None and task.type not in allowed:
            continue
        ok, confidence = agent.can_do(task, check_capacity=False)
        if ok:
            ranked.append(Candidate(agent, confidence, load_of(agent.agent_id)))
    ranked.sort(key=lambda c: (-c.confidence, c.load, c.agent.agent_id))
    return ranked


def supported_types(registry: AgentRegistry) -> list[str]:
    types: set[str] = set()
    for agent in registry.agents.values():
        types.update(getattr(agent, "TASK_TYPES", None) or ())
    return sorted(types)
