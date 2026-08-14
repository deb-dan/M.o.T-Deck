#!/usr/bin/env python3
"""Build data/models.json — the harness's own model registry (llamacpp adapter).

Scans (a) the harness-owned models dir data/models/ (source "local" — where the
cleanup slice migrates Jan's models into, and where the download manager writes),
(b) Jan's model folder (imports GGUF models the user still has there), and
(c) LM Studio's library, then merges into data/models.json, preserving any
non-rescanned entries (e.g. download-manager additions, source "download"). stdlib
only.

It also scans for AUDIO (voice) models — kind:"audio" entries the Models → Audio tab
owns and api_models keeps OUT of every chat list: (d) data/models/ folders whose name
+ file shape match a known TTS/STT family (source "local", app-owned) and (e) the
machine-wide HuggingFace cache (source "audio-hf-cache", read-only). See
audio_format_for() for why that classifier is deliberately narrow.

Structured as functions so the scan/merge logic can be unit-tested against a temp
dir without touching the real one. main() uses the real paths.
"""
import os
import json
import configparser

JAN_MODELS_DIR = os.path.expanduser(
    "~/Library/Application Support/Jan/data/llamacpp/models")
JAN_PRESET_INI = os.path.expanduser(
    "~/Library/Application Support/Jan/data/llamacpp/router.preset.ini")
LMSTUDIO_MODELS_DIR = os.path.expanduser("~/.lmstudio/models")
LOCAL_MODELS_DIR = os.path.join("data", "models")
REGISTRY_PATH = os.path.join("data", "models.json")


def _load_preset(preset_path):
    """Parse router.preset.ini → {section_id: ctx_size_int}. Ignores [*] defaults."""
    ctx_by_id = {}
    if not os.path.isfile(preset_path):
        return ctx_by_id
    cfg = configparser.ConfigParser()
    try:
        cfg.read(preset_path)
    except Exception:
        return ctx_by_id
    for section in cfg.sections():
        if section == "*":
            continue
        raw = cfg.get(section, "ctx-size", fallback=None)
        if raw is None:
            continue
        try:
            ctx_by_id[section] = int(str(raw).strip())
        except (ValueError, TypeError):
            ctx_by_id[section] = None
    return ctx_by_id


def scan_jan(jan_dir, preset_path=JAN_PRESET_INI):
    """Return a list of jan-import registry entries for every subfolder of jan_dir
    that contains a model.gguf."""
    entries = []
    if not os.path.isdir(jan_dir):
        return entries
    ctx_by_id = _load_preset(preset_path)
    for name in sorted(os.listdir(jan_dir)):
        folder = os.path.join(jan_dir, name)
        if not os.path.isdir(folder):
            continue
        model_path = os.path.join(folder, "model.gguf")
        if not os.path.isfile(model_path):
            continue
        mmproj_path = os.path.join(folder, "mmproj.gguf")
        mmproj = mmproj_path if os.path.isfile(mmproj_path) else None
        try:
            size_bytes = os.path.getsize(model_path)
        except OSError:
            size_bytes = None
        entries.append({
            "id": name,
            "name": name,
            "format": "gguf",
            "path": os.path.abspath(model_path),
            "mmproj": os.path.abspath(mmproj) if mmproj else None,
            "size_bytes": size_bytes,
            "ctx": ctx_by_id.get(name),
            "vision": bool(mmproj),
            "source": "jan-import",
        })
    return entries


