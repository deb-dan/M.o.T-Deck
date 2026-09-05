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
import importlib.util
import argparse
import hashlib
import sys

# ── tool-calling capability (2026-08-21) ─────────────────────────────────────
# `bridge/modeltools.py` owns the verdict for BOTH consumers (this scan and the
# bridge's download registrars), so there is exactly ONE implementation of the
# GGUF header reader and the marker rule — replicating a binary-format parser the
# way the audio CONSTANTS were replicated would rot on the first bump.
# This script is not part of a package, so the module is loaded BY PATH — resolved
# from THIS FILE's location, never the cwd, so it works from the repo and from the
# provisioned snapshot alike. If it cannot be loaded, `tools` simply stays absent:
# an unknown capability is a missing pill, never a broken rescan.
def _load_modeltools():
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         os.pardir, "bridge", "modeltools.py")
        spec = importlib.util.spec_from_file_location("harness_modeltools", p)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:                                          # noqa: BLE001
        return None


MODELTOOLS = _load_modeltools()

# ── S29 / registry hygiene: the ONE definition of "a model that is real" ─────
# Loaded the same way, and for the same reason: this script is not part of a package.
# If it cannot be loaded the prune below turns itself OFF entirely (see prune_absent) —
# a helper that failed to import must never be read as "every model is gone".
def _load_modelreg():
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         os.pardir, "bridge", "core", "modelreg.py")
        spec = importlib.util.spec_from_file_location("harness_modelreg", p)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:                                          # noqa: BLE001
        return None


MODELREG = _load_modelreg()


def _load_model_sources():
    """Load external-manager membership adapters without making scripts a package."""
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_sources.py")
        spec = importlib.util.spec_from_file_location("harness_model_sources", p)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:                                          # noqa: BLE001
        return None


MODEL_SOURCES = _load_model_sources()


def _ready_chat(entry):
    """Discovery accepts only the shared, structurally ready chat-artifact verdict."""
    if MODELREG is None:
        return False
    try:
        return MODELREG.artifact_probe(entry).get("state") == "ready"
    except Exception:
        return False

# ⚠️ The IMPORT SOURCE DIRS. Jan and M.O.T-local entries are filesystem sources.
# LM Studio is different: its public CLI owns membership, while this directory walk
# independently supplies artifact structure and byte metadata for CLI-listed rows.
# The env overrides let suites exercise both signals against a temp tree rather than
# mistaking whatever happens to be on the tester's machine for evidence.
JAN_MODELS_DIR = os.environ.get("HARNESS_JAN_MODELS_DIR") or os.path.expanduser(
    "~/Library/Application Support/Jan/data/llamacpp/models")
JAN_PRESET_INI = os.environ.get("HARNESS_JAN_PRESET_INI") or os.path.expanduser(
    "~/Library/Application Support/Jan/data/llamacpp/router.preset.ini")
