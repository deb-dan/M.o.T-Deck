"""Harness-native voice capability — Phase B engine dispatch (FABLE-VOICE-CAPABILITY-SPEC).

One-shot subprocesses, never a resident server: `llama-tts` from OUR pinned llama.cpp
build, and `python -m mlx_audio.tts.generate` from OUR mlx venv. No new port, no
lifecycle card, no persistent RAM claim — a voice model costs DISK plus transient RAM
for the duration of one render.

Registry shape (entries live in the EXISTING data/models.json, `kind: "audio"`):

    tts-gguf : {id, name, kind:"audio", format:"tts-gguf", path:<backbone .gguf>,
                mmproj:<mmproj .gguf>, size_bytes, [lang], [max_frames]}
    tts-mlx  : {id, name, kind:"audio", format:"tts-mlx",  path:<model dir or HF repo>,
                size_bytes, [voice]}
    stt-mlx  : {id, name, kind:"audio", format:"stt-mlx",  path:<model dir or HF repo>}

Three invariants this module exists to hold:

  1. **Audio never leaks into the chat model lists.** `split_audio()` is the single
     seam; the runner switch / aux / chat pickers all feed off the chat half.
  2. **Both engines EXIT 0 ON FAILURE.** mlx-audio catches every exception, prints a
     traceback and returns normally; llama-tts is upstream-labelled a playground.
     Success is therefore defined ONLY as `render_ok()` — the output wav exists and
     is non-empty. The return code is never trusted. Unit-tested.
  3. **Explicit paths, never PATH lookup.** Anything the bridge spawns inherits a
     Finder-minimal PATH (standing project rule, learned from the voicebox `uv` miss),
     so the llama-tts binary and the mlx interpreter are resolved by absolute path and
     a missing one is reported by name.

Verified argv surfaces (Debi's Mac, 2026-08-07):

    llama-tts -m backbone.gguf -mm mmproj.gguf -p "text" -o out.wav
              [--tts-lang <iso639-1>] [--tts-speaker-file f] [-n N]
              # b10295: the rewritten mtmd tool. NO --voice, NO -mv/--vocoder-model.
    python -m mlx_audio.tts.generate --model <repo|dir> --text "…" --join_audio
              --output_path <dir> --file_prefix out [--voice V] [--lang_code L]
              # WITHOUT --join_audio it writes out_000.wav segments, not out.wav.
    mlx_whisper <audio> --model <repo|dir> -f json -o <dir> --verbose False
              # Phase D. The CLI WRITES <dir>/<audio-stem>.json — it does not print
              # the transcript to stdout (spec amendment §6).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Hard caps (spec §Phase B). Text beyond the cap is a 413, not a truncation — a
# silently shortened clip is worse than a refusal.
VOICE_MAX_CHARS = 2000
VOICE_TIMEOUT_S = 120
VOICE_LOG_TAIL = 1500          # chars of stdout+stderr carried into an error

# Phase D (STT). 25MB ≈ 20 minutes of opus-in-webm from MediaRecorder, and far more
# than the panel's 60s auto-stop can produce — the cap exists to bound a hand-crafted
# POST, not to constrain the mic button.
VOICE_MAX_AUDIO_BYTES = 25 * 1024 * 1024
# Containers the panel's MediaRecorder can emit plus the ones a curl user will try.
# Anything not wav goes through ffmpeg; an unknown suffix is refused at the door
# rather than handed to ffmpeg to guess at.
STT_SUFFIXES = ("wav", "webm", "mp4", "m4a", "mp3", "ogg", "flac")
STT_SAMPLE_RATE = 16000        # what whisper wants; resampling here saves it the work

TTS_FORMATS = ("tts-gguf", "tts-mlx")
STT_FORMATS = ("stt-mlx",)
AUDIO_FORMATS = TTS_FORMATS + STT_FORMATS

# ── named voices ────────────────────────────────────────────────────────────────
# WHY this exists: mlx-audio picks a RANDOM named voice per render when --voice is
# absent (Debi-observed on Qwen3-TTS-mlx), so "the same model" sounds like a
# different person every reply. tts_argv already emits `--voice <v>` when the
# registry entry carries one — this table is just the list of names worth offering.
#
# It is deliberately SMALL and honest: a family token → its documented voice ids.
# An unknown family gets an empty list and the UI falls back to a free-text box
# (a voice we have never heard of is still perfectly valid to type), and EVERY
# tts-gguf gets an empty list because llama-tts at b10295 has no --voice flag at
# all — its voice is baked into the model.
#
# ⚠️ RECON-LEVEL, not machine-verified: the Kokoro ids come from hexgrad's
# published VOICES.md (af_/am_ = American female/male, bf_/bm_ = British), the
# Qwen3-TTS pair from the model card. A name the engine does not know is not
# catastrophic — mlx-audio falls back — but it is worth re-checking at a pin bump.
KNOWN_VOICES = {
    # The REAL Qwen3-TTS voices, from the CustomVoice checkpoint's own config.json
    # talker_config.spk_id (research-verified 2026-08-08). "Chelsie"/"Ethan" were
    # README fiction — they exist in no checkpoint. NOTE: these apply to the
    # *CustomVoice* variant; the *Base* variant declares spk_id:{} (cloning-only)
    # and silently ignores every name. Config-derived chips (queued) fix this
    # properly; until then the offer is at least real.
    "qwen3-tts": ["serena", "vivian", "ryan", "aiden", "dylan",
                  "eric", "uncle_fu", "sohee", "ono_anna"],
    "kokoro": ["af_heart", "af_bella", "af_nicole", "af_sarah",
               "am_adam", "am_michael", "bf_emma", "bm_george"],
}

# A voice id is a short token (`af_heart`, `Chelsie`), never prose. The cap exists
# so a stray paste cannot end up on an argv.
VOICE_NAME_MAX = 64


def voices_for(entry: "dict | None") -> list:
    """The named voices worth OFFERING for this registry entry, from the STATIC
    table. PURE. ⚠️ DEMOTED (2026-08-13): this is the OFFER OF LAST RESORT — the
    authoritative source is the model's own config.json (voices_for_entry). It
    survives only for a model whose files we cannot read (an HF repo id that was
    never downloaded, a moved directory).

    Empty list ⇒ the UI must not show chips: either the engine has no voice
    parameter (every tts-gguf) or we simply do not know this family's names (then
    the UI offers free text instead — never a closed list we cannot honour).
    """
    if not is_tts_entry(entry):
        return []
    if entry_format(entry) != "tts-mlx":
        return []                      # llama-tts: no --voice, no choice to make
    hay = " ".join(str((entry or {}).get(k) or "")
                   for k in ("id", "repo", "path", "name")).lower()
    for token, names in KNOWN_VOICES.items():
        if token in hay:
            return list(names)
    return []


# ── config-derived voices (the AUTHORITATIVE source) ────────────────────────────
# WHY this exists: the static table above is a guess about a FAMILY, and a family is
# not a checkpoint. `mlx-community/Qwen3-TTS-…-Base-8bit` and `…-CustomVoice-8bit`
# share every family token and have OPPOSITE voice behaviour — CustomVoice declares
# nine named speakers, Base declares none and silently ignores any name you pass
# (Debi's A/B, then source-confirmed). Only the model's own config.json can tell
# them apart, so that is what we read.
#
# The discriminator is `tts_model_type` in config.json:
#     custom_voice → named voices, listed in talker_config.spk_id (name → id)
#     base         → cloning-only (spk_id:{}); a name does nothing
#     voice_design → described by instruction text, not by name
# and `talker_config.spk_is_dialect` (name → bool) marks the regional speakers
# (dylan = Beijing, eric = Sichuan) so the UI can say so rather than leaving the
# user to discover it by listening.
#
# Kokoro is a SECOND mechanism with the same UI: its 54 voices are not in config at
# all, they are the stems of `voices/*.pt` files in the model dir.
CONFIG_FILENAME = "config.json"
VOICES_SUBDIR = "voices"
VOICE_PT_SUFFIX = ".pt"

# The honest thing to say about a checkpoint that declares no names. It is NOT an
# error state — cloning models are a legitimate design; they just cannot be driven
# by a name, so offering a text box would be inviting a no-op.
NO_VOICES_NOTE = ("this model has no named voices — voice control needs "
                  "reference audio")
# HF-verified 2026-08-13 (api/models/… returned 200, pipeline_tag text-to-speech,
# library mlx-audio): the CustomVoice sibling really exists under this exact id, so
# naming it in the note is a usable instruction rather than a guess.
QWEN_CUSTOMVOICE_REPO = "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit"
QWEN_SIBLING_HINT = (f" — for named voices use the CustomVoice variant "
                     f"({QWEN_CUSTOMVOICE_REPO})")

# The model types that constitute an AUTHORITATIVE "there are no names here"
# verdict. Anything else (an absent/unknown tts_model_type) leaves the question
# open, and an open question falls through to the voices/ dir and then the table
# rather than telling the user something we do not know.
NO_NAME_MODEL_TYPES = ("base", "voice_design")


def voices_from_config(cfg: object) -> dict:
    """Named voices declared by a model's own config.json. PURE.

    Returns {"voices": [names…], "dialects": {name: bool}, "model_type": str|None}.
    Defensive against every surprise shape: a config is third-party data and a
    TypeError here would take out the whole Audio tab.
    """
    out = {"voices": [], "dialects": {}, "model_type": None}
    if not isinstance(cfg, dict):
        return out
    mt = cfg.get("tts_model_type")
    if isinstance(mt, str) and mt.strip():
        out["model_type"] = mt.strip().lower()
    talker = cfg.get("talker_config")
    if not isinstance(talker, dict):
        return out
    spk = talker.get("spk_id")
    names = []
    if isinstance(spk, dict):
        # Insertion order is the checkpoint's own order — nicer than alphabetical
        # (serena/vivian/ryan/… reads like the model card).
        names = [k.strip() for k in spk.keys()
                 if isinstance(k, str) and k.strip()]
    elif isinstance(spk, (list, tuple)):
        names = [v.strip() for v in spk if isinstance(v, str) and v.strip()]
    out["voices"] = names
    dial = talker.get("spk_is_dialect")
    if isinstance(dial, dict) and names:
        known = set(names)
        out["dialects"] = {k.strip(): bool(v) for k, v in dial.items()
                           if isinstance(k, str) and k.strip() in known}
    return out


def voices_from_dir(model_dir: object) -> list:
    """Kokoro's mechanism: the stems of <model_dir>/voices/*.pt. Sorted, guarded."""
    try:
        vdir = os.path.join(str(model_dir or ""), VOICES_SUBDIR)
        if not os.path.isdir(vdir):
            return []
        return sorted(n[:-len(VOICE_PT_SUFFIX)] for n in os.listdir(vdir)
                      if n.lower().endswith(VOICE_PT_SUFFIX) and len(n) > 3)
    except OSError:
        return []


