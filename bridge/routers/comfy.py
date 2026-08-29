"""ROUTER — the ComfyUI first-party GENERATE surface (S1: image + video).

Spec: docs/FABLE-COMFY-SURFACE-SPEC.md · research: docs/research/2026-08-29-comfyui-tab.md.
The page is bridge/panel/comfy.html at GET /comfy; everything below it is /api/comfy/*.

WHAT THIS LANE IS FOR (obligation 1). Type a sentence, get a picture or a short clip,
without learning node graphs — with honest numbers (disk, minutes, memory) BEFORE
committing, and the stock ComfyUI tab left intact as the power exit. Deliberately NOT a
workflow editor, a custom-node manager or an arbitrary-URL downloader.

⚠️ THE CURATION, THE CATALOG AND THE GRAPH BUILDERS LIVE IN bridge/core/comfycur.py
   (ledger S8, extracted when this file hit the 1,500-line facade ceiling). This file is
   the ROUTES, the ComfyUI client, the download engine, the job follower and the gallery.
   Everything comfycur owns is re-exported below, because ~40 assertions and four other
   modules name these symbols through `bridge.routers.comfy` (and through the app
   facade) and a refactor that moves a symbol is not allowed to move its address.

⚠️ FIVE THINGS THE NEXT READER MUST NOT RE-DERIVE ────────────────────────────────────

1. THE PATHS ARE THE APP'S, NOT THE REPO'S. A repo checkout has no data/comfyui; the
   running instance belongs to the SHIPPED app. Everything resolves off ROOT.

2. THE CURATION IS GENERATED AND THE CATALOG IS DISCOVERED. `PICKS` is the RECOMMENDED
   SUBSET (sha-pinned, licence read); `catalog()` is the superset — every template-native
   model the vendored registry can drive, re-measured against the disk on every call, so
   deleting a model drops it off and downloading one makes its workflows appear.

3. SIZE AND SHA ARE CHECKED, AND A FAILED CHECK IS NOT A DOWNLOAD. A card claiming
   "downloaded" over a truncated file resurfaces hours later as an inscrutable ComfyUI
   error, so the .part is renamed only after BOTH the byte count and the sha256 match.
   ⚠️ A DISCOVERED file has no sha256 pin (upstream's registry carries none) — it is
   verified against the size the SERVER declared, and the card SAYS which of the two
   checks it got rather than implying the stronger one.

4. THE DISK VERDICT COMES FROM THE MODELS DIRECTORY ITSELF — not ROOT, not "/". Here
   "/" is the sealed system volume and the data volume is a different filesystem, so
   statvfs'ing the wrong one is a confidently wrong number (the LIE class).

5. EVERY GATE HERE IS ADVISORY (Debi's 2026-08-28 ruling): numbers and a
   recommendation, never a disabled button. The only refusals are for things that
   cannot work at all (a missing model file, ComfyUI down, a template this engine
   cannot run), each naming its own fix.

STOCK NODES ONLY (the supply-chain fence, research §4.1: the ComfyUI_LLMVISION and
Ultralytics incidents). The curated builders emit only `ALLOWED_NODES`; a DISCOVERED
template is fenced against the running server's own `/object_info`, where a class from a
third-party pack answers `python_module: custom_nodes.<pack>` and is refused by name.
`custom_nodes/` stays empty and test_comfy_lane.py fails if either fence is weakened.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path

import httpx
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, Response

from ..core.appctx import PANEL, ROOT, app
from ..core.events import publish
from ..core.procs import cfg

# ── THE RE-EXPORTED CURATION LAYER (bridge/core/comfycur.py) ─────────────────
# Explicit, not `import *`: the underscore names below are named from the suite and
# from this file, and a star import would silently drop exactly those.
from ..core.comfycur import (                                    # noqa: F401
    ALLOWED_NODES, CAP_WHY, DISK_HEADROOM, LOADER_DIRS, MEASURED, OUT_PREFIX,
    PICKS, PICK_BY_ID, PRIMARY_DIRS, REFUSED_MODELS, SIZES, STARTER_CAP_BYTES,
    _dim, _disk, _file_state, _measure_load, _measure_save, _wan_length,
    apply_controls, build_graph, cap_statement, catalog, comfy_base, curation,
    disk_verdict, dynamic_fence_violations, fence_violations, gb, graph_classes,
    graph_steps, input_dir, measure_note, model_key, models_dir, output_dir,
    pick_card, retarget_outputs, size_known, sizes_save, state_dir, stock_class,
    template_graph, template_models, templates_dir, ui_to_api, workflow_controls,
    workflow_files,
)

# ── constants ────────────────────────────────────────────────────────────────
COMFY_DEFAULT_PORT = 8188       # harness.yaml components.comfyui.port overrides it
DL_TICK_S = 2.0                 # SSE progress cadence — the downloads lane's number
JOB_TICK_S = 1.0                # queue/progress poll cadence while a job is live
OBJECT_INFO_TTL = 60.0          # the node table changes only when the engine restarts
CATALOG_TTL = 4.0               # a disk re-scan per render is honest but not free


def comfy_port() -> int:
    try:
        c = (cfg().get("components") or {}).get("comfyui") or {}
        return int(c.get("port") or COMFY_DEFAULT_PORT)
    except Exception:                                            # noqa: BLE001
        return COMFY_DEFAULT_PORT


def comfy_url(path: str = "") -> str:
    return f"http://127.0.0.1:{comfy_port()}{path}"


def comfy_pid() -> "int | None":
    try:
        v = int((ROOT / "data" / "comfyui.pid").read_text().strip())
    except (OSError, ValueError):
        return None
    return v if v > 0 else None


def _footprint(pid: "int | None") -> "int | None":
    """ComfyUI's phys_footprint right now, or None if we cannot see the process."""
    if not pid:
        return None
    try:
        from ..core import memory as _mem
        r = _mem.proc_footprint(int(pid))
    except Exception:                                            # noqa: BLE001
        return None
    return int(r["footprint"]) if r else None


# ══ THE COMFYUI CLIENT ═══════════════════════════════════════════════════════
_CX = httpx.AsyncClient(timeout=httpx.Timeout(10, read=30))
_DL = httpx.AsyncClient(timeout=httpx.Timeout(30, read=120), follow_redirects=True)


async def _cget(path: str, timeout: float = 6.0):
    r = await _CX.get(comfy_url(path), timeout=timeout)
    r.raise_for_status()
    return r.json()


# /object_info is ~2 MB and answers the same for the life of one engine process, so it
# is fetched at most once a minute. It is NOT cached across an engine restart: the pid
# is part of the key, because a restarted engine is exactly when the node table could
# have changed and a stale table would fence against the wrong evidence.
_INFO = {"at": 0.0, "pid": None, "data": None, "error": None}


async def object_info(force: bool = False) -> dict:
    now = time.time()
    pid = comfy_pid()
    if (not force and _INFO["data"] is not None and _INFO["pid"] == pid
            and now - _INFO["at"] < OBJECT_INFO_TTL):
        return _INFO["data"]
    try:
        data = await _cget("/object_info", timeout=25.0)
    except Exception as e:                                       # noqa: BLE001
        _INFO["error"] = f"{type(e).__name__}: {e}"[:160]
        return _INFO["data"] or {}
    _INFO.update(at=now, pid=pid, data=data, error=None)
    return data


