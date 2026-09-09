"""ROUTER — the LOffice lane: the document routes, the MCP server, the changeset surface."""
from __future__ import annotations

import asyncio
import os
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from ..core.appctx import PANEL, ROOT, _OFFICE_MCP_ERR, _office, _office_mcp, _office_ops, app
from ..core.hermescfg import _hermes_get_mcp, _hermes_write_mcp, hermes_cfg_gen
from ..core.officelog import _office_log, _office_unavailable
from .aider import _bridge_port
from .oo import _oo_headers


# ══ OFFICE LANE — slice 1, SHEETS ONLY (office-lane-recon §5/§7, 2026-08-21) ═════
#
# Not a component: Univer is vendored JS our own /assets mount already serves, and
# this is the .xlsx round-trip behind it (bridge/office.py). No port, no card, no
# daemon. Every route takes a NAME off the wire, so every route goes through
# office.doc_target — the `library_target`/`_deletable_target` containment rule.
#
# THE FIDELITY CONTRACT is single-sourced from office.FIDELITY_NOTE and printed on
# the page: a save writes a NEW workbook from the snapshot, so a file that came from
# Excel gets a `.bak` taken first (once per day, before the first save of the day).



@app.get("/office")
def office_page() -> FileResponse:
    """The Office tab's own document — deliberately not the panel: it must not carry
    the panel's poll loops (the /aider precedent).

    ⚠️ THIS PAGE IS CROSS-ORIGIN ISOLATED AS OF loffice-2026-08-28a, AND THAT IS THE
    CONSEQUENCE OF sample'S ONE-EDITOR RULING. The ONLYOFFICE editor now lives in a
    same-origin iframe filling this page's centre column instead of behind a
    navigation to /oo-edit. `crossOriginIsolated` is a property of the WHOLE frame
    tree — a COEP child inside a non-COEP parent is embedded but NOT isolated, and an
    un-isolated spreadsheet editor hangs for ever at "Loading spreadsheet" with zero
    console errors (measured, 2026-08-27). So the three headers move UP to the
    embedder as well.

    THE SUBRESOURCE AUDIT THAT MADE THIS SAFE (a require-corp document refuses any
    CROSS-ORIGIN subresource that does not opt in; same-origin ones are unaffected):
      · office.html contains NO external script or link tag at all — bridge/tests/
        test_office_grid.js pins that, and it is the whole reason this is a one-line
        change rather than a re-plumbing.
      · every fetch it makes is same-origin (/api/office/*, /api/oo/status,
        /api/chat/direct, /api/hermes/*, /api/models, /api/status).
      · the retired Univer loader's /assets/vendor/* URLs are same-origin too, so even
        the rollback path is unaffected.
      · the nested document, /oo-edit, already carries CORP: same-origin.
      · Download is `window.location.href = /api/office/download/...` — a NAVIGATION,
        not a subresource, and COEP does not gate those.
    ⚠️ COOP: same-origin also severs any window.opener relationship. This page never
    opens one: `goHome()` talks to the shell's message handler and otherwise sets
    location.href. Nothing here calls window.open.
    ⚠️ AND IT MUST STAY A TOP-LEVEL DOCUMENT. app/main.swift gives LOffice its own
    MOTDeckTab and bridge/panel/index.html marks the entry `view:null`, which makes it
    ineligible for the ⧉ peek overlay (peekEligible requires a view) — the one place
    that would otherwise put /office inside an iframe of the panel and silently cost
    it isolation.
    """
    return FileResponse(
        PANEL / "office.html",
        headers=_oo_headers({"Cache-Control": "no-store, no-cache, must-revalidate",
                             "Pragma": "no-cache"}),
    )


