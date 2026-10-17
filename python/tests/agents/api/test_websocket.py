"""WebSocket event stream."""

from __future__ import annotations

import asyncio

import pytest
from starlette.websockets import WebSocketDisconnect

from unistax.agents import AgentMessageEvent, Message

from .conftest import API, SECRET, create_agent, submit_task, wait_task

pytestmark = pytest.mark.api

WS = f"{API}/ws/events"


def collect_until(ws, event_name, limit=20):
    seen = []
    for _ in range(limit):
        message = ws.receive_json()
        seen.append(message)
        if message.get("event") == event_name:
            return seen
    raise AssertionError(f"never saw {event_name}: {[m.get('event', m['type']) for m in seen]}")


class TestAuthentication:
    def test_header_auth(self, client, viewer):
        with client.websocket_connect(WS, headers=viewer) as ws:
            assert ws.receive_json()["type"] == "connected"

    def test_first_message_auth_for_browsers(self, client, viewer):
        token = viewer["Authorization"].split()[1]
        with client.websocket_connect(WS) as ws:
            ws.send_json({"action": "auth", "token": token})
            assert ws.receive_json()["type"] == "connected"

    def test_bad_token_closes_with_4401(self, client):
        with client.websocket_connect(WS) as ws:
            ws.send_json({"action": "auth", "token": "garbage"})
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
        assert exc.value.code == 4401

    def test_unauthenticated_first_message_closes(self, client):
        with client.websocket_connect(WS) as ws:
            ws.send_json({"action": "ping"})
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
        assert exc.value.code == 4401

    def test_no_auth_timeout(self, make_client):
        client = make_client(ws_auth_timeout=0.2)
        with client.websocket_connect(WS) as ws:
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
        assert exc.value.code == 4401

    def test_token_in_query_string_is_not_accepted(self, client, viewer):
        token = viewer["Authorization"].split()[1]
        with client.websocket_connect(f"{WS}?token={token}") as ws:
            ws.send_json({"action": "ping"})
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()

    def test_connection_cap(self, make_client, viewer):
        client = make_client(ws_max_connections=1)
        with client.websocket_connect(WS, headers=viewer) as first:
            assert first.receive_json()["type"] == "connected"
            with client.websocket_connect(WS, headers=viewer) as second:
                with pytest.raises(WebSocketDisconnect) as exc:
                    second.receive_json()
            assert exc.value.code == 1013

    def test_connections_are_released(self, client, viewer):
        runtime = client.app.state.runtime
        with client.websocket_connect(WS, headers=viewer) as ws:
            ws.receive_json()
            assert runtime.hub.connection_count == 1
        client.get("/health/live")
        for _ in range(50):
            if runtime.hub.connection_count == 0:
                break
            import time

            time.sleep(0.02)
        assert runtime.hub.connection_count == 0


