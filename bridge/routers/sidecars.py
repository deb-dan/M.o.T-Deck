"""ROUTER — the direct lane's two sidecars: thinking traces and image attachments."""
from __future__ import annotations

import asyncio
import threading
from fastapi.responses import JSONResponse
from ..core.appctx import ROOT, app


# ── Direct-lane thinking sidecar (Fable, 2026-08-06) ─────────────────────────
# The direct chat lane persists only {role, content} to Odysseus (inject_messages),
# so a reopened session loses the turn's thinking. The Hermes lane rehydrates from
# Hermes's own store and the Odysseus agent lane keeps its own — this local sidecar
# gives the DIRECT lane parity.
#
# Keyed by (session id, hash of the assistant answer) rather than a message id:
# inject_messages returns no ids, and the answer text is what the panel renders
# back, so the hash is the only join we own. Same discipline as analytics above:
# one lock, every read/write wrapped — this must NEVER raise into the chat path.
_thinking_lock = threading.Lock()
_thinking_pruned = False   # global retention prune runs once per process


def answer_hash(text: str) -> str:
    """Stable join key: sha1 of the answer's first 2048 characters (utf-8).

    Truncated so a long answer that Odysseus stores/returns with trailing
    differences still matches, and so hashing stays cheap. Pure — unit-tested.
    """
    import hashlib
    return hashlib.sha1((text or "")[:2048].encode("utf-8", "replace")).hexdigest()


def _thinking_conn():
    import sqlite3
    global _thinking_pruned
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(ROOT / "data" / "thinking.db"), timeout=5)
    c.execute("CREATE TABLE IF NOT EXISTS thoughts("
              "sid TEXT, chash TEXT, reasoning TEXT, ts REAL)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_thoughts_sid_chash ON thoughts(sid, chash)")
    if not _thinking_pruned:   # callers already hold _thinking_lock
        _thinking_pruned = True
        try:   # best-effort global cap (mirrors the analytics prune-once pattern)
            c.execute("DELETE FROM thoughts WHERE rowid NOT IN "
                      "(SELECT rowid FROM thoughts ORDER BY ts DESC LIMIT 5000)")
            c.commit()
        except Exception:
            pass
    return c


def log_thinking(sid: str, answer: str, reasoning: str) -> None:
    """Store one direct-lane turn's thinking. Best-effort; never raises."""
    try:
        if not (sid and answer and reasoning):
            return
        import time as _t
        with _thinking_lock:
            c = _thinking_conn()
            c.execute("INSERT INTO thoughts VALUES(?,?,?,?)",
                      (sid, answer_hash(answer), reasoning, _t.time()))
            # Per-session cap: keep the newest 200 rows for this sid.
            c.execute("DELETE FROM thoughts WHERE sid=? AND rowid NOT IN "
                      "(SELECT rowid FROM thoughts WHERE sid=? ORDER BY ts DESC LIMIT 200)",
                      (sid, sid))
            c.commit(); c.close()
    except Exception:
        pass


def _thinking_rows(sid: str) -> list:
    """All (chash, reasoning) rows for a session, oldest first. Never raises."""
    try:
        if not sid:
            return []
        with _thinking_lock:
            c = _thinking_conn()
            rows = c.execute("SELECT chash, reasoning FROM thoughts WHERE sid=? "
                             "ORDER BY ts ASC, rowid ASC", (sid,)).fetchall()
            c.close()
        return [(r[0], r[1]) for r in rows]
    except Exception:
        return []


def _thinking_forget(sid: str) -> None:
    """Drop a deleted session's sidecar rows. Best-effort; never raises."""
    try:
        if not sid:
            return
        with _thinking_lock:
            c = _thinking_conn()
            c.execute("DELETE FROM thoughts WHERE sid=?", (sid,))
            c.commit(); c.close()
    except Exception:
        pass