async def comfy_state() -> dict:
    """Reachable? version? pid? NEVER raises — the page must render regardless."""
    out = {"up": False, "port": comfy_port(), "url": comfy_url(), "pid": comfy_pid(),
           "version": None, "error": None, "custom_nodes": None}
    try:
        st = await _cget("/system_stats")
        sysd = st.get("system") or {}
        out.update(up=True, version=sysd.get("comfyui_version"),
                   templates_version=sysd.get("installed_templates_version"),
                   torch=sysd.get("pytorch_version"))
    except Exception as e:                                       # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"[:200]
    # The supply-chain fence, REPORTED rather than merely tested: S1–S3 ship with zero.
    try:
        cn = comfy_base() / "custom_nodes"
        out["custom_nodes"] = sorted(
            d.name for d in cn.iterdir()
            if d.is_dir() and not d.name.startswith((".", "__")))
    except OSError:
        out["custom_nodes"] = []
    return out


async def validate_pick(pick_id: str, mode: str) -> dict:
    """CONNECT-TIME VALIDATION — the Krita-plugin discipline, before submit.

    Three checks against the LIVE server, each failure named with its own fix: is
    ComfyUI up; does every node class exist in /object_info (the stock-node fence,
    verified against the running server rather than assumed); is every model file in
    /models/{folder} — the SERVER's view, not our stat(). ⚠️ WHY NOT JUST LET POST
    /prompt FAIL: it would (`node_errors` is authoritative and we surface it too) but
    AFTER the click, in a payload shaped for a graph editor, and it cannot say "press
    Download on the Wan card"."""
    spec = PICK_BY_ID.get(pick_id)
    if spec is None:
        return {"ok": False, "reason": "unknown model", "missing_models": [],
                "missing_nodes": []}
    graph = build_graph(pick_id, mode, {"seed": 0, "prompt": "x"})
    out = {"ok": False, "pick": pick_id, "mode": mode, "missing_nodes": [],
           "missing_models": [], "reason": None,
           "fence_violations": fence_violations(graph)}
    try:
        info = await _cget("/object_info", timeout=20.0)
    except Exception as e:                                       # noqa: BLE001
        out["reason"] = (f"ComfyUI is not answering on {comfy_url()} "
                         f"({type(e).__name__}). Start it from MOT Deck → Components.")
        return out
    have = set(info or {})
    out["missing_nodes"] = sorted(c for c in graph_classes(graph) if c not in have)
    # /models/{folder} is the server's own listing — an empty/500 answer is treated as
    # "cannot confirm", and we fall back to our own stat() rather than inventing a
    # refusal for a model that is sitting right there.
    _busy = cdl_inflight(pick_id)
    for f in spec["files"]:
        seen = None
        try:
            seen = await _cget(f"/models/{f['directory']}")
        except Exception:                                        # noqa: BLE001
            seen = None
        st = _file_state(f)
        if seen is not None:
            ok = f["name"] in (seen or [])
        else:
            ok = st["present"]
        if not ok or st["state"] == "corrupt":
            out["missing_models"].append({
                "directory": f["directory"], "name": f["name"],
                "bytes": f["bytes"], "size_h": gb(f["bytes"]),
                "state": st["state"], "pick": pick_id, "pick_title": spec["title"],
                # ⚠️ "PRESS DOWNLOAD" WHILE IT IS DOWNLOADING IS A SMALL LIE, and this is
                # the likeliest moment to hit the refusal. Say what is happening instead.
                "how": ((f"“{spec['title']}” is downloading right now "
                         f"({_cdl_json(_busy)['pct']}% of {_cdl_json(_busy)['total_h']}) "
                         f"— this will work as soon as it lands.") if _busy else
                        f"Download “{spec['title']}” on the Models card above — it puts "
                        f"{f['name']} in models/{f['directory']}/."),
            })
    if out["missing_nodes"]:
        out["reason"] = ("this ComfyUI is missing node classes this graph needs: "
                         + ", ".join(out["missing_nodes"])
                         + ". That should be impossible on a stock v0.34.x — check the "
                           "component install.")
    elif out["missing_models"]:
        names = ", ".join(m["name"] for m in out["missing_models"])
        out["reason"] = f"missing model file(s): {names}"
    elif out["fence_violations"]:
        out["reason"] = ("this graph would use non-stock nodes ("
                         + ", ".join(out["fence_violations"]) + ") — refused.")
    else:
        out["ok"] = True
    return out


# ══ THE DYNAMIC CATALOG, LIVE ════════════════════════════════════════════════
# comfycur.catalog() answers "what is on this disk"; this half adds the two verdicts
# only the running engine can give — does the template CONVERT, and does it stay inside
# the supply-chain fence — and it caches for four seconds so a 1 s poll during a job
# does not re-read 533 template files every tick.
_CAT = {"at": 0.0, "data": None}


async def catalog_live(force: bool = False) -> dict:
    now = time.time()
    if not force and _CAT["data"] is not None and now - _CAT["at"] < CATALOG_TTL:
        return _CAT["data"]
    cat = catalog()
    info = await object_info()
    for m in cat.get("models") or []:
        for w in m.get("workflows") or []:
            w.update(runnable=None, run_reason=None, controls=[], needs=[])
            if not w["complete"]:
                w["run_reason"] = "files are missing"
                w["runnable"] = False
                continue
            if not info:
                w["run_reason"] = ("ComfyUI is not answering, so this template has not "
                                   "been checked against its node table")
                continue
            conv = ui_to_api(template_graph(w["template"]) or {}, info)
            if not conv["ok"]:
                w.update(runnable=False, run_reason=conv["reason"])
                continue
            bad = dynamic_fence_violations(conv["graph"], info)
            if bad:
                w.update(runnable=False,
                         run_reason=("refused: " + ", ".join(bad) + " comes from a "
                                     "third-party node pack, not from ComfyUI itself"))
                continue
            ctl = workflow_controls(conv["graph"], conv["widgets"])
            w.update(runnable=True, run_reason=None,
                     controls=sorted(ctl.keys()),
                     needs=[k for k in ("image", "video", "audio") if k in ctl],
                     defaults={k: v.get("default") for k, v in ctl.items()
                               if k in ("width", "height", "length", "steps", "cfg",
                                        "fps", "negative")})
    _CAT.update(at=now, data=cat)
    return cat


def catalog_invalidate() -> None:
    _CAT.update(at=0.0, data=None)


def find_workflow(cat: dict, name: str) -> "tuple | None":
    for m in cat.get("models") or []:
        for w in m.get("workflows") or []:
            if w["id"] == name:
                return m, w
    return None


# ── THE SIZE PROBE — HEAD, cached, background, never blocking a render ───────
# A file that is not on disk has no size, and inventing one under a Get button is the
# LIE class. So the size is ASKED for, once per URL, in the background, and the answer
# is cached forever; until it arrives the row says the size is not known yet.
_PROBING: set = set()


async def _probe_one(url: str) -> None:
    try:
        r = await _DL.head(url, timeout=20.0)
        n = int(r.headers.get("content-length") or 0)
        if r.status_code < 400 and n > 0:
            SIZES[url] = n
            sizes_save()
            catalog_invalidate()
    except Exception:                                            # noqa: BLE001
        pass                       # a probe that fails leaves the row saying "unknown"
    finally:
        _PROBING.discard(url)