@app.post("/api/office/diag")
async def office_diag(req: Request) -> Response:
    """THE BOOT BEACON. `{stage, detail, boot, ms}` → the bridge log + its own file.

    Written after LOffice failed twice on a Mac none of us can reach, where the whole
    report a person can give is "the tab is blank" — a description that fits a stale
    cached document, a 404'd bundle, a JS engine that refused to parse ten megabytes,
    a mount into a zero-sized box and a web content process killed by jetsam, all
    equally. The page now says which one it is, while it happens, and the answer is a
    grep instead of a hypothesis.

    THREE RULES, all deliberate:
      * it NEVER fails. 204 for everything — junk body, wrong content-type, no body.
        A beacon endpoint that 4xx's would make the page's own error handling fire,
        i.e. the diagnostic would become a second fault to diagnose.
      * it works with `_office` UNAVAILABLE. That case (openpyxl missing, a syntax
        error in office.py) is one of the failures worth reporting, so the reporting
        path cannot depend on the module being importable — it degrades to the bridge
        log alone.
      * the body is parsed leniently. `navigator.sendBeacon` is the transport of
        choice precisely because it survives a page being torn down, and it sends
        text/plain or a Blob, never a tidy JSON content-type.
    """
    # `req.json()` — NOT `json.loads`: this module has no module-level `json` import
    # (every other body-reading route here uses `await req.json()` or a local alias),
    # and Starlette's own parser ignores the content-type, which is exactly what a
    # text/plain sendBeacon needs. ⚠️ The first draft of this route DID write
    # `json.loads`, the NameError was swallowed by the except below, and every single
    # beacon logged as "unparseable" — caught by driving the real page in a real
    # browser, which is the only reason this line is right.
    try:
        body = await req.json()
        if not isinstance(body, dict):
            body = {"stage": "malformed-beacon", "detail": str(body)[:200]}
    except Exception:                                            # noqa: BLE001
        body = {"stage": "unparseable-beacon"}
    stage, detail = body.get("stage"), body.get("detail")
    boot, ms = body.get("boot"), body.get("ms")
    if _office is not None:
        line = _office.write_diag(ROOT, stage, detail, boot, ms)
    else:
        line = f"(office module unavailable) stage={stage} detail={detail}"
    # ⚠️ THE TAG IS `loffice-diag`, NOT `diag`, AND THAT ONE WORD COST A ROUND.
    # These lines used to be logged as `[office] diag …`, and the instruction given to
    # sample was `grep loffice <bridge.log>`. Only ONE stage — script-start, whose detail
    # happens to contain the build stamp `loffice-2026-08-21x` — carried the string
    # "loffice" at all, so the grep returned exactly one line on a PERFECT boot. That
    # single line was then read as "the document stopped dead after the head script",
    # and a whole round went into a failure that may never have happened. Every line
    # is greppable by one stable token now.
    _office_log(f"loffice-diag {line}")
    return Response(status_code=204)


@app.get("/api/office/files")
def office_files() -> JSONResponse:
    if _office is None:
        return _office_unavailable()
    err = _office.openpyxl_error()
    return JSONResponse({"ok": True, "dir": _office.office_dir(ROOT),
                         "files": _office.list_docs(ROOT),
                         # ⚠️ TWO SENTENCES AS OF loffice-2026-08-28d, one per SAVE PATH
                         # (live finding L3): the editor's x2t save is materially higher
                         # fidelity than the openpyxl mapper, and the page used to print
                         # the mapper's limits over both of them.
                         "fidelity": _office.FIDELITY_NOTE,
                         "fidelity_editor": _office.FIDELITY_EDITOR_NOTE,
                         "ext": _office.DOC_EXT,
                         # STAGE 3: three types live here now. `ext` stays as the
                         # DEFAULT (what New makes when nobody says otherwise) so the
                         # page's existing uses do not shift meaning; `exts` and `kinds`
                         # are the new facts, and `fidelity_blob` is the per-type
                         # sentence for the two the bridge never rewrites.
                         "exts": list(_office.DOC_EXTS),
                         "kinds": _office.KINDS,
                         "kind_labels": _office.KIND_LABELS,
                         "fidelity_blob": _office.FIDELITY_BLOB_NOTE,
                         "roundtrip": not err,
                         "roundtrip_error": err})


