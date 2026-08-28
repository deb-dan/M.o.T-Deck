"""ROUTER — the Hermes chat lane: the shared WebSocket, the SSE frame mapping, sessions.

Also carries the PATH-GUARD audit tier and the MAX-TURN-TIME budget, both of which
exist only for this lane.
"""
from __future__ import annotations

import asyncio
import os
import yaml
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from ..core.appctx import ROOT, _office_ops, app
from ..core.hermescfg import _hermes_port, _hermes_token
from ..core.procs import cfg
from .hermestools import HERMES_SESSION_SOURCE


# ── Hermes chat lane (Phase 1) — the dashboard's /api/ws JSON-RPC gateway re-emitted
#    as panel SSE (FABLE-HERMES-LANE-SPEC, PATH A). ONE shared WebSocket, multiplexed
#    by session_id; token deltas / thinking / tool events map onto the SAME frame
#    shapes the panel's existing stream renderer already handles; approvals
#    (Phase 2) surface as an interactive panel card answered via
#    POST /api/hermes/approve → approval.respond.
#    ⚠ The /api/ws protocol is upstream-INTERNAL (no stability promise) —
#    bridge/contract_tests/test_hermes_ws_contract.py gates every Hermes pin-bump
#    on the exact method/event names used below.
try:
    import websockets  # bridge/requirements.txt — used ONLY by this lane
except Exception:      # missing dep degrades the lane with a clear error, never the bridge
    websockets = None




# ── PATH-GUARD audit tier (C) ────────────────────────────────────────────────
# Detect-only twin of the guards/harness-path-guard plugin (B1 = the enforcement).
# The plugin can be disabled or misconfigured in ~/.hermes; this tier reads the
# SAME policy roots straight from the repo and flags any COMPLETED write that
# landed outside the allowlist, so the panel shows a faint warning line even when
# the fence is off. Deny roots are irrelevant here (a deny is never written).
_GUARD_ROOTS: list | None = None


def _guard_allow_roots() -> list:
    """Resolved allow roots from guards/harness-path-guard/policy.yaml (cached).

    Placeholders resolve the same way the plugin resolves them: {HARNESS_ROOT} =
    this repo, {TMPDIR} = env, {HERMES_CWD} = the bridge's cwd — which IS the
    Hermes launch cwd (start_component.sh runs both from the repo root).
    ⚠ PENDING FABLE QA: if Hermes is ever launched from a different cwd than the
    bridge, this tier's workspace root drifts (it would over-flag, never under-flag).
    """
    global _GUARD_ROOTS
    if _GUARD_ROOTS is not None:
        return _GUARD_ROOTS
    roots: list = []
    try:
        pol = yaml.safe_load(
            (ROOT / "guards" / "harness-path-guard" / "policy.yaml").read_text()) or {}
        raw = pol.get("allow") if isinstance(pol.get("allow"), list) else []
        home = os.path.expanduser("~")
        subs = {"{HARNESS_ROOT}": str(ROOT), "{TMPDIR}": os.environ.get("TMPDIR", ""),
                "{HERMES_CWD}": os.getcwd()}
        for entry in raw:
            r = str(entry or "").strip()
            if not r:
                continue
            bad = False
            for token, value in subs.items():
                if token in r:
                    if not value:
                        bad = True
                        break
                    r = r.replace(token, value)
            if bad or "{" in r:
                continue
            if r.startswith("~"):
                r = home + r[1:] if r == "~" or r.startswith("~/") else os.path.expanduser(r)
            if not os.path.isabs(r):
                continue
            roots.append(os.path.realpath(r).rstrip(os.sep) or os.sep)
    except Exception as exc:
        print(f"[guard] policy unreadable ({exc}) — audit tier disabled", flush=True)
        roots = []
    _GUARD_ROOTS = roots
    return roots


def guard_path_outside(path: str, roots=None) -> bool:
    """True iff *path* resolves OUTSIDE every allow root (containment via
    commonpath — never string prefixes). Unknown/empty roots → False (the tier
    stays silent rather than crying wolf on every write)."""
    try:
        roots = _guard_allow_roots() if roots is None else roots
        if not roots:
            return False
        p = str(path or "").strip()
        if not p:
            return False
        if p.startswith("~"):
            p = os.path.expanduser(p)
        if not os.path.isabs(p):
            return False       # relative legacy path — cwd unknown here, stay quiet
        t = os.path.realpath(p).rstrip(os.sep) or os.sep
        for r in roots:
            try:
                if os.path.commonpath([t, r]) == r:
                    return False
            except Exception:
                continue
        return True
    except Exception:
        return False


def _guard_flag(path: str, tool: str) -> bool:
    """Audit hook used by the mapper: log ONE warning line and report whether the
    panel should render the faint out-of-workspace notice."""
    if not guard_path_outside(path):
        return False
    print(f"[guard] {tool} wrote OUTSIDE the path-guard allowlist: {path}", flush=True)
    return True


