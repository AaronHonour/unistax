"""The scripted backend used by tests and offline development."""

from __future__ import annotations

import asyncio
import time

import pytest

from unistax.agents.llm import LLMRequest, LLMResponse, ScriptedBackend, Usage

pytestmark = pytest.mark.agents


async def test_returns_text_dicts_and_full_responses():
    texts = iter(
        ["plain", {"a": 1}, LLMResponse(text="full", usage=Usage(calls=1, input_tokens=3))]
    )
    backend = ScriptedBackend(lambda r: next(texts))

    assert (await backend.run(LLMRequest(prompt="x"))).text == "plain"
    structured = await backend.run(LLMRequest(prompt="x"))
    assert structured.structured == {"a": 1} and structured.text == '{"a": 1}'
    assert (await backend.run(LLMRequest(prompt="x"))).usage.input_tokens == 3
    assert len(backend.requests) == 3


async def test_exceptions_are_raised():
    backend = ScriptedBackend(lambda r: ValueError("boom"))
    with pytest.raises(ValueError, match="boom"):
        await backend.run(LLMRequest(prompt="x"))
    assert backend.active == 0


async def test_handlers_may_be_coroutines():
    async def handler(request):
        await asyncio.sleep(0.01)
        return f"async:{request.prompt}"

    assert (await ScriptedBackend(handler).run(LLMRequest(prompt="q"))).text == "async:q"


async def test_delay_can_depend_on_the_request():
    backend = ScriptedBackend(lambda r: "ok", delay=lambda r: 0.3 if r.label == "slow" else 0.0)
    started = time.monotonic()
    await backend.run(LLMRequest(prompt="x", label="fast"))
    assert time.monotonic() - started < 0.2
    started = time.monotonic()
    await backend.run(LLMRequest(prompt="x", label="slow"))
    assert time.monotonic() - started >= 0.28


async def test_it_tracks_how_many_calls_overlap():
    backend = ScriptedBackend(lambda r: "ok", delay=0.05)
    await asyncio.gather(*(backend.run(LLMRequest(prompt="x")) for _ in range(4)))
    assert backend.peak_active == 4 and backend.active == 0
