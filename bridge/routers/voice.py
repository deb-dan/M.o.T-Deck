"""ROUTER — the harness-native VOICE capability: config, refs, library, TTS, STT."""
from __future__ import annotations

import asyncio
import functools
import os
import random
import subprocess
import time
from fastapi import Request
from fastapi.responses import JSONResponse, Response
from ..core.appctx import ROOT, _VOICE_ERR, _voice, app
from ..core.hfclient import _HF_ANY
from ..core.procs import _registry_models, cfg
from ..core.yamlset import _set_yaml_scalar
from .downloads import _registry_update
from .models import _is_hidden, _split_audio, _voice_cfg, _voice_spawn_guard


# ── Harness-native VOICE capability (FABLE-VOICE-CAPABILITY-SPEC, Phase B) ───────
# Distinct from /api/voice/status|toggle above (those register the two OPTIONAL
# voice COMPONENTS' MCP servers). These three own the all-MIT agents-can-speak path:
# one-shot llama-tts / mlx-audio subprocesses, no port, no card.
def _voice_unavailable() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": f"the voice module failed to load: {_VOICE_ERR}"},
        status_code=503)


@app.get("/api/voice/config")
def voice_config_get() -> JSONResponse:
    """Current defaults + every audio model in the registry (Phase A/C read this)."""
    v = _voice_cfg()
    available = []
    if _voice is not None:
        _, audio = _split_audio(_registry_models())
        # Hidden models are filtered here too, not only in /api/models — this list
        # feeds the composer's AUDIO popover, and a model hidden from the Models page
        # that still appeared in the composer would make "hide" mean two things.
        available = [_voice.audio_entry_view(m) for m in audio if not _is_hidden(m)]
    return JSONResponse({
        "ok": _voice is not None,
        "tts_model": v["tts_model"], "stt_model": v["stt_model"],
        "available": available,
        "max_chars": (_voice.VOICE_MAX_CHARS if _voice else 0),
        # What is loaded IN MEMORY right now (persistent worker). None = nothing
        # resident, so the next ▶ speak pays the load. The Audio tab shows this as a
        # `resident` pill + an Unload action.
        "resident": (_voice.worker_resident() if _voice else None),
        "error": _VOICE_ERR or None,
    })


@app.post("/api/voice/config")
async def voice_config_set(req: Request) -> JSONResponse:
    """Set the default TTS and/or STT model. Only keys PRESENT in the body are
    touched, so the panel can set one without clobbering the other. An empty string
    clears the slot (= capability off). The id must exist in the registry AND be of
    the right role — writing an unusable default would only fail later, at speak
    time, far from the click that caused it."""
    if _voice is None:
        return _voice_unavailable()
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    _, audio = _split_audio(_registry_models())
    v_before = _voice_cfg()
    changed = []
    for field, key, pred, label in (
            ("tts_model", "tts_model", _voice.is_tts_entry, "TTS"),
            ("stt_model", "stt_model", _voice.is_stt_entry, "STT")):
        if field not in body:
            continue
        mid = str(body.get(field) or "").strip()
        if mid:
            entry = _voice.find_entry(audio, mid)
            if entry is None:
                return JSONResponse(
                    {"ok": False, "error": f"'{mid}' is not an audio model in the registry "
                                           f"— rescan or download it in Models → Audio"},
                    status_code=400)
            if not pred(entry):
                return JSONResponse(
                    {"ok": False, "error": f"'{mid}' is a {_voice.audio_entry_view(entry)['role']} "
                                           f"model — it cannot be the default {label} model"},
                    status_code=400)
        if key == "tts_model" and mid != v_before["tts_model"]:
            # The resident worker holds exactly one checkpoint. Clearing the default
            # must free that RAM immediately (Debi's ratified lifecycle), and a SWITCH
            # would otherwise leave the old model resident — charged to the ledger —
            # until someone happened to speak again. ⚠️ PENDING FABLE QA: the spec
            # named only the clear case; killing on a switch too is strictly tidier.
            _voice.worker_stop("tts default " + ("cleared" if not mid else f"→ {mid}"))
        _set_yaml_scalar("voice", key, mid)
        changed.append(f"{key}={mid or '(off)'}")
    if changed:
        print(f"[voice] config {' · '.join(changed)}", flush=True)
    v = _voice_cfg()
    return JSONResponse({"ok": True, "tts_model": v["tts_model"],
                         "stt_model": v["stt_model"], "changed": changed})


@app.post("/api/voice/entry-voice")
async def voice_entry_voice(req: Request) -> JSONResponse:
    """{id, voice} → pin a NAMED VOICE onto one audio registry entry.

    The voice lives ON the registry entry, not in harness.yaml: a voice is a
    property of a model choice (Chelsie only means anything for Qwen3-TTS), so
    two installed TTS models can each remember their own. tts_argv already reads
    `entry["voice"]` and emits `--voice` only when it is set — this endpoint is
    the only writer. An empty string CLEARS it (back to the engine's own default,
    which for mlx-audio means a random name per render — that is the bug this
    whole slice exists to let the user opt out of)."""
    if _voice is None:
        return _voice_unavailable()
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    mid = str(body.get("id") or "").strip()
    voice = body.get("voice", "")
    if not mid:
        return JSONResponse({"ok": False, "error": "no model id given"}, status_code=400)
    _, audio = _split_audio(_registry_models())
    entry = _voice.find_entry(audio, mid)
    err = _voice.validate_voice_choice(entry, voice)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    v = _voice.normalize_voice(voice)
    updated = _registry_update(mid, {"voice": v or None})
    if updated is None:
        return JSONResponse(
            {"ok": False, "error": f"'{mid}' is no longer in the registry"},
            status_code=400)
    print(f"[voice] entry-voice {mid} → {v or '(model default)'}", flush=True)
    return JSONResponse({"ok": True, "entry": _voice.audio_entry_view(updated)})