def probe_sizes(cat: dict, limit: int = 12) -> int:
    """Kick off HEADs for the missing files whose size we have never asked about."""
    started = 0
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return 0
    for m in cat.get("models") or []:
        for w in m.get("workflows") or []:
            for f in w.get("files") or []:
                url = f.get("url")
                if (not url or f.get("present") or url in SIZES or url in _PROBING
                        or not str(url).startswith("https://")):
                    continue
                if started >= limit:
                    return started
                _PROBING.add(url)
                loop.create_task(_probe_one(url))
                started += 1
    return started


@app.get("/comfy")
def comfy_page() -> FileResponse:
    """The Generate tab's own document — not the panel (the /aider + /office
    precedent): it must not carry the panel's poll loops."""
    return FileResponse(
        PANEL / "comfy.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate",
                 "Pragma": "no-cache"})


@app.get("/api/comfy/state")
async def api_comfy_state() -> JSONResponse:
    """Everything the page needs for a full render, in ONE request — the empty state,
    the cards, the disk strip and the gallery total all have to agree, and independent
    fetches can disagree mid-download."""
    st = await comfy_state()
    cur = curation()
    gal = gallery()
    return JSONResponse({
        "ok": True, "comfy": st, "curation": cur,
        "downloads": [_cdl_json(e) for e in CDL.values()],
        "jobs": [_job_json(j) for j in JOBS.values()],
        "gallery_total_bytes": gal["total_bytes"],
        "gallery_total_h": gb(gal["total_bytes"]),
        "gallery_count": len(gal["items"]),
        "output_dir": str(output_dir()),
        "measure": MEASURED,
        "fence": {"allowed_nodes": sorted(ALLOWED_NODES),
                  "custom_nodes": st.get("custom_nodes") or []},
    })


@app.get("/api/comfy/catalog")
async def api_comfy_catalog(refresh: int = 0) -> JSONResponse:
    """The DYNAMIC catalogue — Debi's ask, 2026-08-29: delete a model and it drops off,
    download one and its workflows appear, with no list in this repo to edit."""
    cat = await catalog_live(force=bool(refresh))
    probing = probe_sizes(cat)
    return JSONResponse({"ok": True, "catalog": cat, "probing": probing,
                         "engine_up": bool(_INFO.get("data")),
                         "models_dir": str(models_dir())})


@app.get("/api/comfy/sources")
async def api_comfy_sources() -> JSONResponse:
    """The media a workflow that takes an input can be pointed AT.

    ⚠️ WITHOUT THIS, EVERY IMAGE-TO-VIDEO WORKFLOW IS A DEAD END — it converts, it is
    fenced, its files are on disk, and it cannot run because nothing has ever put a
    picture in ComfyUI's input/ directory. What it lists is real: this surface's own
    gallery (a still you made a minute ago is the obvious source) and whatever is
    already in input/. Nothing is fabricated and nothing is copied until you submit."""
    out = []
    for it in gallery()["items"]:
        if it.get("kind") in ("image", "video") and it.get("state") != "missing":
            out.append({"origin": "gallery", "kind": it["kind"],
                        "filename": it["filename"], "subfolder": it.get("subfolder") or "",
                        "label": it["filename"], "at": it.get("at")})
    # ⚠️ DEDUPED ON THE FILE NAME, AND THE GALLERY COPY WINS. Submitting a gallery
    # picture COPIES it into input/, so the second time you reach for the same still it
    # is in both places — and the picker then offered two rows with the identical label
    # and no way to tell them apart (walked 2026-08-29). Two controls that look the same
    # and may not do the same thing is the ambiguity this surface exists to remove.
    seen = {r["filename"] for r in out}
    try:
        for p in sorted(input_dir().iterdir()):
            if p.is_file() and not p.name.startswith(".") and p.name not in seen:
                k = _kind(p.name)
                if k in ("image", "video", "audio"):
                    seen.add(p.name)
                    out.append({"origin": "input", "kind": k, "filename": p.name,
                                "subfolder": "", "label": p.name,
                                "at": p.stat().st_mtime})
    except OSError:
        pass
    out.sort(key=lambda r: -(r.get("at") or 0))
    return JSONResponse({"ok": True, "sources": out, "input_dir": str(input_dir())})


def stage_source(src: dict) -> "str | None":
    """Put a chosen source file where LoadImage/LoadVideo can see it, and return the
    name to write into the widget. A gallery file is COPIED (never moved: the gallery
    keeps everything), and a file already in input/ is used where it lies."""
    fn = str((src or {}).get("filename") or "")
    if not fn:
        return None
    if (src.get("origin") or "gallery") == "input":
        return fn if (input_dir() / fn).is_file() else None
    root = output_dir().resolve()
    try:
        p = (root / (src.get("subfolder") or "") / fn).resolve()
        p.relative_to(root)
    except (ValueError, OSError):
        return None
    if not p.is_file():
        return None
    try:
        input_dir().mkdir(parents=True, exist_ok=True)
        dest = input_dir() / p.name
        if not dest.exists() or dest.stat().st_size != p.stat().st_size:
            shutil.copy2(str(p), str(dest))
    except OSError:
        return None
    return dest.name


# ══ DOWNLOADS — resumable, size- AND (where pinned) sha-verified ═════════════
CDL: dict = {}
_CDL_SEQ = {"n": 0}


def _cdl_json(e: dict) -> dict:
    out = {k: v for k, v in e.items() if k != "task"}
    done = sum(int(f.get("done") or 0) for f in e["files"])
    total = sum(int(f["bytes"] or 0) for f in e["files"])
    out["done_bytes"], out["total_bytes"] = done, total
    out["pct"] = round(100.0 * done / total, 1) if total else 0.0
    out["done_h"], out["total_h"] = gb(done), gb(total) if total else "?"
    return out


async def _sha256(path: Path) -> str:
    """Hash a multi-GB file WITHOUT blocking the event loop.

    ⚠️ NOT INLINE: hashing 6.7 GB on the loop would freeze every other bridge route for
    the duration, which reads as "the app hung mid-download"."""
    def _run() -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 22), b""):
                h.update(chunk)
        return h.hexdigest()
    return await asyncio.to_thread(_run)


