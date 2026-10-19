"""Regression tests for agent lifecycle, registry and orchestrator behaviour."""

from __future__ import annotations

import asyncio

import pytest

from unistax.agents import (
    AgentOrchestrator,
    AgentRegistry,
    AgentState,
    DataAnalystAgent,
    DataEngineerAgent,
    Skill,
    StepStatus,
    Task,
    TaskStatus,
    TeamType,
    Workflow,
    WorkflowStatus,
    WorkflowStep,
)
from unistax.logging import get_logger
from unistax.logging.context import log_context
from unistax.metrics import MetricsManager

pytestmark = pytest.mark.agents


class TestRunTask:
    async def test_real_metrics_manager_does_not_break_tasks(self):
        metrics = MetricsManager()
        agent = DataEngineerAgent("eng", metrics_manager=metrics)
        task = Task(type="quality_check", context={"table": "t"})

        await agent.accept_task(task)
        await agent.run_task(task)

        assert task.status == TaskStatus.COMPLETED and task.error is None
        recorded = metrics.get_metrics()
        assert recorded["counters"]  # something was counted

    async def test_broken_metrics_backend_never_fails_a_task(self):
        class Broken:
            def counter(self, *a, **k):
                raise RuntimeError("metrics down")

            histogram = counter

        agent = DataEngineerAgent("eng", metrics_manager=Broken())
        task = Task(type="quality_check", context={"table": "t"})
        await agent.accept_task(task)
        await agent.run_task(task)
        assert task.status == TaskStatus.COMPLETED

    async def test_agent_returns_to_idle_and_publishes_it(self):
        agent = DataEngineerAgent("eng")
        seen = []

        from unistax.agents import AgentStateChangeEvent

        @agent.event_bus.subscribe(AgentStateChangeEvent)
        async def record(event):
            seen.append((event.old_state, event.new_state))

        task = Task(type="quality_check", context={"table": "t"})
        await agent.accept_task(task)
        await agent.run_task(task)

        assert agent.state == AgentState.IDLE
        assert seen == [("idle", "working"), ("working", "idle")]

    async def test_failed_task_is_recorded_and_agent_recovers(self):
        agent = DataEngineerAgent("eng")
        task = Task(type="not_a_real_task")
        await agent.accept_task(task)
        await agent.run_task(task)

        assert task.status == TaskStatus.FAILED and "Unknown task type" in task.error
        assert agent.state == AgentState.IDLE and agent.current_tasks == []
        assert agent.metrics["tasks_failed"] == 1

    async def test_release_task_frees_the_slot(self):
        agent = DataEngineerAgent("eng")
        task = Task(type="quality_check")
        await agent.accept_task(task)
        agent.state = AgentState.WORKING

        agent.release_task(task)

        assert task.status == TaskStatus.CANCELLED and task.completed_at is not None
        assert agent.current_tasks == [] and agent.state == AgentState.IDLE

    def test_can_do_can_ignore_capacity(self):
        agent = DataEngineerAgent("eng", max_concurrent_tasks=1)
        agent.current_tasks.append(Task(type="busy"))
        task = Task(type="quality_check", required_skills={"sql": 0.5})
        assert agent.can_do(task)[0] is False
        assert agent.can_do(task, check_capacity=False)[0] is True

    def test_personas_declare_their_task_types(self):
        assert "build_pipeline" in DataEngineerAgent.TASK_TYPES
        assert "analyze_data" in DataAnalystAgent.TASK_TYPES
        assert not DataEngineerAgent.TASK_TYPES & DataAnalystAgent.TASK_TYPES


class TestEventSubscriptions:
    async def test_unsubscribed_agents_stop_receiving_messages(self):
        registry = AgentRegistry()
        sender = DataEngineerAgent("a", event_bus=registry.event_bus)
        receiver = DataAnalystAgent("b", event_bus=registry.event_bus)
        registry.register(sender)
        registry.register(receiver)

        await sender.send_message("b", "notification", {"n": 1})
        assert receiver.inbox.qsize() == 1

        registry.unregister("b")
        await sender.send_message("b", "notification", {"n": 2})
        assert receiver.inbox.qsize() == 1  # nothing delivered after removal

    def test_unsubscribe_is_idempotent(self):
        agent = DataEngineerAgent("a")
        agent.unsubscribe_from_events()
        agent.unsubscribe_from_events()


