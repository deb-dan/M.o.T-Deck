"""ROUTER — LOffice's vendored ONLYOFFICE editors and the COOP/COEP asset serving."""
from __future__ import annotations

import asyncio
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, Response
from ..core.appctx import PANEL, ROOT, _OO_ERR, _OOAI_ERR, _office, _oo, _ooai, app
from ..core.officelog import _office_log, _office_unavailable


# ══ LOFFICE TIER 2 — the vendored ONLYOFFICE editors ════════════════════════════
#
# Still not a component: `scripts/install_onlyoffice.sh` unzips two sha256-pinned
# CryptPad release zips into data/onlyoffice/ and this serves them read-only. No
# port, no daemon, no manifest key. bridge/oo.py owns every decision; these four
# routes are wiring.
#
# ⚠️ EVERY response below carries oo.ISOLATION_HEADERS. Without cross-origin
# isolation the spreadsheet editor hangs at "Loading spreadsheet" forever with zero
# console errors — measured in a real WKWebView on 2026-08-27. That includes the
# GLUE PAGE itself: a COEP document is the only kind that may embed the COEP editor
# frame, and `crossOriginIsolated` is a property of the whole page tree.

def _oo_unavailable() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "installed": False,
         "reason": f"the rich-editor module failed to load: {_OO_ERR}",
         "installer": "scripts/install_onlyoffice.sh"},
        status_code=503, headers=dict(_OO_FALLBACK_HEADERS))


