"""OFFICE MCP SERVER — the LOffice toolset, hosted by the bridge (slice S1).

Built to docs/FABLE-LOFFICE-HERMES-TOOLS-SPEC.md §1/§2. Mounted on the EXISTING :8700
app under `/mcp/office`: no harness.yaml component, no new port, no daemon, loopback
only — the same "not a component" discipline as the Office lane itself. Hermes consumes
it through its own MCP catalog, so Hermes's approval cards, its tool registry and its
Capabilities pane all keep working and `vendor/hermes` is never edited (compose over
APIs, never fork).

bridge/office_ops.py owns every DECISION. This file is the WIRE, and it is deliberately
boring.

═══ WHY THIS SPEAKS THE PROTOCOL BY HAND, WITH NO NEW DEPENDENCY ═══

The spec suggested FastMCP. It was measured instead of assumed, and the answer came out
the other way:

    data/bridge-venv/bin/python -m pip install --dry-run fastmcp
      → 49 new packages, including cryptography, cffi, rpds-py and watchfiles
        (all with COMPILED wheels), plus a second HTTP stack (httpx2).
    …--dry-run mcp   (the official SDK alone)
      → 17 new packages, still including cryptography/cffi/rpds-py and httpx2.

bridge/requirements.txt today is SIX pure-python lines, and build_app.sh 4b carries
every one of them into a wheelhouse that a fresh Mac provisions from. Adding a compiled
dependency tree — and a second httpx next to the one this bridge's whole Hermes lane
already uses — to serve five JSON-RPC methods is not a trade this codebase makes.

WHAT WE ACTUALLY NEED is the SERVER half of MCP Streamable HTTP for a tools-only
server, which is five methods and one header:

    initialize · notifications/initialized · tools/list · tools/call · ping

and the two rules that make the transport work with a real client (read out of the
CLIENT the vendored Hermes actually uses — mcp 1.28.1, data/hermes-venv, so this is
measured too, not remembered):

  · A REQUEST may be answered with a single `application/json` body. The client's
    `_handle_post_request` branches on the response content type
    (mcp/client/streamable_http.py:365-372) and `application/json` is a first-class
    branch, not a fallback. We never open an SSE stream: there is nothing to stream —
    every one of these tools is one synchronous answer.
  · A NOTIFICATION is answered `202 Accepted` with NO body
    (streamable_http.py:346-348). Answering a notification with a JSON-RPC response is
    the single most common way a hand-written MCP server fails, because the client
    treats it as a reply to a request it never sent.

Everything else is optional and is either provided (an `Mcp-Session-Id`, so a
well-behaved client has one to echo) or declined honestly (`GET` → 405, which the client
handles at streamable_http.py:588 and simply stops asking for a server-initiated
stream).

⚠️ THE SESSION ID IS ADVISORY AND UNKNOWN IDS ARE ACCEPTED. A bridge restart would
otherwise turn every live Hermes session into a hard 404 the model cannot recover from,
which is a worse outcome than a stateless server — and this server IS stateless: every
call resolves the workbook off disk by name. Same judgment as the office_ops heartbeat:
never invent state whose loss breaks the lane.

═══ APPROVAL: WHAT HERMES ACTUALLY OFFERS, AND WHAT WE DO WITH IT ═══

The spec asked for the write tools to be registered "approval-required". Read out of the
pin (v2026.8.13) rather than assumed, THERE IS NO PER-TOOL APPROVAL FIELD in a Hermes
`mcp_servers` entry. What exists is a TWO-FACTOR gate
(vendor/hermes/tools/mcp_tool.py:3929-4070):

  1. PER SERVER, operator-set: `mcp_servers.<name>.trust: full | untrusted`. Default is
     `full`, i.e. the gate is OFF. `_normalize_server_trust` (:3963) fails CLOSED — any
     unrecognised value becomes `untrusted`.
  2. PER TOOL, server-declared: a tool is WRITE-CAPABLE unless its discovery-time
     `annotations.readOnlyHint` is exactly `True` (`_annotation_read_only_hint`, :3985 —
     "missing/malformed annotations fail closed to write-capable").

`_trust_gate_check` (:4017) then routes every write-capable call on an untrusted server
through `tools.approval.request_elicitation_consent` (approval.py:4830) BEFORE any
transport work happens (`_handler`, mcp_tool.py:5349) — which in our lane is Hermes's
own gateway approval card, the same surface `write_file` uses.

SO WE GET THE PER-TOOL GRANULARITY THE SPEC WANTED, just declared from this side of the
wire instead of configured on that side:

  · the bridge writes `trust: untrusted` into the `loffice` entry (arming the gate), and
  · THIS FILE declares `readOnlyHint: true` on the three read tools and NOT on the four
    write tools.

⚠️ WHICH MEANS THE ANNOTATIONS BELOW ARE A SECURITY BOUNDARY, NOT DOCUMENTATION. Putting
`readOnlyHint: true` on a tool that writes would silently remove its approval card.
bridge/tests/test_office_mcp.py asserts the exact split, and it must fail if a tool
changes side.

⚠️ AND THE APPROVAL IS PER CALL, NEVER REMEMBERED: `request_elicitation_consent` passes
`allow_permanent=False` (approval.py:4909), so there is no "always allow" to leak.
"""
from __future__ import annotations