def read_model_config(model_dir: object) -> "dict | None":
    """<model_dir>/config.json, or None when absent/unreadable/not an object."""
    try:
        p = os.path.join(str(model_dir or ""), CONFIG_FILENAME)
        if not os.path.isfile(p):
            return None
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else None
    except (OSError, ValueError):
        return None


def _config_stamp(model_dir: str) -> tuple:
    """(config mtime, voices-dir mtime) — the cache key's freshness half. A model
    dir does not change under us in practice, but a re-download does, and getting a
    stale voice list after replacing a checkpoint would be a genuinely confusing bug."""
    def _m(p):
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0.0
    return (_m(os.path.join(model_dir, CONFIG_FILENAME)),
            _m(os.path.join(model_dir, VOICES_SUBDIR)))


# The panel re-reads /api/models on a timer, and audio_entry_view runs for EVERY
# audio entry on every one of those calls — without this, a two-second poll would
# stat and json-parse every voice model forever.
_VOICES_CACHE = {}                    # path -> (stamp, result dict)
_VOICES_CACHE_LOCK = threading.Lock()


def clear_voices_cache() -> None:
    with _VOICES_CACHE_LOCK:
        _VOICES_CACHE.clear()


def voices_for_entry(entry: "dict | None") -> dict:
    """The voices to OFFER for one registry entry, resolved from the model itself.

    Returns {"voices", "dialects", "model_type", "note", "source"} where source is
    one of "config" | "dir" | "table" | "none" — the panel does not branch on it,
    but it makes a wrong answer diagnosable from the API response alone.

    Resolution order, strongest evidence first:
      1. config.json talker_config.spk_id      → the checkpoint's own declaration
      2. voices/*.pt stems                     → Kokoro's declaration
      3. config says base/voice_design (or declares an EMPTY spk_id) → no voices,
         plus an honest note. This is the case that fixes Debi's Base model.
      4. the static KNOWN_VOICES table         → last resort, for a model whose
         files we cannot read at all
    """
    blank = {"voices": [], "dialects": {}, "model_type": None,
             "note": "", "source": "none", "cloning": False}
    if not is_tts_entry(entry) or entry_format(entry) != "tts-mlx":
        return blank
    path = str((entry or {}).get("path") or "").strip()
    if not path or not os.path.isdir(path):
        # An HF repo id, or a directory that has moved. Nothing to read → the table
        # is all we have, and an offer we cannot verify beats no offer at all.
        return dict(blank, voices=voices_for(entry),
                    source=("table" if voices_for(entry) else "none"))

    stamp = _config_stamp(path)
    with _VOICES_CACHE_LOCK:
        hit = _VOICES_CACHE.get(path)
        if hit and hit[0] == stamp:
            return dict(hit[1])

    cfg = read_model_config(path)
    cv = voices_from_config(cfg)
    pt = [] if cv["voices"] else voices_from_dir(path)
    # CLONING is decided from the SAME config read — the panel must be able to branch
    # on it without a second probe (audio_entry_view runs on every /api/models poll).
    cloning = is_cloning_model(cfg) or _config_says_no_names(cfg, cv)
    if cv["voices"]:
        out = dict(blank, voices=cv["voices"], dialects=cv["dialects"],
                   model_type=cv["model_type"], source="config", cloning=cloning)
    else:
        if pt:
            out = dict(blank, voices=pt, model_type=cv["model_type"], source="dir",
                       cloning=cloning)
        elif _config_says_no_names(cfg, cv):
            out = dict(blank, model_type=cv["model_type"], source="config",
                       cloning=cloning,
                       note=NO_VOICES_NOTE + (QWEN_SIBLING_HINT
                                              if _is_qwen3_tts(entry) else ""))
        else:
            tbl = voices_for(entry)
            out = dict(blank, voices=tbl, model_type=cv["model_type"],
                       cloning=cloning,
                       source=("table" if tbl else "none"))
    with _VOICES_CACHE_LOCK:
        _VOICES_CACHE[path] = (stamp, out)
    return dict(out)


def _config_says_no_names(cfg: object, cv: dict) -> bool:
    """True only when the config gives a POSITIVE verdict of 'no named voices'.

    An absent or unrecognised tts_model_type is not a verdict — silence must not be
    read as "there are none", or every non-Qwen model would grow a note claiming
    something we never checked.
    """
    if not isinstance(cfg, dict):
        return False
    if (cv.get("model_type") or "") in NO_NAME_MODEL_TYPES:
        return True
    talker = cfg.get("talker_config")
    # A declared-but-empty spk_id is the Base checkpoint's actual fingerprint.
    return isinstance(talker, dict) and isinstance(talker.get("spk_id"), dict) \
        and not talker["spk_id"]


# ── cloning models (zero-shot: voice identity comes from AUDIO, never a name) ───
# WHY: OmniVoice renders a DIFFERENT random voice on every ▶ speak (Debi-observed),
# and no amount of --voice fixes it — `Model.generate()` in mlx_audio/tts/models/
# omnivoice/omnivoice.py takes `ref_audio` / `ref_text` / `ref_audio_max_duration_s`
# and has NO speaker table at all (source-read 2026-08-13). For this family the only
# way to hear the same person twice is to hand it the same clip twice.
#
# The discriminator is the config's own model_type. mlx-audio ROUTES on it
# (utils.MODEL_REMAPPING["omnivoice"] = "omnivoice"), so a checkpoint that loads as
# OmniVoice necessarily declares it — this is not a name guess like the old family
# table was.
CLONING_MODEL_TYPES = ("base", "voice_design", "omnivoice")


