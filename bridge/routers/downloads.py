"""ROUTER — the bridge-owned download manager and the registry writes behind it."""
from __future__ import annotations

import asyncio
import hashlib
import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from ..core.appctx import ROOT, _modeltools, _voice, app
from ..core.events import publish
from ..core.hfclient import _HF
from ..core.modelreg import _read_registry_text, registry_lock, write_registry

# ── SSE (2026-08-28): how often a running download is allowed to push ────────
# ⚠️ THE ONE EMITTER THAT NEEDS A THROTTLE, AND THE NUMBER IS NOT ARBITRARY. The read
# loop below pulls 1 MB chunks, so a 30 GB weight set is ~30,000 iterations: emitting
# per chunk would turn a push channel into a flood, wake the panel thousands of times,
# and make the hub's own drop counter the busiest thing in the process. A progress bar
# needs about the cadence a human eye reads, which is also exactly the panel's old
# download poll (2s) — so this is not slower than what it replaces; it is the same
# cadence with the wakeups moved off the idle path (nothing ticks when nothing runs).
DL_TICK_S = 2.0


# ── Download manager (Bridge-owned, no Jan) ──────────────────────────────────
# Download the EXACT HuggingFace file the user clicks, into MOT Deck's own
# models dir (data/models/<model-id>/), with visible progress, pause/resume/cancel
# and parallelism. HF `resolve` URLs 302 to a CDN off huggingface.co, so a
# follow_redirects client is used against the absolute URL.
import re as _dl_re

DOWNLOADS: dict = {}
_DL_SEQ = {"n": 0}
_DL = httpx.AsyncClient(timeout=httpx.Timeout(30, read=120), follow_redirects=True)

_SPLIT_RE = _dl_re.compile(r"^(.*)-(\d{5})-of-(\d{5})\.gguf$")

# The origin every `f["url"]` (a repo-relative /repo/resolve/main/... path) is
# resolved against. A NAMED CONSTANT rather than an inline literal so the verify
# gate below can be exercised against a local shim serving a real truncated /
# tampered body — doctrine 2b wants the failure modes EXECUTED, and "no network in
# the sandbox" is not a reason to leave the corruption path unwalked.
_DL_BASE = "https://huggingface.co"


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
    """Add a completed artifact while preserving the library and user choices."""
    import json as _json
    reg = ROOT / "data" / "models.json"
    with registry_lock(str(reg)):
        try:
            data = _json.loads(_read_registry_text(reg))
        except FileNotFoundError:
            data = {"models": []}
        if (not isinstance(data, dict) or not isinstance(data.get("models"), list)
                or any(not isinstance(m, dict) for m in data["models"])):
            raise ValueError("model registry is unreadable — the existing library was left unchanged")
        old = next((m for m in data["models"] if m.get("id") == entry.get("id")), {})
        entry = dict(entry)
        # These choices cannot be reconstructed from weights. Like Rescan, a
        # re-download must carry them forward while refreshing artifact evidence.
        for key in ("voice", "ref_audio", "ref_text", "hidden", "settings", "load", "name"):
            if key in old:
                entry[key] = old[key]
        if entry.get("ctx") is None and old.get("ctx") is not None:
            entry["ctx"] = old["ctx"]
        models = [m for m in data["models"] if m.get("id") != entry.get("id")]
        models.append(entry)
        data["models"] = models
        write_registry(str(reg), data)


def _registry_update(mid: str, patch: dict, *, expected: dict | None = None) -> "dict | None":
    """Read data/models.json, merge `patch` into the entry with id `mid`, then use
    the one deterministic locked/fsynced registry writer shared by every mutator.
    Returns the updated entry, or None if missing or changed since `expected`.

    A key whose patch value is None is REMOVED rather than stored as null: the
    voice picker's "model default" is the absence of a `voice` key, not a null."""
    import json as _json, os as _os
    reg = ROOT / "data" / "models.json"
    with registry_lock(str(reg)):
        try:
            data = _json.loads(_read_registry_text(reg))
            if not isinstance(data, dict) or not isinstance(data.get("models"), list):
                return None
        except Exception:
            return None
        out = None
        for m in data["models"]:
            if isinstance(m, dict) and m.get("id") == mid:
                if expected is not None and m != expected:
                    return None
                for k, v in (patch or {}).items():
                    if v is None:
                        m.pop(k, None)
                    else:
                        m[k] = v
                out = m
                break
        if out is None:
            return None
        write_registry(str(reg), data)
        return out


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
    """JSON-safe view; task ownership and the control mutex stay private."""
    return {k: v for k, v in e.items() if k not in ("task", "control_lock")}