import json
import os
import secrets
import time

try:                                                             # pragma: no cover
    from . import office, office_ops
except ImportError:                                              # pragma: no cover
    import office                                                # type: ignore
    import office_ops                                            # type: ignore

# ⚠️ MODULE LEVEL, NOT INSIDE build_router(), AND THAT IS NOT TIDINESS. This file has
# `from __future__ import annotations`, so every parameter annotation is a STRING that
# FastAPI resolves against the MODULE's globals when it builds the route. A `Request`
# imported inside build_router() is a LOCAL: FastAPI cannot see it, decides `req` must
# be a query parameter, and every POST comes back 422 "Field required" — which is
# exactly what happened, once, before this moved up here.
try:                                                             # pragma: no cover
    from fastapi import APIRouter, Request
    from fastapi.responses import JSONResponse, Response
except Exception:                                                # noqa: BLE001
    APIRouter = Request = JSONResponse = Response = None          # type: ignore


MOUNT_PATH = "/mcp/office"
SERVER_NAME = "loffice"
SERVER_VERSION = "1"

# The protocol revisions this server is prepared to name back at a client. It implements
# nothing version-specific — five methods, one transport rule — so the list exists only
# so that a client asking for something we have never heard of gets a definite answer
# rather than an echo of its own guess.
KNOWN_PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_PROTOCOL = "2025-06-18"

# The single sentence in front of every tool description. A model that has never seen
# this harness must learn the containment rule from the TOOL LIST, not by trying.
_ADDRESSING = ("Workbooks are addressed by NAME (as office_list returns them), never by "
               "path: these tools cannot see anything outside the Office folder. ")


# ── the schemas ──────────────────────────────────────────────────────────────
_NAME_ARG = {"type": "string",
             "description": "the workbook's name, e.g. 'Sales.xlsx' (from office_list)"}
_SHEET_ARG = {"type": "string",
              "description": "sheet name; omitted means the first sheet. Sheet names "
                             "come from office_sheet_stats — a name that does not "
                             "exist falls back to the first sheet and the result SAYS "
                             "so."}

# ⚠️ `ops` is described rather than fully schema'd on purpose. The grammar is the LOffice
# action block's, it is validated by office_ops.validate_ops with a sentence per refusal,
# and a JSON Schema strict enough to be worth having here would be a SECOND validator
# that could disagree with the first. The description teaches it; the validator enforces
# it; the refusal explains it.
_OPS_ARG = {
    "type": "array",
    "description": (
        "the change, as a list of operations (max 60, and max 2000 cells across all of "
        "them — over either cap the WHOLE change is refused, never half-applied):\n"
        '  {"op":"set","at":"A1","values":[["Month","Planned"],["Jan",900]]}'
        "  — row-major; a leading = is a formula; null or \"\" empties a cell but KEEPS "
        "its formatting. \"at\" is an ANCHOR, not a clip: values larger than the range "
        "write past it.\n"
        '  {"op":"style","at":"A1:C1","set":{"bl":1}}'
        "  — bl bold · it italic · ul underline · st strikethrough · ff font · fs size "
        "· cl text colour · bg fill (both #rrggbb) · ht/vt align (left/center/right, "
        "top/middle/bottom) · tb wrap · n number format. Those are exactly the keys the "
        ".xlsx round-trip carries; anything else is dropped.\n"
        '  {"op":"sheet","add":"Notes"} / {"op":"sheet","rename":"2026"}\n'
        '  {"op":"resize","rows":500,"cols":40}  — grows the sheet; clamped, not '
        "refused.\n"
        "Use office_sort and office_insert_delete for sorting and for inserting or "
        "deleting rows and columns."),
    "items": {"type": "object"},
}