def is_cloning_model(cfg: object) -> bool:
    """True when the model's own config says voice identity comes from reference
    audio rather than from a name. PURE, and defensive: a config is third-party data.

    ⚠️ PENDING FABLE QA: both `tts_model_type` (Qwen3-TTS's key) and `model_type`
    (mlx-audio's routing key, where "omnivoice" lives) are checked against ONE set.
    A checkpoint whose plain model_type is literally "base" would therefore be called
    cloning — which is the harmless direction: it would be offered a clip picker for
    a parameter it ignores, and a named-voice model is protected anyway because
    declared names win in voices_for_entry.
    """
    if not isinstance(cfg, dict):
        return False
    for key in ("tts_model_type", "model_type"):
        v = cfg.get(key)
        if isinstance(v, str) and v.strip().lower() in CLONING_MODEL_TYPES:
            return True
    return False


def _is_qwen3_tts(entry: "dict | None") -> bool:
    hay = " ".join(str((entry or {}).get(k) or "")
                   for k in ("id", "repo", "path", "name")).lower()
    return "qwen3-tts" in hay or "qwen3_tts" in hay


def normalize_voice(voice: object) -> str:
    """'' means CLEAR (fall back to the engine's own default). PURE."""
    return str(voice or "").strip()


def validate_voice_choice(entry: "dict | None", voice: object) -> "str | None":
    """None when `voice` may be written onto `entry`, else a user-facing reason.

    The tts-gguf refusal is the interesting one: it is not a validation nicety,
    it is the truth about llama.cpp — there is no flag to carry the answer.
    """
    if not entry:
        return "no such model in the registry"
    if not is_tts_entry(entry):
        return (f"'{entry.get('id')}' is not a TTS model "
                f"(format {entry_format(entry) or 'unknown'})")
    if entry_format(entry) == "tts-gguf":
        return ("llama.cpp models have no voice parameter — "
                "voice is chosen by the model")
    if not isinstance(voice, str):
        return "voice must be a string"
    v = normalize_voice(voice)
    if len(v) > VOICE_NAME_MAX:
        return (f"that voice name is too long ({len(v)} characters) — "
                f"the cap is {VOICE_NAME_MAX}")
    return None


# ── reference audio + the voice library ─────────────────────────────────────────
# A cloning model's voice IS a wav file, so pinning one is exactly the same kind of
# decision as pinning a name: it lives ON the registry entry (`ref_audio`, absolute
# path) next to `voice`, and the two may coexist — the engine ignores whichever it
# has no parameter for.
#
# `data/voices/` is the LIBRARY: a plain directory of clips (recorded in-panel or
# dropped in by hand). It is deliberately not a database — a folder the user can
# open in Finder is the least surprising store for files they can already play.
REF_AUDIO_SUFFIXES = ("wav", "mp3", "flac", "m4a")
REF_AUDIO_MAX_BYTES = 15 * 1024 * 1024      # a reference clip is seconds, not minutes
REF_TEXT_MAX = 500                          # a transcript of ~10s of speech
VOICE_LIB_DIRNAME = "voices"
VOICE_LIB_NAME_MAX = 48
# Kept out of a saved filename: path separators, the traversal dots and anything a
# shell or a URL would treat as structure. An allowlist, not a denylist — the name is
# user input that becomes a filename.
_CLIP_NAME_RE = re.compile(r"[^A-Za-z0-9 ._-]+")


def voices_dir(root: "str | Path | None" = None) -> str:
    return str(Path(root or ROOT) / "data" / VOICE_LIB_DIRNAME)


def normalize_ref_suffix(suffix: object) -> "str | None":
    """'.WAV' / 'audio/mpeg' / 'clip.m4a' → a bare supported suffix, else None. PURE."""
    s = str(suffix or "").strip().lower()
    if not s:
        return None
    s = s.split(";")[0].strip()
    if "/" in s:                       # a mime type
        s = s.split("/")[-1].strip()
    if "." in s:                       # a filename
        s = s.rsplit(".", 1)[-1]
    s = s.lstrip(".")
    s = {"mpeg": "mp3", "mpga": "mp3", "x-m4a": "m4a", "x-wav": "wav",
         "wave": "wav", "vnd.wave": "wav"}.get(s, s)
    return s if s in REF_AUDIO_SUFFIXES else None


def sanitize_clip_name(name: object, fmt: object = "") -> "str | None":
    """A user-supplied clip name → a safe basename with a forced suffix. PURE.

    None when unusable. The suffix comes from `fmt` when given (the recorder knows
    its container better than the typed name does) and only otherwise from the name.
    """
    raw = str(name or "").strip().replace("\\", "/")
    raw = os.path.basename(raw).replace("\x00", "")
    stem, dot, own = raw.rpartition(".")
    if not dot:
        stem, own = raw, ""
    sfx = normalize_ref_suffix(fmt) or normalize_ref_suffix(own)
    if not sfx:
        return None
    stem = _CLIP_NAME_RE.sub("", stem).strip(" .")
    if not stem or len(stem) > VOICE_LIB_NAME_MAX:
        return None
    return f"{stem}.{sfx}"


def unique_clip_path(dir_path: str, name: str) -> str:
    """A path in `dir_path` that does not exist yet — ' (n)' suffixed, never
    clobbering. Same policy as the artifact save (a recording is unrecoverable; an
    overwrite would silently destroy the voice someone already pinned)."""
    stem, _, sfx = str(name).rpartition(".")
    path = os.path.join(dir_path, name)
    n = 1
    while os.path.exists(path) and n < 100:
        path = os.path.join(dir_path, f"{stem} ({n}).{sfx}")
        n += 1
    return path


def library_entries(root: "str | Path | None" = None) -> list:
    """Every usable clip in data/voices, sorted. Never raises."""
    d = voices_dir(root)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    out = []
    for n in names:
        p = os.path.join(d, n)
        try:
            if not os.path.isfile(p):
                continue
            if normalize_ref_suffix(n) is None:
                continue
            out.append({"name": n, "stem": os.path.splitext(n)[0],
                        "path": p, "size": os.path.getsize(p)})
        except OSError:
            continue
    return out


def library_target(name: object, root: "str | Path | None" = None) -> tuple:
    """(abs path, None) when `name` resolves to a file STRICTLY inside data/voices,
    else (None, reason). Same containment discipline as _deletable_target: realpath
    both sides, then require the prefix — a delete endpoint must never be talked out
    of its own directory by a '../' or a symlink.
    """
    raw = str(name or "").strip()
    if not raw:
        return None, "no clip name given"
    d = os.path.realpath(voices_dir(root))
    p = os.path.realpath(os.path.join(d, os.path.basename(raw.replace("\\", "/"))))
    if not p.startswith(d + os.sep):
        return None, "that clip is not in the voice library"
    if not os.path.isfile(p):
        return None, f"no clip named '{os.path.basename(raw)}' in the voice library"
    return p, None


def validate_ref_audio(path: object) -> "str | None":
    """None when `path` is a usable reference clip, else a user-facing reason. The
    checks are the file's, not the model's: exists, a container the engine's loader
    understands, and small enough that a mis-click cannot hand it an album."""
    p = str(path or "").strip()
    if not p:
        return "no clip given"
    if normalize_ref_suffix(p) is None:
        return (f"unsupported clip format — expected one of "
                f"{', '.join(REF_AUDIO_SUFFIXES)}")
    if not os.path.isfile(p):
        return f"no such clip: {os.path.basename(p)}"
    try:
        size = os.path.getsize(p)
    except OSError:
        return f"could not read {os.path.basename(p)}"
    if size <= 0:
        return f"{os.path.basename(p)} is empty"
    if size > REF_AUDIO_MAX_BYTES:
        return (f"that clip is too large ({size // (1024 * 1024)} MB) — the cap is "
                f"{REF_AUDIO_MAX_BYTES // (1024 * 1024)} MB; a reference clip only "
                f"needs a few seconds")
    return None


