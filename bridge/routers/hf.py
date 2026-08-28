"""ROUTER — the HuggingFace browser, including the audio search and its probe."""
from __future__ import annotations

import os
from fastapi.responses import JSONResponse
from ..core.appctx import _voice, app
from ..core.hfclient import _HF
from .downloads import _mlx_repo_files


# ── Slice 2: HuggingFace model browser (Bridge runs on the Mac → real internet) ──


@app.get("/api/models/hf")
async def hf_search(q: str = "", sort: str = "downloads", fmt: str = "gguf",
                    limit: int = 25) -> JSONResponse:
    """Search HuggingFace. sort: downloads | recent | match. fmt: gguf | mlx."""
    q = (q or "").strip()
    if not q:
        return JSONResponse([])
    params = {"search": q, "limit": limit}
    if fmt in ("gguf", "mlx"):
        params["filter"] = fmt
    if sort == "downloads":
        params["sort"] = "downloads"; params["direction"] = "-1"
    elif sort == "recent":
        params["sort"] = "lastModified"; params["direction"] = "-1"
    # sort == "match" → HuggingFace relevance ranking (no sort param)
    try:
        r = await _HF.get("/api/models", params=params)
        out = [{"repo": m.get("id") or m.get("modelId"),
                "downloads": m.get("downloads", 0), "likes": m.get("likes", 0),
                "pipeline": m.get("pipeline_tag"),
                "updated": m.get("lastModified") or m.get("createdAt")}
               for m in (r.json() if r.status_code == 200 else []) if (m.get("id") or m.get("modelId"))]
        return JSONResponse(out)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=502)


@app.get("/api/models/hf/files")
async def hf_files(repo: str) -> JSONResponse:
    """Weight files + sizes for the detail/fit view. GGUF → per-file (each a model);
    else MLX (.safetensors) → the whole repo is one model (summed size)."""
    try:
        meta = await _HF.get(f"/api/models/{repo}")
        tree = await _HF.get(f"/api/models/{repo}/tree/main", params={"recursive": "true"})
        gguf, mlx = [], []
        if tree.status_code == 200:
            for it in tree.json():
                p = it.get("path", ""); low = p.lower()
                if low.endswith(".gguf"):
                    gguf.append({"filename": p, "size_bytes": it.get("size")})
                elif low.endswith(".safetensors"):
                    mlx.append({"filename": p, "size_bytes": it.get("size")})
        m = meta.json() if meta.status_code == 200 else {}
        base = {"repo": repo, "downloads": m.get("downloads", 0),
                "likes": m.get("likes", 0), "tags": m.get("tags", [])}
        if gguf:
            return JSONResponse({**base, "kind": "gguf", "files": gguf})
        return JSONResponse({**base, "kind": "mlx", "files": mlx,
                             "total_size": sum((f["size_bytes"] or 0) for f in mlx)})
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=502)


@app.get("/api/models/hf/card")
async def hf_card(repo: str) -> JSONResponse:
    """The model's README (front-matter stripped), rendered in-app instead of the browser."""
    try:
        r = await _HF.get(f"/{repo}/raw/main/README.md")
        text = r.text if r.status_code == 200 else ""
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) == 3:
                text = parts[2]
        return JSONResponse({"repo": repo, "markdown": text[:20000]})
    except Exception as e:
        return JSONResponse({"repo": repo, "markdown": "", "error": str(e)[:200]})


