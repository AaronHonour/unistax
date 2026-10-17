"""REST + WebSocket API for the agent framework.

Run with::

    uvicorn --factory unistax.agents.api.app:create_agent_api

Requires the ``agents-api`` extra: ``pip install 'unistax[agents-api]'``.
"""

from unistax.agents.api.app import create_agent_api
from unistax.agents.api.auth import Role, create_access_token
from unistax.agents.api.runtime import AgentRuntime
from unistax.agents.api.settings import AgentAPISettings

__all__ = [
    "AgentAPISettings",
    "AgentRuntime",
    "Role",
    "create_access_token",
    "create_agent_api",
]