# Used only when oo.py itself did not import; the literal is duplicated ONCE, here,
# so a broken oo.py cannot serve a page without the headers that make it work.
_OO_FALLBACK_HEADERS = {
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _oo_headers(extra: dict | None = None) -> dict:
    h = dict(_oo.ISOLATION_HEADERS if _oo is not None else _OO_FALLBACK_HEADERS)
    if extra:
        h.update(extra)
    return h


@app.get("/api/oo/status")
def oo_status() -> JSONResponse:
    """Is the rich editor installed, at which pins, and how do I install it?

    The page and the LOffice button BOTH branch on this, which is why "not
    installed" always carries a reason and the installer path: the button must never
    be a dead click.
    """
    if _oo is None:
        return _oo_unavailable()
    body = _oo.install_state(ROOT)
    return JSONResponse({"ok": True, **body},
                        headers=_oo_headers({"Cache-Control": _oo.NO_CACHE}))


@app.get("/oo-edit")
def oo_edit_page() -> Response:
    """The glue page — OUR integration, at /oo-edit?doc=<name>[&embed=1].

    ⚠️ THE OLD DOCSTRING HERE ARGUED FOR A NAVIGATION AND AGAINST AN IFRAME, AND
    DEBI'S 2026-08-27 ONE-EDITOR RULING REVERSED IT. Its second (deciding) reason was
    that embedding "would force the LOffice page ITSELF to carry COEP, and that page
    loads /assets/*". That premise was already stale when it was written: the Univer
    tier had been retired in the same wave, so office.html loads no subresource at
    all. See the audit in office_page() above — COEP on /office costs nothing.

    So this page is now BOTH:
      · `?embed=1` — the editing surface inside LOffice's centre column. Its own
        header/footer are hidden and the LOffice chrome around it does that job.
      · no `embed` — the standalone page, unchanged, kept as the rollback and as the
        way to open the editor on its own when something about the embed goes wrong.
    Parent and child are same-origin, so the contract between them is direct property
    access (window.LOfficeHost / window.LOfficeEmbed) rather than postMessage — the
    whole of it is documented at the top of bridge/panel/oo.html.
    """
    if _oo is None:
        return _oo_unavailable()
    return FileResponse(
        PANEL / "oo.html",
        headers=_oo_headers({"Cache-Control": _oo.NO_CACHE, "Pragma": "no-cache"}))


@app.get("/oo/{rel:path}")
def oo_asset(rel: str, request: Request) -> Response:
    """The bundle, read-only. Containment + forced MIME + immutable cache + brotli.

    Deliberately NOT a StaticFiles mount: a mount cannot add per-response headers
    without a middleware wrapper (the /assets precedent), and three of the four
    things this route does are per-response.
    """
    if _oo is None:
        return _oo_unavailable()
    # ⚠️ ONE GENERATED FILE INSIDE AN OTHERWISE READ-ONLY BUNDLE, and the whole
    # argument for it is in bridge/ooai.py under "THE SECOND CHANNEL": the editor asks
    # its host for `plugins.json`, the vendored bundle does not ship one, and the 404
    # is what makes the plugin-merge race lose. Answering it is configuration, not a
    # modification — nothing is written to disk. It is served ONLY when the bundle has
    # no plugins.json of its own AND the AI tab is genuinely usable.
    if _ooai is not None and rel.lstrip("/") == _ooai.SERVER_LIST_REL:
        on_disk, _ = _oo.bundle_target(ROOT, rel)
        if not on_disk:
            from ..core.modelid import _runner_loaded_id
            from ..core.procs import cfg
            st = _ooai.status(ROOT, cfg, _runner_loaded_id)
            base = str(request.base_url).rstrip("/")
            body = _ooai.server_plugins_json(
                st.get("enabled"), st.get("guid") or "",
                base + (st.get("config_url") or ""),
                base + (st.get("shim_url") or ""))
            if body is None:
                return JSONResponse({"ok": False, "error": "no server plugin list"},
                                    status_code=404, headers=_oo_headers())
            return JSONResponse(body, headers=_oo_headers(
                {"Cache-Control": _oo.NO_CACHE}))
    target, reason = _oo.bundle_target(ROOT, rel)
    if not target:
        # 404 for everything, including a refused traversal. Telling a caller which
        # of its guesses was "outside the bundle" is free reconnaissance.
        return JSONResponse({"ok": False, "error": reason}, status_code=404,
                            headers=_oo_headers())
    headers = _oo_headers({"Cache-Control": _oo.cache_control_for(rel)})
    media = _oo.media_type_for(target)
    # A Range request must never be answered with the .br sibling: FileResponse would
    # slice the COMPRESSED bytes and still claim Content-Encoding: br, which is a
    # corrupt response rather than a slow one. Ranges get the plain file.
    br = ("" if request.headers.get("range")
          else _oo.brotli_sibling(target, request.headers.get("accept-encoding", "")))
    if br:
        # The `.br` sibling shipped inside the zip. Content-Type stays that of the
        # UNCOMPRESSED file — brotli is a transfer encoding, not a format.
        headers["Content-Encoding"] = "br"
        headers["Vary"] = "Accept-Encoding"
        return FileResponse(br, media_type=media, headers=headers)
    return FileResponse(target, media_type=media, headers=headers)


# ══ THE IN-RIBBON AI TAB — ONLYOFFICE's own plugin, our runner ══════════════════
#
# Two routes, and they are the whole integration: one says whether the tab can work
# (and hands the glue page the localStorage seed that registers our runner), one
# serves the vendored plugin. Every decision lives in bridge/ooai.py.
#
# ⚠️ THESE CARRY oo.ISOLATION_HEADERS TOO, and for a reason that is easy to miss: the
# plugin is loaded into an IFRAME INSIDE the editor iframe, i.e. inside the
# cross-origin-isolated page tree. A nested document without CORP is refused by a
# require-corp embedder, so a plugin served without these headers does not "load
# slowly" — it does not load, and the ribbon tab never appears.

@app.get("/api/oo/fonts")
def oo_fonts() -> JSONResponse:
    """The bundle's font file names — the precondition for Download as PDF.

    x2t renders the PDF with real embedded faces and its wasm filesystem starts empty,
    so the glue page copies these in first. The list comes off disk (bridge/oo.py
    `font_files`) so a vendored bump cannot leave a hardcoded list quietly short.
    """
    if _oo is None:
        return _oo_unavailable()
    files = _oo.font_files(ROOT)
    return JSONResponse({"ok": True, "count": len(files),
                         "base": "/oo/" + _oo.FONTS_REL, "files": files},
                        headers=_oo_headers({"Cache-Control": _oo.NO_CACHE}))


@app.get("/api/oo/ai/status")
def oo_ai_status() -> JSONResponse:
    """Can the in-ribbon AI tab work right now, and with which model?

    Install state + the runner probe + the seed, in ONE body, because the glue page
    needs all three before it may construct the editor: the plugin list goes into the
    DocsAPI config, and a config is not something you can amend after the fact.
    """
    if _ooai is None:
        return JSONResponse(
            {"ok": False, "installed": False, "enabled": False,
             "gate": f"the in-ribbon AI module failed to load: {_OOAI_ERR}",
             "installer": "scripts/install_oo_ai_plugin.sh"},
            status_code=503, headers=_oo_headers())
    # Injected rather than imported inside ooai.py so that module stays unit-testable
    # without the model lane (which imports the world). See ooai.runner_state.
    from ..core.modelid import _runner_loaded_id
    from ..core.procs import cfg
    body = _ooai.status(ROOT, cfg, _runner_loaded_id)
    return JSONResponse({"ok": True, **body},
                        headers=_oo_headers({"Cache-Control": _oo.NO_CACHE
                                             if _oo is not None else "no-store"}))


@app.get("/api/oo/ai/shim/config.json")
def oo_ai_shim_config() -> JSONResponse:
    """OUR OWN invisible companion plugin descriptor — an upstream crash workaround.

    Read bridge/ooai.py's "THE COMPANION ENTRY" block before touching this: without a
    non-background plugin in the list, the vendored editor throws while registering
    plugins and the AI tab never appears. Generated, never a file on disk, and served
    under /api/ rather than /ooplug/ precisely so nobody can mistake it for part of the
    vendored ONLYOFFICE plugin.
    """
    if _ooai is None:
        return JSONResponse({"ok": False, "error": _OOAI_ERR}, status_code=503,
                            headers=_oo_headers())
    return JSONResponse(_ooai.shim_config(),
                        headers=_oo_headers({"Cache-Control": "no-store"}))


@app.get("/ooplug/{rel:path}")
def oo_plugin_asset(rel: str, request: Request) -> Response:
    """The vendored AI plugin, read-only. Same containment + MIME discipline as /oo/*.

    Its own route rather than a subtree of /oo/* because it is a DIFFERENT vendored
    artefact with a different installer and pin — putting it under /oo/ would make an
    editor-bundle re-unzip (which does `rm -rf`) delete it.
    """
    if _ooai is None:
        return JSONResponse({"ok": False, "error": "the in-ribbon AI module failed to "
                                                   f"load: {_OOAI_ERR}"},
                            status_code=503, headers=_oo_headers())
    target, reason = _ooai.plugin_target(ROOT, rel)
    if not target:
        # 404 for everything, refused traversals included — same reasoning as /oo/*.
        return JSONResponse({"ok": False, "error": reason}, status_code=404,
                            headers=_oo_headers())
    media = _oo.media_type_for(target) if _oo is not None else "application/octet-stream"
    # NOT immutable-cached like the editor bundle. The plugin is 8 MB, not 1 GB, so the
    # cache buys little — and it is the artefact most likely to be re-pinned, which
    # with an immutable year-long cache would need a hard reload nobody would think of.
    headers = _oo_headers({"Cache-Control": "public, max-age=300"})
    return FileResponse(target, media_type=media, headers=headers)


@app.post("/api/office/writeback/{name}")
async def office_writeback(name: str, req: Request) -> JSONResponse:
    """RAW .xlsx body → OVERWRITE that workbook. This is Save, not import.

    `?mtime=<float>` is the fence: the mtime the editor saw when it opened. A
    workbook that changed underneath gets a 409 and no write, unless `?force=1`.
    A daily .bak is taken first and the write is temp-file + os.replace — see
    oo.writeback, which owns all of that.

    ⚠️ NO `?mtime=` IS A DELIBERATE, LOGGED SKIP — NEVER AN IMPLIED ONE (bug-echo W-01).
    oo.html omits the param only when `openedMtime === null`, i.e. when the editor never
    learned the file's mtime at all. That caller genuinely cannot fence, and refusing its
    Save would trap the user's edits inside the editor to protect a file nobody else was
    writing — a worse loss than the one the fence prevents. So this route says `unfenced`
    OUT LOUD, in the call and in the log, instead of letting a default argument decide it
    silently for every future caller too.
    """
    if _oo is None:
        return _oo_unavailable()
    if _office is None:
        return _office_unavailable()
    raw = await req.body()
    q = req.query_params
    mtime = q.get("mtime")
    mtime = mtime if mtime not in (None, "") else None
    force = q.get("force") in ("1", "true", "yes")
    report, err = await asyncio.to_thread(
        _oo.writeback, _office, ROOT, name, raw, mtime, force, None,
        mtime is None)
    if report is None:
        status, reason = err
        _office_log(f"oo-writeback reject {name!r}: {status} {reason}")
        return JSONResponse({"ok": False, "error": reason}, status_code=status,
                            headers=_oo_headers())
    _office_log(f"oo-writeback saved {report['name']} ({report['bytes']} bytes"
                + (f", .bak {report['backup']}" if report["backup"] else "")
                + (", FORCED" if report["forced"] else "")
                + ("" if report.get("fenced") else
                   ", UNFENCED: the editor sent no mtime, so nothing checked whether "
                   "this overwrote a newer version")
                + ")")
    return JSONResponse({"ok": True, **report}, headers=_oo_headers())