async def _transcribe_clip(path: str, audio: list) -> str:
    """Transcribe ONE reference clip with the harness's own default STT model, or ''.

    THE POINT (root-caused 2026-08-13 from Debi's 30s-per-render report): mlx-audio's
    `generate_audio`, handed a ref_audio with NO ref_text, loads
    whisper-large-v3-turbo (~1.6GB) to transcribe the clip on EVERY render and then
    discards it (generate.py: "Ref_text not found. Transcribing ref_audio…"). Doing it
    ONCE here with whisper-base (sub-second, Gate-2 measured) makes every subsequent
    render skip that path entirely.

    Best-effort by design: no STT default, an unreadable clip or a failed
    transcription all return '' — the render still works, it is just slow, which is
    strictly better than refusing to pin a clip because dictation is not set up.
    """
    if _voice is None:
        return ""
    try:
        vc = cfg().get("voice")
        v = vc if isinstance(vc, dict) else {}
        stt_id = str(v.get("stt_model") or "").strip()
        stt_entry = _voice.find_entry(audio, stt_id) if stt_id else None
        if not stt_entry:
            return ""
        with open(path, "rb") as f:
            clip_bytes = f.read()
        sfx = os.path.splitext(path)[1].lstrip(".").lower() or "wav"
        return (await asyncio.to_thread(functools.partial(
            _voice.stt_transcribe, stt_entry, clip_bytes, sfx, root=ROOT)) or "").strip()
    except Exception as e:                                      # noqa: BLE001
        print(f"[voice] clip transcription skipped: {e}", flush=True)
        return ""


async def _heal_ref_text(entry: dict, audio: list) -> "dict | None":
    """Fill in a MISSING ref_text on an already-pinned entry and persist it.

    Returns the updated entry, or None when nothing could be healed. This is the
    self-heal for clips pinned BEFORE pin-time transcription existed: without it the
    fix would only ever apply to clips pinned after the upgrade, and Debi's existing
    pin would keep paying whisper-large on every single render forever.
    """
    path = str(entry.get("ref_audio") or "").strip()
    if not path or _voice is None:
        return None
    text = await _transcribe_clip(path, audio)
    if not text:
        return None
    updated = _registry_update(entry.get("id"), {"ref_text": text[:_voice.REF_TEXT_MAX]})
    if updated is None:
        return None
    print(f"[voice] ref_text self-healed for {entry.get('id')}: {text[:60]!r}",
          flush=True)
    return updated


def _trim_ref_clip(ff: "str | None", src: str) -> tuple:
    """(path to a ≤REF_CLIP_TRIM_SECS copy, "") or (None, reason). Never raises.

    The copy lives in data/voices/trimmed/ and is what gets PINNED; the source file is
    only read. Re-trimming the same source is skipped when a non-empty copy is already
    there, so pinning the same long clip twice costs one ffmpeg run, not two.
    """
    if not ff or _voice is None:
        return None, "no ffmpeg"
    try:
        dst = _voice.trimmed_clip_path(src, ROOT)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isfile(dst) and os.path.getsize(dst) > 0 \
                and os.path.getmtime(dst) >= os.path.getmtime(src):
            return dst, ""
        argv = _voice.ffmpeg_trim_argv(ff, src, dst, _voice.REF_CLIP_TRIM_SECS)
        c = subprocess.run(argv, capture_output=True, text=True, cwd=str(ROOT),
                           timeout=120)
        if os.path.isfile(dst) and os.path.getsize(dst) > 0:
            return dst, ""
        return None, ((c.stderr or "").strip()[-160:] or "ffmpeg produced no wav")
    except Exception as e:                                   # noqa: BLE001
        return None, f"{type(e).__name__}: {str(e)[:120]}"


