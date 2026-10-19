"""A worker agent whose work is done by a language model (Claude Code in headless mode)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from unistax.agents.base import Agent, Skill, Task
from unistax.agents.llm import LLMNotConfigured, LLMRequest
from unistax.agents.llm.profiles import DEFAULT_ROLE, PROFILES
from unistax.agents.swarm import prompts
from unistax.events import EventBus
from unistax.logging import get_logger
from unistax.metrics import MetricsManager

if TYPE_CHECKING:
    from unistax.agents.llm import LLMGateway

logger = get_logger(__name__)

MAX_INSTRUCTIONS_CHARS = 20_000
MIN_INPUT_CHARS, MAX_INPUT_CHARS = 1_000, 200_000


class ClaudeWorkerAgent(Agent):
    """Carries out ``llm_task`` tasks by asking a model, in a role.

    The task context supplies ``instructions`` and optionally ``role`` (see
    ``unistax.agents.llm.profiles``), ``goal``, ``title``, ``material`` (source text),
    ``dependency_results`` (filled in by the orchestrator), ``output_schema``, ``model``,
    ``effort`` and ``swarm_id`` (the call budget to charge).

    Workers have no tools: they cannot run code, read files or reach the network. Without
    a configured model backend the task fails with a clear message; it is never simulated.
    """

    TASK_TYPES: ClassVar[frozenset[str]] = frozenset({"llm_task"})
    USES_LLM: ClassVar[bool] = True

    def __init__(
        self,
        agent_id: str,
        event_bus: EventBus | None = None,
        metrics_manager: MetricsManager | None = None,
        skills: list[Skill] | None = None,
        team_id: str | None = None,
        llm: LLMGateway | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the worker; ``llm`` is the gateway through which all calls go."""
        default_skills = [
            Skill("reasoning", 0.90, "llm"),
            Skill("analysis", 0.85, "llm"),
            Skill("writing", 0.85, "llm"),
            Skill("review", 0.80, "llm"),
            Skill("planning", 0.80, "llm"),
            Skill("synthesis", 0.85, "llm"),
        ]
        super().__init__(
            agent_id=agent_id,
            persona="claude_worker",
            skills=skills or default_skills,
            event_bus=event_bus,
            metrics_manager=metrics_manager,
            team_id=team_id,
            **kwargs,
        )
        self.llm = llm
        self.calls_made = 0

    async def decide(self) -> str | None:
        """Run the highest-priority queued task, otherwise stay idle."""
        if self.current_tasks:
            self.current_tasks.sort(key=lambda t: t.priority, reverse=True)
            return f"execute_task:{self.current_tasks[0].id}"
        return None

    def build_request(self, context: dict[str, Any]) -> tuple[LLMRequest, str]:
        """Turn a task context into a model request (and the role name).

        Raises:
            ValueError: The context is malformed. Messages are safe to return to callers.
        """
        instructions = context.get("instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            raise ValueError("instructions is required")
        if len(instructions) > MAX_INSTRUCTIONS_CHARS:
            raise ValueError("instructions are too long")

        role = context.get("role", DEFAULT_ROLE)
        if role not in PROFILES:
            raise ValueError(f"unknown role '{role}'; available: {sorted(PROFILES)}")
        profile = PROFILES[role]

        max_chars = context.get("max_input_chars", 20_000)
        if (
            not isinstance(max_chars, int)
            or isinstance(max_chars, bool)
            or not MIN_INPUT_CHARS <= max_chars <= MAX_INPUT_CHARS
        ):
            raise ValueError(
                f"max_input_chars must be an integer in [{MIN_INPUT_CHARS}, {MAX_INPUT_CHARS}]"
            )

        schema = context.get("output_schema")
        if schema is not None and not isinstance(schema, dict):
            raise ValueError("output_schema must be a JSON object")
        for key in ("goal", "title", "material", "model", "effort", "swarm_id"):
            if context.get(key) is not None and not isinstance(context[key], str):
                raise ValueError(f"{key} must be a string")

        dependencies = [
            (step_id, _role_of(result), result)
            for step_id, result in (context.get("dependency_results") or {}).items()
        ]
        prompt = prompts.compose_worker_prompt(
            goal=context.get("goal") or "(no overall goal given)",
            title=context.get("title") or "Task",
            instructions=instructions,
            material=context.get("material") or "",
            dependencies=dependencies,
            max_chars=max_chars,
        )
        request = LLMRequest(
            prompt=prompt,
            system_prompt=profile.system_prompt,
            model=context.get("model") or None,
            effort=context.get("effort") or profile.effort,
            tools=profile.tools,
            json_schema=schema,
            run_id=context.get("swarm_id") or None,
            label=f"{role}:{context.get('title') or 'task'}"[:80],
        )
        return request, role

    async def execute_task(self, task: Task) -> Any:
        """Ask the model to do the task and return its answer with usage details."""
        if task.type != "llm_task":
            raise ValueError(f"Unknown task type: {task.type}")
        if self.llm is None:
            raise LLMNotConfigured(
                "no language-model backend is configured "
                "(set UNISTAX_AGENT_API_LLM_BACKEND=claude_cli)"
            )
        request, role = self.build_request(task.context)
        logger.info("%s running llm_task (%s)", self.agent_id, request.label)

        response = await self.llm.run(request)
        self.calls_made += 1
        return {
            "status": "success",
            "role": role,
            "title": task.context.get("title"),
            "text": response.text,
            "structured": response.structured,
            "usage": response.usage.as_dict(),
            "nominal_cost_usd": response.nominal_cost_usd,
            "model": response.model,
            "num_turns": response.num_turns,
            "duration_ms": response.duration_ms,
        }

    async def _proactive_monitor(self) -> None:
        """Nothing to monitor."""

    def get_worker_stats(self) -> dict[str, Any]:
        """Base metrics plus the number of model calls made."""
        return {**self.get_metrics(), "model_calls": self.calls_made}


def _role_of(result: Any) -> str:
    if isinstance(result, dict) and isinstance(result.get("role"), str):
        return str(result["role"])
    return "worker"
