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

═══ APPROVAL IN v2: THERE IS NOTHING LEFT TO APPROVE ═══

docs/FABLE-AGENT-CHANGESET-SPEC.md §1 retired the four write tools. THE CATALOG IS NOW
FOUR READ TOOLS, all annotated `readOnlyHint: true`, and one of them —
`office_stage_changes` — records a PROPOSAL the bridge holds. None of them can touch a
workbook, so Hermes's per-call trust gate has nothing to fire on: ZERO approval cards on
this lane, ever.

That is not a hole; it is the ruling. The 2026-08-27 incident (docs/research/
2026-08-27-agent-consent-incident.md) was per-CALL consent applied to a document edit
that was ONE intention: three writes, three cards, one missed, and a model narrating
"Done" over a failure nothing in the UI contradicted. Hermes's card cannot show tool
ARGUMENTS (the message is built from the tool and server NAME literals —
vendor/hermes/tools/mcp_tool.py:4035-4046) and its trust gate remembers nothing
(`request_elicitation_consent` passes allow_permanent=False, approval.py:4909). So the
consent moved to the surface that CAN show the change: the LOffice panel renders the
staged changeset as ONE card with before → after per cell, and Apply is a button.

WHAT THE ANNOTATIONS MEAN NOW, and it is still a security boundary — just a simpler one:

  · `readOnlyHint: true` on all four is HONEST. Three of them read a file; the fourth
    reads a file, runs the ops on an in-memory COPY, and stores the diff. `bridge/tests/
    test_office_mcp.py` asserts the file's mtime is UNCHANGED by staging, which is the
    assertion that makes the annotation a fact rather than a claim.
  · The `loffice` entry still carries `trust: untrusted`. Redundant today (nothing on
    the server is write-capable) and kept anyway: it costs nothing, and it means that a
    tool which ever DOES gain the ability to write gets a card the moment it drops the
    hint, instead of shipping unattended because someone also had to remember the config.

⚠️ SO THE ONE RULE FOR ANYONE EDITING THIS FILE: A TOOL THAT WRITES A WORKBOOK MUST NOT
BE ADDED HERE. Apply lives on POST /api/office/changeset/{id}/apply, which is reachable
from the panel and from nowhere else. `bridge/tests/test_office_mcp.py` pins the catalog
as an exact list of four and pins every one of them read-only, and the contract test
pins the upstream facts that make the annotation load-bearing.
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
        "the WHOLE change, as a list of operations (max 60, and max 2000 cells across "
        "all of them — over either cap the whole change is refused, never half-staged). "
        "Send every operation the request needs in ONE call: Debi sees one card per "
        "call, so two calls are two cards for one intention.\n"
        '  {"op":"set","at":"A1","values":[["Month","Planned"],["Jan",900]]}'
        "  — row-major; a leading = is a formula; null or \"\" empties a cell but KEEPS "
        "its formatting. \"at\" is an ANCHOR, not a clip: values larger than the range "
        "write past it.\n"
        # ═══ TYPES. THE ONE THING TO GET RIGHT, AND THE INCIDENT THAT PROVES IT ═══
        # 2026-08-28: an agent staged a budget as "$2,500", "$400", … — strings — and the
        # =SUM over them computed 0, correctly and silently, because every spreadsheet
        # engine skips text inside an aggregate. THE GRAMMAR ALREADY CARRIES THE TYPE (a
        # JSON number is a number; a JSON string is text), so the fix that actually holds
        # is teaching this here, emphatically, with examples. The bridge's contextual
        # inference is a backstop, not the plan.
        "★ TYPES MATTER MORE THAN ANYTHING ELSE IN THIS GRAMMAR. A JSON NUMBER is stored "
        "as a number; a JSON STRING is stored as text; and a formula that aggregates TEXT "
        "computes 0 — silently, in a document Debi will trust. So:\n"
        '  · MONEY → the NUMBER plus the format, in the same change:\n'
        '      {"op":"set","at":"B2","values":[[2500],[400]]},\n'
        '      {"op":"style","at":"B2:B3","set":{"n":{"pattern":"$#,##0"}}}\n'
        "    NOT [[\"$2,500\"],[\"$400\"]]. Same for percentages (0.125 with "
        '"n":{"pattern":"0.0%"}) and for any quantity a total will ever be taken over.\n'
        "  · IDs, PHONE NUMBERS, CODES, SKUs, PART NUMBERS, price bands → STRINGS, and "
        'when the string looks like a number add "as_text": true to that set op (or send '
        "it with a leading apostrophe, '007) so nothing can second-guess it.\n"
        "  · A numeric-shaped STRING that arrives anyway is decided from CONTEXT — the "
        "column's other values, what that column already holds, and its header — and the "
        "result is listed on Debi's card either way. That is a safety net for a mistake, "
        "not a substitute for typing the value.\n"
        '  {"op":"style","at":"A1:C1","set":{"bl":1}}'
        "  — bl bold · it italic · ul underline · st strikethrough · ff font · fs size "
        "· cl text colour · bg fill (both #rrggbb) · ht/vt align (left/center/right, "
        "top/middle/bottom) · tb wrap · n number format. Those are exactly the keys the "
        ".xlsx round-trip carries; anything else is dropped.\n"
        '  {"op":"sort","col":"B","desc":false}  — sorts the WHOLE sheet by that '
        "column, ROW 1 INCLUDED (nothing here guesses at a header row), and is REFUSED "
        "on a sheet with any merged range.\n"
        '  {"op":"insert","what":"row","at":7,"n":1}  — blank rows ABOVE row 7 / '
        "columns LEFT of the column named.\n"
        '  {"op":"delete_rc","what":"row","at":7,"n":1}  — deletes rows/columns AND '
        "the data in them.\n"
        '  {"op":"add_sheet","name":"Notes"} / {"op":"sheet","rename":"2026"}\n'
        '  {"op":"create_workbook"}  — makes the workbook named in `name`, when it does '
        "not exist yet. It takes no name of its own: a change is about ONE workbook.\n"
        '  {"op":"resize","rows":500,"cols":40}  — grows the sheet; clamped, not '
        "refused.\n"
        "Merged ranges are renumbered on an insert or a delete, but FORMULA REFERENCES "
        "ARE NEVER REWRITTEN — a formula travels as text, and the result says so."),
    "items": {"type": "object"},
}