def attach_thinking(history_rows, thought_rows):
    """PURE: attach stored reasoning to assistant messages, consuming IN ORDER.

    Each stored row is used at most once per response: rows are bucketed by hash
    and popped from the front, so a session that answered the same text twice
    gets its two distinct thinkings back in the order they were produced.
    Malformed rows/messages are skipped — this must never raise.
    """
    try:
        buckets: dict = {}
        for row in (thought_rows or []):
            try:
                h, rsn = row[0], row[1]
            except Exception:
                continue
            if not (h and rsn):
                continue
            buckets.setdefault(str(h), []).append(rsn)
        if not buckets:
            return history_rows
        for m in (history_rows or []):
            try:
                if not isinstance(m, dict) or m.get("role") != "assistant":
                    continue
                if m.get("reasoning"):
                    continue          # never overwrite a lane that already has it
                content = m.get("content")
                if not isinstance(content, str) or not content:
                    continue
                b = buckets.get(answer_hash(content))
                if b:
                    m["reasoning"] = b.pop(0)
            except Exception:
                continue
    except Exception:
        pass
    return history_rows


# ── Direct-lane image sidecar (2026-08-07) ───────────────────────────────────
# Same problem/shape as the thinking sidecar above: the direct lane persists
# {role, content} strings to Odysseus, so an attached image survives a reopen
# only as the "\n[image attached]" marker line. This sidecar keeps the BYTES
# locally (data/attachments.db) keyed by (session id, hash of the user text) and
# re-attaches an {id, name} handle on history read, so the panel can rehydrate
# the same thumbnail it showed at send time.
#
# Discipline is identical: one lock, every read/write wrapped — this must NEVER
# raise into the chat path. Storing bytes rather than the dataURL keeps the file
# ~33% smaller and lets GET /api/attachment/{id} serve it with its real mime.
_attach_lock = threading.Lock()
ATTACH_MAX_ROWS = 300      # global cap (blobs are heavy — far tighter than thinking's 5000)
ATTACH_MARKER = "\n[image attached]"   # appended by chat_direct when persisting the user turn


def user_key(text: str) -> str:
    """Stable join key for a USER turn: sha1 of its first 2048 characters.

    Parallel to answer_hash, with one extra normalization: chat_direct persists
    the user message with ATTACH_MARKER appended, so the string we store at send
    time and the string history hands back differ by exactly that suffix. Strip
    it on both sides and the two always agree. Pure — unit-tested.
    """
    import hashlib
    t = text or ""
    if t.endswith(ATTACH_MARKER):
        t = t[:-len(ATTACH_MARKER)]
    return hashlib.sha1(t[:2048].encode("utf-8", "replace")).hexdigest()


def parse_data_url(s, max_chars: int):
    """PURE: 'data:<mime>;base64,<payload>' → (mime, bytes), else (None, None).

    Total: any malformed / oversize / non-image input yields (None, None) so the
    caller simply skips storing. Never raises.
    """
    try:
        if not isinstance(s, str) or not s.startswith("data:"):
            return (None, None)
        if max_chars and len(s) > max_chars:
            return (None, None)
        head, _, payload = s.partition(",")
        if not payload:
            return (None, None)
        meta = head[5:]                      # drop 'data:'
        if not meta.endswith(";base64"):
            return (None, None)
        mime = meta[:-len(";base64")].strip().lower()
        if not mime.startswith("image/"):
            return (None, None)
        import base64
        raw = base64.b64decode(payload, validate=True)
        if not raw:
            return (None, None)
        return (mime, raw)
    except Exception:
        return (None, None)


def _attach_conn():
    import sqlite3
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(ROOT / "data" / "attachments.db"), timeout=5)
    c.execute("CREATE TABLE IF NOT EXISTS attachments("
              "id INTEGER PRIMARY KEY, ts REAL, sid TEXT, key TEXT, "
              "name TEXT, mime TEXT, bytes BLOB)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_attachments_sid_key ON attachments(sid, key)")
    return c


