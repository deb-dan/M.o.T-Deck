"""Executable contracts for U31's bridge-owned, in-memory turn buffer."""
from __future__ import annotations

import asyncio
import json

import bridge.core.turns as turnmod
from bridge.core.turns import TurnConflict, TurnStore


def body(request_id: str = "request-1", lane: str = "chat", session: str = "session-1"):
    return {"request_id": request_id, "lane": lane, "session": session,
            "message": "keep working"}


def frame(payload: dict) -> str:
    return "data: " + json.dumps(payload) + "\n\n"


async def wait_terminal(store: TurnStore, turn_id: str) -> dict:
    for _ in range(200):
        record = await store.metadata(turn_id)
        if record and record["state"] in turnmod.TERMINAL:
            return record
        await asyncio.sleep(0)
    raise AssertionError("producer did not reach a terminal state")


async def replay(store: TurnStore, turn_id: str, after: int = 0) -> list[dict]:
    return [event async for event in store.events(turn_id, after)]


def test_disconnecting_one_subscriber_does_not_cancel_the_producer():
    async def journey():
        store = TurnStore()
        release = asyncio.Event()

        async def producer():
            yield frame({"delta": "first"})
            await release.wait()
            yield frame({"type": "tool_start", "tool": "search"})
            yield frame({"delta": "second"})
            yield "data: [DONE]\n\n"

        record, created = await store.create(body())
        assert created
        await store.start(record["id"], producer)
        subscription = store.events(record["id"])
        assert (await anext(subscription))["delta"] == "first"
        await subscription.aclose()  # exactly what a lane switch/reload does
        release.set()
        assert (await wait_terminal(store, record["id"]))["state"] == "completed"
        events = await replay(store, record["id"])
        assert [event.get("delta") for event in events if "delta" in event] == ["first", "second"]
        assert any(event.get("type") == "tool_start" for event in events)
        assert events[-1]["type"] == "terminal"

    asyncio.run(journey())


def test_two_subscribers_receive_the_same_ordered_frames_without_lost_wakeups():
    async def journey():
        store = TurnStore()
        release = asyncio.Event()

        async def producer():
            await release.wait()
            for number in range(8):
                yield frame({"delta": str(number)})
                await asyncio.sleep(0)
            yield "data: [DONE]\n\n"

        record, _ = await store.create(body())
        await store.start(record["id"], producer)
        first = asyncio.create_task(replay(store, record["id"]))
        second = asyncio.create_task(replay(store, record["id"]))
        release.set()
        a, b = await asyncio.gather(first, second)
        assert a == b
        assert [row["seq"] for row in a] == list(range(1, 10))

    asyncio.run(journey())


def test_replay_cursor_returns_only_later_committed_frames():
    async def journey():
        store = TurnStore()

        async def producer():
            yield frame({"delta": "a"})
            yield frame({"delta": "b"})
            yield frame({"delta": "c"})
            yield "data: [DONE]\n\n"

        record, _ = await store.create(body())
        await store.start(record["id"], producer)
        await wait_terminal(store, record["id"])
        assert [event.get("delta") for event in await replay(store, record["id"], 2)] == ["c", None]

    asyncio.run(journey())


def test_request_retry_is_idempotent_but_second_active_turn_conflicts():
    async def journey():
        store = TurnStore()
        first, created = await store.create(body())
        again, created_again = await store.create(body())
        assert not created_again and again["id"] == first["id"]
        try:
            await store.create(body("different-request"))
        except TurnConflict as exc:
            assert exc.turn_id == first["id"]
        else:
            raise AssertionError("a second active turn was accepted for one lane/session")

    asyncio.run(journey())


def test_chat_and_agent_cannot_write_one_session_concurrently_but_other_sessions_can():
    async def journey():
        store = TurnStore()
        first = await store.create(body("a", "chat", "same"))
        try:
            await store.create(body("b", "agent", "same"))
        except TurnConflict as exc:
            assert exc.turn_id == first[0]["id"]
        else:
            raise AssertionError("Chat and Agent were allowed to write one session concurrently")
        other = await store.create(body("c", "agent", "other"))
        assert other[0]["id"] != first[0]["id"]

    asyncio.run(journey())


def test_stop_is_scoped_and_idempotent():
    async def journey():
        store = TurnStore()
        release = asyncio.Event()

        async def producer():
            await release.wait()
            yield "data: [DONE]\n\n"

        a, _ = await store.create(body("a", "chat", "one"))
        b, _ = await store.create(body("b", "chat", "two"))
        await store.start(a["id"], producer)
        await store.start(b["id"], producer)
        assert (await store.stop(a["id"]))["state"] == "stopped"
        assert (await store.stop(a["id"]))["state"] == "stopped"
        assert (await store.metadata(b["id"]))["state"] == "running"
        release.set()
        assert (await wait_terminal(store, b["id"]))["state"] == "completed"

    asyncio.run(journey())


def test_unreadable_frames_fail_visibly_without_killing_the_buffer():
    async def journey():
        store = TurnStore()

        async def producer():
            yield "data: this is not json\n\n"
            yield "data: [DONE]\n\n"

        record, _ = await store.create(body())
        await store.start(record["id"], producer)
        await wait_terminal(store, record["id"])
        events = await replay(store, record["id"])
        assert events[0]["type"] == "proxy_error"
        assert events[-1]["state"] == "completed"

    asyncio.run(journey())