def scan_local(local_dir):
    """Return source "local" registry entries for every subfolder of local_dir
    (the harness-owned data/models/) that contains a model.gguf (+ optional
    mmproj.gguf) — the shape the migrate_jan_models.sh cleanup produces. ctx is
    None here (no preset); the merge step carries a previously-known ctx forward.
    Download-manager models keep their real gguf filenames (not model.gguf) so
    they are skipped here and preserved via their source "download" entries."""
    entries = []
    if not os.path.isdir(local_dir):
        return entries
    for name in sorted(os.listdir(local_dir)):
        folder = os.path.join(local_dir, name)
        if not os.path.isdir(folder):
            continue
        model_path = os.path.join(folder, "model.gguf")
        if not os.path.isfile(model_path):
            continue
        mmproj_path = os.path.join(folder, "mmproj.gguf")
        mmproj = mmproj_path if os.path.isfile(mmproj_path) else None
        try:
            size_bytes = os.path.getsize(model_path)
        except OSError:
            size_bytes = None
        entries.append({
            "id": name,
            "name": name,
            "format": "gguf",
            "path": os.path.abspath(model_path),
            "mmproj": os.path.abspath(mmproj) if mmproj else None,
            "size_bytes": size_bytes,
            "ctx": None,
            "vision": bool(mmproj),
            "source": "local",
        })
    return entries


# ── Audio (voice) models — FABLE-VOICE-CAPABILITY-SPEC Phase A ────────────────
# Debi's ask: "rescan audio models already on the computer". The classifier below is
# deliberately CONSERVATIVE. A miss just means the user clicks Get; a FALSE POSITIVE
# turns a chat model into an audio model, which makes it VANISH from every chat list
# (api_models partitions audio out) — a silent, confusing failure. So a folder is only
# ever classified as audio when its name carries an explicit family token AND its file
# shape matches the engine that would run it.
#
# ⚠️ PENDING FABLE QA: the token lists are the whole safety margin. Adding a generic
# word here (e.g. "audio", "voice", "speech") would start catching chat models.
AUDIO_TTS_TOKENS = ("tts", "kokoro", "outetts")
# "parakeet" joins "whisper" as an STT family token. It is a BIRD, not a generic
# speech word — it cannot start eating chat models the way "audio"/"voice"/"speech"
# would. Which of the two STT engines a folder actually is stays a CONFIG decision
# (audio_format_probed below); this list only says "look at it at all".
AUDIO_STT_TOKENS = ("whisper", "parakeet")
AUDIO_HF_CACHE_DIR = os.path.expanduser("~/.cache/huggingface/hub")


def _has_token(text, tokens):
    low = (text or "").lower()
    return any(t in low for t in tokens)


def audio_format_for(dir_name, filenames):
    """PURE classifier: 'tts-gguf' | 'tts-mlx' | 'stt-mlx' | None for ONE model folder.

    `dir_name` is the folder's basename, `filenames` its direct entries (no recursion —
    both the download manager and mlx conversions write flat model dirs).

      MLX shape  : config.json + >=1 *.safetensors, folder named whisper*  → stt-mlx
                                                    folder named *tts*/kokoro/outetts → tts-mlx
      GGUF pair  : >=1 non-mmproj *.gguf AND >=1 mmproj*.gguf, and a TTS token in the
                   folder name OR in the backbone filename                → tts-gguf
                   (llama-tts at b10295 needs BOTH halves; a lone gguf is never audio.)

    Anything else → None (i.e. a chat model, or not a model at all).
    """
    names = list(filenames or [])
    low = [n.lower() for n in names]
    has_cfg = "config.json" in low
    safet = [n for n in low if n.endswith(".safetensors")]
    if has_cfg and safet:
        # STT first: a whisper folder can never also be a TTS folder, and checking it
        # first keeps the (hypothetical) "whisper-tts" name out of the TTS bucket.
        if _has_token(dir_name, AUDIO_STT_TOKENS):
            return "stt-mlx"
        if _has_token(dir_name, AUDIO_TTS_TOKENS):
            return "tts-mlx"
        return None
    ggufs = [n for n in names if n.lower().endswith(".gguf")
             and "mmproj" not in n.lower()]
    mmprojs = [n for n in names if n.lower().endswith(".gguf")
               and "mmproj" in n.lower()]
    if ggufs and mmprojs:
        if _has_token(dir_name, AUDIO_TTS_TOKENS) or any(
                _has_token(g, AUDIO_TTS_TOKENS) for g in ggufs):
            return "tts-gguf"
    return None