async def _run_cdl(dl_id: str) -> None:
    e = CDL.get(dl_id)
    if not e:
        return
    last_push = 0.0
    try:
        for f in e["files"]:
            dest = Path(f["dest"])
            part = Path(str(dest) + ".part")
            want = int(f["bytes"]) if f.get("bytes") else None
            if dest.exists() and want and dest.stat().st_size == want:
                f["done"], f["state"] = want, "present"
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            have = part.stat().st_size if part.exists() else 0
            if want and have > want:            # a stale .part from another pin
                part.unlink()
                have = 0
            f["done"] = have
            headers = {"Range": f"bytes={have}-"} if have else {}
            async with _DL.stream("GET", f["url"], headers=headers) as resp:
                if resp.status_code not in (200, 206):
                    body = ""
                    try:
                        body = (await resp.aread())[:200].decode("utf-8", "replace")
                    except Exception:                            # noqa: BLE001
                        pass
                    e.update(state="error",
                             error=f"HTTP {resp.status_code} fetching {f['name']}: {body}"[:300])
                    publish("comfy", what="download", id=dl_id, state="error")
                    return
                # A 200 answering a Range request means the range was ignored:
                # appending would splice the head into the middle. Restart the file.
                mode = "ab" if (have and resp.status_code == 206) else "wb"
                if mode == "wb":
                    f["done"] = have = 0
                # THE SIZE PIN, BEFORE A BYTE IS WRITTEN. content-length on a 206 is
                # the REMAINDER, so the whole-file size is have + length.
                try:
                    clen = int(resp.headers.get("content-length") or 0)
                except ValueError:
                    clen = 0
                if want and clen and (have + clen) != want:
                    e.update(state="error",
                             error=(f"{f['name']}: upstream says {gb(have + clen)} "
                                    f"({have + clen} B) but our pin is {gb(want)} "
                                    f"({want} B). The model file changed upstream — "
                                    f"refusing to download something we cannot verify. "
                                    f"Re-run the curation pass."))
                    publish("comfy", what="download", id=dl_id, state="error")
                    return
                # A DISCOVERED file has no pin, so the server's own content-length
                # becomes the size to verify against — recorded here, before the write,
                # so a truncated transfer still fails the check at the end.
                if not want and clen:
                    want = f["bytes"] = have + clen
                with open(part, mode) as out:
                    async for chunk in resp.aiter_bytes(1 << 20):
                        if e["state"] == "cancelled":
                            break
                        if e["state"] == "paused":
                            return                       # .part survives; resume re-streams
                        out.write(chunk)
                        f["done"] += len(chunk)
                        now = time.time()
                        if now - last_push >= DL_TICK_S:
                            last_push = now
                            publish("comfy", what="download", id=dl_id, state="downloading")
            if e["state"] == "cancelled":
                break
            # ⚠️ THE VERIFY GATE: until BOTH pass the file keeps its .part name, so the
            # card never says "downloaded" and ComfyUI never sees a bad file.
            got = part.stat().st_size
            if want and got != want:
                e.update(state="error",
                         error=(f"{f['name']}: got {gb(got)} ({got} B), expected "
                                f"{gb(want)} ({want} B). Left as .part — press Retry."))
                publish("comfy", what="download", id=dl_id, state="error")
                return
            if f.get("sha256"):
                f["state"] = "verifying"
                publish("comfy", what="download", id=dl_id, state="verifying")
                digest = await _sha256(part)
                if digest != f["sha256"]:
                    e.update(state="error",
                             error=(f"{f['name']}: sha256 {digest[:12]}… does not match the "
                                    f"pinned {f['sha256'][:12]}…. The bytes are not the file "
                                    f"we curated. Left as .part; delete it and retry."))
                    publish("comfy", what="download", id=dl_id, state="error")
                    return
            os.replace(part, dest)
            f["state"] = "present"
        if e["state"] == "cancelled":
            publish("comfy", what="download", id=dl_id, state="cancelled")
            return
        e["state"] = "done"
        catalog_invalidate()
        publish("comfy", what="download", id=dl_id, state="done")
    except Exception as ex:                                      # noqa: BLE001
        e.update(state="error", error=f"{type(ex).__name__}: {ex}"[:300])
        publish("comfy", what="download", id=dl_id, state="error")


def cdl_inflight(pick_id: str):
    for e in CDL.values():
        if e.get("pick") == pick_id and e.get("state") in ("downloading", "paused"):
            return e
    return None


# A .part written within this many seconds is being written BY SOMEBODY, and CDL is not
# who. 30s is generous against a slow CDN stall and short enough that a genuinely
# abandoned .part is resumable within a minute.
LIVE_PART_S = 30.0


def foreign_writer(spec: dict) -> "str | None":
    """Is another PROCESS writing this model's .part right now?

    ⚠️ FOUND BY WALKING, NOT BY THINKING — the corruption case `cdl_inflight` cannot see.
    A bridge restart mid-download leaves the OLD process's task alive and still
    appending while the NEW one starts with an empty CDL whose duplicate guard says
    "nothing in flight"; both append, and only the sha catches it, an hour later. The
    .part's MTIME is the evidence, and it needs no cross-process bookkeeping."""
    for f in spec["files"]:
        part = models_dir() / f["directory"] / (f["name"] + ".part")
        try:
            age = time.time() - part.stat().st_mtime
        except OSError:
            continue
        if age < LIVE_PART_S:
            return (f"{f['name']} is being written right now (its .part was touched "
                    f"{age:.0f}s ago) — most likely by a bridge that was restarted "
                    f"mid-download. Wait a moment and press Refresh; if nothing moves "
                    f"for a minute the .part is stale and this will resume it.")
    return None


def _start_cdl(key: str, title: str, files: list) -> dict:
    _CDL_SEQ["n"] += 1
    dl_id = f"c{_CDL_SEQ['n']}"
    e = {"id": dl_id, "pick": key, "title": title, "files": files,
         "state": "downloading", "error": None, "started": time.time(), "task": None}
    CDL[dl_id] = e
    e["task"] = asyncio.create_task(_run_cdl(dl_id))
    publish("comfy", what="download", id=dl_id, state="downloading")
    return e


@app.post("/api/comfy/download")
async def api_comfy_download(req: Request) -> JSONResponse:
    body = await req.json()
    wf_name = str((body or {}).get("workflow") or "")
    if wf_name:
        return await _download_workflow(wf_name)
    pick_id = str((body or {}).get("pick") or "")
    spec = PICK_BY_ID.get(pick_id)
    if spec is None:
        return JSONResponse({"ok": False, "error": "unknown model"}, status_code=400)
    dup = cdl_inflight(pick_id)
    if dup:
        # Two clicks must not become two writers on one .part: the second JOINS.
        return JSONResponse({"ok": True, "download": _cdl_json(dup), "joined": True})
    busy = foreign_writer(spec)
    if busy:
        return JSONResponse({"ok": False, "error": busy}, status_code=409)
    card = pick_card(spec)
    files = []
    for f, state in zip(spec["files"], card["files"]):
        if state["present"]:
            continue
        url = state.get("url")
        if not url:
            return JSONResponse(
                {"ok": False, "error": (
                    f"no download URL for {f['name']}: the vendored workflow-templates "
                    f"registry did not list it. This is the registry-drift case — the "
                    f"curation pass must be re-run against this pin.")}, status_code=409)
        files.append({"directory": f["directory"], "name": f["name"],
                      "bytes": int(f["bytes"]), "sha256": f["sha256"], "url": url,
                      "dest": str(models_dir() / f["directory"] / f["name"]),
                      "done": 0, "state": "queued", "verify": "size + sha256"})
    if not files:
        return JSONResponse({"ok": True, "download": None,
                             "note": "every file is already on disk"})
    return JSONResponse({"ok": True, "download": _cdl_json(_start_cdl(
        pick_id, spec["title"], files))})