LMSTUDIO_MODELS_DIR = os.environ.get(
    "HARNESS_LMSTUDIO_DIR") or os.path.expanduser("~/.lmstudio/models")
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
    try:
        names = sorted(os.listdir(jan_dir))
    except OSError:
        return entries
    for name in names:
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
        entry = {
            "id": name,
            "name": name,
            "format": "gguf",
            "path": os.path.abspath(model_path),
            "mmproj": os.path.abspath(mmproj) if mmproj else None,
            "size_bytes": size_bytes,
            "ctx": ctx_by_id.get(name),
            "vision": bool(mmproj),
            "source": "jan-import",
        }
        if _ready_chat(entry):
            entries.append(entry)
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
    try:
        names = sorted(os.listdir(local_dir))
    except OSError:
        return entries
    for name in names:
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
        entry = {
            "id": name,
            "name": name,
            "format": "gguf",
            "path": os.path.abspath(model_path),
            "mmproj": os.path.abspath(mmproj) if mmproj else None,
            "size_bytes": size_bytes,
            "ctx": None,
            "vision": bool(mmproj),
            "source": "local",
        }
        if _ready_chat(entry):
            entries.append(entry)
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
    try:
        publishers = sorted(os.listdir(lms_dir))
    except OSError:
        return entries
    for publisher in publishers:
        pub_dir = os.path.join(lms_dir, publisher)
        if not os.path.isdir(pub_dir):
            continue
        try:
            model_dirs = sorted(os.listdir(pub_dir))
        except OSError:
            continue
        for model_dir_name in model_dirs:
            model_dir = os.path.join(pub_dir, model_dir_name)
            if not os.path.isdir(model_dir):
                continue
            try:
                files = sorted(os.listdir(model_dir))
            except OSError:
                continue
            # GGUF files directly inside the model dir (skip mmproj files). Numbered
            # split groups are ONE model at part 1; the shared probe owns completeness.
            ggufs = [f for f in sorted(files)
                     if f.endswith(".gguf") and "mmproj" not in f
                     and os.path.isfile(os.path.join(model_dir, f))]
            mmproj_files = [f for f in files
                            if f.endswith(".gguf") and "mmproj" in f
                            and os.path.isfile(os.path.join(model_dir, f))]
            mmproj = (os.path.abspath(os.path.join(model_dir, mmproj_files[0]))
                      if len(mmproj_files) == 1 else None)
            gguf_candidates, seen_groups = [], set()
            for fname in ggufs:
                group = MODELREG.split_gguf_group(fname) if MODELREG else None
                if group:
                    if group in seen_groups:
                        continue
                    seen_groups.add(group)
                    fname, stem = f"{group[0]}-00001-of-{group[1]:05d}.gguf", group[0]
                else:
                    stem = os.path.splitext(fname)[0]
                gguf_candidates.append((fname, stem))
            for fname, stem in gguf_candidates:
                fpath = os.path.join(model_dir, fname)
                entry = {
                    "id": stem, "name": stem, "format": "gguf",
                    "path": os.path.abspath(fpath), "mmproj": mmproj,
                    "size_bytes": None, "ctx": None, "vision": bool(mmproj),
                    "source": "lmstudio-import",
                }
                probe = MODELREG.artifact_probe(entry) if MODELREG else {}
                if probe.get("state") != "ready":
                    continue
                try:
                    entry["size_bytes"] = sum(os.path.getsize(os.path.join(model_dir, n))
                                              for n in probe["evidence"]["manifest"]["files"]
                                              if n.endswith(".gguf") and "mmproj" not in n.lower())
                except OSError:
                    continue
                entries.append(entry)
            # MLX model dir. The shared probe verifies config + direct weight shape.
            config_path = os.path.join(model_dir, "config.json")
            mlx_entry = {
                "id": model_dir_name, "name": model_dir_name, "format": "mlx",
                "path": os.path.abspath(model_dir), "mmproj": None, "size_bytes": 0,
                "ctx": None, "vision": False, "source": "lmstudio-import",
            }
            if _ready_chat(mlx_entry):
                total = 0
                for f in files:
                    if not f.endswith(".safetensors"):
                        continue
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
                mlx_entry["size_bytes"], mlx_entry["vision"] = total, vision
                entries.append(mlx_entry)
    return entries


def _source_identity(entry):
    """Canonical chat-artifact identity shared by scans and manager membership."""
    if not isinstance(entry, dict):
        return None
    path = entry.get("path")
    if not isinstance(path, str) or not path:
        return None
    fmt = "mlx" if str(entry.get("format") or "").lower() == "mlx" else "gguf"
    try:
        return fmt, os.path.realpath(os.path.abspath(path))
    except (OSError, TypeError, ValueError):
        return None


def _lmstudio_member_entry(member, root):
    """A catalog-listed row even when its bytes are missing or malformed."""
    path, fmt = member["path"], member["format"]
    base = os.path.basename(path.rstrip(os.sep))
    model_id = os.path.splitext(base)[0] if fmt == "gguf" else base
    entry = {
        "id": model_id, "name": member.get("display_name") or model_id,
        "format": fmt, "path": path, "mmproj": None,
        "size_bytes": member.get("size_bytes"), "ctx": member.get("ctx"),
        "vision": member.get("vision") is True, "source": "lmstudio-import",
        "source_membership": "listed",
        "source_observation": MODEL_SOURCES.source_observation(member, root),
    }
    if isinstance(member.get("tools"), bool):
        entry["tools"] = member["tools"]
    return entry