# ── the whisper config probe (closes a real false-positive) ──────────────────
# `openai/whisper-medium` in the HF cache is a TRANSFORMERS checkpoint: it carries a
# whisper token in the name, a config.json and safetensors, so the NAME-based
# classifier above happily called it stt-mlx — and then mlx_whisper died with
# `ModelDimensions.__init__() unexpected keyword '_name_or_path'`, at dictation time,
# far from the cause. (A whole-repo download of one would also drag ~12GB of four
# redundant weight formats.) The filename layer cannot tell these apart; the CONFIG
# can, because the two projects use disjoint vocabularies:
#
#   mlx-whisper : config.json IS a serialised ModelDimensions — n_mels, n_audio_state,
#                 n_audio_head, n_audio_layer, n_vocab, n_text_state, …
#   transformers: _name_or_path, architectures, transformers_version, num_mel_bins,
#                 d_model, encoder_layers, decoder_layers, is_encoder_decoder
#                 (whisper-medium trips all eight)
#
# So: any veto key present ⇒ reject outright; otherwise ALL six required keys must be
# there. Both halves matter — the veto catches a transformers config that happens to
# gain an mlx-looking key, the requirement catches a config that is neither.
MLX_WHISPER_REQUIRED = ("n_mels", "n_audio_state", "n_audio_head",
                        "n_audio_layer", "n_vocab", "n_text_state")
MLX_WHISPER_VETO = ("_name_or_path", "architectures", "transformers_version",
                    "num_mel_bins", "d_model", "encoder_layers",
                    "decoder_layers", "is_encoder_decoder")


def is_mlx_whisper_config(cfg):
    """PURE: True only for a config.json that is an mlx-whisper ModelDimensions."""
    if not isinstance(cfg, dict):
        return False
    if any(k in cfg for k in MLX_WHISPER_VETO):
        return False
    return all(k in cfg for k in MLX_WHISPER_REQUIRED)


# ── the parakeet / NeMo config probe (the second STT engine) ─────────────────
# A NeMo checkpoint shares NOTHING with the whisper ModelDimensions shape — it has
# none of the six required keys and usually no `model_type` at all — so the whisper
# probe correctly rejects it, and without a second rule a downloaded Parakeet would
# silently vanish from the Audio tab.
#
# The fingerprint is NOT a name guess. NeMo serialises its module graph with hydra
# `_target_` strings, so a real parakeet config carries e.g.
#   preprocessor._target_ = "nemo.collections.asr.modules.AudioToMelSpectrogramPreprocessor"
#   encoder._target_      = "nemo.collections.asr.modules.ConformerEncoder"
#   decoder._target_      = "nemo.collections.asr.modules.RNNTDecoder"
# (read from the real mlx-community/parakeet-tdt-0.6b-v3 config.json). Requiring TWO
# of those blocks to name `nemo.` is what separates it from a transformers checkpoint
# such as `nvidia/parakeet-tdt-0.6b-v3` itself, which is a torch/transformers repo
# mlx-audio cannot load — the exact whisper-medium class of false positive.
#
# ⚠️ The whisper transformers VETO is deliberately NOT applied here. It is an
# ASR-lane rule written for whisper; a NeMo config may legitimately carry keys that
# look transformers-ish, and applying the veto would condemn every Parakeet repo.
# The nemo `_target_` requirement is a POSITIVE fingerprint and does that job better.
PARAKEET_SHAPE_KEYS = ("preprocessor", "encoder", "decoder")
PARAKEET_TARGET_PREFIX = "nemo."
PARAKEET_MIN_NEMO_BLOCKS = 2
PARAKEET_MODEL_TYPES = ("parakeet",)


