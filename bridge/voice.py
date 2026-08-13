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
import shutil
import subprocess
import tempfile
import threading
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
    """The named voices worth OFFERING for this registry entry. PURE.

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


class VoiceError(RuntimeError):
    """A render failed. `.message` is user-facing; `.log_tail` is the engine's output."""

    def __init__(self, message: str, log_tail: str = ""):
        super().__init__(message)
        self.message = message
        self.log_tail = log_tail or ""


class VoiceBusy(VoiceError):
    """A render is already in flight (one at a time). Maps to HTTP 409."""


# ONE global render lock, not one per engine: two engines rendering at once would
# each load a multi-GB model, and the ledger deliberately does not account for voice
# weights (spec: transient RAM only). Serialising is the cheap safe answer, and a
# TTS render is a couple of seconds. ⚠️ PENDING FABLE QA (per-engine locks would
# allow tts+stt concurrency later).
_RENDER_LOCK = threading.Lock()


def render_lock() -> threading.Lock:
    """Exposed so tests (and any future STT path) can reason about the same lock."""
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
        # The names the Audio-tab detail pane offers as chips. [] ⇒ free text
        # (unknown family) or no picker at all (tts-gguf / stt) — see voices_for.
        "voices": voices_for(m),
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


# ── dispatch ────────────────────────────────────────────────────────────────────
def _tail(*chunks: object) -> str:
    return ("".join(str(c or "") for c in chunks))[-VOICE_LOG_TAIL:]


def tts_render(entry: dict, text: str,
               root: "str | Path | None" = None,
               llama_bin: "str | None" = None,
               mlx_py: "str | None" = None) -> bytes:
    """Render `text` with `entry` and return the wav bytes.

    Raises VoiceBusy when another render holds the lock, VoiceError otherwise
    (validation, missing engine, timeout, or an empty/absent output wav). The temp
    directory is ALWAYS removed, including on timeout.
    """
    root = Path(root or ROOT)
    err = validate_tts_request(text, entry)
    if err:
        raise VoiceError(err)

    fmt = entry_format(entry)
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
