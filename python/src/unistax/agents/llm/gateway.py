"""The single door through which all model calls pass.

A subscription has limits that are shared with your interactive use, so the gateway is
deliberately conservative:

* **Concurrency cap**: at most ``max_concurrency`` calls run at once; others wait.
* **Per-run budget**: each swarm run may make only so many calls, including retries.
* **Usage-limit circuit breaker**: once the limit is hit, every call fails immediately for a
  cool-down period instead of each one hitting the limit again.
* **Retry only when it can help**: overload is retried with backoff; usage limits, auth
  problems and timeouts are not.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Callable
from typing import Any

from unistax.agents.llm.types import (
    BudgetExceeded,
    LLMBackend,
    LLMOverloaded,
    LLMRequest,
    LLMResponse,
    Usage,
    UsageLimitReached,
)

logger = logging.getLogger(__name__)


class CallBudget:
    """How many model calls one run may still make."""

    def __init__(self, max_calls: int) -> None:
        """Allow ``max_calls`` calls in total."""
        self.max_calls = max_calls
        self.used = 0

    @property
    def remaining(self) -> int:
        """Calls left."""
        return self.max_calls - self.used

    def spend(self) -> None:
        """Use one call, or raise :class:`BudgetExceeded`."""
        if self.used >= self.max_calls:
            raise BudgetExceeded(f"this run used all {self.max_calls} model calls it was allowed")
        self.used += 1


class LLMGateway:
    """Rate-limited, budgeted access to an :class:`LLMBackend`."""

    def __init__(
        self,
        backend: LLMBackend,
        *,
        max_concurrency: int = 2,
        cooldown_seconds: float = 300.0,
        retries: int = 2,
        backoff_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        """Wrap ``backend``; ``clock``/``sleep`` are injectable for tests."""
        self.backend = backend
        self.max_concurrency = max(1, max_concurrency)
        self.cooldown_seconds = cooldown_seconds
        self.retries = max(0, retries)
        self.backoff_seconds = backoff_seconds
        self._clock = clock
        self._sleep = sleep
        self._slots = asyncio.Semaphore(self.max_concurrency)
        self._budgets: dict[str, CallBudget] = {}
        self._blocked_until = 0.0
        self._in_flight = 0
        self._waiting = 0
        self._calls = 0
        self._failures = 0
        self._usage = Usage()
        self._nominal_cost = 0.0
        self._last_error: str | None = None

    # -- budgets ---------------------------------------------------------------
    def open_budget(self, run_id: str, max_calls: int) -> CallBudget:
        """Start tracking calls for ``run_id``."""
        budget = self._budgets[run_id] = CallBudget(max_calls)
        return budget

    def close_budget(self, run_id: str) -> CallBudget | None:
        """Stop tracking ``run_id`` and return its final tally."""
        return self._budgets.pop(run_id, None)

    # -- state -------------------------------------------------------------------
    @property
    def paused_for(self) -> float:
        """Seconds until calls are allowed again after a usage limit (0 when running)."""
        return max(0.0, self._blocked_until - self._clock())

    def stats(self) -> dict[str, Any]:
        """Counters for monitoring (no prompts or outputs)."""
        return {
            "backend": getattr(self.backend, "name", "unknown"),
            "max_concurrency": self.max_concurrency,
            "in_flight": self._in_flight,
            "waiting": self._waiting,
            "calls": self._calls,
            "failures": self._failures,
            "paused_seconds": round(self.paused_for, 1),
            "last_error": self._last_error,
            "usage": self._usage.as_dict(),
            "nominal_cost_usd": round(self._nominal_cost, 4),
            "nominal_cost_note": "list-price equivalent; not billed on a subscription plan",
        }

    def _check_paused(self) -> None:
        remaining = self.paused_for
        if remaining > 0:
            raise UsageLimitReached(
                f"model calls are paused for another {remaining:.0f}s after the usage limit was hit"
            )

    # -- calls ---------------------------------------------------------------------
    async def run(self, request: LLMRequest) -> LLMResponse:
        """Make one call under the concurrency cap, budget and circuit breaker."""
        budget = self._budgets.get(request.run_id) if request.run_id else None
        self._check_paused()

        self._waiting += 1
        try:
            await self._slots.acquire()
        finally:
            self._waiting -= 1
        try:
            return await self._attempts(request, budget)
        finally:
            self._slots.release()

    async def _attempts(self, request: LLMRequest, budget: CallBudget | None) -> LLMResponse:
        for attempt in range(self.retries + 1):
            self._check_paused()  # a queued call may start after another tripped the breaker
            if budget is not None:
                budget.spend()
            self._in_flight += 1
            self._calls += 1
            try:
                response = await self.backend.run(request)
            except UsageLimitReached as exc:
                self._failed(exc)
                self._blocked_until = self._clock() + (exc.retry_after or self.cooldown_seconds)
                logger.warning("Claude usage limit reached; pausing model calls")
                raise
            except LLMOverloaded as exc:
                self._failed(exc)
                if attempt >= self.retries:
                    raise
                delay = self.backoff_seconds * (2**attempt) * (0.5 + random.random() / 2)
                logger.info("Model overloaded; retrying in %.1fs", delay)
                await self._sleep(delay)
                continue
            except BaseException as exc:
                self._failed(exc)
                raise
            finally:
                self._in_flight -= 1
            self._usage = self._usage + response.usage
            self._nominal_cost += response.nominal_cost_usd
            return response
        raise AssertionError("unreachable")  # pragma: no cover

    def _failed(self, exc: BaseException) -> None:
        self._failures += 1
        self._last_error = type(exc).__name__

    async def close(self) -> None:
        """Close the backend."""
        await self.backend.close()