# ── Audio HF search (T2) ──────────────────────────────────────────────────────
# WHY: the Audio tab shipped with five curated starters and Debi asked the obvious
# question — "why are there only these models". This is the discovery half. It is a
# SEPARATE surface from /api/models/hf because voice discovery is nothing like chat
# discovery: the useful axis is pipeline_tag + framework, not a quant filename, and
# the RESULT of a search must be probed before it can be trusted (see below).
#
# THREE web-verified facts drive the shape of this code (2026-08-08 research):
#   1. `?library=` on the models API is SILENTLY IGNORED. Never send it; `?filter=`
#      is the parameter that actually narrows.
#   2. TTS discovery must be a UNION of `filter=mlx-audio` and `filter=mlx` — the
#      mlx-audio tag alone MISSES Kokoro, the best quality-per-MB model we offer.
#   3. TAGS LIE. `openai/whisper-medium` carries every whisper token and is a
#      TRANSFORMERS checkpoint that mlx_whisper cannot load (it died with
#      "ModelDimensions.__init__() unexpected keyword '_name_or_path'" on Debi's
#      machine). Only config.json settles it — hence the probe endpoint.
AUDIO_SEARCH_KINDS = ("tts", "tts-gguf", "stt")

# ⚠️ PENDING FABLE QA: the kind vocabulary is THREE, not the brief's two. The GGUF
# TTS lane is a different query shape (filter=gguf + a text term, no pipeline_tag —
# GGUF repos are not pipeline-tagged) and mixing its hits into the MLX list would
# make one result list whose rows mean different things. A third chip is cheaper
# than a heterogeneous list.
AUDIO_SEARCH_QUERIES = {
    "tts": ({"filter": "mlx-audio", "pipeline_tag": "text-to-speech"},
            {"filter": "mlx", "pipeline_tag": "text-to-speech"}),
    "stt": ({"filter": "mlx", "pipeline_tag": "automatic-speech-recognition"},),
    "tts-gguf": ({"filter": "gguf"},),
}
# The GGUF lane has no pipeline tag to lean on, so an empty box still needs a term.
AUDIO_GGUF_DEFAULT_TERM = "tts"

# Licences we will NOT offer a Get for. Non-commercial covers the whole cc-by-nc
# family (Spark-TTS = cc-by-nc-sa, Voxtral-TTS = cc-by-nc with 20 tempting named
# voices). The row is still SHOWN — hiding a model would be a worse lie than
# showing it with the reason its button is off.
_NC_PREFIXES = ("cc-by-nc", "cc-nc")
_NC_SUBSTRINGS = ("noncommercial", "non-commercial")
_UNKNOWN_LICENSES = ("", "other", "unknown", "none")
# OpenRAIL is NOT non-commercial — it permits commercial use with behavioural
# use-restrictions. Blocking it would cost real models for no legal reason on a
# personal machine, so it gets an honest amber badge instead (Fable fix 2026-08-13).
_RESTRICTED_PREFIXES = ("creativeml-openrail", "openrail", "bigscience-openrail")

LICENSE_NC_REASON = "non-commercial licence"

# ── known-mistagged repos ─────────────────────────────────────────────────────
# Some upstreams tag the CODE licence on a repo whose WEIGHTS carry a different
# one. Our licence gate reads the tag, so a mistag defeats it silently. This table
# is the honest correction, consulted BEFORE the tag-derived badge at BOTH call
# sites (the search rows and the single-repo probe).
#
# OmniVoice: k2-fsa's own README says verbatim — "Our code is released under the
# Apache 2.0 License. The pre-trained model is licensed under the CC-BY-NC due to
# constraints from its training data (e.g. Emilia)."
#   https://huggingface.co/k2-fsa/OmniVoice   (see docs/research/2026-08-14-omnivoice-provenance.md)
# The k2 repo itself carries NO licence tag; every mlx-community/OmniVoice* repo
# tags itself apache-2.0 — the code licence, not the weights licence. Every one of
# them declares base_model k2-fsa/OmniVoice with the identical 612,577,280 params,
# i.e. a format conversion, so the weights term follows the conversion.
#
# ⚠️ PENDING FABLE QA: the badge is AMBER and **Get stays ENABLED**, unlike the
# unambiguous cc-by-nc-TAGGED rows (Spark-TTS, Voxtral-TTS) which stay disabled.
# Rationale: this is Debi's own machine and personal use is unaffected by CC-BY-NC;
# the honest thing is to SAY the weights term, not to hide the model behind a
# button we turn off. Same verdict shape as the recorded unknown-licence and
# OpenRAIL calls — honesty over gatekeeping. Flipping this to "nc" would disable
# Get on a model the harness already ships as its recommended TTS.
OMNIVOICE_LICENSE_REASON = ("weights CC-BY-NC per upstream README; code Apache-2.0")