def reconcile_lmstudio(existing, scanned, inventory, protect=()):
    """Combine manager membership and filesystem structure without conflating them.

    Only an ``available`` whole-catalog observation may remove a manager row. A listed
    artifact is retained even when its bytes fail the format probe, so the Models pane
    can explain the actual state. A no-longer-listed protected row remains visible only
    to explain/eject the live or pinned model; it is never offerable downstream.
    """
    if (not isinstance(inventory, dict) or inventory.get("state") != "available"
            or MODEL_SOURCES is None):
        return None, [], []
    root = inventory["root"]
    scanned_by = {_source_identity(row): row for row in scanned or []
                  if _source_identity(row) is not None}
    old_rows = [row for row in existing or []
                if isinstance(row, dict) and row.get("source") == "lmstudio-import"]
    old_by = {}
    old_by_member = {}
    for row in old_rows:
        identity = _source_identity(row)
        if identity is not None and identity not in old_by:
            old_by[identity] = row
        observation = row.get("source_observation")
        if (isinstance(observation, dict)
                and observation.get("adapter") == MODEL_SOURCES.ADAPTER
                and isinstance(observation.get("member_key"), str)
                and observation.get("member_key")
                and observation.get("format") in ("gguf", "mlx")):
            member_identity = (observation["format"], observation["member_key"])
            if member_identity not in old_by_member:
                old_by_member[member_identity] = row
    # Stable manager identity outranks path, and is reserved for every member before
    # any legacy path fallback. Without the two passes, a new catalog item reusing a
    # moved item's old path could steal its row before the stable key was considered.
    matched, claimed_old = {}, set()
    members = list(inventory.get("members") or [])
    for index, member in enumerate(members):
        old = old_by_member.get((member["format"], member["member_key"]))
        if old is not None and id(old) not in claimed_old:
            matched[index] = old
            claimed_old.add(id(old))
    for index, member in enumerate(members):
        if index in matched:
            continue
        old = old_by.get((member["format"], member["path"]))
        if old is not None and id(old) not in claimed_old:
            matched[index] = old
            claimed_old.add(id(old))
    listed, current = [], set()
    for index, member in enumerate(members):
        identity = (member["format"], member["path"])
        current.add(identity)
        old, scanned_row = matched.get(index), scanned_by.get(identity)
        row = dict(scanned_row) if scanned_row else _lmstudio_member_entry(member, root)
        if scanned_row and member.get("display_name"):
            row["name"] = member["display_name"]
        if scanned_row and isinstance(member.get("ctx"), int):
            row["ctx"] = member["ctx"]
        if old:
            # Registry ids are public references used by pins and transcripts. A
            # manager display-name change must not silently retarget those references.
            row["id"] = old.get("id") or row["id"]
            row["name"] = old.get("name") or row["name"]
        row["source_membership"] = "listed"
        row["source_observation"] = MODEL_SOURCES.source_observation(member, root)
        listed.append(row)
    protected = {str(item).strip() for item in protect if str(item or "").strip()}
    removed, unlisted = [], []
    for old in old_rows:
        if id(old) in claimed_old or _source_identity(old) in current:
            continue
        mid = str(old.get("id") or "")
        if mid in protected:
            listed.append(dict(old, source_membership="unlisted"))
            unlisted.append(mid)
        elif mid:
            removed.append(mid)
    return listed, sorted(set(removed)), sorted(set(unlisted))


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
# `settings` (per-model sampling overrides, 2026-08-20) is the same class: a rescan
# reads FILES, so without it one RESCAN click silently resets every tuned model back
# to the harness defaults. Carried WHOLESALE (see _keep_user) — the nested dict is
# preserved atomically, which is right while nothing on disk can teach a sampling key.
# `load` (per-model LOAD overrides — ctx / gpu_layers / flash_attn / kv_quant,
# 2026-08-20 v2) is the same class as `settings` and carried the same way.
USER_KEYS = ("voice", "ref_audio", "ref_text", "hidden", "settings", "load")


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


