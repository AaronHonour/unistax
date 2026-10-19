"""Queue manager."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .backends import QueueBackend


@dataclass
class Message:
    """Queue message."""

    id: str
    body: Any
    attributes: dict[str, Any]
    timestamp: datetime | None = None

    def __post_init__(self) -> None:
        """Initialize timestamp."""
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


class QueueManager:
    """Message queue manager."""

    def __init__(self, backend: "QueueBackend") -> None:
        """Initialize queue manager.

        Args:
            backend: Queue backend
        """
        self.backend = backend

    def send(self, queue_name: str, message: Any, attributes: dict[str, Any] | None = None) -> str:
        """Send message to queue.

        Args:
            queue_name: Queue name
            message: Message body
            attributes: Message attributes

        Returns:
            Message ID
        """
        return self.backend.send(queue_name, message, attributes or {})

    def receive(self, queue_name: str, max_messages: int = 1, wait_time: int = 0) -> list[Message]:
        """Receive messages from queue.

        Args:
            queue_name: Queue name
            max_messages: Maximum messages to receive
            wait_time: Wait time in seconds

        Returns:
            List of messages
        """
        return self.backend.receive(queue_name, max_messages, wait_time)

    def delete(self, queue_name: str, message_id: str) -> None:
        """Delete message from queue.

        Args:
            queue_name: Queue name
            message_id: Message ID
        """
        self.backend.delete(queue_name, message_id)

    def subscribe(self, queue_name: str, handler: Callable[[Message], None]) -> None:
        """Subscribe to queue with handler.

        Args:
            queue_name: Queue name
            handler: Message handler function
        """
        self.backend.subscribe(queue_name, handler)