def _guard_audit(path, tool, sid="", stored_sid="") -> None:
    """Durable audit trail: one JSON line per flagged write in data/logs/guard.log.

    The python-log warning above is transient (rotates with bridge.log noise) and
    the SSE guard_flag frame is gone on reload; this file is what the Logs pane's
    `path-guard` source reads. Best-effort — an audit write must NEVER affect the
    stream.
    """
    try:
        import json as _json, datetime as _dt
        d = ROOT / "data" / "logs"
        d.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "path": str(path or ""), "tool": str(tool or ""), "sid": str(sid or ""),
        }
        # The live gateway sid dies with the session; the STORED id is what the
        # panel's rail can reopen — recorded when the panel supplies it, so an
        # audit entry can jump back to the exact conversation.
        if stored_sid:
            rec["stored_sid"] = str(stored_sid)
        line = _json.dumps(rec, ensure_ascii=False)
        with open(d / "guard.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def hermes_event_to_frames(ev):
    """PURE mapper: one Hermes gateway event → (panel SSE frame dicts, action).

    action: "" = keep streaming, "done" = the turn is over (caller emits [DONE]).
    Stays pure so it can be unit-tested standalone (bridge/tests/
    test_hermes_sse_map.py extracts it by ast; keep it dependency-free).
    Malformed events must NEVER raise.
    """
    try:
        t = (ev or {}).get("type") or ""
        p = (ev or {}).get("payload")
        if not isinstance(p, dict):
            p = {}
        if t == "message.delta":
            txt = p.get("text") or ""
            return ([{"delta": txt}] if txt else [], "")
        if t in ("reasoning.delta", "thinking.delta"):
            txt = p.get("text") or ""
            return ([{"delta": txt, "thinking": True}] if txt else [], "")
        if t == "tool.start":
            return ([{"type": "tool_start", "tool": p.get("name") or "tool"}], "")
        if t == "tool.complete":
            # Slim: never forward the (potentially huge) raw result to the panel.
            fr = {"type": "tool_output", "tool": p.get("name") or "tool"}
            if p.get("summary"):
                fr["summary"] = p.get("summary")
            # ⚠️ A TOOL THAT FAILED MUST NOT ARRIVE LOOKING LIKE A TOOL THAT WORKED,
            # and that silence is half of the 2026-08-27 consent incident: a write
            # returned an error, the panel rendered nothing, and the model's "Done"
            # stood unchallenged. Every failure path lands in the same shape — Hermes's
            # own tool_error() returns `{"error": …}` (tools/registry.py:1282) and an
            # MCP result with isError:true is converted to exactly that
            # (tools/mcp_tool.py:5442-5456) — so ONE test on the parsed result covers
            # native tools and every MCP server alike. The panel renders it as a red ✗
            # chip carrying the tool's own sentence.
            _res = p.get("result")
            _err_text = ""
            if isinstance(_res, dict) and _res.get("error"):
                _err_text = str(_res.get("error"))
            elif isinstance(_res, str) and _res.lstrip().startswith('{"error"'):
                # The import is INSIDE the branch on purpose: this function is
                # ast-extracted into a bare namespace by bridge/tests/
                # test_hermes_sse_map.py, so it must not lean on a module-level alias.
                try:
                    import json as _j
                    _err_text = str((_j.loads(_res) or {}).get("error") or "")
                except Exception:                                # noqa: BLE001
                    _err_text = ""
            # ⚠️ AND ONE UNWRAP, MEASURED ON THE REAL LANE. An MCP tool's refusal arrives
            # DOUBLE-ENCODED: our server answers isError with a JSON body of its own
            # ({"ok": false, "error": "…"}), Hermes reads the text off the content block
            # and hands it to tool_error(), which wraps it AGAIN — so `result.error` is a
            # JSON string, and the panel's ✗ chip rendered as a wall of braces (seen live,
            # 2026-08-28). One unwrap turns it back into the tool's own sentence, which is
            # the entire point of showing the chip.
            if _err_text.lstrip().startswith("{"):
                try:
                    import json as _j2
                    _inner = _j2.loads(_err_text)
                    if isinstance(_inner, dict) and _inner.get("error"):
                        _err_text = str(_inner["error"])
                except Exception:                                # noqa: BLE001
                    pass
            if _err_text:
                fr["is_error"] = True
                fr["error"] = _err_text[:600]
            frames = [fr]
            # §F file cards: a SUCCESSFUL write_file/patch also emits one
            # file_card frame per file touched, so the panel can render a
            # produced-file card (Open / Show in Folder via /api/open).
            # tool.complete payload (tui_gateway/server.py:5044-5088):
            # {tool_id, name, args, result(json-parsed when possible), summary?}.
            # Success = result is a dict WITHOUT "error" (file_tools.py returns
            # json dicts; tool_error always carries "error"). Paths: prefer
            # result.files_modified (ABSOLUTE, file_tools.py:1632/1787 — handles
            # multi-file V4A patches), then result.resolved_path (:1630/1789),
            # then args.path (legacy-resolution fallback :1601-1608 — may be
            # relative/~; forwarded as-is, the relay expands ~ and the panel
            # skips non-absolute ⚠ PENDING FABLE QA). Kept inline (not a helper)
            # so the ast-extracted mapper stays self-contained for the tests.
            if p.get("name") in ("write_file", "patch"):
                res = p.get("result")
                args = p.get("args") if isinstance(p.get("args"), dict) else {}
                if isinstance(res, dict) and not res.get("error"):
                    paths = res.get("files_modified")
                    if not (isinstance(paths, list) and paths):
                        one = res.get("resolved_path") or args.get("path")
                        paths = [one] if one else []
                    seen = set()
                    for fp in paths:
                        fp = str(fp or "").strip()
                        if not fp or fp in seen:
                            continue
                        seen.add(fp)
                        frames.append({"type": "file_card", "path": fp,
                                       "tool": p.get("name")})
                        # Audit tier C: flag a write that landed outside the
                        # path-guard allowlist (detect-only; the plugin enforces).
                        # The inner try keeps the mapper self-contained for the
                        # ast-extracted unit test, where _guard_flag is absent →
                        # NameError → no guard_flag frame (tested separately in
                        # bridge/tests/test_path_guard.py).
                        try:
                            if _guard_flag(fp, p.get("name") or "write"):
                                frames.append({"type": "guard_flag", "path": fp,
                                               "tool": p.get("name")})
                        except Exception:
                            pass
            return (frames, "")
        if t == "approval.request":
            # Phase 2: interactive approval card. NO auto-deny — the relay keeps
            # draining while the panel POSTs /api/hermes/approve → approval.respond.
            # The gateway keys approvals purely by SESSION (FIFO, no request_id on
            # the wire — vendor/hermes/apps/desktop/src/store/prompts.ts:71,
            # tools/approval.py resolve_gateway_approval), so none is forwarded.
            # The command arrives already credential-redacted upstream
            # (tui_gateway/server.py:1592 _emit_approval_request, #48456).
            ch = p.get("choices")
            if not (isinstance(ch, list) and ch):
                # Upstream omits choices only when neither smart_denied nor
                # allow_permanent is set (server.py:1600-1606). Conservative
                # default: never OFFER a persistence scope upstream didn't
                # declare. ⚠ PENDING FABLE QA: ["once","deny"] as the fallback.
                ch = ["once", "deny"]
            # description is forwarded too: for a PLUGIN-escalated approval (the
            # path-guard fence) upstream sets command to the synthetic label
            # "<write_file> (plugin approval rule)" (tools/approval.py
            # request_tool_approval → _run_approval_gate display_target) and puts
            # the real reason — including the target PATH — in description. Without
            # it the card could not show what is being written.
            # ⚠ PENDING FABLE QA: adding description to the existing card (one faint
            # line above the command block), not a new surface.
            return ([{"type": "approval",
                      "request": {"command": p.get("command") or "",
                                  "description": str(p.get("description") or ""),
                                  "choices": [str(c) for c in ch]}}], "")
        if t == "clarify.request":
            # INTERACTIVE ASK CARD (2026-08-14). The `clarify` tool blocks the
            # agent thread on a gateway prompt (tui_gateway/server.py:5376-5390
            # clarify_callback → _block("clarify.request", …)); the payload is
            # {question, choices?, multi_select? (only when True)} plus the
            # request_id _block injects at server.py:2861. Without a surface for
            # it the turn simply sat "working" until something timed out — the
            # exact class approval cards already solved.
            #
            # allows_free_text is ALWAYS true and that is upstream's own rule,
            # not our guess: every renderer appends an "Other (type your answer)"
            # option (tools/clarify_tool.py:22, schema :233), and a clarify with
            # NO choices is open-ended by construction (:157 empty list → None).
            # The answer is a plain STRING either way — the tool returns it
            # verbatim as user_response (clarify_tool.py:170).
            ch = p.get("choices")
            opts = [str(c) for c in ch if str(c or "").strip()] if isinstance(ch, list) else []
            return ([{"type": "ask",
                      "request": {"request_id": str(p.get("request_id") or ""),
                                  "question": str(p.get("question") or ""),
                                  "options": opts,
                                  "multi_select": bool(p.get("multi_select")),
                                  "allows_free_text": True}}], "")
        if t == "clarify.expire":
            # Upstream gave up waiting (server.py:2886-2896 emits `<x>.expire`
            # for every blocking bridge whose respond tolerates a late reply).
            # The card must stop pretending it is still answerable.
            return ([{"type": "ask_expire",
                      "request_id": str(p.get("request_id") or "")}], "")
        if t == "message.complete":
            # Final text is NOT re-emitted — the deltas already built the bubble.
            # ANY message.complete ends the turn: complete / error / interrupted
            # (Phase 1.1 — a dashboard-side interrupt emits status:"interrupted";
            # the panel turn must end, with a short in-stream note).
            if (p.get("status") == "error") or p.get("error"):
                return ([{"type": "proxy_error",
                          "error": str(p.get("error") or "turn failed")[:300]}], "done")
            if p.get("status") == "interrupted":
                return ([{"delta": "\n· interrupted"}], "done")
            return ([], "done")
        if t == "error":
            return ([{"type": "proxy_error",
                      "error": str(p.get("message") or p.get("error")
                                   or "hermes error")[:300]}], "done")
        if t == "_ws_closed":
            # Adapter-injected close sentinel — the shared WS died mid-turn.
            return ([{"type": "proxy_error", "error": "Hermes connection lost"}], "done")
        if t == "status.update":
            return ([{"type": "status", "kind": p.get("kind") or "",
                      "text": p.get("text") or ""}], "")
        return ([], "")  # session.info / gateway.ready / unknown — inspect-only noise, drop
    except Exception:
        return ([], "")


class _HermesWS:
    """ONE shared JSON-RPC client over the dashboard's /api/ws WebSocket.

    - lazy connect on first use; reconnect attempts are spaced by a capped backoff
      so a down Hermes can't hot-loop the bridge;
    - RPCs are id-correlated (id → Future);
    - gateway events (method=event) fan out to per-session asyncio.Queues keyed
      by params.session_id;
    - on connection loss every pending RPC fails and every open queue gets the
      {"type": "_ws_closed"} sentinel so relaying turns terminate cleanly.
    """

    def __init__(self) -> None:
        self._ws = None
        self._lock = asyncio.Lock()
        self._pending: dict = {}      # rpc id → Future
        self._queues: dict = {}       # session_id → asyncio.Queue
        self._next_id = 1
        self._backoff = 0.5

    async def _ensure(self) -> None:
        async with self._lock:
            if self._ws is not None:
                return
            if websockets is None:
                raise RuntimeError("websockets not installed in the bridge venv "
                                   "(pip install websockets)")
            tok = _hermes_token()
            if not tok:
                raise RuntimeError("no Hermes dashboard token — start Hermes from "
                                   "the panel first (it mints data/hermes.token)")
            url = f"ws://127.0.0.1:{_hermes_port()}/api/ws?token={tok}"
            try:
                ws = await websockets.connect(url, max_size=32 * 1024 * 1024,
                                              ping_interval=20, ping_timeout=20,
                                              open_timeout=8)
            except Exception as e:
                delay, self._backoff = self._backoff, min(self._backoff * 2, 8.0)
                await asyncio.sleep(delay)
                raise RuntimeError(f"Hermes dashboard unreachable on "
                                   f":{_hermes_port()}/api/ws — {str(e)[:160]}")
            self._backoff = 0.5
            self._ws = ws
            asyncio.get_running_loop().create_task(self._read_loop(ws))

    async def _read_loop(self, ws) -> None:
        try:
            async for raw in ws:
                # Wire = newline-delimited JSON-RPC (identical to Hermes's stdio
                # transport); one WS text message MAY carry a coalesced token batch.
                for line in str(raw).splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        import json as _json
                        obj = _json.loads(line)
                    except Exception:
                        continue
                    if obj.get("method") == "event":
                        prm = obj.get("params") or {}
                        q = self._queues.get(prm.get("session_id") or "")
                        if q is not None:
                            q.put_nowait({"type": prm.get("type"),
                                          "session_id": prm.get("session_id"),
                                          "payload": prm.get("payload")})
                    elif obj.get("id") is not None:
                        fut = self._pending.pop(obj.get("id"), None)
                        if fut is not None and not fut.done():
                            fut.set_result(obj)
        except Exception:
            pass
        finally:
            self._ws = None
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_exception(RuntimeError("Hermes connection lost"))
            self._pending.clear()
            for q in list(self._queues.values()):
                try:
                    q.put_nowait({"type": "_ws_closed"})
                except Exception:
                    pass

    async def rpc(self, method: str, params: dict, timeout: float = 30.0) -> dict:
        import json as _json
        await self._ensure()
        rid = self._next_id
        self._next_id += 1
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            await self._ws.send(_json.dumps({"jsonrpc": "2.0", "id": rid,
                                             "method": method, "params": params}))
            resp = await asyncio.wait_for(fut, timeout)
        except Exception:
            self._pending.pop(rid, None)
            raise
        if resp.get("error"):
            raise RuntimeError(str((resp.get("error") or {}).get("message")
                                   or "hermes rpc error"))
        return resp.get("result") or {}

    def open_queue(self, sid: str) -> "asyncio.Queue":
        q: asyncio.Queue = asyncio.Queue()
        self._queues[sid] = q
        return q

    def close_queue(self, sid: str) -> None:
        self._queues.pop(sid, None)


_HERMES = _HermesWS()


def _hermes_stale_sid(err: Exception) -> bool:
    s = str(err).lower()
    return "session" in s and ("not found" in s or "unknown" in s or "no such" in s)


# ── MAX TURN TIME (2026-08-14) ────────────────────────────────────────────────
# A 4B thinking model can spiral into a deliberation loop that never terminates:
# it keeps EMITTING, so the relay's 20s-silence watchdogs never fire and the only
# remaining bound was the 600s TOTAL-SILENCE hard guard — which such a turn never
# trips either (it is not silent). Even when a guard did fire, only the RELAY gave
# up: Hermes kept generating and kept cooking the CPU. So this guard is armed at
# prompt.submit, measures TOTAL turn time (not silence), is checked on the EVENT
# path as well as on the timeout tick, and its remedy is session.interrupt — it
# kills the GENERATION, not just the stream.
HERMES_MAX_TURN_S_DEFAULT = 600.0


def hermes_max_turn_s(conf) -> float:
    """Resolve `hermes.max_turn_s` (seconds). PURE.

    0 (or negative) = DISABLED. Absent OR unparseable = the 600s default: this is
    a safety guard, so a typo must not silently switch it off — disabling has to be
    a deliberate `0`. Top-level `hermes:` block (NOT components.hermes) because
    ship.sh's manifest merge is additive at the TOP level only: a new sub-key under
    the already-present components.hermes would never reach the app snapshot.
    """
    try:
        h = (conf or {}).get("hermes")
    except Exception:
        return HERMES_MAX_TURN_S_DEFAULT
    if not isinstance(h, dict) or "max_turn_s" not in h:
        return HERMES_MAX_TURN_S_DEFAULT
    v = h.get("max_turn_s")
    if isinstance(v, bool) or v is None:
        return HERMES_MAX_TURN_S_DEFAULT
    try:
        f = float(v)
    except (TypeError, ValueError):
        return HERMES_MAX_TURN_S_DEFAULT
    if f != f or f in (float("inf"), float("-inf")):   # NaN / inf
        return HERMES_MAX_TURN_S_DEFAULT
    return 0.0 if f <= 0 else f


# SEGMENT, NOT TURN (2026-08-14h, Fable revision after Debi's objection): a cap on
# TOTAL turn time punishes exactly the work the harness exists for — a research turn
# that legitimately spends an hour making tool call after tool call. What must be
# bounded is an UNBROKEN GENERATION STRETCH: the model talking to itself with nothing
# to show for it. So the clock is a SEGMENT clock — it restarts every time the turn
# makes visible progress (a tool starts or completes) and every time an interactive
# card is answered — and only one continuous deliberation stretch longer than the
# budget is interrupted. A turn with a tool call every few minutes runs forever.
HERMES_SEGMENT_RESET_EVENTS = ("tool.start", "tool.complete")


def hermes_segment_resets(ev_type) -> bool:
    """PURE. Does this gateway event END the current unbroken-generation segment?

    Deliberately NOT message deltas: a spiralling model emits deltas continuously,
    so resetting on them would make the guard blind to the only failure it exists
    to catch. Tool lifecycle events are the honest "the turn is getting somewhere"
    signal (card resolution is the other, handled by the relay's pause bookkeeping).
    """
    return isinstance(ev_type, str) and ev_type.strip() in HERMES_SEGMENT_RESET_EVENTS


def hermes_segment_spent(now: float, started_at: float,
                         paused_total: float = 0.0, paused_since=None) -> float:
    """Segment time that COUNTS against the budget. PURE.

    Wall clock since the segment began (prompt.submit, or the last reset) MINUS
    every interval spent waiting on an interactive card (approval / clarify): a card
    that legitimately waits for Debi must never be shot. `paused_total` is the sum of
    closed pauses; `paused_since` is the start of the pause still open (None if not
    paused). Never negative.
    """
    spent = float(now) - float(started_at) - float(paused_total or 0.0)
    if paused_since is not None:
        spent -= max(0.0, float(now) - float(paused_since))
    return spent if spent > 0 else 0.0


def hermes_segment_overrun(spent_s: float, budget_s: float) -> bool:
    """Has this generation segment blown its budget? PURE.
    budget <= 0 = disabled = never."""
    try:
        b = float(budget_s)
        s = float(spent_s)
    except (TypeError, ValueError):
        return False
    if not (b > 0):
        return False
    return s >= b


def hermes_overrun_error(budget_s: float) -> str:
    """The exact user-facing line for an over-budget generation segment. PURE."""
    n = int(budget_s) if float(budget_s) == int(float(budget_s)) else float(budget_s)
    return (f"generation exceeded {n}s without a tool call or output — likely a "
            "deliberation loop; interrupted server-side (hermes.max_turn_s)")


async def _hermes_kill_segment(sid: str, spent_s: float, budget_s: float) -> None:
    """Stop the GENERATION for an over-budget segment + leave a durable trace.

    Best-effort by design: whether or not the RPC lands, the relay ends the turn
    (an unreachable gateway is exactly the case where the stream must still close).
    """
    print(f"[hermes] generation segment exceeded max_turn_s "
          f"({spent_s:.0f}s >= {budget_s:.0f}s) "
          f"— sending session.interrupt for {sid or '?'}", flush=True)
    try:
        await _HERMES.rpc("session.interrupt", {"session_id": sid}, timeout=10.0)
        print("[hermes] session.interrupt acknowledged", flush=True)
    except Exception as e:
        print(f"[hermes] session.interrupt FAILED: {str(e)[:200]}", flush=True)


async def _hermes_session_working(sid: str) -> bool:
    """Best-effort probe: is this gateway session still running a turn?

    Uses session.active_list (methods_session.py:942 → _session_live_item,
    server.py:8072, status ∈ waiting/starting/working/idle via _session_live_status,
    server.py:8040). Returns True on ANY doubt — a probe failure must never kill a
    live stream. A session that is absent or "idle" while our relay still waits means
    the turn ended WITHOUT a terminal event reaching us (e.g. interrupted from the
    Hermes dashboard) → the caller ends the turn.

    The status vocabulary is upstream-INTERNAL and a silent addition to it would cut
    live turns off, so it is now contract-pinned as an exact set
    (`test_active_list_status_vocabulary_is_unchanged`), closing the gap this
    docstring used to just flag. Re-verified unchanged at v2026.8.13.
    """
    try:
        res = await _HERMES.rpc("session.active_list", {}, timeout=8.0)
        for row in (res.get("sessions") or []):
            if str(row.get("id") or "") == sid:
                return str(row.get("status") or "") in ("working", "starting", "waiting")
        return False  # gone from the gateway → definitely not running
    except Exception:
        return True


# ── HERMES-LANE IMAGE ATTACH (2026-08-28, the capability-affordance audit) ───
# Hermes's gateway takes an image as BASE64 over the same WebSocket we already
# hold: `image.attach_bytes {session_id, content_base64, filename}` writes the
# bytes into the gateway's own images dir and queues the path on the SESSION
# (tui_gateway/methods_prompt.py:801). The very next `prompt.submit` drains
# `session["attached_images"]` (server.py:9780) and routes it either as native
# image_url parts (vision model) or through vision_analyze for a text-only one
# (agent/image_routing.py). So the panel's data URL crosses UNCHANGED — the helper
# below only fences shape and size before we spend the round trip.
#
# ORDERING IS LOAD-BEARING: the attach must land on the session that is about to be
# prompted, so it happens AFTER session.create — and AGAIN after the stale-sid retry
# mints a NEW session, whose attached_images list is empty.
HERMES_IMAGE_MAX_CHARS = 12 * 1024 * 1024   # dataURL chars (~9MB of image bytes);
                                            # upstream's own cap is 25MB of bytes


def hermes_attach_error(image) -> str:
    """PURE: why this image cannot ride the Hermes lane, or "" when it can.

    Same vocabulary as the other two lanes. No vision clause: Hermes decides
    pixels-vs-description per turn from the active model's own capabilities.
    """
    if not image:
        return ""
    if not isinstance(image, str) or not image.startswith("data:image/"):
        return "attachment is not an image data URL — attach removed"
    if len(image) > HERMES_IMAGE_MAX_CHARS:
        return "image too large — attach removed"
    return ""


@app.post("/api/hermes/chat")
async def hermes_chat(req: Request) -> StreamingResponse:
    """Stream one Hermes turn to the panel as SSE (same protocol as the other lanes).

    Body: {"session_id": <sid or empty>, "message": <text>, "image": <dataURL>}.
    No sid → session.create first, and the NEW sid is announced early via
    {"type":"hermes_session","id":…} so the panel can persist it before any tokens
    arrive. One stale-sid retry.
    """
    body = await req.json()
    sid = (body.get("session_id") or "").strip()
    msg = (body.get("message") or "").strip()
    stored_sid = (body.get("stored_sid") or "").strip()   # durable id, for the guard audit
    image = body.get("image") or ""
    image_name = (body.get("image_name") or "")[:200]

    async def gen():
        import json as _json
        nonlocal sid, stored_sid

        async def _attach_image(target_sid: str) -> str:
            """Queue the staged image on `target_sid`. Returns "" or the reason.

            An image the user attached and Hermes refused must FAIL the turn — never
            be dropped silently and answered as if the message had been plain text.
            That would be a LIE-TO-USER, which outranks a refusal.
            """
            if not image:
                return ""
            try:
                res = await _HERMES.rpc("image.attach_bytes", {
                    "session_id": target_sid,
                    "content_base64": image,
                    "filename": image_name or "image.png"})
            except Exception as e:                        # noqa: BLE001
                return f"hermes refused the image: {str(e)[:180]}"
            if not (res or {}).get("attached"):
                return "hermes did not attach the image (no reason given)"
            return ""

        q = None
        try:
            if not msg:
                yield 'data: {"type":"proxy_error","error":"empty message"}\n\n'
                return
            _imgerr = hermes_attach_error(image)
            if _imgerr:      # shape/size — refuse before creating a session for it
                yield f'data: {_json.dumps({"type": "proxy_error", "error": _imgerr})}\n\n'
                return
            if not sid:
                res = await _HERMES.rpc("session.create", {"source": HERMES_SESSION_SOURCE})
                sid = str(res.get("session_id") or "")
                if not sid:
                    yield 'data: {"type":"proxy_error","error":"session.create returned no id"}\n\n'
                    return
                # stored_id (Phase 3): lets the rail mark the matching stored row.
                stored_sid = stored_sid or str(res.get("stored_session_id") or "")
                yield f'data: {_json.dumps({"type": "hermes_session", "id": sid, "stored_id": str(res.get("stored_session_id") or "")})}\n\n'
            # ⚠️ WHO IS THE OFFICE CHANGESET FOR. An MCP tools/call carries the MCP
            # TRANSPORT's session id, and Hermes keeps ONE MCP client per process, so
            # that id is identical for every conversation and useless as a key. This is
            # the only correlation available: the Hermes session whose turn is running
            # right now. Recorded here (and re-recorded on the retry path below, which
            # mints a new sid), read by office_ops.active_session(). Costs one dict
            # write per turn and is a no-op when the office modules are absent.
            if _office_ops is not None:
                try:
                    _office_ops.mark_session(sid)
                except Exception:                        # noqa: BLE001
                    pass
            # Open the fan-out queue BEFORE submitting so no early event is missed.
            q = _HERMES.open_queue(sid)
            _imgerr = await _attach_image(sid)
            if _imgerr:
                yield f'data: {_json.dumps({"type": "proxy_error", "error": _imgerr})}\n\n'
                return
            try:
                await _HERMES.rpc("prompt.submit", {"session_id": sid, "text": msg})
            except RuntimeError as e:
                if not _hermes_stale_sid(e):
                    raise
                # ONE retry: the persisted sid points at a dead gateway session
                # (dashboard restarted) — mint a fresh one and resubmit.
                _HERMES.close_queue(sid)
                res = await _HERMES.rpc("session.create", {"source": HERMES_SESSION_SOURCE})
                sid = str(res.get("session_id") or "")
                if not sid:
                    raise RuntimeError("session.create returned no id")
                stored_sid = stored_sid or str(res.get("stored_session_id") or "")
                yield f'data: {_json.dumps({"type": "hermes_session", "id": sid, "stored_id": str(res.get("stored_session_id") or "")})}\n\n'
                if _office_ops is not None:
                    try:
                        _office_ops.mark_session(sid)     # the sid changed under us
                    except Exception:                     # noqa: BLE001
                        pass
                q = _HERMES.open_queue(sid)
                # The image was queued on the session that turned out to be dead —
                # this one's attached_images is empty, so re-attach before resubmitting.
                _imgerr = await _attach_image(sid)
                if _imgerr:
                    yield f'data: {_json.dumps({"type": "proxy_error", "error": _imgerr})}\n\n'
                    return
                await _HERMES.rpc("prompt.submit", {"session_id": sid, "text": msg})
            # Relay gateway events until the turn completes. Watchdogs (Phase 1.1):
            #   • first-event: NOTHING within 60s of prompt.submit → end with a clear
            #     error (⚠ PENDING FABLE QA: 60s is a judgment call — local prefill
            #     normally emits status kaomoji well before that);
            #   • liveness: 20s of mid-turn silence → panel-visible "working…" note
            #     (large-prompt prefill on local models reads as dead otherwise) + a
            #     best-effort session.active_list probe — if Hermes says the session
            #     is no longer working, the turn ended without a terminal event
            #     (e.g. interrupted from the dashboard) → end cleanly;
            #   • stop fallback: /api/hermes/stop nudges this queue with a
            #     _stop_requested sentinel; if no terminal event lands within ~3s
            #     the relay ends the turn itself;
            #   • hard guard: 600s of TOTAL silence still aborts (unchanged);
            #   • MAX GENERATION SEGMENT (hermes.max_turn_s, default 600s, 0 = off):
            #     time in ONE unbroken generation stretch — armed at submit, RESET on
            #     every tool.start / tool.complete and on every card resolution, and
            #     PAUSED while a card is pending. So a long research turn with tool
            #     calls runs forever; only a model talking to itself with nothing to
            #     show for it is cut. Checked on the EVENT path too — a runaway
            #     deliberation loop keeps emitting, so every silence-based guard is
            #     blind to it. Remedy is session.interrupt: the generation stops,
            #     not just the stream.
            got_any = False
            silent = 0.0
            noted_slow = False
            # Read ONCE, at submit: a config edit mid-turn must not retune a live
            # turn (same rule as the voice hangover read at capture time).
            try:
                max_turn = hermes_max_turn_s(cfg())
            except Exception:
                max_turn = HERMES_MAX_TURN_S_DEFAULT
            seg_started = asyncio.get_running_loop().time()
            pause_total = 0.0
            pause_since = None
            # An INTERACTIVE CARD awaits the user: a Phase-2 approval, or (2026-08-14)
            # a clarify/ask card. Both block the agent thread on a gateway prompt, so
            # neither is "silence" — the watchdogs must not read them as a dead turn.
            approval_pending = False
            stop_at = None  # monotonic deadline once a panel Stop was requested
            while True:
                if stop_at is not None:
                    timeout = max(0.25, stop_at - asyncio.get_running_loop().time())
                else:
                    timeout = 20.0
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    if stop_at is not None:
                        # Stop was requested but no terminal event arrived — end anyway.
                        yield f"data: {_json.dumps({'delta': chr(10) + '· interrupted'})}\n\n"
                        break
                    silent += timeout
                    # HEARTBEAT (2026-08-14): one tiny frame per ~20s tick, in
                    # EVERY waiting branch (including a pending approval card,
                    # which can legitimately wait minutes). The panel does not
                    # render it — it exists so the panel's own last-resort stall
                    # watchdog can tell "the model is slow" from "the relay is
                    # gone". Without it the panel could only wait out the 600s
                    # hard guard, which is what "stuck forever" felt like.
                    yield 'data: {"type":"hermes_ping"}\n\n'
                    # Segment guard FIRST: it is the only one that also stops
                    # Hermes, so when two guards come due on the same tick the one
                    # that kills the generation should win.
                    _spent = hermes_segment_spent(
                        asyncio.get_running_loop().time(), seg_started,
                        pause_total, pause_since)
                    if hermes_segment_overrun(_spent, max_turn):
                        await _hermes_kill_segment(sid, _spent, max_turn)
                        yield ('data: {"type":"hermes_status","text":'
                               + _json.dumps(hermes_overrun_error(max_turn))
                               + '}\n\n')
                        yield ('data: '
                               + _json.dumps({"type": "proxy_error",
                                              "error": hermes_overrun_error(max_turn)})
                               + '\n\n')
                        break
                    if not got_any and silent >= 60.0:
                        yield ('data: {"type":"proxy_error","error":'
                               '"no response from Hermes within 60s of submit — '
                               'check the Hermes dashboard / model config"}\n\n')
                        break
                    if silent >= 600.0:
                        yield ('data: {"type":"proxy_error","error":'
                               '"hermes turn idle >10min — giving up"}\n\n')
                        break
                    if approval_pending:
                        # Phase 2 / ask cards: the card IS the status — suppress the
                        # 20s working note AND the liveness probe while the user
                        # decides (the agent thread is blocked in
                        # _await_gateway_decision; upstream's own 300s approval
                        # timeout resolves it, and the 600s hard guard above
                        # stays). Panel Stop still works: session.interrupt
                        # auto-denies the pending approval (tools/approval.py:
                        # 3326-3335, #8697) → message.complete(interrupted).
                        # ⚠ PENDING FABLE QA: probe skipped too, not just the
                        # note — a probe misread must never kill a pending card.
                        continue
                    if got_any and not await _hermes_session_working(sid):
                        # Turn ended upstream with no terminal event reaching us
                        # (dashboard-side interrupt was the live repro) — close it.
                        yield f"data: {_json.dumps({'delta': chr(10) + '· interrupted'})}\n\n"
                        break
                    if not noted_slow:
                        noted_slow = True
                        yield ('data: {"type":"hermes_status","text":'
                               '"hermes is working — large prompt prefill can take '
                               'a while on local models"}\n\n')
                    continue
                got_any = True
                silent = 0.0
                noted_slow = False
                if (ev or {}).get("type") == "_stop_requested":
                    # Panel Stop: session.interrupt was issued — give the mapped
                    # message.complete(status=interrupted) ~3s to land, then force-end.
                    if stop_at is None:
                        stop_at = asyncio.get_running_loop().time() + 3.0
                    continue
                # An approval.request OR a clarify.request opens a pending card;
                # ANY other event means the wait resolved (post-decision tool/turn
                # events only flow once resolve_gateway_approval / clarify.respond
                # unblocked the agent thread). clarify.expire is "any other event",
                # which is exactly right: an expired card is no longer pending.
                _was_pending = approval_pending
                approval_pending = ((ev or {}).get("type")
                                    in ("approval.request", "clarify.request"))
                # PAUSE the segment clock for the whole time a card is on screen:
                # a user deciding is not the model burning CPU, and shooting a turn
                # that is WAITING FOR DEBI would be the worst failure of this guard.
                _now = asyncio.get_running_loop().time()
                _resolved = False
                if approval_pending and not _was_pending:
                    pause_since = _now
                elif _was_pending and not approval_pending:
                    if pause_since is not None:
                        pause_total += max(0.0, _now - pause_since)
                        pause_since = None
                    _resolved = True
                # RESET the segment on visible progress: a tool starting or finishing,
                # or a card being answered, both mean this is not one unbroken
                # deliberation stretch. Runs BEFORE the end-of-body overrun check, so
                # a resetting event is never judged against the pre-reset clock.
                if _resolved or hermes_segment_resets((ev or {}).get("type")):
                    seg_started = _now
                    pause_total = 0.0
                frames, action = hermes_event_to_frames(ev)
                for fr in frames:
                    if fr.get("type") == "file_card":
                        # §F: mapper stays pure — expand ~ here (Hermes runs as
                        # this same user). Relative paths pass through as-is
                        # (session cwd not on the wire ⚠ PENDING FABLE QA); the
                        # panel only renders absolute/home paths.
                        try:
                            fp = str(fr.get("path") or "")
                            if fp.startswith("~"):
                                fr["path"] = os.path.expanduser(fp)
                        except Exception:
                            pass
                    elif fr.get("type") == "guard_flag":
                        _guard_audit(fr.get("path"), fr.get("tool"), sid, stored_sid)
                    yield f"data: {_json.dumps(fr, ensure_ascii=False)}\n\n"
                if action == "done":
                    break
                # THE branch that matters for a runaway loop: a spiralling model
                # emits continuously, so this is the only place the guard can see
                # it (the timeout tick above never fires while events flow).
                _spent = hermes_segment_spent(asyncio.get_running_loop().time(),
                                              seg_started, pause_total, pause_since)
                if hermes_segment_overrun(_spent, max_turn):
                    await _hermes_kill_segment(sid, _spent, max_turn)
                    yield ('data: {"type":"hermes_status","text":'
                           + _json.dumps(hermes_overrun_error(max_turn)) + '}\n\n')
                    yield ('data: '
                           + _json.dumps({"type": "proxy_error",
                                          "error": hermes_overrun_error(max_turn)})
                           + '\n\n')
                    break
        except Exception as e:
            yield f'data: {_json.dumps({"type": "proxy_error", "error": str(e)[:300]})}\n\n'
        finally:
            if q is not None:
                _HERMES.close_queue(sid)
            yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/hermes/stop")
async def hermes_stop(req: Request) -> JSONResponse:
    """Interrupt a running Hermes turn (panel Stop button).

    Nudges the relay FIRST via a _stop_requested queue sentinel (arms its ~3s
    force-end fallback even if the RPC below stalls), then issues the gateway's
    session.interrupt (vendor/hermes/tui_gateway/methods_session.py:2705) — the
    normal path is that Hermes then emits message.complete(status="interrupted"),
    which the mapper turns into a clean turn end.
    """
    body = await req.json()
    sid = (body.get("session_id") or "").strip()
    if not sid:
        return JSONResponse({"error": "session_id required"}, status_code=400)
    q = _HERMES._queues.get(sid)
    if q is not None:
        try:
            q.put_nowait({"type": "_stop_requested"})
        except Exception:
            pass
    try:
        res = await _HERMES.rpc("session.interrupt", {"session_id": sid}, timeout=10.0)
        return JSONResponse({"ok": True,
                             "status": res.get("status") or "interrupted"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:300]}, status_code=502)