# MiniMax-Music3: the SECOND confirmed instance of the same defect class, on a new
# model family (docs/research/2026-08-20-music-video-gen.md § Corrections #1) — i.e.
# this table is structural, not a one-off patch.
# `Abiray/MiniMax-Music3-GGUF` declares `license: apache-2.0` and its README claims it
# "Inherits the Apache-2.0 License from the original release" — FALSE. Upstream
# `MiniMaxAI/MiniMax-Music3` ships a custom "MiniMax-Music3 COMMUNITY LICENSE" with
# attribution duties on commercial surfaces, a $20M-revenue written-authorization
# trigger, a safeguards clause, and a 19-clause acceptable-use policy.
#   https://huggingface.co/MiniMaxAI/MiniMax-Music3/blob/main/LICENSE
# The contrast that proves the tag cannot be trusted, only the file:
# `PocketAiHub/MiniMax-Music3-MLX` tags itself `license: other` +
# `license_name: minimax-music3-community` and links the real LICENSE (verified live
# via the HF API, 2026-08-20) — one repackager was honest, one was not. The key covers
# the whole family (upstream, the honest MLX port, the Comfy-Org repack, every quant)
# because the weights term follows a format conversion, exactly as for OmniVoice.
#
# ⚠️ PENDING FABLE QA: amber, Get ENABLED — same verdict shape as OmniVoice and
# OpenRAIL. This licence is NOT non-commercial; personal use is unaffected and the
# duties bite only on commercial surfaces, so the honest move is to SAY the term
# rather than switch off a button.
MINIMAX_MUSIC3_LICENSE_REASON = (
    "weights under the MiniMax-Music3 Community License (attribution on commercial "
    "surfaces, written authorization above $20M revenue); some repacks mistag apache-2.0")

_MINIMAX_MUSIC3_RECORD = {
    "license": "minimax-community (weights)",
    "badge": "unknown",
    "reason": MINIMAX_MUSIC3_LICENSE_REASON,
    "source_url": "https://huggingface.co/MiniMaxAI/MiniMax-Music3/blob/main/LICENSE",
}

# key = a lowercase SUBSTRING matched against the repo id (so every fork/quant of a
# family is covered without listing them all — the mlx-community set alone is six
# repos and theoracleguy has a seventh).
LICENSE_OVERRIDES = {
    "omnivoice": {
        "license": "cc-by-nc (weights)",
        "badge": "unknown",
        "reason": OMNIVOICE_LICENSE_REASON,
        "source_url": "https://huggingface.co/k2-fsa/OmniVoice",
    },
    "minimax-music3": _MINIMAX_MUSIC3_RECORD,
    # Comfy-Org spells the repack `MiniMax-Music-3` (extra hyphen) and every GGUF
    # quant of it inherits that spelling, so BOTH forms are listed rather than
    # relying on one substring to catch a name we do not control.
    "minimax-music-3": _MINIMAX_MUSIC3_RECORD,
}


def license_override(repo: object) -> dict:
    """PURE: the override record for a repo id, or {} when nothing is known.

    Substring match, case-insensitive, on the whole `org/name` string.
    """
    if not isinstance(repo, str) or not repo.strip():
        return {}
    low = repo.strip().lower()
    for key, rec in LICENSE_OVERRIDES.items():
        if key in low:
            return dict(rec)
    return {}


def audio_license_row(repo: object, meta: object) -> dict:
    """PURE: the licence record for one repo — override FIRST, tag second.

    This is the ONE seam both the search rows and the probe go through, so a
    known mistag can never reach the UI through one path and not the other.
    """
    ov = license_override(repo)
    return ov if ov else audio_license_badge(hf_license(meta))