@app.post("/api/voice/entry-ref")
async def voice_entry_ref(req: Request) -> JSONResponse:
    """{id, path|name, ref_text?} → pin a REFERENCE CLIP onto one audio entry.

    A zero-shot ("cloning") model such as OmniVoice has no speaker table at all —
    `model.generate()` takes ref_audio/ref_text and nothing else — so it renders a
    different random voice every time unless it is handed the same clip every time.
    This endpoint is that pin, and it lives on the registry entry beside `voice` for
    the same reason: it is a property of THIS model choice.

    `name` resolves inside the voice library (data/voices); `path` accepts any clip
    on disk (⚠️ PENDING FABLE QA: deliberately not confined to data/voices — Debi may
    point at a clip they already have; it is only ever READ, never deleted). An empty
    path/name CLEARS the pin (the key is removed, never stored as null).

    The resident worker is deliberately NOT restarted: the reference travels per
    request, exactly like the voice name, so a clip change costs no reload.
    """
    if _voice is None:
        return _voice_unavailable()
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    mid = str(body.get("id") or "").strip()
    if not mid:
        return JSONResponse({"ok": False, "error": "no model id given"}, status_code=400)
    ref_text = body.get("ref_text", "")
    if not isinstance(ref_text, str):
        ref_text = ""
    name = str(body.get("name") or "").strip()
    path = str(body.get("path") or "").strip()
    if name and not path:
        path, why = _voice.library_target(name, ROOT)
        if not path:
            return JSONResponse({"ok": False, "error": why}, status_code=400)
    _, audio = _split_audio(_registry_models())
    entry = _voice.find_entry(audio, mid)
    err = _voice.validate_ref_choice(entry, path, ref_text)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    ref_text = ref_text.strip()
    # ── LENGTH GUARD (2026-08-14, from Debi's 7.28 MB / ~30s mp3) ────────────────
    # The engine reads only the first ~10s of a reference clip (OmniVoice's
    # ref_audio_max_duration_s=10), so everything past that is render time bought for
    # nothing — and a long clip ALSO makes the pin-time transcription below far more
    # expensive. When we can measure the clip and we have ffmpeg, pin a bounded COPY
    # instead; without ffmpeg, an over-long clip is refused with the reason and the
    # limit named. The original file is never touched either way.
    length_note = ""
    if path:
        secs, method = _voice.estimate_clip_secs(path)
        ff = _voice.ffmpeg_bin(ROOT)
        action, msg = _voice.clip_length_verdict(secs, bool(ff), method)
        if action == "refuse":
            return JSONResponse({"ok": False, "error": msg}, status_code=400)
        if action == "trim":
            trimmed, why = _trim_ref_clip(ff, path)
            if trimmed:
                path, length_note = trimmed, msg
                # A trimmed clip is a DIFFERENT clip, so a transcript supplied for the
                # original no longer describes it. Dropping it costs one whisper pass
                # and keeps the ref_text honest.
                ref_text = ""
                print(f"[voice] entry-ref trimmed to {_voice.REF_CLIP_TRIM_SECS}s → "
                      f"{path}", flush=True)
            else:
                length_note = f"{msg} (the trim failed: {why} — pinning it as it is)"
        elif action == "warn":
            length_note = msg
    if path and not ref_text:
        # A STARTER clip comes WITH its ground-truth transcript (the corpus utterance
        # text), so it never pays a transcription — not the whisper-per-render one
        # below, and not even the one-off pin-time one. Checked BEFORE the STT call
        # because it is free and it is more accurate than any ASR result would be.
        ref_text = _voice.starter_ref_text(path, ROOT)
        if ref_text:
            print(f"[voice] entry-ref starter transcript used (no STT): "
                  f"{ref_text[:60]!r}", flush=True)
    if path and not ref_text:
        # AUTO-TRANSCRIBE ONCE AT PIN TIME (Fable fix 2026-08-13, root-caused from
        # Debi's 30s-per-render report): mlx-audio's generate_audio, handed a clip
        # with NO ref_text, loads whisper-large-v3-turbo (~1.6GB) to transcribe the
        # clip on EVERY render, then discards it (generate.py: "Ref_text not found.
        # Transcribing ref_audio..."). Transcribing once HERE with the harness's own
        # default STT (whisper-base, sub-second — Gate-2 measured) and storing the
        # text makes every render skip that path. Best-effort: no STT default or a
        # failed transcription just leaves ref_text empty (slow but working). ONE
        # implementation, shared with the /api/voice/tts self-heal.
        ref_text = await _transcribe_clip(path, audio)
        if ref_text:
            print(f"[voice] entry-ref transcribed clip once: {ref_text[:60]!r}",
                  flush=True)
    patch = {"ref_audio": path or None,
             # Clearing the clip clears its transcript too: a caption with no audio
             # is not a voice, it is a stray sentence prepended to every render.
             "ref_text": (ref_text[:500] or None) if path else None}
    updated = _registry_update(mid, patch)
    if updated is None:
        return JSONResponse(
            {"ok": False, "error": f"'{mid}' is no longer in the registry"},
            status_code=400)
    print(f"[voice] entry-ref {mid} → {os.path.basename(path) if path else '(cleared)'}",
          flush=True)
    return JSONResponse({"ok": True, "entry": _voice.audio_entry_view(updated),
                         "note": length_note})


@app.get("/api/voice/library")
def voice_library(folder: str = "") -> JSONResponse:
    """The reference clips in data/voices — the voice library. A plain directory
    listing: name, absolute path and size, sorted, never raising when the dir does
    not exist yet (it is created on the first save).

    `?folder=<abs path>` lists an EXTRA source instead (non-recursive, capped). The
    folder must be one the user has already added: this endpoint reads a directory
    named by a query parameter, so an allowlist of exact configured directories is
    the whole boundary — no prefix matching, no descent into children.
    """
    if _voice is None:
        return _voice_unavailable()
    if folder:
        folders = _voice.load_folders(ROOT)
        if not _voice.folder_allowed(folder, folders):
            return JSONResponse(
                {"ok": False, "error": "that folder is not one of your clip folders "
                                       "— add it first"}, status_code=400)
        clips = _voice.folder_entries(folder)
        return JSONResponse({"ok": True, "dir": _voice.normalize_folder(folder),
                             "clips": clips, "folder": True,
                             "capped": len(clips) >= _voice.FOLDER_CLIPS_CAP})
    clips = _voice.library_entries(ROOT)
    return JSONResponse({"ok": True, "dir": _voice.voices_dir(ROOT), "clips": clips,
                         # The starter set's own metadata travels with the listing so
                         # the picker can render the CC BY attribution without a
                         # second round-trip — an attribution nobody fetched is an
                         # attribution nobody sees, and CC BY requires it be visible.
                         "starter_dir": _voice.starter_dir(ROOT),
                         "starter_total": len(_voice.STARTER_VOICES),
                         "starter_license": _voice.VCTK_LICENSE,
                         "starter_attribution": _voice.VCTK_ATTRIBUTION,
                         "voice_notice": _voice.VOICE_AI_NOTICE})


_VCTK_TRIES = 4                 # 1 attempt + 3 retries; ~0.8/1.6/3.2s apart
_VCTK_PACE_SECS = 0.06          # a small gap between requests — see below