@app.post("/api/hermes/approve")
async def hermes_approve(req: Request) -> JSONResponse:
    """Answer a pending approval card (Phase 2 chip UX).

    The gateway keys approvals purely by SESSION — resolve_gateway_approval
    (vendor/hermes/tools/approval.py:2198) pops the oldest pending entry FIFO;
    there is no request id on the wire (desktop store/prompts.ts:71) — so
    {session_id, choice} is the complete address. approval.respond params:
    {session_id, choice, all?} (tui_gateway/methods_prompt.py:864-883); the
    optional resolve-all flag is deliberately NOT exposed to the panel.
    """
    body = await req.json()
    sid = (body.get("session_id") or "").strip()
    choice = (body.get("choice") or "").strip()
    if not sid:
        return JSONResponse({"error": "session_id required"}, status_code=400)
    if choice not in ("once", "session", "always", "deny"):
        return JSONResponse({"error": "invalid choice"}, status_code=400)
    try:
        res = await _HERMES.rpc("approval.respond",
                                {"session_id": sid, "choice": choice}, timeout=10.0)
        # resolved=0 → nothing was pending (card raced a timeout/interrupt);
        # surface it so the panel can stamp the card instead of lying "approved".
        return JSONResponse({"ok": True, "resolved": res.get("resolved")})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:300]}, status_code=502)