@app.post("/api/office/new")
async def office_new(req: Request) -> JSONResponse:
    if _office is None:
        return _office_unavailable()
    try:
        body = await req.json()
    except Exception:                                            # noqa: BLE001
        body = {}
    # ⚠️ `step` IS THE TEMPLATE CARDS' OWN FLAG (live finding B2), AND IT DOES NOT WEAKEN
    # THE NEVER-CLOBBER RULING. A name the USER TYPED is still honoured literally and a
    # collision is still REFUSED, because quietly making `budget (2).xlsx` when somebody
    # asked for `budget.xlsx` hides the thing they need to know. A TEMPLATE CARD is a
    # different request — "give me one of these" — and refusing it left the card
    # PERMANENTLY DEAD after one use, with a red line offering no way forward, on a screen
    # listing the existing file two inches below. So the caller SAYS which of the two it
    # is, and a template takes the same ' (n)' walk import and the blank name already take.
    want = (body or {}).get("name") or ""
    # STAGE 3: WHICH TYPE. `kind` ("sheet" | "doc" | "slides") is what the start-screen
    # cards send, because a card is a statement of intent and an extension typed into a
    # name box is not; `ext` is accepted too for a caller that would rather be literal.
    # Anything unrecognised is refused rather than silently made into a spreadsheet.
    kind = str((body or {}).get("kind") or "").strip().lower()
    ext = str((body or {}).get("ext") or "").strip().lower()
    if kind and not ext:
        for _e, _k in _office.KINDS.items():
            if _k == kind:
                ext = _e
                break
        if not ext:
            return JSONResponse({"ok": False, "error": f"refused: there is no “{kind}” "
                                 "kind of file here"}, status_code=400)
    if ext and ext not in _office.DOC_EXTS:
        return JSONResponse({"ok": False, "error": "refused: LOffice stores "
                             + ", ".join(_office.DOC_EXTS)}, status_code=400)
    if bool((body or {}).get("step")) and str(want).strip():
        safe, reason = await asyncio.to_thread(
            _office.free_name, ROOT, (os.path.splitext(str(want))[0] + ext) if ext
            else want)
        if not safe:
            return JSONResponse({"ok": False, "error": reason}, status_code=400)
        want = safe
    name, reason = await asyncio.to_thread(_office.create_doc, ROOT, want, ext)
    if not name:
        return JSONResponse({"ok": False, "error": reason}, status_code=400)
    _office_log(f"created {name}")
    return JSONResponse({"ok": True, "name": name})


@app.get("/api/office/open/{name}")
async def office_open(name: str) -> JSONResponse:
    """The .xlsx as an IWorkbookData snapshot the Univer facade can take directly.

    ⚠️ `mtime` COMES BACK WITH IT, AND IT IS THE FENCE VALUE FOR THE NEXT SAVE (bug-echo
    BE-02). A caller that opens a workbook here has, by definition, the version it
    started from; sending it back as `expect_mtime` on /api/office/save is what turns
    that save from an unfenced overwrite into a refusal when somebody else got there
    first. `open_doc` reads it BEFORE the content, on purpose — see its comment.
    """
    if _office is None:
        return _office_unavailable()
    snap, reason = await asyncio.to_thread(_office.open_doc, ROOT, name)
    if snap is None:
        _office_log(f"open reject {name!r}: {reason}")
        return JSONResponse({"ok": False, "error": reason},
                            status_code=404 if "no such" in (reason or "") else 400)
    return JSONResponse({"ok": True, "name": name, "snapshot": snap,
                         "mtime": snap.get("file_mtime")})


