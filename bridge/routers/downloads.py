"""ROUTER — the bridge-owned download manager and the registry writes behind it."""
from __future__ import annotations

import asyncio
import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from ..core.appctx import ROOT, _modeltools, _voice, app
from ..core.hfclient import _HF


# ── Download manager (Bridge-owned, no Jan) ──────────────────────────────────
# Download the EXACT HuggingFace file the user clicks, into the harness's own
# models dir (data/models/<model-id>/), with visible progress, pause/resume/cancel
# and parallelism. HF `resolve` URLs 302 to a CDN off huggingface.co, so a
# follow_redirects client is used against the absolute URL.
import re as _dl_re

DOWNLOADS: dict = {}
_DL_SEQ = {"n": 0}
_DL = httpx.AsyncClient(timeout=httpx.Timeout(30, read=120), follow_redirects=True)

_SPLIT_RE = _dl_re.compile(r"^(.*)-(\d{5})-of-(\d{5})\.gguf$")


def _safe_dir(name: str) -> str:
    """Keep [A-Za-z0-9._-]; replace anything else with '-'."""
    return _dl_re.sub(r"[^A-Za-z0-9._-]", "-", name)


def _model_id_from_filename(filename: str) -> str:
    """Model id = filename stem minus '.gguf', with a trailing split suffix
    (-NNNNN-of-MMMMM) stripped. 'foo-Q4_K_M.gguf'→'foo-Q4_K_M';
    'bar-00001-of-00002.gguf'→'bar'."""
    stem = filename[:-5] if filename.lower().endswith(".gguf") else filename
    m = _dl_re.match(r"^(.*)-(\d{5})-of-(\d{5})$", stem)
    return m.group(1) if m else stem


def _split_files(filename: str) -> list:
    """If filename is a split part (…-NNNNN-of-MMMMM.gguf) return all parts in
    order (same prefix, 1..M); else just [filename]."""
    m = _SPLIT_RE.match(filename)
    if not m:
        return [filename]
    prefix, total = m.group(1), m.group(3)
    return [f"{prefix}-{i:05d}-of-{total}.gguf" for i in range(1, int(total) + 1)]


def _registry_add(entry: dict) -> None:
    """Read data/models.json, drop any model with the same id, append `entry`,
    atomic write (tmp + os.replace)."""
    import json as _json, os as _os
    reg = ROOT / "data" / "models.json"
    try:
        data = _json.loads(reg.read_text())
        if not isinstance(data, dict) or "models" not in data:
            data = {"models": []}
    except Exception:
        data = {"models": []}
    models = [m for m in data.get("models", []) if m.get("id") != entry.get("id")]
    models.append(entry)
    data["models"] = models
    reg.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(reg) + ".harness-tmp"
    with open(tmp, "w") as f:
        _json.dump(data, f, indent=2)
    _os.replace(tmp, reg)


def _registry_update(mid: str, patch: dict) -> "dict | None":
    """Read data/models.json, merge `patch` into the entry with id `mid`, atomic
    write (tmp + os.replace — the SAME shape as _registry_add/_registry_drop).
    Returns the updated entry, or None when the id is not in the registry.

    A key whose patch value is None is REMOVED rather than stored as null: the
    voice picker's "model default" is the absence of a `voice` key, not a null."""
    import json as _json, os as _os
    reg = ROOT / "data" / "models.json"
    try:
        data = _json.loads(reg.read_text())
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            return None
    except Exception:
        return None
    out = None
    for m in data["models"]:
        if isinstance(m, dict) and m.get("id") == mid:
            for k, v in (patch or {}).items():
                if v is None:
                    m.pop(k, None)
                else:
                    m[k] = v
            out = m
            break
    if out is None:
        return None
    tmp = str(reg) + ".harness-tmp"
    with open(tmp, "w") as f:
        _json.dump(data, f, indent=2)
    _os.replace(tmp, reg)
    return out


def _registry_drop(mid: str) -> None:
    """Read data/models.json, drop the model with id `mid`, atomic write. Used by the
    delete endpoint — note re-seeding would NOT remove a source="download" entry
    (merge preserves non-rescanned sources), so we drop it explicitly here."""
    import json as _json, os as _os
    reg = ROOT / "data" / "models.json"
    try:
        data = _json.loads(reg.read_text())
        if not isinstance(data, dict) or "models" not in data:
            return
    except Exception:
        return
    data["models"] = [m for m in data.get("models", []) if m.get("id") != mid]
    tmp = str(reg) + ".harness-tmp"
    with open(tmp, "w") as f:
        _json.dump(data, f, indent=2)
    _os.replace(tmp, reg)


