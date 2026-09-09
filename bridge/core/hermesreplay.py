"""Redacted Hermes reconnect buffering and bridge-restart following."""
from __future__ import annotations

import asyncio
from collections import deque
import json
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

HERMES_IMAGE_MAX_CHARS = 12 * 1024 * 1024
REPLAY_TEXT_MAX = 16 * 1024
REPLAY_FIELD_MAX = 4096
REPLAY_LIST_MAX = 32

# The WebSocket gap cache is deliberately much smaller than a turn buffer.  It
# only covers the race between a marked ``session.resume`` response and the
# subscriber opening its queue; Hermes's stored transcript remains the recovery
# authority.  The limits are enforced by _HermesWS, including a global cap.
HERMES_WS_REPLAY_MAX_SESSIONS = 16
HERMES_WS_REPLAY_MAX_EVENTS_PER_SESSION = 128
HERMES_WS_REPLAY_PER_SESSION_BYTES = 256 * 1024
HERMES_WS_REPLAY_TOTAL_BYTES = 2 * 1024 * 1024
HERMES_LIVE_QUEUE_MAX_EVENTS = 32
HERMES_LIVE_QUEUE_MAX_BYTES = 2 * 1024 * 1024
HERMES_LIVE_EVENT_MAX_BYTES = 256 * 1024
HERMES_QUEUE_OVERFLOW_ERROR = (
    "Hermes event delivery exceeded the bridge safety bound; interruption was "
    "requested — reopen the session to verify its final state"
)