def validate_ref_choice(entry: "dict | None", path: object,
                        ref_text: object = "") -> "str | None":
    """None when `path` may be written onto `entry` as its reference clip, else a
    reason. '' clears (the key is REMOVED, same semantics as the voice pin).

    The tts-gguf refusal is the truth about llama.cpp, not a nicety: llama-tts takes
    `--tts-speaker-file`, which is a different mechanism with a different file format,
    and pretending otherwise would produce a pin that silently does nothing.
    """
    if not entry:
        return "no such model in the registry"
    if not is_tts_entry(entry):
        return (f"'{entry.get('id')}' is not a TTS model "
                f"(format {entry_format(entry) or 'unknown'})")
    if entry_format(entry) == "tts-gguf":
        return ("llama.cpp models have no ref_audio parameter — llama-tts uses "
                "--tts-speaker-file, a different mechanism the harness does not "
                "wire yet")
    if not isinstance(path, str):
        return "clip path must be a string"
    if not isinstance(ref_text, str):
        return "ref_text must be a string"
    if len(ref_text or "") > REF_TEXT_MAX:
        return (f"that transcript is too long ({len(ref_text)} characters) — the cap "
                f"is {REF_TEXT_MAX}")
    p = path.strip()
    if not p:
        return None                     # clearing is always allowed
    return validate_ref_audio(p)


class VoiceError(RuntimeError):
    """A render failed. `.message` is user-facing; `.log_tail` is the engine's output."""

    def __init__(self, message: str, log_tail: str = ""):
        super().__init__(message)
        self.message = message
        self.log_tail = log_tail or ""


class VoiceBusy(VoiceError):
    """A render is already in flight (one at a time). Maps to HTTP 409."""


# The ONE-SHOT render lock. Scope NARROWED when the persistent worker landed
# (2026-08-13): it now guards ONLY the paths that still spawn a fresh multi-GB
# process per request — llama-tts (tts-gguf) and mlx_whisper (STT). A tts-mlx render
# goes through VoiceWorker instead, which holds its OWN per-worker lock and must NOT
# take this one.
#
# WHY THAT MATTERS BEYOND SPEED: with one shared lock, speaking blocked dictation and
# dictation blocked speaking (a recorded Fable QA watch-item). A resident worker no
# longer loads anything per render, so serialising it against whisper bought safety
# we no longer need to pay for. tts-gguf and STT still share this lock: they DO each
# load a multi-GB model per call, which is exactly the concurrency the lock exists
# to prevent.
_RENDER_LOCK = threading.Lock()


def render_lock() -> threading.Lock:
    """Exposed so tests can reason about the same lock. Guards the ONE-SHOT engines
    (tts-gguf, stt-mlx) only — see the comment above."""
    return _RENDER_LOCK


# ── binary / interpreter resolution (EXPLICIT paths — never `command -v`) ────────
def llama_tts_bin(root: "str | Path | None" = None) -> str:
    """Path to llama-tts. Ships in the SAME macos-arm64 tarball as llama-server, so
    it rides `runner.llamacpp_pin` for free (verified present at b10295)."""
    return str(Path(root or ROOT) / "data" / "llamacpp" / "build" / "bin" / "llama-tts")


def mlx_python(root: "str | Path | None" = None) -> str:
    """Interpreter of the existing MLX venv (mlx-audio is installed alongside
    mlx-lm/mlx-vlm by scripts/install_mlx.sh)."""
    return str(Path(root or ROOT) / "data" / "mlx-venv" / "bin" / "python")


def mlx_whisper_bin(root: "str | Path | None" = None) -> str:
    """The `mlx_whisper` console script installed by mlx-whisper into the MLX venv.
    Preferred over `-m mlx_whisper` because the package exposes NO runnable __main__:
    the CLI lives in mlx_whisper.cli, and the console script is its only stable name."""
    return str(Path(root or ROOT) / "data" / "mlx-venv" / "bin" / "mlx_whisper")


# Where a user's own ffmpeg actually lives on a Mac. The bridge inherits a
# Finder-MINIMAL PATH (standing project rule, learned from the voicebox `uv` miss), so
# `shutil.which` alone would miss a perfectly good /opt/homebrew/bin/ffmpeg. It is
# still tried FIRST — a user who put one somewhere unusual should win — but it is one
# entry in an explicit list, never the whole strategy.
FFMPEG_CANDIDATES = (
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "/usr/bin/ffmpeg",
)


def ffmpeg_candidates(root: "str | Path | None" = None) -> list:
    """The explicit search order, PURE. `data/ffmpeg/bin/ffmpeg` is LAST: it is our
    provisioned copy (scripts/ensure_ffmpeg.sh, from the imageio-ffmpeg wheel) and
    carries no ffprobe, so a real system install should always win."""
    return list(FFMPEG_CANDIDATES) + [
        str(Path(root or ROOT) / "data" / "ffmpeg" / "bin" / "ffmpeg")]


def ffmpeg_bin(root: "str | Path | None" = None) -> "str | None":
    """Resolve ffmpeg the SAME way scripts/ensure_ffmpeg.sh does — the user's own
    first, then the copy that script provisioned into data/ffmpeg/bin.

    Deliberately NEVER installs: this runs inside a request. ensure_ffmpeg.sh is an
    INSTALL-time helper (it pip-installs into a component venv and can take a minute);
    calling it from a POST would turn a 2-second transcription into a surprise
    download. If nothing resolves, the caller raises a VoiceError naming the two
    components whose install provisions one.
    """
    found = shutil.which("ffmpeg")
    if found:
        return found
    for cand in ffmpeg_candidates(root):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


# ── registry partitioning (PURE) ────────────────────────────────────────────────
def is_audio_entry(m: object) -> bool:
    """True for a voice model. Checks `kind == "audio"` AND the audio `format`
    vocabulary: a hand-added entry that forgot `kind` still must not reach a chat
    list. Belt-and-suspenders on purpose — this is the leak that must be impossible."""
    if not isinstance(m, dict):
        return False
    if str(m.get("kind") or "").strip().lower() == "audio":
        return True
    return str(m.get("format") or "").strip().lower() in AUDIO_FORMATS


def split_audio(models: "list | None") -> tuple:
    """(chat_models, audio_models), order preserved. The ONLY partition seam."""
    chat, audio = [], []
    for m in (models or []):
        (audio if is_audio_entry(m) else chat).append(m)
    return chat, audio


def entry_format(entry: "dict | None") -> str:
    return str((entry or {}).get("format") or "").strip().lower()


def is_tts_entry(entry: "dict | None") -> bool:
    return is_audio_entry(entry) and entry_format(entry) in TTS_FORMATS


def is_stt_entry(entry: "dict | None") -> bool:
    return is_audio_entry(entry) and entry_format(entry) in STT_FORMATS


def find_entry(models: "list | None", mid: str) -> "dict | None":
    mid = (mid or "").strip()
    if not mid:
        return None
    return next((m for m in (models or [])
                 if isinstance(m, dict) and m.get("id") == mid), None)


def audio_download_entry(base: dict, voice_format: str) -> dict:
    """Turn a CHAT-shaped registry entry (as built by app._gguf_registry_entry /
    app._mlx_registry_entry when a download completes) into an AUDIO entry.

    Phase A seam: the download manager is format-agnostic, so the Get buttons in the
    Audio tab pass an explicit `voice_format` hint down through /api/dl/start rather
    than sniffing filenames on the way back out. Filename sniffing would have to
    decide "is this gguf a TTS backbone or a chat model?" from a string — a false
    positive there makes a CHAT model vanish from the chat lists, which is the one
    failure mode this whole partition exists to prevent.

    Shape mapping (the gguf pair is ONE entry, never two):
        tts-gguf : path = backbone .gguf, mmproj = projector .gguf   (llama-tts -m/-mm)
        tts-mlx  : path = model dir                                  (mlx-audio --model)
        stt-mlx  : path = model dir                                  (mlx-whisper)

    `vision` and `ctx` are dropped: they are chat-model concepts and an audio entry
    carrying vision:true would light up a "vision" pill on a voice model.
    """
    fmt = str(voice_format or "").strip().lower()
    if fmt not in AUDIO_FORMATS:
        raise ValueError(f"unsupported audio format {voice_format!r} "
                         f"(expected one of {', '.join(AUDIO_FORMATS)})")
    out = {
        "id": base.get("id"),
        "name": base.get("name") or base.get("id"),
        "kind": "audio",
        "format": fmt,
        "path": base.get("path"),
        "size_bytes": base.get("size_bytes"),
        "source": base.get("source") or "download",
        "repo": base.get("repo") or None,
    }
    # llama-tts needs BOTH halves; the mlx engines take a directory and nothing else,
    # so an mmproj key there would be dead weight (and misleading in the detail pane).
    out["mmproj"] = base.get("mmproj") if fmt == "tts-gguf" else None
    return out


