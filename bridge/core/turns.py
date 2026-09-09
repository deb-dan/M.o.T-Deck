"""Bridge-owned turn buffers for first-party Chat and Agent streams.

The bridge process, not a WebView response, owns each producer. Public SSE frames are
kept in bounded memory so a lane switch or panel reload can replay them. Durable chat
history stays with Odysseus/Hermes; tool output and prompts are never copied to a new
on-disk journal. A bridge restart therefore interrupts generation honestly instead of
claiming that a task can survive the process that owns its network connection.
"""
from __future__ import annotations

import asyncio
import codecs
from contextlib import aclosing
import json
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable


TERMINAL = frozenset({"completed", "failed", "stopped", "interrupted"})
MAX_TERMINAL_TURNS = 500
MAX_TERMINAL_AGE = 7 * 86400
MAX_EVENTS_PER_TURN = 20_000
MAX_EVENT_BYTES_PER_TURN = 8 * 1024 * 1024
MAX_STORE_EVENT_BYTES = 32 * 1024 * 1024
MAX_ACTIVE_TURNS = 8
TERMINAL_RESERVE_BYTES = 4096
# Two SSE line endings, without misreading one CRLF as CR + LF. The explicit mixed
# cases matter when a proxy normalizes only one side of the blank line.
SSE_BOUNDARY = re.compile(
    r"\r\n\r\n|\r\n\n|\r\n\r|\n\r\n|\n\n|\n\r|\r\r\n|\r\r")
SSE_LINE = re.compile(r"\r\n|\r|\n")


class TurnConflict(RuntimeError):
    def __init__(self, turn_id: str):
        super().__init__(turn_id)
        self.turn_id = turn_id


class TurnOverflow(RuntimeError):
    pass


@dataclass
class Turn:
    id: str
    request_id: str
    lane: str
    session: str
    state: str
    created_at: float
    updated_at: float
    error: str = ""
    next_seq: int = 1
    event_bytes: int = 0
    events: list[tuple[int, dict[str, Any]]] = field(default_factory=list)
    task: asyncio.Task | None = None
    subscribers: int = 0