def _audio_artifact_identity(entry):
    """Canonical format + complete launch-artifact identity, or ``None``.

    This is deliberately an identity check only: resolving a symlink lets a rescan
    recognise one artifact under two spellings, but never authorizes a caller to
    alter either target. TTS GGUF requires both its backbone and projector, so rows
    sharing only the backbone are not the same runnable artifact. A missing or
    unresolvable required path is unknown, not equal.
    """
    if not isinstance(entry, dict):
        return None
    fmt = str(entry.get("format") or "").strip().lower()
    if entry.get("kind") != "audio" and not fmt.startswith(("tts-", "stt-")):
        return None
    path = entry.get("path")
    if not isinstance(path, str) or not path:
        return None
    try:
        if not os.path.exists(path):
            return None
        primary = os.path.realpath(os.path.abspath(path))
        projector = ""
        if fmt == "tts-gguf":
            mmproj = entry.get("mmproj")
            if not isinstance(mmproj, str) or not mmproj or not os.path.exists(mmproj):
                return None
            projector = os.path.realpath(os.path.abspath(mmproj))
        return fmt, primary, projector
    except (OSError, TypeError, ValueError):
        return None


def _is_audio_entry(entry):
    """The shared modern + legacy audio spelling, safe if modelreg did not load."""
    if MODELREG is not None:
        try:
            return MODELREG.is_audio(entry)
        except Exception:
            pass
    return (isinstance(entry, dict) and (entry.get("kind") == "audio"
            or str(entry.get("format") or "").strip().lower().startswith(("tts-", "stt-"))))


def _local_collision_id(model_id, used):
    """A deterministic local-row suffix which never overwrites a real artifact."""
    base = f"{model_id}-local"
    candidate, number = base, 2
    while candidate in used:
        candidate = f"{base}-{number}"
        number += 1
    return candidate