def _nemo_block_count(cfg):
    """How many of the three shape blocks are dicts naming a `nemo.` _target_."""
    n = 0
    for k in PARAKEET_SHAPE_KEYS:
        blk = cfg.get(k)
        if not isinstance(blk, dict):
            continue
        tgt = blk.get("_target_")
        if isinstance(tgt, str) and tgt.startswith(PARAKEET_TARGET_PREFIX):
            n += 1
    return n


def is_parakeet_config(cfg):
    """PURE: True only for a config.json mlx-audio's parakeet loader can drive."""
    if not isinstance(cfg, dict):
        return False
    if _nemo_block_count(cfg) >= PARAKEET_MIN_NEMO_BLOCKS:
        return True
    # A conversion that declares itself outright still counts — but only when it is
    # NOT also waving the transformers flags (mlx-audio injects "parakeet" itself, so
    # a checkpoint carrying it AND `architectures` is somebody else's repackaging).
    mt = cfg.get("model_type")
    if isinstance(mt, str) and mt.strip().lower() in PARAKEET_MODEL_TYPES:
        return not any(k in cfg for k in MLX_WHISPER_VETO)
    return False


def stt_format_by_name(dir_name):
    """PURE: the lenient last-resort verdict, mirroring what mlx-audio's own loader
    does (dash-split name-part matching against its stt/models/ directory)."""
    return "stt-mlx-audio" if _has_token(dir_name, ("parakeet",)) else "stt-mlx"