def hf_license(meta: object) -> str:
    """PURE: the licence id for a model, from cardData.license or a `license:*` tag.

    The list API returns tags but usually no cardData; the single-model API returns
    both. Reading either means one function serves both call sites.
    """
    if not isinstance(meta, dict):
        return ""
    card = meta.get("cardData")
    lic = card.get("license") if isinstance(card, dict) else None
    if isinstance(lic, (list, tuple)):
        lic = lic[0] if lic else None
    if not isinstance(lic, str) or not lic.strip():
        lic = meta.get("license") if isinstance(meta.get("license"), str) else None
    if isinstance(lic, str) and lic.strip():
        return lic.strip().lower()
    for t in (meta.get("tags") or []):
        if isinstance(t, str) and t.lower().startswith("license:"):
            return t.split(":", 1)[1].strip().lower()
    return ""


def audio_license_badge(license_id: object) -> dict:
    """PURE: {"license", "badge", "reason"} for one licence id.

    badge ∈ ok | unknown | nc.
      nc      → Get DISABLED, reason shown on the row.
      unknown → amber badge, Get STILL ENABLED. ⚠️ PENDING FABLE QA: this is Debi's
                own machine and a missing license tag is extremely common on model
                repos (kitten, soprano, the ggml-org GGUF mirrors all lack one);
                refusing them would hide half of HuggingFace over metadata hygiene.
                We badge the uncertainty instead of pretending to know.
      ok      → apache/mit/etc.
    """
    lic = (license_id or "").strip().lower() if isinstance(license_id, str) else ""
    if lic in _UNKNOWN_LICENSES:
        return {"license": lic, "badge": "unknown", "reason": "licence unknown"}
    if lic.startswith(_NC_PREFIXES) or any(s in lic for s in _NC_SUBSTRINGS):
        return {"license": lic, "badge": "nc", "reason": LICENSE_NC_REASON}
    if lic.startswith(_RESTRICTED_PREFIXES):
        # amber like unknown, but with the true reason; Get stays ENABLED
        return {"license": lic, "badge": "unknown", "reason": "use-restricted licence"}
    return {"license": lic, "badge": "ok", "reason": ""}


# Replicated from scripts/seed_registry.py (the bridge does not import scripts/).
# bridge/tests/test_audio_search.py asserts these are BYTE-IDENTICAL to the seed
# copy, so the two can never drift apart silently.
AUDIO_WHISPER_REQUIRED = ("n_mels", "n_audio_state", "n_audio_head",
                          "n_audio_layer", "n_vocab", "n_text_state")
AUDIO_WHISPER_VETO = ("_name_or_path", "architectures", "transformers_version",
                      "num_mel_bins", "d_model", "encoder_layers",
                      "decoder_layers", "is_encoder_decoder")


def is_mlx_whisper_cfg(cfg: object) -> bool:
    """PURE: True only for a config.json that is an mlx-whisper ModelDimensions."""
    if not isinstance(cfg, dict):
        return False
    if any(k in cfg for k in AUDIO_WHISPER_VETO):
        return False
    return all(k in cfg for k in AUDIO_WHISPER_REQUIRED)


# Replicated the same way, for the SECOND STT engine (mlx-audio / Parakeet). See
# scripts/seed_registry.py::is_parakeet_config for the reasoning; the test asserts
# these four are byte-identical to the seed copy too, so the pair cannot drift.
AUDIO_PARAKEET_SHAPE_KEYS = ("preprocessor", "encoder", "decoder")
AUDIO_PARAKEET_TARGET_PREFIX = "nemo."
AUDIO_PARAKEET_MIN_NEMO_BLOCKS = 2
AUDIO_PARAKEET_MODEL_TYPES = ("parakeet",)


