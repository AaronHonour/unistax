"""Bridges the agent EventBus to WebSocket subscribers."""

from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from unistax.agents.api.db.store import to_jsonable
from unistax.agents.base import (
    AgentMessageEvent,
    AgentStateChangeEvent,
    CollaborationRequestEvent,
    TaskAssignedEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
)
from unistax.agents.orchestrator import WorkflowExecutedEvent
from unistax.events import Event, EventBus
from unistax.logging import get_logger

logger = get_logger(__name__)

EVENT_NAMES: dict[type[Event], str] = {
    TaskAssignedEvent: "task_assigned",
    TaskCompletedEvent: "task_completed",
    TaskFailedEvent: "task_failed",
    AgentStateChangeEvent: "agent_state_changed",
    AgentMessageEvent: "agent_message",
    CollaborationRequestEvent: "collaboration_requested",
    WorkflowExecutedEvent: "workflow_finished",
}
KNOWN_EVENT_TYPES = frozenset(EVENT_NAMES.values())
# Inter-agent message contents can be sensitive, so they need a higher role.
PRIVILEGED_EVENT_TYPES = frozenset({"agent_message"})


@dataclass(eq=False)
class Subscriber:
    """One WebSocket connection's delivery queue and filters."""

    queue: asyncio.Queue[dict[str, Any]]
    can_see_messages: bool = False
    event_types: set[str] = field(default_factory=set)  # empty = everything allowed
    agent_id: str | None = None
    overflowed: bool = False

    def wants(self, name: str, agent_ids: set[str]) -> bool:
        if name in PRIVILEGED_EVENT_TYPES and not self.can_see_messages:
            return False
        if self.event_types and name not in self.event_types:
            return False
        if self.agent_id and self.agent_id not in agent_ids:
            return False
        return True


def _agent_ids(name: str, data: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in ("agent_id", "requester_id"):
        if isinstance(data.get(key), str):
            ids.add(data[key])
    message = data.get("message")
    if isinstance(message, dict):
        if isinstance(message.get("from_agent"), str):
            ids.add(message["from_agent"])
        target = message.get("to_agent")
        ids.update([target] if isinstance(target, str) else target or [])
    return ids


class EventHub:
    """Fans EventBus events out to bounded per-connection queues."""

    def __init__(self, bus: EventBus, max_connections: int, queue_size: int) -> None:
        self._bus = bus
        self._max_connections = max_connections
        self._queue_size = queue_size
        self._subscribers: set[Subscriber] = set()
        self._attached = False

    @property
    def connection_count(self) -> int:
        return len(self._subscribers)

    def attach(self) -> None:
        if self._attached:
            return
        for event_type in EVENT_NAMES:
            self._bus.subscribe(event_type)(self._on_event)
        self._attached = True

    def detach(self) -> None:
        for event_type in EVENT_NAMES:
            self._bus.unsubscribe(event_type, self._on_event)
        self._attached = False

    def subscribe(self, *, can_see_messages: bool) -> Subscriber | None:
        """Register a connection; returns None when the connection cap is reached."""
        if len(self._subscribers) >= self._max_connections:
            return None
        sub = Subscriber(
            queue=asyncio.Queue(maxsize=self._queue_size), can_see_messages=can_see_messages
        )
        self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        self._subscribers.discard(sub)

    async def _on_event(self, event: Event) -> None:
        name = EVENT_NAMES.get(type(event))
        if name is None or not self._subscribers:
            return

        data = to_jsonable(dataclasses.asdict(event))
        data.pop("event_id", None)
        data.pop("timestamp", None)
        stamp = event.timestamp or datetime.now()
        envelope = {
            "type": "event",
            "event": name,
            "event_id": event.event_id,
            "timestamp": stamp.astimezone(timezone.utc).isoformat(),
            "data": data,
        }
        agent_ids = _agent_ids(name, data)

        for sub in list(self._subscribers):
            if not sub.wants(name, agent_ids):
                continue
            try:
                sub.queue.put_nowait(envelope)
            except asyncio.QueueFull:
                # A slow consumer must never block publishers; the connection is dropped.
                sub.overflowed = True
                logger.warning("WebSocket subscriber too slow; dropping connection")