def tool_specs() -> list:
    """The tool catalog. PURE, so the test can read the split without a server.

    ⚠️ `read_only` here becomes `annotations.readOnlyHint`, which is what arms or
    disarms Hermes's approval card for that tool. See the module docstring.
    """
    return [
        {
            "name": "office_list",
            "read_only": True,
            "description": (
                _ADDRESSING +
                "List every spreadsheet in the Office folder, newest first, with its "
                "size, when it changed, whether Debi has it open in LOffice right now "
                "and whether she has unsaved edits in it. Start here: the other tools "
                "need a name from this list."),
            "schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "office_read",
            "read_only": True,
            "description": (
                _ADDRESSING +
                "Read cells from one sheet: values, formulas AS TEXT with the value "
                "cached in the file by whichever real engine last saved it, and any "
                "merged ranges. NOTHING HERE RECOMPUTES ANYTHING — there is no formula "
                "engine — so a cached value can be stale and every result says so. Cap "
                f"{office_ops.READ_MAX_CELLS} cells; omit `range` for the used range."),
            "schema": {"type": "object", "properties": {
                "name": _NAME_ARG, "sheet": _SHEET_ARG,
                "range": {"type": "string",
                          "description": "A1-style cell or range, e.g. 'A1:D20'. "
                                         "Omitted means the whole used range."},
            }, "required": ["name"], "additionalProperties": False},
        },
        {
            "name": "office_sheet_stats",
            "read_only": True,
            "description": (
                _ADDRESSING +
                "The shape of a workbook: every sheet's name, used size, merge and "
                "formula counts, plus per-column stats for one sheet (how many "
                "numbers, text, booleans, blanks and formulas, and min/max/sum/mean of "
                "the numbers) and row 1 as it actually is. Cheaper than office_read for "
                "'what is in this file' and 'which column holds the amounts'."),
            "schema": {"type": "object", "properties": {
                "name": _NAME_ARG, "sheet": _SHEET_ARG,
            }, "required": ["name"], "additionalProperties": False},
        },
        {
            "name": "office_write_cells",
            "read_only": False,
            "description": (
                _ADDRESSING +
                "Write values and formatting into a workbook, add or rename a sheet, or "
                "grow one. The workbook as it was first goes to "
                "<name>.pre-agent.xlsx beside it — that is the only undo for this, "
                "because LOffice's in-page undo cannot see a write it did not make. "
                "REFUSED while Debi has unsaved edits in that workbook."),
            "schema": {"type": "object", "properties": {
                "name": _NAME_ARG, "sheet": _SHEET_ARG, "ops": _OPS_ARG,
            }, "required": ["name", "ops"], "additionalProperties": False},
        },
        {
            "name": "office_sort",
            "read_only": False,
            "description": (
                _ADDRESSING +
                "Sort the WHOLE sheet by one column — ROW 1 INCLUDED, because LOffice "
                "never guesses at a header row. Blank cells go to the bottom in both "
                "directions; numbers sort before text before booleans; equal keys keep "
                "their order. REFUSED on a sheet that has ANY merged range (a sort "
                "moves whole rows and a merge does not move with them). Formula "
                "references are NOT rewritten — a formula travels as text and the "
                "result says so."),
            "schema": {"type": "object", "properties": {
                "name": _NAME_ARG, "sheet": _SHEET_ARG,
                "col": {"type": "string",
                        "description": "the column LETTER to sort by, e.g. 'B'. A bare "
                                       "number is refused: it is ambiguous between "
                                       "'column 2' and 'column B'."},
                "desc": {"type": "boolean",
                         "description": "true for Z→A / largest first. Default false."},
            }, "required": ["name", "col"], "additionalProperties": False},
        },
        {
            "name": "office_insert_delete",
            "read_only": False,
            "description": (
                _ADDRESSING +
                "Insert blank rows/columns, or DELETE rows/columns and the data in "
                "them. An insert goes ABOVE the row / to the LEFT of the column named. "
                "Merged ranges are renumbered properly (a merge that straddles the line "
                "grows on an insert and shrinks on a delete, which is what Excel does), "
                "but formula references are NOT rewritten and the result says so. An "
                "insert of more than "
                f"{office_ops.RC_MAX} is clamped; a DELETE of more than "
                f"{office_ops.RC_MAX} is refused, because a clamped delete would "
                "destroy exactly as much data as it felt like."),
            "schema": {"type": "object", "properties": {
                "name": _NAME_ARG, "sheet": _SHEET_ARG,
                "action": {"type": "string", "enum": ["insert", "delete"],
                           "description": "insert blank rows/columns, or delete them"},
                "what": {"type": "string", "enum": ["row", "col"],
                         "description": "rows or columns"},
                "at": {"description": "for rows: the 1-based row number (or a cell "
                                      "reference like 'A3'). For columns: the column "
                                      "LETTER."},
                "n": {"type": "integer",
                      "description": "how many. Default 1."},
            }, "required": ["name", "action", "what", "at"],
                "additionalProperties": False},
        },
        {
            "name": "office_create",
            "read_only": False,
            "description": (
                _ADDRESSING +
                "Create a new, empty spreadsheet. It NEVER overwrites: a name already "
                "taken comes back stepped — 'budget.xlsx' → 'budget (2).xlsx' — and the "
                "result says which name it actually got. Use that name for every "
                "following call."),
            "schema": {"type": "object", "properties": {
                "name": {"type": "string",
                         "description": "what to call it; the .xlsx is added for you"},
            }, "required": ["name"], "additionalProperties": False},
        },
    ]