def _read_json(path):
    """A dict, or None when absent/unreadable/not an object. Never raises."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else None
    except (OSError, ValueError):
        return None


def audio_format_probed(dir_name, filenames, folder, strict=True):
    """audio_format_for + the config probe for the STT verdicts only.

    The name-based classifier can only say "this looks like an STT folder"; WHICH
    engine it is (stt-mlx = mlx-whisper, stt-mlx-audio = mlx-audio/Parakeet) is
    decided by config.json, never by the folder name — except in the lenient
    last-resort branch below.


    `strict=True` (the HF cache) FAILS CLOSED: an unreadable config means we do not
    know, and "do not know" must not become "hand this to mlx_whisper" — the cache is
    full of other apps' downloads and a false positive there is exactly the bug this
    closes.

    ⚠️ PENDING FABLE QA — `strict=False` (data/models/, our OWN tree) keeps the old
    name-token behaviour when the config cannot be READ (present but corrupt/
    unparseable). Rationale: a folder we downloaded ourselves with the stt-mlx hint is
    ours, and silently dropping it from the registry over a parse error would look
    like the model vanished. A config that parses is always obeyed, in both modes.
    """
    fmt = audio_format_for(dir_name, filenames)
    if fmt != "stt-mlx":
        return fmt
    cfg = _read_json(os.path.join(folder, "config.json"))
    if cfg is None:
        return None if strict else stt_format_by_name(dir_name)
    # Strongest evidence first, and the two probes are DISJOINT by construction (a
    # ModelDimensions config has no nemo `_target_` blocks and vice versa), so the
    # order below is documentation rather than a tie-break.
    if is_mlx_whisper_config(cfg):
        return "stt-mlx"
    if is_parakeet_config(cfg):
        return "stt-mlx-audio"
    return None


def _audio_entry(model_id, fmt, folder, filenames, source):
    """Build one audio registry entry from an already-classified folder."""
    names = sorted(filenames or [])
    if fmt == "tts-gguf":
        backbone = next(n for n in names
                        if n.lower().endswith(".gguf") and "mmproj" not in n.lower())
        mmproj = next(n for n in names
                      if n.lower().endswith(".gguf") and "mmproj" in n.lower())
        path = os.path.abspath(os.path.join(folder, backbone))
        mmproj_path = os.path.abspath(os.path.join(folder, mmproj))
        try:
            size = os.path.getsize(path)
        except OSError:
            size = None
    else:
        path, mmproj_path = os.path.abspath(folder), None
        size = 0
        for n in names:
            if n.lower().endswith(".safetensors"):
                try:
                    size += os.path.getsize(os.path.join(folder, n))
                except OSError:
                    pass
    return {"id": model_id, "name": model_id, "kind": "audio", "format": fmt,
            "path": path, "mmproj": mmproj_path, "size_bytes": size,
            "source": source}


def scan_audio_local(local_dir):
    """Audio models sitting in the harness's OWN models dir (data/models/). source
    "local" so they are app-owned: deletable from the Audio tab, and re-scanned (a
    folder the user removes drops out of the registry on the next Rescan)."""
    entries = []
    if not os.path.isdir(local_dir):
        return entries
    for name in sorted(os.listdir(local_dir)):
        folder = os.path.join(local_dir, name)
        if not os.path.isdir(folder):
            continue
        try:
            files = os.listdir(folder)
        except OSError:
            continue
        fmt = audio_format_probed(name, files, folder, strict=False)
        if fmt:
            entries.append(_audio_entry(name, fmt, folder, files, "local"))
    return entries


def scan_audio_hf_cache(hub_dir):
    """Audio models already in the machine-wide HuggingFace cache (what
    mlx-audio / mlx-whisper download when invoked with a bare repo id, and where
    another app may have left one). Read-only: source "audio-hf-cache" is NOT in the
    delete allowlist, so the Audio tab shows them as managed elsewhere.

    Layout: <hub>/models--<org>--<name>/snapshots/<sha>/… — only the MLX shape is
    recognised (config.json + safetensors); a cached GGUF is not a usable llama-tts
    pair without its mmproj, so the cache is never mined for tts-gguf."""
    entries = []
    if not os.path.isdir(hub_dir):
        return entries
    for repo_dir_name in sorted(os.listdir(hub_dir)):
        if not repo_dir_name.startswith("models--"):
            continue
        leaf = repo_dir_name.split("--")[-1]
        if not (_has_token(leaf, AUDIO_STT_TOKENS) or _has_token(leaf, AUDIO_TTS_TOKENS)):
            continue
        snaps_root = os.path.join(hub_dir, repo_dir_name, "snapshots")
        if not os.path.isdir(snaps_root):
            continue
        # Newest snapshot wins — a cache can hold several revisions of one repo.
        snaps = []
        for sha in os.listdir(snaps_root):
            d = os.path.join(snaps_root, sha)
            if os.path.isdir(d):
                try:
                    snaps.append((os.path.getmtime(d), d))
                except OSError:
                    pass
        if not snaps:
            continue
        folder = max(snaps)[1]
        try:
            files = os.listdir(folder)
        except OSError:
            continue
        fmt = audio_format_probed(leaf, files, folder, strict=True)
        if fmt in ("tts-mlx", "stt-mlx", "stt-mlx-audio"):
            entries.append(_audio_entry(leaf, fmt, folder, files, "audio-hf-cache"))
    return entries


def scan_lmstudio(lms_dir):
    """Return lmstudio-import registry entries by walking exactly two levels:
    <lms_dir>/<publisher>/<model_dir>/. GGUF files → one entry each; an MLX model
    dir (config.json + >=1 *.safetensors) → one entry."""
    entries = []
    if not os.path.isdir(lms_dir):
        return entries
    for publisher in sorted(os.listdir(lms_dir)):
        pub_dir = os.path.join(lms_dir, publisher)
        if not os.path.isdir(pub_dir):
            continue
        for model_dir_name in sorted(os.listdir(pub_dir)):
            model_dir = os.path.join(pub_dir, model_dir_name)
            if not os.path.isdir(model_dir):
                continue
            files = os.listdir(model_dir)
            # GGUF files directly inside the model dir (skip mmproj files).
            ggufs = [f for f in sorted(files)
                     if f.endswith(".gguf") and "mmproj" not in f
                     and os.path.isfile(os.path.join(model_dir, f))]
            mmproj_files = [f for f in files
                            if f.endswith(".gguf") and "mmproj" in f
                            and os.path.isfile(os.path.join(model_dir, f))]
            mmproj = (os.path.abspath(os.path.join(model_dir, mmproj_files[0]))
                      if len(mmproj_files) == 1 else None)
            for fname in ggufs:
                fpath = os.path.join(model_dir, fname)
                stem = os.path.splitext(fname)[0]
                try:
                    size_bytes = os.path.getsize(fpath)
                except OSError:
                    size_bytes = None
                entries.append({
                    "id": stem,
                    "name": stem,
                    "format": "gguf",
                    "path": os.path.abspath(fpath),
                    "mmproj": mmproj,
                    "size_bytes": size_bytes,
                    "ctx": None,
                    "vision": bool(mmproj),
                    "source": "lmstudio-import",
                })
            # MLX model dir (config.json + safetensors).
            config_path = os.path.join(model_dir, "config.json")
            safetensors = [f for f in files if f.endswith(".safetensors")
                           and os.path.isfile(os.path.join(model_dir, f))]
            if os.path.isfile(config_path) and safetensors:
                total = 0
                for f in safetensors:
                    try:
                        total += os.path.getsize(os.path.join(model_dir, f))
                    except OSError:
                        pass
                vision = False
                try:
                    with open(config_path) as fh:
                        cfg = json.load(fh)
                    vision = "vision_config" in cfg
                except Exception:
                    vision = False
                entries.append({
                    "id": model_dir_name,
                    "name": model_dir_name,
                    "format": "mlx",
                    "path": os.path.abspath(model_dir),
                    "mmproj": None,
                    "size_bytes": total,
                    "ctx": None,
                    "vision": vision,
                    "source": "lmstudio-import",
                })
    return entries


def load_existing(path):
    """Return the existing registry's model list (or [] if none/invalid)."""
    if not os.path.isfile(path):
        return []
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data.get("models", []) or []
    except Exception:
        return []