ASK_ANSWER_MAX = 4000   # chars accepted from the panel's free-text box


@app.post("/api/hermes/answer")
async def hermes_answer(req: Request) -> JSONResponse:
    """Answer a pending clarify/ask card.

    UNLIKE approvals, clarify prompts ARE addressed by id: _block mints a
    request_id and stamps it into the emitted payload
    (tui_gateway/server.py:2856-2862), and clarify.respond resolves purely on
    it — `_respond(rid, params, "answer", allow_expired=True)`
    (methods_prompt.py:836-842) reads params["request_id"] + params["answer"]
    and never looks at a session (server.py:9981-9992). So {request_id, answer}
    is the complete address; session_id is accepted for symmetry with
    /api/hermes/approve and for logging only.

    The ANSWER IS A PLAIN STRING — upstream stores it verbatim and the clarify
    tool returns it as user_response (tools/clarify_tool.py:170). There is no
    index protocol on the wire, so the panel sends the chosen option's LABEL.
    ⚠ PENDING FABLE QA: the brief said `choice_index?|text?`; there is no
    choice_index, because resolving one would mean the BRIDGE keeping a copy of
    the option list — duplicated gateway state whose staleness could answer a
    different question than the card on screen shows. The panel holds the list
    it rendered and sends the label, so what is answered is what was displayed.

    cancel:true sends the empty string, which is exactly what upstream's own
    cancel path does (_clear_pending sets the answer to "" — server.py:2922-2926).

    Result: {"ok":true,"status":"ok"|"expired"} — "expired" means the prompt was
    already gone gateway-side (timeout / interrupt), so the panel must stamp the
    card honestly instead of claiming the answer landed.
    """
    body = await req.json()
    rid = str(body.get("request_id") or "").strip()
    if not rid:
        return JSONResponse({"error": "request_id required"}, status_code=400)
    if body.get("cancel"):
        answer = ""
    else:
        answer = body.get("answer")
        if not isinstance(answer, str):
            return JSONResponse({"error": "answer must be a string"}, status_code=400)
        answer = answer.strip()
        if not answer:
            return JSONResponse({"error": "empty answer — use cancel:true to skip"},
                                status_code=400)
        if len(answer) > ASK_ANSWER_MAX:
            return JSONResponse({"error": f"answer too long (max {ASK_ANSWER_MAX})"},
                                status_code=400)
    try:
        res = await _HERMES.rpc("clarify.respond",
                                {"request_id": rid, "answer": answer}, timeout=10.0)
        return JSONResponse({"ok": True, "status": res.get("status") or "ok"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:300]}, status_code=502)