async def _download_workflow(name: str) -> JSONResponse:
    """Fetch exactly the files ONE DISCOVERED WORKFLOW is missing.

    ⚠️ THE HONEST DIFFERENCE FROM A CURATED PICK, STATED IN THE PAYLOAD: upstream's
    registry carries a URL but no sha256, so these files are verified against the size
    the SERVER declares and not against a hash we pinned. `verify` says which check the
    file got, the page prints it, and nothing here implies the stronger one."""
    dup = cdl_inflight("wf:" + name)
    if dup:
        return JSONResponse({"ok": True, "download": _cdl_json(dup), "joined": True})
    cat = await catalog_live()
    hit = find_workflow(cat, name)
    if not hit:
        return JSONResponse({"ok": False, "error": "unknown workflow"}, status_code=400)
    _model, wf = hit
    files, no_url = [], []
    for f in wf["files"]:
        if f["present"]:
            continue
        if not f.get("url"):
            no_url.append(f"{f['directory']}/{f['name']}")
            continue
        files.append({"directory": f["directory"], "name": f["name"],
                      "bytes": f.get("bytes"), "sha256": None, "url": f["url"],
                      "dest": str(models_dir() / f["directory"] / f["name"]),
                      "done": 0, "state": "queued", "verify": "size declared by server"})
    if no_url and not files:
        return JSONResponse({"ok": False, "error": (
            "the vendored registry carries no download link for "
            + ", ".join(no_url) + " — this workflow names a file upstream never "
            "published. Put it in models/ yourself, or open the template in the "
            "ComfyUI tab.")}, status_code=409)
    if not files:
        return JSONResponse({"ok": True, "download": None,
                             "note": "every file this workflow needs is already here"})
    e = _start_cdl("wf:" + name, wf["title"], files)
    return JSONResponse({"ok": True, "download": _cdl_json(e), "no_url": no_url})


@app.post("/api/comfy/download/{dl_id}/cancel")
async def api_comfy_download_cancel(dl_id: str) -> JSONResponse:
    e = CDL.get(dl_id)
    if not e:
        return JSONResponse({"ok": False, "error": "no such download"}, status_code=404)
    e["state"] = "cancelled"
    # The .part is DELIBERATELY KEPT — a cancelled 9 GB download resumed tomorrow must
    # not start from zero — and `_file_state` reports it as `partial`, not present.
    publish("comfy", what="download", id=dl_id, state="cancelled")
    return JSONResponse({"ok": True, "download": _cdl_json(e)})


@app.get("/api/comfy/downloads")
async def api_comfy_downloads() -> JSONResponse:
    return JSONResponse({"ok": True, "downloads": [_cdl_json(e) for e in CDL.values()]})


@app.post("/api/comfy/validate")
async def api_comfy_validate(req: Request) -> JSONResponse:
    body = await req.json()
    v = await validate_pick(str((body or {}).get("pick") or ""),
                            str((body or {}).get("mode") or "image"))
    return JSONResponse({"ok": True, "validation": v})


# ══ JOBS — submit, follow, recover ═══════════════════════════════════════════
JOBS: dict = {}


def _job_json(j: dict) -> dict:
    return {k: v for k, v in j.items() if k not in ("task", "graph")}


def _job_note(j: dict) -> str:
    if j["state"] == "running":
        if j.get("step") and j.get("step_max"):
            return f"step {j['step']}/{j['step_max']}"
        return "running"
    return j["state"]


async def _follow(job_id: str) -> None:
    """Follow one job: the websocket for step-granular progress, /history as the truth
    about what came out, and a footprint sample every tick. ⚠️ THE WEBSOCKET IS THE
    NICE-TO-HAVE AND /history IS THE CONTRACT — a dropped ws costs the progress bar,
    never the RESULT, so /history is re-polled unconditionally and the ws read
    opportunistically ("ws drop degrades to polling, silently")."""
    j = JOBS.get(job_id)
    if not j:
        return
    pid = comfy_pid()
    peak = _footprint(pid) or 0
    t0 = time.time()
    ws = None
    try:
        import websockets                                        # declared in requirements
        ws = await asyncio.wait_for(
            websockets.connect(f"ws://127.0.0.1:{comfy_port()}/ws?clientId={j['client_id']}"),
            timeout=5)
    except Exception:                                            # noqa: BLE001
        j["ws"] = False
    else:
        j["ws"] = True
    try:
        while True:
            if j["state"] in ("done", "error", "cancelled"):
                break
            if time.time() - t0 > 3 * 3600:
                j.update(state="error", error="gave up following after 3 hours")
                break
            # 1) footprint sample — the measured peak this run is credited with.
            f = _footprint(pid)
            if f:
                peak = max(peak, f)
                j["peak_bytes"] = peak
            # 2) websocket drain (non-blocking-ish).
            if ws is not None:
                try:
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=JOB_TICK_S)
                        if isinstance(raw, (bytes, bytearray)):
                            continue                     # binary previews — ignored
                        m = json.loads(raw)
                        _ws_apply(j, m)
                        if j["state"] in ("done", "error", "cancelled"):
                            break
                except asyncio.TimeoutError:
                    pass
                except Exception:                                # noqa: BLE001
                    j["ws"] = False
                    try:
                        await ws.close()
                    except Exception:                            # noqa: BLE001
                        pass
                    ws = None
            else:
                await asyncio.sleep(JOB_TICK_S)
            # 3) /history — the authoritative answer, ws or no ws.
            try:
                hist = await _cget(f"/history/{job_id}", timeout=8.0)
            except Exception as e:                               # noqa: BLE001
                # ComfyUI died mid-run. Say so; do NOT report the job as finished.
                j.update(state="error",
                         error=(f"lost contact with ComfyUI ({type(e).__name__}). The "
                                f"job may or may not have finished — start ComfyUI from "
                                f"MOT Deck → Components and press Refresh; anything it "
                                f"produced will appear in the gallery."))
                break
            rec = (hist or {}).get(job_id)
            if rec:
                _history_apply(j, rec)
                if j["state"] in ("done", "error", "cancelled"):
                    break
            publish("comfy", what="job", id=job_id, state=j["state"])
    finally:
        if ws is not None:
            try:
                await ws.close()
            except Exception:                                    # noqa: BLE001
                pass
        j["wall_s"] = round(time.time() - t0, 1)
        j["peak_bytes"] = peak or None
        gallery_finalize(j)
        if j["state"] == "done" and peak:
            m = MEASURED.setdefault(j["pick"], {})
            m[j["mode"]] = {"wall_s": j["wall_s"], "peak_bytes": int(peak),
                            "at": time.time(), "label": j.get("shape") or "",
                            "metric": "phys_footprint"}
            _measure_save()
        publish("comfy", what="job", id=job_id, state=j["state"])