def _mlx_registry_entry(e: dict) -> dict:
    """Build the source="download" registry entry for a completed MLX download.
    path = the model DIR; size = summed .safetensors bytes; vision read from the
    now-present config.json (vision_config or image_token_id). Pure/testable."""
    import os as _os, json as _json
    model_dir = e.get("model_dir") or _os.path.dirname(e["files"][0]["dest"])
    size = sum((f["total"] or (_os.path.getsize(f["dest"])
                               if _os.path.exists(f["dest"]) else 0))
               for f in e["files"] if f["dest"].lower().endswith(".safetensors"))
    vision = False
    try:
        cfgp = _os.path.join(model_dir, "config.json")
        if _os.path.isfile(cfgp):
            cj = _json.loads(open(cfgp).read())
            vision = ("vision_config" in cj) or ("image_token_id" in cj)
    except Exception:
        vision = False
    return {"id": e["model_id"], "name": e["model_id"], "format": "mlx",
            "path": model_dir, "mmproj": None, "size_bytes": size,
            "ctx": None, "source": "download", "vision": vision,
            "repo": e.get("repo") or None}   # provenance (mirrors the gguf entry)


def _gguf_registry_entry(e: dict) -> dict:
    """Build the source="download" registry entry for a completed GGUF download.
    path = the primary .gguf (files[0] = part-1 for split models — llama-server
    auto-loads the sibling parts); size = summed non-mmproj bytes; a lone mmproj
    sibling → vision. Pure/testable (mirrors _mlx_registry_entry) so the
    completion→library path can be unit-checked without the network."""
    import os as _os
    main_dest = e["files"][0]["dest"]
    mmproj_dest, nonmm = None, 0
    for f in e["files"]:
        if "mmproj" in _os.path.basename(f["dest"]).lower():
            mmproj_dest = f["dest"]
        else:
            nonmm += f["total"] or (_os.path.getsize(f["dest"])
                                    if _os.path.exists(f["dest"]) else 0)
    return {"id": e["model_id"], "name": e["model_id"], "format": "gguf",
            "path": main_dest, "mmproj": mmproj_dest, "size_bytes": nonmm,
            "ctx": None, "source": "download", "vision": bool(mmproj_dest),
            # Persist the SOURCE REPO: MTP models are commonly named
            # "<repo>/…-MTP-GGUF" while the per-file registry id carries no MTP
            # marker (e.g. Qwen3.5-9B-Q4_0). start_component.sh's speculative-
            # decoding gate matches id OR repo, so without this the MTP flags
            # never engage and you get MTP-without-acceleration.
            "repo": e.get("repo") or None}


def _dl_json(e: dict) -> dict:
    """JSON-safe view of a DOWNLOADS entry (drops the asyncio Task)."""
    return {k: v for k, v in e.items() if k != "task"}


def _dl_cleanup(e: dict) -> None:
    """Delete every file's .part and the model dir if it is left empty."""
    import os as _os
    last_dir = None
    for f in e["files"]:
        part = f["dest"] + ".part"
        try:
            if _os.path.exists(part):
                _os.remove(part)
        except OSError:
            pass
        last_dir = _os.path.dirname(f["dest"])
    try:
        if last_dir and _os.path.isdir(last_dir) and not _os.listdir(last_dir):
            _os.rmdir(last_dir)
    except OSError:
        pass


