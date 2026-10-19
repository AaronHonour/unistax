"""Application lifecycle management."""

import asyncio
import logging
import signal
import sys
from collections.abc import Callable
from enum import Enum
from typing import Any

from .health import HealthCheck, HealthCheckRegistry
from .hooks import LifecycleHook

logger = logging.getLogger(__name__)


class LifecycleEvent(str, Enum):
    """Application lifecycle events."""

    STARTUP = "startup"
    SHUTDOWN = "shutdown"
    READY = "ready"


class Application:
    """Application lifecycle manager.

    Manages startup, shutdown, and health checks.

    Examples:
        >>> app = Application()
        >>>
        >>> @app.on_startup
        ... async def init_db():
        ...     await db.connect()
        >>>
        >>> @app.on_shutdown
        ... async def cleanup():
        ...     await db.disconnect()
        >>>
        >>> @app.health_check
        ... def db_health():
        ...     return db.ping()
        >>>
        >>> await app.start()
    """

    def __init__(self, name: str = "app", shutdown_timeout: float = 30.0) -> None:
        """Initialize application.

        Args:
            name: Application name
            shutdown_timeout: Graceful shutdown timeout in seconds
        """
        self.name = name
        self.shutdown_timeout = shutdown_timeout
        self._startup_hooks: list[LifecycleHook] = []
        self._shutdown_hooks: list[LifecycleHook] = []
        self._health_registry = HealthCheckRegistry()
        self._is_running = False
        self._signal_handlers_installed = False

    def on_startup(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Register startup hook.

        Args:
            func: Startup function (can be sync or async)

        Returns:
            Original function
        """
        hook = LifecycleHook(LifecycleEvent.STARTUP, func)
        self._startup_hooks.append(hook)
        return func

    def on_shutdown(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Register shutdown hook.

        Args:
            func: Shutdown function (can be sync or async)

        Returns:
            Original function
        """
        hook = LifecycleHook(LifecycleEvent.SHUTDOWN, func)
        self._shutdown_hooks.append(hook)
        return func

    def health_check(
        self, name: str | None = None, check_type: str = "readiness"
    ) -> Callable[..., Any]:  # noqa: E501
        """Register health check.

        Args:
            name: Health check name (defaults to function name)
            check_type: "liveness" or "readiness"

        Returns:
            Decorator function
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            check_name = name or func.__name__
            health_check = HealthCheck(check_name, func, check_type)
            self._health_registry.register(health_check)
            return func

        return decorator

    async def start(self) -> None:
        """Start the application.

        Runs all startup hooks and installs signal handlers.
        """
        if self._is_running:
            return

        logger.info("Starting application: %s", self.name)

        # Install signal handlers
        self._install_signal_handlers()

        # Run startup hooks
        for hook in self._startup_hooks:
            try:
                await hook.execute()
                logger.info("Startup hook executed: %s", hook.func.__name__)
            except Exception as e:
                logger.error("Startup hook failed: %s: %s", hook.func.__name__, e)
                raise

        self._is_running = True
        logger.info("Application started: %s", self.name)

    async def stop(self) -> None:
        """Stop the application.

        Runs all shutdown hooks with timeout.
        """
        if not self._is_running:
            return

        logger.info("Stopping application: %s", self.name)
        self._is_running = False

        # Run shutdown hooks with timeout
        try:
            await asyncio.wait_for(self._run_shutdown_hooks(), timeout=self.shutdown_timeout)
            logger.info("Application stopped gracefully: %s", self.name)
        except asyncio.TimeoutError:
            logger.warning("Shutdown timeout exceeded: %s", self.name)

    async def _run_shutdown_hooks(self) -> None:
        """Run all shutdown hooks."""
        for hook in reversed(self._shutdown_hooks):  # Reverse order
            try:
                await hook.execute()
                logger.info("Shutdown hook executed: %s", hook.func.__name__)
            except Exception as e:
                logger.warning("Shutdown hook error: %s: %s", hook.func.__name__, e)
                # Continue with other hooks

    def _install_signal_handlers(self) -> None:
        """Install signal handlers for graceful shutdown."""
        if self._signal_handlers_installed:
            return

        def signal_handler(sig: Any, _frame: Any) -> None:
            logger.info("Received signal %s, initiating graceful shutdown...", sig)
            asyncio.create_task(self.stop())

        # Only on Unix systems
        if sys.platform != "win32":
            signal.signal(signal.SIGTERM, signal_handler)
            signal.signal(signal.SIGINT, signal_handler)

        self._signal_handlers_installed = True

    def get_health_status(self) -> dict[str, Any]:
        """Get application health status.

        Returns:
            Dictionary with health check results
        """
        return self._health_registry.check_all()

    def is_healthy(self) -> bool:
        """Check if application is healthy.

        Returns:
            True if all health checks pass
        """
        status = self.get_health_status()
        return status.get("status") == "healthy"

    def is_ready(self) -> bool:
        """Check if application is ready to serve requests.

        Returns:
            True if running and readiness checks pass
        """
        if not self._is_running:
            return False

        return self._health_registry.check_readiness()

    def is_alive(self) -> bool:
        """Check if application is alive (liveness check).

        Returns:
            True if running and liveness checks pass
        """
        if not self._is_running:
            return False

        return self._health_registry.check_liveness()

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Application(name={self.name}, running={self._is_running})"