def audio_entry_view(m: dict) -> dict:
    """JSON view of an audio registry entry for /api/voice/config + /api/models."""
    fmt = entry_format(m)
    vv = voices_for_entry(m)
    return {
        "id": m.get("id"),
        "name": m.get("name") or m.get("id"),
        "kind": "audio",
        "format": fmt,
        "role": "stt" if fmt in STT_FORMATS else "tts",
        "engine": ("mlx" if fmt.endswith("-mlx") else "llamacpp"),
        "size_bytes": m.get("size_bytes"),
        "path": m.get("path"),
        "mmproj": m.get("mmproj"),
        "voice": m.get("voice") or None,
        # The names the Audio-tab detail pane offers as chips, read from the MODEL
        # (config.json spk_id, or Kokoro's voices/*.pt) and only falling back to the
        # static table. [] + a voice_note ⇒ this checkpoint genuinely has no names
        # and the pane shows the note INSTEAD of a picker; [] with no note ⇒ we do
        # not know this family, so free text. See voices_for_entry.
        "voices": vv["voices"],
        "voice_note": vv["note"] or None,
        "dialects": vv["dialects"],
        "voice_source": vv["source"],
        "tts_model_type": vv["model_type"],
        # CLONING: this checkpoint takes its voice from AUDIO, so the panel offers a
        # clip picker instead of names. The clip's NAME (never the whole path) is what
        # the UI needs; the path stays server-side, where it is validated.
        "cloning": bool(vv.get("cloning")),
        "ref_audio": (os.path.basename(str(m.get("ref_audio")))
                      if m.get("ref_audio") else None),
        "ref_text": m.get("ref_text") or None,
        "lang": m.get("lang") or None,
        "source": m.get("source"),
        "repo": m.get("repo"),
    }


# ── argv builders (PURE) ────────────────────────────────────────────────────────
def tts_argv(entry: dict, text: str, out_path: str,
             llama_bin: str, mlx_py: str) -> list:
    """Build the one-shot command line for a TTS render. Pure: no filesystem, no
    spawn — so both engines' argv surfaces are pinned by unit tests.

    `out_path` is the wav we expect to exist afterwards. For MLX that is expressed
    as --output_path <dirname> + --file_prefix <stem>, which (with --join_audio)
    produces exactly <dirname>/<stem>.wav.
    """
    fmt = entry_format(entry)
    if fmt == "tts-gguf":
        argv = [str(llama_bin),
                "-m", str(entry.get("path") or ""),
                "-mm", str(entry.get("mmproj") or ""),
                "-p", text,
                "-o", str(out_path)]
        lang = str(entry.get("lang") or "").strip()
        if lang:
            argv += ["--tts-lang", lang]
        if entry.get("max_frames"):
            argv += ["-n", str(entry["max_frames"])]
        return argv
    if fmt == "tts-mlx":
        out_dir = os.path.dirname(str(out_path)) or "."
        stem = os.path.splitext(os.path.basename(str(out_path)))[0]
        argv = [str(mlx_py), "-m", "mlx_audio.tts.generate",
                "--model", str(entry.get("path") or ""),
                "--text", text,
                # WITHOUT this the tool writes <stem>_000.wav segments and our
                # render_ok() check on <stem>.wav would report a false failure.
                "--join_audio",
                "--output_path", out_dir,
                "--file_prefix", stem]
        voice = str(entry.get("voice") or "").strip()
        if voice:
            argv += ["--voice", voice]
        # Reference audio: the ONLY voice control a zero-shot model has (OmniVoice
        # and the Qwen3-TTS Base variant both ignore names entirely). Emitted only
        # when pinned, and never on the gguf branch above — llama-tts has no such
        # flag. `--ref_text` is optional and improves the clone; without it the
        # engine transcribes the clip itself with whisper (generate.py:274-292),
        # which works but costs a second model load per render.
        ref = str(entry.get("ref_audio") or "").strip()
        if ref:
            argv += ["--ref_audio", ref]
            ref_text = str(entry.get("ref_text") or "").strip()
            if ref_text:
                argv += ["--ref_text", ref_text]
        return argv
    raise ValueError(f"unsupported TTS format {fmt!r} "
                     f"(expected one of {', '.join(TTS_FORMATS)})")


# The inline program of the FALLBACK STT form. Kept as a module constant so the unit
# test can assert on it without duplicating a 200-char string literal.
STT_INLINE_PROGRAM = (
    "import mlx_whisper,json,sys; "
    "print(json.dumps(mlx_whisper.transcribe(sys.argv[1], path_or_hf_repo=sys.argv[2])))"
)


def stt_argv(entry: dict, audio_path: str, out_dir: str,
             mlx_bin: str, mlx_py: "str | None" = None,
             use_script: bool = True) -> list:
    """Build the one-shot command line for a transcription. Pure.

    TWO forms, and the difference matters to the caller:

      use_script=True  → the `mlx_whisper` CONSOLE SCRIPT. Per spec amendment §6 the
        CLI WRITES FILES and prints nothing useful to stdout, so `-f json -o <dir>`
        puts `<stem-of-audio>.json` in out_dir and stt_read_output() reads it.
      use_script=False → ⚠️ FALLBACK for a venv where mlx-whisper is importable but
        its console script is absent (a `--no-deps`/partial install, or a wheel
        installed with scripts stripped). It calls the library directly and prints the
        result dict to STDOUT as json. Same parser handles both because
        stt_read_output() prefers the file and falls back to the captured stdout.
        ⚠️ PENDING FABLE QA: the fallback exists because the console script is the one
        piece of this path we cannot verify in-sandbox; if the Mac shows the script is
        always present, this branch is dead weight and can be deleted.

    `--verbose False` in the script form: mlx_whisper's CLI prints every segment to
    stdout as it decodes, which would fill our log tail with the transcript itself.
    """
    fmt = entry_format(entry)
    if fmt not in STT_FORMATS:
        raise ValueError(f"unsupported STT format {fmt!r} "
                         f"(expected one of {', '.join(STT_FORMATS)})")
    model = str(entry.get("path") or "")
    if use_script:
        return [str(mlx_bin), str(audio_path),
                "--model", model,
                "-f", "json",
                "-o", str(out_dir),
                "--verbose", "False"]
    return [str(mlx_py or ""), "-c", STT_INLINE_PROGRAM, str(audio_path), model]


def normalize_audio_suffix(suffix: object) -> "str | None":
    """'.WebM' / 'audio/webm;codecs=opus' / 'webm' → 'webm'. None when unusable.

    Accepts a mime type too so the endpoint can fall back to Content-Type when no
    ?fmt= was given. 'audio/mpeg' and 'audio/x-m4a' are normalised to their file
    suffixes because ffmpeg keys off the container, not our naming.
    """
    s = str(suffix or "").strip().lower()
    if not s:
        return None
    s = s.split(";")[0].strip()          # drop ';codecs=opus'
    if "/" in s:                         # a mime type
        s = s.split("/")[-1].strip()
    s = s.lstrip(".")
    s = {"mpeg": "mp3", "mpga": "mp3", "x-m4a": "m4a", "x-wav": "wav",
         "wave": "wav", "vnd.wave": "wav", "quicktime": "mp4"}.get(s, s)
    return s if s in STT_SUFFIXES else None


def stt_needs_conversion(suffix: object) -> bool:
    """Everything but wav goes through ffmpeg. Even a wav is NOT resampled: whisper
    resamples internally, and skipping ffmpeg entirely means the common desktop-curl
    case (a wav file) needs no external tool at all."""
    return normalize_audio_suffix(suffix) != "wav"