class TestRegistry:
    def test_unregister_clears_team_membership(self):
        registry = AgentRegistry()
        team = registry.create_team("T", TeamType.FUNCTIONAL)
        agent = DataEngineerAgent("a", team_id=team.id, event_bus=registry.event_bus)
        registry.register(agent)
        assert "a" in team.members

        registry.unregister("a")

        assert "a" not in team.members
        assert registry.team_hierarchy.get_agent_team("a") is None
        assert registry.find_by_team(team.id) == []

    def test_update_agent_reindexes(self):
        registry = AgentRegistry()
        t1 = registry.create_team("one")
        t2 = registry.create_team("two")
        agent = DataEngineerAgent("a", team_id=t1.id, event_bus=registry.event_bus)
        registry.register(agent)

        registry.update_agent(
            "a", team_id=t2.id, set_team=True, skills=[Skill("rust", 0.9, "lang")]
        )

        assert [x.agent_id for x in registry.find_by_team(t2.id)] == ["a"]
        assert registry.find_by_team(t1.id) == []
        assert [x.agent_id for x in registry.find_by_skill("rust")] == ["a"]
        assert registry.find_by_skill("sql") == []
        assert "a" in t2.members and "a" not in t1.members

    def test_team_move_rejects_cycles(self):
        registry = AgentRegistry()
        a = registry.create_team("a")
        b = registry.create_team("b", parent_id=a.id)
        c = registry.create_team("c", parent_id=b.id)

        with pytest.raises(ValueError):
            registry.update_team(a.id, parent_id=c.id, reparent=True)
        with pytest.raises(ValueError):
            registry.update_team(a.id, parent_id=a.id, reparent=True)
        with pytest.raises(KeyError):
            registry.update_team(a.id, parent_id="ghost", reparent=True)

        registry.update_team(c.id, parent_id=a.id, reparent=True)
        assert c.id in a.child_teams and c.id not in b.child_teams and c.parent_team_id == a.id

    def test_remove_team_rules(self):
        registry = AgentRegistry()
        parent = registry.create_team("p")
        child = registry.create_team("c", parent_id=parent.id)
        with pytest.raises(ValueError):
            registry.remove_team(parent.id)
        assert registry.remove_team(child.id) is True
        assert parent.child_teams == set()
        assert registry.remove_team(child.id) is False


def make_workflow(*steps: WorkflowStep) -> Workflow:
    return Workflow(name="wf", steps=list(steps))


def step(step_id, task_type="quality_check", persona="data_engineer", deps=(), retries=1):
    return WorkflowStep(
        id=step_id,
        name=step_id,
        task=Task(id=f"t-{step_id}", type=task_type, context={"table": "t"}),
        agent_persona=persona,
        dependencies=list(deps),
        max_retries=retries,
    )


class TestOrchestrator:
    async def test_runs_dependencies_in_order(self):
        registry = AgentRegistry()
        registry.register(DataEngineerAgent("eng", event_bus=registry.event_bus))
        workflow = make_workflow(step("a"), step("b", deps=["a"]))

        result = await AgentOrchestrator(registry).execute_workflow(workflow)

        assert result["status"] == "completed" and result["steps_completed"] == 2
        assert workflow.get_step("a").completed_at <= workflow.get_step("b").started_at

    async def test_failed_dependency_skips_dependents_instead_of_hanging(self):
        registry = AgentRegistry()
        registry.register(DataEngineerAgent("eng", event_bus=registry.event_bus))
        workflow = make_workflow(
            step("bad", task_type="nonexistent"),
            step("after", deps=["bad"]),
            step("after2", deps=["after"]),
            step("free"),
        )

        result = await asyncio.wait_for(
            AgentOrchestrator(registry).execute_workflow(workflow), timeout=10
        )

        states = {s.id: s.status for s in workflow.steps}
        assert states == {
            "bad": StepStatus.FAILED,
            "after": StepStatus.SKIPPED,
            "after2": StepStatus.SKIPPED,
            "free": StepStatus.COMPLETED,
        }
        assert result["status"] == "failed"

    async def test_cancellation_stops_running_steps(self, monkeypatch):
        started = asyncio.Event()
        finished = []

        async def hang(self, context):
            started.set()
            try:
                await asyncio.sleep(30)
            finally:
                finished.append("cancelled")

        monkeypatch.setattr(DataEngineerAgent, "_run_quality_check", hang)
        registry = AgentRegistry()
        agent = DataEngineerAgent("eng", event_bus=registry.event_bus)
        registry.register(agent)

        job = asyncio.create_task(
            AgentOrchestrator(registry).execute_workflow(make_workflow(step("a")))
        )
        await asyncio.wait_for(started.wait(), 5)
        job.cancel()
        with pytest.raises(asyncio.CancelledError):
            await job
        await asyncio.sleep(0)

        assert finished == ["cancelled"]  # the step coroutine was cancelled, not orphaned

    async def test_retry_does_not_start_the_step_twice(self, monkeypatch):
        calls = []

        async def flaky(self, context):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("transient")
            await asyncio.sleep(0.05)
            return {"status": "success"}

        monkeypatch.setattr(DataEngineerAgent, "_run_quality_check", flaky)
        monkeypatch.setattr("unistax.agents.orchestrator.asyncio.sleep", _fast_sleep, raising=False)
        registry = AgentRegistry()
        registry.register(DataEngineerAgent("eng", event_bus=registry.event_bus))
        workflow = make_workflow(step("a", retries=3))

        result = await AgentOrchestrator(registry).execute_workflow(workflow)

        assert result["status"] == "completed"
        assert len(calls) == 2  # one failure + exactly one retry

    async def test_workflow_events_and_status(self):
        registry = AgentRegistry()
        registry.register(DataEngineerAgent("eng", event_bus=registry.event_bus))
        orchestrator = AgentOrchestrator(registry)
        workflow = make_workflow(step("a"))
        await orchestrator.execute_workflow(workflow)
        assert workflow.status == WorkflowStatus.COMPLETED
        assert orchestrator.get_workflow_status(workflow.id)["progress"] == 1.0


