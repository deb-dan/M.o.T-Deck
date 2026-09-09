"""Pause/resume/cancel operate on one writer, even while a response is stalled."""
import asyncio
import hashlib
from pathlib import Path

from bridge.routers import downloads as D


def test_rapid_pause_resume_never_runs_two_writers(tmp_path, monkeypatch):
    async def run():
        first_chunk = asyncio.Event()
        stalled = asyncio.Event()
        payload = b"a" * (1 << 20) + b"b" * (1 << 20)
        active = 0
        peak = 0
        calls = []
        added = []

        class Stream:
            def __init__(self, headers):
                self.offset = int(headers.get("Range", "bytes=0-")[6:-1])
                self.status_code = 206 if self.offset else 200
                self.headers = {"content-length": str(len(payload) - self.offset)}

            async def __aenter__(self):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                calls.append(self.offset)
                return self

            async def __aexit__(self, *args):
                nonlocal active
                active -= 1

            async def aiter_bytes(self, size):
                if not self.offset:
                    yield payload[:1 << 20]
                    first_chunk.set()
                    await stalled.wait()
                yield payload[1 << 20:]

        class Client:
            def stream(self, *args, headers):
                return Stream(headers)

        monkeypatch.setattr(D, "_DL", Client())
        monkeypatch.setattr(D, "DOWNLOADS", {})
        monkeypatch.setattr(D, "_registry_add", added.append)
        monkeypatch.setattr(D, "_modeltools", None)
        dest = tmp_path / "fixture.gguf"
        entry = D._mk_download("fixture/model", [{
            "name": dest.name, "url": "/fixture", "dest": str(dest),
            "total": len(payload), "done": 0, "sha256": hashlib.sha256(payload).hexdigest(),
        }], "fixture", "gguf")
        await first_chunk.wait()
        old_task = entry["task"]
        await asyncio.wait_for(D.dl_pause(entry["id"]), 1)
        try:
            assert old_task.done(), "Pause returned while its writer still owned the partial file"
            await asyncio.gather(D.dl_resume(entry["id"]), D.dl_resume(entry["id"]))
            await asyncio.wait_for(entry["task"], 2)
            assert peak == 1
            assert calls == [0, 1 << 20]
            assert dest.read_bytes() == payload
            assert entry["state"] == "done" and len(added) == 1
            assert "control_lock" not in D._dl_json(entry)
        finally:
            stalled.set()
            for task in {old_task, entry["task"]}:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_cancel_while_paused_waits_for_writer_before_removing_partial(tmp_path, monkeypatch):
    async def run():
        part = tmp_path / "model.gguf.part"
        part.write_bytes(b"partial")
        started = asyncio.Event()
        released = asyncio.Event()

        async def writer():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                released.set()

        task = asyncio.create_task(writer())
        await started.wait()
        entry = {"id": "fixture", "state": "paused", "task": task,
                 "files": [{"dest": str(part)[:-5]}]}
        monkeypatch.setattr(D, "DOWNLOADS", {"fixture": entry})
        try:
            await D.dl_cancel("fixture")
            assert task.done() and released.is_set()
            assert not part.exists() and entry["state"] == "cancelled"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