def merge(existing, jan_entries, lmstudio_entries=None, local_entries=None,
          audio_cache_entries=None, refreshed_sources=None, authoritative_sources=()):
    """Keep every existing entry whose source is not one we re-scan ('jan-import',
    'lmstudio-import', 'local', 'audio-hf-cache'); replace each re-scanned set with
    its fresh scan. Entries with other sources (e.g. 'download') are preserved
    untouched.

    ctx preservation: a fresh 'local' scan has ctx=None (no router preset). When a
    model's files are migrated out of Jan's folder into data/models/, its context
    would otherwise be lost — so for each local entry whose ctx is null we carry
    forward any non-null ctx already recorded for that id in the existing registry
    (e.g. the 35B's 95536 that came from Jan's router.preset.ini).

    On id collision, suffix the lmstudio entry's id with '-lms'. A fresh local AUDIO
    row first compares its canonical primary-artifact path with kept audio rows: a
    matching path is the same artifact, so the richer kept row wins; a different path
    keeps both via a deterministic '-local' suffix. HF-cache audio entries instead
    DROP on collision: the same weights already reached the registry by a path we
    trust more (a download entry, or a copy under data/models/), and a suffixed
    duplicate would offer the user two rows for one model."""
    lmstudio_entries = lmstudio_entries or []
    local_entries = local_entries or []
    audio_cache_entries = audio_cache_entries or []
    refreshed = (set(RESCANNED_SOURCES) if refreshed_sources is None
                 else set(refreshed_sources))
    authoritative = set(authoritative_sources or ())
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
    existing_user, existing_evidence = {}, {}
    for m in existing:
        keep = {k: m.get(k) for k in USER_KEYS if m.get(k) not in (None, "", False)}
        if keep:
            existing_user[m.get("id")] = keep
        evidence = m.get("artifact_evidence")
        if isinstance(evidence, dict):
            existing_evidence[(str(m.get("source") or ""), str(m.get("id") or ""))] = evidence

    def carry_evidence(m):
        evidence = existing_evidence.get((str(m.get("source") or ""), str(m.get("id") or "")))
        if not isinstance(evidence, dict) or not isinstance(evidence.get("real_path"), str):
            return m
        path = m.get("path")
        try:
            same = isinstance(path, str) and os.path.realpath(path) == evidence["real_path"]
        except (OSError, TypeError, ValueError):
            same = False
        return dict(m, artifact_evidence=evidence) if same else m
    local_filled = []
    for m in local_entries:
        if m.get("ctx") in (None, "") and existing_ctx.get(m.get("id")) not in (None, ""):
            m = dict(m)
            m["ctx"] = existing_ctx[m["id"]]
        m = carry_evidence(_keep_user(m, existing_user))
        local_filled.append(m)
    fresh_keys = {(str(m.get("source") or ""), str(m.get("id") or ""))
                  for m in list(jan_entries) + list(local_entries)
                  + list(lmstudio_entries) + list(audio_cache_entries)
                  if isinstance(m, dict)}
    # A re-scan learns nothing from an unreadable import root. Preserve an unknown or
    # incomplete existing row until a fresh same-source/id row replaces it; `prune_absent`
    # keeps the incomplete row visible while a definite missing row still deletes.
    def preserve_unavailable(m):
        if not isinstance(m, dict) or m.get("source") not in RESCANNED_SOURCES or MODELREG is None:
            return isinstance(m, dict) and m.get("source") not in RESCANNED_SOURCES
        if m.get("source") not in refreshed:
            return True
        # A manager adapter that successfully returned one validated whole catalog
        # owns membership for its source. Protected unlisted rows were put into the
        # fresh plan explicitly; no stale row may re-enter via a filesystem fallback.
        if m.get("source") in authoritative:
            return False
        # U75 owns chat-model artifacts only. Audio's engine validators and wholesale
        # cache/local scan semantics remain authoritative, including a cache row whose
        # directory is no longer there; never preserve it through the chat probe.
        fmt = str(m.get("format") or "").lower()
        if m.get("kind") == "audio" or fmt.startswith(("tts-", "stt-")):
            return False
        if (str(m.get("source") or ""), str(m.get("id") or "")) in fresh_keys:
            return False
        try:
            probe = MODELREG.artifact_probe(m)
            state = probe.get("state")
            return state in ("unknown", "incomplete", "missing")
        except Exception:
            return True
    kept = [m for m in existing if preserve_unavailable(m)]
    kept_audio_paths = {_audio_artifact_identity(m) for m in kept}
    kept_audio_paths.discard(None)
    result = kept + [carry_evidence(_keep_user(m, existing_user)) for m in jan_entries]
    used = {m.get("id") for m in result}
    for m in local_filled:
        if _is_audio_entry(m):
            artifact = _audio_artifact_identity(m)
            if artifact is not None and artifact in kept_audio_paths:
                continue
            if m.get("id") in used:
                m = dict(m)
                m["id"] = _local_collision_id(m["id"], used)
        used.add(m.get("id"))
        result.append(m)
    for m in lmstudio_entries:
        if m.get("id") in used:
            m = dict(m)
            base, number = f"{m['id']}-lms", 2
            m["id"] = base
            while m["id"] in used:
                m["id"] = f"{base}-{number}"
                number += 1
        used.add(m.get("id"))
        result.append(carry_evidence(_keep_user(m, existing_user)))
    for m in audio_cache_entries:
        if m.get("id") in used:
            continue
        used.add(m.get("id"))
        result.append(carry_evidence(_keep_user(m, existing_user)))
    return result


