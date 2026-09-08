"""Executable contracts for U31's bridge-owned, in-memory turn buffer."""
from __future__ import annotations

import asyncio
import json

import bridge.core.turns as turnmod
from bridge.core.turns import TurnConflict, TurnOverflow, TurnStore


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
        assert events[-1]["state"] == "failed"

    asyncio.run(journey())


def test_named_upstream_error_is_the_terminal_reason_not_a_generic_eof():
    async def journey():
        store = TurnStore()

        async def producer():
            yield ('event: error\n'
                   'data: {"status":502,"text":"generation repeated tokens",'
                   '"error":"generation repeated tokens"}\n\n')

        record, _ = await store.create(body())
        await store.start(record["id"], producer)
        final = await wait_terminal(store, record["id"])
        assert final["state"] == "failed"
        assert final["error"] == "generation repeated tokens"
        events = await replay(store, record["id"])
        assert events == [{"seq": 1, "type": "terminal", "state": "failed",
                           "error": "generation repeated tokens"}]

    asyncio.run(journey())


def test_proxy_error_cannot_become_completed_after_done():
    async def journey():
        store = TurnStore()

        async def producer():
            yield frame({"type": "proxy_error", "error": "runner refused the request"})
            yield "data: [DONE]\n\n"

        record, _ = await store.create(body())
        await store.start(record["id"], producer)
        final = await wait_terminal(store, record["id"])
        events = await replay(store, record["id"])
        assert events[0]["type"] == "proxy_error"
        assert final["state"] == events[-1]["state"] == "failed"
        assert final["error"] == "runner refused the request"

    asyncio.run(journey())


def test_unterminated_frame_is_bounded_before_json_parsing(monkeypatch):
    async def journey():
        store = TurnStore()

        async def producer():
            yield 'data: {"delta":"'
            for _ in range(100):
                yield "x" * 100

        record, _ = await store.create(body())
        await store.start(record["id"], producer)
        final = await wait_terminal(store, record["id"])
        assert final["state"] == "failed"
        assert "incomplete event limit" in final["error"]

    monkeypatch.setattr(turnmod, "MAX_EVENT_BYTES_PER_TURN", 256)
    asyncio.run(journey())


def test_done_does_not_consume_trailing_partial_data():
    async def journey():
        store = TurnStore()

        async def producer():
            yield 'data: [DONE]\n\ndata: {"delta":"after completion"}'

        record, _ = await store.create(body())
        await store.start(record["id"], producer)
        await wait_terminal(store, record["id"])
        events = await replay(store, record["id"])
        assert events == [{"seq": 1, "type": "terminal", "state": "completed"}]

    asyncio.run(journey())


def test_crlf_and_chunk_split_sse_frames_complete_normally():
    async def journey():
        store = TurnStore()

        async def producer():
            yield b'data: {"delta":"first"}\r'
            yield b'\n\r'
            yield b'\ndata: {"delta":"second"}\r\n'
            yield b'\ndata: [DONE]\r'
            yield b'\n\r\n'

        record, _ = await store.create(body())
        await store.start(record["id"], producer)
        assert (await wait_terminal(store, record["id"]))["state"] == "completed"
        events = await replay(store, record["id"])
        assert [row.get("delta") for row in events[:-1]] == ["first", "second"]
        assert events[-1]["state"] == "completed"

    asyncio.run(journey())


def test_sse_line_grammar_and_utf8_survive_every_byte_boundary():
    async def journey():
        store = TurnStore()
        wire = (': keepalive\r'
                'event: message\r'
                'data:{"delta":"héllo",\r'
                'data: "thinking":false}\r\r'
                'data:[DONE]\r\r').encode("utf-8")

        async def producer():
            for byte in wire:
                yield bytes([byte])

        record, _ = await store.create(body())
        await store.start(record["id"], producer)
        assert (await wait_terminal(store, record["id"]))["state"] == "completed"
        events = await replay(store, record["id"])
        assert events[0]["delta"] == "héllo"
        assert events[-1]["state"] == "completed"

    asyncio.run(journey())


def test_named_error_at_eof_wins_without_a_trailing_blank_line():
    async def journey():
        store = TurnStore()

        async def producer():
            yield 'event: error\r\ndata:{"error":"exact upstream failure"}'

        record, _ = await store.create(body())
        await store.start(record["id"], producer)
        final = await wait_terminal(store, record["id"])
        assert final["state"] == "failed"
        assert final["error"] == "exact upstream failure"

    asyncio.run(journey())


def test_named_error_sentinel_cannot_become_success():
    async def journey():
        store = TurnStore()

        async def producer():
            yield "event: error\ndata:[DONE]\n\n"

        record, _ = await store.create(body())
        await store.start(record["id"], producer)
        final = await wait_terminal(store, record["id"])
        assert final["state"] == "failed"
        assert "error sentinel" in final["error"]

    asyncio.run(journey())


