"""Events published by the swarm runner."""

from __future__ import annotations

from dataclasses import dataclass

from unistax.events import Event


@dataclass
class SwarmFinishedEvent(Event):
    """A swarm run reached a final state."""

    swarm_id: str = ""
    status: str = ""
    duration_seconds: float = 0.0
    calls_used: int = 0
