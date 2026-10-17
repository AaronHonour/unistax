"""Agent API routers."""

from unistax.agents.api.routers.agents.discovery import router as discovery_router
from unistax.agents.api.routers.agents.knowledge import router as knowledge_router
from unistax.agents.api.routers.agents.management import router as management_router
from unistax.agents.api.routers.agents.metrics import router as metrics_router
from unistax.agents.api.routers.agents.tasks import router as tasks_router
from unistax.agents.api.routers.agents.teams import router as teams_router
from unistax.agents.api.routers.agents.websocket import router as websocket_router
from unistax.agents.api.routers.agents.workflows import router as workflows_router

__all__ = [
    "discovery_router",
    "knowledge_router",
    "management_router",
    "metrics_router",
    "tasks_router",
    "teams_router",
    "websocket_router",
    "workflows_router",
]