def test_incomplete_utf8_fails_as_a_visible_terminal():
    async def journey():
        store = TurnStore()

        async def producer():
            yield b'data: {"delta":"broken \xe2\x82'

        record, _ = await store.create(body())
        await store.start(record["id"], producer)
        final = await wait_terminal(store, record["id"])
        assert final["state"] == "failed"
        assert "bridge producer failed" in final["error"]

    asyncio.run(journey())


def test_malformed_final_sse_event_fails_visibly():
    async def journey():
        store = TurnStore()

        async def producer():
            yield 'data: {"delta":'

        record, _ = await store.create(body())
        await store.start(record["id"], producer)
        final = await wait_terminal(store, record["id"])
        assert final["state"] == "failed"
        assert "unreadable event" in final["error"]
        events = await replay(store, record["id"])
        assert events[0]["type"] == "proxy_error"

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


def test_process_wide_budget_evicts_only_unattached_terminal_replay(monkeypatch):
    async def journey():
        store = TurnStore()

        async def first_producer():
            yield frame({"delta": "x" * 120})
            yield "data: [DONE]\n\n"

        async def second_producer():
            yield frame({"delta": "y" * 120})
            yield "data: [DONE]\n\n"

        first, _ = await store.create(body("first", session="one"))
        await store.start(first["id"], first_producer)
        await wait_terminal(store, first["id"])
        first_bytes = store._turns[first["id"]].event_bytes
        monkeypatch.setattr(turnmod, "MAX_STORE_EVENT_BYTES",
                            first_bytes + turnmod.TERMINAL_RESERVE_BYTES + 80)
        second, _ = await store.create(body("second", session="two"))
        await store.start(second["id"], second_producer)
        await wait_terminal(store, second["id"])
        assert await store.metadata(first["id"]) is None
        assert (await store.metadata(second["id"]))["state"] == "completed"
        assert store._event_bytes == sum(
            turn.event_bytes for turn in store._turns.values())
        assert store._event_bytes <= turnmod.MAX_STORE_EVENT_BYTES

    asyncio.run(journey())


def test_process_wide_budget_never_evicts_a_subscriber_lease(monkeypatch):
    async def journey():
        store = TurnStore()

        async def producer():
            yield frame({"delta": "held"})
            yield "data: [DONE]\n\n"

        first, _ = await store.create(body("first", session="one"))
        await store.start(first["id"], producer)
        await wait_terminal(store, first["id"])
        subscription = await store.subscribe(first["id"])
        assert subscription is not None
        stream, release = subscription
        first_bytes = store._turns[first["id"]].event_bytes
        monkeypatch.setattr(turnmod, "MAX_STORE_EVENT_BYTES",
                            first_bytes + turnmod.TERMINAL_RESERVE_BYTES - 1)
        try:
            await store.create(body("second", session="two"))
        except TurnOverflow as exc:
            assert "replay store is full" in str(exc)
        else:
            raise AssertionError("a new turn spent a subscriber's retained frames")
        rows = [row async for row in stream]
        assert rows[-1]["type"] == "terminal"
        await release()

    asyncio.run(journey())


def test_exact_payload_budget_still_delivers_a_consistent_terminal(monkeypatch):
    async def journey():
        store = TurnStore()
        monkeypatch.setattr(turnmod, "MAX_STORE_EVENT_BYTES", 5000)
        monkeypatch.setattr(turnmod, "TERMINAL_RESERVE_BYTES", 4096)

        record, _ = await store.create(body())
        subscription = await store.subscribe(record["id"])
        assert subscription is not None
        stream, release = subscription
        await store._append(record["id"], {"delta": "x" * 890})
        assert await store._terminal(record["id"], "completed")
        rows = [row async for row in stream]
        metadata = await store.metadata(record["id"])
        assert rows[-1]["state"] == "completed"
        assert metadata["state"] == "completed" and metadata["error"] == ""
        assert store._event_bytes <= turnmod.MAX_STORE_EVENT_BYTES
        await release()

    asyncio.run(journey())


def test_terminal_fallback_state_matches_metadata(monkeypatch):
    async def journey():
        store = TurnStore()
        record, _ = await store.create(body())
        monkeypatch.setattr(turnmod, "TERMINAL_RESERVE_BYTES", 128)
        assert await store._terminal(record["id"], "completed", "x" * 200)
        rows = await replay(store, record["id"])
        metadata = await store.metadata(record["id"])
        assert rows[-1]["state"] == "failed"
        assert rows[-1]["error"] == metadata["error"]
        assert metadata["state"] == "failed"

    asyncio.run(journey())


def test_active_turn_count_is_bounded_before_a_producer_is_started(monkeypatch):
    async def journey():
        store = TurnStore()
        monkeypatch.setattr(turnmod, "MAX_ACTIVE_TURNS", 1)
        await store.create(body("first", session="one"))
        try:
            await store.create(body("second", session="two"))
        except TurnOverflow as exc:
            assert "replay store is full" in str(exc)
        else:
            raise AssertionError("the store accepted more active turns than its hard cap")

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


