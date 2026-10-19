"""Swarms: a planner splits a goal into subtasks that LLM workers carry out in parallel."""

from unistax.agents.swarm.events import SwarmFinishedEvent
from unistax.agents.swarm.plan import Plan, PlanError, PlannedStep, make_plan, validate_plan

__all__ = [
    "Plan",
    "PlanError",
    "PlannedStep",
    "SwarmFinishedEvent",
    "make_plan",
    "validate_plan",
]
