"""U106: Hermes generation outlives any one panel subscription."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from bridge.core import hermesturn
from bridge.core import hermesreplay
from bridge.routers import hermes


ROOT = Path(__file__).resolve().parents[2]


def run(awaitable):
    return asyncio.run(awaitable)


def test_detach_does_not_cancel_producer_and_return_replays_every_frame():
    async def journey():
        store = hermesturn.HermesTurnStore()
        release = asyncio.Event()

        async def producer():
            yield 'data: {"delta":"one"}\n\n'
            await release.wait()
            yield 'data: {"delta":"two"}\n\n'
            yield "data: [DONE]\n\n"

        turn = store.start(sid="live", stored_sid="stored", request_id="request",
                           user="hello", image_name="", producer=producer())
        first_view = turn.subscribe(0)
        assert "one" in await anext(first_view)
        await first_view.aclose()  # lane switch / reload: viewer only
        assert turn.state == "running"
        release.set()
        for _ in range(100):
            if turn.state != "running":
                break
            await asyncio.sleep(0.001)
        replay = [frame async for frame in turn.subscribe(0)]
        assert ["one" in replay[0], "two" in replay[1], "[DONE]" in replay[2]] \
            == [True, True, True]
        assert turn.state == "completed"

    run(journey())


def test_two_subscribers_receive_the_same_frames_without_queue_theft():
    async def journey():
        store = hermesturn.HermesTurnStore()
        release = asyncio.Event()

        async def producer():
            await release.wait()
            yield 'data: {"delta":"shared"}\n\n'
            yield "data: [DONE]\n\n"

        turn = store.start(sid="live", stored_sid="stored", request_id="request",
                           user="hello", image_name="", producer=producer())
        async def collect():
            return [frame async for frame in turn.subscribe(0)]
        left = asyncio.create_task(collect())
        right = asyncio.create_task(collect())
        release.set()
        a, b = await asyncio.gather(left, right)
        assert a == b
        assert "shared" in a[0]

    run(journey())


def test_request_retry_is_idempotent_but_second_prompt_is_refused():
    async def journey():
        store = hermesturn.HermesTurnStore()
        release = asyncio.Event()

        async def producer():
            await release.wait()
            yield "data: [DONE]\n\n"

        turn = store.start(sid="live", stored_sid="stored", request_id="same",
                           user="hello", image_name="", producer=producer())
        assert store.find(request_id="same") is turn
        assert store.find(sid="live", active_only=True) is turn
        with pytest.raises(RuntimeError, match="already has a running turn"):
            store.start(sid="live", stored_sid="stored", request_id="different",
                        user="duplicate", image_name="", producer=producer())
        release.set()
        await asyncio.sleep(0)

    run(journey())


def test_active_turn_limit_refuses_new_work_without_cancelling_existing_turn(monkeypatch):
    async def journey():
        monkeypatch.setattr(hermesturn, "MAX_ACTIVE_TURNS", 1)
        store = hermesturn.HermesTurnStore()
        release = asyncio.Event()

        async def producer():
            await release.wait()
            yield "data: [DONE]\n\n"

        first = store.start(sid="one", stored_sid="one-stored", request_id="one",
                            user="one", image_name="", producer=producer())
        with pytest.raises(RuntimeError, match="maximum number"):
            store.start(sid="two", stored_sid="two-stored", request_id="two",
                        user="two", image_name="", producer=producer())
        assert first.state == "running"
        release.set()
        for _ in range(100):
            if first.state != "running":
                break
            await asyncio.sleep(0.001)
        assert first.state == "completed"

    run(journey())


def test_turn_metadata_is_bounded_and_oversize_restart_state_is_visible(monkeypatch):
    async def journey():
        monkeypatch.setattr(hermesturn, "MAX_TURN_USER_CHARS", 12)
        monkeypatch.setattr(hermesturn, "MAX_TURN_SEED_BYTES", 80)
        store = hermesturn.HermesTurnStore()

        async def producer():
            yield "data: [DONE]\n\n"

        turn = store.start(
            sid="live", stored_sid="stored", request_id="bounded",
            user="u" * 1000, image_name="image.png", producer=producer(),
            seed={"recovery_scope": "transcript_and_current_state",
                  "inflight": {"assistant": "private-large-state-" * 100}})
        assert turn.user == "u" * 12
        assert turn.seed == {"recovery_scope": "transcript_and_current_state",
                             "recovery_truncated": True}
        assert "private-large-state" not in json.dumps(turn.panel_record())

    run(journey())


def test_stale_live_session_rebinds_all_aliases_and_resumes_durable_history(monkeypatch):
    class Request:
        async def json(self):
            return {"session_id": "dead-live", "stored_sid": "durable",
                    "message": "continue", "request_id": "same-request"}

    class Gateway:
        def __init__(self):
            self.queues = {}
            self.prompts = 0
            self.calls = []

        def open_queue(self, sid, after_seq=None):
            queue = asyncio.Queue()
            self.queues[sid] = queue
            return queue

        def close_queue(self, sid):
            self.queues.pop(sid, None)

        async def rpc(self, method, params, timeout=30):
            self.calls.append((method, dict(params)))
            if method == "prompt.submit":
                self.prompts += 1
                if self.prompts == 1:
                    raise RuntimeError("session not found")
                self.queues[params["session_id"]].put_nowait({
                    "type": "message.delta", "payload": {"text": "answer"}})
                self.queues[params["session_id"]].put_nowait({
                    "type": "message.complete", "payload": {"status": "complete"}})
                return {"status": "streaming"}
            if method == "session.resume":
                assert params["session_id"] == "durable"
                return {"session_id": "new-live", "session_key": "durable"}
            raise AssertionError(method)

    async def journey():
        gateway = Gateway()
        store = hermesturn.HermesTurnStore()
        monkeypatch.setattr(hermes, "_HERMES", gateway)
        monkeypatch.setattr(hermes, "HERMES_TURNS", store)
        monkeypatch.setattr(hermes, "cfg", lambda: {"components": {"hermes": {}}})
        response = await hermes.hermes_chat(Request())
        body = "".join([frame async for frame in response.body_iterator])
        turn = store.find(request_id="same-request")
        assert "answer" in body and turn is not None
        assert turn.sid == "new-live" and turn.stored_sid == "durable"
        assert store.find(sid="dead-live") is None
        assert store.find(sid="new-live") is turn
        assert gateway.prompts == 2
        assert [call[0] for call in gateway.calls].count("session.resume") == 1

    run(journey())


def test_resume_follower_honours_stop_fallback_and_guard_audit():
    class Gateway:
        def __init__(self):
            self.queue = asyncio.Queue()

        def open_queue(self, _sid, after_seq=None):
            return self.queue

        def close_queue(self, _sid):
            pass

    async def journey():
        gateway = Gateway()
        audits = []
        await gateway.queue.put({"type": "guard"})
        await gateway.queue.put({"type": "_stop_requested"})
        policy = hermesreplay.ResumeFollowPolicy(
            gateway=gateway, max_turn=0,
            segment_spent=lambda *_: 0, segment_overrun=lambda *_: False,
            overrun_error=lambda *_: "", kill_segment=lambda *_: None,
            session_working=lambda *_: None, segment_resets=lambda *_: False,
            event_to_frames=lambda event: (
                ([{"type": "guard_flag", "path": "/tmp/out", "tool": "write"}], "")
                if event.get("type") == "guard" else ([], "")),
            guard_audit=lambda *args: audits.append(args),
            interrupt_overflow=lambda *_: None, stored_sid="durable")
        frames = [frame async for frame in hermesreplay.follow_resumed_turn(
            "live", 0, False, policy)]
        assert audits == [("/tmp/out", "write", "live", "durable")]
        assert any("interrupted" in frame for frame in frames)
        assert frames[-1] == "data: [DONE]\n\n"

    run(journey())


def test_replay_bound_is_visible_not_silent(monkeypatch):
    async def journey():
        monkeypatch.setattr(hermesturn, "MAX_TURN_BYTES", 30)
        turn = hermesturn.HermesTurn("t", "live", "stored", "request", "hello")
        await turn.append('data: {"delta":"first"}\n\n')
        await turn.append('data: {"delta":"second"}\n\n')
        await turn.finish()
        replay = [frame async for frame in turn.subscribe(0)]
        assert "exceeded the in-memory safety bound" in replay[0]
        assert any("second" in frame for frame in replay)
        assert turn.truncated is True

    run(journey())


def test_gap_replay_event_caps_nested_strings_and_lists():
    event = hermesreplay.safe_replay_event({"type": "tool.complete", "session_id": "s",
        "payload": {"name": "n" * 9000, "summary": "s" * 9000,
                    "result": {"error": "e" * 9000,
                               "resolved_path": "/" + "p" * 9000,
                               "files_modified": ["/" + "x" * 9000] * 100}}})
    payload = event["payload"]
    assert len(payload["name"]) == hermesreplay.REPLAY_FIELD_MAX
    assert len(payload["summary"]) == hermesreplay.REPLAY_FIELD_MAX
    assert len(payload["result"]["files_modified"]) == hermesreplay.REPLAY_LIST_MAX
    assert all(len(path) <= hermesreplay.REPLAY_FIELD_MAX
               for path in payload["result"]["files_modified"])


def test_ws_gap_cache_is_bounded_by_session_event_and_total_bytes(monkeypatch):
    event = {"type": "message.delta", "session_id": "one",
             "payload": {"text": "x" * 80}}
    cost = hermesreplay.replay_event_bytes(event)
    cache = hermesreplay.HermesGapCache(max_sessions=2, max_events_per_session=2,
                                        per_session_bytes=cost * 2,
                                        total_bytes=cost * 3)
    for seq in range(1, 4):
        cache.append("one", seq, event)
    assert len(cache.after("one", 0)) == 2
    cache.append("two", 4, event)
    cache.append("three", 5, event)
    assert cache.session_count <= 2
    assert cache.total_bytes <= cost * 3


def test_live_queue_overflow_is_one_visible_terminal_and_other_session_survives():
    async def journey():
        first = hermesreplay.HermesLiveQueue(max_events=1, max_bytes=200,
                                              max_event_bytes=150)
        second = hermesreplay.HermesLiveQueue(max_events=2, max_bytes=1000,
                                               max_event_bytes=500)
        assert first.offer({"type": "message.delta", "payload": {"text": "one"}})
        assert not first.offer({"type": "message.delta", "payload": {"text": "two"}})
        overflow = await first.get()
        assert overflow["type"] == "_queue_overflow"
        assert overflow["payload"]["error"] == hermesreplay.HERMES_QUEUE_OVERFLOW_ERROR
        assert first.closed and first.pending_events == 0 and first.pending_bytes == 0
        assert second.offer({"type": "message.delta", "payload": {"text": "safe"}})
        assert (await second.get())["payload"]["text"] == "safe"

    run(journey())


def test_live_queue_oversize_event_never_retains_the_raw_payload():
    async def journey():
        queue = hermesreplay.HermesLiveQueue(max_events=4, max_bytes=1000,
                                             max_event_bytes=100)
        secret = "do-not-retain-" * 100
        assert not queue.offer({"type": "tool.complete",
                                "payload": {"result": secret}})
        terminal = await queue.get()
        assert terminal["type"] == "_queue_overflow"
        assert secret not in json.dumps(terminal)
        assert queue.pending_bytes == 0

    run(journey())


def test_actual_hermes_route_interrupts_on_live_queue_overflow(monkeypatch):
    class Request:
        async def json(self):
            return {"session_id": "live", "stored_sid": "durable",
                    "message": "bounded", "request_id": "overflow-request"}

    class Gateway:
        def __init__(self):
            self.queues = {}
            self.interrupted = False

        def open_queue(self, sid, after_seq=None):
            queue = hermesreplay.HermesLiveQueue(max_events=1, max_bytes=1000,
                                                 max_event_bytes=500)
            self.queues[sid] = queue
            return queue

        def close_queue(self, sid):
            queue = self.queues.pop(sid, None)
            if queue:
                queue.close()

        async def rpc(self, method, params, timeout=30):
            if method == "prompt.submit":
                queue = self.queues[params["session_id"]]
                assert queue.offer({"type": "message.delta",
                                    "payload": {"text": "first"}})
                assert not queue.offer({"type": "message.delta",
                                        "payload": {"text": "second"}})
                return {"status": "streaming"}
            if method == "session.interrupt":
                self.interrupted = True
                return {"status": "interrupted"}
            raise AssertionError(method)

    async def journey():
        gateway = Gateway()
        monkeypatch.setattr(hermes, "_HERMES", gateway)
        monkeypatch.setattr(hermes, "HERMES_TURNS", hermesturn.HermesTurnStore())
        monkeypatch.setattr(hermes, "cfg", lambda: {"components": {"hermes": {}}})
        response = await hermes.hermes_chat(Request())
        body = "".join([frame async for frame in response.body_iterator])
        event = json.loads(next(line[6:] for line in body.splitlines()
                                if line.startswith("data: {")
                                and "proxy_error" in line))
        assert event == {"type": "proxy_error",
                         "error": hermesreplay.HERMES_QUEUE_OVERFLOW_ERROR}
        assert gateway.interrupted is True
        assert gateway.queues == {}

    run(journey())


@pytest.mark.parametrize("created", [
    {"session_id": "live-only"},
    {"stored_session_id": "stored-only"},
    {},
])
def test_session_new_fails_closed_without_both_durable_identities(monkeypatch, created):
    class Gateway:
        async def rpc(self, method, params):
            assert method == "session.create"
            return created

    async def journey():
        monkeypatch.setattr(hermes, "_HERMES", Gateway())
        response = await hermes.hermes_session_new()
        assert response.status_code == 502
        assert json.loads(response.body)["error"] == (
            "Hermes created no durable live/stored identity")

    run(journey())


def test_panel_wires_two_phase_send_and_non_submitting_recovery():
    panel = (ROOT / "bridge" / "panel" / "index.html").read_text()
    stream = (ROOT / "bridge" / "panel" / "assets" / "turn-stream.js").read_text()
    hermes = (ROOT / "bridge" / "routers" / "hermes.py").read_text()
    send = panel.split("async function sendChat()", 1)[1].split(
        "/* ============================================================================\n"
        "   PHASE 2", 1)[0]
    assert send.index("prepareHermesSession()") < send.index("inp.value = ''")
    assert "'/api/hermes/session/new'" in stream
    assert "request_id: streamApi.requestId()" in send
    assert "streamApi.postHermes(reqBody, turn.ctl.signal)" in send
    assert "/api/hermes/turns/" in stream and "recoverHermes" in stream
    assert 'HERMES_TURNS.start(' in hermes
    assert 'session.interrupt' not in stream.split("async function recoverHermes", 1)[1]
    assert "seed.recovery_truncated" in stream