@app.post("/api/office/save")
async def office_save(req: Request) -> JSONResponse:
    """{name, snapshot, expect_mtime?, force?} → the tier-1 snapshot write.

    ⚠️ `expect_mtime` IS THE FENCE, AND IT IS THE SAME CONTRACT /api/office/writeback
    ALREADY HAS (bug-echo BE-02). It is the mtime the caller last SAW on disk — for the
    grid that is office.html's `extSeen`, the baseline its 5s extCheck maintains; for the
    Quick lane's sort it is the mtime of the open it re-read a moment earlier. A workbook
    that moved underneath gets a 409 and NO write, unless `force` is sent — the shape
    oo.writeback's own fence uses, so the page's 409 handling is one grammar, not two.
    A save that carries neither is written UNFENCED and SAYS SO IN THE LOG (below): the
    one thing this route must never do again is overwrite a newer version in silence.
    """
    if _office is None:
        return _office_unavailable()
    try:
        body = await req.json()
    except Exception:                                            # noqa: BLE001
        body = {}
    if not isinstance(body, dict):        # a JSON body can legally be a list or a string
        body = {}
    name = (body.get("name") or "").strip()
    snapshot = body.get("snapshot")
    # `mtime` is accepted as well as `expect_mtime` because the writeback route spells it
    # that way on the wire (`?mtime=`), and one lane should not need two spellings.
    fence = body.get("expect_mtime")
    if fence in (None, ""):
        fence = body.get("mtime")
    fence = None if fence in (None, "") else fence
    force = bool(body.get("force"))
    # ⚠️ THE SKIP IS EXPLICIT AND LOUD, NEVER IMPLIED. `unfenced=True` is what makes
    # save_doc write without a fence at all, and this route passes it ONLY when the
    # caller sent nothing to fence with — which today is every tier-1 Save, because
    # bridge/panel/office.html does not yet put `extSeen` in the body (it HAS the value;
    # it is a one-line change in `save()` and in the Quick lane's `actWrite`, and that
    # page is owned elsewhere this round). Until it does, this line is the honest record
    # that the guarantee is missing rather than met.
    report, reason = await asyncio.to_thread(
        _office.save_doc, ROOT, name, snapshot, fence,
        force=force, unfenced=(fence is None))
    if report is None:
        _office_log(f"save reject {name!r}: {reason}")
        # The fence refusal is a 409 like the editor's, not a 400: nothing about the
        # request was malformed — the file moved. The page distinguishes them by status.
        code = 409 if reason == _office.SAVE_FENCE_REFUSAL else 400
        return JSONResponse({"ok": False, "error": reason}, status_code=code)
    _office_log(f"saved {report['name']} ({report['cells']} cells, "
                f"{report['sheets']} sheet(s))"
                + (f" — backup {report['backup']}" if report.get("backup") else "")
                + (", FORCED over a newer version" if report.get("forced") else "")
                + ("" if report.get("fenced") or report.get("created") else
                   " — UNFENCED: the caller sent no expect_mtime, so a write that landed "
                   "since it read the file has just been overwritten if there was one"))
    return JSONResponse({"ok": True, **report})


@app.post("/api/office/delete")
async def office_delete(req: Request) -> JSONResponse:
    if _office is None:
        return _office_unavailable()
    try:
        body = await req.json()
    except Exception:                                            # noqa: BLE001
        body = {}
    # ⚠️ `backups` IS OPT-IN AND IT EXISTS BECAUSE "This cannot be undone" WAS FALSE IN
    # BOTH DIRECTIONS (live finding B5). Deleting a workbook through this route left its
    # daily `<name>.YYYYMMDD.bak.xlsx` on disk, and `is_backup_name()` filters those out of
    # /api/office/files — so the copy was neither listed nor deletable from the UI. The
    # delete could therefore BE undone (from a file the user was not told about) and a user
    # deleting a workbook for privacy KEPT its contents. The default is still to keep them
    # (a backup exists to survive a mistake), but "delete it and its backups" is now a
    # thing she can mean.
    ok, reason = await asyncio.to_thread(
        _office.delete_doc, ROOT, ((body or {}).get("name") or ""),
        bool((body or {}).get("backups")))
    if not ok:
        _office_log(f"delete reject: {reason}")
        return JSONResponse({"ok": False, "error": reason}, status_code=400)
    _office_log("deleted a workbook"
                + (" and its backups" if (body or {}).get("backups") else ""))
    return JSONResponse({"ok": True})


@app.post("/api/office/rename")
async def office_rename(req: Request) -> JSONResponse:
    """{name, to} → the workbook under a new name. Never clobbers (office.rename_doc)."""
    if _office is None:
        return _office_unavailable()
    try:
        body = await req.json()
    except Exception:                                            # noqa: BLE001
        body = {}
    if not isinstance(body, dict):        # a JSON body can legally be a list or a string
        body = {}
    name, reason = await asyncio.to_thread(
        _office.rename_doc, ROOT, (body.get("name") or ""), (body.get("to") or ""))
    if not name:
        _office_log(f"rename reject: {reason}")
        return JSONResponse({"ok": False, "error": reason}, status_code=400)
    _office_log(f"renamed a workbook to {name}")
    return JSONResponse({"ok": True, "name": name})