def log_attachment(sid: str, key: str, name: str, mime: str, blob) -> None:
    """Store one turn's image. Best-effort; never raises."""
    try:
        if not (sid and key and mime and blob):
            return
        import time as _t
        with _attach_lock:
            c = _attach_conn()
            c.execute("INSERT INTO attachments(ts, sid, key, name, mime, bytes) "
                      "VALUES(?,?,?,?,?,?)",
                      (_t.time(), sid, key, (name or "image"), mime, blob))
            # Global retention cap: drop the oldest rows beyond ATTACH_MAX_ROWS.
            c.execute("DELETE FROM attachments WHERE id NOT IN "
                      "(SELECT id FROM attachments ORDER BY ts DESC, id DESC LIMIT ?)",
                      (ATTACH_MAX_ROWS,))
            c.commit(); c.close()
    except Exception:
        pass


def _attachment_rows(sid: str) -> list:
    """All (key, id, name) rows for a session, oldest first. Never raises."""
    try:
        if not sid:
            return []
        with _attach_lock:
            c = _attach_conn()
            rows = c.execute("SELECT key, id, name FROM attachments WHERE sid=? "
                             "ORDER BY ts ASC, id ASC", (sid,)).fetchall()
            c.close()
        return [(r[0], r[1], r[2]) for r in rows]
    except Exception:
        return []


def _attachment_get(aid: int):
    """(name, mime, bytes) for one row, or None. Never raises."""
    try:
        with _attach_lock:
            c = _attach_conn()
            row = c.execute("SELECT name, mime, bytes FROM attachments WHERE id=?",
                            (int(aid),)).fetchone()
            c.close()
        return (row[0], row[1], row[2]) if row else None
    except Exception:
        return None


def _attachment_delete(aid: int) -> bool:
    """Remove one stored image ('remove from the app'). NEVER touches any source
    file on disk — this store is the only copy the harness owns. Never raises."""
    try:
        with _attach_lock:
            c = _attach_conn()
            cur = c.execute("DELETE FROM attachments WHERE id=?", (int(aid),))
            n = cur.rowcount
            c.commit(); c.close()
        return bool(n)
    except Exception:
        return False


def _attachment_forget(sid: str) -> None:
    """Drop a deleted session's stored images. Best-effort; never raises."""
    try:
        if not sid:
            return
        with _attach_lock:
            c = _attach_conn()
            c.execute("DELETE FROM attachments WHERE sid=?", (sid,))
            c.commit(); c.close()
    except Exception:
        pass


def attach_images(history_rows, att_rows):
    """PURE: attach stored image handles to user messages, consuming IN ORDER.

    Mirrors attach_thinking exactly: rows are bucketed by key and popped from the
    front, so a session that sent "test" twice with two different images gets
    them back 1:1 in the order they were sent. Malformed rows/messages are
    skipped — this must never raise.
    """
    try:
        buckets: dict = {}
        for row in (att_rows or []):
            try:
                k, aid, nm = row[0], row[1], row[2]
            except Exception:
                continue
            if not k or aid is None:
                continue
            buckets.setdefault(str(k), []).append((aid, nm))
        if not buckets:
            return history_rows
        for m in (history_rows or []):
            try:
                if not isinstance(m, dict) or m.get("role") != "user":
                    continue
                if m.get("attachment"):
                    continue          # never overwrite an already-populated handle
                content = m.get("content")
                if not isinstance(content, str) or not content:
                    continue
                b = buckets.get(user_key(content))
                if b:
                    aid, nm = b.pop(0)
                    m["attachment"] = {"id": aid, "name": nm or "image"}
            except Exception:
                continue
    except Exception:
        pass
    return history_rows


@app.get("/api/attachment/{aid}")
async def api_attachment(aid: int):
    """Serve one stored image's bytes with its own mime. 404 when it's gone
    (pruned / deleted) so a stale thumbnail simply fails to load."""
    from fastapi.responses import Response
    row = await asyncio.to_thread(_attachment_get, aid)
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    name, mime, blob = row
    return Response(content=blob, media_type=mime or "application/octet-stream",
                    headers={"Cache-Control": "private, max-age=3600"})


@app.post("/api/attachment/{aid}/delete")
async def api_attachment_delete(aid: int) -> JSONResponse:
    """'Remove this image from the app' — drops the sidecar row only. The user's
    original file on disk is never read again and never touched."""
    ok = await asyncio.to_thread(_attachment_delete, aid)
    return JSONResponse({"ok": ok})
