"""WebSocket event stream.

Connect to ``/api/v1/ws/events`` (all agents) or ``/api/v1/ws/agents/{agent_id}``.

Authentication: send ``Authorization: Bearer <token>`` in the handshake, or - for
browsers, which cannot set headers - send ``{"action": "auth", "token": "<token>"}``
as the first message (within ``ws_auth_timeout`` seconds). Tokens are deliberately
not accepted in the URL, where they would end up in access logs.

Client messages::

    {"action": "subscribe",   "event_types": ["task_completed"], "agent_id": "eng_1"}
    {"action": "unsubscribe", "event_types": ["task_completed"]}
    {"action": "ping"}

Server messages have a ``type`` of ``connected``, ``subscribed``, ``pong``,
``heartbeat``, ``error`` or ``event`` (the latter carries ``event``, ``timestamp``
and ``data``). ``agent_message`` events require the ``operator`` role.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from unistax.agents.api.auth import ANONYMOUS, AuthError, Principal, Role
from unistax.agents.api.runtime import AgentRuntime
from unistax.agents.api.services.events import KNOWN_EVENT_TYPES, Subscriber
from unistax.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/ws", tags=["WebSocket"])

HEARTBEAT_SECONDS = 30.0
MAX_CLIENT_MESSAGE = 4096

CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403


async def _authenticate(ws: WebSocket, runtime: AgentRuntime) -> Principal | None:
    if runtime.authenticator is None:
        return ANONYMOUS

    token: str | None = None
    header = ws.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
    else:
        try:
            raw = await asyncio.wait_for(ws.receive_text(), runtime.settings.ws_auth_timeout)
            message = json.loads(raw) if len(raw) <= MAX_CLIENT_MESSAGE else {}
            if isinstance(message, dict) and message.get("action") == "auth":
                token = message.get("token")
        except (asyncio.TimeoutError, json.JSONDecodeError, WebSocketDisconnect):
            token = None

    if not isinstance(token, str) or not token:
        await ws.close(code=CLOSE_UNAUTHORIZED, reason="Authentication required")
        return None
    try:
        return runtime.authenticator.authenticate(token)
    except AuthError as exc:
        code = (
            CLOSE_FORBIDDEN if exc.status_code == status.HTTP_403_FORBIDDEN else CLOSE_UNAUTHORIZED
        )
        await ws.close(code=code, reason=str(exc))
        return None


async def _sender(ws: WebSocket, sub: Subscriber) -> None:
    while True:
        try:
            envelope = await asyncio.wait_for(sub.queue.get(), HEARTBEAT_SECONDS)
        except asyncio.TimeoutError:
            envelope = {"type": "heartbeat"}
        await ws.send_json(envelope)
        if sub.overflowed:
            # The client fell behind and events were dropped: end the stream so it
            # reconnects, rather than silently serving a gappy one.
            await ws.close(code=status.WS_1013_TRY_AGAIN_LATER, reason="Consumer too slow")
            return


async def _receiver(ws: WebSocket, sub: Subscriber) -> None:
    while True:
        raw = await ws.receive_text()
        if len(raw) > MAX_CLIENT_MESSAGE:
            await ws.send_json({"type": "error", "message": "Message too large"})
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            await ws.send_json({"type": "error", "message": "Invalid JSON"})
            continue
        if not isinstance(message, dict):
            await ws.send_json({"type": "error", "message": "Expected a JSON object"})
            continue

        action = message.get("action")
        if action == "ping":
            await ws.send_json({"type": "pong"})
        elif action in ("subscribe", "unsubscribe"):
            requested = message.get("event_types", [])
            if not isinstance(requested, list) or not all(isinstance(t, str) for t in requested):
                await ws.send_json(
                    {"type": "error", "message": "event_types must be a list of strings"}
                )
                continue
            unknown = sorted(set(requested) - KNOWN_EVENT_TYPES)
            if unknown:
                await ws.send_json(
                    {
                        "type": "error",
                        "message": f"Unknown event types: {unknown}",
                        "known": sorted(KNOWN_EVENT_TYPES),
                    }
                )
                continue
            if action == "subscribe":
                sub.event_types.update(requested)
                agent_id = message.get("agent_id")
                if isinstance(agent_id, str):
                    sub.agent_id = agent_id
            else:
                sub.event_types.difference_update(requested)
            await ws.send_json(
                {
                    "type": "subscribed",
                    "event_types": sorted(sub.event_types),
                    "agent_id": sub.agent_id,
                }
            )
        else:
            await ws.send_json({"type": "error", "message": f"Unknown action '{action}'"})


async def _serve(ws: WebSocket, agent_id: str | None) -> None:
    runtime: AgentRuntime = ws.app.state.runtime
    await ws.accept()

    principal = await _authenticate(ws, runtime)
    if principal is None:
        return

    sub = runtime.hub.subscribe(can_see_messages=principal.role >= Role.OPERATOR)
    if sub is None:
        await ws.close(code=status.WS_1013_TRY_AGAIN_LATER, reason="Too many connections")
        return
    sub.agent_id = agent_id

    sender: asyncio.Task[None] | None = None
    try:
        await ws.send_json(
            {
                "type": "connected",
                "subject": principal.subject,
                "event_types": sorted(KNOWN_EVENT_TYPES),
            }
        )
        sender = asyncio.create_task(_sender(ws, sub))
        sender.add_done_callback(_consume_result)
        await _receiver(ws, sub)
    except (WebSocketDisconnect, RuntimeError):
        pass  # client went away, or the socket was closed under us
    finally:
        if sender is not None:
            sender.cancel()
        runtime.hub.unsubscribe(sub)


def _consume_result(task: asyncio.Task[None]) -> None:
    """Retrieve the sender's outcome so failures are logged, never left unretrieved."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc and not isinstance(exc, (WebSocketDisconnect, RuntimeError)):
        logger.error("WebSocket sender failed: %s", exc)


@router.websocket("/events")
async def events(ws: WebSocket) -> None:
    """Stream agent, task and workflow events."""
    await _serve(ws, agent_id=None)


@router.websocket("/agents/{agent_id}")
async def agent_events(ws: WebSocket, agent_id: str) -> None:
    """Stream events involving one agent."""
    await _serve(ws, agent_id=agent_id)