@app.post("/api/office/upload")
async def office_upload(req: Request) -> JSONResponse:
    """RAW .xlsx / .docx / .pptx body + ?name= → import a file into data/office.

    Same body shape as /api/voice/library/save: one part, so multipart would buy
    nothing. The name is sanitized by office.valid_name like every other route here,
    the bytes are VERIFIED as a workbook before they are kept, and an existing file is
    never clobbered — the import comes back under ' (n)' and says so.
    """
    if _office is None:
        return _office_unavailable()
    raw = await req.body()
    if not raw:
        return JSONResponse({"ok": False, "error": "no file received"}, status_code=400)
    if len(raw) > _office.UPLOAD_MAX_BYTES:
        return JSONResponse(
            {"ok": False, "error": f"that file is {len(raw) // (1024 * 1024)} MB — "
                                   f"the import cap is "
                                   f"{_office.UPLOAD_MAX_BYTES // (1024 * 1024)} MB"},
            status_code=413)
    report, reason = await asyncio.to_thread(
        _office.import_doc, ROOT, (req.query_params.get("name") or ""), raw)
    if report is None:
        _office_log(f"import reject: {reason}")
        return JSONResponse({"ok": False, "error": reason}, status_code=400)
    _office_log(f"imported {report['name']} ({report['bytes']} bytes)")
    return JSONResponse({"ok": True, **report})


@app.get("/api/office/download/{name}")
def office_download(name: str) -> Response:
    """The real file, for Save-a-copy out of the tab. Same containment as delete."""
    if _office is None:
        return _office_unavailable()
    target, reason = _office.doc_target(ROOT, name)
    if not target:
        raise HTTPException(404, reason)
    # ⚠️ THE MIME FOLLOWS THE TYPE (stage 3). It was hardcoded to the spreadsheet type,
    # which for a .docx would have been a download the OS opens in the wrong app — and
    # for the EDITOR's own fetch of the bytes, a Content-Type that contradicts the file.
    return FileResponse(target, media_type=_office.MEDIA_TYPES.get(
        _office.ext_of(target), "application/octet-stream"),
        filename=os.path.basename(target))


# ══ THE OFFICE AGENT LANE — MCP server + the open-dirty heartbeat ════════════════
#
# bridge/office_mcp.py mounts the MCP server itself (POST/GET/DELETE /mcp/office). The
# three routes here are the surfaces that are NOT MCP:
#
#   POST /api/office/heartbeat  — the page tells the bridge "I have <name> open and it
#                                 is (not) dirty", so a write tool can refuse a
#                                 workbook with unsaved edits in it. ADVISORY, TTL'd,
#                                 NEVER a lock file: see office_ops's own comment. S2
#                                 (the panel lane) is what will call it; until then
#                                 nothing registers and every write is allowed, which
#                                 is the correct behaviour for a page that is closed.
#   GET  /api/office/mcp        — is the loffice server in Hermes's config, does it
#                                 MATCH what this bridge would write, and which tools
#                                 need an approval card. The Capabilities pane's
#                                 out-of-sync/Adopt reconciliation reads this.
#   POST /api/office/mcp        — {on} → write or remove the entry. The same
#                                 idempotent yaml round-trip the Browse and voice
#                                 toggles use (_hermes_write_mcp), so it can never
#                                 disturb another server in the same map.
#
# ⚠️ THE CONFIG ENTRY IS NOT WRITTEN AT IMPORT TIME, and that is deliberate: the
# config-gen step is scripts/start_component.sh's hermes branch (it runs on every
# Hermes start, so it survives a pin bump the way the path-guard plugin seed does), and
# a bridge that wrote ~/.hermes/config.yaml merely by being IMPORTED would also write it
# during every test run that imports bridge.app — which is exactly what
# bridge/tests/test_voice_mcp.py's exact-set assertions would trip over.

def _office_mcp_unavailable() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": "the office agent-lane modules failed to load: "
                               f"{_OFFICE_MCP_ERR}"}, status_code=503)


@app.post("/api/office/heartbeat")
async def office_heartbeat(req: Request) -> JSONResponse:
    """{name, dirty} → the advisory open-file registry. {name, close:true} forgets it."""
    if _office_ops is None:
        return _office_mcp_unavailable()
    try:
        body = await req.json()
    except Exception:                            # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    name = body.get("name") or ""
    if body.get("close"):
        _office_ops.heartbeat_clear(name)
        return JSONResponse({"ok": True, "name": name, "closed": True})
    out = _office_ops.heartbeat(name, bool(body.get("dirty")))
    return JSONResponse(out, status_code=200 if out.get("ok") else 400)