def hermes_sessions_normalize(rows):
    """PURE (unit-tested standalone): gateway session.list rows → the panel
    rail shape [{id, name, updated_at, message_count, source}].

    session.list rows (methods_session.py:196-206): {id, title, preview,
    started_at, message_count, source}. NOTE the WS projection forwards
    started_at ONLY — list_sessions_rich's last_active is dropped upstream —
    so the rail's relative time is the session START time; the ORDERING from
    the gateway IS by last activity. ⚠ PENDING FABLE QA (honest-but-odd stamp).
    started_at may be epoch seconds or ms; both → ISO-8601 UTC ('' if absent).
    Untitled rows fall back to the preview snippet (Hermes's own picker does
    the same). Malformed rows are dropped, never raise."""
    out = []
    if not isinstance(rows, list):
        return out
    for r in rows:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("id") or "").strip()
        if not rid:
            continue
        iso = ""
        try:
            ts = float(r.get("started_at") or 0)
            if ts > 1e12:          # milliseconds epoch
                ts = ts / 1000.0
            if ts > 0:
                from datetime import datetime, timezone
                iso = datetime.fromtimestamp(ts, timezone.utc).isoformat()
        except Exception:
            iso = ""
        try:
            mc = int(r.get("message_count") or 0)
        except Exception:
            mc = 0
        title = str(r.get("title") or "").strip()
        preview = str(r.get("preview") or "").strip()
        out.append({"id": rid,
                    "name": title or preview or "Untitled",
                    "updated_at": iso,
                    "message_count": mc,
                    "source": str(r.get("source") or "")})
    return out


