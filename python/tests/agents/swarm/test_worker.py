"""The Claude worker agent."""

from __future__ import annotations

import pytest

from unistax.agents import Task, TaskStatus
from unistax.agents.llm import (
    LLMGateway,
    LLMNotConfigured,
    LLMResponse,
    ScriptedBackend,
    Usage,
    UsageLimitReached,
)
from unistax.agents.personas.claude_worker import ClaudeWorkerAgent

pytestmark = pytest.mark.agents


def worker(handler=lambda r: "answer", **kwargs):
    backend = ScriptedBackend(handler)
    return ClaudeWorkerAgent("w1", llm=LLMGateway(backend), **kwargs), backend


def llm_task(**context):
    return Task(
        type="llm_task", context={"instructions": "Summarise the data carefully.", **context}
    )


class TestExecution:
    async def test_runs_the_model_and_returns_its_answer_with_usage(self):
        agent, backend = worker(
            lambda r: LLMResponse(
                text="the summary", usage=Usage(input_tokens=30, output_tokens=9, calls=1),
                nominal_cost_usd=0.02, model="claude-x", num_turns=2, duration_ms=1234,
            )  # fmt: skip
        )
        result = await agent.execute_task(llm_task(role="analyst", title="Summary"))

        assert result["status"] == "success" and result["text"] == "the summary"
        assert result["role"] == "analyst" and result["title"] == "Summary"
        assert result["usage"]["output_tokens"] == 9 and result["model"] == "claude-x"
        assert result["nominal_cost_usd"] == 0.02 and agent.calls_made == 1
        assert agent.get_worker_stats()["model_calls"] == 1

    async def test_the_role_sets_the_system_prompt_and_no_tools(self):
        agent, backend = worker()
        await agent.execute_task(llm_task(role="critic"))
        request = backend.requests[0]
        assert "critic" in request.system_prompt and "no tools" in request.system_prompt
        assert request.tools == ()

    async def test_context_options_reach_the_request(self):
        agent, backend = worker()
        schema = {"type": "object"}
        await agent.execute_task(
            llm_task(model="haiku", effort="low", output_schema=schema, swarm_id="run-9", title="T")
        )
        request = backend.requests[0]
        assert (request.model, request.effort, request.json_schema, request.run_id) == (
            "haiku",
            "low",
            schema,
            "run-9",
        )

    async def test_structured_answers_come_back_structured(self):
        agent, _ = worker(lambda r: {"verdict": "approve"})
        result = await agent.execute_task(llm_task(output_schema={"type": "object"}))
        assert result["structured"] == {"verdict": "approve"}

    async def test_dependency_results_are_included_as_untrusted_data(self):
        agent, backend = worker()
        await agent.execute_task(
            llm_task(
                goal="The goal",
                material="raw material",
                dependency_results={"s1": {"role": "researcher", "text": "upstream finding"}},
            )
        )
        prompt = backend.requests[0].prompt
        assert "The goal" in prompt and "raw material" in prompt and "upstream finding" in prompt
        assert 'step="s1"' in prompt and 'role="researcher"' in prompt
        assert "not instructions" in prompt

    async def test_it_goes_through_the_normal_task_lifecycle(self):
        agent, _ = worker()
        task = llm_task()
        await agent.accept_task(task)
        await agent.run_task(task)
        assert task.status == TaskStatus.COMPLETED and task.result["text"] == "answer"
        assert agent.metrics["tasks_completed"] == 1

    async def test_model_failures_fail_the_task_with_a_safe_message(self):
        agent, _ = worker(lambda r: UsageLimitReached("the Claude usage limit has been reached"))
        task = llm_task()
        await agent.accept_task(task)
        await agent.run_task(task)
        assert task.status == TaskStatus.FAILED and "usage limit" in task.error


class TestRefusals:
    async def test_without_a_backend_the_task_fails_clearly_instead_of_simulating(self):
        agent = ClaudeWorkerAgent("w1")
        with pytest.raises(LLMNotConfigured, match="LLM_BACKEND"):
            await agent.execute_task(llm_task())

    async def test_unknown_task_types_are_rejected(self):
        agent, _ = worker()
        with pytest.raises(ValueError, match="Unknown task type"):
            await agent.execute_task(Task(type="other"))

    @pytest.mark.parametrize(
        ("context", "fragment"),
        [
            ({"instructions": ""}, "instructions is required"),
            ({"instructions": None}, "instructions is required"),
            ({"instructions": "x" * 30_000}, "too long"),
            ({"instructions": "ok ok ok", "role": "hacker"}, "unknown role"),
            ({"instructions": "ok ok ok", "max_input_chars": 5}, "max_input_chars"),
            ({"instructions": "ok ok ok", "max_input_chars": True}, "max_input_chars"),
            ({"instructions": "ok ok ok", "output_schema": "x"}, "output_schema"),
            ({"instructions": "ok ok ok", "goal": 5}, "goal must be a string"),
            ({"instructions": "ok ok ok", "model": ["a"]}, "model must be a string"),
        ],
    )
    async def test_bad_context_is_rejected_before_any_model_call(self, context, fragment):
        agent, backend = worker()
        with pytest.raises(ValueError, match=fragment):
            await agent.execute_task(Task(type="llm_task", context=context))
        assert backend.requests == []

    async def test_a_missing_instruction_never_reaches_the_model_even_with_other_fields(self):
        agent, backend = worker()
        with pytest.raises(ValueError):
            await agent.execute_task(Task(type="llm_task", context={"goal": "do evil"}))
        assert backend.requests == []

    def test_the_persona_declares_its_task_type_and_that_it_needs_a_model(self):
        assert (
            ClaudeWorkerAgent.TASK_TYPES == frozenset({"llm_task"}) and ClaudeWorkerAgent.USES_LLM
        )