def tool_list_payload() -> list:
    """tool_specs() in MCP's own `tools/list` shape."""
    out = []
    for t in tool_specs():
        ent = {"name": t["name"], "description": t["description"],
               "inputSchema": t["schema"]}
        # ⚠️ ONLY the read tools carry readOnlyHint, and only `true` disarms Hermes's
        # gate (`hint is True`, mcp_tool.py:3999). A write tool carries NO hint at all
        # rather than `false`, so that a client which ignores annotations entirely still
        # sees no claim of read-onlyness anywhere.
        if t["read_only"]:
            ent["annotations"] = {"readOnlyHint": True, "title": t["name"]}
        else:
            ent["annotations"] = {"destructiveHint": True, "title": t["name"]}
        out.append(ent)
    return out


def write_tool_names() -> list:
    return [t["name"] for t in tool_specs() if not t["read_only"]]


def read_tool_names() -> list:
    return [t["name"] for t in tool_specs() if t["read_only"]]


# ── the dispatcher ───────────────────────────────────────────────────────────
def _args(params) -> dict:
    a = (params or {}).get("arguments")
    return a if isinstance(a, dict) else {}


def call_tool(root, name, params):
    """(text, is_error). The ONE place a tool name becomes an office_ops call.

    A refusal comes back as `isError` with the SENTENCE in it, never as a JSON-RPC
    error: a model that gets a transport error learns nothing, and a model that gets
    "refused: a workbook is addressed by name, not by path" learns the rule.
    """
    a = _args(params)
    try:
        if name == "office_list":
            return _ok(office_ops.op_list(root))
        if name == "office_read":
            return _pair(office_ops.op_read(root, a.get("name"), a.get("sheet"),
                                            a.get("range")))
        if name == "office_sheet_stats":
            return _pair(office_ops.op_sheet_stats(root, a.get("name"), a.get("sheet")))
        if name == "office_write_cells":
            return _pair(office_ops.op_write_cells(root, a.get("name"), a.get("sheet"),
                                                   a.get("ops")))
        if name == "office_sort":
            return _pair(office_ops.op_sort(root, a.get("name"), a.get("sheet"),
                                            a.get("col"), a.get("desc")))
        if name == "office_insert_delete":
            return _pair(office_ops.op_insert_delete(
                root, a.get("name"), a.get("sheet"), a.get("action"), a.get("what"),
                a.get("at"), 1 if a.get("n") is None else a.get("n")))
        if name == "office_create":
            return _pair(office_ops.op_create(root, a.get("name")))
    except office.OfficeError as e:                               # a refusal with words
        return json.dumps({"ok": False, "error": str(e)}), True
    except Exception as e:                                        # noqa: BLE001
        # TOTALITY. Every argument here came from a language model; a traceback out of
        # this function would take down a Hermes turn instead of costing one tool call.
        return json.dumps({"ok": False,
                           "error": f"that call failed inside the bridge: "
                                    f"{type(e).__name__}: {str(e)[:200]}"}), True
    return None, None                                             # unknown tool


