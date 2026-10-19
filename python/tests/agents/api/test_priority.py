"""Priority-aware admission of queued work."""

from __future__ import annotations

import asyncio
import threading

import pytest

from unistax.agents import DataEngineerAgent
from unistax.agents.api.services.priority_gate import PriorityGate

from .conftest import API, create_agent, submit_task, task_state, wait_for, wait_task

pytestmark = pytest.mark.api


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


class TestPriorityGate:
    async def test_admits_up_to_capacity_without_waiting(self):
        gate = PriorityGate(2)
        await gate.acquire()
        await gate.acquire()
        assert gate.in_use == 2 and gate.waiting == 0

    async def test_waiters_are_admitted_by_priority(self):
        gate = PriorityGate(1, aging_seconds=0)
        await gate.acquire()
        order: list[str] = []

        async def worker(name: str, priority: int) -> None:
            async with gate.slot(priority):
                order.append(name)

        tasks = [
            asyncio.create_task(worker("low", 1)),
            asyncio.create_task(worker("high", 9)),
            asyncio.create_task(worker("mid", 5)),
        ]
        await settle()
        assert gate.waiting == 3
        gate.release()
        await asyncio.gather(*tasks)

        assert order == ["high", "mid", "low"]

    async def test_equal_priorities_are_first_come_first_served(self):
        gate = PriorityGate(1, aging_seconds=0)
        await gate.acquire()
        order: list[int] = []

        async def worker(n: int) -> None:
            async with gate.slot(5):
                order.append(n)

        tasks = []
        for n in range(5):
            tasks.append(asyncio.create_task(worker(n)))
            await settle()
        gate.release()
        await asyncio.gather(*tasks)

        assert order == [0, 1, 2, 3, 4]

    async def test_aging_lets_old_low_priority_work_overtake(self):
        gate = PriorityGate(1, aging_seconds=0.05)
        await gate.acquire()
        order: list[str] = []

        async def worker(name: str, priority: int) -> None:
            async with gate.slot(priority):
                order.append(name)

        old_low = asyncio.create_task(worker("old-low", 1))
        await settle()
        await asyncio.sleep(0.6)  # ages by ~12 priority points
        new_high = asyncio.create_task(worker("new-high", 9))
        await settle()
        gate.release()
        await asyncio.gather(old_low, new_high)

        assert order == ["old-low", "new-high"]

    async def test_strict_priority_never_ages(self):
        gate = PriorityGate(1, aging_seconds=0)
        await gate.acquire()
        order: list[str] = []

        async def worker(name: str, priority: int) -> None:
            async with gate.slot(priority):
                order.append(name)

        old_low = asyncio.create_task(worker("old-low", 1))
        await settle()
        await asyncio.sleep(0.2)
        new_high = asyncio.create_task(worker("new-high", 9))
        await settle()
        gate.release()
        await asyncio.gather(old_low, new_high)

        assert order == ["new-high", "old-low"]

    async def test_cancelled_waiter_leaves_the_queue(self):
        gate = PriorityGate(1)
        await gate.acquire()
        waiter = asyncio.create_task(gate.acquire(5))
        await settle()
        assert gate.waiting == 1

        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

        assert gate.waiting == 0
        gate.release()
        assert gate.in_use == 0

    async def test_slot_granted_to_a_cancelled_waiter_is_passed_on(self):
        gate = PriorityGate(1)
        await gate.acquire()
        first = asyncio.create_task(gate.acquire(9))
        second_done = asyncio.Event()

        async def second() -> None:
            async with gate.slot(1):
                second_done.set()

        second_task = asyncio.create_task(second())
        await settle()

        gate.release()  # admits `first` (future resolved, task not yet resumed)
        first.cancel()  # ...and it is cancelled before it can run
        with pytest.raises(asyncio.CancelledError):
            await first

        await asyncio.wait_for(second_done.wait(), 2)  # the slot was not lost
        await second_task
        assert gate.in_use == 0

    async def test_resize_up_admits_waiters_and_down_applies_lazily(self):
        gate = PriorityGate(1)
        await gate.acquire()
        waiter = asyncio.create_task(gate.acquire())
        await settle()

        gate.resize(2)
        await asyncio.wait_for(waiter, 2)
        assert gate.in_use == 2

        gate.resize(1)  # nobody is evicted
        assert gate.in_use == 2
        gate.release()
        late = asyncio.create_task(gate.acquire())
        await settle()
        assert not late.done()  # still at the new limit of 1
        gate.release()
        await asyncio.wait_for(late, 2)

    async def test_capacity_never_exceeded_under_contention(self):
        gate = PriorityGate(3, aging_seconds=0)
        running = peak = 0

        async def worker(priority: int) -> None:
            nonlocal running, peak
            async with gate.slot(priority):
                running += 1
                peak = max(peak, running)
                await asyncio.sleep(0.005)
                running -= 1

        await asyncio.gather(*(worker(i % 10 + 1) for i in range(60)))
        assert peak == 3 and gate.in_use == 0 and gate.waiting == 0