# ══ RESCAN IS THE PRUNE (Debi, 2026-08-29: "isn't there a way to make the apps scan?")
#
# THE INCIDENT: manager-level removal can leave model bytes in LM Studio's storage.
# U82 therefore reconciles `lmstudio-import` membership through the validated CLI
# adapter above; a filesystem walk alone has no authority to re-add or remove those
# rows. `prune_absent` handles the separate physical-file class, including source
# `download` rows whose metadata cannot be reconstructed from a directory scan.
#
# So the rescan gets a second, source-blind pass — one stat per row, three outcomes:
#
#   file THERE          → clear any absent flag (a re-plugged volume heals silently)
#   file PROVABLY GONE  → REMOVE the row, and PRINT the line, unless it is protected
#                         (the pin / the live model), which is FLAGGED `absent: true`
#                         and kept so the runner card's honest state keeps its subject
#   we could not TELL   → do nothing at all, say nothing at all
#
# ⚠️ WHY FLAG AND NOT DELETE, EVER, OUTSIDE THIS FUNCTION: the file may be on a volume
# that is merely unplugged. A row carries identity a scan cannot rebuild — the pinned
# TTS voice, the per-model sampling overrides, the known ctx. Removal happens ONLY here,
# ONLY under an explicit human RESCAN, and it always says which rows it took.
# ⚠️ AND IT NEVER TOUCHES MODEL FILES. This function edits data/models.json and nothing
# else; deleting weights is /api/models/delete's job and a different consent.
def prune_absent(models, protect=(), present_of=None, confirm_missing=(), details=False):
    """PURE-ish (one stat per row via `present_of`). Returns (kept, removed, flagged).

    `protect` — ids that must be FLAGGED rather than removed (pin + live model).
    `present_of` — row → True|False|None; defaults to modelreg.entry_present. When the
    helper could not be loaded at all this whole pass is skipped by main(), because
    "we cannot check" must never become "everything is gone".
    """
    use_probe = present_of is None
    if present_of is None:
        if MODELREG is None:
            return list(models or []), [], []
        present_of = MODELREG.entry_present
    absent_key = MODELREG.ABSENT_KEY if MODELREG else "absent"
    keep_ids = {str(x).strip() for x in (protect or []) if str(x or "").strip()}
    kept, removed, flagged, ambiguous = [], [], [], []
    confirmed = {str(x).strip() for x in (confirm_missing or ()) if str(x).strip()}
    for m in (models or []):
        if not isinstance(m, dict):
            continue
        # Audio has its own scanner/engine contract.  It never carries chat artifact
        # evidence, so it must never enter the U76 missing-source consent planner.
        # Keep the pre-U76 wholesale-rescan behavior: a preserved/download audio row
        # is not probed, previewed, flagged, or removed by this chat-artifact pass.
        if MODELREG is not None and MODELREG.is_audio(m):
            kept.append(m)
            continue
        if use_probe:
            try:
                probe = MODELREG.artifact_probe(m)
            except Exception:
                probe = {"state": "unknown"}
            state = probe.get("state")
            if state == "incomplete":
                kept.append(m)  # observable broken artifact belongs in Models, not a silent prune
                continue
            if state == "unknown":
                kept.append(m)
                continue
            if state == "missing":
                if m.get("source_membership") == "listed":
                    # The manager still owns this row; filesystem absence is a
                    # readiness problem, not evidence that the user removed it from
                    # their library. Keep it visible and non-offerable.
                    kept.append(m)
                    continue
                availability = MODELREG.source_availability(m, probe).get("state")
                if availability == "unavailable":
                    kept.append(m)
                    continue
                if availability == "unknown":
                    mid = str(m.get("id") or "")
                    ambiguous.append(mid)
                    if mid not in confirmed:
                        kept.append(m)
                        continue
                # available is a confirmed deletion; confirmed legacy-unknown is an
                # explicit human decision after this exact row was re-probed.
                present = False
            else:
                present = state == "ready"
        else:
            try:
                present = present_of(m)
            except Exception:                                  # noqa: BLE001
                present = None
        if present is True:
            if m.get(absent_key) is not None:
                m = {k: v for k, v in m.items() if k != absent_key}
            kept.append(m)
            continue
        if present is None:
            kept.append(m)                # unknown is not a claim, in either direction
            continue
        mid = str(m.get("id") or "")
        if mid in keep_ids:
            kept.append(dict(m, **{absent_key: True}))
            flagged.append(mid)
        else:
            removed.append(mid)
    if details:
        return kept, removed, flagged, sorted(set(x for x in ambiguous if x))
    return kept, removed, flagged