RESCANNED_SOURCES = ("jan-import", "lmstudio-import", "local", "audio-hf-cache")


# Keys that are USER DECISIONS, not facts about files. A rescan reads the disk, so it
# can never reproduce any of them — without carrying them forward, one RESCAN click
# silently un-pins every voice, un-pins every reference clip, and un-hides everything
# the user hid. (The `voice` half of this was already a shipped fix; `ref_audio` /
# `ref_text` / `hidden` are the same bug in the same place.)
USER_KEYS = ("voice", "ref_audio", "ref_text", "hidden")


def _keep_voice(entry, existing_voice):
    """Carry a user-pinned `voice` across a rescan. PURE (returns a copy when it
    changes anything). A freshly scanned entry never carries one — the voice is a
    choice, not a file — so an existing pin for the same id wins.

    Kept as the narrow single-key helper it always was; _keep_user generalises it.
    """
    v = existing_voice.get(entry.get("id"))
    if v and not str(entry.get("voice") or "").strip():
        entry = dict(entry)
        entry["voice"] = v
    return entry


def _keep_user(entry, existing_user):
    """Carry EVERY user-decision key across a rescan. PURE.

    `existing_user` is {id: {key: value}}. A freshly scanned entry that already
    carries a value keeps its own (nothing does today, but the rule must be
    'the scan wins when the scan knows', not 'the past always wins')."""
    prev = existing_user.get(entry.get("id")) or {}
    add = {k: v for k, v in prev.items()
           if v not in (None, "", False) and entry.get(k) in (None, "", False)}
    return dict(entry, **add) if add else entry


