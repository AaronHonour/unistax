"""A backend that returns scripted answers: for tests and offline development."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from unistax.agents.llm.types import LLMRequest, LLMResponse, Usage

Outcome = str | dict[str, Any] | LLMResponse | Exception
Handler = Callable[[LLMRequest], Outcome | Awaitable[Outcome]]
Delay = float | Callable[[LLMRequest], float]


class ScriptedBackend:
    """Answers each request by calling ``handler(request)``.

    The handler may return text, a dict (returned as structured output and as JSON text),
    a full :class:`LLMResponse`, or an exception instance (raised). It may be a coroutine
    function, which lets a test hold one request open while others proceed.
    """

    name = "scripted"

    def __init__(self, handler: Handler, delay: Delay = 0.0) -> None:
        """Create the backend; ``delay`` simulates latency (seconds, or per-request)."""
        self.handler = handler
        self.delay = delay
        self.requests: list[LLMRequest] = []
        self.active = 0
        self.peak_active = 0

    async def run(self, request: LLMRequest) -> LLMResponse:
        """Record the request, wait ``delay``, and answer from the handler."""
        self.requests.append(request)
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        try:
            pause = self.delay(request) if callable(self.delay) else self.delay
            if pause:
                await asyncio.sleep(pause)
            outcome = self.handler(request)
            if inspect.isawaitable(outcome):
                outcome = await outcome
        finally:
            self.active -= 1
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, LLMResponse):
            return outcome
        usage = Usage(input_tokens=10, output_tokens=5, calls=1)
        if isinstance(outcome, dict):
            import json

            return LLMResponse(text=json.dumps(outcome), structured=outcome, usage=usage)
        return LLMResponse(text=str(outcome), usage=usage)

    async def close(self) -> None:
        """Nothing to release."""