def hermes_messages_to_panel(messages):
    """PURE (unit-tested standalone): gateway _history_to_messages rows →
    the panel history shape [{role, content}] the Odysseus loader renders.

    Gateway rows (server.py:6645 _history_to_messages): user/assistant carry
    {role, text, reasoning*…}; tool rows are {role:'tool', name, context};
    system rows possible. Only user/assistant rows survive — tool rows are
    dropped (tool detail isn't reconstructible on reopen).

    THINKING REHYDRATION (2026-08-06, Fable QA pass): unlike the direct lane —
    which persists {role, content} to Odysseus and therefore has NOTHING stored
    to restore — Hermes's own store DOES keep the reasoning, so a reopened
    session shows its thinking again as the same collapsed disclosure.

    Aligned with the UPSTREAM projection (server.py _history_to_messages):
    (1) its reasoning keys are exactly reasoning / reasoning_content /
        reasoning_details / codex_reasoning_items — the structured ones are
        flattened defensively (list items: strings, or dicts with a text-ish
        field); a surprise type must never break a transcript.
    (2) reasoning-ONLY assistant turns (thinking with no visible answer) are
        KEPT, mirroring upstream's own #44022 fix — dropping them made
        extended-thinking turns vanish from reopened sessions."""
    def _flatten_reasoning(v):
        if isinstance(v, str):
            return v.strip()
        if isinstance(v, list):
            parts = []
            for it in v:
                if isinstance(it, str) and it.strip():
                    parts.append(it.strip())
                elif isinstance(it, dict):
                    for tk in ("text", "reasoning", "content", "summary"):
                        tv = it.get(tk)
                        if isinstance(tv, str) and tv.strip():
                            parts.append(tv.strip())
                            break
            return "\n".join(parts)
        return ""

    out = []
    if not isinstance(messages, list):
        return out
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        txt = m.get("text")
        txt = txt if isinstance(txt, str) else ""
        reasoning = ""
        if role == "assistant":
            for k in ("reasoning", "reasoning_content",
                      "reasoning_details", "codex_reasoning_items"):
                reasoning = _flatten_reasoning(m.get(k))
                if reasoning:
                    break
        if not txt.strip() and not reasoning:
            continue    # truly empty row — nothing to show
        row = {"role": role, "content": txt}
        if reasoning:
            row["reasoning"] = reasoning
        out.append(row)
    return out