def apply_artifact_evidence(models):
    """Explicit-Rescan-only observation writer; audio and non-ready rows are unchanged."""
    out = []
    for m in models or []:
        if not isinstance(m, dict) or MODELREG is None or MODELREG.is_audio(m):
            out.append(m)
            continue
        try:
            evidence = MODELREG.artifact_evidence(m)
        except Exception:
            evidence = None
        out.append(dict(m, artifact_evidence=evidence) if evidence else m)
    return out


def missing_confirmation_token(models, ambiguous_ids):
    """Bind consent to the registry revision and exact observed missing rows.

    IDs remain display text only. The token changes when a path, format, source,
    evidence record, symlink target, or any concurrently-written registry field
    changes between preview and confirmation.
    """
    ids = sorted({str(item) for item in ambiguous_ids if str(item)})
    observed = []
    for row in models or []:
        if not isinstance(row, dict) or str(row.get("id") or "") not in ids:
            continue
        raw_path = row.get("path") if isinstance(row.get("path"), str) else ""
        observed.append({"row": row, "real_path": os.path.realpath(raw_path) if raw_path else ""})
    payload = {"v": 1, "ambiguous_ids": ids, "observed": observed,
               "registry": list(models or [])}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write(path, models):
    if MODELREG is None:
        raise RuntimeError("model registry helper is unavailable")
    MODELREG.write_registry(path, {"models": models})


def local_entries_for(local_dir):
    """Every source "local" entry for data/models/ — audio folders FIRST, then the
    plain chat folders scan_local finds, minus any id the audio scan already claimed.

    The subtraction is the point: a data/models/<x>/ holding model.gguf + mmproj.gguf
    and named …TTS… matches BOTH scanners, and two entries for one id would put the
    same model in the chat list and the audio list at once."""
    audio = scan_audio_local(local_dir)
    audio_ids = {m["id"] for m in audio}
    return audio + [m for m in scan_local(local_dir) if m.get("id") not in audio_ids]


def annotate_tools(models):
    """Fill `tools` (True/False/None) on every chat entry that lacks a verdict.

    Runs ONCE over the MERGED list rather than inside each scanner, so it also
    reaches the entries merge() preserves untouched — source "download" models,
    which is most of what a real registry contains. A no-op when bridge/modeltools
    could not be loaded."""
    if MODELTOOLS is None:
        return models
    try:
        return MODELTOOLS.annotate_tools(models)
    except Exception:                                          # noqa: BLE001
        return models