def is_parakeet_cfg(cfg: object) -> bool:
    """PURE: True only for a NeMo/Parakeet config mlx-audio's STT loader can drive.
    The transformers veto is NOT applied to the shape rule — a positive `nemo.`
    fingerprint is stronger evidence than the absence of transformers keys."""
    if not isinstance(cfg, dict):
        return False
    n = 0
    for k in AUDIO_PARAKEET_SHAPE_KEYS:
        blk = cfg.get(k)
        if isinstance(blk, dict):
            tgt = blk.get("_target_")
            if isinstance(tgt, str) and tgt.startswith(AUDIO_PARAKEET_TARGET_PREFIX):
                n += 1
    if n >= AUDIO_PARAKEET_MIN_NEMO_BLOCKS:
        return True
    mt = cfg.get("model_type")
    if isinstance(mt, str) and mt.strip().lower() in AUDIO_PARAKEET_MODEL_TYPES:
        return not any(k in cfg for k in AUDIO_WHISPER_VETO)
    return False


_TTS_TOKENS = ("tts", "text-to-speech", "speech", "voice", "kokoro", "outetts")


def _file_pairs(files: object) -> list:
    """Coerce a caller's `files` into [(path:str, size:int)]. Third-party JSON goes
    through every one of these functions; a TypeError here would blank the Audio tab."""
    out = []
    for it in (files if isinstance(files, (list, tuple)) else []):
        if isinstance(it, (list, tuple)) and len(it) == 2 and isinstance(it[0], str):
            out.append((it[0], it[1] if isinstance(it[1], int) else 0))
    return out


def gguf_tts_pair(files: object) -> tuple:
    """PURE: (backbone, mmproj) from [(path, size)] — or (None, None).

    llama-tts needs BOTH halves; a repo with only one is not a usable TTS model.
    Preference mirrors the curated starter exactly (Q4_K_M backbone, Q8_0 projector)
    so a searched Qwen3-TTS lands byte-identical to the offered one.
    """
    import os as _os
    ggufs = [(p, s) for p, s in _file_pairs(files) if p.lower().endswith(".gguf")]
    mm = [p for p, _ in ggufs if "mmproj" in _os.path.basename(p).lower()]
    back = [(p, s or 0) for p, s in ggufs
            if "mmproj" not in _os.path.basename(p).lower()]
    if not mm or not back:
        return (None, None)
    pick = next((p for p, _ in back if "q4_k_m" in p.lower()),
                min(back, key=lambda t: t[1])[0])
    proj = next((p for p in mm if "q8_0" in p.lower()), mm[0])
    return (pick, proj)