def tool_specs() -> list:
    """The tool catalog: EXACTLY FOUR TOOLS, ALL READ-ONLY. PURE, so the test can read
    the whole surface without a server.

    ⚠️ `read_only` here becomes `annotations.readOnlyHint`. In v2 it is True on every
    row, because no tool on this server writes a workbook. Adding a fifth tool that
    does — or dropping the hint on one of these — is the one change this file must not
    take: see the module docstring.
    """
    return [
        {
            "name": "office_list",
            "read_only": True,
            "description": (
                _ADDRESSING +
                "List every file in the Office folder, newest first, with its size, "
                "when it changed, whether Debi has it open in LOffice right now and "
                "whether she has unsaved edits in it. Start here: the other tools need "
                "a name from this list. "
                "⚠️ THE FOLDER HOLDS THREE KINDS OF FILE AND YOU CAN ONLY WORK WITH "
                "ONE. Each row carries `kind`: 'sheet' (.xlsx) is a spreadsheet and "
                "every tool here works on it; 'doc' (.docx) and 'slides' (.pptx) are "
                "edited only by LOffice's editor and are OPAQUE to these tools — "
                "office_read and office_stage_changes refuse them by name. Do not "
                "offer to change one; say it is the editor's and offer the "
                "spreadsheets."),
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
                f"{office_ops.READ_MAX_CELLS} cells; omit `range` for the used range. "
                "SPREADSHEETS (.xlsx) ONLY: a .docx or .pptx is refused with a sentence "
                "saying so — there is no way to read inside one from here."),
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
                "'what is in this file' and 'which column holds the amounts'. "
                "SPREADSHEETS (.xlsx) ONLY, like office_read."),
            "schema": {"type": "object", "properties": {
                "name": _NAME_ARG, "sheet": _SHEET_ARG,
            }, "required": ["name"], "additionalProperties": False},
        },
        {
            "name": "office_stage_changes",
            "read_only": True,
            "description": (
                _ADDRESSING +
                "PROPOSE a change to a workbook. THIS WRITES NOTHING. It checks the "
                "operations, reads the workbook, works out what each cell would say "
                "before and after, and hands Debi ONE card in LOffice with the whole "
                "list on it and an Apply button. "
                + office_ops.NOT_APPLIED_SENTENCE + " "
                "You cannot apply it: there is no apply tool and there never will be. "
                "SPREADSHEETS (.xlsx) ONLY: a .docx or .pptx cannot be staged, because "
                "nothing here reads or writes one. "
                "Stage the COMPLETE change for the request in ONE call — a second call "
                "REPLACES the first proposal, so a change sent in pieces loses the "
                "earlier pieces. Then say in one short sentence what you staged, and "
                "stop. Never say a workbook was changed unless a system line tells you "
                "the changeset was applied. "
                # ═══ THE TWO THINGS THE RESULT WILL TELL YOU, AND WHAT TO DO ═══
                "SEND AMOUNTS AS JSON NUMBERS with a number-format style op, never as "
                "\"$2,500\" — a formula over text computes 0. READ THE RESULT'S `notes` "
                "AND `warnings` BEFORE YOU ANSWER: if one says a range holds text that "
                "looks numeric, fix it in THIS turn by staging one new change that "
                "re-sets those cells as numbers AND re-states the formula together, or — "
                "if the column really is ids or codes — drop the aggregate and say why. "
                "Do not ask Debi to decide a cell's type. A proposal expires after "
                f"{int(office_ops.CHANGESET_TTL // 60)} minutes."),
            "schema": {"type": "object", "properties": {
                "name": _NAME_ARG, "sheet": _SHEET_ARG, "ops": _OPS_ARG,
            }, "required": ["name", "ops"], "additionalProperties": False},
        },
    ]


