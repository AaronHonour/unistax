r"""Agent API application factory.

Run with::

    UNISTAX_AGENT_API_JWT_SECRET=<32+ chars> \\
    uvicorn --factory unistax.agents.api.app:create_agent_api --host 0.0.0.0 --port 8000

See ``unistax.agents.api.settings`` for all configuration options.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from unistax.agents.api.limits import rate_limit
from unistax.agents.api.middleware import RequestHardeningMiddleware
from unistax.agents.api.routers.agents import (
    datasource_router,
    discovery_router,
    knowledge_router,
    llm_router,
    management_router,
    metrics_router,
    swarms_router,
    tasks_router,
    teams_router,
    websocket_router,
    workflows_router,
)
from unistax.agents.api.runtime import AgentRuntime
from unistax.agents.api.settings import AgentAPISettings
from unistax.logging import get_logger

logger = get_logger(__name__)

API_VERSION = "1.0.0"


def create_agent_api(
    settings: AgentAPISettings | None = None, *, runtime: AgentRuntime | None = None
) -> FastAPI:
    """Build the agent API.

    Args:
        settings: Configuration; read from the environment when omitted.
        runtime: Pre-built runtime (mainly for tests).

    Raises:
        ValueError: If the configuration is unsafe (e.g. auth enabled without a key).
    """
    if runtime is None:
        runtime = AgentRuntime(settings or AgentAPISettings.from_env())
    settings = runtime.settings

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    docs = settings.docs_enabled
    app = FastAPI(
        title="Agent Framework API",
        version=API_VERSION,
        description="Manage and orchestrate autonomous data-platform agents.",
        lifespan=lifespan,
        docs_url=f"{settings.api_prefix}/docs" if docs else None,
        redoc_url=f"{settings.api_prefix}/redoc" if docs else None,
        openapi_url=f"{settings.api_prefix}/openapi.json" if docs else None,
    )
    app.state.runtime = runtime

    # The last middleware added is the outermost.
    app.add_middleware(RequestHardeningMiddleware, max_body_bytes=settings.max_request_bytes)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=False,  # bearer tokens, not cookies
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )

    api = APIRouter(prefix=settings.api_prefix, dependencies=[Depends(rate_limit)])
    for router in (
        management_router,
        tasks_router,
        teams_router,
        discovery_router,
        workflows_router,
        knowledge_router,
        metrics_router,
        datasource_router,
        swarms_router,
        llm_router,
    ):
        api.include_router(router)
    app.include_router(api)
    app.include_router(websocket_router, prefix=settings.api_prefix)

    @app.get("/health/live", tags=["Health"], summary="Liveness probe")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["Health"], summary="Readiness probe")
    async def ready(response: Response) -> dict[str, object]:
        db_ok = await runtime.db.ping()
        is_ready = runtime.ready and db_ok
        if not is_ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ready" if is_ready else "unavailable",
            "database": db_ok,
            "datasource": runtime.datasource_state,
            "llm": runtime.llm_state,
        }

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        request_id = request.scope.get("state", {}).get("request_id")
        logger.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error", "request_id": request_id},
        )

    return app