def main(argv=None):
    if argv is None:
        argv = []
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--json", action="store_true", dest="json_mode")
    parser.add_argument("--confirm-missing-token", default="")
    args = parser.parse_args(argv)
    token = str(args.confirm_missing_token or "").strip().lower()
    if token and (len(token) != 64 or any(ch not in "0123456789abcdef" for ch in token)):
        if args.json_mode:
            print(json.dumps({"ok": False, "error": "invalid missing-entry confirmation token"}))
            return 1
        raise SystemExit("ERROR: invalid missing-entry confirmation token")
    if MODELREG is None:
        if args.json_mode:
            print(json.dumps({"ok": False, "error": "model integrity helper unavailable"}))
            return 1
        raise SystemExit("ERROR: model integrity helper unavailable; registry left unchanged")
    local_entries = local_entries_for(LOCAL_MODELS_DIR)
    audio_local = [m for m in local_entries if m.get("kind") == "audio"]
    audio_cache = scan_audio_hf_cache(AUDIO_HF_CACHE_DIR)
    jan_entries = scan_jan(JAN_MODELS_DIR)
    refresh_lmstudio = args.json_mode or not os.path.isfile(REGISTRY_PATH)
    lmstudio_inventory = None
    if refresh_lmstudio and MODEL_SOURCES is not None:
        lmstudio_inventory = MODEL_SOURCES.lmstudio_inventory(LMSTUDIO_MODELS_DIR)
    elif refresh_lmstudio:
        lmstudio_inventory = {"state": "unavailable", "members": [],
                              "detail": "model-source adapter could not be loaded"}
    source_warnings, manager_removed, unlisted = [], [], []
    # All registry writers share this lock: the evidence/confirmation plan must be
    # computed from the same bytes it atomically replaces.
    with MODELREG.registry_lock(REGISTRY_PATH):
        existing = load_existing(REGISTRY_PATH)
        protect = MODELREG.protected_ids(".")
        refreshed = {"jan-import", "local", "audio-hf-cache"}
        authoritative = set()
        lmstudio_entries = []
        if refresh_lmstudio and lmstudio_inventory.get("state") == "available":
            lmstudio_entries, manager_removed, unlisted = reconcile_lmstudio(
                existing, scan_lmstudio(LMSTUDIO_MODELS_DIR), lmstudio_inventory,
                protect=protect)
            refreshed.add("lmstudio-import")
            authoritative.add("lmstudio-import")
        elif refresh_lmstudio:
            source_warnings.append(lmstudio_inventory.get("detail")
                                   or "LM Studio membership could not be refreshed")
        merged = merge(existing, jan_entries, lmstudio_entries, local_entries,
                       audio_cache, refreshed_sources=refreshed,
                       authoritative_sources=authoritative)
        merged = annotate_tools(merged)
        explicit = args.json_mode or bool(token)
        if explicit:
            merged = apply_artifact_evidence(merged)
        # RESCAN IS THE PRUNE (see prune_absent). Protected = harness.yaml's pin plus
        # whatever the caller knows is LIVE (the bridge's rescan route exports
        # HARNESS_PROTECT_MODELS); those are flagged, never removed, so the runner card's
        # honest "pinned model missing" keeps the row it is talking about.
        removed, flagged, ambiguous = [], [], []
        planned, removed, flagged, ambiguous = prune_absent(
            merged, protect=protect, details=True)
        expected_token = missing_confirmation_token(merged, ambiguous) if ambiguous else ""
        # Consent is a digest of the whole current registry revision plus the exact
        # missing row/path/format/source/evidence observations. An id match alone has
        # no authority: U84 proved a different same-id row could otherwise be removed.
        if token and token != expected_token:
            if args.json_mode:
                print(json.dumps({"ok": False, "error": "missing-entry confirmation changed",
                                  "ambiguous_missing": ambiguous}))
                return 1
            raise SystemExit("ERROR: missing-entry confirmation changed; registry left unchanged")
        if ambiguous and not token:
            if args.json_mode:
                print(json.dumps({"ok": False, "count": len(planned), "pruned": removed,
                                  "flagged": flagged, "requires_confirmation": True,
                                  "ambiguous_missing": ambiguous,
                                  "confirmation_token": expected_token,
                                  "log": "missing entries could be an unavailable model library"}))
                return 3
            # Non-explicit startup seeding must never turn legacy uncertainty into authority.
            return 0
        if token:
            merged, removed, flagged, ambiguous = prune_absent(
                merged, protect=protect, confirm_missing=ambiguous, details=True)
        else:
            merged = planned
        write(REGISTRY_PATH, merged)
    if args.json_mode:
        print(json.dumps({"ok": True, "count": len(merged), "pruned": removed,
                          "flagged": flagged, "requires_confirmation": False,
                          "ambiguous_missing": [], "manager_removed": manager_removed,
                          "unlisted": unlisted, "source_warnings": source_warnings,
                          "partial": bool(source_warnings)}))
        return 0
    print(f"seeded {len(merged)} models "
          f"({len(local_entries)} local, {len(jan_entries)} jan-imports, "
          f"{len(lmstudio_entries)} lmstudio-imports, "
          f"{len(audio_local) + len(audio_cache)} audio)")
    # The printed line is the point: a rescan that silently shrinks a list is
    # indistinguishable from a rescan that broke. One line per row it took.
    for mid in removed:
        print(f"removed: {mid} — its file is no longer on disk")
    for mid in flagged:
        print(f"flagged absent (kept — it is the pinned/live model): {mid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