def _ws_apply(j: dict, m: dict) -> None:
    """Apply one websocket frame to our job record. Pure-ish, testable."""
    t, d = m.get("type"), (m.get("data") or {})
    if d.get("prompt_id") not in (None, j["id"]):
        return                                    # another client's job on a shared server
    if t == "progress_state":
        # ⚠️ `progress_state`, NOT `progress`, AND THAT IS A LIVE FINDING. Every
        # write-up of this websocket — our own research §1.4 included — says the sampler
        # sends `progress` with {value, max}. At OUR pin comfy_execution/progress.py
        # sends ONE `progress_state` frame carrying every non-pending node instead, so a
        # handler written from the documentation matches nothing and the bar never moves
        # (exactly what the first live run showed). Read the vendored source.
        # step_max is NOT `steps`: `steps` is what the USER asked for and stays put.
        for nid, ns in (d.get("nodes") or {}).items():
            if ns.get("state") == "running" and (ns.get("max") or 0) > 1:
                j["step"], j["step_max"], j["node"] = ns.get("value"), ns.get("max"), nid
                break
    elif t == "progress":            # older pins' shape; kept, costs nothing
        j["step"], j["step_max"] = d.get("value"), d.get("max")
    elif t == "executing":
        j["node"] = d.get("node")
        if d.get("node") is None and d.get("prompt_id") == j["id"]:
            j["state"] = "finishing"              # /history confirms; we never guess
    elif t == "execution_error":
        j["state"] = "error"
        j["error"] = (f"{d.get('node_type') or 'node'} {d.get('node_id') or ''}: "
                      f"{d.get('exception_message') or 'execution error'}")[:400]
    elif t == "execution_interrupted":
        j["state"] = "cancelled"
    elif t == "status":
        q = ((d.get("status") or {}).get("exec_info") or {}).get("queue_remaining")
        if q is not None:
            j["queue_remaining"] = q


def _history_apply(j: dict, rec: dict) -> None:
    """The authoritative end-of-job read: status + the output file manifest."""
    st = (rec.get("status") or {})
    done = bool(st.get("completed"))
    sstr = str(st.get("status_str") or "")
    outs = []
    for _nid, node_out in (rec.get("outputs") or {}).items():
        for key in ("images", "gifs", "videos", "audio"):
            for it in (node_out.get(key) or []):
                if isinstance(it, dict) and it.get("filename"):
                    outs.append({"filename": it["filename"],
                                 "subfolder": it.get("subfolder") or "",
                                 "type": it.get("type") or "output"})
    if outs:
        j["outputs"] = outs
    if sstr == "error" or (not done and sstr and sstr != "success"):
        if j["state"] != "error":
            msgs = []
            for pair in (st.get("messages") or []):
                if isinstance(pair, (list, tuple)) and len(pair) == 2 and pair[0] == "execution_error":
                    msgs.append(str((pair[1] or {}).get("exception_message") or "")[:200])
            j.update(state="error", error=("; ".join(m for m in msgs if m)
                                           or f"ComfyUI reported {sstr!r}"))
        return
    if done:
        if outs:
            gallery_ingest(j)
            j["state"] = "done"
        else:
            j.update(state="error",
                     error="ComfyUI reported success but produced no output file")


async def _submit(graph: dict, j: dict) -> "JSONResponse | None":
    """POST /prompt and start following. Returns a JSONResponse on refusal, else None."""
    try:
        r = await _CX.post(comfy_url("/prompt"), timeout=30.0,
                           json={"prompt": graph, "client_id": j["client_id"],
                                 "prompt_id": j["id"]})
    except Exception as e:                                       # noqa: BLE001
        return JSONResponse({"ok": False, "error": (
            f"ComfyUI did not accept the job ({type(e).__name__}: {e}). Start it from "
            f"MOT Deck → Components, then try again.")}, status_code=502)
    try:
        payload = r.json()
    except ValueError:
        payload = {}
    if r.status_code >= 400:
        # node_errors IS the authoritative missing-model signal (research §4.5) —
        # surfaced verbatim, never swallowed into a generic failure.
        ne = payload.get("node_errors") or {}
        err = payload.get("error") or {}
        lines = []
        for nid, ent in ne.items():
            cls = ent.get("class_type") or nid
            for d in (ent.get("errors") or []):
                lines.append(f"{cls}: {d.get('message')} ({d.get('details')})")
        return JSONResponse({"ok": False, "error": (
            "; ".join(lines) or err.get("message") or f"ComfyUI refused the job "
                                                      f"(HTTP {r.status_code})"),
            "node_errors": ne}, status_code=409)
    JOBS[j["id"]] = j
    j["task"] = asyncio.create_task(_follow(j["id"]))
    publish("comfy", what="job", id=j["id"], state="running")
    return None


@app.post("/api/comfy/generate")
async def api_comfy_generate(req: Request) -> JSONResponse:
    body = await req.json() or {}
    if str(body.get("workflow") or ""):
        return await _generate_workflow(body)
    pick_id = str(body.get("pick") or "")
    mode = str(body.get("mode") or "image")
    spec = PICK_BY_ID.get(pick_id)
    if spec is None:
        return JSONResponse({"ok": False, "error": "unknown model"}, status_code=400)
    if mode not in spec["modes"]:
        return JSONResponse({"ok": False,
                             "error": f"{spec['title']} does not do {mode}"}, status_code=400)
    if not str(body.get("prompt") or "").strip():
        return JSONResponse({"ok": False, "error": "type a prompt first"}, status_code=400)

    # CONNECT-TIME VALIDATION, BEFORE SUBMIT — nodes and models both.
    v = await validate_pick(pick_id, mode)
    if not v["ok"]:
        return JSONResponse({"ok": False, "error": v["reason"], "validation": v},
                            status_code=409)

    # A blank seed means "surprise me" and the rolled number is REPORTED, so the result
    # stays reproducible. Never silently 0 (every default run would come out identical).
    seed = body.get("seed")
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        seed = int.from_bytes(os.urandom(6), "big")
    params = dict(body)
    params["seed"] = seed
    graph = build_graph(pick_id, mode, params)
    bad = fence_violations(graph)
    if bad:
        return JSONResponse({"ok": False,
                             "error": f"stock-node fence: refusing {', '.join(bad)}"},
                            status_code=500)

    shape = (f"{params.get('width') or spec['defaults'][mode]['width']}×"
             f"{params.get('height') or spec['defaults'][mode]['height']}")
    if mode == "video":
        shape += f" · {_wan_length(params.get('frames') or spec['defaults'][mode]['frames'])}f"
    j = {"id": str(uuid.uuid4()), "client_id": str(uuid.uuid4()), "pick": pick_id,
         "pick_title": spec["title"], "mode": mode, "state": "running",
         "prompt": params.get("prompt"), "negative": params.get("negative"),
         "seed": seed, "steps": graph_steps(graph), "shape": shape,
         "submitted": time.time(), "step": None, "step_max": None,
         "outputs": [], "error": None, "peak_bytes": None, "wall_s": None,
         "ws": None, "measured_before": measure_note(pick_id, mode),
         "workflow": spec["template"], "graph": graph}
    refused = await _submit(graph, j)
    if refused is not None:
        return refused
    return JSONResponse({"ok": True, "job": _job_json(j), "seed": seed})