def audio_probe_verdict(repo: object, cfg: object, files: object,
                        tags: object = (), pipeline: object = "") -> dict:
    """PURE: classify one HF repo for the Audio tab. Never raises.

    Returns {format, warn, file, mmproj, can_get, block_reason} where format ∈
      tts-mlx | stt-mlx | tts-gguf   → a lane the harness can actually drive
      transformers                   → the whisper-medium class: LOOKS right, is not
      unknown                        → we could not tell; Get stays off

    ORDER MATTERS. The transformers veto is applied ONLY on the ASR lane: a TTS
    config that happens to carry `architectures` (several mlx-audio conversions do)
    must not be condemned by a rule written for whisper.
    """
    import os as _os
    repo = repo if isinstance(repo, str) else ""
    pipeline = (pipeline or "").lower() if isinstance(pipeline, str) else ""
    # tags/files are third-party JSON: a surprise type here must not take out the tab.
    tagset = {t.lower() for t in (tags if isinstance(tags, (list, tuple)) else [])
              if isinstance(t, str)}
    pairs = _file_pairs(files)
    paths = [p for p, _ in pairs]
    lowp = [p.lower() for p in paths]
    has_weights = any(p.endswith((".safetensors", ".npz")) for p in lowp)
    has_cfg = any(_os.path.basename(p) == "config.json" for p in paths)
    cfgd = cfg if isinstance(cfg, dict) else {}
    asr_lane = ("whisper" in repo.lower()
                or pipeline == "automatic-speech-recognition"
                or "automatic-speech-recognition" in tagset)

    def _out(fmt, warn="", file=None, mmproj=None):
        # An MLX verdict with no weights/config in the tree would send the Get into
        # whole-repo mode, which 400s ("not an MLX model"). Better to say we do not
        # know than to hand the user a button that cannot work.
        if fmt in ("tts-mlx", "stt-mlx", "stt-mlx-audio") and not (has_weights and has_cfg):
            fmt, warn = "unknown", ("looks like a voice model but ships no "
                                    "safetensors/npz weights + config.json")
        blocked = {"transformers": "transformers checkpoint — not an MLX conversion; "
                                   "mlx_whisper cannot load it",
                   "unknown": "the harness could not identify an engine for this repo"}
        reason = blocked.get(fmt, "")
        if fmt == "unknown" and warn:
            reason = warn                      # the specific miss beats the generic one
        return {"format": fmt, "warn": warn, "file": file, "mmproj": mmproj,
                "can_get": fmt not in blocked, "block_reason": reason}

    # 1. The checkpoint says it is a TTS model (strongest possible evidence).
    if "tts_model_type" in cfgd or isinstance(cfgd.get("talker_config"), dict):
        return _out("tts-mlx")
    # 2. mlx-audio's own tag.
    if "mlx-audio" in tagset:
        return _out("tts-mlx")
    # 3/4. The whisper lane — shape decides, name never does.
    if is_mlx_whisper_cfg(cfgd):
        return _out("stt-mlx")
    # 3b. The OTHER ASR lane: mlx-audio's NeMo/Parakeet family. Checked BEFORE the
    #     transformers veto, because a NeMo config legitimately carries
    #     `model_defaults`/`target` keys and the veto would condemn every real
    #     Parakeet repo — the positive `nemo._target_` fingerprint decides instead.
    if is_parakeet_cfg(cfgd):
        return _out("stt-mlx-audio")
    if asr_lane and cfgd and any(k in cfgd for k in AUDIO_WHISPER_VETO):
        return _out("transformers")
    # 5. GGUF TTS pair (backbone + projector). A TTS token is required: every
    #    vision chat model is also a gguf+mmproj pair and must not land here.
    back, proj = gguf_tts_pair(pairs)
    if back and (any(t in repo.lower() for t in _TTS_TOKENS)
                 or any(t in tagset for t in _TTS_TOKENS)):
        return _out("tts-gguf", file=back, mmproj=proj)
    # 6/7. Tag-only fallbacks for a correctly-shaped MLX repo we cannot fingerprint.
    if has_weights and has_cfg:
        if pipeline == "text-to-speech" or "text-to-speech" in tagset:
            return _out("tts-mlx", warn="not tagged mlx-audio — engine support is "
                                        "unverified for this repo")
        if asr_lane:
            return _out("transformers" if cfgd else "unknown")
    return _out("unknown")


def audio_probe_size(fmt: object, files: object, back=None, proj=None) -> int:
    """PURE: bytes the Get would actually download for this verdict."""
    pairs = _file_pairs(files)
    if fmt == "tts-gguf":
        want = {back, proj}
        return sum(s for p, s in pairs if p in want)
    if fmt in ("tts-mlx", "stt-mlx", "stt-mlx-audio"):
        return sum(s for _, s in _mlx_repo_files(
            [{"path": p, "size": s, "type": "file"} for p, s in pairs]))
    return 0


def audio_probe_voices(cfg: object, files: object) -> list:
    """PURE: named voices this repo declares — config.json spk_id, or Kokoro's
    voices/*.pt stems. Same two mechanisms voices_for_entry resolves on disk, read
    here from the HF tree so the count is visible BEFORE downloading."""
    names = []
    if _voice is not None:
        try:
            names = list(_voice.voices_from_config(cfg).get("voices") or [])
        except Exception:                                  # noqa: BLE001
            names = []
    if names:
        return names
    out = []
    for p, _ in _file_pairs(files):
        low = p.lower().replace("\\", "/")
        if low.startswith("voices/") and low.endswith(".pt"):
            out.append(p.split("/")[-1][:-3])
    return sorted(out)