def _ok(result):
    return json.dumps(result, ensure_ascii=False, default=str), False


def _pair(pair):
    result, reason = pair
    if result is None:
        return json.dumps({"ok": False, "error": reason}, ensure_ascii=False), True
    return _ok(result)


# ── JSON-RPC ─────────────────────────────────────────────────────────────────
def _err(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": code, "message": message}}


def _res(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def negotiate(asked) -> str:
    """The protocolVersion to answer with. A version we know is echoed; anything else
    gets the one we name as ours, which is what the spec tells a server to do rather
    than agreeing to a revision it has never heard of."""
    return asked if isinstance(asked, str) and asked in KNOWN_PROTOCOLS \
        else DEFAULT_PROTOCOL


def handle(root, message):
    """One JSON-RPC message → (response dict or None). None means "this was a
    notification": the caller must answer 202 with an EMPTY body."""
    if not isinstance(message, dict):
        return _err(None, -32600, "not a JSON-RPC object")
    method = message.get("method")
    rid = message.get("id")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if not isinstance(method, str):
        return _err(rid, -32600, "no method")
    if rid is None:                                # ── a NOTIFICATION: no reply, ever
        return None
    if method == "initialize":
        return _res(rid, {
            "protocolVersion": negotiate(params.get("protocolVersion")),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION,
                           "title": "LOffice spreadsheets"},
            "instructions": (
                "These tools read and write the spreadsheets in Debi's Office folder. "
                "Call office_list first — every other tool takes a NAME from it, and "
                "none of them can reach a file outside that folder. Nothing here "
                "computes a formula: office_read returns formulas as text plus the "
                "value cached in the file, and says which is which. Before every "
                "write the workbook is copied to <name>.pre-agent.xlsx, which is the "
                "only way back; say so when you report a write."),
        })
    if method == "ping":
        return _res(rid, {})
    if method == "tools/list":
        return _res(rid, {"tools": tool_list_payload()})
    if method in ("resources/list", "resources/templates/list"):
        return _res(rid, {"resources": []} if method == "resources/list"
                    else {"resourceTemplates": []})
    if method == "prompts/list":
        return _res(rid, {"prompts": []})
    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str):
            return _err(rid, -32602, "tools/call needs a tool name")
        text, is_error = call_tool(root, name, params)
        if text is None:
            return _err(rid, -32602, f"no such tool: {name}")
        return _res(rid, {"content": [{"type": "text", "text": text}],
                          "isError": bool(is_error)})
    return _err(rid, -32601, f"method not found: {method}")


# ── the ASGI surface ─────────────────────────────────────────────────────────
# A FastAPI router rather than a mounted sub-app: three routes that need to be on the
# main app's middleware and logging like everything else, and a mount would buy an
# isolation this server does not want (it must be reachable at exactly
# http://127.0.0.1:8700/mcp/office, which is the URL written into Hermes's config).
_ROOT = None
_SESSIONS: dict = {}
SESSION_MAX = 32


def configure(root) -> None:
    """Called once by bridge/app.py. Kept explicit rather than re-deriving the root
    here: two ideas of where the harness lives is exactly the bug that lets a tool
    write to the wrong data/office."""
    global _ROOT
    _ROOT = root


