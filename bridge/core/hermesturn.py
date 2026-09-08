"""Bridge-lifetime ownership for Hermes turns and their panel subscriptions.

Hermes remains the generation authority and durable transcript owner.  This module
does one narrower job: an HTTP client going away must not cancel the bridge relay that
is enforcing M.O.T's watchdogs and translating Hermes events.  The relay is therefore
one background task with any number of cursor-based subscribers.

Only already-redacted panel SSE frames are retained, in memory, for the current turn.
There is no second transcript database and no raw tool payload journal.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import AsyncIterator


# The relay is intentionally bridge-lifetime state, so it needs a real upper
# bound rather than merely a TTL.  Eight active plus eight recently finished
# turns can retain at most 64 MiB of already-redacted panel frames.  A viewer
# that falls behind sees the explicit replay-bound error in ``subscribe`` and
# can recover the durable transcript from Hermes; it is never silently given a
# partial answer.
MAX_TURN_BYTES = 4 * 1024 * 1024
MAX_TURN_USER_CHARS = 64 * 1024
MAX_TURN_SEED_BYTES = 512 * 1024
MAX_ACTIVE_TURNS = 8
MAX_FINISHED_TURNS = 8
FINISHED_TTL_S = 300.0


def _bounded_seed(seed: dict | None) -> dict | None:
    """Keep projected restart state bounded, or replace it with a visible verdict."""
    if not seed:
        return None
    try:
        encoded = json.dumps(seed, ensure_ascii=False, separators=(",", ":")).encode()
    except (TypeError, ValueError, UnicodeError):
        encoded = b"x" * (MAX_TURN_SEED_BYTES + 1)
    if len(encoded) <= MAX_TURN_SEED_BYTES:
        return seed
    return {
        "recovery_scope": str(seed.get("recovery_scope") or
                              "transcript_and_current_state")[:100],
        "recovery_truncated": True,
    }


@dataclass
class HermesTurn:
    id: str
    sid: str
    stored_sid: str
    request_id: str
    user: str
    image_name: str = ""
    seed: dict | None = None
    created_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    state: str = "running"
    error: str = ""
    frames: list[tuple[int, str]] = field(default_factory=list)
    first_seq: int = 1
    next_seq: int = 1
    retained_bytes: int = 0
    truncated: bool = False
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)

    async def append(self, frame: str) -> None:
        encoded = frame.encode("utf-8", errors="replace")
        async with self.condition:
            self.frames.append((self.next_seq, frame))
            self.next_seq += 1
            self.retained_bytes += len(encoded)
            while self.frames and self.retained_bytes > MAX_TURN_BYTES:
                _seq, removed = self.frames.pop(0)
                self.retained_bytes -= len(removed.encode("utf-8", errors="replace"))
                self.first_seq = _seq + 1
                self.truncated = True
            self.condition.notify_all()

    async def finish(self, state: str = "completed", error: str = "") -> None:
        async with self.condition:
            self.state = state
            self.error = error
            self.finished_at = time.monotonic()
            self.condition.notify_all()

    async def subscribe(self, after: int = 0) -> AsyncIterator[str]:
        """Replay and follow without consuming another subscriber's wake-up."""
        cursor = max(0, int(after or 0))
        while True:
            async with self.condition:
                if cursor < self.first_seq - 1:
                    message = (
                        'data: {"type":"proxy_error","error":"Hermes replay exceeded '
                        'the in-memory safety bound; reopen the session to recover from '
                        'Hermes history"}\n\n'
                    )
                    cursor = self.first_seq - 1
                else:
                    message = ""
                ready = [(seq, value) for seq, value in self.frames if seq > cursor]
                terminal = self.state != "running"
                if not message and not ready and not terminal:
                    await self.condition.wait()
                    continue
            if message:
                yield message
            for seq, value in ready:
                cursor = seq
                yield value
            if terminal and cursor >= self.next_seq - 1:
                return

    def panel_record(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.sid,
            "stored_id": self.stored_sid,
            "user": self.user,
            "image_name": self.image_name,
            "state": self.state,
            "first_seq": self.first_seq,
            "last_seq": self.next_seq - 1,
            "truncated": self.truncated,
            **({"seed": self.seed} if self.seed else {}),
        }