def replay_event_bytes(event: dict) -> int:
    """Exact UTF-8 payload cost used for the bridge's reconnect gap cache."""
    return len(json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


class HermesGapCache:
    """Small, byte-bounded cache for the resume-to-subscribe WebSocket race.

    It holds only the safe event projection.  A cache miss is not transcript loss:
    callers recover durable text and current state from Hermes itself.
    """

    def __init__(self, *, max_sessions: int = HERMES_WS_REPLAY_MAX_SESSIONS,
                 max_events_per_session: int = HERMES_WS_REPLAY_MAX_EVENTS_PER_SESSION,
                 per_session_bytes: int = HERMES_WS_REPLAY_PER_SESSION_BYTES,
                 total_bytes: int = HERMES_WS_REPLAY_TOTAL_BYTES) -> None:
        self.max_sessions = max(1, int(max_sessions))
        self.max_events_per_session = max(1, int(max_events_per_session))
        self.per_session_bytes = max(1, int(per_session_bytes))
        self.total_limit_bytes = max(1, int(total_bytes))
        self._rows: dict[str, deque[tuple[int, dict, int]]] = {}
        self._bytes: dict[str, int] = {}
        self.total_bytes = 0

    def _discard(self, sid: str) -> None:
        self._rows.pop(sid, None)
        self.total_bytes -= self._bytes.pop(sid, 0)
        self.total_bytes = max(0, self.total_bytes)

    def append(self, sid: str, wire_seq: int, event: dict) -> None:
        """Append if it fits; evict old gap data before accepting new data."""
        cost = replay_event_bytes(event)
        if cost > self.per_session_bytes or cost > self.total_limit_bytes:
            return
        rows = self._rows.get(sid)
        if rows is None:
            while len(self._rows) >= self.max_sessions:
                self._discard(next(iter(self._rows)))
            rows = deque()
            self._rows[sid] = rows
            self._bytes[sid] = 0
        else:
            # Dict insertion order doubles as LRU order.
            self._rows.pop(sid)
            self._rows[sid] = rows
        while rows and (len(rows) >= self.max_events_per_session
                        or self._bytes[sid] + cost > self.per_session_bytes):
            _seq, _event, removed = rows.popleft()
            self._bytes[sid] -= removed
            self.total_bytes -= removed
        # The active sid is at the tail.  Prefer evicting old sessions, but when
        # an intentionally tiny configured global cap requires it, trim this
        # sid's oldest race events too rather than violating the byte limit.
        while self.total_bytes + cost > self.total_limit_bytes and self._rows:
            oldest = next(iter(self._rows))
            if oldest != sid:
                self._discard(oldest)
            elif rows:
                _seq, _event, removed = rows.popleft()
                self._bytes[sid] -= removed
                self.total_bytes -= removed
            else:
                return
        rows.append((wire_seq, event, cost))
        self._bytes[sid] += cost
        self.total_bytes += cost

    def after(self, sid: str, wire_seq: int) -> list[dict]:
        """Return safe events strictly after the caller's marked RPC boundary."""
        return [event for seq, event, _cost in self._rows.get(sid, ()) if seq > wire_seq]

    @property
    def session_count(self) -> int:
        return len(self._rows)


class HermesLiveQueue:
    """One bounded raw-event delivery queue for a live Hermes session.

    Raw gateway events must remain available to the live mapper, unlike the safe
    reconnect cache. If a slow subscriber or hostile payload would exceed either
    bound, pending raw events are discarded as a unit and replaced by one small,
    user-visible terminal sentinel. The caller interrupts that one upstream
    session after reading the sentinel; no RPC is ever made by the WS read loop.
    """

    def __init__(self, *, max_events: int = HERMES_LIVE_QUEUE_MAX_EVENTS,
                 max_bytes: int = HERMES_LIVE_QUEUE_MAX_BYTES,
                 max_event_bytes: int = HERMES_LIVE_EVENT_MAX_BYTES) -> None:
        self.max_events = max(1, int(max_events))
        self.max_bytes = max(1, int(max_bytes))
        self.max_event_bytes = max(1, int(max_event_bytes))
        self._queue: asyncio.Queue = asyncio.Queue()
        self.pending_events = 0
        self.pending_bytes = 0
        self.closed = False

    def _replace_with_terminal(self, kind: str, error: str = "") -> None:
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.pending_events = 0
        self.pending_bytes = 0
        self.closed = True
        payload = {"error": error} if error else {}
        self._queue.put_nowait(({"type": kind, "payload": payload}, 0))

    def offer(self, event: dict) -> bool:
        """Accept one raw event, or replace delivery with an overflow sentinel."""
        if self.closed:
            return False
        cost = replay_event_bytes(event)
        if (cost > self.max_event_bytes or self.pending_events >= self.max_events
                or self.pending_bytes + cost > self.max_bytes):
            self._replace_with_terminal("_queue_overflow", HERMES_QUEUE_OVERFLOW_ERROR)
            return False
        self._queue.put_nowait((event, cost))
        self.pending_events += 1
        self.pending_bytes += cost
        return True

    def request_stop(self) -> None:
        """A user Stop supersedes queued raw events and wakes the live relay."""
        if not self.closed:
            self._replace_with_terminal("_stop_requested")

    def connection_lost(self) -> None:
        if not self.closed:
            self._replace_with_terminal("_ws_closed")

    def close(self) -> None:
        self.closed = True

    async def get(self) -> dict:
        event, cost = await self._queue.get()
        if cost:
            self.pending_events -= 1
            self.pending_bytes -= cost
        return event


def hermes_sessions_normalize(rows):
    """Gateway session.list rows -> stable panel rail rows."""
    from datetime import datetime, timezone
    out = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id") or "").strip()
        if not rid:
            continue
        iso = ""
        try:
            stamp = float(row.get("started_at") or 0)
            if stamp > 1e12:
                stamp /= 1000.0
            if stamp > 0:
                iso = datetime.fromtimestamp(stamp, timezone.utc).isoformat()
        except Exception:
            pass
        try:
            count = int(row.get("message_count") or 0)
        except Exception:
            count = 0
        title = str(row.get("title") or "").strip()
        preview = str(row.get("preview") or "").strip()
        out.append({"id": rid, "name": title or preview or "Untitled",
                    "updated_at": iso, "message_count": count,
                    "source": str(row.get("source") or "")})
    return out


def hermes_attach_error(image) -> str:
    """Why a staged image cannot ride Hermes; empty means it can."""
    if not image:
        return ""
    if not isinstance(image, str) or not image.startswith("data:image/"):
        return "attachment is not an image data URL — attach removed"
    if len(image) > HERMES_IMAGE_MAX_CHARS:
        return "image too large — attach removed"
    return ""


def safe_replay_event(event: dict) -> dict | None:
    """Keep only fields the panel mapper consumes; never cache raw tool results."""
    kind = str((event or {}).get("type") or "")
    payload = (event or {}).get("payload")
    payload = payload if isinstance(payload, dict) else {}
    allowed = {
        "message.delta": ("text",), "reasoning.delta": ("text",),
        "thinking.delta": ("text",), "tool.start": ("name",),
        "approval.request": ("command", "description", "choices"),
        "clarify.request": ("request_id", "question", "choices", "multi_select"),
        "clarify.expire": ("request_id",),
        "message.complete": ("status", "error"),
        "error": ("message", "error"), "status.update": ("kind", "text"),
    }
    if kind == "tool.complete":
        safe = {key: payload.get(key) for key in ("name", "summary") if key in payload}
        result = payload.get("result")
        if isinstance(result, dict):
            reduced = {key: result.get(key) for key in
                       ("error", "files_modified", "resolved_path") if key in result}
            if reduced:
                safe["result"] = reduced
        args = payload.get("args")
        if isinstance(args, dict) and args.get("path"):
            safe["args"] = {"path": str(args["path"])[:4096]}
    elif kind in allowed:
        safe = {key: payload.get(key) for key in allowed[kind] if key in payload}
    else:
        return None
    for key in ("text", "command", "description", "question", "message", "error",
                "name", "summary", "request_id", "status", "kind"):
        if key in safe:
            safe[key] = str(safe[key])[:(REPLAY_TEXT_MAX if key == "text"
                                        else REPLAY_FIELD_MAX)]
    if "choices" in safe:
        choices = safe["choices"] if isinstance(safe["choices"], list) else []
        safe["choices"] = [str(value)[:REPLAY_FIELD_MAX]
                           for value in choices[:REPLAY_LIST_MAX]]
    if isinstance(safe.get("result"), dict):
        result = safe["result"]
        for key in ("error", "resolved_path"):
            if key in result:
                result[key] = str(result[key])[:REPLAY_FIELD_MAX]
        files = result.get("files_modified")
        result["files_modified"] = ([str(value)[:REPLAY_FIELD_MAX]
                                      for value in files[:REPLAY_LIST_MAX]]
                                     if isinstance(files, list) else [])
    return {"type": kind, "session_id": str((event or {}).get("session_id") or ""),
            "payload": safe}


@dataclass(frozen=True)
class ResumeFollowPolicy:
    gateway: Any
    max_turn: float
    segment_spent: Callable[..., float]
    segment_overrun: Callable[[float, float], bool]
    overrun_error: Callable[[float], str]
    kill_segment: Callable[[str, float, float], Awaitable[None]]
    session_working: Callable[[str], Awaitable[bool]]
    segment_resets: Callable[[Any], bool]
    event_to_frames: Callable[[Any], tuple[list, str]]
    guard_audit: Callable[[str, str, str, str], None]
    interrupt_overflow: Callable[[str], Awaitable[None]]
    stored_sid: str


async def follow_resumed_turn(sid: str, after_wire_seq: int, pending: bool,
                              policy: ResumeFollowPolicy):
    """Follow without submitting; restart the unknown segment clock at attach."""
    queue = policy.gateway.open_queue(sid, after_seq=after_wire_seq)
    waiting = bool(pending)
    try:
        started = asyncio.get_running_loop().time()
        paused_since = started if waiting else None
        paused_total = 0.0
        stop_at = None
        while True:
            try:
                timeout = (max(0.25, stop_at - asyncio.get_running_loop().time())
                           if stop_at is not None else 20.0)
                event = await asyncio.wait_for(queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                if stop_at is not None:
                    yield f'data: {json.dumps({"delta": chr(10) + "· interrupted"})}\n\n'
                    break
                yield 'data: {"type":"hermes_ping"}\n\n'
                now = asyncio.get_running_loop().time()
                spent = policy.segment_spent(now, started, paused_total, paused_since)
                if policy.segment_overrun(spent, policy.max_turn):
                    await policy.kill_segment(sid, spent, policy.max_turn)
                    error = policy.overrun_error(policy.max_turn)
                    yield f'data: {json.dumps({"type": "proxy_error", "error": error})}\n\n'
                    break
                if not waiting and not await policy.session_working(sid):
                    break
                continue
            if (event or {}).get("type") == "_stop_requested":
                if stop_at is None:
                    stop_at = asyncio.get_running_loop().time() + 3.0
                continue
            if (event or {}).get("type") == "_queue_overflow":
                yield f'data: {json.dumps({"type": "proxy_error", "error": HERMES_QUEUE_OVERFLOW_ERROR})}\n\n'
                await policy.interrupt_overflow(sid)
                break
            was_waiting = waiting
            waiting = ((event or {}).get("type")
                       in ("approval.request", "clarify.request"))
            now = asyncio.get_running_loop().time()
            resolved = False
            if waiting and not was_waiting:
                paused_since = now
            elif was_waiting and not waiting:
                if paused_since is not None:
                    paused_total += max(0.0, now - paused_since)
                    paused_since = None
                resolved = True
            if resolved or policy.segment_resets((event or {}).get("type")):
                started, paused_total = now, 0.0
            frames, action = policy.event_to_frames(event)
            for frame in frames:
                if frame.get("type") == "file_card":
                    path = str(frame.get("path") or "")
                    if path.startswith("~"):
                        frame["path"] = os.path.expanduser(path)
                elif frame.get("type") == "guard_flag":
                    policy.guard_audit(str(frame.get("path") or ""),
                                       str(frame.get("tool") or ""), sid,
                                       policy.stored_sid)
                yield f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"
            if action == "done":
                break
        yield "data: [DONE]\n\n"
    finally:
        policy.gateway.close_queue(sid)
