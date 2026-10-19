"""Language-model access for agents: a backend, and a gateway that keeps usage in check."""

from unistax.agents.llm.gateway import CallBudget, LLMGateway
from unistax.agents.llm.profiles import PLANNER, PROFILES, Profile
from unistax.agents.llm.scripted import ScriptedBackend
from unistax.agents.llm.types import (
    BackendUnavailable,
    BudgetExceeded,
    LLMAuthError,
    LLMBackend,
    LLMError,
    LLMNotConfigured,
    LLMOutputError,
    LLMOverloaded,
    LLMRequest,
    LLMResponse,
    LLMTimeout,
    Usage,
    UsageLimitReached,
)

__all__ = [
    "PLANNER",
    "PROFILES",
    "BackendUnavailable",
    "BudgetExceeded",
    "CallBudget",
    "LLMAuthError",
    "LLMBackend",
    "LLMError",
    "LLMGateway",
    "LLMNotConfigured",
    "LLMOutputError",
    "LLMOverloaded",
    "LLMRequest",
    "LLMResponse",
    "LLMTimeout",
    "Profile",
    "ScriptedBackend",
    "Usage",
    "UsageLimitReached",
]