async def _dl_quiesce(e: dict) -> None:
    """Close the old stream/file before resuming or removing its partial bytes."""
    task = e.get("task")
    if task is not None:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


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


# ══ THE VERIFY GATE (ledger A10, 2026-08-29) ═════════════════════════════════
# ⚠️ WHY THIS EXISTS. Until this landed, `_run_download` renamed `.part`→dest
# UNCONDITIONALLY. A stream that died with an exception kept its .part (correct);
# a stream that ended early CLEANLY — a CDN truncation, a proxy cutting a 30 GB
# transfer at 12 GB, a captive-portal 200 — simply fell out of the read loop, got
# renamed onto the destination name, was written into data/models.json and shown
# as "complete — in your library". That is the LIE class: the worst class, because
# the user's next symptom is llama-server failing to load a model the app told
# them it had. The comfy lane fixed exactly this in v1.5.36 ("renamed only after
# BOTH the byte count and the sha256 match") and the rule never reached its older
# sibling here, even though dl_start already had the numbers in hand.
#
# The two facts we verify with, both from the SAME HF tree fetch dl_start already
# does:
#   • size    — `size` on every tree entry, LFS or not.
#   • sha256  — `lfs.oid`. ⚠️ NOT the top-level `oid`, which is the GIT BLOB sha1
#               and is not a content digest of anything. A non-LFS file
#               (config.json, merges.txt, tokenizer_config.json) genuinely has NO
#               published digest, so it is size-verified only — and the download
#               SAYS so rather than implying a full verification it did not do.
_SHA_RE = _dl_re.compile(r"^[0-9a-f]{64}$")


def _tree_sha256(tree: list) -> dict:
    """{path: sha256} for every LFS file in an HF tree response. Files with no
    `lfs` block (small text files, committed as plain git blobs) are ABSENT from
    the map — that absence is what downgrades them to size-only verification."""
    out = {}
    for it in tree or []:
        if not isinstance(it, dict):
            continue
        p = it.get("path") or ""
        lfs = it.get("lfs")
        oid = ((lfs or {}).get("oid") or "").strip().lower() if isinstance(lfs, dict) else ""
        if p and _SHA_RE.match(oid):
            out[p] = oid
    return out


def _verify_verdict(name: str, got: int, want, want_sha, digest) -> dict:
    """PURE — the gate between a finished .part and the rename. Testable without a
    socket, which is the point: this is the branch that used to not exist.

      got      bytes actually on disk in the .part
      want     bytes upstream says the whole file is (None = upstream said nothing)
      want_sha sha256 upstream publishes (None = upstream publishes none)
      digest   sha256 we actually computed (None when want_sha is None)

    Returns {"ok", "error", "verified"}. `verified` is carried into the download's
    own state so the UI can never imply a stronger check than the one that ran."""
    if want is not None and got != want:
        short = want - got
        gap = (f"{short} bytes short" if short > 0 else f"{-short} bytes too long")
        return {"ok": False, "verified": "size",
                "error": (f"CORRUPT — {name}: the transfer ended at {got} bytes but "
                          f"HuggingFace says this file is {want} bytes ({gap}). The "
                          f"stream was cut short, so this is not the model. The "
                          f"partial file was deleted and nothing was added to your "
                          f"library — press Get again to retry.")}
    if want_sha:
        if (digest or "") != want_sha:
            return {"ok": False, "verified": "sha256",
                    "error": (f"CORRUPT — {name}: sha256 {(digest or '(not computed)')[:12]}"
                              f"… does not match the {want_sha[:12]}… HuggingFace "
                              f"publishes for this file. The byte count is right but "
                              f"the bytes are not. The partial file was deleted and "
                              f"nothing was added to your library — press Get again "
                              f"to retry.")}
        return {"ok": True, "error": None, "verified": "size+sha256"}
    if want is not None:
        return {"ok": True, "error": None, "verified": "size"}
    return {"ok": True, "error": None, "verified": "unverified"}


