"""The gateway: concurrency, budgets, retries and the usage-limit circuit breaker."""

from __future__ import annotations

import asyncio

import pytest

from unistax.agents.llm import (
    BudgetExceeded,
    LLMAuthError,
    LLMGateway,
    LLMOutputError,
    LLMOverloaded,
    LLMRequest,
    LLMResponse,
    LLMTimeout,
    ScriptedBackend,
    Usage,
    UsageLimitReached,
)

pytestmark = pytest.mark.agents


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def gateway(handler, **kwargs):
    kwargs.setdefault("sleep", lambda s: asyncio.sleep(0))
    backend = ScriptedBackend(handler, delay=kwargs.pop("delay", 0.0))
    return LLMGateway(backend, **kwargs), backend


def req(i=0, run_id=None):
    return LLMRequest(prompt=f"p{i}", run_id=run_id)


class TestConcurrency:
    async def test_never_more_calls_in_flight_than_allowed(self):
        gw, backend = gateway(lambda r: "ok", max_concurrency=3, delay=0.02)
        results = await asyncio.gather(*(gw.run(req(i)) for i in range(15)))
        assert len(results) == 15 and backend.peak_active == 3

    async def test_one_at_a_time(self):
        gw, backend = gateway(lambda r: "ok", max_concurrency=1, delay=0.01)
        await asyncio.gather(*(gw.run(req(i)) for i in range(5)))
        assert backend.peak_active == 1

    async def test_a_cancelled_waiter_does_not_leak_a_slot(self):
        gw, backend = gateway(lambda r: "ok", max_concurrency=1, delay=0.2)
        first = asyncio.create_task(gw.run(req(1)))
        await asyncio.sleep(0.02)
        waiter = asyncio.create_task(gw.run(req(2)))
        await asyncio.sleep(0.02)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        await first
        assert (await asyncio.wait_for(gw.run(req(3)), 2)).text == "ok"  # the slot is free
        assert gw.stats()["waiting"] == 0 and gw.stats()["in_flight"] == 0

    async def test_a_cancelled_call_releases_its_slot(self):
        gw, _ = gateway(lambda r: "ok", max_concurrency=1, delay=5)
        running = asyncio.create_task(gw.run(req(1)))
        await asyncio.sleep(0.02)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert gw.stats()["in_flight"] == 0
        gw.backend.delay = 0
        assert (await asyncio.wait_for(gw.run(req(2)), 2)).text == "ok"


class TestBudget:
    async def test_a_run_cannot_exceed_its_call_budget(self):
        gw, backend = gateway(lambda r: "ok")
        budget = gw.open_budget("run-1", 3)
        for i in range(3):
            await gw.run(req(i, "run-1"))
        with pytest.raises(BudgetExceeded, match="all 3"):
            await gw.run(req(4, "run-1"))
        assert len(backend.requests) == 3 and budget.remaining == 0

    async def test_budgets_are_per_run(self):
        gw, _ = gateway(lambda r: "ok")
        gw.open_budget("a", 1)
        gw.open_budget("b", 1)
        await gw.run(req(1, "a"))
        await gw.run(req(2, "b"))
        with pytest.raises(BudgetExceeded):
            await gw.run(req(3, "a"))

    async def test_retries_count_against_the_budget(self):
        calls = []

        def handler(r):
            calls.append(1)
            return LLMOverloaded("busy")

        gw, backend = gateway(handler, retries=5)
        gw.open_budget("r", 3)
        with pytest.raises(BudgetExceeded):
            await gw.run(req(1, "r"))
        assert len(backend.requests) == 3  # three paid-for attempts, then stopped

    async def test_calls_without_a_run_are_unbudgeted(self):
        gw, _ = gateway(lambda r: "ok")
        for i in range(30):
            await gw.run(req(i))

    async def test_closing_a_budget_reports_what_was_used(self):
        gw, _ = gateway(lambda r: "ok")
        gw.open_budget("r", 10)
        await gw.run(req(1, "r"))
        await gw.run(req(2, "r"))
        assert gw.close_budget("r").used == 2 and gw.close_budget("r") is None