class TestPriorityThroughTheAPI:
    def test_higher_priority_tasks_run_first(self, client, admin, monkeypatch):
        started = threading.Event()
        release = threading.Event()
        ran: list[str] = []

        async def controlled(self, context):
            ran.append(context["label"])
            if context["label"] == "blocker":
                started.set()
                while not release.is_set():
                    await asyncio.sleep(0.01)
            return {"status": "success"}

        monkeypatch.setattr(DataEngineerAgent, "_run_quality_check", controlled)
        create_agent(client, admin, max_concurrent_tasks=1)

        def submit(label: str, priority: int) -> str:
            body = {"task_type": "quality_check", "priority": priority, "context": {"label": label}}
            response = client.post(f"{API}/tasks", json=body, headers=admin)
            assert response.status_code == 202, response.text
            return response.json()["data"]["task_id"]

        blocker = submit("blocker", 5)
        assert started.wait(5)
        ids = [submit("low", 1), submit("mid", 5), submit("high", 10)]

        release.set()
        for task_id in [blocker, *ids]:
            assert wait_task(client, admin, task_id)["status"] == "completed"

        assert ran == ["blocker", "high", "mid", "low"]

    def test_cancelling_a_queued_task_frees_its_place(self, client, admin, monkeypatch):
        release = threading.Event()
        started = threading.Event()

        async def controlled(self, context):
            if context["label"] == "blocker":
                started.set()
                while not release.is_set():
                    await asyncio.sleep(0.01)
            return {"status": "success"}

        monkeypatch.setattr(DataEngineerAgent, "_run_quality_check", controlled)
        create_agent(client, admin, max_concurrent_tasks=1)

        def submit(label: str) -> str:
            body = {"task_type": "quality_check", "context": {"label": label}}
            return client.post(f"{API}/tasks", json=body, headers=admin).json()["data"]["task_id"]

        submit("blocker")
        assert started.wait(5)
        queued = submit("queued")
        survivor = submit("survivor")

        assert client.post(f"{API}/tasks/{queued}/cancel", headers=admin).status_code == 200
        release.set()

        assert wait_task(client, admin, survivor)["status"] == "completed"
        assert task_state(client, admin, queued)["status"] == "cancelled"

    def test_raising_an_agents_limit_takes_effect_for_queued_work(self, client, admin, monkeypatch):
        release = threading.Event()
        running = threading.Semaphore(0)

        async def controlled(self, context):
            running.release()
            while not release.is_set():
                await asyncio.sleep(0.01)
            return {"status": "success"}

        monkeypatch.setattr(DataEngineerAgent, "_run_quality_check", controlled)
        create_agent(client, admin, max_concurrent_tasks=1)
        ids = [submit_task(client, admin)["task_id"] for _ in range(3)]

        assert running.acquire(timeout=5)
        assert not running.acquire(timeout=0.3)  # only one at a time so far

        patched = client.patch(
            f"{API}/agents/eng_1", json={"max_concurrent_tasks": 3}, headers=admin
        )
        assert patched.status_code == 200
        assert running.acquire(timeout=5) and running.acquire(timeout=5)  # the queued ones start

        release.set()
        for task_id in ids:
            wait_task(client, admin, task_id)


class TestBoundedHistory:
    def test_agent_history_is_capped_but_counters_are_exact(self):
        agent = DataEngineerAgent("eng", max_history=3)

        async def run_many() -> None:
            from unistax.agents import Task

            for _ in range(10):
                task = Task(type="quality_check", context={"table": "t"})
                await agent.accept_task(task)
                await agent.run_task(task)

        asyncio.run(run_many())

        assert len(agent.task_history) == 3
        assert agent.metrics["tasks_completed"] == 10

    def test_history_limit_is_at_least_one(self):
        assert DataEngineerAgent("eng", max_history=0).task_history.maxlen == 1


def test_settings_reject_negative_aging():
    from unistax.agents.api import AgentAPISettings

    with pytest.raises(ValueError, match="aging"):
        AgentAPISettings(jwt_secret="x" * 40, priority_aging_seconds=-1).validate()


def test_idle_gates_are_dropped_with_their_agent(client, admin):
    runtime = client.app.state.runtime
    create_agent(client, admin)
    wait_task(client, admin, submit_task(client, admin)["task_id"])
    wait_for(lambda: {"n": len(runtime.executor._slots)}, lambda v: v["n"] == 1)

    assert client.delete(f"{API}/agents/eng_1", headers=admin).status_code == 204
    assert runtime.executor._slots == {}