async def _run_download(dl_id: str) -> None:
    import os as _os, time as _t
    e = DOWNLOADS.get(dl_id)
    if not e:
        return
    try:
        for f in e["files"]:
            dest, total = f["dest"], f["total"]
            part = dest + ".part"
            # Already complete? (full-size dest present)
            if _os.path.exists(dest) and (total == 0 or _os.path.getsize(dest) == total):
                f["done"] = _os.path.getsize(dest)
                continue
            _os.makedirs(_os.path.dirname(dest), exist_ok=True)
            existing = _os.path.getsize(part) if _os.path.exists(part) else 0
            f["done"] = existing
            headers = {}
            if existing > 0:
                headers["Range"] = f"bytes={existing}-"
            url = "https://huggingface.co" + f["url"]
            last_ts, last_done = _t.time(), existing
            async with _DL.stream("GET", url, headers=headers) as resp:
                if resp.status_code not in (200, 206):
                    snip = ""
                    try:
                        snip = (await resp.aread())[:200].decode("utf-8", "replace")
                    except Exception:
                        pass
                    e["state"] = "error"
                    e["error"] = f"HTTP {resp.status_code}: {snip}"[:300]
                    return
                # A 200 to a Range request means the server ignored it → restart file.
                mode = "ab" if (existing > 0 and resp.status_code == 206) else "wb"
                if mode == "wb":
                    f["done"] = last_done = 0
                # 1 MB read buffer (was 64 KB). Bigger chunks cut per-chunk Python
                # overhead on multi-GB weights; no per-chunk flush/fsync (the OS page
                # cache batches writes) — ISSUE 3 local perf. The observed ~1.4 MB/s
                # average vs a 59 MB/s peak is HF-CDN-side throttling, not this loop
                # (a 64 KB loop already sustains >>100 MB/s locally). ⚠️ unmeasurable
                # in-sandbox (no network) — the safe local improvements are applied.
                with open(part, mode) as out:
                    async for chunk in resp.aiter_bytes(1 << 20):
                        st = e["state"]
                        if st == "paused":
                            return                     # keep .part; resume re-streams
                        if st == "cancelled":
                            break
                        out.write(chunk)
                        f["done"] += len(chunk)
                        now = _t.time()
                        dt = now - last_ts
                        if dt > 0:
                            inst = (f["done"] - last_done) / dt
                            e["rate"] = 0.7 * e["rate"] + 0.3 * inst
                            last_ts, last_done = now, f["done"]
            if e["state"] == "cancelled":
                break
            _os.replace(part, dest)
        if e["state"] == "cancelled":
            _dl_cleanup(e)
            return
        # All files complete → register the model.
        base = (_mlx_registry_entry(e) if e.get("kind") == "mlx"
                else _gguf_registry_entry(e))
        # Phase A: an AUDIO download carries an explicit format hint from the Get
        # button (never sniffed from the filename — see voice.audio_download_entry).
        vf = e.get("voice_format")
        if vf and _voice is not None:
            try:
                base = _voice.audio_download_entry(base, vf)
            except Exception as ex:                              # noqa: BLE001
                # A bad hint must not lose the download: register the chat-shaped
                # entry and say so, rather than dropping the model on the floor.
                print(f"[dl] audio hint {vf!r} rejected ({ex}) — "
                      f"registering {base.get('id')!r} as a chat model", flush=True)
        # TOOL-CALLING verdict, read from the freshly-downloaded files (the GGUF
        # header / the MLX tokenizer_config). Done HERE rather than inside the two
        # pure builders so those stay filesystem-free — and done at all so a model
        # that just landed shows its `tools` pill without a Rescan. Never raises:
        # `tools: None` is a legitimate "we could not tell".
        if _modeltools is not None and base.get("kind") != "audio":
            try:
                base["tools"] = _modeltools.tools_for_entry(base)
            except Exception:                                    # noqa: BLE001
                base["tools"] = None
        _registry_add(base)
        e["state"] = "done"
    except Exception as ex:
        e["state"] = "error"
        e["error"] = str(ex)[:300]


# Files a model NEVER needs at runtime. Everything else in the repo is fetched.
# DENYLIST, not an allowlist: the old allowlist (*.safetensors / tokenizer* / *.json)
# silently skipped `merges.txt`, so Qwen3-TTS downloaded a vocab with no merges and
# died at generate time with "vocab and merges must be both be from memory or both
# filenames". Every new model family would have re-broken an allowlist the same way;
# a denylist fails toward downloading a few KB too much instead of a dead model.
_MLX_SKIP_EXACT = {".gitattributes", ".gitignore", ".ds_store", "license", "notice"}
_MLX_SKIP_EXT = (".md", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".mp3",
                 ".wav", ".pdf", ".gguf")


def _mlx_repo_files(tree: list) -> list:
    """From an HF tree, return [(relpath, size)] for everything an MLX model needs —
    i.e. the whole repo minus docs/images/licences (see _MLX_SKIP_*). Weights,
    config, tokenizer assets (tokenizer.json OR vocab.json + merges.txt), sentencepiece
    models and nested dirs (e.g. speech_tokenizer/) all come down."""
    import os as _os
    out = []
    for it in tree:
        if (it.get("type") or "file") != "file":
            continue                                   # skip tree/dir entries
        p = it.get("path", "")
        if not p:
            continue
        b = _os.path.basename(p).lower()
        stem = b.rsplit(".", 1)[0]
        if b in _MLX_SKIP_EXACT or stem in _MLX_SKIP_EXACT:
            continue
        if b.endswith(_MLX_SKIP_EXT):
            continue
        out.append((p, it.get("size") or 0))
    return out