async def _vctk_rows(offset: int, length: int, tries: int = _VCTK_TRIES) -> tuple:
    """One page of the VCTK datasets-server listing as (rows, total, error).

    On success: (list, num_rows_total, ""). On failure: (None, 0, reason) — and the
    REASON is carried out, because the whole point of this rewrite is that the caller
    must be able to tell "the mirror does not have this speaker" from "we were rate
    limited". Never raises.

    RETRY + PACING (the second half of the 2026-08-14 bug): one full run of thirteen
    slots is ~200 anonymous requests to a service the research itself flagged as
    rate-limiting, and the first build had no retry, no backoff and no gap between
    requests at all — so a single 429 anywhere in the run cost a voice and reported it
    as a missing speaker. Retries are exponential with jitter (`vctk_retry_delay`, pure
    and unit-tested), and 4xx that are NOT 429 fail immediately: a 404 will not become a
    200 no matter how long we wait.
    """
    last = "unknown error"
    for attempt in range(max(1, int(tries))):
        if attempt:
            await asyncio.sleep(_voice.vctk_retry_delay(attempt - 1,
                                                        jitter=random.random() * 0.4))
        try:
            r = await _HF_ANY.get(_voice.VCTK_ROWS_URL, params={
                "dataset": _voice.VCTK_DATASET, "config": "default", "split": "train",
                "offset": int(offset), "length": int(length)})
        except Exception as e:                              # noqa: BLE001
            last = f"{type(e).__name__}: {str(e)[:120]}"
            continue
        if r.status_code == 200:
            try:
                j = r.json()
            except Exception:                               # noqa: BLE001
                last = "the mirror returned a body that is not JSON"
                continue
            rows = j.get("rows") if isinstance(j, dict) else None
            if not isinstance(rows, list):
                last = "the mirror returned no rows"
                continue
            await asyncio.sleep(_VCTK_PACE_SECS)
            return rows, _voice.vctk_total_rows(j), ""
        if r.status_code == 429:
            last = "rate limited by the dataset mirror (HTTP 429)"
            continue
        if 400 <= r.status_code < 500:
            return None, 0, f"the dataset mirror refused the request (HTTP {r.status_code})"
        last = f"the dataset mirror is having trouble (HTTP {r.status_code})"
    return None, 0, last