class TurnStore:
    """One in-process owner for producers, replay buffers, and subscriber wakeups."""

    def __init__(self) -> None:
        # One Condition is both the state lock and a notify-all channel. Subscribers
        # wait on their own cursor; nobody clears shared state, so one subscriber
        # cannot consume another subscriber's wake-up.
        self._changed = asyncio.Condition()
        self._turns: dict[str, Turn] = {}
        self._requests: dict[tuple[str, str, str], str] = {}
        self._event_bytes = 0
        # A browser marker may outlive this process. It can call a missing turn an
        # interruption only when this nonce changed; a record pruned by the same
        # process is not evidence of a restart.
        self.instance_id = secrets.token_urlsafe(18)

    @staticmethod
    def _public(turn: Turn) -> dict[str, Any]:
        return {name: getattr(turn, name) for name in (
            "id", "state", "lane", "session", "created_at", "updated_at", "error")}

    def _drop_locked(self, turn: Turn) -> None:
        removed = self._turns.pop(turn.id, None)
        if removed is not None:
            self._event_bytes = max(0, self._event_bytes - removed.event_bytes)
        self._requests.pop((turn.request_id, turn.lane, turn.session), None)

    def _prune_locked(self, *, required_bytes: int = 0,
                      active_delta: int = 0) -> bool:
        now = time.time()
        terminal = sorted(
            (turn for turn in self._turns.values() if turn.state in TERMINAL),
            key=lambda turn: turn.updated_at,
            reverse=True,
        )
        # An attached response may be between frames when another turn completes.
        # Retain its terminal record until every already-attached subscriber has
        # consumed it; otherwise pruning can turn a successful final frame into an
        # unexplained EOF in the panel. Subscriber-held rows are temporary leases,
        # not an escape from the age/count bound: ``events`` prunes again when the
        # final lease is released.
        keep = ({turn.id for turn in terminal[:MAX_TERMINAL_TURNS]
                 if now - turn.updated_at <= MAX_TERMINAL_AGE}
                | {turn.id for turn in terminal if turn.subscribers})
        for turn in terminal:
            if turn.id in keep:
                continue
            self._drop_locked(turn)

        # Per-turn limits alone still permitted hundreds of multi-megabyte replay
        # buffers. Keep one process-wide encoded-payload budget as well. Active
        # producers and subscriber-leased terminal rows are never evicted: older,
        # unattached terminal rows go first, and a new/expanding turn is refused if
        # those safe evictions cannot make room.
        active_count = sum(turn.state not in TERMINAL for turn in self._turns.values())
        active_count += active_delta
        if active_count > MAX_ACTIVE_TURNS:
            return False
        budget = MAX_STORE_EVENT_BYTES - active_count * TERMINAL_RESERVE_BYTES
        evictable = sorted(
            (turn for turn in self._turns.values()
             if turn.state in TERMINAL and not turn.subscribers),
            key=lambda turn: turn.updated_at,
        )
        while self._event_bytes + required_bytes > budget and evictable:
            stale = evictable.pop(0)
            self._drop_locked(stale)
        return self._event_bytes + required_bytes <= budget

    @staticmethod
    def _validate(body: dict[str, Any]) -> tuple[str, str, str]:
        lane, session, request_id = body.get("lane"), body.get("session"), body.get("request_id")
        if not isinstance(lane, str) or lane not in {"chat", "agent"}:
            raise ValueError("lane must be exactly chat or agent")
        if not isinstance(session, str) or not session.strip():
            raise ValueError("session is required")
        if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 200:
            raise ValueError("request_id is required")
        if not isinstance(body.get("message"), str) or not body["message"].strip():
            raise ValueError("message is required")
        return lane, session, request_id

    async def create(self, body: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        lane, session, request_id = self._validate(body)
        key = (request_id, lane, session)
        async with self._changed:
            self._prune_locked()
            existing_id = self._requests.get(key)
            if existing_id and existing_id in self._turns:
                return self._public(self._turns[existing_id]), False
            active = next((turn for turn in self._turns.values()
                           if turn.session == session
                           and turn.state not in TERMINAL), None)
            if active:
                raise TurnConflict(active.id)
            if not self._prune_locked(active_delta=1):
                raise TurnOverflow(
                    "the bridge replay store is full; wait for another turn to finish and try again")
            now = time.time()
            turn = Turn(secrets.token_urlsafe(24), request_id, lane, session,
                        "queued", now, now)
            self._turns[turn.id] = turn
            self._requests[key] = turn.id
            return self._public(turn), True

    async def metadata(self, turn_id: str) -> dict[str, Any] | None:
        async with self._changed:
            turn = self._turns.get(turn_id)
            return self._public(turn) if turn else None

    async def active(self, lane: str, session: str) -> dict[str, Any] | None:
        if lane not in {"chat", "agent"} or not session:
            raise ValueError("lane and session are required")
        async with self._changed:
            active = [turn for turn in self._turns.values()
                      if turn.lane == lane and turn.session == session
                      and turn.state not in TERMINAL]
            turn = max(active, key=lambda item: item.created_at) if active else None
            return self._public(turn) if turn else None

    async def start(self, turn_id: str,
                    producer: Callable[[], AsyncIterator[str | bytes]]) -> None:
        async with self._changed:
            turn = self._turns.get(turn_id)
            if not turn or turn.state in TERMINAL or turn.task is not None:
                return
            turn.state = "running"
            turn.updated_at = time.time()
            turn.task = asyncio.create_task(self._run(turn_id, producer),
                                             name=f"mot-turn:{turn_id}")
            self._changed.notify_all()

    async def _append(self, turn_id: str, payload: dict[str, Any]) -> None:
        # JSON round-tripping rejects unserialisable/private Python objects and gives
        # the memory bound the exact bytes subscribers will receive.
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        public = json.loads(encoded)
        size = len(encoded.encode("utf-8"))
        async with self._changed:
            turn = self._turns.get(turn_id)
            if not turn or turn.state in TERMINAL:
                return
            if (len(turn.events) >= MAX_EVENTS_PER_TURN
                    or turn.event_bytes + size > MAX_EVENT_BYTES_PER_TURN):
                raise TurnOverflow("the turn exceeded the bridge replay limit")
            if not self._prune_locked(required_bytes=size):
                raise TurnOverflow("the bridge replay store reached its process-wide limit")
            turn.events.append((turn.next_seq, public))
            turn.next_seq += 1
            turn.event_bytes += size
            self._event_bytes += size
            turn.updated_at = time.time()
            self._changed.notify_all()

    async def _terminal(self, turn_id: str, state: str, error: str = "") -> bool:
        if state not in TERMINAL:
            raise ValueError("invalid terminal state")
        async with self._changed:
            turn = self._turns.get(turn_id)
            if not turn or turn.state in TERMINAL:
                return False
            payload: dict[str, Any] = {"type": "terminal", "state": state}
            if error:
                payload["error"] = error
            encoded_size = len(json.dumps(payload, separators=(",", ":")).encode())
            # Every active turn reserves enough room for this terminal record when it
            # is created. This capacity check may evict only unattached old terminals;
            # it can never spend a connected subscriber's final frame.
            if (encoded_size > TERMINAL_RESERVE_BYTES
                    or not self._prune_locked(required_bytes=encoded_size,
                                              active_delta=-1)):
                payload = {"type": "terminal", "state": "failed",
                           "error": "the bridge replay store exhausted its terminal reserve"}
                encoded_size = len(json.dumps(payload, separators=(",", ":")).encode())
                # The production reserve is deliberately larger than the bounded
                # fallback. Re-check the accounting invariant rather than appending a
                # terminal record that the store has no capacity to retain.
                if (encoded_size > TERMINAL_RESERVE_BYTES
                        or not self._prune_locked(required_bytes=encoded_size,
                                                  active_delta=-1)):
                    raise RuntimeError("the bridge terminal reserve invariant failed")
                state = "failed"
            turn.events.append((turn.next_seq, payload))
            turn.next_seq += 1
            turn.event_bytes += encoded_size
            self._event_bytes += encoded_size
            turn.state = str(payload["state"])
            turn.error = str(payload.get("error") or "")
            turn.updated_at = time.time()
            self._prune_locked()
            self._changed.notify_all()
            return True

    async def _run(self, turn_id: str,
                   factory: Callable[[], AsyncIterator[str | bytes]]) -> None:
        saw_done = False
        upstream_error = ""
        unreadable_event = False
        buffer = ""
        decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")

        async def consume_frame(frame: str) -> None:
            nonlocal saw_done, upstream_error, unreadable_event
            event_name = ""
            data_lines = []
            for line in SSE_LINE.split(frame):
                if not line or line.startswith(":"):
                    continue
                field, colon, value = line.partition(":")
                if colon and value.startswith(" "):
                    value = value[1:]
                if field == "event":
                    event_name = value.strip()
                elif field == "data":
                    data_lines.append(value)
            if not data_lines:
                return
            value = "\n".join(data_lines)
            if value.strip() == "[DONE]":
                if event_name == "error":
                    upstream_error = "the upstream agent ended with an error sentinel"
                else:
                    saw_done = True
                return
            try:
                payload = json.loads(value)
                if not isinstance(payload, dict):
                    raise ValueError("event is not an object")
            except (json.JSONDecodeError, ValueError):
                unreadable_event = True
                await self._append(turn_id, {
                    "type": "proxy_error",
                    "error": "the producer emitted an unreadable event",
                })
                return
            if event_name == "error":
                # A named upstream failure wins over any later [DONE] marker.
                reason = payload.get("error") or payload.get("text")
                upstream_error = str(reason or "the upstream agent failed")[:2000]
            else:
                if payload.get("type") == "proxy_error":
                    upstream_error = str(payload.get("error") or "the producer failed")[:2000]
                await self._append(turn_id, payload)

        try:
            async with aclosing(factory()) as producer:
                async for raw in producer:
                    if isinstance(raw, bytes):
                        buffer += decoder.decode(raw, final=False)
                    else:
                        # Producers in this app use bytes or text consistently. Refuse a
                        # text chunk if it would skip an incomplete buffered UTF-8 codepoint.
                        pending, _flag = decoder.getstate()
                        if pending:
                            raise UnicodeDecodeError("utf-8", pending, 0, len(pending),
                                                     "text arrived mid-codepoint")
                        buffer += raw
                    frames = SSE_BOUNDARY.split(buffer)
                    buffer = frames.pop()
                    for frame in frames:
                        await consume_frame(frame)
                        if saw_done:
                            break
                    if saw_done:
                        break
                    # The parsed-event cap cannot protect an unterminated SSE frame.
                    if len(buffer.encode("utf-8")) > MAX_EVENT_BYTES_PER_TURN:
                        raise TurnOverflow("the producer exceeded the incomplete event limit")
            buffer += decoder.decode(b"", final=True)
            if buffer and not saw_done:
                await consume_frame(buffer)
            if upstream_error:
                await self._terminal(turn_id, "failed", upstream_error)
            elif unreadable_event:
                await self._terminal(turn_id, "failed",
                                     "the producer ended with an unreadable event")
            elif saw_done:
                await self._terminal(turn_id, "completed")
            else:
                await self._terminal(turn_id, "failed",
                                     "the producer ended without a completion frame")
        except asyncio.CancelledError:
            # Explicit stop records the terminal frame before cancelling. If shutdown
            # cancels us first, subscribers still receive an honest interruption.
            await self._terminal(turn_id, "interrupted",
                                 "the bridge stopped while this turn was running")
            raise
        except TurnOverflow as exc:
            await self._terminal(turn_id, "failed", str(exc))
        except Exception as exc:  # noqa: BLE001 -- producer boundary must become public state
            await self._terminal(turn_id, "failed",
                                 f"the bridge producer failed: {str(exc)[:200]}")
        finally:
            async with self._changed:
                turn = self._turns.get(turn_id)
                if turn:
                    turn.task = None
                self._changed.notify_all()

    async def stop(self, turn_id: str) -> dict[str, Any] | None:
        async with self._changed:
            turn = self._turns.get(turn_id)
            if not turn:
                return None
            if turn.state in TERMINAL:
                return self._public(turn)
            task = turn.task
        await self._terminal(turn_id, "stopped", "stopped by the user")
        if task and not task.done():
            task.cancel()
        return await self.metadata(turn_id)

    async def subscribe(self, turn_id: str, after: int = 0):
        """Reserve a replay lease now, before an HTTP response starts iterating."""
        cursor = max(0, after)
        async with self._changed:
            turn = self._turns.get(turn_id)
            if not turn:
                return None
            turn.subscribers += 1
        released = False

        async def release() -> None:
            nonlocal released
            async with self._changed:
                if released:
                    return
                released = True
                turn = self._turns.get(turn_id)
                if turn:
                    turn.subscribers = max(0, turn.subscribers - 1)
                self._prune_locked()
                self._changed.notify_all()

        async def stream():
            nonlocal cursor
            try:
                while True:
                    async with self._changed:
                        await self._changed.wait_for(
                            lambda: turn_id not in self._turns
                            or any(seq > cursor for seq, _ in self._turns[turn_id].events)
                            or self._turns[turn_id].state in TERMINAL)
                        turn = self._turns.get(turn_id)
                        if not turn:
                            return
                        rows = [(seq, payload) for seq, payload in turn.events if seq > cursor]
                        terminal = turn.state in TERMINAL
                    for seq, payload in rows:
                        cursor = seq
                        yield {"seq": seq, **payload}
                    if terminal:
                        return
            finally:
                await release()
        return stream(), release

    async def events(self, turn_id: str, after: int = 0) -> AsyncIterator[dict[str, Any]]:
        subscription = await self.subscribe(turn_id, after)
        if subscription is None:
            return
        stream, release = subscription
        try:
            async for event in stream:
                yield event
        finally:
            await stream.aclose()
            await release()


turns = TurnStore()