@app.get("/api/hermes/sessions")
async def hermes_sessions() -> JSONResponse:
    """Stored Hermes sessions for the rail (Phase 3; WS-based, no REST token dance).

    session.list (methods_session.py:162) reads state.db ordered by last
    activity; rows are normalized bridge-side (pure hermes_sessions_normalize).
    NOTE: a freshly created EMPTY session has no DB row yet (the write is
    deferred to the first prompt — methods_session.py:895-904 comment), so it
    won't appear here until its first turn. ⚠ PENDING FABLE QA."""
    try:
        res = await _HERMES.rpc("session.list", {"limit": 100})
        return JSONResponse(hermes_sessions_normalize(res.get("sessions") or []))
    except Exception as e:
        return JSONResponse({"error": str(e)[:300]}, status_code=502)


@app.post("/api/hermes/session/new")
async def hermes_session_new() -> JSONResponse:
    try:
        res = await _HERMES.rpc("session.create", {"source": HERMES_SESSION_SOURCE})
        return JSONResponse({"id": res.get("session_id"),
                             "stored_id": res.get("stored_session_id")})
    except Exception as e:
        return JSONResponse({"error": str(e)[:300]}, status_code=502)


@app.post("/api/hermes/session/resume")
async def hermes_session_resume(req: Request) -> JSONResponse:
    """Reopen a STORED Hermes session: transcript + a LIVE sid to continue it.

    session.resume (methods_session.py:305) is the real mechanism — it returns
    a NEW live session_id bound to the stored conversation plus the full display
    transcript (every branch of it includes `messages`: lazy :453, deferred
    :533, eager/live-reuse via _live_session_payload server.py:7588-7597, which
    also carries session_key). prompt.submit on the returned live sid continues
    the conversation — full parity, not read-only. The deferred (default) path
    schedules the agent build OFF the response path, so this returns quickly;
    re-clicking an already-open row hits the live-reuse fast path (:392-396).
    """
    body = await req.json()
    stored = (body.get("id") or "").strip()
    if not stored:
        return JSONResponse({"error": "id required"}, status_code=400)
    try:
        res = await _HERMES.rpc("session.resume",
                                {"session_id": stored, "source": HERMES_SESSION_SOURCE},
                                timeout=30.0)
        return JSONResponse({
            "id": res.get("session_id") or "",
            "stored_id": str(res.get("session_key") or res.get("resumed") or stored),
            "history": hermes_messages_to_panel(res.get("messages") or []),
            "running": bool(res.get("running")),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)[:300]}, status_code=502)