def tool_list_payload() -> list:
    """tool_specs() in MCP's own `tools/list` shape."""
    out = []
    for t in tool_specs():
        ent = {"name": t["name"], "description": t["description"],
               "inputSchema": t["schema"]}
        # ⚠️ ONLY `readOnlyHint: true` (the literal True — Hermes tests `hint is True`,
        # mcp_tool.py:3999) disarms the trust gate, and in v2 every tool earns it: not
        # one of them opens a workbook for writing. The mtime assertion in
        # bridge/tests/test_office_mcp.py is what keeps that honest.
        if t["read_only"]:
            ent["annotations"] = {"readOnlyHint": True, "title": t["name"]}
        else:                                                    # pragma: no cover
            # Unreachable in v2 and kept as the fence: a write tool added here would
            # carry NO read-only claim, so Hermes would card it rather than run it.
            ent["annotations"] = {"destructiveHint": True, "title": t["name"]}
        out.append(ent)
    return out


def write_tool_names() -> list:
    """Empty in v2, and that is the headline. Kept as a function because /api/office/mcp
    reports the approval split and "nothing is gated because nothing writes" is the
    honest answer to give a reader, not a missing key."""
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
    "refused: a file here is addressed by name, not by path" learns the rule. The panel
    renders every isError result as a red ✗ chip, so a refusal is no longer something
    only the model sees (that silence is half of the 2026-08-27 incident).
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
        if name == "office_stage_changes":
            # ⚠️ THE SESSION IS RESOLVED HERE, NOT PASSED. An MCP tools/call carries the
            # MCP TRANSPORT's session id and Hermes keeps ONE MCP client per process, so
            # the transport id is the same for every Hermes conversation and is useless
            # as a key. office_ops.active_session() is the honest correlation: the
            # Hermes session whose turn is running right now, recorded by the bridge's
            # own /api/hermes/chat relay. See its docstring for what that costs.
            return _pair(office_ops.stage_changes(
                root, office_ops.active_session(), a.get("name"), a.get("sheet"),
                a.get("ops")))
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
                "These tools read the spreadsheets in Debi's Office folder and PROPOSE "
                "changes to them. Call office_list first — every other tool takes a "
                "NAME from it, and none of them can reach a file outside that folder. "
                "Nothing here computes a formula: office_read returns formulas as text "
                "plus the value cached in the file, and says which is which. "
                "NOTHING HERE WRITES A WORKBOOK. office_stage_changes records ONE "
                "proposal per workbook — send the complete change in a single call — "
                "and Debi applies it with a button in LOffice, which also keeps a "
                "checkpoint she can undo from. You cannot apply it, and you must never "
                "report a change as made unless a system line says the changeset was "
                "applied. "
                # U47 / S33-F2: the standing trust rule, stated once at the server
                # level as well as on every result that carries file content. A model
                # that reads the instructions and then a hostile cell has been told
                # twice; one of the two channels can be trimmed by a client, and the
                # result-level `content_trust` key is the one that always travels.
                + office_ops.UNTRUSTED_CONTENT_NOTE),
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
               server (`_trust_gate_check`, mcp_tool.py:4017). In v2 NO tool here is
               write-capable, so this fires on nothing and Debi sees no card — which is
               the ruling, not an oversight (see the module docstring). It is written
               anyway, deliberately: the day a tool on this server does gain a write,
               the gate is already armed and the tool gets a card by dropping its
               readOnlyHint alone, instead of shipping unattended because a config key
               also had to be remembered. Without it the default is `full`.
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
