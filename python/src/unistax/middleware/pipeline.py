"""Middleware pipeline implementation."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Request:
    """Request context."""

    method: str
    path: str
    headers: dict[str, str] = field(default_factory=dict[str, Any])
    query_params: dict[str, str] = field(default_factory=dict[str, Any])
    body: Any = None
    context: dict[str, Any] = field(
        default_factory=dict[str, Any]
    )  # For passing data between middleware  # noqa: E501


@dataclass
class Response:
    """Response context."""

    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict[str, Any])
    body: Any = None


# Type for next handler in chain
NextHandler = Callable[[Request], Awaitable[Response]]


class Middleware(ABC):
    """Base middleware class.

    Subclass and implement process() method.
    """

    @abstractmethod
    async def process(self, request: Request, next_handler: NextHandler) -> Response:
        """Process request through middleware.

        Args:
            request: Request context
            next_handler: Next middleware in chain

        Returns:
            Response
        """
        pass


class MiddlewarePipeline:
    """Middleware pipeline for request/response processing.

    Examples:
        >>> pipeline = MiddlewarePipeline()
        >>> pipeline.use(LoggingMiddleware())
        >>> pipeline.use(AuthMiddleware())
        >>> response = await pipeline.execute(request)
    """

    def __init__(self) -> None:
        """Initialize MiddlewarePipeline."""
        self._middleware: list[Middleware] = []

    def use(self, middleware: Middleware) -> "MiddlewarePipeline":
        """Add middleware to pipeline.

        Args:
            middleware: Middleware instance

        Returns:
            Self for chaining
        """
        self._middleware.append(middleware)
        return self

    async def execute(self, request: Request, final_handler: NextHandler | None = None) -> Response:
        """Execute middleware pipeline.

        Args:
            request: Request to process
            final_handler: Final handler after all middleware

        Returns:
            Response
        """
        if not self._middleware:
            if final_handler:
                return await final_handler(request)
            return Response(status_code=200, body={"message": "OK"})

        # Build middleware chain
        async def build_chain(index: int) -> Response:
            if index >= len(self._middleware):
                # Last middleware - call final handler
                if final_handler:
                    return await final_handler(request)
                return Response(status_code=200, body={"message": "OK"})

            middleware = self._middleware[index]

            async def next_handler(req: Request) -> Response:
                return await build_chain(index + 1)

            return await middleware.process(request, next_handler)

        return await build_chain(0)

    def __repr__(self) -> str:
        """Return string representation."""
        return f"MiddlewarePipeline(middleware={len(self._middleware)})"