async def _generate_workflow(body: dict) -> JSONResponse:
    """Run a DISCOVERED workflow: convert its vendored template, fence it against the
    running engine, put the user's values in the slots the template actually has, and
    submit. Every failure names itself and names its fix."""
    name = str(body.get("workflow") or "")
    cat = await catalog_live()
    hit = find_workflow(cat, name)
    if not hit:
        return JSONResponse({"ok": False, "error": "unknown workflow"}, status_code=400)
    model, wf = hit
    if model.get("refused"):
        return JSONResponse({"ok": False, "error": model["refused"]}, status_code=409)
    if not wf["complete"]:
        miss = [f for f in wf["files"] if not f["present"]]
        return JSONResponse({"ok": False, "error": (
            "missing model file(s): " + ", ".join(f["name"] for f in miss)),
            "validation": {"ok": False, "workflow": name,
                           "reason": ("missing model file(s): "
                                      + ", ".join(f["name"] for f in miss)),
                           "missing_models": [{
                               "directory": f["directory"], "name": f["name"],
                               "bytes": f.get("bytes"),
                               "size_h": gb(f["bytes"]) if f.get("bytes") else "size unknown",
                               "state": f["state"], "workflow": name,
                               "pick": wf.get("curated_pick"),
                               "pick_title": wf["title"],
                               "how": (f"Get “{wf['title']}” — it puts {f['name']} in "
                                       f"models/{f['directory']}/.")} for f in miss]}},
            status_code=409)
    info = await object_info()
    if not info:
        return JSONResponse({"ok": False, "error": (
            "ComfyUI is not answering, so this template cannot be converted. Start it "
            "from MOT Deck → Components, then try again.")}, status_code=502)
    conv = ui_to_api(template_graph(name) or {}, info)
    if not conv["ok"]:
        return JSONResponse({"ok": False, "error": conv["reason"]}, status_code=409)
    graph = conv["graph"]
    bad = dynamic_fence_violations(graph, info)
    if bad:
        return JSONResponse({"ok": False, "error": (
            "stock-node fence: refusing " + ", ".join(bad) + " — it comes from a "
            "third-party node pack, not from ComfyUI itself.")}, status_code=500)
    controls = workflow_controls(graph, conv["widgets"])
    if "prompt" in controls and not str(body.get("prompt") or "").strip():
        return JSONResponse({"ok": False, "error": "type a prompt first"}, status_code=400)
    # A workflow that takes a picture needs one, and the refusal names what would fix it
    # rather than letting ComfyUI fail on a filename that is not in input/.
    for kind in ("image", "video", "audio"):
        if kind not in controls:
            continue
        src = (body.get("source") or {}) if isinstance(body.get("source"), dict) else {}
        staged = stage_source(src) if src else None
        if not staged:
            return JSONResponse({"ok": False, "error": (
                f"this workflow starts from {'a picture' if kind == 'image' else 'a ' + kind}"
                f" — pick one under Source. Anything in the results rail can be used."),
                "needs_source": kind}, status_code=409)
        graph[controls[kind]["node"]]["inputs"][controls[kind]["widget"]] = staged
    seed = body.get("seed")
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        seed = int.from_bytes(os.urandom(6), "big")
    params = dict(body)
    params["seed"] = seed
    params["length"] = body.get("frames", body.get("length"))
    used = apply_controls(graph, controls, params)
    retarget_outputs(graph)
    w = used.get("width") or (controls.get("width") or {}).get("default")
    h = used.get("height") or (controls.get("height") or {}).get("default")
    shape = f"{w}×{h}" if w and h else ""
    length = used.get("length") or (controls.get("length") or {}).get("default")
    if wf["kind"] == "video" and length:
        shape = (shape + " · " if shape else "") + f"{length}f"
    j = {"id": str(uuid.uuid4()), "client_id": str(uuid.uuid4()),
         "pick": "wf:" + name, "pick_title": wf["title"], "mode": wf["kind"],
         "state": "running", "prompt": params.get("prompt"),
         "negative": params.get("negative"), "seed": used.get("seed", seed),
         "steps": graph_steps(graph) or used.get("steps"), "shape": shape,
         "submitted": time.time(), "step": None, "step_max": None,
         "outputs": [], "error": None, "peak_bytes": None, "wall_s": None,
         "ws": None, "measured_before": measure_note("wf:" + name, wf["kind"]),
         "workflow": name, "model": model["title"], "graph": graph}
    refused = await _submit(graph, j)
    if refused is not None:
        return refused
    return JSONResponse({"ok": True, "job": _job_json(j), "seed": j["seed"],
                         "used": used})


@app.get("/api/comfy/jobs")
async def api_comfy_jobs() -> JSONResponse:
    """Our jobs + ComfyUI's OWN queue view (`/api/jobs`, new at our pin). Different
    questions: ours knows what THIS surface submitted and measured; the server's knows
    what it is actually doing — including work queued from the ComfyUI tab, which would
    otherwise look like our job hanging for no reason."""
    server = {"ok": False, "jobs": [], "error": None}
    try:
        server_raw = await _cget("/api/jobs?limit=25", timeout=8.0)
        server = {"ok": True, "error": None,
                  "jobs": [{"id": x.get("id") or x.get("prompt_id"),
                            "status": x.get("status"),
                            "mine": (x.get("id") or x.get("prompt_id")) in JOBS}
                           for x in (server_raw.get("jobs") or [])]}
    except Exception as e:                                       # noqa: BLE001
        server["error"] = f"{type(e).__name__}: {e}"[:160]
    return JSONResponse({"ok": True, "jobs": [_job_json(j) for j in JOBS.values()],
                         "server": server})


@app.post("/api/comfy/jobs/{job_id}/cancel")
async def api_comfy_job_cancel(job_id: str) -> JSONResponse:
    j = JOBS.get(job_id)
    err = None
    try:
        r = await _CX.post(comfy_url(f"/api/jobs/{job_id}/cancel"), timeout=8.0, json={})
        if r.status_code >= 400:
            await _CX.post(comfy_url("/interrupt"), timeout=8.0)
    except Exception as e:                                       # noqa: BLE001
        err = f"{type(e).__name__}: {e}"[:160]
    if j:
        j["state"] = "cancelled"
    publish("comfy", what="job", id=job_id, state="cancelled")
    return JSONResponse({"ok": err is None, "error": err,
                         "job": _job_json(j) if j else None})


@app.get("/api/comfy/graph/{job_id}")
async def api_comfy_graph(job_id: str) -> JSONResponse:
    """The EXACT API-format graph we submitted — the only honest answer to "what did it
    actually run": not the template, the graph."""
    j = JOBS.get(job_id)
    if not j:
        it = next((x for x in gallery()["items"] if x.get("job") == job_id), None)
        if it and it.get("graph"):
            return JSONResponse({"ok": True, "graph": it["graph"]})
        return JSONResponse({"ok": False, "error": "no such job"}, status_code=404)
    return JSONResponse({"ok": True, "graph": j["graph"]})


@app.post("/api/comfy/open-template")
async def api_comfy_open_template(req: Request) -> JSONResponse:
    """Copy the STOCK template into ComfyUI's workflow browser directory.

    ⚠️ IT IS THE TEMPLATE, NOT YOUR PARAMETERS, AND THE UI SAYS SO: the browser reads
    UI-format graphs, we submit API format, and a hand-rolled conversion that lost a
    setting would be the lie. The exact graph is offered as JSON instead."""
    body = await req.json() or {}
    name = str(body.get("workflow") or "")
    if not name:
        spec = PICK_BY_ID.get(str(body.get("pick") or ""))
        if spec is None:
            return JSONResponse({"ok": False, "error": "unknown model"}, status_code=400)
        name = spec["template"]
    d = templates_dir()
    if d is None:
        return JSONResponse({"ok": False, "error": (
            "the vendored workflow-templates package is not in this install")},
            status_code=404)
    src = d / f"{name}.json"
    dst = comfy_base() / "user" / "default" / "workflows" / f"harness-{name}.json"
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError as e:
        return JSONResponse({"ok": False, "error": f"could not write {dst}: {e}"},
                            status_code=500)
    return JSONResponse({"ok": True, "path": str(dst), "name": dst.stem,
                         "url": comfy_url("/"),
                         "note": (f"Open the ComfyUI tab → Workflows → {dst.stem}. It is "
                                  f"upstream's stock template, not your parameters.")})


