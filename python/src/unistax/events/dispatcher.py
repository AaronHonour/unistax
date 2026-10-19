"""Event dispatcher for routing events."""

from collections.abc import Callable
from typing import Any

from .bus import Event


class EventDispatcher:
    """Event dispatcher with priority and filtering.

    Extends EventBus with additional features.
    """

    def __init__(self) -> None:
        """Initialize EventDispatcher."""
        self._handlers: dict[type[Event], list[tuple[int, Callable[..., Any]]]] = {}

    def register(
        self, event_type: type[Event], handler: Callable[..., Any], priority: int = 0
    ) -> None:  # noqa: E501
        """Register event handler with priority.

        Args:
            event_type: Event type
            handler: Handler function
            priority: Handler priority (higher = earlier)
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []

        self._handlers[event_type].append((priority, handler))
        # Sort by priority (descending)
        self._handlers[event_type].sort(key=lambda x: x[0], reverse=True)

    async def dispatch(self, event: Event) -> None:
        """Dispatch event to handlers in priority order."""
        event_type = type(event)

        if event_type not in self._handlers:
            return

        for _priority, handler in self._handlers[event_type]:
            await handler(event)