@app.post("/api/voice/library/starter")
async def voice_library_starter() -> JSONResponse:
    """Fetch the 13-clip VCTK starter voice set into data/voices/starter/.

    WHY a bespoke endpoint and not the download manager: the download manager is built
    around whole-HF-REPO model downloads that end in a registry entry. Thirteen loose
    wavs totalling ~3 MB are not a model, would never get a registry row, and would
    have to be taught to skip every step that makes that machine worth having.

    FETCH PLAN (research §6.3, followed exactly): the canonical VCTK release is a
    10.94 GB zip with no per-speaker path, so clips come from the HF datasets-server
    `/rows` endpoint against the `sanchit-gandhi/vctk` parquet mirror. Rows are
    speaker-ordered, so each speaker's first offset is found by BINARY SEARCH (pure,
    unit-tested with an injected probe) and then one page is read from there. Signed
    asset URLs EXPIRE, so metadata and audio are fetched in one pass and nothing is
    cached. `/filter?where=` is deliberately not used — re-confirmed live on
    2026-08-14: it still returns an empty body for this dataset.

    PARTIAL SUCCESS IS THE DESIGN: each slot lands independently and a failure is
    reported per-slot with its reason. Re-running only fetches what is missing, and
    now costs almost no probes either — the offset index it learned is persisted.

    ⚠️ FIXED 2026-08-14 after Debi's Mac reported "2 added — 11 failed". Two defects,
    both in the LOOKUP half:

      1. the slots were walked in ACCENT-SLOT order (p311, p334, p345, p294, …) while
         the `lo` floor carried forward monotonically. The floor is only sound if the
         speakers ascend, so from the fourth slot on, every lower-numbered speaker was
         searched exclusively in the region ABOVE p345 and reported absent. Nine slots
         failed this way on every single run, deterministically. FIX:
         `starter_fetch_order()` walks by speaker id; the table keeps its reading order.
      2. a probe that FAILED (429 / timeout) was cached as None and read as "speaker
         absent" — a false statement that also poisoned that offset for every later
         search. FIX: `VctkProbeUnavailable` separates the two outcomes, failures are
         never cached, and `_vctk_rows` retries with backoff + jitter and paces itself.

    A live probe the same day found all thirteen speakers present and the column
    contiguous (p225 … p376 then s5), so no substitution was needed to fix this — the
    `alt` lists exist for a mirror that changes later, and a substitution is always
    reported, never silent.
    """
    if _voice is None:
        return _voice_unavailable()
    ff = _voice.ffmpeg_bin(ROOT)
    d = _voice.starter_dir(ROOT)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError as e:
        return JSONResponse({"ok": False, "error": f"could not create {d}: {e}"},
                            status_code=500)
    man = _voice.read_starter_manifest(ROOT)
    saved, failed, skipped, substituted = [], [], [], []
    deadline = time.time() + _voice.STARTER_BUDGET_SECS

    # The probe cache, seeded from what earlier runs learned. Only SUCCESSFUL answers
    # ever go in: caching a failure is what turned one 429 into a permanently missing
    # voice. The thirteen searches overlap heavily (speakers ascend and so do their
    # offsets), so a remembered offset turns ~13 independent 17-step searches into far
    # fewer requests — and a re-run into almost none.
    known = _voice.read_starter_offsets(ROOT)
    probes: dict = {v: k for k, v in known.items()}

    class _PastEnd(Exception):
        """The mirror answered, and the answer was 'there is nothing at that row'."""

    # PRIME the row count from one real page before any search runs. The binary search's
    # upper bound has to be right BEFORE the first probe, and a hardcoded total that the
    # mirror has since shrunk would send that probe past the end of the data — where the
    # server returns a perfectly good 200 with an empty list, which is not a failure and
    # so cannot be retried out of. Caught in a synthetic run of this exact walk.
    _first, _tot, _err = await _vctk_rows(0, 1)
    total_rows = _tot or _voice.VCTK_ROWS_TOTAL
    if _first is None:
        return JSONResponse({"ok": False, "saved": [], "skipped": [], "substituted": [],
                             "ffmpeg": bool(ff), "attribution": _voice.VCTK_ATTRIBUTION,
                             "failed": [{"slot": s["slot"], "speaker": s["speaker"],
                                         "reason": f"could not reach the dataset "
                                                   f"mirror: {_err}"}
                                        for s in _voice.STARTER_VOICES]},
                            status_code=502)

    async def probe_async(off: int) -> str:
        """The speaker at `off`. Raises rather than lying: VctkProbeUnavailable when the
        mirror could not answer, _PastEnd when it answered 'nothing there'."""
        nonlocal total_rows
        if off in probes:
            return probes[off]
        rows, tot, err = await _vctk_rows(off, 1)
        if tot:
            total_rows = tot
        if rows is None:
            raise _voice.VctkProbeUnavailable(err or "the mirror gave no answer")
        sid = ""
        if rows and isinstance(rows[0], dict):
            row = rows[0].get("row")
            if isinstance(row, dict):
                sid = str(row.get("speaker_id") or "")
        if not sid:
            total_rows = min(total_rows, off)   # the data ends before here
            raise _PastEnd(off)
        probes[off] = sid
        return sid

    async def find_offset(spk: str, lo: int) -> "int | None":
        """The pure binary search, pumped: run it against the cache, and when it asks
        for an offset we have not seen, fetch that one and start over. Bounded by the
        search depth (~18 probes over 88k rows), 60 rounds of headroom."""
        if spk in known:
            return known[spk]
        for _round in range(60):
            missing = []

            def sync_probe(o, _m=missing):
                if o in probes:
                    return probes[o]
                _m.append(o)
                return None                # aborts the search; we fetch and retry
            try:
                return _voice.vctk_speaker_bounds(spk, sync_probe, total_rows, lo)
            except _voice.VctkProbeUnavailable:
                if not missing:
                    raise
            try:
                await probe_async(missing[0])
            except _PastEnd:
                continue        # total_rows just shrank; re-run with the real bound
        raise _voice.VctkProbeUnavailable("the offset search did not converge")

    lo = 0
    for spec in _voice.starter_fetch_order(_voice.STARTER_VOICES):
        slot, spk = spec["slot"], spec["speaker"]
        name = _voice.starter_clip_name(slot, spk)
        dst = os.path.join(d, name)
        # RE-RUNNABLE: a slot already on disk is skipped. Checks BOTH suffixes, because
        # the no-ffmpeg degrade writes .flac and the old wav-only test meant a machine
        # without ffmpeg re-downloaded everything it already had on every click.
        have = _voice.starter_present(slot, spk, ROOT)
        if have and man.get(os.path.basename(have)):
            skipped.append(os.path.basename(have))
            continue
        if time.time() > deadline:
            failed.append({"slot": slot, "speaker": spk,
                           "reason": "ran out of time for this run — click again to "
                                     "carry on with the slots that are still missing"})
            continue
        try:
            # The primary speaker, then the research's named alternates for this accent
            # slot. Only a genuine ABSENCE moves to the next candidate; a probe failure
            # fails the slot with its real reason, because retrying a rate limit under a
            # different speaker id would just spend the budget faster.
            offset, used = None, spk
            for cand in _voice.starter_candidates(spec):
                offset = await find_offset(cand, lo if cand >= spk else 0)
                if offset is not None:
                    used = cand
                    break
            if offset is None:
                cands = _voice.starter_candidates(spec)
                failed.append({"slot": slot, "speaker": spk,
                               "reason": f"not present in the dataset mirror "
                                         f"(tried {', '.join(cands)}) — fill this slot "
                                         f"by hand with ⊕ add clip file"})
                continue
            if used != spk:
                # ⚠️ A SUBSTITUTION CHANGES THE VOICE, keeping only the accent slot.
                substituted.append({"slot": slot, "wanted": spk, "used": used})
                print(f"[voice] starter {slot}: {spk} absent — substituting {used} "
                      f"({spec.get('accent')})", flush=True)
            spk = used
            name = _voice.starter_clip_name(slot, spk)
            dst = os.path.join(d, name)
            known[spk] = offset
            if used == spec["speaker"]:
                # The floor advances ONLY on a primary hit. The walk is sorted by
                # PRIMARY speaker, so a primary offset is a sound floor for the next
                # primary — an alternate's offset is not (p376's alternate is p248,
                # which sits near the very start), and this is exactly the class of
                # mistake that caused the bug being fixed.
                lo = max(lo, offset)
            rows, tot, err = await _vctk_rows(offset, _voice.STARTER_PAGE)
            if tot:
                total_rows = tot
            if rows is None:
                failed.append({"slot": slot, "speaker": spk,
                               "reason": f"could not read this speaker's rows: {err}"})
                continue
            picks = _voice.vctk_pick_utterances(rows, spk)
            if not picks:
                failed.append({"slot": slot, "speaker": spk,
                               "reason": "no mic1 utterances returned for this speaker"})
                continue
            parts = []
            for i, p in enumerate(picks):
                # Same retry discipline as the row pages — the asset host is the same
                # rate-limited service, and losing one of three utterances costs the
                # whole slot.
                r, why = None, "unknown error"
                for attempt in range(_VCTK_TRIES):
                    if attempt:
                        await asyncio.sleep(_voice.vctk_retry_delay(
                            attempt - 1, jitter=random.random() * 0.4))
                    try:
                        r = await _HF_ANY.get(p["src"])
                    except Exception as e:                   # noqa: BLE001
                        r, why = None, f"{type(e).__name__}: {str(e)[:100]}"
                        continue
                    if r.status_code == 200 and r.content:
                        break
                    why = f"HTTP {r.status_code}"
                    r = None
                if r is None:
                    failed.append({"slot": slot, "speaker": spk,
                                   "reason": f"clip download failed: {why}"})
                    parts = []
                    break
                src = os.path.join(d, f".{slot}-{i}.flac")
                with open(src, "wb") as f:
                    f.write(r.content)
                parts.append(src)
            if not parts:
                continue
            try:
                if ff and len(parts) >= 1:
                    argv = _voice.ffmpeg_concat_argv(ff, parts, dst)
                    c = subprocess.run(argv, capture_output=True, text=True,
                                       cwd=str(ROOT), timeout=120)
                    ok = os.path.isfile(dst) and os.path.getsize(dst) > 0
                    if not ok:
                        raise RuntimeError((c.stderr or "")[-300:] or "ffmpeg produced no wav")
                    text = " ".join(p["text"] for p in picks)
                else:
                    # ⚠️ NO ffmpeg: keep the SINGLE longest utterance as flac rather
                    # than fail. flac is in REF_AUDIO_SUFFIXES and mlx-audio reads it
                    # with miniaudio — no external tool — so the clip still works; it
                    # is just ~3.6s instead of ~10s. Honest degrade, not a silent one.
                    best = max(range(len(parts)), key=lambda i: os.path.getsize(parts[i]))
                    dst = os.path.join(d, os.path.splitext(name)[0] + ".flac")
                    os.replace(parts[best], dst)      # same dir ⇒ same filesystem
                    parts = [p for i, p in enumerate(parts) if i != best]
                    text = picks[best]["text"]
            except Exception as e:                           # noqa: BLE001
                failed.append({"slot": slot, "speaker": spk,
                               "reason": f"could not assemble the clip: {e}"})
                continue
            finally:
                for p in parts:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            key = os.path.basename(dst)
            man[key] = {"text": text[:_voice.REF_TEXT_MAX], "slot": slot,
                        "speaker": spk, "sex": spec.get("sex", ""),
                        "accent": spec.get("accent", ""),
                        "region": spec.get("region", ""),
                        "source": "VCTK 0.92 (CC BY 4.0)"}
            _voice.write_starter_manifest(man, ROOT)
            saved.append(key)
        except _voice.VctkProbeUnavailable as e:
            # The honest reason, NOT "speaker not found". This distinction is the whole
            # point of the class: it tells Debi to click again rather than to believe a
            # voice is gone.
            failed.append({"slot": slot, "speaker": spk,
                           "reason": f"could not reach the dataset mirror: {e} "
                                     f"— click again in a minute"})
        except Exception as e:                               # noqa: BLE001
            failed.append({"slot": slot, "speaker": spk,
                           "reason": f"{type(e).__name__}: {str(e)[:160]}"})
    # Persist whatever offsets this run learned even if it failed part-way: the next
    # click then spends its requests on the missing clips, not on re-deriving offsets.
    try:
        _voice.write_starter_offsets(known, ROOT)
    except OSError as e:
        print(f"[voice] starter offset index not written: {e}", flush=True)
    for f in failed:
        print(f"[voice] starter {f['slot']} ({f['speaker']}) failed: {f['reason']}",
              flush=True)
    print(f"[voice] starter voices: {len(saved)} saved, {len(skipped)} already there, "
          f"{len(failed)} failed, {len(substituted)} substituted "
          f"({len(probes)} offsets known)", flush=True)
    return JSONResponse({"ok": bool(saved or skipped) or not failed,
                         "saved": saved, "skipped": skipped, "failed": failed,
                         "substituted": substituted, "ffmpeg": bool(ff),
                         "attribution": _voice.VCTK_ATTRIBUTION})