def _verify_summary(files: list) -> str:
    """One honest sentence about how hard the completed download was checked. The
    'size only' case is NOT hidden: an upstream that publishes no digest is a real
    difference in what we can promise, and requirement (2) of the fix is that the
    state say which check actually ran."""
    modes = [f.get("verified") or "unverified" for f in files]
    if not modes:
        return "nothing to verify"
    unver = [f["name"] for f in files if (f.get("verified") or "unverified") == "unverified"]
    sized = [f["name"] for f in files if f.get("verified") == "size"]
    pre = [f["name"] for f in files if f.get("verified") == "pre-existing"]
    parts = []
    if all(m == "size+sha256" for m in modes):
        return "byte count and sha256 both verified against HuggingFace"
    if any(m == "size+sha256" for m in modes):
        parts.append("byte count and sha256 verified where HuggingFace publishes a digest")
    if sized:
        parts.append(f"size-only for {len(sized)} file(s) upstream publishes no digest for "
                     f"({', '.join(sized[:3])}{'…' if len(sized) > 3 else ''})")
    if pre:
        parts.append(f"{len(pre)} file(s) were already on disk and were not re-checked")
    if unver:
        parts.append(f"NOT VERIFIED: {len(unver)} file(s) — upstream published neither a "
                     f"size nor a digest ({', '.join(unver[:3])}"
                     f"{'…' if len(unver) > 3 else ''})")
    return "; ".join(parts) or "unverified"


async def _sha256_file(path: str) -> str:
    """Hash a multi-GB file WITHOUT blocking the event loop — the same reasoning as
    comfy's `_sha256`: hashing 30 GB inline would freeze every other bridge route
    for minutes, which reads to the user as "the app hung at 100%"."""
    def _run() -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 22), b""):
                h.update(chunk)
        return h.hexdigest()
    return await asyncio.to_thread(_run)