class HermesTurnStore:
    def __init__(self) -> None:
        self._turns: dict[str, HermesTurn] = {}
        self._by_sid: dict[str, str] = {}
        self._by_stored: dict[str, str] = {}
        self._by_request: dict[str, str] = {}
        self._tasks: set[asyncio.Task] = set()

    def _prune(self) -> None:
        now = time.monotonic()
        finished = sorted(
            (turn for turn in self._turns.values() if turn.finished_at is not None),
            key=lambda turn: turn.finished_at or 0,
            reverse=True,
        )
        retire = {
            turn.id for index, turn in enumerate(finished)
            if index >= MAX_FINISHED_TURNS
            or now - (turn.finished_at or now) > FINISHED_TTL_S
        }
        for turn_id in retire:
            turn = self._turns.pop(turn_id, None)
            if turn is None:
                continue
            if self._by_sid.get(turn.sid) == turn_id:
                self._by_sid.pop(turn.sid, None)
            if turn.stored_sid and self._by_stored.get(turn.stored_sid) == turn_id:
                self._by_stored.pop(turn.stored_sid, None)
            if turn.request_id and self._by_request.get(turn.request_id) == turn_id:
                self._by_request.pop(turn.request_id, None)

    def find(self, *, turn_id: str = "", sid: str = "", stored_sid: str = "",
             request_id: str = "", active_only: bool = False) -> HermesTurn | None:
        self._prune()
        found = turn_id or self._by_sid.get(sid, "") or self._by_stored.get(stored_sid, "") \
            or self._by_request.get(request_id, "")
        turn = self._turns.get(found)
        if active_only and (turn is None or turn.state != "running"):
            return None
        return turn

    def start(self, *, sid: str, stored_sid: str, request_id: str, user: str,
              image_name: str, producer: AsyncIterator[str],
              seed: dict | None = None) -> HermesTurn:
        self._prune()
        existing = self.find(request_id=request_id) if request_id else None
        if existing is not None:
            return existing
        active = self.find(sid=sid, active_only=True)
        if active is not None:
            raise RuntimeError("that Hermes session already has a running turn")
        active_count = sum(turn.state == "running" for turn in self._turns.values())
        if active_count >= MAX_ACTIVE_TURNS:
            raise RuntimeError("Hermes is already running the maximum number of "
                               "bridge-owned turns; wait for one to finish")
        turn = HermesTurn(
            id=uuid.uuid4().hex, sid=sid, stored_sid=stored_sid,
            request_id=request_id, user=str(user)[:MAX_TURN_USER_CHARS],
            image_name=str(image_name)[:200], seed=_bounded_seed(seed),
        )
        self._turns[turn.id] = turn
        self._by_sid[sid] = turn.id
        if stored_sid:
            self._by_stored[stored_sid] = turn.id
        if request_id:
            self._by_request[request_id] = turn.id
        task = asyncio.create_task(self._collect(turn, producer))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return turn

    def rebind(self, turn: HermesTurn, *, sid: str, stored_sid: str) -> None:
        """Atomically retarget every lookup alias after a stale live-session retry."""
        if self._turns.get(turn.id) is not turn:
            raise RuntimeError("Hermes turn is no longer registered")
        conflict = self.find(sid=sid, active_only=True)
        if conflict is not None and conflict is not turn:
            raise RuntimeError("replacement Hermes session already has a running turn")
        if self._by_sid.get(turn.sid) == turn.id:
            self._by_sid.pop(turn.sid, None)
        if turn.stored_sid and self._by_stored.get(turn.stored_sid) == turn.id:
            self._by_stored.pop(turn.stored_sid, None)
        turn.sid = sid
        turn.stored_sid = stored_sid
        self._by_sid[sid] = turn.id
        if stored_sid:
            self._by_stored[stored_sid] = turn.id

    async def _collect(self, turn: HermesTurn, producer: AsyncIterator[str]) -> None:
        state, error = "completed", ""
        saw_done, reported_error = False, False
        try:
            async with aclosing(producer):
                async for frame in producer:
                    # Producers emit complete panel frames, not network chunks.
                    # Hold the terminator until their cleanup has finished.
                    data = frame[5:].strip() if frame.startswith("data:") else ""
                    if data == "[DONE]":
                        saw_done = True
                        continue
                    try:
                        payload = json.loads(data)
                    except (TypeError, ValueError):
                        payload = None
                    if isinstance(payload, dict) and payload.get("type") == "proxy_error":
                        state, error = "failed", str(payload.get("error") or "Hermes turn failed")[:300]
                        reported_error = True
                    await turn.append(frame)
            if not saw_done and not error:
                state, error = "failed", "Hermes relay ended without a completion event"
        except asyncio.CancelledError:
            state, error = "interrupted", "bridge shutdown"
            raise
        except Exception as exc:
            state, error = "failed", str(exc)[:300]
        finally:
            if error and not reported_error:
                await turn.append("data: " + json.dumps({
                    "type": "proxy_error", "error": error}) + "\n\n")
            await turn.append("data: [DONE]\n\n")
            await turn.finish(state, error)
            self._prune()


HERMES_TURNS = HermesTurnStore()