@app.get("/api/voice/library/folders")
def voice_library_folders() -> JSONResponse:
    """The configured extra clip folders + the suggested ones that exist on this Mac.

    A folder is a POINTER, never a copy: nothing is imported and nothing is moved, so
    removing one only forgets the pointer. `missing:true` marks a folder that has since
    been deleted or unmounted — shown rather than silently dropped, because a folder
    that vanished is information."""
    if _voice is None:
        return _voice_unavailable()
    folders = _voice.load_folders(ROOT)
    out = []
    for p in folders:
        real = _voice.normalize_folder(p)
        out.append({"path": p, "real": real, "missing": real is None,
                    "count": len(_voice.folder_entries(p)) if real else 0})
    return JSONResponse({"ok": True, "folders": out,
                         "suggested": _voice.suggested_folders(ROOT),
                         "max": _voice.FOLDER_LIST_MAX})


@app.post("/api/voice/library/folders/add")
async def voice_library_folder_add(req: Request) -> JSONResponse:
    """{path} → remember one more clip folder. Idempotent; validates that it IS a
    directory (a typo must fail here, not later as an empty chip)."""
    if _voice is None:
        return _voice_unavailable()
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw = str(body.get("path") or "").strip()
    if not raw:
        return JSONResponse({"ok": False, "error": "no folder path given"},
                            status_code=400)
    real = _voice.normalize_folder(raw)
    if not real:
        return JSONResponse(
            {"ok": False, "error": f"no such folder: {raw[:200]}"}, status_code=400)
    folders = _voice.load_folders(ROOT)
    if any(_voice.normalize_folder(f) == real for f in folders):
        return JSONResponse({"ok": True, "folders": folders, "added": False})
    if len(folders) >= _voice.FOLDER_LIST_MAX:
        return JSONResponse(
            {"ok": False, "error": f"that is {_voice.FOLDER_LIST_MAX} folders already "
                                   f"— remove one first"}, status_code=400)
    folders = folders + [real]
    _voice.save_folders(folders, ROOT)
    print(f"[voice] clip folder added: {real}", flush=True)
    return JSONResponse({"ok": True, "folders": folders, "added": True})


@app.post("/api/voice/library/folders/remove")
async def voice_library_folder_remove(req: Request) -> JSONResponse:
    """{path} → forget one clip folder. The FILES ARE NEVER TOUCHED — this endpoint
    has no delete in it at all, which is why it can safely accept an arbitrary path."""
    if _voice is None:
        return _voice_unavailable()
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw = str(body.get("path") or "").strip()
    real = _voice.normalize_folder(raw)
    folders = _voice.load_folders(ROOT)
    kept = [f for f in folders
            if f != raw and (real is None or _voice.normalize_folder(f) != real)]
    if len(kept) != len(folders):
        _voice.save_folders(kept, ROOT)
        print(f"[voice] clip folder removed (files untouched): {raw}", flush=True)
    return JSONResponse({"ok": True, "folders": kept,
                         "removed": len(kept) != len(folders)})