def test_direct_prompt_non_2xx_is_retried_with_the_answer(monkeypatch):
    import bridge.routers.chat as chat

    class Response:
        def __init__(self, status=200, payload=None, lines=None):
            self.status_code = status
            self._payload = payload if payload is not None else {}
            self._lines = lines or []

        def json(self):
            return self._payload

        async def aiter_lines(self):
            for line in self._lines:
                yield line

    class RunnerContext:
        async def __aenter__(self):
            return Response(lines=[
                'data: {"choices":[{"delta":{"content":"saved answer"}}]}',
                "data: [DONE]",
            ])

        async def __aexit__(self, *_args):
            return False

    class Runner:
        def stream(self, *_args, **_kwargs):
            return RunnerContext()

    posts = []

    async def ody(method, path, **kwargs):
        if method == "GET" and path.startswith("/api/history/"):
            return Response(payload={"history": []})
        if method == "POST":
            messages = kwargs["json"]["messages"]
            posts.append(messages)
            if len(posts) == 1:
                return Response(status=500, payload={"ok": False})
            return Response(payload={"ok": True, "count": len(messages)})
        return Response(payload=[])

    monkeypatch.setattr(chat, "_ody_req", ody)
    monkeypatch.setattr(chat, "_RUNNER", Runner())
    monkeypatch.setattr(chat, "cfg", lambda: {"runner": {
        "endpoint": "http://runner/v1", "api_key": "key", "port": 6767,
        "model": "model-1"}})
    monkeypatch.setattr(chat, "_live_model_id", lambda _port: "model-1")
    monkeypatch.setattr(chat, "_registry_models", lambda: [
        {"id": "model-1", "format": "gguf"}])
    monkeypatch.setattr(chat, "log_turn", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(chat, "log_thinking", lambda *_args, **_kwargs: None)

    async def journey():
        stream = await chat.direct_events({
            "session": "session-1", "request_id": "request-1",
            "message": "keep this prompt",
        })
        return [chunk async for chunk in stream]

    chunks = asyncio.run(journey())
    assert [row[0]["role"] for row in posts] == ["user", "user"]
    assert [row["role"] for row in posts[1]] == ["user", "assistant"]
    assert posts[1][0]["metadata"]["mot_direct_request_id"] == "request-1"
    assert chunks[-1] == "data: [DONE]\n\n"
    assert not any("could not be confirmed" in chunk for chunk in chunks)


def test_direct_persistence_receipt_requires_status_ok_and_exact_count():
    from bridge.routers.chat import _inject_acknowledged

    class Response:
        def __init__(self, status, payload=None, error=False):
            self.status_code = status
            self.payload = payload
            self.error = error

        def json(self):
            if self.error:
                raise ValueError("not json")
            return self.payload

    assert _inject_acknowledged(Response(200, {"ok": True, "count": 2}), 2)
    for response in (
        Response(500, {"ok": True, "count": 2}),
        Response(200, {"ok": False, "count": 2}),
        Response(200, {"ok": True, "count": 1}),
        Response(200, ["ok"]),
        Response(200, error=True),
    ):
        assert not _inject_acknowledged(response, 2)


def test_direct_prompt_success_is_not_duplicated_in_final_write(monkeypatch):
    import bridge.routers.chat as chat

    class Response:
        status_code = 200

        def __init__(self, payload=None, lines=None):
            self._payload = payload if payload is not None else {}
            self._lines = lines or []

        def json(self):
            return self._payload

        async def aiter_lines(self):
            for line in self._lines:
                yield line

    class RunnerContext:
        async def __aenter__(self):
            return Response(lines=[
                'data: {"choices":[{"delta":{"content":"one answer"}}]}',
                "data: [DONE]",
            ])

        async def __aexit__(self, *_args):
            return False

    posts = []

    async def ody(method, path, **kwargs):
        if method == "GET" and path.startswith("/api/history/"):
            return Response({"history": []})
        if method == "POST":
            messages = kwargs["json"]["messages"]
            posts.append(messages)
            return Response({"ok": True, "count": len(messages)})
        return Response([])

    monkeypatch.setattr(chat, "_ody_req", ody)
    monkeypatch.setattr(chat, "_RUNNER", type("Runner", (), {
        "stream": lambda *_args, **_kwargs: RunnerContext()})())
    monkeypatch.setattr(chat, "cfg", lambda: {"runner": {
        "endpoint": "http://runner/v1", "api_key": "key", "port": 6767,
        "model": "model-1"}})
    monkeypatch.setattr(chat, "_live_model_id", lambda _port: "model-1")
    monkeypatch.setattr(chat, "_registry_models", lambda: [
        {"id": "model-1", "format": "gguf"}])
    monkeypatch.setattr(chat, "log_turn", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(chat, "log_thinking", lambda *_args, **_kwargs: None)

    async def journey():
        stream = await chat.direct_events({
            "session": "session-1", "request_id": "request-2",
            "message": "persist once",
        })
        return [chunk async for chunk in stream]

    asyncio.run(journey())
    assert [[row["role"] for row in batch] for batch in posts] \
        == [["user"], ["assistant"]]


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