def test_overflow_becomes_an_honest_terminal_failure(monkeypatch):
    async def journey():
        store = TurnStore()

        async def producer():
            yield frame({"delta": "one"})
            yield frame({"delta": "two"})
            yield "data: [DONE]\n\n"

        record, _ = await store.create(body())
        await store.start(record["id"], producer)
        final = await wait_terminal(store, record["id"])
        assert final["state"] == "failed"
        assert "replay limit" in final["error"]

    monkeypatch.setattr(turnmod, "MAX_EVENTS_PER_TURN", 1)
    asyncio.run(journey())


def test_terminal_records_are_pruned_continuously(monkeypatch):
    async def journey():
        store = TurnStore()

        async def producer():
            yield "data: [DONE]\n\n"

        first, _ = await store.create(body("first", session="one"))
        await store.start(first["id"], producer)
        await wait_terminal(store, first["id"])
        second, _ = await store.create(body("second", session="two"))
        await store.start(second["id"], producer)
        await wait_terminal(store, second["id"])
        assert await store.metadata(first["id"]) is None
        assert (await store.metadata(second["id"]))["state"] == "completed"

    monkeypatch.setattr(turnmod, "MAX_TERMINAL_TURNS", 1)
    asyncio.run(journey())


def test_terminal_pruning_cannot_delete_a_frame_from_an_attached_subscriber(monkeypatch):
    async def journey():
        store = TurnStore()

        async def first_producer():
            yield frame({"delta": "visible-before-terminal"})
            yield "data: [DONE]\n\n"

        async def done_producer():
            yield "data: [DONE]\n\n"

        first, _ = await store.create(body("first", session="one"))
        stream = store.events(first["id"])
        waiting = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)  # attach the subscriber lease before production
        await store.start(first["id"], first_producer)
        assert (await waiting)["delta"] == "visible-before-terminal"
        await wait_terminal(store, first["id"])

        # Completing a newer turn crosses the one-terminal cap. The suspended
        # first stream must still own and receive its terminal frame.
        second, _ = await store.create(body("second", session="two"))
        await store.start(second["id"], done_producer)
        await wait_terminal(store, second["id"])
        assert await store.metadata(first["id"]) is not None
        terminal = await anext(stream)
        assert terminal["type"] == "terminal" and terminal["state"] == "completed"
        await stream.aclose()
        assert await store.metadata(first["id"]) is None

    monkeypatch.setattr(turnmod, "MAX_TERMINAL_TURNS", 1)
    asyncio.run(journey())


def test_route_style_subscription_reserves_lease_before_iteration(monkeypatch):
    async def journey():
        store = TurnStore()

        async def done_producer():
            yield "data: [DONE]\n\n"

        first, _ = await store.create(body("first", session="one"))
        await store.start(first["id"], done_producer)
        await wait_terminal(store, first["id"])
        subscription = await store.subscribe(first["id"])
        assert subscription is not None
        stream, release = subscription

        # The HTTP handler has reserved the row but StreamingResponse has not begun
        # iterating it yet. A newer completion must not prune the reserved final frame.
        second, _ = await store.create(body("second", session="two"))
        await store.start(second["id"], done_producer)
        await wait_terminal(store, second["id"])
        assert await store.metadata(first["id"]) is not None
        rows = [row async for row in stream]
        assert rows[-1]["type"] == "terminal"
        await release()  # background cleanup is deliberately idempotent
        assert await store.metadata(first["id"]) is None

    monkeypatch.setattr(turnmod, "MAX_TERMINAL_TURNS", 1)
    asyncio.run(journey())


def test_store_creates_no_transcript_or_event_files(tmp_path, monkeypatch):
    async def journey():
        store = TurnStore()
        record, _ = await store.create(body())
        await store.stop(record["id"])

    monkeypatch.chdir(tmp_path)
    asyncio.run(journey())
    assert list(tmp_path.iterdir()) == []


def test_legacy_direct_route_keeps_loffice_empty_session_compatibility(monkeypatch):
    import bridge.routers.chat as chat

    seen = []

    class Request:
        async def json(self):
            return {"session": "", "message": "summarise this selection"}

    async def fake_direct_events(payload):
        seen.append(payload)

        async def stream():
            yield "data: [DONE]\n\n"

        return stream()

    async def journey():
        monkeypatch.setattr(chat, "direct_events", fake_direct_events)
        response = await chat.chat_direct(Request())
        chunks = [chunk async for chunk in response.body_iterator]
        assert chunks == ["data: [DONE]\n\n"]

    asyncio.run(journey())
    assert seen == [{"session": "", "message": "summarise this selection"}]


def test_turn_routes_are_registered_in_the_real_app():
    import bridge.app as bridge_app

    paths = {getattr(route, "path", "") for route in bridge_app.app.routes}
    assert {"/api/turns", "/api/turns/active", "/api/turns/{turn_id}",
            "/api/turns/{turn_id}/events", "/api/turns/{turn_id}/stop"} <= paths