# ══ GALLERY — keep everything, and never claim a file it cannot see ══════════
def _gallery_path() -> Path:
    return state_dir() / "gallery.json"


def _gallery_load() -> list:
    try:
        d = json.loads(_gallery_path().read_text(encoding="utf-8"))
        return list(d.get("items") or [])
    except (OSError, ValueError):
        return []


def _gallery_write(items: list) -> None:
    try:
        state_dir().mkdir(parents=True, exist_ok=True)
        tmp = str(_gallery_path()) + ".harness-tmp"
        with open(tmp, "w") as f:
            json.dump({"items": items}, f, indent=2)
        os.replace(tmp, _gallery_path())
    except OSError:
        pass


def gallery_ingest(j: dict) -> None:
    """Record a finished job's outputs; called once, from the history read."""
    items = _gallery_load()
    known = {(i.get("subfolder"), i.get("filename")) for i in items}
    for o in j.get("outputs") or []:
        if (o["subfolder"], o["filename"]) in known:
            continue
        path = output_dir() / (o["subfolder"] or "") / o["filename"]
        try:
            size = path.stat().st_size
        except OSError:
            size = None
        items.append({
            "filename": o["filename"], "subfolder": o["subfolder"],
            "job": j["id"], "pick": j["pick"], "pick_title": j["pick_title"],
            "mode": j["mode"], "prompt": j.get("prompt"), "seed": j.get("seed"),
            "steps": j.get("steps"), "shape": j.get("shape"),
            "workflow": j.get("workflow"),
            "at": time.time(), "bytes_at_ingest": size,
            "wall_s": j.get("wall_s"), "peak_bytes": j.get("peak_bytes"),
            "graph": j.get("graph"),
        })
    _gallery_write(items)


def gallery_finalize(j: dict) -> None:
    """Write the run's MEASURED numbers onto the items it produced.

    ⚠️ WHY A SECOND PASS: ingest happens when /history says complete — BEFORE the
    follower's `finally` stops the clock, which left the first live run's gallery card
    blank while the queue strip above it read 59.6s."""
    items = _gallery_load()
    touched = False
    for it in items:
        if it.get("job") == j["id"]:
            it["wall_s"], it["peak_bytes"] = j.get("wall_s"), j.get("peak_bytes")
            touched = True
    if touched:
        _gallery_write(items)


def gallery() -> dict:
    """Registry ∪ what is on disk under <output>/harness/, re-stat'd every time.

    ⚠️ THREE LIES THIS REFUSES TO TELL: an item whose file is GONE is listed `missing`,
    never hidden; one whose size CHANGED since ingest is flagged `size_changed` rather
    than drawn as if nothing happened; and a file under our prefix the registry never
    saw is still LISTED (`orphan`) — keep-everything means the DISK is the truth, which
    is also what makes the gallery survive a lost registry."""
    items, out, seen = _gallery_load(), [], set()
    for it in items:
        p = output_dir() / (it.get("subfolder") or "") / it["filename"]
        seen.add(str(p))
        row = dict(it)
        row.pop("graph", None)                    # too big for a list payload
        try:
            sz = p.stat().st_size
            row["bytes"] = sz
            row["size_h"] = gb(sz)
            row["state"] = ("size_changed"
                            if (it.get("bytes_at_ingest") and sz != it["bytes_at_ingest"])
                            else "ok")
        except OSError:
            row["bytes"], row["size_h"], row["state"] = 0, "—", "missing"
        row["path"] = str(p)
        row["kind"] = _kind(it["filename"])
        out.append(row)
    root = output_dir() / OUT_PREFIX
    try:
        for p in sorted(root.rglob("*")):
            if not p.is_file() or str(p) in seen:
                continue
            st = p.stat()
            out.append({"filename": p.name,
                        "subfolder": str(p.parent.relative_to(output_dir())),
                        "bytes": st.st_size, "size_h": gb(st.st_size),
                        "at": st.st_mtime, "state": "orphan", "path": str(p),
                        "kind": _kind(p.name),
                        "note": "found on disk; this surface has no record of making it"})
    except OSError:
        pass
    out.sort(key=lambda r: -(r.get("at") or 0))
    return {"items": out, "total_bytes": sum(int(r.get("bytes") or 0) for r in out)}


def _kind(name: str) -> str:
    n = name.lower()
    if n.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return "image"
    if n.endswith((".mp4", ".webm", ".mkv", ".gif")):
        return "video"
    if n.endswith((".flac", ".mp3", ".wav", ".opus", ".ogg")):
        return "audio"
    return "file"


@app.get("/api/comfy/gallery")
async def api_comfy_gallery() -> JSONResponse:
    g = gallery()
    return JSONResponse({"ok": True, "items": g["items"],
                         "total_bytes": g["total_bytes"],
                         "total_h": gb(g["total_bytes"]),
                         "output_dir": str(output_dir()),
                         "disk": _disk(output_dir())})


@app.get("/api/comfy/file")
async def api_comfy_file(filename: str, subfolder: str = "") -> Response:
    """Serve one gallery file from ComfyUI's output dir.

    ⚠️ CONTAINMENT, THE OFFICE LANE'S RULE: resolve, then compare against the root."""
    root = output_dir().resolve()
    try:
        p = (root / (subfolder or "") / filename).resolve()
        p.relative_to(root)
    except (ValueError, OSError):
        return JSONResponse({"ok": False, "error": "path outside the output directory"},
                            status_code=400)
    if not p.is_file():
        return JSONResponse({"ok": False, "error": "no such file"}, status_code=404)
    return FileResponse(str(p), headers={"Cache-Control": "no-store"})


@app.post("/api/comfy/reveal")
async def api_comfy_reveal(req: Request) -> JSONResponse:
    """Reveal one gallery file in Finder. Same containment rule as the file route."""
    import subprocess
    body = await req.json() or {}
    root = output_dir().resolve()
    if body.get("what") == "models":
        target = models_dir()
        try:
            subprocess.run(["/usr/bin/open", "-R", str(target)], timeout=10,
                           capture_output=True)
        except Exception as e:                                   # noqa: BLE001
            return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"},
                                status_code=500)
        return JSONResponse({"ok": True, "revealed": str(target)})
    try:
        p = (root / (body.get("subfolder") or "") / str(body.get("filename") or "")).resolve()
        p.relative_to(root)
    except (ValueError, OSError):
        return JSONResponse({"ok": False, "error": "path outside the output directory"},
                            status_code=400)
    target = p if p.exists() else root
    try:
        subprocess.run(["/usr/bin/open", "-R", str(target)], timeout=10,
                       capture_output=True)
    except Exception as e:                                       # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"},
                            status_code=500)
    return JSONResponse({"ok": True, "revealed": str(target)})
