"""Notification manager."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .channels import ChannelBackend


class NotificationChannel(str, Enum):
    """Notification channel types."""

    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    WEBHOOK = "webhook"


@dataclass
class Notification:
    """Notification message."""

    channel: NotificationChannel
    recipient: str
    subject: str | None = None
    body: str = ""
    template: str | None = None
    template_vars: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    scheduled_at: datetime | None = None


class NotificationManager:
    """Multi-channel notification manager."""

    def __init__(self) -> None:
        """Initialize notification manager."""
        self.channels: dict[NotificationChannel, ChannelBackend] = {}

    def register_channel(
        self, channel_type: NotificationChannel, backend: "ChannelBackend"
    ) -> None:  # noqa: E501
        """Register channel backend.

        Args:
            channel_type: Channel type
            backend: Channel backend
        """
        self.channels[channel_type] = backend

    def send(self, notification: Notification) -> str:
        """Send notification.

        Args:
            notification: Notification to send

        Returns:
            Notification ID

        Raises:
            ValueError: If channel not registered
        """
        if notification.channel not in self.channels:
            raise ValueError(f"Channel {notification.channel} not registered")

        backend = self.channels[notification.channel]
        return backend.send(notification)

    def send_bulk(self, notifications: list[Notification]) -> list[str]:
        """Send multiple notifications.

        Args:
            notifications: List of notifications

        Returns:
            List of notification IDs
        """
        return [self.send(notif) for notif in notifications]