def _new_session() -> str:
    sid = secrets.token_hex(16)
    if len(_SESSIONS) >= SESSION_MAX:            # cheap bound; oldest out first
        for k in sorted(_SESSIONS, key=lambda k: _SESSIONS[k])[:len(_SESSIONS) // 2 + 1]:
            _SESSIONS.pop(k, None)
    _SESSIONS[sid] = time.time()
    return sid


def build_router():
    """The three routes. Built by a call rather than by decorators at import time, so
    the module is importable — and every pure function above testable — on a machine
    where FastAPI is not installed at all."""
    if APIRouter is None:                                        # pragma: no cover
        raise RuntimeError("FastAPI is not available in this interpreter")
    router = APIRouter()

    @router.post(MOUNT_PATH)
    async def mcp_post(req: Request):
        """The whole transport. One JSON-RPC message in, one JSON body (or 202) out."""
        try:
            raw = await req.body()
            msg = json.loads(raw.decode("utf-8", "replace")) if raw else None
        except Exception:                                        # noqa: BLE001
            return JSONResponse({"jsonrpc": "2.0", "id": None,
                                 "error": {"code": -32700, "message": "parse error"}},
                                status_code=400)
        root = _ROOT
        if root is None:
            return JSONResponse(
                {"jsonrpc": "2.0", "id": None,
                 "error": {"code": -32603,
                           "message": "the office MCP server was not configured"}},
                status_code=503)
        # A list is the pre-2025-06-18 batch shape. Answered rather than refused: a
        # batch of notifications is still 202, and a batch with any request is a list.
        if isinstance(msg, list):
            out = [r for r in (handle(root, m) for m in msg) if r is not None]
            if not out:
                return Response(status_code=202)
            return JSONResponse(out, headers=_headers(req))
        out = handle(root, msg)
        if out is None:
            return Response(status_code=202, headers=_headers(req))
        return JSONResponse(out, headers=_headers(req))

    def _headers(req) -> dict:
        """`Mcp-Session-Id` on the way back. Minted on initialize, echoed otherwise,
        and an id we have never seen is ACCEPTED — see the module docstring."""
        got = req.headers.get("mcp-session-id")
        if got:
            _SESSIONS.setdefault(got, time.time())
            return {"Mcp-Session-Id": got}
        return {"Mcp-Session-Id": _new_session()}

    @router.get(MOUNT_PATH)
    def mcp_get():
        """405: this server never initiates anything, so there is no stream to open.
        The client handles exactly this (mcp/client/streamable_http.py:588) and stops
        asking. `Allow` is there because a 405 without it is a malformed 405."""
        return Response(status_code=405, headers={"Allow": "POST, DELETE"},
                        content=b"")

    @router.delete(MOUNT_PATH)
    def mcp_delete(req: Request):
        """Session termination. Honoured because it costs nothing, and a client that
        cleans up should not get a 405 for doing the right thing."""
        got = req.headers.get("mcp-session-id")
        if got:
            _SESSIONS.pop(got, None)
        return Response(status_code=204)

    return router


# ── registration in Hermes's config ─────────────────────────────────────────
def hermes_entry(port=8700) -> dict:
    """PURE. The `mcp_servers.loffice` entry, so the wire shape is unit-testable with
    no ~/.hermes on disk (the voice_mcp_spec precedent).

    EVERY KEY IS LOAD-BEARING:
      url    — Hermes picks its transport by shape: `"url" in config` → HTTP
               (`_is_http`, mcp_tool.py:2174), and without `transport: sse` that is
               Streamable HTTP (`_run_http`, :3018). Loopback, always.
      trust  — `untrusted` ARMS the approval gate for every write-capable tool on this
               server (`_trust_gate_check`, mcp_tool.py:4017). Without it the default is
               `full` and our write tools would run with NO card. This one word is the
               whole approval story on the config side; the per-tool half is the
               readOnlyHint annotations in tool_list_payload().
      timeout— a full-workbook read + snapshot + save of a large .xlsx is seconds, not
               milliseconds, and the default per-call timeout is 300s. 120 is generous
               for this and fails faster than the default when something is truly stuck.
      skip_preflight — NOT set, deliberately: Hermes's content-type probe
               (mcp_tool.py:2852) is best-effort and only rejects an unambiguous
               non-MCP 2xx body. Our GET answers 405, which the probe passes through
               silently, so the probe costs us nothing and still protects a
               mis-typed URL.
    """
    try:
        p = int(port)
    except (TypeError, ValueError):
        return {}
    if p <= 0 or p > 65535:
        return {}
    return {"url": f"http://127.0.0.1:{p}{MOUNT_PATH}",
            "trust": "untrusted",
            "timeout": 120}