class TestUsageLimitCircuitBreaker:
    async def test_after_the_limit_is_hit_calls_fail_fast_without_reaching_the_backend(self):
        clock = Clock()
        outcomes = iter([UsageLimitReached("limit"), "fine"])
        gw, backend = gateway(lambda r: next(outcomes), clock=clock, cooldown_seconds=300)

        with pytest.raises(UsageLimitReached):
            await gw.run(req(1))
        for _ in range(5):
            with pytest.raises(UsageLimitReached, match="paused for another"):
                await gw.run(req(2))
        assert len(backend.requests) == 1  # nothing else hit the limit
        assert gw.paused_for == pytest.approx(300)

        clock.now += 301
        assert (await gw.run(req(3))).text == "fine"
        assert gw.paused_for == 0

    async def test_calls_already_waiting_are_stopped_too(self):
        outcomes = iter([UsageLimitReached("limit")] + ["ok"] * 10)
        gw, backend = gateway(lambda r: next(outcomes), max_concurrency=1, delay=0.02)

        results = await asyncio.gather(*(gw.run(req(i)) for i in range(6)), return_exceptions=True)

        assert all(isinstance(r, UsageLimitReached) for r in results)
        assert len(backend.requests) == 1  # five queued calls never started

    async def test_a_known_retry_time_overrides_the_default(self):
        clock = Clock()
        gw, _ = gateway(
            lambda r: UsageLimitReached("limit", retry_after=42), clock=clock, cooldown_seconds=900
        )
        with pytest.raises(UsageLimitReached):
            await gw.run(req(1))
        assert gw.paused_for == pytest.approx(42)

    async def test_other_errors_do_not_trip_the_breaker(self):
        gw, backend = gateway(lambda r: LLMAuthError("no login"))
        for _ in range(3):
            with pytest.raises(LLMAuthError):
                await gw.run(req(1))
        assert len(backend.requests) == 3 and gw.paused_for == 0


class TestRetries:
    async def test_overload_is_retried_with_growing_backoff(self):
        delays = []

        async def record_sleep(seconds):
            delays.append(seconds)

        outcomes = iter([LLMOverloaded("busy"), LLMOverloaded("busy"), "recovered"])
        gw, backend = gateway(
            lambda r: next(outcomes), retries=3, backoff_seconds=1.0, sleep=record_sleep
        )

        assert (await gw.run(req(1))).text == "recovered"
        assert len(backend.requests) == 3 and len(delays) == 2
        assert 0.5 <= delays[0] <= 1.0 and 1.0 <= delays[1] <= 2.0

    async def test_retries_run_out(self):
        gw, backend = gateway(lambda r: LLMOverloaded("busy"), retries=2)
        with pytest.raises(LLMOverloaded):
            await gw.run(req(1))
        assert len(backend.requests) == 3  # the first attempt plus two retries

    @pytest.mark.parametrize(
        "error", [LLMTimeout("slow"), LLMAuthError("login"), LLMOutputError("bad")]
    )
    async def test_other_errors_are_not_retried(self, error):
        gw, backend = gateway(lambda r: error, retries=5)
        with pytest.raises(type(error)):
            await gw.run(req(1))
        assert len(backend.requests) == 1


class TestStats:
    async def test_counters_and_totals(self):
        outcomes = iter(["a", LLMTimeout("t"), "b"])
        gw, _ = gateway(lambda r: next(outcomes))
        await gw.run(req(1))
        with pytest.raises(LLMTimeout):
            await gw.run(req(2))
        await gw.run(req(3))

        stats = gw.stats()
        assert (stats["calls"], stats["failures"], stats["last_error"]) == (3, 1, "LLMTimeout")
        assert stats["usage"]["calls"] == 2 and stats["usage"]["input_tokens"] == 20
        assert stats["in_flight"] == 0 and stats["backend"] == "scripted"

    async def test_nominal_cost_is_labelled_as_not_billed(self):
        gw, _ = gateway(lambda r: LLMResponse(text="x", nominal_cost_usd=0.5, usage=Usage(calls=1)))
        await gw.run(req(1))
        stats = gw.stats()
        assert stats["nominal_cost_usd"] == 0.5 and "not billed" in stats["nominal_cost_note"]

    async def test_stats_contain_no_prompts_or_outputs(self):
        gw, _ = gateway(lambda r: "the-model-said-this")
        await gw.run(LLMRequest(prompt="sensitive-prompt-text"))
        dumped = str(gw.stats())
        assert "sensitive-prompt-text" not in dumped and "the-model-said-this" not in dumped
