"""API application wrapper for FastAPI."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, FastAPI, Request  # type: ignore[import-not-found]
from fastapi.middleware.cors import CORSMiddleware  # type: ignore[import-not-found]
from fastapi.responses import JSONResponse  # type: ignore[import-not-found]

from unistax.config import ConfigManager
from unistax.lifecycle import Application
from unistax.logging import get_logger
from unistax.middleware import MiddlewarePipeline


@dataclass
class RouteConfig:
    """Route configuration."""

    path: str
    methods: list[str]
    handler: Callable[..., Any]
    tags: list[str] | None = None
    summary: str | None = None
    description: str | None = None
    response_model: Any | None = None


class APIApplication:
    """API application wrapper integrating FastAPI with toolkit."""

    def __init__(
        self,
        title: str = "API",
        version: str = "1.0.0",
        description: str | None = None,
        docs_url: str = "/docs",
        redoc_url: str = "/redoc",
        openapi_url: str = "/openapi.json",
        cors_enabled: bool = True,
        cors_origins: list[str] | None = None,
    ) -> None:
        """Initialize API application.

        Args:
            title: API title
            version: API version
            description: API description
            docs_url: Swagger UI docs URL
            redoc_url: ReDoc docs URL
            openapi_url: OpenAPI schema URL
            cors_enabled: Enable CORS
            cors_origins: Allowed CORS origins
        """
        self.app = FastAPI(
            title=title,
            version=version,
            description=description,
            docs_url=docs_url,
            redoc_url=redoc_url,
            openapi_url=openapi_url,
        )

        self.lifecycle = Application(name=title)
        self.middleware_pipeline: MiddlewarePipeline | None = None
        self.logger = get_logger(__name__)

        # Setup CORS
        if cors_enabled:
            self.add_cors(origins=cors_origins)

        # Setup exception handlers
        self._setup_exception_handlers()

    @classmethod
    def from_yaml(cls, path: str, prefix: str = "api") -> "APIApplication":
        """Create from YAML configuration.

        Args:
            path: Path to YAML file
            prefix: Configuration prefix

        Returns:
            APIApplication instance
        """
        config_manager = ConfigManager.from_yaml(path)
        config = config_manager.get(prefix, default={})

        return cls(
            title=config.get("title", "API"),
            version=config.get("version", "1.0.0"),
            description=config.get("description"),
            docs_url=config.get("docs_url", "/docs"),
            redoc_url=config.get("redoc_url", "/redoc"),
            openapi_url=config.get("openapi_url", "/openapi.json"),
            cors_enabled=config.get("cors_enabled", True),
            cors_origins=config.get("cors_origins"),
        )

    def add_cors(
        self,
        origins: list[str] | None = None,
        allow_credentials: bool = True,
        allow_methods: list[str] | None = None,
        allow_headers: list[str] | None = None,
    ) -> None:
        """Add CORS middleware.

        Args:
            origins: Allowed origins
            allow_credentials: Allow credentials
            allow_methods: Allowed HTTP methods
            allow_headers: Allowed headers
        """
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=origins or ["*"],
            allow_credentials=allow_credentials,
            allow_methods=allow_methods or ["*"],
            allow_headers=allow_headers or ["*"],
        )

    def add_middleware(self, middleware_class: Any, **kwargs: Any) -> None:
        """Add middleware to application.

        Args:
            middleware_class: Middleware class
            **kwargs: Middleware arguments
        """
        self.app.add_middleware(middleware_class, **kwargs)

    def _setup_exception_handlers(self) -> None:
        """Setup exception handlers."""

        @self.app.exception_handler(404)  # type: ignore[misc]
        async def not_found_handler(request: Request, exc: Any) -> JSONResponse:
            return JSONResponse(
                status_code=404,
                content={
                    "error": "Not Found",
                    "message": "The requested resource was not found",
                    "path": str(request.url.path),
                },
            )

        @self.app.exception_handler(500)  # type: ignore[misc]
        async def server_error_handler(request: Request, exc: Any) -> JSONResponse:
            self.logger.error(f"Internal server error: {exc}")
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal Server Error",
                    "message": "An unexpected error occurred",
                },
            )

    def include_router(
        self, router: "APIRouter", prefix: str = "", tags: list[str] | None = None
    ) -> None:  # noqa: E501
        """Include router in application.

        Args:
            router: API router
            prefix: URL prefix
            tags: Route tags
        """
        self.app.include_router(router.router, prefix=prefix, tags=tags or [])

    def on_startup(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Register startup handler.

        Args:
            func: Startup function

        Returns:
            Decorated function
        """
        return self.app.on_event("startup")(func)  # type: ignore[no-any-return]

    def on_shutdown(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Register shutdown handler.

        Args:
            func: Shutdown function

        Returns:
            Decorated function
        """
        return self.app.on_event("shutdown")(func)  # type: ignore[no-any-return]

    def get_app(self) -> FastAPI:
        """Get FastAPI application.

        Returns:
            FastAPI instance
        """
        return self.app