def ffmpeg_argv(ff_bin: str, src: str, dst: str) -> list:
    """16 kHz mono PCM wav — whisper's native input. Pure."""
    return [str(ff_bin), "-nostdin", "-y", "-i", str(src),
            "-ac", "1", "-ar", str(STT_SAMPLE_RATE),
            "-f", "wav", str(dst)]


def validate_stt_request(audio_bytes: object, suffix: object,
                         entry: "dict | None") -> "str | None":
    """None when the request can be attempted, else a short user-facing reason."""
    if not isinstance(audio_bytes, (bytes, bytearray)) or not audio_bytes:
        return "no audio received"
    if len(audio_bytes) > VOICE_MAX_AUDIO_BYTES:
        return (f"that recording is too large ({len(audio_bytes) // (1024 * 1024)} MB) — "
                f"the cap is {VOICE_MAX_AUDIO_BYTES // (1024 * 1024)} MB")
    if normalize_audio_suffix(suffix) is None:
        return (f"unsupported audio format {str(suffix or '(none)')!r} — "
                f"expected one of {', '.join(STT_SUFFIXES)}")
    if not entry:
        return "no speech-to-text model configured — pick one in Models → Audio"
    if not is_stt_entry(entry):
        return (f"'{entry.get('id')}' is not a speech-to-text model "
                f"(format {entry_format(entry) or 'unknown'})")
    if not str(entry.get("path") or "").strip():
        return f"'{entry.get('id')}' has no model path in the registry"
    return None


def stt_text_from_payload(payload: object) -> str:
    """Pull the transcript out of whisper's result dict. Pure.

    Both forms produce the same shape ({"text": …, "segments": [...], …}); segments
    are joined only when `text` is missing, which some versions do for `-f json`.
    """
    if isinstance(payload, str):
        return payload.strip()
    if not isinstance(payload, dict):
        return ""
    txt = payload.get("text")
    if isinstance(txt, str) and txt.strip():
        return txt.strip()
    segs = payload.get("segments")
    if isinstance(segs, list):
        return " ".join(str(s.get("text") or "").strip()
                        for s in segs if isinstance(s, dict)).strip()
    return ""


def stt_read_output(out_dir: str, stem: str, stdout: str = "") -> str:
    """File first (console-script form), then stdout (fallback form). Returns '' when
    neither yielded a transcript — which, per the exit-0 invariant, IS the failure
    signal: mlx_whisper prints a traceback and returns normally on a bad model."""
    path = os.path.join(str(out_dir), f"{stem}.json")
    try:
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return stt_text_from_payload(json.load(f))
    except (OSError, ValueError):
        pass
    raw = (stdout or "").strip()
    if raw:
        # The library form prints exactly one json object; be forgiving about a
        # leading warning line by scanning back to the last '{'.
        start = raw.rfind("{")
        if start >= 0:
            try:
                return stt_text_from_payload(json.loads(raw[start:]))
            except ValueError:
                pass
    return ""


def stt_transcribe(entry: dict, audio_bytes: bytes, suffix: str,
                   root: "str | Path | None" = None,
                   mlx_bin: "str | None" = None,
                   mlx_py: "str | None" = None,
                   ff_bin: "str | None" = None) -> str:
    """Transcribe `audio_bytes` with `entry` and return the text.

    Shares tts_render's whole shape on purpose: the SAME global lock (a whisper load
    is multi-GB too), the same 120s cap, the same always-cleaned temp dir, and the
    same "the engine can exit 0 having done nothing" success rule — here 'a non-empty
    transcript came back' rather than 'a non-empty wav exists'.
    """
    root = Path(root or ROOT)
    err = validate_stt_request(audio_bytes, suffix, entry)
    if err:
        raise VoiceError(err)
    sfx = normalize_audio_suffix(suffix)

    mb = mlx_bin or mlx_whisper_bin(root)
    mp = mlx_py or mlx_python(root)
    use_script = os.path.isfile(mb) and os.access(mb, os.X_OK)
    if not use_script and not os.path.isfile(mp):
        raise VoiceError(f"the MLX runtime is missing at {mp} — run scripts/install_mlx.sh")

    ff = None
    if sfx != "wav":
        ff = ff_bin or ffmpeg_bin(root)
        if not ff:
            # Short by design: this is a chip tooltip, not a paragraph.
            raise VoiceError("ffmpeg is needed to read that recording — install the "
                             "voicebox or voicestudio component (either provisions it)")

    if not _RENDER_LOCK.acquire(blocking=False):
        raise VoiceBusy("a voice render is already in progress — try again in a moment")
    tmp_dir = None
    try:
        tmp_root = root / "data" / "tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)
        tmp_dir = tempfile.mkdtemp(prefix="stt-", dir=str(tmp_root))
        src = os.path.join(tmp_dir, f"in.{sfx}")
        with open(src, "wb") as f:
            f.write(bytes(audio_bytes))

        audio_path, stem = src, "in"
        if ff:
            wav = os.path.join(tmp_dir, "conv.wav")
            try:
                c = subprocess.run(ffmpeg_argv(ff, src, wav), capture_output=True,
                                   text=True, cwd=str(root), timeout=VOICE_TIMEOUT_S)
            except subprocess.TimeoutExpired as e:
                raise VoiceError(f"audio conversion timed out after {VOICE_TIMEOUT_S}s",
                                 _tail(getattr(e, "stdout", ""), getattr(e, "stderr", "")))
            if not (os.path.isfile(wav) and os.path.getsize(wav) > 0):
                raise VoiceError("could not decode that recording (ffmpeg produced no audio)",
                                 _tail(c.stdout, c.stderr))
            audio_path, stem = wav, "conv"

        argv = stt_argv(entry, audio_path, tmp_dir, mb, mp, use_script=use_script)
        try:
            p = subprocess.run(argv, capture_output=True, text=True,
                               cwd=str(root), timeout=VOICE_TIMEOUT_S)
        except subprocess.TimeoutExpired as e:
            raise VoiceError(
                f"transcription timed out after {VOICE_TIMEOUT_S}s",
                _tail(getattr(e, "stdout", ""), getattr(e, "stderr", "")))
        log = _tail(p.stdout, p.stderr)
        # p.returncode deliberately NOT checked — same invariant as render_ok().
        text = stt_read_output(tmp_dir, stem, p.stdout)
        if not text:
            raise VoiceError(
                f"{entry.get('id')} returned no transcript (exit {p.returncode}) — "
                f"silence, or the model failed to load", log)
        return text
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        _RENDER_LOCK.release()


# ── validation (PURE) ───────────────────────────────────────────────────────────
def validate_tts_request(text: object, entry: "dict | None") -> "str | None":
    """None when the request can be attempted, else a short user-facing reason."""
    if not isinstance(text, str) or not text.strip():
        return "no text to speak"
    if len(text) > VOICE_MAX_CHARS:
        return (f"text is too long ({len(text)} characters) — "
                f"the cap is {VOICE_MAX_CHARS} per render")
    if not entry:
        return "no voice model configured — pick one in Models → Audio"
    fmt = entry_format(entry)
    if not is_tts_entry(entry):
        return (f"'{entry.get('id')}' is not a TTS model "
                f"(format {fmt or 'unknown'})")
    if not str(entry.get("path") or "").strip():
        return f"'{entry.get('id')}' has no model path in the registry"
    if fmt == "tts-gguf" and not str(entry.get("mmproj") or "").strip():
        return (f"'{entry.get('id')}' is missing its mmproj file — llama-tts needs "
                f"both the backbone (-m) and the projector (-mm)")
    return None


# ── success predicate (the exit-0-on-failure invariant) ─────────────────────────
def render_ok(out_path: str) -> bool:
    """The ONLY definition of success. Both engines can exit 0 having produced
    nothing (mlx-audio swallows exceptions and returns normally), so the return code
    is never consulted anywhere in this module."""
    try:
        return os.path.isfile(out_path) and os.path.getsize(out_path) > 0
    except OSError:
        return False