def _mk_download(repo: str, files: list, model_id: str, kind: str,
                 model_dir=None, voice_format: "str | None" = None) -> dict:
    """Register a new DOWNLOADS entry + spawn its task. `files` = the
    _run_download file-dict list already built by the caller. `voice_format` (Phase A)
    is the audio hint carried through to the registry entry on completion."""
    _DL_SEQ["n"] += 1
    dl_id = str(_DL_SEQ["n"])
    entry = {"id": dl_id, "repo": repo, "files": files, "state": "downloading",
             "error": None, "rate": 0.0, "model_id": model_id, "kind": kind,
             "model_dir": model_dir, "voice_format": voice_format, "task": None}
    DOWNLOADS[dl_id] = entry
    entry["task"] = asyncio.create_task(_run_download(dl_id))
    return entry


def _dl_inflight(model_id: str):
    """Return an in-flight (downloading/paused) DOWNLOADS entry for model_id, or None
    — the duplicate-start guard (two Gets → two tasks on one .part → corruption)."""
    for other in DOWNLOADS.values():
        if other.get("model_id") == model_id and other.get("state") in ("downloading", "paused"):
            return other
    return None


@app.post("/api/dl/start")
async def dl_start(req: Request) -> JSONResponse:
    """Unified acquisition for BOTH formats (Fable PART 0):
      • filename = "<x>.gguf"  → GGUF single-file (split-aware, + lone mmproj sibling).
      • filename = ""          → whole-MLX-repo mode: enqueue every model file into
                                  data/models/<repo-leaf>/ via the same machinery.

    Phase A (voice) adds two OPTIONAL body keys, both only ever set by the Audio tab's
    Get buttons — the chat paths are byte-identical without them:
      • voice_format ∈ tts-gguf | tts-mlx | stt-mlx → the completed download is
        registered as an AUDIO entry (kind:"audio") instead of a chat model.
      • mmproj = "<file>.gguf" → fetched ALONGSIDE the backbone into the SAME model
        dir, so the pair lands as ONE tts-gguf entry. Needed because the existing
        lone-sibling heuristic only fires when the repo has exactly one mmproj, and
        the Qwen3-TTS GGUF repo ships several quants of it."""
    import os as _os
    body = await req.json()
    repo = (body.get("repo") or "").strip()
    filename = (body.get("filename") or "").strip()
    voice_format = (body.get("voice_format") or "").strip().lower() or None
    mmproj_req = _os.path.basename((body.get("mmproj") or "").strip())
    if not repo:
        return JSONResponse({"ok": False, "log": "repo required"}, status_code=400)
    if voice_format and (_voice is None
                         or voice_format not in _voice.AUDIO_FORMATS):
        return JSONResponse(
            {"ok": False, "log": f"unknown voice format {voice_format!r}"},
            status_code=400)
    # One tree fetch feeds both modes. recursive=true so nested files are seen.
    tree = []
    try:
        r = await _HF.get(f"/api/models/{repo}/tree/main", params={"recursive": "true"})
        if r.status_code == 200:
            tree = r.json()
    except Exception:
        tree = []

    if filename == "":
        # ── Whole-MLX-repo mode ──────────────────────────────────────────────
        paths = [it.get("path", "") for it in tree]
        has_gguf = any(p.lower().endswith(".gguf") for p in paths)
        # weights.npz is the older MLX weight format — mlx-community's whisper-base/
        # small conversions ship it INSTEAD of safetensors (recon-flagged; Debi hit it:
        # the Get button 400'd invisibly). Both are MLX weights; accept either.
        has_st = any(p.lower().endswith((".safetensors", ".npz")) for p in paths)
        has_cfg = any(_os.path.basename(p) == "config.json" for p in paths)
        if has_gguf or not (has_st and has_cfg):
            return JSONResponse(
                {"ok": False, "log": "empty filename = MLX-repo mode, but this repo is "
                 "not an MLX model (needs *.safetensors + config.json, no *.gguf) — "
                 "pick a specific .gguf file instead"}, status_code=400)
        model_id = repo.split("/")[-1]
        dup = _dl_inflight(model_id)
        if dup:
            return JSONResponse(_dl_json(dup))
        dest_dir = ROOT / "data" / "models" / _safe_dir(model_id)
        files = []
        for relpath, size in _mlx_repo_files(tree):
            dest = str(dest_dir / relpath)      # preserve relative layout (usually flat)
            part = dest + ".part"
            done = _os.path.getsize(part) if _os.path.exists(part) else 0
            files.append({"name": relpath, "url": f"/{repo}/resolve/main/{relpath}",
                          "dest": dest, "total": int(size), "done": done})
        entry = _mk_download(repo, files, model_id, "mlx", model_dir=str(dest_dir),
                             voice_format=voice_format)
        return JSONResponse(_dl_json(entry))

    # ── GGUF single-file (existing behavior) ─────────────────────────────────
    model_id = _model_id_from_filename(filename)
    dup = _dl_inflight(model_id)
    if dup:
        return JSONResponse(_dl_json(dup))
    file_names = _split_files(filename)
    # Look up sizes + a single mmproj sibling from the repo tree.
    sizes, mmproj_name = {}, None
    for it in tree:
        p = it.get("path", "")
        sizes[_os.path.basename(p)] = it.get("size") or 0
    mmprojs = [it.get("path", "") for it in tree
               if "mmproj" in _os.path.basename(it.get("path", "")).lower()
               and it.get("path", "").lower().endswith(".gguf")]
    if len(mmprojs) == 1:
        mmproj_name = mmprojs[0]
    # An EXPLICIT mmproj (Audio tab) always wins over the lone-sibling heuristic —
    # a TTS repo carries several mmproj quants, so the heuristic silently fetches
    # nothing and llama-tts would then have no projector to load.
    if mmproj_req:
        mmproj_name = next((p for p in mmprojs
                            if _os.path.basename(p) == mmproj_req), mmproj_req)
    if mmproj_name and mmproj_name not in file_names:
        file_names.append(mmproj_name)
    dest_dir = ROOT / "data" / "models" / _safe_dir(model_id)
    files = []
    for name in file_names:
        base = _os.path.basename(name)
        dest = str(dest_dir / base)
        part = dest + ".part"
        done = _os.path.getsize(part) if _os.path.exists(part) else 0
        files.append({"name": name, "url": f"/{repo}/resolve/main/{name}",
                      "dest": dest, "total": int(sizes.get(base, 0)), "done": done})
    entry = _mk_download(repo, files, model_id, "gguf", voice_format=voice_format)
    return JSONResponse(_dl_json(entry))