@app.get("/api/office/mcp")
def office_mcp_status() -> JSONResponse:
    if _office_mcp is None:
        return _office_mcp_unavailable()
    want = _office_mcp.hermes_entry(_bridge_port())
    got = _hermes_get_mcp(_office_mcp.SERVER_NAME)
    return JSONResponse({
        "ok": True, "name": _office_mcp.SERVER_NAME, "path": _office_mcp.MOUNT_PATH,
        "registered": got is not None, "entry": got, "expected": want,
        "in_sync": got == want,
        # Which tools Hermes will put behind an approval card, and why. In Hermes that
        # is the server's `trust` PLUS each tool's readOnlyHint annotation, never a
        # per-tool config field (see bridge/office_mcp.py's docstring) — and as of the
        # changeset ruling the honest answer is NONE OF THEM, because none of them can
        # write. Consent moved to the panel's changeset card, and `consent` below says
        # so rather than leaving a reader to infer it from an empty list.
        "approval": {"mechanism": "mcp_servers.loffice.trust=untrusted + per-tool "
                                  "annotations.readOnlyHint",
                     "gated": _office_mcp.write_tool_names(),
                     "ungated": _office_mcp.read_tool_names()},
        # ⚠️ THE KEY IS `surface`, AND THE OBVIOUS SHORTER NAME FOR IT IS UNAVAILABLE
        # ON PURPOSE. bridge/tests/test_starter_voices.py asserts that the
        # datasets-server filter keyword (w-h-e-r-e, in quotes) appears NOWHERE in this
        # file — it is guarding the HuggingFace /rows call against ever growing that
        # param. A broad negative, but a real one, and renaming one key here is far
        # cheaper than weakening someone else's fence. Do not "tidy" this back.
        "consent": {"surface": "the LOffice panel's changeset card",
                    "apply_route": "POST /api/office/changeset/{id}/apply",
                    "why": "every tool on this server is read-only, so Hermes has "
                           "nothing to card; office_stage_changes records a proposal "
                           "the bridge holds and only a person can apply it"},
        "tools": [t["name"] for t in _office_mcp.tool_specs()],
        "catalog_sha256": _office_mcp.catalog_sha256(),
    })


@app.post("/api/office/mcp")
async def office_mcp_register(req: Request) -> JSONResponse:
    """{on} → add/remove `mcp_servers.loffice`. Idempotent on both sides."""
    if _office_mcp is None:
        return _office_mcp_unavailable()
    try:
        body = await req.json()
    except Exception:                            # noqa: BLE001
        body = {}
    on = bool((body or {}).get("on", True)) if isinstance(body, dict) else True
    entry = _office_mcp.hermes_entry(_bridge_port()) if on else None
    if on and not entry:
        return JSONResponse({"ok": False, "error": "the bridge port is unusable"},
                            status_code=500)
    try:
        present = _hermes_write_mcp(_office_mcp.SERVER_NAME, entry)
    except Exception as e:                       # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"could not write Hermes's config: "
                                                   f"{str(e)[:160]}"}, status_code=500)
    _office_log(f"mcp register on={on} present={present}")
    return JSONResponse({"ok": present is on, "on": on, "registered": bool(present),
                         "gen": hermes_cfg_gen()})


# ══ THE CHANGESET SURFACE — the four routes only the PANEL can reach ════════════
#
# docs/FABLE-AGENT-CHANGESET-SPEC.md §1/§2: the MCP write tools are gone, staging holds
# a proposal, and APPLY IS A HUMAN GESTURE. That is what these routes are — the button
# end of the wire. No MCP method reaches any of them, and the page adds no writer of its
# own: it POSTs here and then RELOADS the document.
#
#   GET  /api/office/changeset            — the ONE pending changeset for
#                                           ?file=&session=, plus any outcome lines the
#                                           next agent turn still has to be told about
#   POST /api/office/changeset/{id}/apply — apply it, atomically, and answer with a
#                                           RECEIPT (the only thing the panel's success
#                                           badge renders from)
#   POST /api/office/changeset/{id}/dismiss — drop it, and tell the session it was never
#                                           applied
#   POST /api/office/changeset/{id}/undo  — restore the checkpoint that apply pushed,
#                                           behind an mtime fence
#
# ⚠️ THE ID IS THE WHOLE ADDRESS AND IT IS A 64-BIT SECRET (office_ops.stage_changes →
# secrets.token_hex(8)). These routes are loopback-only like the rest of this bridge, and
# an id cannot be guessed into a write of a workbook the caller never staged.

