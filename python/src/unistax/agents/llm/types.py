"""Types shared by LLM backends: requests, responses and errors.

Error messages are safe to show to API callers: they never contain prompts, model output,
environment variables or credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(Exception):
    """A language-model call failed."""

    retryable = False


class LLMNotConfigured(LLMError):
    """No language-model backend is configured for this service."""


class BackendUnavailable(LLMError):
    """The backend cannot run at all (missing executable, unsupported version, ...)."""


class LLMAuthError(LLMError):
    """The backend is not signed in (or its credentials were rejected)."""


class UsageLimitReached(LLMError):
    """The account's usage or rate limit is exhausted; retrying now will not help."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        """Create the error; ``retry_after`` is seconds until the limit resets, if known."""
        super().__init__(message)
        self.retry_after = retry_after


class LLMOverloaded(LLMError):
    """The service is temporarily overloaded; a short retry is reasonable."""

    retryable = True


class LLMTimeout(LLMError):
    """The call exceeded its time limit and was killed."""

    retryable = True


class LLMOutputError(LLMError):
    """The backend returned something that could not be understood."""


class BudgetExceeded(LLMError):
    """A run used all the model calls it was allowed."""


@dataclass(frozen=True)
class Usage:
    """Token counts for one or more calls."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    calls: int = 0

    def __add__(self, other: Usage) -> Usage:
        """Sum two usages."""
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_creation_tokens + other.cache_creation_tokens,
            self.calls + other.calls,
        )

    def as_dict(self) -> dict[str, int]:
        """JSON-friendly form."""
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
        }


@dataclass(frozen=True)
class LLMRequest:
    """One model call.

    ``prompt`` carries all data and goes to the model out-of-band (never on a command
    line). ``system_prompt`` is for fixed instructions only.
    """

    prompt: str
    system_prompt: str | None = None
    model: str | None = None
    effort: str | None = None
    tools: tuple[str, ...] = ()
    json_schema: dict[str, Any] | None = None
    timeout: float | None = None
    run_id: str | None = None
    label: str = ""


@dataclass(frozen=True)
class LLMResponse:
    """What came back from one call."""

    text: str
    structured: Any | None = None
    usage: Usage = field(default_factory=lambda: Usage(calls=1))
    nominal_cost_usd: float = 0.0
    num_turns: int = 1
    duration_ms: int = 0
    model: str | None = None
    session_id: str | None = None


class LLMBackend(Protocol):
    """Anything that can answer a request."""

    name: str

    async def run(self, request: LLMRequest) -> LLMResponse:
        """Answer ``request`` or raise an :class:`LLMError`."""
        ...

    async def close(self) -> None:
        """Release resources."""
        ...