@app.post("/api/voice/library/save")
async def voice_library_save(req: Request) -> JSONResponse:
    """RAW audio body + ?name=&fmt= → save a recorded clip into data/voices.

    Same body shape as /api/voice/stt (the panel already holds a Blob from
    MediaRecorder; multipart would buy nothing for a single part). The name is
    sanitized to a basename with a suffix forced from ?fmt=, and an existing file is
    NEVER clobbered — a recording cannot be re-made, so ' (n)' is the only safe
    policy. The bytes are not decoded or transcoded here: mlx-audio's own loader
    reads the container at render time.
    """
    if _voice is None:
        return _voice_unavailable()
    raw = await req.body()
    if not raw:
        return JSONResponse({"ok": False, "error": "no audio received"}, status_code=400)
    if len(raw) > _voice.REF_AUDIO_MAX_BYTES:
        return JSONResponse(
            {"ok": False, "error": f"that clip is too large "
                                   f"({len(raw) // (1024 * 1024)} MB) — the cap is "
                                   f"{_voice.REF_AUDIO_MAX_BYTES // (1024 * 1024)} MB"},
            status_code=413)
    fmt = (req.query_params.get("fmt") or "").strip() or req.headers.get("content-type", "")
    name = _voice.sanitize_clip_name(req.query_params.get("name") or "", fmt)
    if not name:
        return JSONResponse(
            {"ok": False, "error": f"give the clip a short name and a supported format "
                                   f"({', '.join(_voice.REF_AUDIO_SUFFIXES)})"},
            status_code=400)
    d = _voice.voices_dir(ROOT)
    os.makedirs(d, exist_ok=True)
    path = _voice.unique_clip_path(d, name)
    try:
        with open(path, "wb") as f:
            f.write(raw)
    except OSError as e:
        return JSONResponse({"ok": False, "error": f"could not save the clip: {str(e)[:200]}"},
                            status_code=500)
    # LENGTH GUARD, save side. The library keeps what it was given — trimming a stored
    # recording behind the user's back would be a worse surprise than a slow render —
    # so this only REFUSES the case we could neither use nor shorten (over-long AND no
    # ffmpeg anywhere), and otherwise reports the estimate so the pin can say what it
    # is about to do. The file is removed again on refusal: a clip the harness has just
    # told the user it will not accept must not be left sitting in the library.
    note = ""
    if _voice is not None:
        secs, method = _voice.estimate_clip_secs(path)
        action, msg = _voice.clip_length_verdict(secs, bool(_voice.ffmpeg_bin(ROOT)),
                                                 method)
        if action == "refuse":
            try:
                os.remove(path)
            except OSError:
                pass
            return JSONResponse({"ok": False, "error": msg}, status_code=400)
        if action in ("trim", "warn"):
            note = msg
    print(f"[voice] library saved {len(raw)} bytes → {path}"
          + (f" ({note})" if note else ""), flush=True)
    return JSONResponse({"ok": True, "name": os.path.basename(path), "path": path,
                         "size": len(raw), "note": note})


@app.post("/api/voice/library/delete")
async def voice_library_delete(req: Request) -> JSONResponse:
    """{name} → remove one clip from data/voices. Containment-guarded (realpath must
    land strictly inside the library dir), and any registry entry pinned to it is
    un-pinned in the same breath — a pin at a deleted file would only fail later, at
    speak time, far from the click that caused it."""
    if _voice is None:
        return _voice_unavailable()
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    path, why = _voice.library_target(body.get("name"), ROOT)
    if not path:
        return JSONResponse({"ok": False, "error": why}, status_code=400)
    try:
        os.remove(path)
    except OSError as e:
        return JSONResponse({"ok": False, "error": f"could not delete: {str(e)[:200]}"},
                            status_code=500)
    unpinned = []
    for m in _registry_models():
        if str(m.get("ref_audio") or "") == path:
            _registry_update(m.get("id"), {"ref_audio": None, "ref_text": None})
            unpinned.append(m.get("id"))
    print(f"[voice] library deleted {os.path.basename(path)}"
          f"{' (unpinned ' + ', '.join(unpinned) + ')' if unpinned else ''}", flush=True)
    return JSONResponse({"ok": True, "deleted": os.path.basename(path),
                         "unpinned": unpinned})