def _changeset_reply(pair, log):
    out, reason = pair
    if out is None:
        _office_log(f"{log} reject: {reason}")
        return JSONResponse({"ok": False, "error": reason}, status_code=400)
    _office_log(f"{log} ok")
    return JSONResponse({"ok": True, **out})


@app.get("/api/office/changeset")
def office_changeset_pending(file: str = "", session: str = "") -> JSONResponse:
    """The pending proposal for that workbook, or null. The panel polls this after a
    turn ends; it is also what a reloaded page uses to find the card again."""
    if _office_ops is None:
        return _office_mcp_unavailable()
    cs = _office_ops.pending_changeset(session or None, file or None)
    return JSONResponse({
        "ok": True,
        "changeset": (_office_ops.public_changeset(cs) if cs else None),
        # The honest fallback for the spec's "inject one system line into the Hermes
        # session": the gateway has no way to append a message to an idle session, so
        # the bridge queues the line and the PANEL prepends it to the next agent
        # message. See office_ops.push_session_line for the measured reasoning.
        "session_lines": _office_ops.peek_session_lines(session or None),
        "ttl_s": _office_ops.CHANGESET_TTL,
    })


@app.post("/api/office/changeset/{cid}/apply")
async def office_changeset_apply(cid: str) -> JSONResponse:
    """APPLY. Atomic, all-or-nothing, checkpointed, and it answers with a receipt."""
    if _office_ops is None:
        return _office_mcp_unavailable()
    out, reason = await asyncio.to_thread(_office_ops.apply_changeset, ROOT, cid)
    if out is None:
        _office_log(f"changeset apply reject {cid}: {reason}")
        return JSONResponse({"ok": False, "error": reason}, status_code=400)
    _office_log(f"changeset applied {cid} → {out['name']} "
                f"({out['cells_written']} cells, receipt {out['receipt']})")
    return JSONResponse({"ok": True, **out})


@app.post("/api/office/changeset/{cid}/dismiss")
async def office_changeset_dismiss(cid: str) -> JSONResponse:
    if _office_ops is None:
        return _office_mcp_unavailable()
    return _changeset_reply(
        await asyncio.to_thread(_office_ops.dismiss_changeset, ROOT, cid),
        f"changeset dismiss {cid}")


@app.post("/api/office/changeset/{cid}/undo")
async def office_changeset_undo(cid: str) -> JSONResponse:
    """"Undo this change" — the checkpoint back, or an honest refusal if the workbook
    moved since the apply."""
    if _office_ops is None:
        return _office_mcp_unavailable()
    return _changeset_reply(
        await asyncio.to_thread(_office_ops.undo_changeset, ROOT, cid),
        f"changeset undo {cid}")


@app.get("/api/office/checkpoints/{name}")
def office_checkpoints(name: str) -> JSONResponse:
    """The checkpoint stack for one workbook, newest first. Read-only; the panel uses it
    to say whether an undo is still possible after a page reload."""
    if _office_ops is None:
        return _office_mcp_unavailable()
    safe, reason = _office.valid_name(name) if _office is not None else (None, "no office")
    if not safe:
        return JSONResponse({"ok": False, "error": reason}, status_code=400)
    rows = [{"changeset_id": e["changeset_id"], "at": e["at"],
             "size_bytes": e["size_bytes"]}
            for e in _office_ops.list_checkpoints(ROOT, safe)]
    return JSONResponse({"ok": True, "name": safe, "keep": _office_ops.CHECKPOINT_KEEP,
                         "checkpoints": rows})


if _office_mcp is not None:
    _office_mcp.configure(ROOT)
    app.include_router(_office_mcp.build_router())
