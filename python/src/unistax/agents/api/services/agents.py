"""Agent construction helpers."""

from __future__ import annotations

from collections.abc import Callable

from unistax.agents.base import Agent, Skill
from unistax.agents.personas.data_analyst import DataAnalystAgent
from unistax.agents.personas.data_engineer import DataEngineerAgent
from unistax.agents.personas.data_scientist import DataScientistAgent
from unistax.agents.personas.data_steward import DataStewardAgent
from unistax.events import EventBus
from unistax.metrics import MetricsManager

PERSONAS: dict[str, Callable[..., Agent]] = {
    "data_engineer": DataEngineerAgent,
    "data_analyst": DataAnalystAgent,
    "data_scientist": DataScientistAgent,
    "data_steward": DataStewardAgent,
}

_ALIASES = {
    "engineer": "data_engineer",
    "analyst": "data_analyst",
    "scientist": "data_scientist",
    "steward": "data_steward",
}


def resolve_persona(name: str) -> str | None:
    """Canonical persona name for ``name`` (accepts short aliases), or None."""
    key = name.strip().lower()
    key = _ALIASES.get(key, key)
    return key if key in PERSONAS else None


def supported_task_types(persona: str) -> frozenset[str] | None:
    """Task types a persona handles (None means 'unrestricted')."""
    cls = PERSONAS.get(persona)
    return getattr(cls, "TASK_TYPES", None) if cls else None


def to_skills(values: dict[str, float]) -> list[Skill]:
    return [
        Skill(name=name, proficiency=value, category="custom") for name, value in values.items()
    ]


def build_agent(
    *,
    agent_id: str,
    persona: str,
    event_bus: EventBus,
    metrics_manager: MetricsManager | None,
    team_id: str | None = None,
    skills: dict[str, float] | None = None,
    max_concurrent_tasks: int = 3,
) -> Agent:
    factory = PERSONAS[persona]
    return factory(
        agent_id=agent_id,
        event_bus=event_bus,
        metrics_manager=metrics_manager,
        team_id=team_id,
        skills=to_skills(skills) if skills else None,
        max_concurrent_tasks=max_concurrent_tasks,
    )