async def _hf_json(path: str, params=None):
    """GET a HuggingFace JSON endpoint; None on any non-200/exception."""
    try:
        r = await _HF.get(path, params=params or {})
        return r.json() if r.status_code == 200 else None
    except Exception:                                      # noqa: BLE001
        return None


@app.get("/api/models/hf/audio")
async def hf_audio_search(q: str = "", kind: str = "tts", limit: int = 25) -> JSONResponse:
    """Search HuggingFace for VOICE models. kind ∈ tts | tts-gguf | stt.

    The tts kind is the documented UNION of two queries (mlx-audio ∪ mlx) deduped
    by repo id — mlx-audio alone misses Kokoro.
    """
    kind = (kind or "tts").strip().lower()
    if kind not in AUDIO_SEARCH_KINDS:
        return JSONResponse({"error": f"unknown kind {kind!r}"}, status_code=400)
    q = (q or "").strip()
    term = q or (AUDIO_GGUF_DEFAULT_TERM if kind == "tts-gguf" else "")
    seen, out = set(), []
    for base in AUDIO_SEARCH_QUERIES[kind]:
        params = dict(base, limit=limit, sort="downloads", direction="-1")
        if term:
            params["search"] = term
        rows = await _hf_json("/api/models", params)
        if rows is None:
            continue
        for m in rows:
            repo = m.get("id") or m.get("modelId")
            if not repo or repo in seen:
                continue
            seen.add(repo)
            lic = audio_license_row(repo, m)
            out.append({"repo": repo, "downloads": m.get("downloads", 0),
                        "likes": m.get("likes", 0),
                        "pipeline": m.get("pipeline_tag"),
                        "updated": m.get("lastModified") or m.get("createdAt"),
                        **lic})
    if not out and not seen:
        return JSONResponse({"error": "HuggingFace search failed"}, status_code=502)
    out.sort(key=lambda r: r.get("downloads") or 0, reverse=True)
    return JSONResponse(out[:limit * 2])


@app.get("/api/models/hf/audio/probe")
async def hf_audio_probe(repo: str) -> JSONResponse:
    """Config-probe ONE repo: what engine (if any) can drive it, how big the Get is,
    how many named voices it declares, and whether its licence lets us offer it.

    This is the whisper-medium fix generalised: a row is never Get-able because of
    what it is CALLED, only because of what its config.json and file tree say."""
    repo = (repo or "").strip()
    if not repo:
        return JSONResponse({"error": "repo required"}, status_code=400)
    meta = await _hf_json(f"/api/models/{repo}") or {}
    tree = await _hf_json(f"/api/models/{repo}/tree/main",
                          {"recursive": "true"}) or []
    files = [(it.get("path", ""), it.get("size") or 0) for it in tree
             if isinstance(it, dict) and (it.get("type") or "file") == "file"
             and it.get("path")]
    cfg = None
    if any(os.path.basename(p) == "config.json" for p, _ in files):
        try:
            r = await _HF.get(f"/{repo}/raw/main/config.json")
            if r.status_code == 200:
                import json as _json
                cfg = _json.loads(r.text)
                if not isinstance(cfg, dict):
                    cfg = None
        except Exception:                                  # noqa: BLE001
            cfg = None
    v = audio_probe_verdict(repo, cfg, files, meta.get("tags") or [],
                            meta.get("pipeline_tag") or "")
    lic = audio_license_row(repo, meta)
    if lic["badge"] == "nc":
        v["can_get"] = False
        v["block_reason"] = lic["reason"]
    voices = audio_probe_voices(cfg, files)
    return JSONResponse({"repo": repo, **v, **lic,
                         "size_bytes": audio_probe_size(v["format"], files,
                                                        v.get("file"), v.get("mmproj")),
                         "voices": voices, "voice_count": len(voices),
                         "downloads": meta.get("downloads", 0),
                         "likes": meta.get("likes", 0),
                         "files": len(files)})