class TestStreaming:
    def test_task_lifecycle_events_arrive_in_order(self, client, admin):
        create_agent(client, admin)
        with client.websocket_connect(WS, headers=admin) as ws:
            ws.receive_json()
            submit_task(client, admin)
            seen = collect_until(ws, "task_completed")

        events = [m["event"] for m in seen if m["type"] == "event"]
        assert events.index("task_assigned") < events.index("task_completed")
        completed = seen[-1]["data"]
        assert completed["agent_id"] == "eng_1" and completed["success"] is True
        assert completed["task_type"] == "quality_check"
        assert seen[-1]["timestamp"].endswith("+00:00")

    def test_subscribe_filters_event_types(self, client, admin):
        create_agent(client, admin)
        with client.websocket_connect(WS, headers=admin) as ws:
            ws.receive_json()
            ws.send_json({"action": "subscribe", "event_types": ["task_completed"]})
            assert ws.receive_json()["event_types"] == ["task_completed"]
            task_id = submit_task(client, admin)["task_id"]
            first = ws.receive_json()
        assert first["event"] == "task_completed" and first["data"]["task_id"] == task_id

    def test_unknown_event_types_and_actions_are_rejected(self, client, viewer):
        with client.websocket_connect(WS, headers=viewer) as ws:
            ws.receive_json()
            ws.send_json({"action": "subscribe", "event_types": ["nope"]})
            assert ws.receive_json()["type"] == "error"
            ws.send_json({"action": "explode"})
            assert ws.receive_json()["type"] == "error"
            ws.send_text("not json")
            assert ws.receive_json()["type"] == "error"
            ws.send_json({"action": "ping"})
            assert ws.receive_json()["type"] == "pong"

    def test_agent_scoped_stream(self, client, admin):
        create_agent(client, admin, "eng_1")
        create_agent(client, admin, "eng_2")
        with client.websocket_connect(f"{API}/ws/agents/eng_2", headers=admin) as ws:
            ws.receive_json()
            ws.send_json({"action": "subscribe", "event_types": ["task_completed"]})
            ws.receive_json()
            other = submit_task(client, admin, agent_id="eng_1")["task_id"]
            mine = submit_task(client, admin, agent_id="eng_2")["task_id"]
            message = ws.receive_json()
        assert message["data"]["task_id"] == mine and message["data"]["task_id"] != other

    def test_workflow_completion_is_broadcast(self, client, admin):
        create_agent(client, admin)
        with client.websocket_connect(WS, headers=admin) as ws:
            ws.receive_json()
            ws.send_json({"action": "subscribe", "event_types": ["workflow_finished"]})
            ws.receive_json()
            wf = client.post(
                f"{API}/workflows",
                json={
                    "name": "w",
                    "steps": [
                        {
                            "step_id": "a",
                            "task_type": "quality_check",
                            "agent_persona": "data_engineer",
                        }
                    ],
                },
                headers=admin,
            ).json()["data"]["workflow_id"]
            client.post(f"{API}/workflows/{wf}/execute", headers=admin)
            message = ws.receive_json()
        assert message["event"] == "workflow_finished"
        assert message["data"]["workflow_id"] == wf and message["data"]["status"] == "completed"

    def test_agent_messages_need_operator_role(self, client, admin, viewer, operator):
        create_agent(client, admin, "eng_1")
        runtime = client.app.state.runtime

        def publish():
            client.portal.call(
                runtime.event_bus.publish,
                AgentMessageEvent(
                    message=Message(
                        from_agent="eng_1",
                        to_agent="eng_2",
                        msg_type="notification",
                        content={"secret": 1},
                    )
                ),
            )

        with (
            client.websocket_connect(WS, headers=viewer) as v,
            client.websocket_connect(WS, headers=operator) as o,
        ):
            v.receive_json()
            o.receive_json()
            publish()
            seen_by_operator = o.receive_json()
            assert seen_by_operator["event"] == "agent_message"
            assert seen_by_operator["data"]["message"]["content"] == {"secret": 1}

            v.send_json({"action": "ping"})
            assert v.receive_json()["type"] == "pong"  # nothing queued ahead of the pong

    def test_slow_consumer_is_dropped_not_blocking_publishers(self, make_client, admin):
        client = make_client(ws_queue_size=1)
        create_agent(client, admin)
        runtime = client.app.state.runtime
        sub = runtime.hub.subscribe(can_see_messages=True)  # a consumer that never reads
        for _ in range(3):
            wait_task(client, admin, submit_task(client, admin)["task_id"])
        assert sub.overflowed is True
        runtime.hub.unsubscribe(sub)


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.closed_with = None

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self, code=1000, reason=None):
        self.closed_with = code


async def test_overflowed_consumer_gets_a_1013_close():
    from unistax.agents.api.routers.agents.websocket import _sender
    from unistax.agents.api.services.events import EventHub
    from unistax.events import EventBus

    hub = EventHub(EventBus(), max_connections=5, queue_size=2)
    sub = hub.subscribe(can_see_messages=True)
    sub.queue.put_nowait({"type": "event", "n": 1})
    sub.queue.put_nowait({"type": "event", "n": 2})
    sub.overflowed = True  # a third event did not fit

    ws = FakeSocket()
    await asyncio.wait_for(_sender(ws, sub), 2)

    assert ws.closed_with == 1013
    assert [m["n"] for m in ws.sent] == [1]  # stopped at the first opportunity


async def test_hub_marks_slow_subscribers_and_never_blocks_publishers():
    from unistax.agents.api.services.events import EventHub
    from unistax.agents.base import TaskAssignedEvent
    from unistax.events import EventBus

    bus = EventBus()
    hub = EventHub(bus, max_connections=5, queue_size=1)
    hub.attach()
    slow = hub.subscribe(can_see_messages=False)
    for i in range(3):
        await bus.publish(TaskAssignedEvent(task_id=str(i), agent_id="a", task_type="t"))

    assert slow.overflowed and slow.queue.qsize() == 1
    hub.detach()