async def _run_download(dl_id: str) -> None:
    import os as _os, time as _t
    e = DOWNLOADS.get(dl_id)
    if not e:
        return
    last_push = 0.0           # SSE progress throttle clock (see DL_TICK_S)
    try:
        for f in e["files"]:
            dest, total = f["dest"], f["total"]
            part = dest + ".part"
            # Already complete? (full-size dest present)
            # ⚠️ DELIBERATELY NOT RE-HASHED (requirement 4 of the A10 fix): the
            # verify gate applies at COMPLETION, not retroactively. Re-digesting
            # every model already in the library on every touch would be a rescan
            # storm on tens of GB and would call files "corrupt" that nobody has
            # any evidence against. The state says which ones were skipped.
            if _os.path.exists(dest) and (total == 0 or _os.path.getsize(dest) == total):
                f["done"] = _os.path.getsize(dest)
                f["verified"] = f.get("verified") or "pre-existing"
                continue
            _os.makedirs(_os.path.dirname(dest), exist_ok=True)
            existing = _os.path.getsize(part) if _os.path.exists(part) else 0
            # A .part LONGER than the file it claims to be is a leftover from a
            # different revision of the same filename: resuming from its end asks
            # for a range past EOF (416) and appending to it can never produce the
            # right file. Start over. (Same guard comfy's `have > want` carries.)
            if total and existing > total:
                try:
                    _os.remove(part)
                except OSError:
                    pass
                existing = 0
            f["done"] = existing
            headers = {}
            if existing > 0:
                headers["Range"] = f"bytes={existing}-"
            url = _DL_BASE + f["url"]
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
                    publish("download", id=dl_id, state="error")
                    return
                # A 200 to a Range request means the server ignored it → restart file.
                mode = "ab" if (existing > 0 and resp.status_code == 206) else "wb"
                if mode == "wb":
                    f["done"] = last_done = existing = 0
                # THE SIZE PIN, BEFORE A BYTE IS WRITTEN (A10, comfy's shape).
                # content-length on a 206 is the REMAINDER, so the whole-file size
                # is existing + length. ⚠️ SKIPPED when the response is encoded:
                # HF serves small text files (config.json, tokenizer_config.json)
                # gzipped, and content-length is then the COMPRESSED length while
                # aiter_bytes yields decoded bytes — comparing the two would fail
                # honest downloads. The post-write gate below still checks those.
                stream_total = None
                if not (resp.headers.get("content-encoding") or "").strip():
                    try:
                        clen = int(resp.headers.get("content-length") or 0)
                    except ValueError:
                        clen = 0
                    if clen > 0:
                        stream_total = existing + clen
                if stream_total is not None:
                    if total and stream_total != total:
                        e["state"] = "error"
                        e["error"] = (
                            f"{_os.path.basename(dest)}: HuggingFace's file listing says "
                            f"{total} bytes but the download itself is offering "
                            f"{stream_total}. The file changed upstream mid-flight — "
                            f"refusing to fetch something we cannot verify. Press Get "
                            f"again to re-read the repo.")[:500]
                        publish("download", id=dl_id, state="error")
                        return
                    # No size in the tree (a failed/redirected tree fetch): the
                    # transfer's OWN declared length becomes the expectation, so a
                    # truncation is still caught rather than silently accepted.
                    f["expect"] = stream_total
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
                        # SSE progress tick, throttled to DL_TICK_S. Carries NO
                        # numbers: the panel's handler is refreshDownloads(), which
                        # reads /api/dl — so a tick can never disagree with the list.
                        if now - last_push >= DL_TICK_S:
                            last_push = now
                            publish("download", id=dl_id, state="downloading")
            if e["state"] == "cancelled":
                break
            # ══ THE VERIFY GATE — nothing reaches `dest` before this passes ══
            # Both facts are checked on the FULL ASSEMBLED FILE, never on the
            # resumed tail: a Range-resumed download whose earlier half was
            # written by a different revision is exactly the corruption a
            # tail-only check would wave through.
            fname = _os.path.basename(dest)
            got = _os.path.getsize(part) if _os.path.exists(part) else 0
            want = total or f.get("expect") or None
            want_sha = f.get("sha256") or None
            digest = None
            if want_sha and (want is None or got == want):
                # Only worth hashing once the cheap check passed. `phase` (not
                # `state`) so the download list keeps rendering as a running
                # download rather than falling into an unknown-state branch.
                f["state"] = "verifying"
                e["phase"] = "verifying"
                publish("download", id=dl_id, state="downloading")
                digest = await _sha256_file(part)
                # Cancel clicked while a multi-GB hash was running: honour it here
                # rather than renaming a file into a library the user just backed
                # out of. The .part survives — cancel's own cleanup owns it.
                if e["state"] == "cancelled":
                    e["phase"] = None
                    break
            v = _verify_verdict(fname, got, want, want_sha, digest)
            e["phase"] = None
            f["verified"] = v["verified"]
            if not v["ok"]:
                # No half-file at `dest`, no registry entry, no ".part" left to be
                # mistaken for a resumable transfer of the right file.
                try:
                    if _os.path.exists(part):
                        _os.remove(part)
                except OSError:
                    pass
                f["state"] = "corrupt"
                f["done"] = 0
                e["corrupt"] = True
                e["state"] = "error"
                e["error"] = v["error"][:500]
                publish("download", id=dl_id, state="error")
                return
            _os.replace(part, dest)
            f["state"] = "present"
        if e["state"] == "cancelled":
            _dl_cleanup(e)
            publish("download", id=dl_id, state="cancelled")
            return
        # All files complete AND VERIFIED → register the model. `verified` says
        # which check actually ran, so nothing downstream can imply a digest match
        # on files HuggingFace publishes no digest for.
        e["verified"] = _verify_summary(e["files"])
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
        # Two events, because two things changed: the download list AND the model
        # library (the registry gained an entry). Each maps to the poll handler that
        # already owns that surface — no new render logic on either side.
        publish("download", id=dl_id, state="done")
        publish("model", phase="library changed", done=True)
    except Exception as ex:
        e["state"] = "error"
        e["error"] = str(ex)[:300]
        publish("download", id=dl_id, state="error")


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
             "model_dir": model_dir, "voice_format": voice_format, "task": None,
             # A10: the verify gate's own fields, present from the first poll so
             # no consumer has to guess whether an older entry simply lacks them.
             "corrupt": False, "phase": None, "verified": None}
    DOWNLOADS[dl_id] = entry
    entry["task"] = asyncio.create_task(_run_download(dl_id))
    # SSE: a new download exists. This is what lets the panel's Downloads section
    # appear the instant a Get is clicked in ANOTHER tab.
    publish("download", id=dl_id, state="downloading")
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
    # A10: the LFS sha256s were already in this response and were being thrown
    # away. Keep them alongside the sizes — they are what makes the completion
    # gate a real verification instead of a byte count.
    oids = _tree_sha256(tree)

    if filename == "":
        # ── Whole-MLX-repo mode ──────────────────────────────────────────────
        paths = [it.get("path", "") for it in tree]
        has_gguf = any(p.lower().endswith(".gguf") for p in paths)
        # weights.npz is the older MLX weight format — mlx-community's whisper-base/
        # small conversions ship it INSTEAD of safetensors (recon-flagged; sample hit it:
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
                          "dest": dest, "total": int(size), "done": done,
                          "sha256": oids.get(relpath), "verified": None})
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
    # Keyed by BASENAME here (not path) because a GGUF download flattens the repo
    # layout into one model dir — the sha256 map has to be keyed the same way or
    # every gguf would silently drop to size-only verification.
    sha_by_base = {}
    for it in tree:
        p = it.get("path", "")
        sizes[_os.path.basename(p)] = it.get("size") or 0
        if p in oids:
            sha_by_base[_os.path.basename(p)] = oids[p]
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
                      "dest": dest, "total": int(sizes.get(base, 0)), "done": done,
                      "sha256": sha_by_base.get(base), "verified": None})
    entry = _mk_download(repo, files, model_id, "gguf", voice_format=voice_format)
    return JSONResponse(_dl_json(entry))