def merge(existing, jan_entries, lmstudio_entries=None, local_entries=None,
          audio_cache_entries=None):
    """Keep every existing entry whose source is not one we re-scan ('jan-import',
    'lmstudio-import', 'local', 'audio-hf-cache'); replace each re-scanned set with
    its fresh scan. Entries with other sources (e.g. 'download') are preserved
    untouched.

    ctx preservation: a fresh 'local' scan has ctx=None (no router preset). When a
    model's files are migrated out of Jan's folder into data/models/, its context
    would otherwise be lost — so for each local entry whose ctx is null we carry
    forward any non-null ctx already recorded for that id in the existing registry
    (e.g. the 35B's 95536 that came from Jan's router.preset.ini).

    On id collision, suffix the lmstudio entry's id with '-lms'. HF-cache audio
    entries instead DROP on collision: the same weights already reached the registry
    by a path we trust more (a download entry, or a copy under data/models/), and a
    suffixed duplicate would offer the user two rows for one model."""
    lmstudio_entries = lmstudio_entries or []
    local_entries = local_entries or []
    audio_cache_entries = audio_cache_entries or []
    # id -> ctx from the current registry (any source), for the preservation rule.
    existing_ctx = {m.get("id"): m.get("ctx")
                    for m in existing if m.get("ctx") not in (None, "")}
    # id -> pinned TTS voice, same preservation rule as ctx and for the same reason:
    # a fresh scan reads FILES, and the chosen voice is a USER decision that lives
    # nowhere on disk. Without this, hitting RESCAN would silently un-pin the voice
    # of every local / hf-cache voice model (download-sourced entries are kept whole,
    # so they were never at risk).
    # id -> {user key: value}. Same rule for the pinned voice, the pinned reference
    # clip + its transcript, and the hidden flag: all four are USER decisions that
    # live nowhere on disk, so a file scan would silently erase them.
    existing_user = {}
    for m in existing:
        keep = {k: m.get(k) for k in USER_KEYS if m.get(k) not in (None, "", False)}
        if keep:
            existing_user[m.get("id")] = keep
    local_filled = []
    for m in local_entries:
        if m.get("ctx") in (None, "") and existing_ctx.get(m.get("id")) not in (None, ""):
            m = dict(m)
            m["ctx"] = existing_ctx[m["id"]]
        m = _keep_user(m, existing_user)
        local_filled.append(m)
    kept = [m for m in existing if m.get("source") not in RESCANNED_SOURCES]
    result = kept + list(jan_entries) + local_filled
    used = {m.get("id") for m in result}
    for m in lmstudio_entries:
        if m.get("id") in used:
            m = dict(m)
            m["id"] = f"{m['id']}-lms"
        used.add(m.get("id"))
        result.append(_keep_user(m, existing_user))
    for m in audio_cache_entries:
        if m.get("id") in used:
            continue
        used.add(m.get("id"))
        result.append(_keep_user(m, existing_user))
    return result


def write(path, models):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump({"models": models}, fh, indent=2)
        fh.write("\n")


def local_entries_for(local_dir):
    """Every source "local" entry for data/models/ — audio folders FIRST, then the
    plain chat folders scan_local finds, minus any id the audio scan already claimed.

    The subtraction is the point: a data/models/<x>/ holding model.gguf + mmproj.gguf
    and named …TTS… matches BOTH scanners, and two entries for one id would put the
    same model in the chat list and the audio list at once."""
    audio = scan_audio_local(local_dir)
    audio_ids = {m["id"] for m in audio}
    return audio + [m for m in scan_local(local_dir) if m.get("id") not in audio_ids]


def main():
    local_entries = local_entries_for(LOCAL_MODELS_DIR)
    audio_local = [m for m in local_entries if m.get("kind") == "audio"]
    audio_cache = scan_audio_hf_cache(AUDIO_HF_CACHE_DIR)
    jan_entries = scan_jan(JAN_MODELS_DIR)
    lmstudio_entries = scan_lmstudio(LMSTUDIO_MODELS_DIR)
    existing = load_existing(REGISTRY_PATH)
    merged = merge(existing, jan_entries, lmstudio_entries, local_entries,
                   audio_cache)
    write(REGISTRY_PATH, merged)
    print(f"seeded {len(merged)} models "
          f"({len(local_entries)} local, {len(jan_entries)} jan-imports, "
          f"{len(lmstudio_entries)} lmstudio-imports, "
          f"{len(audio_local) + len(audio_cache)} audio)")


if __name__ == "__main__":
    main()
