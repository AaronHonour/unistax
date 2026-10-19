"""Plans: what the planner returns, validated before anything is run."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from unistax.agents.llm import LLMError, LLMGateway, LLMRequest, Usage
from unistax.agents.llm.profiles import PLANNER, PROFILES
from unistax.agents.swarm import prompts

RESERVED_IDS = frozenset({"synthesize", "review"})
WORKER_ROLES = tuple(r for r in PROFILES if r != "synthesizer")
_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class PlanError(LLMError):
    """The planner could not produce a valid plan."""


class PlannedStep(BaseModel):
    """One subtask."""

    id: str
    role: str
    title: str = Field(min_length=1, max_length=120)
    instructions: str = Field(min_length=10, max_length=4000)
    depends_on: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("title", "instructions")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class Plan(BaseModel):
    """A validated plan: independent steps plus dependencies, with a rationale."""

    rationale: str = Field(default="", max_length=2000)
    steps: list[PlannedStep]

    def as_dict(self) -> dict[str, Any]:
        """JSON-friendly form."""
        return self.model_dump()


def validate_plan(data: Any, *, max_steps: int) -> Plan:
    """Parse and check ``data``.

    Raises:
        PlanError: With every problem found, so a repair attempt can address them all.
    """
    if not isinstance(data, dict):
        raise PlanError("the plan must be a JSON object with 'rationale' and 'steps'")
    try:
        plan = Plan.model_validate(data)
    except ValidationError as exc:
        invalid = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:10]]
        raise PlanError("; ".join(invalid)) from None

    problems: list[str] = []
    if not 1 <= len(plan.steps) <= max_steps:
        problems.append(
            f"the plan must have between 1 and {max_steps} steps (it has {len(plan.steps)})"
        )

    ids = [s.id for s in plan.steps]
    for duplicate in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"step id '{duplicate}' is used more than once")
    known = set(ids)

    for step in plan.steps:
        if not _ID.match(step.id):
            problems.append(
                f"step id '{step.id}' must use lowercase letters, digits and underscore "
                "and start with a letter"
            )
        if step.id in RESERVED_IDS:
            problems.append(f"step id '{step.id}' is reserved")
        if step.role not in WORKER_ROLES:
            problems.append(
                f"step '{step.id}' has unknown role '{step.role}' (use one of {list(WORKER_ROLES)})"
            )
        for dep in step.depends_on:
            if dep == step.id:
                problems.append(f"step '{step.id}' depends on itself")
            elif dep not in known:
                problems.append(f"step '{step.id}' depends on unknown step '{dep}'")

    if not problems and _has_cycle(plan):
        problems.append("the steps contain a dependency cycle")
    if problems:
        raise PlanError("; ".join(problems))
    return plan


def _has_cycle(plan: Plan) -> bool:
    remaining = {s.id: set(s.depends_on) for s in plan.steps}
    while remaining:
        ready = [step for step, deps in remaining.items() if not deps]
        if not ready:
            return True
        for step in ready:
            del remaining[step]
        for deps in remaining.values():
            deps.difference_update(ready)
    return False


def _extract_json(text: str) -> Any:
    """Parse JSON from model text, tolerating a code fence or surrounding prose."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    for candidate in ([fenced.group(1)] if fenced else []) + [text]:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except (json.JSONDecodeError, ValueError):
            pass
    raise PlanError("the planner did not return valid JSON")


@dataclass(frozen=True)
class PlanningResult:
    """A plan and what it cost to get."""

    plan: Plan
    usage: Usage


async def make_plan(
    gateway: LLMGateway,
    *,
    goal: str,
    material: str,
    max_steps: int,
    run_id: str,
    model: str | None = None,
    effort: str | None = None,
    max_chars: int = 20_000,
) -> PlanningResult:
    """Ask the model for a plan; if it is invalid, ask once more with the problems listed.

    Raises:
        PlanError: Both attempts failed validation.
        LLMError: The model could not be reached (usage limit, auth, timeout, ...).
    """
    roles = {name: PROFILES[name].description for name in WORKER_ROLES}
    prompt = prompts.compose_planner_prompt(
        goal=goal, material=material, roles=roles, max_steps=max_steps, max_chars=max_chars
    )
    usage = Usage()
    last_problem = ""
    for _ in range(2):
        response = await gateway.run(
            LLMRequest(
                prompt=prompt,
                system_prompt=PLANNER.system_prompt,
                model=model,
                effort=effort,
                json_schema=prompts.PLAN_SCHEMA,
                run_id=run_id,
                label="plan",
            )
        )
        usage = usage + response.usage
        raw = response.structured if response.structured is not None else response.text
        try:
            data = _extract_json(raw) if isinstance(raw, str) else raw
            return PlanningResult(validate_plan(data, max_steps=max_steps), usage)
        except PlanError as exc:
            last_problem = str(exc)
            problems = [p.strip() for p in last_problem.split(";") if p.strip()]
            shown = json.dumps(raw, default=str)[:3000] if not isinstance(raw, str) else raw[:3000]
            prompt = prompts.compose_repair_prompt(shown, problems)
    raise PlanError(f"the planner could not produce a valid plan: {last_problem}")


__all__ = [
    "Plan",
    "PlanError",
    "PlannedStep",
    "PlanningResult",
    "make_plan",
    "validate_plan",
]