# ── persistent MLX TTS worker ───────────────────────────────────────────────────
# THE PROBLEM IT SOLVES: `python -m mlx_audio.tts.generate` reloads the whole 3.6GB
# checkpoint on every invocation, so a re-listen cost as much as the first listen.
# bridge/voice_worker.py keeps the model resident and renders on demand over JSON
# lines on a pipe (no port, no auth surface). This half owns its lifecycle.
#
# LIFECYCLE (Debi-ratified):
#   spawn   — lazily, on the first tts-mlx render
#   respawn — on a MODEL change (a worker holds exactly one checkpoint)
#   voice   — per REQUEST, so a voice change costs nothing: no reload
#   kill    — when the TTS default is cleared/changed, on Unload, on the model's
#             deletion, or on any protocol failure. NO idle timeout: a resident
#             model is the whole point, and the ledger keeps it honest.
class VoiceBudget(VoiceError):
    """Spawning the worker would blow the model-RAM budget. Maps to HTTP 409 — the
    same 'free something first' shape the runner switch returns."""


WORKER_TIMEOUT_S = 120          # one render; same cap as the one-shot path
WORKER_LOAD_TIMEOUT_S = 300     # ⚠️ a cold 3.6GB load legitimately outlasts a render
WORKER_LOG_LINES = 4000         # the worker log is trimmed to this on each spawn


def worker_script(root: "str | Path | None" = None) -> str:
    return str(Path(root or ROOT) / "bridge" / "voice_worker.py")


def worker_argv(mlx_py: str, script: str) -> list:
    """PURE. Explicit interpreter + explicit script path — the Finder-minimal-PATH
    rule applies to anything the bridge spawns, and `python` alone would be wrong
    even if it resolved (the worker needs the MLX venv, not ours)."""
    return [str(mlx_py), str(script)]


def worker_log_path(root: "str | Path | None" = None) -> str:
    return str(Path(root or ROOT) / "data" / "logs" / "voice-worker.log")


class VoiceWorker:
    """A handle on one resident worker process. One in-flight request at a time.

    Every failure mode collapses to the same answer: kill the process and mark it
    down. The next render spawns a fresh one, so a wedged or crashed worker costs a
    single slow render, never a stuck panel.
    """

    def __init__(self, model_id: str, model_path: str, size_bytes: int = 0,
                 root: "str | Path | None" = None, mlx_py: "str | None" = None):
        self.model_id = model_id
        self.model_path = model_path
        self.size_bytes = int(size_bytes or 0)
        self.root = Path(root or ROOT)
        self.mlx_py = mlx_py or mlx_python(self.root)
        self.proc = None
        self.started_at = 0.0
        self.renders = 0
        self._seq = 0
        self._lock = threading.Lock()          # one in-flight request
        self._q = None
        self._logf = None

    # ── plumbing ───────────────────────────────────────────────────────────────
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _reader(self, stdout, q):
        """Own thread: readline() has no timeout, so the timeout lives on the queue."""
        try:
            for line in stdout:
                q.put(line)
        except (OSError, ValueError):
            pass
        finally:
            q.put(None)                        # EOF sentinel — the process is gone

    def start(self) -> None:
        """Spawn + `load`. Raises VoiceError if either fails (nothing is left running)."""
        import queue as _queue
        if not os.path.isfile(self.mlx_py):
            raise VoiceError(f"the MLX runtime is missing at {self.mlx_py} — "
                             f"run scripts/install_mlx.sh")
        script = worker_script(self.root)
        if not os.path.isfile(script):
            raise VoiceError(f"the voice worker is missing at {script}")
        logp = worker_log_path(self.root)
        os.makedirs(os.path.dirname(logp), exist_ok=True)
        _trim_log(logp, WORKER_LOG_LINES)
        self._logf = open(logp, "a", encoding="utf-8", errors="replace")
        self._logf.write(f"\n=== voice worker {self.model_id} "
                         f"({time.strftime('%Y-%m-%d %H:%M:%S')}) ===\n")
        self._logf.flush()
        try:
            self.proc = subprocess.Popen(
                worker_argv(self.mlx_py, script),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._logf,
                cwd=str(self.root), text=True, bufsize=1)
        except OSError as e:
            self._close_log()
            raise VoiceError(f"could not start the voice worker: {str(e)[:200]}")
        self.started_at = time.time()
        self._q = _queue.Queue()
        threading.Thread(target=self._reader, args=(self.proc.stdout, self._q),
                         daemon=True).start()
        try:
            self._request({"cmd": "load", "model": self.model_path},
                          WORKER_LOAD_TIMEOUT_S)
        except VoiceError:
            self.stop()
            raise

    def _close_log(self) -> None:
        try:
            if self._logf:
                self._logf.close()
        except OSError:
            pass
        self._logf = None

    def stop(self) -> None:
        """Idempotent. Closing stdin is the polite exit (the worker loop ends at EOF);
        kill is the guarantee."""
        p, self.proc = self.proc, None
        if p is not None:
            try:
                if p.stdin:
                    p.stdin.close()
            except OSError:
                pass
            try:
                p.wait(timeout=2)
            except Exception:                                   # noqa: BLE001
                try:
                    p.kill()
                    p.wait(timeout=2)
                except Exception:                               # noqa: BLE001
                    pass
        self._close_log()
        self._q = None

    def _request(self, payload: dict, timeout: float) -> dict:
        """Send one request, wait for its reply. Any protocol trouble kills the
        process and raises — a half-read pipe can never be trusted again."""
        if not self.alive():
            raise VoiceError("the voice worker is not running")
        self._seq += 1
        rid = self._seq
        line = json.dumps(dict(payload, id=rid), ensure_ascii=True) + "\n"
        try:
            self.proc.stdin.write(line)
            self.proc.stdin.flush()
        except (OSError, ValueError) as e:
            self.stop()
            raise VoiceError(f"the voice worker stopped accepting input "
                             f"({str(e)[:120]})", _log_tail(worker_log_path(self.root)))
        deadline = time.time() + timeout
        while True:
            try:
                raw = self._q.get(timeout=max(0.05, deadline - time.time()))
            except Exception:                                   # queue.Empty
                self.stop()
                raise VoiceError(
                    f"the voice worker did not answer within {int(timeout)}s",
                    _log_tail(worker_log_path(self.root)))
            if raw is None:
                self.stop()
                raise VoiceError("the voice worker exited",
                                 _log_tail(worker_log_path(self.root)))
            try:
                resp = json.loads(raw)
            except ValueError:
                # Not protocol json. The worker redirects fd 1 to stderr precisely so
                # this cannot happen; if it does, the stream is untrustworthy.
                self.stop()
                raise VoiceError("the voice worker sent something that was not a "
                                 "response", _log_tail(worker_log_path(self.root)))
            if not isinstance(resp, dict):
                continue
            if resp.get("id") not in (rid, 0):
                continue                       # a stale reply; keep reading
            if not resp.get("ok"):
                raise VoiceError(str(resp.get("error") or "the voice worker failed"),
                                 _log_tail(worker_log_path(self.root)))
            return resp

    # ── the one public operation ───────────────────────────────────────────────
    def render(self, text: str, voice: str, out_path: str,
               ref_audio: str = "", ref_text: str = "") -> dict:
        """One render. VoiceBusy (→409) when another render holds this worker, which
        mirrors the one-shot path's answer rather than queueing behind it.

        `ref_audio`/`ref_text` are PER REQUEST, exactly like `voice`: changing the
        pinned clip must never cost a respawn — the model is what the worker holds,
        the reference is just an argument to generate().
        """
        if not self._lock.acquire(blocking=False):
            raise VoiceBusy("a voice render is already in progress — try again in a moment")
        try:
            resp = self._request(
                {"cmd": "tts", "text": text, "voice": voice or "", "out": out_path,
                 "ref_audio": ref_audio or "", "ref_text": ref_text or ""},
                WORKER_TIMEOUT_S)
            self.renders += 1
            return resp
        finally:
            self._lock.release()

    def info(self) -> dict:
        return {"model": self.model_id, "path": self.model_path,
                "size_bytes": self.size_bytes, "renders": self.renders,
                "uptime_s": int(time.time() - self.started_at) if self.started_at else 0,
                "pid": (self.proc.pid if self.alive() else None)}


def _trim_log(path: str, keep: int) -> None:
    """Keep the worker log bounded without rotating files around (one long-lived
    process appends to one fd — a rename would orphan its output)."""
    try:
        if not os.path.isfile(path):
            return
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if len(lines) > keep:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines[-keep:])
    except OSError:
        pass