@app.post("/api/dl/{dl_id}/pause")
async def dl_pause(dl_id: str) -> JSONResponse:
    e = DOWNLOADS.get(dl_id)
    if not e:
        return JSONResponse({"ok": False}, status_code=404)
    if e["state"] == "downloading":
        e["state"] = "paused"        # the task returns on its next chunk
    return JSONResponse(_dl_json(e))


@app.post("/api/dl/{dl_id}/resume")
async def dl_resume(dl_id: str) -> JSONResponse:
    import os as _os
    e = DOWNLOADS.get(dl_id)
    if not e:
        return JSONResponse({"ok": False}, status_code=404)
    if e["state"] == "paused":
        for f in e["files"]:
            part = f["dest"] + ".part"
            f["done"] = (_os.path.getsize(part) if _os.path.exists(part)
                         else (_os.path.getsize(f["dest"]) if _os.path.exists(f["dest"]) else 0))
        e["rate"] = 0.0
        e["state"] = "downloading"
        e["task"] = asyncio.create_task(_run_download(dl_id))
    return JSONResponse(_dl_json(e))


@app.post("/api/dl/{dl_id}/cancel")
async def dl_cancel(dl_id: str) -> JSONResponse:
    e = DOWNLOADS.get(dl_id)
    if not e:
        return JSONResponse({"ok": False}, status_code=404)
    was = e["state"]
    e["state"] = "cancelled"
    task = e.get("task")
    # If nothing is actively streaming (paused/finished), clean up the partials here.
    if was in ("paused", "done", "error") or task is None or task.done():
        _dl_cleanup(e)
    return JSONResponse(_dl_json(e))


@app.get("/api/dl")
async def dl_list() -> JSONResponse:
    items = [_dl_json(e) for e in DOWNLOADS.values()]
    items.sort(key=lambda x: int(x["id"]), reverse=True)
    return JSONResponse(items)
