"""Runner-to-transcript journeys: network chunking must not change a reply."""
import asyncio
import json

import pytest

from bridge.core.turns import TurnStore
from bridge.routers import chat


@pytest.fixture
def runner(monkeypatch):
    class Fixture:
        lines = []
        posts = []
        thinking = []

        def stream(self, *args, **kwargs):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        status_code = 200

        async def aiter_lines(self):
            for line in self.lines:
                yield line

    fixture = Fixture()

    class Receipt:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    async def ody(method, path, **kwargs):
        if method == "POST":
            rows = kwargs["json"]["messages"]
            fixture.posts.extend(rows)
            return Receipt({"ok": True, "count": len(rows)})
        return Receipt({"history": []} if "/history/" in path else [])

    monkeypatch.setattr(chat, "_RUNNER", fixture)
    monkeypatch.setattr(chat, "cfg", lambda: {"runner": {"model": "fixture"}})
    monkeypatch.setattr(chat, "_registry_models", lambda: [])
    monkeypatch.setattr(chat, "_ody_req", ody)
    monkeypatch.setattr(chat, "log_thinking",
                        lambda sid, answer, think: fixture.thinking.append((answer, think)))
    monkeypatch.setattr(chat, "log_turn", lambda *args, **kwargs: None)
    return fixture


def delta(content=None, reasoning=None, finish=None, prefix="data: "):
    payload = {}
    if content is not None:
        payload["content"] = content
    if reasoning is not None:
        payload["reasoning_content"] = reasoning
    return prefix + json.dumps({"choices": [{"delta": payload, "finish_reason": finish}]})


def journey():
    async def run():
        store = TurnStore()
        body = {"lane": "chat", "session": "fixture-session", "request_id": "fixture-turn",
                "message": "Give an answer"}
        record, _ = await store.create(body)

        async def producer():
            stream = await chat.direct_events(body)
            async for frame in stream:
                yield frame

        await store.start(record["id"], producer)
        rows = [row async for row in store.events(record["id"])]
        assert (await store.metadata(record["id"]))["state"] == rows[-1]["state"]
        return rows

    return asyncio.run(run())


@pytest.mark.parametrize("width", [1, 2, 3, 7, 1000])
def test_inline_reasoning_survives_chunk_boundaries_in_stream_and_history(runner, width):
    text = "<think>private reasoning</think>visible answer"
    runner.lines = [delta(text[i:i + width]) for i in range(0, len(text), width)]
    runner.lines += ["data: [DONE]"]
    rows = journey()
    assert "".join(r.get("delta", "") for r in rows if not r.get("thinking")) == "visible answer"
    assert "".join(r.get("delta", "") for r in rows if r.get("thinking")) == "private reasoning"
    assert runner.posts[-1]["content"] == "visible answer"
    assert runner.thinking == [("visible answer", "private reasoning")]
    assert rows[-1]["state"] == "completed"


def test_reasoning_and_content_in_one_delta_preserve_both(runner):
    runner.lines = [delta("answer", "reasoning"), "data: [DONE]"]
    rows = journey()
    assert runner.posts[-1]["content"] == "answer"
    assert runner.thinking == [("answer", "reasoning")]
    assert rows[-1]["state"] == "completed"


def test_clean_network_eof_keeps_partial_answer_but_is_not_completion(runner):
    runner.lines = [delta("incomplete answer")]
    rows = journey()
    assert runner.posts[-1]["content"] == "incomplete answer"
    assert rows[-1]["state"] == "failed"
    assert "completion" in rows[-1]["error"]


@pytest.mark.parametrize("ending", ["data:[DONE]", delta(finish="stop"), delta(finish="length")])
def test_explicit_runner_completion_is_authoritative(runner, ending):
    runner.lines = [delta("answer", prefix="data:"), ending]
    rows = journey()
    assert runner.posts[-1]["content"] == "answer"
    assert rows[-1]["state"] == "completed"


def test_malformed_payload_cannot_be_hidden_by_later_done(runner):
    runner.lines = [delta("partial"), "data: {broken", "data: [DONE]"]
    assert journey()[-1]["state"] == "failed"


def test_literal_partial_delimiter_is_not_dropped_at_end(runner):
    runner.lines = [delta("literal <thi"), "data: [DONE]"]
    assert journey()[-1]["state"] == "completed"
    assert runner.posts[-1]["content"] == "literal <thi"


def test_closing_direct_stream_preserves_partial_without_yielding_during_close(runner):
    runner.lines = [delta("partial <thi"), delta("nk>reasoning")]

    async def run():
        stream = await chat.direct_events({"session": "fixture-session", "message": "prompt"})
        async for frame in stream:
            if '"delta"' in frame:
                await stream.aclose()
                break

    asyncio.run(run())
    assert runner.posts[-1]["content"] == "partial <thi"