def _log_tail(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()[-VOICE_LOG_TAIL:]
    except OSError:
        return ""


# ── the module-level singleton (at most ONE resident model) ─────────────────────
_WORKER = None                      # VoiceWorker | None
_WORKER_MUTEX = threading.Lock()    # guards the swap, NOT the render


def worker_resident() -> "dict | None":
    """What is resident right now, or None. Read by the ledger and /api/voice/config.
    A dead-but-not-reaped worker reports None: the ledger must not charge for RAM
    that a crashed process already gave back."""
    w = _WORKER
    if w is None or not w.alive():
        return None
    return w.info()


def worker_stop(reason: str = "") -> bool:
    """Kill the resident worker if there is one. Idempotent; True when one died."""
    global _WORKER
    with _WORKER_MUTEX:
        w, _WORKER = _WORKER, None
        if w is None:
            return False
        was = w.alive()
        w.stop()
        if was:
            print(f"[voice] worker stopped ({w.model_id})"
                  f"{' — ' + reason if reason else ''}", flush=True)
        return was


def worker_stop_if_model(model_id: str, reason: str = "") -> bool:
    """Kill only when the resident model IS `model_id`. Used by the callers that
    invalidate one model (default changed/cleared, model deleted)."""
    w = _WORKER
    if w is None or w.model_id != str(model_id or ""):
        return False
    return worker_stop(reason)


def get_worker(entry: dict, root: "str | Path | None" = None,
               mlx_py: "str | None" = None,
               spawn_guard=None) -> VoiceWorker:
    """The resident worker for `entry`, spawning or respawning as needed.

    `spawn_guard(size_bytes) -> str | None` is the ledger hook: the bridge owns
    harness.yaml and the RAM budget, so voice.py asks rather than reads. A returned
    string is the refusal shown to the user (VoiceBudget → 409). It is consulted
    ONLY on a real spawn — an already-resident model is already accounted for.
    """
    global _WORKER
    mid = str(entry.get("id") or "")
    path = str(entry.get("path") or "")
    with _WORKER_MUTEX:
        w = _WORKER
        if w is not None and (not w.alive() or w.model_id != mid):
            why = "model changed" if w.alive() else "process gone"
            w.stop()
            _WORKER = None
            print(f"[voice] worker replaced ({w.model_id} → {mid}, {why})", flush=True)
            w = None
        if w is None:
            if spawn_guard is not None:
                refusal = spawn_guard(int(entry.get("size_bytes") or 0))
                if refusal:
                    raise VoiceBudget(refusal)
            w = VoiceWorker(mid, path, entry.get("size_bytes") or 0,
                            root=root, mlx_py=mlx_py)
            w.start()                       # raises with nothing left running
            _WORKER = w
            print(f"[voice] worker resident: {mid}", flush=True)
        return w


def tts_render_worker(entry: dict, text: str,
                      root: "str | Path | None" = None,
                      mlx_py: "str | None" = None,
                      spawn_guard=None) -> bytes:
    """A tts-mlx render through the resident worker. Deliberately does NOT take the
    global one-shot lock — nothing multi-GB is being loaded here, so a speak render
    no longer blocks dictation (or vice versa)."""
    root = Path(root or ROOT)
    err = validate_tts_request(text, entry)
    if err:
        raise VoiceError(err)
    w = get_worker(entry, root=root, mlx_py=mlx_py, spawn_guard=spawn_guard)
    tmp_root = root / "data" / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="tts-", dir=str(tmp_root))
    try:
        out_path = os.path.join(tmp_dir, "out.wav")
        w.render(text, str(entry.get("voice") or "").strip(), out_path,
                 ref_audio=str(entry.get("ref_audio") or "").strip(),
                 ref_text=str(entry.get("ref_text") or "").strip())
        # The worker already applied render_ok; re-checking here keeps the invariant
        # stated at BOTH ends of the pipe rather than trusting one side of it.
        if not render_ok(out_path):
            raise VoiceError(f"{entry.get('id')} produced no audio",
                             _log_tail(worker_log_path(root)))
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── dispatch ────────────────────────────────────────────────────────────────────
def _tail(*chunks: object) -> str:
    return ("".join(str(c or "") for c in chunks))[-VOICE_LOG_TAIL:]


def resolve_render_voice(entry: dict) -> str:
    """The voice a render should actually use, '' meaning engine default.

    DEFAULT-VOICE FALLBACK (Debi 2026-08-13: "model default" on the CustomVoice
    checkpoint rendered NOTHING — that model refuses a voiceless render, unlike
    Base which ignores names). When no voice is pinned and the model's OWN config
    declares named voices, use its first declared name: deterministic, and always
    a name the checkpoint itself vouches for. Models without config-declared
    voices are untouched (Base/Kokoro keep engine-default behaviour).
    """
    pinned = str((entry or {}).get("voice") or "").strip()
    if pinned:
        return pinned
    if entry_format(entry) != "tts-mlx":
        return ""
    vinfo = voices_for_entry(entry)
    if vinfo.get("source") == "config" and vinfo.get("voices"):
        return str(vinfo["voices"][0])
    return ""


def tts_render(entry: dict, text: str,
               root: "str | Path | None" = None,
               llama_bin: "str | None" = None,
               mlx_py: "str | None" = None,
               use_worker: bool = True,
               spawn_guard=None) -> bytes:
    """Render `text` with `entry` and return the wav bytes. THE single entry point.

    tts-mlx goes through the RESIDENT worker (model loaded once, no global lock);
    tts-gguf stays a one-shot llama-tts call under the global lock. `use_worker=False`
    forces the old one-shot MLX path — kept because it is the fallback a broken
    worker degrades to, and because the tests exercise the argv surface through it.

    Raises VoiceBusy when another render is in flight, VoiceBudget when spawning a
    worker would blow the RAM budget, VoiceError otherwise (validation, missing
    engine, timeout, or an empty/absent output wav). The temp directory is ALWAYS
    removed, including on timeout.
    """
    root = Path(root or ROOT)
    err = validate_tts_request(text, entry)
    if err:
        raise VoiceError(err)

    fmt = entry_format(entry)
    ev = resolve_render_voice(entry)
    if ev != str(entry.get("voice") or "").strip():
        entry = dict(entry, voice=ev)

    if fmt == "tts-mlx" and use_worker:
        return tts_render_worker(entry, text, root=root, mlx_py=mlx_py,
                                 spawn_guard=spawn_guard)
    lb = llama_bin or llama_tts_bin(root)
    mp = mlx_py or mlx_python(root)
    if fmt == "tts-gguf" and not (os.path.isfile(lb) and os.access(lb, os.X_OK)):
        raise VoiceError(f"llama-tts not found at {lb} — run scripts/install_llamacpp.sh")
    if fmt == "tts-mlx" and not os.path.isfile(mp):
        raise VoiceError(f"the MLX runtime is missing at {mp} — run scripts/install_mlx.sh")

    if not _RENDER_LOCK.acquire(blocking=False):
        raise VoiceBusy("a voice render is already in progress — try again in a moment")
    tmp_dir = None
    try:
        tmp_root = root / "data" / "tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)
        tmp_dir = tempfile.mkdtemp(prefix="tts-", dir=str(tmp_root))
        out_path = os.path.join(tmp_dir, "out.wav")
        argv = tts_argv(entry, text, out_path, lb, mp)
        try:
            p = subprocess.run(argv, capture_output=True, text=True,
                               cwd=str(root), timeout=VOICE_TIMEOUT_S)
        except subprocess.TimeoutExpired as e:
            raise VoiceError(
                f"voice render timed out after {VOICE_TIMEOUT_S}s",
                _tail(getattr(e, "stdout", ""), getattr(e, "stderr", "")))
        log = _tail(p.stdout, p.stderr)
        # NOTE: p.returncode is deliberately NOT checked — see render_ok().
        if not render_ok(out_path):
            raise VoiceError(
                f"{entry.get('id')} produced no audio (exit {p.returncode}) — "
                f"the engine can exit 0 on failure, so this is the real check", log)
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        _RENDER_LOCK.release()