@app.post("/api/hermes/session/{sid}/rename")
async def hermes_session_rename(sid: str, req: Request) -> JSONResponse:
    """Rename a STORED Hermes session.

    The WS gateway has no stored-session rename (session.title is live-session-
    gated via _sess_nowait, methods_session.py:838-840), but the dashboard REST
    router does: PATCH /api/sessions/{id} {title} (web_routers/sessions.py:650),
    auth = the same session token, header X-Hermes-Session-Token
    (web_server.py:305/368-398). ⚠ PENDING FABLE QA: this is the lane's ONE
    REST call amid an otherwise WS-only adapter (mixed transport, contract-
    tested at pin-bump)."""
    body = await req.json()
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name required"}, status_code=400)
    tok = _hermes_token()
    if not tok:
        return JSONResponse({"error": "no Hermes dashboard token"}, status_code=502)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.patch(
                f"http://127.0.0.1:{_hermes_port()}/api/sessions/{sid}",
                json={"title": name},
                headers={"X-Hermes-Session-Token": tok})
        if r.status_code >= 400:
            return JSONResponse({"error": f"rename failed ({r.status_code})"},
                                status_code=502)
        return JSONResponse({"ok": True, "name": name})
    except Exception as e:
        return JSONResponse({"error": str(e)[:300]}, status_code=502)


@app.post("/api/hermes/session/{sid}/delete")
async def hermes_session_delete(sid: str, req: Request) -> JSONResponse:
    """Delete a STORED Hermes session (WS session.delete, methods_session.py:788).

    The gateway refuses to delete a session that is LIVE in-process (4023 —
    correct: the live agent is still writing to it). If the panel is deleting
    the row it currently has open, it passes the live sid as `live_id` and the
    bridge closes that gateway session first (session.close,
    methods_session.py:2561) so the stored row becomes deletable."""
    live_id = ""
    try:
        body = await req.json()
        live_id = (body.get("live_id") or "").strip()
    except Exception:
        pass
    try:
        if live_id:
            try:
                await _HERMES.rpc("session.close", {"session_id": live_id},
                                  timeout=15.0)
            except Exception:
                pass   # close is best-effort; delete below reports the truth
        res = await _HERMES.rpc("session.delete", {"session_id": sid})
        return JSONResponse({"ok": True, "deleted": res.get("deleted") or sid})
    except Exception as e:
        return JSONResponse({"error": str(e)[:300]}, status_code=502)


@app.get("/api/hermes/history/{sid}")
async def hermes_history(sid: str) -> JSONResponse:
    """Transcript of a LIVE gateway session (session.history is live-gated via
    _sess_nowait — methods_session.py:2258-2260; stored sessions go through
    /api/hermes/session/resume instead, which returns the transcript too)."""
    try:
        res = await _HERMES.rpc("session.history", {"session_id": sid})
        return JSONResponse({"history": res.get("messages") or [],
                             "count": res.get("count") or 0})
    except Exception as e:
        return JSONResponse({"error": str(e)[:300]}, status_code=502)
