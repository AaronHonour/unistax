"""A concurrency limiter that admits waiting work by priority instead of arrival order."""

from __future__ import annotations

import asyncio
import itertools
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field


@dataclass(eq=False)
class _Waiter:
    priority: int
    queued_at: float
    sequence: int
    future: asyncio.Future[None] = field(repr=False)


class PriorityGate:
    """Allows up to ``capacity`` holders at once; waiters are admitted best-first.

    The next waiter is the one with the highest *effective* priority:
    ``priority + waited_seconds / aging_seconds``. Aging means a low-priority
    waiter eventually overtakes fresh high-priority arrivals, so a steady stream
    of urgent work cannot starve it indefinitely. Ties are broken by arrival order.
    Set ``aging_seconds`` to 0 for strict priority.
    """

    def __init__(self, capacity: int, aging_seconds: float = 30.0) -> None:
        self._capacity = max(1, capacity)
        self._aging = aging_seconds
        self._in_use = 0
        self._waiters: list[_Waiter] = []
        self._sequence = itertools.count()

    @property
    def in_use(self) -> int:
        return self._in_use

    @property
    def waiting(self) -> int:
        return len(self._waiters)

    def resize(self, capacity: int) -> None:
        """Change the limit. Holders are never evicted; a smaller limit applies as they leave."""
        self._capacity = max(1, capacity)
        self._dispatch()

    async def acquire(self, priority: int = 5) -> None:
        if self._in_use < self._capacity and not self._waiters:
            self._in_use += 1
            return

        waiter = _Waiter(
            priority=priority,
            queued_at=time.monotonic(),
            sequence=next(self._sequence),
            future=asyncio.get_running_loop().create_future(),
        )
        self._waiters.append(waiter)
        try:
            await waiter.future
        except asyncio.CancelledError:
            if waiter.future.done() and not waiter.future.cancelled():
                # Admitted at the moment we were cancelled: hand the slot on.
                self._in_use -= 1
                self._dispatch()
            elif waiter in self._waiters:
                self._waiters.remove(waiter)
            raise

    def release(self) -> None:
        self._in_use -= 1
        self._dispatch()

    @asynccontextmanager
    async def slot(self, priority: int = 5) -> AsyncIterator[None]:
        await self.acquire(priority)
        try:
            yield
        finally:
            self.release()

    def _score(self, waiter: _Waiter, now: float) -> tuple[float, int]:
        age = (now - waiter.queued_at) / self._aging if self._aging > 0 else 0.0
        return (waiter.priority + age, -waiter.sequence)

    def _dispatch(self) -> None:
        now = time.monotonic()
        while self._in_use < self._capacity and self._waiters:
            best = max(self._waiters, key=lambda w: self._score(w, now))
            self._waiters.remove(best)
            if best.future.done():
                continue
            self._in_use += 1
            best.future.set_result(None)