@app.post("/api/voice/tts")
async def voice_tts(req: Request) -> Response:
    """{text, model_id?} → audio/wav bytes. model_id defaults to voice.tts_model.

    Never hangs: the subprocess carries a hard 120s timeout and a second render is
    refused (409) rather than queued. Failures are JSON carrying the engine's log
    tail — the engines exit 0 on failure, so 'no wav' IS the failure signal."""
    if _voice is None:
        return _voice_unavailable()
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    text = body.get("text")
    if isinstance(text, str) and len(text) > _voice.VOICE_MAX_CHARS:
        return JSONResponse(
            {"ok": False, "error": f"text is too long ({len(text)} characters) — the cap "
                                   f"is {_voice.VOICE_MAX_CHARS} per render"},
            status_code=413)
    _, audio = _split_audio(_registry_models())
    mid = str(body.get("model_id") or "").strip() or _voice_cfg()["tts_model"]
    entry = _voice.find_entry(audio, mid) if mid else None
    if mid and entry is None:
        return JSONResponse(
            {"ok": False, "error": f"voice model '{mid}' is not in the registry"},
            status_code=400)
    err = _voice.validate_tts_request(text, entry)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)

    # SELF-HEAL (1c): an entry pinned BEFORE the pin-time transcription shipped still
    # has a clip and no transcript, and mlx-audio reacts to that by loading
    # whisper-large-v3-turbo on EVERY render and throwing it away again. Heal it here,
    # once, before the render that would otherwise pay for it — same best-effort guard
    # as the pin-time path (no STT default ⇒ the old slow-but-working behaviour).
    if _voice.needs_ref_text(entry):
        healed = await _heal_ref_text(entry, audio)
        if healed is not None:
            entry = healed

    # REPLAY CACHE (1a): a second ▶ speak of the same reply, with the same model,
    # voice and clip, is the same wav. The key covers all of them (plus the clip's
    # stat), so there is nothing to invalidate.
    ckey = _voice.entry_cache_key(entry, text)
    hit = _voice.cache_get(ckey)
    if hit is not None:
        print(f"[voice] render CACHED ({len(hit)} bytes) model={mid}", flush=True)
        return Response(content=hit, media_type="audio/wav", headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'inline; filename="speech.wav"',
            "X-Harness-Voice-Model": mid,
            "X-Harness-Voice-Cached": "1",
        })

    stats, t0 = {}, time.time()
    try:
        # spawn_guard is the ledger gate: it runs ONLY when a worker is actually
        # about to be spawned (an already-resident model is already accounted for).
        wav = await asyncio.to_thread(
            functools.partial(_voice.tts_render, entry, text, ROOT,
                              spawn_guard=_voice_spawn_guard, stats=stats))
    except _voice.VoiceBudget as e:
        print(f"[voice] tts refused ({mid}): {e.message}", flush=True)
        return JSONResponse({"ok": False, "error": e.message}, status_code=409)
    except _voice.VoiceBusy as e:
        return JSONResponse({"ok": False, "error": e.message}, status_code=409)
    except _voice.VoiceError as e:
        print(f"[voice] tts FAILED ({mid}): {e.message}", flush=True)
        return JSONResponse({"ok": False, "error": e.message, "log": e.log_tail},
                            status_code=500)
    except Exception as e:                                   # noqa: BLE001
        print(f"[voice] tts crashed ({mid}): {str(e)[:200]}", flush=True)
        return JSONResponse({"ok": False, "error": str(e)[:300]}, status_code=500)
    _voice.cache_put(ckey, wav)
    # TIMING (1b): one line per render, so "why was that slow" is answerable from the
    # log alone — a cold spawn, a re-load, or the model's own generation time.
    print(f"[voice] render {time.time() - t0:.1f}s "
          f"(engine {float(stats.get('engine_secs') or 0.0):.1f}s, "
          f"load {float(stats.get('load_secs') or 0.0):.1f}s, "
          f"worker={'SPAWNED' if stats.get('spawned') else 'reused'}, "
          f"path={stats.get('path') or '?'}) "
          f"model={mid} voice={stats.get('voice') or '(default)'} "
          f"ref={stats.get('ref') or '(none)'} chars={len(text)}", flush=True)
    return Response(content=wav, media_type="audio/wav", headers={
        "Cache-Control": "no-store",
        "Content-Disposition": 'inline; filename="speech.wav"',
        "X-Harness-Voice-Model": mid,
        "X-Harness-Voice-Cached": "0",
    })


@app.post("/api/voice/stt")
async def voice_stt(req: Request) -> JSONResponse:
    """RAW audio body → {"text": …}. Phase D (dictation).

    Body shape is deliberately the SIMPLEST thing that works: the recording is the
    whole request body, and the container comes from `?fmt=` (falling back to the
    Content-Type). Multipart would buy nothing here — there is exactly one part, and
    the panel already has the blob in hand from MediaRecorder.

    Status codes mirror /api/voice/tts so the panel's error handling is one path:
    400 unusable request (no STT default, bad format), 413 over the size cap,
    409 a render already holds the global lock, 500 with the engine's log tail.
    """
    if _voice is None:
        return _voice_unavailable()
    raw = await req.body()
    if len(raw) > _voice.VOICE_MAX_AUDIO_BYTES:
        return JSONResponse(
            {"ok": False, "error": f"that recording is too large "
                                   f"({len(raw) // (1024 * 1024)} MB) — the cap is "
                                   f"{_voice.VOICE_MAX_AUDIO_BYTES // (1024 * 1024)} MB"},
            status_code=413)
    # ?fmt= wins: MediaRecorder's mimeType is authoritative on the panel side, while a
    # Content-Type can arrive as a generic application/octet-stream from curl.
    fmt = (req.query_params.get("fmt") or "").strip() or req.headers.get("content-type", "")
    mid = (req.query_params.get("model_id") or "").strip() or _voice_cfg()["stt_model"]
    if not mid:
        return JSONResponse(
            {"ok": False, "error": "set a default STT model in Models → Audio"},
            status_code=400)
    _, audio = _split_audio(_registry_models())
    entry = _voice.find_entry(audio, mid)
    if entry is None:
        return JSONResponse(
            {"ok": False, "error": f"voice model '{mid}' is not in the registry"},
            status_code=400)
    err = _voice.validate_stt_request(raw, fmt, entry)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    try:
        text = await asyncio.to_thread(_voice.stt_transcribe, entry, raw, fmt, ROOT)
    except _voice.VoiceBusy as e:
        return JSONResponse({"ok": False, "error": e.message}, status_code=409)
    except _voice.VoiceError as e:
        print(f"[voice] stt FAILED ({mid}): {e.message}", flush=True)
        return JSONResponse({"ok": False, "error": e.message, "log": e.log_tail},
                            status_code=500)
    except Exception as e:                                   # noqa: BLE001
        print(f"[voice] stt crashed ({mid}): {str(e)[:200]}", flush=True)
        return JSONResponse({"ok": False, "error": str(e)[:300]}, status_code=500)
    print(f"[voice] stt {mid}: {len(raw)} bytes → {len(text)} chars", flush=True)
    return JSONResponse({"ok": True, "text": text, "model_id": mid})


@app.post("/api/voice/unload")
def voice_unload() -> JSONResponse:
    """Kill the resident TTS worker, freeing its weights (and its ledger claim).

    Deliberately does NOT clear the default: this is 'give me the RAM back', not
    'turn voice off'. The next ▶ speak simply pays the load again — which is also
    the honest way to verify the worker is doing its job."""
    if _voice is None:
        return _voice_unavailable()
    before = _voice.worker_resident()
    stopped = _voice.worker_stop("unload requested")
    return JSONResponse({"ok": True, "stopped": bool(stopped),
                         "was": (before or {}).get("model"),
                         "resident": _voice.worker_resident()})