_real_sleep = asyncio.sleep


async def _fast_sleep(delay, *args, **kwargs):
    await _real_sleep(min(delay, 0.01), *args, **kwargs)


class TestLoggingContext:
    def test_logging_works_without_a_log_context(self):
        token = log_context.set(None)
        try:
            get_logger("tests.core").info("no context set")  # used to raise TypeError
        finally:
            log_context.reset(token)


class TestOrchestratorDependenciesAndCapacity:
    async def test_steps_receive_the_results_of_their_dependencies(self):
        seen: dict[str, dict] = {}

        class Recorder(DataEngineerAgent):
            async def _run_quality_check(self, context):
                seen[context.get("name", "?")] = context.get("dependency_results")
                return {"status": "success", "name": context.get("name")}

        registry = AgentRegistry()
        registry.register(Recorder("eng", event_bus=registry.event_bus))

        def named(step_id, deps=()):
            s = step(step_id, deps=deps)
            s.task.context["name"] = step_id
            return s

        workflow = make_workflow(named("a"), named("b"), named("c", deps=["a", "b"]))
        await AgentOrchestrator(registry).execute_workflow(workflow)

        assert seen["a"] is None and seen["b"] is None  # no dependencies, nothing injected
        assert set(seen["c"]) == {"a", "b"}
        assert seen["c"]["a"]["name"] == "a" and seen["c"]["b"]["status"] == "success"

    async def test_only_completed_dependencies_are_passed_on(self):
        seen = {}

        class Recorder(DataEngineerAgent):
            async def _run_quality_check(self, context):
                seen[context["name"]] = context.get("dependency_results")
                return {"status": "success"}

        registry = AgentRegistry()
        registry.register(Recorder("eng", event_bus=registry.event_bus))
        workflow = make_workflow(step("a"), step("b", deps=["a"]))
        for s in workflow.steps:
            s.task.context["name"] = s.id
        await AgentOrchestrator(registry).execute_workflow(workflow)
        assert list(seen["b"]) == ["a"]

    async def test_a_retried_step_gets_fresh_dependency_results_not_stale_ones(self):
        attempts = []

        class Flaky(DataEngineerAgent):
            async def _run_quality_check(self, context):
                if context.get("name") == "b":
                    attempts.append(dict(context.get("dependency_results") or {}))
                    if len(attempts) == 1:
                        raise RuntimeError("transient")
                return {"status": "success", "name": context.get("name")}

        registry = AgentRegistry()
        registry.register(Flaky("eng", event_bus=registry.event_bus))
        a, b = step("a"), step("b", deps=["a"], retries=3)
        a.task.context["name"], b.task.context["name"] = "a", "b"
        await AgentOrchestrator(registry).execute_workflow(make_workflow(a, b))
        assert len(attempts) == 2 and attempts[0] == attempts[1] and list(attempts[1]) == ["a"]

    async def test_steps_wait_for_a_busy_agent_instead_of_failing(self):
        running = peak = 0

        class Slow(DataEngineerAgent):
            async def _run_quality_check(self, context):
                nonlocal running, peak
                running += 1
                peak = max(peak, running)
                await asyncio.sleep(0.05)
                running -= 1
                return {"status": "success"}

        registry = AgentRegistry()
        registry.register(Slow("eng", event_bus=registry.event_bus, max_concurrent_tasks=2))
        workflow = make_workflow(*[step(f"s{i}") for i in range(6)])

        result = await AgentOrchestrator(registry).execute_workflow(
            workflow, max_concurrent_steps=6
        )

        assert result["status"] == "completed" and result["steps_completed"] == 6
        assert peak == 2  # never more than the agent's capacity at once

    async def test_a_step_with_no_suitable_agent_still_fails_immediately(self):
        registry = AgentRegistry()
        started = asyncio.get_running_loop().time()
        result = await AgentOrchestrator(registry, capacity_wait_seconds=30).execute_workflow(
            make_workflow(step("a"))
        )
        assert result["status"] == "failed"
        assert asyncio.get_running_loop().time() - started < 5

    async def test_waiting_for_capacity_gives_up_after_the_limit(self):
        class Stuck(DataEngineerAgent):
            async def _run_quality_check(self, context):
                await asyncio.sleep(5)

        registry = AgentRegistry()
        registry.register(Stuck("eng", event_bus=registry.event_bus, max_concurrent_tasks=1))
        workflow = make_workflow(step("a"), step("b"))
        orchestrator = AgentOrchestrator(registry, capacity_wait_seconds=0.3)

        job = asyncio.create_task(orchestrator.execute_workflow(workflow, max_concurrent_steps=2))
        await asyncio.sleep(1.0)
        states = {s.id: s.status for s in workflow.steps}
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)

        assert StepStatus.FAILED in states.values()  # the one that could not get a slot
        failed = next(s for s in workflow.steps if s.status == StepStatus.FAILED)
        assert "became free" in failed.error