@app.post("/api/dl/{dl_id}/pause")
async def dl_pause(dl_id: str) -> JSONResponse:
    e = DOWNLOADS.get(dl_id)
    if not e:
        return JSONResponse({"ok": False}, status_code=404)
    async with e.setdefault("control_lock", asyncio.Lock()):
        if e["state"] == "downloading":
            e["state"] = "paused"
            await _dl_quiesce(e)
            publish("download", id=dl_id, state="paused")
    return JSONResponse(_dl_json(e))


@app.post("/api/dl/{dl_id}/resume")
async def dl_resume(dl_id: str) -> JSONResponse:
    import os as _os
    e = DOWNLOADS.get(dl_id)
    if not e:
        return JSONResponse({"ok": False}, status_code=404)
    async with e.setdefault("control_lock", asyncio.Lock()):
        if e["state"] == "paused":
            await _dl_quiesce(e)
            for f in e["files"]:
                part = f["dest"] + ".part"
                f["done"] = (_os.path.getsize(part) if _os.path.exists(part)
                             else (_os.path.getsize(f["dest"]) if _os.path.exists(f["dest"]) else 0))
            e["rate"] = 0.0
            e["state"] = "downloading"
            e["task"] = asyncio.create_task(_run_download(dl_id))
            publish("download", id=dl_id, state="downloading")
    return JSONResponse(_dl_json(e))


@app.post("/api/dl/{dl_id}/cancel")
async def dl_cancel(dl_id: str) -> JSONResponse:
    e = DOWNLOADS.get(dl_id)
    if not e:
        return JSONResponse({"ok": False}, status_code=404)
    async with e.setdefault("control_lock", asyncio.Lock()):
        e["state"] = "cancelled"
        await _dl_quiesce(e)
        _dl_cleanup(e)
        publish("download", id=dl_id, state="cancelled")
    return JSONResponse(_dl_json(e))


@app.get("/api/dl")
async def dl_list() -> JSONResponse:
    items = [_dl_json(e) for e in DOWNLOADS.values()]
    items.sort(key=lambda x: int(x["id"]), reverse=True)
    return JSONResponse(items)
