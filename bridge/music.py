"""MOT Deck-native MUSIC lane (FABLE-MUSIC-LANE-SPEC, 2026-08-20).

Same shape as the voice capability and deliberately NOT a component: no port, no
manifest entry, no daemon, no Swift change. A render is a ONE-SHOT SUBPROCESS run
as a background job; the only persistent cost is disk.

Two engines, both measured on sample's Mac before adoption and both kept because both
passed the ear test (docs/handoff/MUSIC-MEASUREMENT-RUNBOOK.md):

  minimax  MiniMax-Music3-MLX int8, 30 flow steps — 60s of song in ~115s wall.
           Runs `generate.py` straight out of an HF snapshot.
  acestep  acestep.cpp GGUF Q8_0 turbo, 8 inference steps — 60s of song in ~25s.
           Two binaries, two loads: ace-lm writes <stem>0.json, ace-synth renders
           <stem>00.<ext> beside it.

THE FOUR THINGS THAT BIT THE PROTOTYPE, encoded here so they cannot bite again:

  1. **The HF snapshot is a SYMLINK FARM.** Every file in `snapshots/<rev>/` is a
     symlink into `../../blobs/<sha>`, and CPython sets `sys.path[0]` to the
     *resolved* directory of the script — the flat blobs dir, where no sibling has a
     name. `generate.py` imports `minimax_mlx_model` by bare name and died. A `cd`
     does NOT fix it (cwd is not on sys.path for a script file); PYTHONPATH does.
     And `--model-dir` defaults to `Path(__file__).resolve().parent` — the blobs dir
     again — while model_manifest.json addresses weights by RELATIVE path. So the
     minimax command carries all three: cwd, PYTHONPATH, explicit --model-dir.
  2. **The engines are one-shot and their exit codes are not the whole truth.**
     Success is defined as: the expected audio file exists and is non-empty. Same
     invariant the voice lane holds.
  3. **Explicit paths, never PATH lookup** — anything the bridge spawns inherits a
     Finder-minimal PATH.
  4. **Never launch upstream's server.sh** (it binds 0.0.0.0). Only ./build/ace-lm
     and ./build/ace-synth are ever exec'd.

Everything decision-shaped in here is a PURE function so it can be table-tested:
argv/request builders, validation, the RAM gate, install detection, library
listing and delete containment. See bridge/tests/test_music_lane.py.
"""
from __future__ import annotations

import glob
import json
import math
import os
import random
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

# ── constants ────────────────────────────────────────────────────────────────
ENGINES = ("minimax", "acestep")

# Planning numbers for the RAM ledger. v1 planned minimax at 32GB on a pre-measurement
# reading of the research; the honest number is the weights (11.9GB int8) plus working
# set — 14GB. It is also no longer a REFUSAL: exceeding it is a WARNING the user can
# override (sample's ruling), because the cost of being wrong is swap, not corruption,
# and only the person at the machine knows what else it is doing.
MUSIC_RAM_GB = {"minimax": 14, "acestep": 9}

# Steps mean DIFFERENT things per engine (flow steps vs DiT inference steps) — the
# defaults are each engine's own design point, not a shared knob.
DEFAULT_STEPS = {"minimax": 30, "acestep": 8}
MAX_STEPS = {"minimax": 30, "acestep": 20}

SECONDS_MIN, SECONDS_MAX = 10, 300
SECONDS_DEFAULT = 60
# 8000, not 2000: MiniMax's own demo captions run to ~4,500 characters of structured
# direction (bpm, key, section-by-section arrangement) and the engine accepts them —
# the old cap refused a caption the model was designed to read. The AR front end
# rejects a prompt over 5,000 TOKENS itself, so this is a sanity bound, not the limit.
PROMPT_MAX = 8000
LYRICS_MAX = 20000            # generous: a full lyric sheet, still bounded
# VERIFIED at the pin (2026-08-20, generate.py read from the HF raw endpoint):
#   parser.add_argument("--seed", type=bounded_int(0, 2**31 - 1), default=7)
# so 2**31-1 is the ENGINE's own ceiling, not ours. The deck spec proposed telling the
# user "0 to 4294967295" (2**32-1); that would have been a number generate.py REFUSES
# at argparse time, minutes before any GPU work. The stated range is therefore the real
# one, and SEED_HELP is single-sourced from this constant so the two can never drift.
SEED_MAX = 2 ** 31 - 1
SEED_HELP = (f"Any whole number from 0 to {SEED_MAX}. The same seed + the same settings "
             f"+ the same engine = the same song again. Leave it empty to roll a new "
             f"one (it is recorded with the track).")

# ── output formats ───────────────────────────────────────────────────────────
# VERIFIED at the pins (2026-08-20), not assumed:
#   acestep  docs/ARCHITECTURE.md @ 9761469d95fc: `output_format` "picks the audio
#            encoder: "mp3", "wav16", "wav24", "wav32"" — a JSON field, no CLI flag.
#   minimax  generate.py @ 0505e3f writes with `wave` directly (write_wav, 2ch/16-bit/
#            44.1kHz) and has NO format argument at all. wav is the only truth there.
MINIMAX_FORMATS = ("wav",)
ACESTEP_FORMATS = ("wav24", "wav32", "wav16", "mp3")
ENGINE_FORMATS = {"minimax": MINIMAX_FORMATS, "acestep": ACESTEP_FORMATS}
DEFAULT_FORMAT = {"minimax": "wav", "acestep": "wav24"}
FORMAT_EXT = {"wav": ".wav", "wav16": ".wav", "wav24": ".wav", "wav32": ".wav",
              "mp3": ".mp3"}
FORMAT_LABEL = {"wav": "WAV", "wav16": "WAV 16-bit", "wav24": "WAV 24-bit",
                "wav32": "WAV 32-bit float", "mp3": "MP3"}

# Convert-after-the-fact. Each entry names the ffmpeg ENCODER it needs, and the
# format is offered only when a probe of the resolved ffmpeg lists it — our
# provisioned imageio-ffmpeg build is not guaranteed to carry libmp3lame, and a
# control that cannot work must not be drawn (the LM-Studio hide-not-grey rule).
CONVERT_FORMATS = {
    "mp3": {"ext": ".mp3", "encoder": "libmp3lame", "bitrate": "192k"},
    "m4a": {"ext": ".m4a", "encoder": "aac", "bitrate": "192k"},
}
LIBRARY_EXTS = (".wav", ".mp3", ".m4a")
CONVERT_TIMEOUT_S = 300

# Wall-clock calibration, measured on sample's Mac (MUSIC-MEASUREMENT-RUNBOOK.md +
# her first real session). minimax is clearly SUPERLINEAR in song length — 60s of
# song cost 115.5s, 145s cost 675.6s — which is exactly why an ETA has to come from
# points rather than a rate. These are the fallback until the library has history.
MUSIC_CALIBRATION = {
    "minimax": ((60, 115.5), (145, 675.6)),
    "acestep": ((60, 24.5),),
}
# A running job never displays a completed bar: the last few percent of both engines
# is decode + write, which the progress lines do not cover.
PROGRESS_DISPLAY_CAP = 0.95

# THE PHASE MODEL (v1.2). A render has two phases with completely different shapes:
#   SETUP   — weights off disk into MLX/Metal. Its own counters count FILES, which say
#             nothing about time, so the bar rides ELAPSED against a fixed allowance.
#   RENDER  — the actual generation. Here the engine's counters ARE time-proportional
#             enough to drive a bar.
# Setup owns the first SETUP_SHARE of the bar and render the rest.
SETUP_ALLOWANCE_S = 60.0
SETUP_SHARE = 0.15
# The blend point for the measured ETA: below this the estimate still leads, above it
# the render's own observed rate does.
ETA_TRUST_AT = 0.5

SETTINGS_FILE = "music_settings.json"      # data/music_settings.json
TEMPLATES_FILE = "templates.json"          # data/music/templates.json (fixed home)

MUSIC_TIMEOUT_S = 1800        # 30 minutes per render (spec)
STDERR_TAIL = 2000            # bytes of engine output carried into a failure

MINIMAX_REPO = "PocketAiHub/MiniMax-Music3-MLX"
# generate.py's own help text: "--lyrics  Lyrics text; use [Instrumental] for no vocals".
MINIMAX_INSTRUMENTAL = "[Instrumental]"
ACESTEP_GGUFS = (
    "vae-BF16.gguf",
    "Qwen3-Embedding-0.6B-Q8_0.gguf",
    "acestep-5Hz-lm-4B-Q8_0.gguf",
    "acestep-v15-turbo-Q8_0.gguf",
)

# Download sizes, used ONLY as the "not installed yet" estimate. Once an engine is
# on disk the real bytes are measured instead.
ENGINE_EST_GB = {"minimax": 11.9, "acestep": 7.7}

ENGINE_LABEL = {"minimax": "MiniMax-Music3 · MLX", "acestep": "acestep.cpp · GGUF"}
ENGINE_NOTE = {
    "minimax": "~2 min per minute of song · highest quality",
    "acestep": "~25s per song · fast",
}
# minimax's licence record is owned by bridge/app.py's LICENSE_OVERRIDES (the same
# table the HF search rows read) — app.py fills this in; music.py never duplicates it.
ENGINE_LICENSE = {"acestep": {"license": "MIT", "badge": "ok", "reason": "",
                              "source_url": "https://github.com/ServeurpersoCom/acestep.cpp"}}


class MusicError(Exception):
    """A render (or its setup) failed, with a message fit to show the user."""


class MusicCancelled(MusicError):
    """The user stopped the render. A separate type because a cancellation is NOT a
    failure: it writes no track, keeps no sidecar, and must never reach the ETA
    history as if it were a measurement of how long a render costs."""


# ── paths ────────────────────────────────────────────────────────────────────
def music_base_dir(root) -> str:
    """The FIXED home under data/ — templates and the default output folder.

    Deliberately not the configurable output dir: a user who points renders at an
    external drive must not lose their templates when that drive is unplugged."""
    d = os.path.join(str(root), "data", "music")
    os.makedirs(d, exist_ok=True)
    return d


def settings_path(root) -> str:
    return os.path.join(str(root), "data", SETTINGS_FILE)


def read_settings(root) -> dict:
    """The music settings bag. Any surprise on disk degrades to defaults rather than
    breaking the page — this file is hand-editable."""
    try:
        with open(settings_path(root), encoding="utf-8") as fh:
            loaded = json.load(fh)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:                                            # noqa: BLE001
        return {}


def write_settings(root, data: dict) -> None:
    """Atomic: a half-written settings file would silently relocate the library."""
    p = settings_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, p)


def validate_output_dir(root, path) -> tuple:
    """(abspath, None) | (None, reason). PURE-ish: the only filesystem calls are the
    mkdir and the writability probe, which ARE the question being asked.

    The boundary is deliberately wide (anywhere under $HOME or under the repo) —
    this is the user's own machine and they typed the path — but never inside
    vendor/ (our never-edit rule) and never a file.
    """
    if not isinstance(path, str) or not path.strip():
        return None, "give a folder path"
    p = os.path.expanduser(path.strip())
    if not os.path.isabs(p):
        p = os.path.join(str(root), p)
    p = os.path.realpath(p)
    vendor = os.path.realpath(os.path.join(str(root), "vendor"))
    if p == vendor or p.startswith(vendor + os.sep):
        return None, "refused: vendor/ is upstream code and is never written to"
    home = os.path.realpath(os.path.expanduser("~"))
    rroot = os.path.realpath(str(root))
    inside = (p == home or p.startswith(home + os.sep)
              or p == rroot or p.startswith(rroot + os.sep))
    if not inside:
        return None, "refused: pick a folder inside your home folder or MOT Deck"
    if os.path.exists(p) and not os.path.isdir(p):
        return None, "that path is a file, not a folder"
    try:
        os.makedirs(p, exist_ok=True)
    except OSError as e:
        return None, f"could not create that folder: {e}"
    if not os.access(p, os.W_OK):
        return None, "that folder is not writable"
    return p, None


def music_dir(root) -> str:
    """Where finished songs live — data/music unless the user pointed it elsewhere.

    A configured folder that has since gone away (an unplugged drive) falls back to
    the default rather than raising: the page must still load and say where it is."""
    want = read_settings(root).get("output_dir")
    if isinstance(want, str) and want.strip():
        p = os.path.expanduser(want.strip())
        if not os.path.isabs(p):
            p = os.path.join(str(root), p)
        try:
            os.makedirs(p, exist_ok=True)
            if os.path.isdir(p):
                return os.path.realpath(p)
        except OSError:
            pass
    return music_base_dir(root)


def venv_python(root) -> str:
    return os.path.join(str(root), "data", "music-venv", "bin", "python")


def acestep_root(root) -> str:
    return os.path.join(str(root), "data", "acestep")


def acestep_bin(root, name) -> str:
    return os.path.join(acestep_root(root), "src", "build", name)


def acestep_models(root) -> str:
    return os.path.join(acestep_root(root), "models")


def hf_cache_root(env=None) -> str:
    """PURE-ish: the hub cache dir huggingface_hub would use, honouring the same env
    vars it does. Only os.path + the mapping — no filesystem access."""
    e = os.environ if env is None else env
    hub = e.get("HF_HUB_CACHE")
    if hub:
        return os.path.expanduser(hub)
    home = e.get("HF_HOME")
    if home:
        return os.path.join(os.path.expanduser(home), "hub")
    return os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")


def hf_snapshot_dir(repo: str, revision: str, cache_root: str) -> str:
    """PURE: the directory `snapshot_download(repo, revision=…)` resolves to.

    Deterministic by construction (`models--org--name/snapshots/<rev>`), which is
    what lets install detection read DISK instead of trusting a stored flag.
    """
    folder = "models--" + str(repo).replace("/", "--")
    return os.path.join(str(cache_root), folder, "snapshots", str(revision))


def cmake_bin(env=None):
    """The cmake the acestep build needs, resolved by EXPLICIT path list.

    A bridge-spawned script gets a Finder-minimal PATH, so `command -v` alone has
    missed a real tool before (the voicebox `uv` incident). Returns None when absent
    — the install endpoint then refuses BEFORE downloading anything.
    """
    cands = ["/opt/homebrew/bin/cmake", "/usr/local/bin/cmake", "/usr/bin/cmake"]
    which = shutil.which("cmake")
    if which:
        cands.insert(0, which)
    for c in cands:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


# ── install detection: read the DISK, never a stored flag ────────────────────
def minimax_installed(root, revision: str, cache_root=None) -> tuple:
    """(bool, snapshot_dir_or_'', reason). Installed = the venv interpreter exists
    AND the pinned snapshot carries every file a render needs."""
    py = venv_python(root)
    if not os.path.isfile(py):
        return False, "", "the music venv is not built yet"
    snap = hf_snapshot_dir(MINIMAX_REPO, revision,
                           cache_root if cache_root is not None else hf_cache_root())
    if not os.path.isdir(snap):
        return False, "", "the pinned weights are not downloaded"
    for f in ("generate.py", "minimax_mlx_model.py", "model_manifest.json"):
        if not os.path.exists(os.path.join(snap, f)):
            return False, snap, f"the download is incomplete (no {f})"
    return True, snap, ""


def acestep_installed(root) -> tuple:
    """(bool, '', reason). Installed = BOTH binaries are executable AND all four
    GGUFs resolve (os.path.exists follows the symlinks into the HF cache, so a
    cleared cache correctly reads as not-installed)."""
    for b in ("ace-lm", "ace-synth"):
        p = acestep_bin(root, b)
        if not (os.path.isfile(p) and os.access(p, os.X_OK)):
            return False, "", "not built yet"
    models = acestep_models(root)
    missing = [f for f in ACESTEP_GGUFS if not os.path.exists(os.path.join(models, f))]
    if missing:
        return False, "", f"{len(missing)} of {len(ACESTEP_GGUFS)} model files are missing"
    return True, "", ""


def engine_installed(root, engine: str, revision: str = "", cache_root=None) -> tuple:
    if engine == "minimax":
        return minimax_installed(root, revision, cache_root)
    if engine == "acestep":
        return acestep_installed(root)
    return False, "", "unknown engine"


def _dir_bytes(path: str, cap: int = 4000) -> int:
    """Best-effort on-disk size. Follows symlinks (the GGUFs and every snapshot file
    are symlinks into the HF cache — that IS where the bytes are), bounded by a file
    count so a surprising tree can never stall a status poll."""
    total, seen = 0, 0
    try:
        for dirpath, _dirs, files in os.walk(path):
            for f in files:
                seen += 1
                if seen > cap:
                    return total
                try:
                    total += os.stat(os.path.join(dirpath, f)).st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def engine_size_gb(root, engine: str, installed: bool, snap: str = "") -> tuple:
    """(gb, estimated). Measured when installed, the download estimate otherwise —
    a number the user can act on either way, honestly labelled."""
    if not installed:
        return ENGINE_EST_GB.get(engine, 0.0), True
    if engine == "minimax":
        return round(_dir_bytes(snap) / 1024 ** 3, 1), False
    if engine == "acestep":
        build = os.path.join(acestep_root(root), "src", "build")
        b = _dir_bytes(acestep_models(root)) + _dir_bytes(build)
        return round(b / 1024 ** 3, 1), False
    return 0.0, True


# ── the RAM ledger gate (PURE) ───────────────────────────────────────────────
def music_need_bytes(engine: str) -> int:
    return int(MUSIC_RAM_GB.get(engine, 0) * (1024 ** 3))


def ram_gate(engine: str, other_bytes: int, budget_bytes: int):
    """None = comfortable, else the WARNING text. Boundary INCLUSIVE (fitting exactly
    is fine), same predicate shape as the runner/aux/voice gates.

    ⚠️ This is no longer a refusal (sample's ruling). The budget is a planning figure,
    not a measurement of what macOS will actually do, and the failure mode of being
    wrong is swap — slow, not destructive. So the bridge states the numbers and lets
    the person at the machine decide; see `wants_confirm`.
    """
    need = music_need_bytes(engine)
    try:
        other = int(other_bytes or 0)
        budget = int(budget_bytes or 0)
    except (TypeError, ValueError):
        other, budget = 0, 0
    if need and (need + other) > budget:
        return (f"a {engine} render wants about {need / 1024**3:.0f} GB and "
                f"{other / 1024**3:.1f} GB of models are already loaded — that is over "
                f"the {budget / 1024**3:.0f} GB model-RAM budget and may push the "
                f"machine into swap. Eject the chat model first, or generate anyway.")
    return None


def wants_confirm(body) -> bool:
    """PURE: did the caller explicitly accept the RAM warning?

    Total and STRICT — only an unambiguous yes counts, because this is the flag that
    turns a warning into a spend. Anything else (missing, junk, "maybe", 0) is no.
    """
    if not isinstance(body, dict):
        return False
    v = body.get("confirm")
    if v is True:
        return True
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    return False


# ── request validation (PURE, total over junk) ───────────────────────────────
def _as_int(v, default=None):
    if isinstance(v, bool):
        return default
    if isinstance(v, int):
        return v
    if isinstance(v, float) and float(v).is_integer():
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        try:
            return int(s)
        except ValueError:
            try:
                f = float(s)
            except ValueError:
                return default
            return int(f) if f.is_integer() else default
    return default


def validate_generate(body, installed_engines) -> tuple:
    """PURE: (params, error). `params` is exactly what a render needs, with every
    default already resolved (so nothing downstream re-decides a default)."""
    if not isinstance(body, dict):
        return None, "bad request body"
    engine = body.get("engine")
    if not isinstance(engine, str) or engine.strip() not in ENGINES:
        return None, f"unknown engine — pick one of: {', '.join(ENGINES)}"
    engine = engine.strip()
    if engine not in set(installed_engines or ()):
        return None, f"{engine} is not installed yet — install it from the Music page"

    prompt = body.get("prompt")
    prompt = prompt.strip() if isinstance(prompt, str) else ""
    if not prompt:
        return None, "describe the music you want (the prompt cannot be empty)"
    if len(prompt) > PROMPT_MAX:
        return None, f"the prompt is too long (max {PROMPT_MAX} characters)"

    lyrics = body.get("lyrics")
    lyrics = lyrics if isinstance(lyrics, str) else ""
    if len(lyrics) > LYRICS_MAX:
        return None, f"the lyrics are too long (max {LYRICS_MAX} characters)"

    # ABSENT and JUNK are different answers: an omitted length means "use the
    # default", a length of "soon" is a mistake and must be said out loud.
    raw_secs = body.get("seconds")
    if raw_secs in (None, ""):
        seconds = SECONDS_DEFAULT
    else:
        seconds = _as_int(raw_secs, None)
    if seconds is None or seconds < SECONDS_MIN or seconds > SECONDS_MAX:
        return None, f"length must be between {SECONDS_MIN} and {SECONDS_MAX} seconds"

    steps = body.get("steps")
    steps = DEFAULT_STEPS[engine] if steps in (None, "") else _as_int(steps, None)
    if steps is None or steps < 1 or steps > MAX_STEPS[engine]:
        return None, f"steps must be between 1 and {MAX_STEPS[engine]} for {engine}"

    raw_seed = body.get("seed")
    if raw_seed in (None, ""):
        # A render with no seed is unreproducible, so MOT Deck picks one and
        # RECORDS it in the sidecar rather than leaving the engine's default unknown.
        seed = random.randint(0, SEED_MAX)
        seed_given = False
    else:
        seed = _as_int(raw_seed, None)
        if seed is None or seed < 0 or seed > SEED_MAX:
            return None, f"seed must be a whole number between 0 and {SEED_MAX}"
        seed_given = True

    fmt = body.get("format")
    allowed = ENGINE_FORMATS.get(engine, ("wav",))
    if fmt in (None, ""):
        fmt = DEFAULT_FORMAT.get(engine, "wav")
    elif not isinstance(fmt, str) or fmt.strip() not in allowed:
        return None, (f"{engine} can write: {', '.join(allowed)}")
    else:
        fmt = fmt.strip()

    return {"engine": engine, "prompt": prompt, "lyrics": lyrics,
            "seconds": int(seconds), "steps": int(steps), "seed": int(seed),
            "seed_given": bool(seed_given), "format": fmt}, None


# ── engine command builders (PURE) ───────────────────────────────────────────
def minimax_cmd(py: str, snapshot: str, params: dict, lyrics_file: str, out: str) -> dict:
    """PURE: everything needed to run the MLX port correctly out of an HF snapshot.

    Returns {argv, cwd, env}: `cwd` and the PYTHONPATH in `env` and the explicit
    `--model-dir` are the three halves of the symlink-farm fix (see module docstring)
    — on a real-file layout they are simply the values Python would have computed.
    """
    argv = [str(py), "generate.py",
            "--prompt", params["prompt"],
            "--seconds", str(int(params["seconds"])),
            "--steps", str(int(params["steps"])),
            "--seed", str(int(params["seed"])),
            "--model-dir", str(snapshot),
            "--output", str(out)]
    if params.get("lyrics", "").strip():
        argv[2:2] = ["--lyrics-file", str(lyrics_file)]
    else:
        # ⚠️ BUG FIXED 2026-08-20, found by reading generate.py at the pin: the lyrics
        # arguments are an argparse mutually-exclusive group with required=True, so
        # passing NEITHER is an immediate usage error — every instrumental minimax
        # render would have failed before touching the GPU. The port's own help text
        # names the answer: "use [Instrumental] for no vocals".
        argv[2:2] = ["--lyrics", MINIMAX_INSTRUMENTAL]
    return {"argv": argv, "cwd": str(snapshot),
            "env": {"PYTHONPATH": str(snapshot)}}


def acestep_request(params: dict) -> dict:
    """PURE: the AceRequest JSON (docs/ARCHITECTURE.md shapes, as the measurement
    prototype used them). `duration` is float SECONDS; `lyrics` is the single source
    of truth for vocals; `output_format` is a JSON field with no CLI flag."""
    fmt = params.get("format") or DEFAULT_FORMAT["acestep"]
    if fmt not in ACESTEP_FORMATS:
        fmt = DEFAULT_FORMAT["acestep"]
    return {
        "caption": params["prompt"],
        "lyrics": params.get("lyrics", "") or "",
        "duration": float(params["seconds"]),
        "seed": int(params["seed"]),
        "inference_steps": int(params["steps"]),
        "output_format": fmt,
    }


def ace_argv(binary: str, models: str, request_path: str) -> list:
    """PURE: both stages take the same three arguments — only the binary and the
    request file differ (ace-synth is handed ace-lm's <stem>0.json)."""
    return [str(binary), "--models", str(models), "--request", str(request_path)]


def ace_stage2_request(request_path: str) -> str:
    """PURE: ace-lm writes `<stem>0.json` beside its input; that file is ace-synth's
    request. (ace-synth then renders `<stem>00.<ext>` beside THAT.)"""
    base, ext = os.path.splitext(str(request_path))
    return base + "0" + (ext or ".json")


def render_ok(path) -> bool:
    """The ONLY success signal (the voice lane's invariant, carried over): the audio
    exists and is non-empty. An exit code is never trusted on its own."""
    try:
        return bool(path) and os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def track_name(engine: str, when=None, fmt: str = "") -> str:
    t = time.localtime(when if when is not None else time.time())
    ext = FORMAT_EXT.get(fmt or "", ".wav")
    return f"{engine}-{time.strftime('%Y%m%d-%H%M%S', t)}{ext}"


# ── templates ────────────────────────────────────────────────────────────────
# Six starters. They exist because the single biggest quality lever on both engines
# is the CAPTION, and a blank textarea teaches nobody what a good one looks like:
# these are written in the structured style the models were trained to read (genre,
# tempo, key, instrumentation, vocal character, section-by-section arrangement, mix),
# long enough to be worth reading and short enough to edit. Clicking one PREFILLS the
# form — it never generates by itself.
#
# Every built-in is asserted (in the tests) to pass `validate_generate` unchanged, so
# a starter can never be a request the bridge would refuse.
MUSIC_TEMPLATES = (
    {
        "id": "neo-soul",
        "name": "Neo-soul / R&B ballad",
        "tag": "vocal · 72 BPM",
        "seconds": 90,
        "prompt": (
            "Warm modern neo-soul R&B ballad at 72 BPM in D minor, swung sixteenths, "
            "intimate and unhurried. Foundation is a soft Rhodes electric piano with a "
            "slow tremolo and long sustain, played in loose extended voicings — ninths, "
            "elevenths, the occasional passing diminished. Underneath it a round, "
            "fretless-feeling electric bass sits deep in the pocket, sliding into the "
            "root a fraction behind the beat. Drums are brushed and dry: a soft rimshot "
            "backbeat, ghost notes on the snare, a closed hi-hat with real human drift, "
            "no click-track stiffness. Lead vocal is a smooth female alto, breathy in "
            "the low register and opening into a controlled belt at the top, with light "
            "vocal fry on phrase ends and a small amount of plate reverb. Stacked "
            "three-part background harmonies answer the lead in the chorus. "
            "Arrangement: the intro is Rhodes and voice alone for four bars; the first "
            "verse adds bass and brushes; the pre-chorus lifts with a sustained analog "
            "string pad and a rising bass fill; the chorus opens fully with harmonies, "
            "a tambourine on the offbeats and a muted trumpet doubling the melody an "
            "octave down; the bridge drops back to Rhodes and one voice before the last "
            "chorus returns with an improvised ad-lib line over the top. Ending is a "
            "ritardando into a single held chord. Mix is warm and analog — gentle tape "
            "saturation, rolled-off highs, wide stereo keys, vocal centred and forward."
        ),
        "lyrics": (
            "[Verse]\n"
            "Streetlight on the kitchen floor\n"
            "I stopped counting hours ago\n"
            "You said stay, I said maybe more\n"
            "and the coffee went cold and slow\n\n"
            "[Chorus]\n"
            "Hold it, hold it, don't let the morning in\n"
            "we're still somewhere the night has never been\n"
            "hold it, hold it, I'll take the quiet part\n"
            "as long as you keep the light on in your heart\n\n"
            "[Verse]\n"
            "Every song I never sent\n"
            "still knows the way back to your door\n"
            "and I'd spend it all again\n"
            "just to hear you laugh once more\n\n"
            "[Bridge]\n"
            "Nothing gold ever asked to stay\n"
            "but it never asked to leave\n\n"
            "[Chorus]\n"
            "Hold it, hold it, don't let the morning in\n"
            "we're still somewhere the night has never been"
        ),
    },
    {
        "id": "rock",
        "name": "Driving rock",
        "tag": "vocal · 148 BPM",
        "seconds": 90,
        "prompt": (
            "High-energy modern rock at 148 BPM in E minor, straight eighths, loud and "
            "forward-leaning. Two electric guitars: a crunchy rhythm part playing "
            "palm-muted power chords hard left, and a brighter, slightly overdriven "
            "second guitar hard right playing an open ringing riff built on the root and "
            "the flat seventh. Bass is a picked P-bass with a light distortion, locked to "
            "the kick and driving eighth notes. Drums are live and roomy — a punchy kick, "
            "a cracking snare with real room ambience, ride bell accents in the chorus, "
            "a full tom fill into each section change. Lead vocal is a gritty male tenor "
            "with a strained, honest edge at the top of his range, doubled in the chorus "
            "and shouted gang vocals on the hook. "
            "Arrangement: a four-bar guitar riff intro with no drums, then a full-band "
            "hit into verse one; the verse is sparse — muted guitar, bass and hats — so "
            "the chorus can explode; the pre-chorus builds with a snare roll and a "
            "sustained feedback note; the chorus is wide, loud and anthemic; after the "
            "second chorus a short half-time breakdown drops to bass and a single "
            "delayed guitar before a lead guitar solo over the chorus changes; the final "
            "chorus repeats twice with an extra harmony guitar line and ends on a hard "
            "stop. Mix is aggressive and modern — tight low end, mid-forward guitars, "
            "vocal sitting on top, real dynamics between sections."
        ),
        "lyrics": (
            "[Verse]\n"
            "Kick the door, the engine's already running\n"
            "I've got nothing left to leave behind\n"
            "half a map and a radio humming\n"
            "and a head that won't make up its mind\n\n"
            "[Pre-Chorus]\n"
            "One more mile, one more mile\n\n"
            "[Chorus]\n"
            "Burn it down, burn it down, I'm not turning around\n"
            "every road I ever hated brought me here\n"
            "burn it down, burn it down, let 'em hear the sound\n"
            "of a heart that finally got out of gear\n\n"
            "[Verse]\n"
            "Rearview full of everything I promised\n"
            "and the horizon doesn't care what I said\n\n"
            "[Chorus]\n"
            "Burn it down, burn it down, I'm not turning around\n"
            "every road I ever hated brought me here"
        ),
    },
    {
        "id": "lofi",
        "name": "Lo-fi study beat",
        "tag": "instrumental · 82 BPM",
        "seconds": 120,
        "prompt": (
            "Instrumental lo-fi hip-hop study beat at 82 BPM in F major, no vocals at "
            "all, endlessly loopable and deliberately undramatic. A dusty sampled jazz "
            "piano plays a four-chord loop — major seventh, minor ninth, dominant "
            "thirteenth, back home — slightly detuned and wowing as if from an old tape. "
            "Drums are a soft boom-bap kit: a rounded kick, a dry rimshot on two and "
            "four, lazy shuffled hi-hats behind the beat, occasional vinyl-crackle "
            "sixteenth ghost notes. An upright double bass walks quietly underneath with "
            "finger noise audible. A muted trumpet plays a short, sleepy motif every "
            "eight bars and then leaves. Continuous background texture: vinyl surface "
            "noise, faint rain against a window, and a low tape hiss that never resolves. "
            "Arrangement: eight bars of piano and crackle alone, then drums enter; the "
            "trumpet motif appears at bar sixteen; a filtered break at the halfway point "
            "removes the drums for four bars and brings them back with a soft filter "
            "sweep; the last section strips back to piano and rain. Mix is warm, dark "
            "and quiet — high frequencies rolled off, everything gently compressed and "
            "glued, nothing sharp or attention-grabbing anywhere."
        ),
        "lyrics": "",
    },
    {
        "id": "cinematic",
        "name": "Cinematic orchestral",
        "tag": "instrumental · builds",
        "seconds": 120,
        "prompt": (
            "Instrumental cinematic orchestral cue in C minor, no vocals, starting at a "
            "slow 68 BPM and pushing to about 96 BPM by the climax. Opens with a single "
            "solo cello playing a plain, mournful four-note theme with plenty of air "
            "around it in a large hall. A sustained low string bed fades in underneath, "
            "then a delicate celesta doubling the theme two octaves up. Strings build in "
            "layers — violas, then second violins, then firsts — each entry adding one "
            "more voice to the harmony rather than more volume. A soft ostinato of "
            "pizzicato strings and staccato piano establishes forward motion. French "
            "horns state the theme in unison at the two-thirds point, answered by "
            "trumpets a fourth above. Percussion arrives late and deliberately: a taiko "
            "pulse on the downbeats, then a rolling timpani crescendo, then cymbal swells "
            "on each section change. "
            "Arrangement: quiet, lonely statement of the theme; a patient two-minute "
            "build where every eight bars adds one instrument family; a sudden full stop "
            "of everything but the solo cello; then the full orchestral climax with brass "
            "carrying the melody, strings running countermelody sixteenths and a choir-"
            "like wordless string pad behind; a long decay back to the solo cello and "
            "silence. Mix is wide, deep and natural — real hall reverb, generous dynamic "
            "range, no modern loudness compression."
        ),
        "lyrics": "",
    },
    {
        "id": "edm",
        "name": "EDM / dance",
        "tag": "vocal hook · 126 BPM",
        "seconds": 90,
        "prompt": (
            "Bright melodic house / dance track at 126 BPM in A minor, four-on-the-floor, "
            "made for a big room and a late summer night. Punchy sidechained kick with a "
            "short click transient, clap layered with a bright snare on two and four, "
            "open hi-hat on every offbeat, shaker sixteenths riding through. Bass is a "
            "round analog sine with a small amount of saturation, pumping hard against "
            "the kick. Lead is a plucked, delayed synth arpeggio in sixteenths with a "
            "long ping-pong delay and a filter that opens slowly across each eight-bar "
            "phrase. A wide supersaw chord stack carries the harmony in the drop, with a "
            "warm analog pad underneath. Female vocal hook, processed and airy, heavily "
            "reverbed, chopped and repeated as a rhythmic element rather than a lead. "
            "Arrangement: filtered intro with just the arp and a rising white-noise "
            "sweep; the beat drops in at bar nine; the verse keeps the kick and bass "
            "minimal so the vocal has room; the build strips the kick, adds a snare roll "
            "doubling in speed, a rising riser and a one-bar silence; the drop is the "
            "full supersaw stack with the vocal hook chopped over it; a second breakdown "
            "goes almost ambient — pad and reversed vocal only — before the final drop. "
            "Mix is loud, clean and modern: tight low end, glossy top, huge stereo width "
            "on the synths, everything mono-safe at the bottom."
        ),
        "lyrics": (
            "[Chorus]\n"
            "Hold on, we're never coming down\n"
            "hold on, we're never coming down\n"
            "hold on\n\n"
            "[Verse]\n"
            "Neon on the water, half past two\n"
            "nothing in the morning I have to do\n\n"
            "[Chorus]\n"
            "Hold on, we're never coming down\n"
            "hold on, we're never coming down"
        ),
    },
    {
        "id": "folk",
        "name": "Acoustic folk ballad",
        "tag": "vocal · 88 BPM",
        "seconds": 90,
        "prompt": (
            "Intimate acoustic folk ballad at 88 BPM in G major, 6/8 feel, recorded to "
            "sound like four people in one small room. Main instrument is a "
            "steel-string acoustic guitar fingerpicked in a rolling pattern, capo "
            "audible, string squeaks and fret noise left in. A second acoustic strums "
            "quietly an octave up on the choruses. Upright bass plays simple root-fifth "
            "movement with a woody, unamplified tone. Percussion is minimal and organic: "
            "a brushed snare, a stomp on the downbeat, and a shaker that enters only in "
            "the second half. A fiddle plays a plaintive countermelody between vocal "
            "lines and takes a short solo before the last verse; a pedal steel adds long "
            "swells underneath the chorus. Lead vocal is a warm male baritone singing "
            "close to the microphone, conversational rather than performed, with a "
            "natural crack on the held notes; a female harmony joins a third above from "
            "the second chorus onward. "
            "Arrangement: solo guitar and voice for the first verse; bass and brushes "
            "join the first chorus; fiddle enters in verse two; the bridge drops to two "
            "voices and one guitar with no rhythm at all; the last chorus has everyone "
            "in, ending on a single strummed chord left to ring out. Mix is dry, close "
            "and honest — very little reverb, no compression pumping, real room tone "
            "audible between phrases."
        ),
        "lyrics": (
            "[Verse]\n"
            "My father built this table out of pine\n"
            "and swore it would outlast us all\n"
            "there's a knot in it that looks like nineteen-ninety-nine\n"
            "and a scar from a autumn I don't recall\n\n"
            "[Chorus]\n"
            "So carry me home the long way\n"
            "past the field and the flooded lane\n"
            "I'll take the miles if you'll take the songs\n"
            "and we'll call it even again\n\n"
            "[Verse]\n"
            "My mother kept the letters in a tin\n"
            "every one of them addressed but never sent\n\n"
            "[Bridge]\n"
            "Nothing here was built to last\n"
            "and everything here still stands\n\n"
            "[Chorus]\n"
            "So carry me home the long way\n"
            "past the field and the flooded lane"
        ),
    },
)

TEMPLATE_NAME_MAX = 60


def builtin_templates() -> list:
    """Copies, always: a caller must never be able to mutate the table."""
    return [dict(t, builtin=True) for t in MUSIC_TEMPLATES]


def templates_path(root) -> str:
    return os.path.join(music_base_dir(root), TEMPLATES_FILE)


def validate_template(body) -> tuple:
    """PURE: (template, error). A saved template is just a remembered form."""
    if not isinstance(body, dict):
        return None, "bad request body"
    name = body.get("name")
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        return None, "give the template a name"
    if len(name) > TEMPLATE_NAME_MAX:
        return None, f"the name is too long (max {TEMPLATE_NAME_MAX} characters)"
    prompt = body.get("prompt")
    prompt = prompt.strip() if isinstance(prompt, str) else ""
    if not prompt:
        return None, "a template needs a prompt"
    if len(prompt) > PROMPT_MAX:
        return None, f"the prompt is too long (max {PROMPT_MAX} characters)"
    lyrics = body.get("lyrics") if isinstance(body.get("lyrics"), str) else ""
    if len(lyrics) > LYRICS_MAX:
        return None, f"the lyrics are too long (max {LYRICS_MAX} characters)"
    secs = _as_int(body.get("seconds"), SECONDS_DEFAULT)
    if secs is None or secs < SECONDS_MIN or secs > SECONDS_MAX:
        secs = SECONDS_DEFAULT
    steps = _as_int(body.get("steps"), None)
    engine = body.get("engine")
    engine = engine if isinstance(engine, str) and engine in ENGINES else ""
    t = {"id": "u" + f"{int(time.time() * 1000):x}", "name": name, "tag": "yours",
         "prompt": prompt, "lyrics": lyrics, "seconds": int(secs), "builtin": False}
    if steps is not None:
        t["steps"] = int(steps)
    if engine:
        t["engine_hint"] = engine
    return t, None


def user_templates(root) -> list:
    try:
        with open(templates_path(root), encoding="utf-8") as fh:
            loaded = json.load(fh)
    except Exception:                                            # noqa: BLE001
        return []
    if not isinstance(loaded, list):
        return []
    out = []
    for t in loaded:
        if isinstance(t, dict) and isinstance(t.get("id"), str) and t.get("prompt"):
            out.append(dict(t, builtin=False))
    return out


def _write_user_templates(root, items) -> None:
    p = templates_path(root)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(items, fh, indent=2)
    os.replace(tmp, p)


def all_templates(root) -> list:
    """Built-ins first, then the user's own — the starters are the teaching material
    and should not be pushed off the strip by a growing personal collection."""
    return builtin_templates() + user_templates(root)


def save_template(root, body) -> tuple:
    t, err = validate_template(body)
    if err:
        return None, err
    items = [dict(x) for x in user_templates(root)]
    items.append(t)
    try:
        _write_user_templates(root, items)
    except OSError as e:
        return None, f"could not save: {e}"
    return t, None


def delete_template(root, tid) -> tuple:
    """(ok, reason). A BUILT-IN can never be deleted — it is code, not data, and a
    delete that appeared to work and came back on restart would be a lie."""
    if not isinstance(tid, str) or not tid.strip():
        return False, "no template given"
    tid = tid.strip()
    if any(t["id"] == tid for t in MUSIC_TEMPLATES):
        return False, "the starter templates cannot be deleted"
    items = [dict(x) for x in user_templates(root)]
    keep = [x for x in items if x.get("id") != tid]
    if len(keep) == len(items):
        return False, "no such template"
    try:
        _write_user_templates(root, keep)
    except OSError as e:
        return False, f"could not save: {e}"
    return True, ""


# ── progress + ETA ───────────────────────────────────────────────────────────
# Two independent, honest sources. (a) the engines' OWN progress lines, tailed out of
# the job log; (b) an estimate fitted to what renders have actually cost on THIS
# machine. (a) is used when it exists, (b) always drives the "time left" figure.
#
# What the engines actually print, read at the pins rather than guessed:
#   minimax  generate.py's `progress(stage, msg)` prints "[N/5] message" for BOTH
#            phases: the pipeline constructor emits 1,2,3 ("Loading … into MLX…") and
#            then .generate() RESTARTS at 1 and emits 1,2,4,5 ("Generating…",
#            "Sampling…", "Decoding…", "Writing…"). There is NO step-count bar at all —
#            the flow loop prints nothing per step. Taking a global maximum across
#            those two runs is what froze the bar at 0.60; see progress_scan.
#   acestep  ace-lm / ace-synth print their own step counters; the generic "N/M" and
#            tqdm "NN%|" forms below cover both without pinning either engine's
#            exact wording (which we do not own).
#
# The phase vocabulary. SETUP is tested FIRST in counter_kind because minimax's third
# loader line literally contains the word "decoder".
SETUP_WORDS = ("load", "download", "fetch", "resolv", "shard", "weight",
               "warm", "init", "compil", "prepar")
RENDER_WORDS = ("generat", "sampl", "decod", "denois", "step", "diffus",
                "synth", "writ", "render", "infer")
_PCT_RE = None
_FRAC_RE = None


def _progress_res():
    global _PCT_RE, _FRAC_RE
    if _PCT_RE is None:
        import re
        _PCT_RE = re.compile(r"(\d{1,3})%\s*\|")
        _FRAC_RE = re.compile(r"\[?\s*(\d{1,6})\s*/\s*(\d{1,6})\s*[\]\s]")
    return _PCT_RE, _FRAC_RE


def _counters(text, pct_re, frac_re):
    """PURE: every progress counter in the log, in order — (frac, total, message)."""
    out = []
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line:
            continue
        f, total, m = None, None, None
        m = pct_re.search(line)
        if m:
            try:
                f = min(1.0, max(0.0, int(m.group(1)) / 100.0))
            except ValueError:
                f, m = None, None
        if f is None:
            m = frac_re.search(line + " ")
            if m:
                try:
                    a, b = int(m.group(1)), int(m.group(2))
                except ValueError:
                    a, b = 0, 0
                if b > 0 and 0 <= a <= b:
                    f, total = a / b, b
                else:
                    m = None
        if f is None:
            continue
        # a tqdm bar often carries "9/20" AFTER the percentage — that total is the one
        # the step-count rule needs, so look for it on the same line
        if total is None:
            fm = frac_re.search(line + " ")
            if fm:
                try:
                    b = int(fm.group(2))
                    if b > 0:
                        total = b
                except ValueError:
                    pass
        out.append((f, total, line[m.end():].strip(" :|\t") if m else ""))
    return out


def counter_kind(total, message, steps, previous) -> str:
    """PURE: is this counter the SETUP phase or the RENDER phase?

    THE NUMERIC RULE FIRST (Fable's): a bar whose total is the requested step count is
    the render, whatever it calls itself. Then the vocabulary, and **setup is tested
    before render on purpose** — minimax's loader line is "Loading MiniMax-Music3 DAV
    *decoder* into MLX…", which contains "decod" and would otherwise read as render.
    An unrecognised counter INHERITS the previous kind rather than inventing one.
    """
    try:
        want = int(steps) if steps not in (None, "") else None
    except (TypeError, ValueError):
        want = None
    if want and total and int(total) == want:
        return "render"
    msg = str(message or "").lower()
    if any(w in msg for w in SETUP_WORDS):
        return "setup"
    if any(w in msg for w in RENDER_WORDS):
        return "render"
    return previous or "setup"


def progress_scan(text, steps=None) -> dict:
    """PURE: {kind, frac, phase} — the phase-aware read of a live engine log.

    ⚠️ THE BUG THIS REPLACES, root-caused from the pinned sources rather than guessed.
    `generate.py` prints EVERY stage as "[N/5] message" through one `progress()`
    helper, and `MiniMaxMusic3MlxPipeline.__init__` uses it for the three weight loads
    (1,2,3) while `.generate()` RESTARTS at 1 (1,2,4,5). v1 took a global MAXIMUM, so
    the moment "[3/5] Loading … DAV decoder into MLX…" printed, the bar pinned at 0.60
    and the phase text froze on that line for the whole render — exactly what sample saw
    ("shoots to about half and sticks", "stuck on Loading … decoder").

    The fix is to segment: a counter that goes BACKWARDS starts a new segment, and only
    the LAST segment of the dominant phase is read. Within a segment the maximum still
    wins, so a bar never travels backwards inside one phase.
    """
    if not isinstance(text, str) or not text.strip():
        return {"kind": "", "frac": None, "phase": ""}
    pct_re, frac_re = _progress_res()
    kind, segs = "", {"setup": None, "render": None}
    saw_render = False
    for f, total, msg in _counters(text, pct_re, frac_re):
        kind = counter_kind(total, msg, steps, kind)
        if kind == "render":
            saw_render = True
        seg = segs.get(kind)
        if seg is None or f < seg["last"]:
            seg = {"max": f, "last": f, "phase": msg}
        else:
            seg = {"max": max(seg["max"], f), "last": f,
                   "phase": msg or seg["phase"]}
        segs[kind] = seg
    want = "render" if saw_render else "setup"
    seg = segs.get(want)
    if seg is None:
        return {"kind": "", "frac": None, "phase": ""}
    return {"kind": want, "frac": seg["max"], "phase": str(seg["phase"])[:120]}


def parse_progress(text, steps=None) -> tuple:
    """PURE: (fraction 0..1 or None, phase text) — the phase-local reading, kept as the
    small surface the older callers and tests use. Total over junk: this reads a file
    written by two third-party engines, so anything at all can be in it."""
    s = progress_scan(text, steps)
    return s["frac"], s["phase"]


def overall_progress(scan, elapsed) -> "float | None":
    """PURE: one 0..1 number for the whole job, from the phase-aware scan.

    SETUP DELIBERATELY IGNORES ITS OWN COUNTER. "3 of 5 files loaded" says nothing
    about seconds — a 12 GB int8 checkpoint is three loads of wildly different cost —
    so the first SETUP_SHARE of the bar rides elapsed against a fixed allowance and
    simply stops there until the render actually starts.
    """
    try:
        el = max(0.0, float(elapsed or 0.0))
    except (TypeError, ValueError):
        el = 0.0
    kind = (scan or {}).get("kind") if isinstance(scan, dict) else None
    frac = (scan or {}).get("frac") if isinstance(scan, dict) else None
    if kind == "render" and isinstance(frac, (int, float)):
        f = min(1.0, max(0.0, float(frac)))
        return SETUP_SHARE + (1.0 - SETUP_SHARE) * f
    ramp = SETUP_SHARE * (el / SETUP_ALLOWANCE_S) if SETUP_ALLOWANCE_S > 0 else SETUP_SHARE
    return min(SETUP_SHARE, max(0.0, ramp))


def remaining_secs(elapsed, progress, estimate) -> "float | None":
    """PURE: seconds still to go, or None when we cannot honestly say.

    None is a real answer and the panel prints it as "taking longer than estimated".
    The alternative is what sample was shown: "~1m 32s left" on a render that had already
    been going for twelve minutes, because the total estimate was simply wrong and the
    panel subtracted elapsed from it anyway.
    """
    try:
        el = max(0.0, float(elapsed or 0.0))
    except (TypeError, ValueError):
        el = 0.0
    try:
        est = float(estimate) if estimate else None
    except (TypeError, ValueError):
        est = None
    r_est = (est - el) if est is not None else None
    if r_est is not None and r_est < 0:
        r_est = None                      # the estimate is spent; it can claim nothing
    try:
        p = float(progress) if progress else 0.0
    except (TypeError, ValueError):
        p = 0.0
    r_meas = (el * (1.0 - p) / p) if (p > 0.02 and el > 0) else None
    if r_meas is None:
        return None if r_est is None else round(r_est, 1)
    if r_est is None:
        return round(max(0.0, r_meas), 1)
    w = min(1.0, p / ETA_TRUST_AT) if ETA_TRUST_AT > 0 else 1.0
    return round(max(0.0, w * r_meas + (1.0 - w) * r_est), 1)


def estimate_wall(engine, seconds, history=None):
    """PURE: seconds of wall clock this render is likely to cost, or None.

    Points, not a rate: minimax is markedly SUPERLINEAR (60s of song → 115s, 145s →
    676s), so dividing by length would under-promise badly at the long end. With two
    points around the request we interpolate; outside the range, or with one point,
    we scale that nearest point proportionally and accept that it under-estimates a
    very long minimax render — the UI says "estimated" for exactly this reason.
    """
    try:
        want = float(seconds)
    except (TypeError, ValueError):
        return None
    if want <= 0:
        return None
    pts = []
    for h in (history or ()):
        if not isinstance(h, dict) or h.get("engine") != engine:
            continue
        try:
            s, w = float(h.get("seconds")), float(h.get("wall"))
        except (TypeError, ValueError):
            continue
        if s > 0 and w > 0:
            pts.append((s, w))
    if not pts:
        pts = [(float(s), float(w)) for s, w in MUSIC_CALIBRATION.get(engine, ())]
    if not pts:
        return None
    exact = [w for s, w in pts if s == want]
    if exact:
        return round(sum(exact) / len(exact), 1)
    pts.sort()
    fit = power_fit(pts)
    if fit is not None:
        a, b = fit
        try:
            return round(a * (want ** b), 1)
        except (OverflowError, ValueError):
            pass
    # ONE point only: proportional is all the evidence supports.
    below = [p for p in pts if p[0] < want]
    above = [p for p in pts if p[0] > want]
    s, w = (below[-1] if below else above[0])
    return round(w * want / s, 1)


# Exponents outside this band are a noisy library, not a real curve — a 220s render
# must not be predicted at four hours because two odd rows sat next to each other.
POWER_B_MIN, POWER_B_MAX = 0.6, 3.0


def power_fit(points) -> "tuple | None":
    """PURE: least squares in LOG-LOG space → (a, b) for wall = a·seconds^b, or None.

    ⚠️ WHY NOT PROPORTIONAL (the v1.1 bug): minimax is markedly superlinear — 60s of
    song cost 115.5s and 145s cost 675.6s, an exponent of ~2.0 — so scaling the nearest
    point by length under-promises badly at the long end. On sample's 220s render the old
    rule predicted ~17 minutes and the render was still going at 13; the fit predicts
    ~26. Two points give an exact fit; more give a real regression.
    """
    pts = [(float(s), float(w)) for s, w in (points or ())
           if isinstance(s, (int, float)) and isinstance(w, (int, float))
           and s > 0 and w > 0]
    xs = sorted({s for s, _ in pts})
    if len(xs) < 2:
        return None
    n = len(pts)
    lx = [math.log(s) for s, _ in pts]
    ly = [math.log(w) for _, w in pts]
    mx_, my = sum(lx) / n, sum(ly) / n
    den = sum((x - mx_) ** 2 for x in lx)
    if den <= 0:
        return None
    b = sum((lx[i] - mx_) * (ly[i] - my) for i in range(n)) / den
    b = max(POWER_B_MIN, min(POWER_B_MAX, b))
    try:
        a = math.exp(my - b * mx_)
    except OverflowError:
        return None
    if not (a > 0) or not math.isfinite(a):
        return None
    return a, b


def progress_view(job, log_text="", history=None, now=None) -> dict:
    """The read side of a running render:
    {progress, phase, phase_kind, elapsed_s, eta_s, remaining_s, source}.

    `progress` is CAPPED at 0.95 while the job runs — both engines finish with a
    decode-and-write phase their own counters never mention, and a bar that sits at
    100% while the user waits is worse than one that sits at 95%."""
    blank = {"progress": None, "phase": "", "phase_kind": "", "elapsed_s": 0.0,
             "eta_s": None, "remaining_s": None, "source": ""}
    if not isinstance(job, dict):
        return dict(blank)
    eta = estimate_wall(job.get("engine"), job.get("seconds"), history)
    running = job.get("state") in ("queued", "running")
    if not running:
        out = dict(blank)
        out["progress"] = 1.0 if job.get("state") == "done" else None
        out["eta_s"] = eta
        return out
    try:
        el = max(0.0, (now if now is not None else time.time())
                 - float(job.get("started") or 0))
    except (TypeError, ValueError):
        el = 0.0
    scan = progress_scan(log_text, job.get("steps"))
    raw = overall_progress(scan, el)
    source = "engine" if scan.get("kind") == "render" else "estimate"
    return {"progress": None if raw is None else round(min(raw, PROGRESS_DISPLAY_CAP), 4),
            "phase": scan.get("phase") or "", "phase_kind": scan.get("kind") or "",
            "elapsed_s": round(el, 1), "eta_s": eta,
            "remaining_s": remaining_secs(el, raw, eta), "source": source}


# ── library ──────────────────────────────────────────────────────────────────
def sidecar_path(wav_path: str) -> str:
    return os.path.splitext(str(wav_path))[0] + ".json"


# A TRACK'S NAME IS NOT ITS FILENAME (Compose slice, 2026-08-29). `minimax-20260820-
# 235921.wav` is a timestamp, not a name — the human identity of a song is what the
# person who made it calls it. So a title lives in the SIDECAR and the file on disk is
# never renamed: a rename would make the library and the folder disagree the moment one
# half failed, and would break every path a user already has (a converted sibling, a
# Finder alias, a playlist). The filename stays the file's truth and is shown as
# provenance; the title is the identity the surfaces display.
TITLE_MAX = 120


def set_track_title(root, name, title) -> tuple:
    """(ok, reason). Writes — or clears — one track's display title in its sidecar.

    Containment is `library_target`'s, the same single boundary /file and /delete use,
    so a title can never be written outside the music folder. The sidecar is per-STEM,
    so song.wav and song.mp3 (its convert sibling) share one title, which is correct:
    they are one song in two containers.
    """
    target, reason = library_target(root, name)
    if not target:
        return False, reason
    if title is None:
        title = ""
    if not isinstance(title, str):
        return False, "a title is text"
    title = " ".join(title.split())            # no newlines, no runs of spaces
    if len(title) > TITLE_MAX:
        return False, f"a title can be at most {TITLE_MAX} characters"
    p = sidecar_path(target)
    meta = {}
    try:
        with open(p, encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            meta = loaded
    except Exception:                                            # noqa: BLE001
        meta = {}                  # a track whose sidecar was lost can still be named
    if title:
        meta["title"] = title
    else:
        meta.pop("title", None)    # empty = back to having no title of its own
    try:
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)
    except OSError as e:
        return False, f"could not write the title: {e}"
    return True, ""


def library_entries(root) -> list:
    """Every finished song, newest first, each married to its sidecar metadata.
    A wav with no sidecar is still listed (the file is real; only its provenance is
    unknown) — losing a track because its metadata went missing would be worse."""
    d = music_dir(root)
    out = []
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for n in names:
        if not n.lower().endswith(LIBRARY_EXTS):
            continue
        p = os.path.join(d, n)
        if not os.path.isfile(p):
            continue
        try:
            st = os.stat(p)
        except OSError:
            continue
        meta = {}
        try:
            with open(sidecar_path(p), encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                meta = loaded
        except Exception:                                        # noqa: BLE001
            meta = {}
        out.append({
            "name": n,
            # The human identity, when the user has given one (Compose). Absent = the
            # surfaces fall back to the prompt and then to the filename; the filename
            # itself is always carried, so nothing displays a name the disk denies.
            "title": (meta.get("title") or "") if isinstance(meta, dict) else "",
            "ext": os.path.splitext(n)[1].lower().lstrip("."),
            "size_bytes": st.st_size,
            "created": st.st_mtime,
            "engine": meta.get("engine") or "",
            "prompt": meta.get("prompt") or "",
            "lyrics": meta.get("lyrics") or "",
            "seconds": meta.get("seconds"),
            "steps": meta.get("steps"),
            "seed": meta.get("seed"),
            "wall": meta.get("wall"),
            "path": p,
        })
    out.sort(key=lambda e: e["created"], reverse=True)
    return out


def library_target(root, name):
    """(wav_path, None) or (None, reason) — the ONE boundary for /file and /delete.

    Basename-only + realpath containment strictly under data/music, exactly the
    `_deletable_target` discipline: the name comes from a request, so no traversal,
    no symlink escape, no directory, .wav only.
    """
    if not isinstance(name, str) or not name.strip():
        return None, "no track name given"
    name = name.strip()
    if name != os.path.basename(name) or name in (".", ".."):
        return None, "refused: a track is addressed by name, not by path"
    if os.sep in name or "/" in name or "\\" in name or name.startswith("."):
        return None, "refused: a track is addressed by name, not by path"
    if not name.lower().endswith(LIBRARY_EXTS):
        return None, "refused: only audio tracks (" + ", ".join(LIBRARY_EXTS) + ")"
    root_real = os.path.realpath(music_dir(root))
    target = os.path.realpath(os.path.join(root_real, name))
    if not target.startswith(root_real + os.sep):
        return None, "refused: that path is outside the music folder"
    if not os.path.isfile(target):
        return None, "no such track"
    return target, None


def delete_track(root, name) -> tuple:
    """Delete a track and, if it was the LAST audio file of its stem, its sidecar.

    The stem test matters since converting arrived: song.wav and song.mp3 SHARE one
    sidecar, so deleting the mp3 must not strip the wav of its prompt and seed.
    """
    target, reason = library_target(root, name)
    if not target:
        return False, reason
    try:
        os.remove(target)
    except OSError as e:
        return False, f"could not delete: {e}"
    stem = os.path.splitext(target)[0]
    siblings = [e for e in LIBRARY_EXTS if os.path.isfile(stem + e)]
    if not siblings:
        try:
            sc = sidecar_path(target)
            if os.path.isfile(sc):
                os.remove(sc)
        except OSError:
            pass                   # the audio is gone; a stale sidecar is harmless
    return True, ""


# ══ WAVEFORM ANALYSIS (Compose v2, 2026-08-29) ═══════════════════════════════
# WHY THIS EXISTS AND WHAT IT IS ALLOWED TO CLAIM.
#
# Compose's identity is a waveform whose HUE carries information about the song's
# shape. The honest problem: NOTHING in this lane knows a song's musical structure.
# Neither engine reports sections, and a sidecar holds a prompt, a seed and a wall
# time — no arrangement at all. Painting "intro / verse / chorus" over a strip would
# be the LIES-TO-USER class: a confident label for something we never measured.
#
# So the colour is driven by the one thing we CAN measure from the file itself: the
# short-term energy envelope. The segmentation below groups the song into runs of
# similar loudness and names them by what was measured — "quiet", "steady", "loud" —
# never by a musical role. The surfaces label the result as DERIVED, and when the
# audio does not segment (a flat ambient bed, a track too short to have runs) the
# analysis says so and the page falls back to a single-hue amplitude ramp rather than
# drawing boundaries that are not there.
ANALYSIS_V = 2                    # bump = every cached analysis is recomputed
ANALYSIS_SR = 4000                # decode rate: an envelope needs no more than this
ANALYSIS_PEAKS = 480              # bars stored; the page downsamples to its width
ANALYSIS_FRAME_S = 0.25           # envelope frame
ANALYSIS_SMOOTH_S = 2.0           # moving average before segmentation
ANALYSIS_MIN_SECTION_S = 6.0      # shorter runs are merged away, never drawn
ANALYSIS_LEVELS = 3               # quiet / steady / loud
ANALYSIS_LEVEL_NAMES = ("quiet", "steady", "loud")
ANALYSIS_METHOD = "energy envelope (RMS over 0.25 s frames), derived from the audio"
ANALYSIS_TIMEOUT_S = 120
ANALYSIS_MAX_BYTES = 600_000_000  # a file bigger than this is not analysed on demand


def _pcm_from_wave(path: str) -> tuple:
    """(samples, sr) from a PCM-16 wav with the standard library alone — the path that
    still works on a machine with no ffmpeg. Anything else (24-bit, float) returns
    (None, 0) and the caller says the analysis is unavailable rather than guessing."""
    try:
        import wave                                              # noqa: PLC0415
        with wave.open(path, "rb") as fh:
            if fh.getsampwidth() != 2:
                return None, 0
            sr, ch = fh.getframerate(), fh.getnchannels()
            n = fh.getnframes()
            if not sr or not n:
                return None, 0
            raw = fh.readframes(n)
    except Exception:                                            # noqa: BLE001
        return None, 0
    import array                                                 # noqa: PLC0415
    a = array.array("h")
    a.frombytes(raw[: (len(raw) // 2) * 2])
    if sys.byteorder == "big":
        a.byteswap()
    if ch > 1:                                    # mono by taking the first channel
        a = a[::ch]
    step = max(1, int(round(sr / ANALYSIS_SR)))
    return a[::step], sr / step


def _pcm_from_ffmpeg(path: str, ffmpeg=None, run=None) -> tuple:
    """(samples, sr) by decoding through the ffmpeg the voice lane already resolves.
    One child, s16le mono at ANALYSIS_SR — cheap, and it reads every container the
    library can hold (wav 24-bit and 32-bit float, mp3, m4a)."""
    exe = ffmpeg or _ffmpeg()
    if not exe:
        return None, 0
    argv = [exe, "-v", "error", "-nostdin", "-i", path, "-map", "a:0",
            "-f", "s16le", "-ac", "1", "-ar", str(ANALYSIS_SR), "-"]
    runner = run or (lambda a: subprocess.run(
        a, capture_output=True, timeout=ANALYSIS_TIMEOUT_S, check=False))
    try:
        r = runner(argv)
    except Exception:                                            # noqa: BLE001
        return None, 0
    raw = getattr(r, "stdout", b"") or b""
    if getattr(r, "returncode", 1) != 0 or len(raw) < 4:
        return None, 0
    import array                                                 # noqa: PLC0415
    a = array.array("h")
    a.frombytes(raw[: (len(raw) // 2) * 2])
    if sys.byteorder == "big":
        a.byteswap()
    return a, ANALYSIS_SR


def envelope(samples, sr, frame_s=ANALYSIS_FRAME_S) -> list:
    """PURE. Per-frame RMS of a mono sample sequence, as a fraction of full scale."""
    if samples is None or not len(samples) or not sr:
        return []
    step = max(1, int(round(sr * frame_s)))
    out = []
    for i in range(0, len(samples), step):
        chunk = samples[i:i + step]
        if not len(chunk):
            break
        acc = 0
        for v in chunk:
            acc += v * v
        out.append(math.sqrt(acc / len(chunk)) / 32768.0)
    return out


def peak_bars(env, n=ANALYSIS_PEAKS) -> list:
    """PURE. The envelope resampled to at most n bars, normalised so the loudest bar
    is 1.0. Normalisation is per TRACK, which is honest: the bars describe this song's
    own dynamics, and the page's hover says exactly that."""
    if not env:
        return []
    n = max(8, min(int(n), max(8, len(env))))
    out = []
    for i in range(n):
        a = int(i * len(env) / n)
        b = max(a + 1, int((i + 1) * len(env) / n))
        window = env[a:b]
        out.append(max(window) if window else 0.0)
    top = max(out) or 1.0
    return [round(v / top, 4) for v in out]


def _smooth(seq, win) -> list:
    """PURE. Centred moving average; `win` is a frame count."""
    if win <= 1 or not seq:
        return list(seq)
    out, half = [], win // 2
    for i in range(len(seq)):
        a, b = max(0, i - half), min(len(seq), i + half + 1)
        out.append(sum(seq[a:b]) / (b - a))
    return out


def _levels(values, k=ANALYSIS_LEVELS, rounds=14) -> list:
    """PURE. 1-D Lloyd/k-means over log-energy, seeded on quantiles so the result is
    DETERMINISTIC — a colour that changed between two identical runs would be its own
    small lie. Returns one level index per value, ordered quiet → loud."""
    if not values:
        return []
    k = max(2, min(int(k), len(set(values)) or 2))
    srt = sorted(values)
    cs = [srt[min(len(srt) - 1, int((j + 0.5) * len(srt) / k))] for j in range(k)]
    assign = [0] * len(values)
    for _ in range(rounds):
        moved = False
        for i, v in enumerate(values):
            best = min(range(k), key=lambda j: abs(v - cs[j]))
            if best != assign[i]:
                assign[i] = best
                moved = True
        for j in range(k):
            mine = [values[i] for i in range(len(values)) if assign[i] == j]
            if mine:
                cs[j] = sum(mine) / len(mine)
        if not moved:
            break
    order = sorted(range(k), key=lambda j: cs[j])
    rank = {j: r for r, j in enumerate(order)}
    return [rank[a] for a in assign]


def segment(env, frame_s=ANALYSIS_FRAME_S, min_s=ANALYSIS_MIN_SECTION_S) -> list:
    """PURE. The energy envelope → runs of similar loudness.

    Returns [{start, end, level, label, energy}], or [] when the audio does not
    honestly segment (one level across the whole song, or fewer than two runs left
    once short ones are merged). [] is a REAL ANSWER: the caller then paints a
    single-hue amplitude ramp instead of inventing boundaries.
    """
    if len(env) < 8:
        return []
    eps = 1e-6
    logs = [math.log10(v + eps) for v in env]
    win = max(1, int(round(ANALYSIS_SMOOTH_S / frame_s)))
    lv = _levels(_smooth(logs, win))
    if len(set(lv)) < 2:
        return []
    runs = []                                       # [level, first, last_exclusive]
    for i, l in enumerate(lv):
        if runs and runs[-1][0] == l:
            runs[-1][2] = i + 1
        else:
            runs.append([l, i, i + 1])
    min_f = max(2, int(round(min_s / frame_s)))
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, r in enumerate(runs):
            if r[2] - r[1] >= min_f:
                continue
            # A too-short run is merged into the LONGER neighbour, so a two-second dip
            # never becomes a section of its own.
            left = runs[i - 1] if i > 0 else None
            right = runs[i + 1] if i + 1 < len(runs) else None
            pick = left if (right is None or
                            (left is not None
                             and (left[2] - left[1]) >= (right[2] - right[1]))) else right
            pick[1], pick[2] = min(pick[1], r[1]), max(pick[2], r[2])
            runs.pop(i)
            j = 0                       # neighbours of one level now touch: fuse them
            while j + 1 < len(runs):
                if runs[j][0] == runs[j + 1][0]:
                    runs[j][2] = runs[j + 1][2]
                    runs.pop(j + 1)
                else:
                    j += 1
            changed = True
            break
    if len(runs) < 2 or len({r[0] for r in runs}) < 2:
        return []
    top = max(env) or 1.0
    out = []
    for lvl, a, b in runs:
        window = env[a:b] or [0.0]
        out.append({"start": round(a * frame_s, 2), "end": round(b * frame_s, 2),
                    "level": int(lvl),
                    "label": ANALYSIS_LEVEL_NAMES[min(lvl, len(ANALYSIS_LEVEL_NAMES) - 1)],
                    "energy": round((sum(window) / len(window)) / top, 3)})
    return out


def analysis_fingerprint(path: str) -> str:
    """The identity of the BYTES analysed. A cached analysis whose fingerprint no
    longer matches is recomputed — a waveform drawn from a file that has since been
    replaced would be a picture of a different song."""
    try:
        st = os.stat(path)
    except OSError:
        return ""
    return f"{ANALYSIS_V}:{st.st_size}:{int(st.st_mtime)}"


def _read_sidecar(p: str) -> dict:
    try:
        with open(p, encoding="utf-8") as fh:
            loaded = json.load(fh)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:                                            # noqa: BLE001
        return {}


def track_analysis(root, name, decode=None) -> tuple:
    """(analysis, reason). The waveform data for ONE track: computed once, then cached
    in that track's own sidecar under "analysis".

    Containment is `library_target`'s — the same single boundary /file and /delete
    use. `mode` is the contract the page draws against:
        "sections" — runs of MEASURED loudness; hue may carry them
        "ramp"     — the bars are real, the segmentation was not honest; ONE hue
    There is no third mode in which sections are invented.
    """
    target, reason = library_target(root, name)
    if not target:
        return None, reason
    fp = analysis_fingerprint(target)
    sc = sidecar_path(target)
    meta = _read_sidecar(sc)
    cached = meta.get("analysis")
    if isinstance(cached, dict) and cached.get("fingerprint") == fp and cached.get("peaks"):
        return cached, ""
    try:
        if os.path.getsize(target) > ANALYSIS_MAX_BYTES:
            return None, "that track is too large to analyse here"
    except OSError as e:
        return None, f"could not read that track: {e}"
    if decode is not None:
        samples, sr = decode(target)
    else:
        samples, sr = _pcm_from_ffmpeg(target)
        if (samples is None or not len(samples)) and target.lower().endswith(".wav"):
            samples, sr = _pcm_from_wave(target)
    if samples is None or not len(samples) or not sr:
        return None, "this track could not be decoded for analysis"
    env = envelope(samples, sr)
    bars = peak_bars(env)
    if not bars:
        return None, "this track could not be decoded for analysis"
    secs = segment(env)
    out = {"v": ANALYSIS_V, "fingerprint": fp, "duration": round(len(samples) / sr, 2),
           "peaks": bars, "sections": secs,
           "mode": "sections" if secs else "ramp",
           "method": ANALYSIS_METHOD, "derived": True,
           "levels": ANALYSIS_LEVELS, "computed": time.time()}
    meta["analysis"] = out
    try:
        with open(sc, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)
    except OSError:
        pass          # an uncacheable analysis is still a correct one; recompute later
    return out, ""


# ── convert (ffmpeg, resolved by the voice lane's ONE ladder) ────────────────
_ENCODERS_CACHE: "set | None" = None


def _ffmpeg() -> "str | None":
    """The SAME resolver the voice lane uses (explicit-path ladder, never a second
    implementation) — imported lazily so music.py stays importable on its own."""
    try:
        from . import voice as _voice                            # noqa: PLC0415
    except ImportError:                                          # pragma: no cover
        import voice as _voice                                   # type: ignore
    return _voice.ffmpeg_bin()


def ffmpeg_encoders(run=None, ffmpeg=None) -> set:
    """The encoder names this ffmpeg build carries, probed ONCE per process.

    `run` is injectable so the decision table can be tested without an ffmpeg: our
    provisioned imageio-ffmpeg build is not guaranteed to ship libmp3lame, and the
    whole point of the probe is that an unavailable format is never offered.
    """
    global _ENCODERS_CACHE
    if run is None and _ENCODERS_CACHE is not None:
        return set(_ENCODERS_CACHE)
    binary = ffmpeg or _ffmpeg()
    if not binary:
        if run is None:
            _ENCODERS_CACHE = set()
        return set()
    try:
        if run is not None:
            out = run([binary, "-hide_banner", "-encoders"])
        else:
            r = subprocess.run([binary, "-hide_banner", "-encoders"],
                               capture_output=True, text=True, timeout=20)
            out = (r.stdout or "") + (r.stderr or "")
    except Exception:                                            # noqa: BLE001
        out = ""
    found = set()
    for line in str(out).splitlines():
        parts = line.split()
        # ffmpeg's table is " A....D libmp3lame  MP3 (MPEG audio layer 3)"
        if len(parts) >= 2 and parts[0][:1] in ("A", "V", "S", "."):
            found.add(parts[1])
    if run is None:
        _ENCODERS_CACHE = set(found)
    return found


def convert_formats(encoders=None) -> list:
    """Which convert targets are offerable. Absent, not greyed out."""
    have = ffmpeg_encoders() if encoders is None else set(encoders)
    return [f for f, spec in CONVERT_FORMATS.items() if spec["encoder"] in have]


def convert_argv(ffmpeg: str, src: str, dst: str, fmt: str) -> list:
    """PURE. `-y` is safe because the caller has already refused an existing target."""
    spec = CONVERT_FORMATS[fmt]
    return [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
            "-c:a", spec["encoder"], "-b:a", spec["bitrate"], str(dst)]


def convert_track(root, name, fmt, ffmpeg=None, encoders=None) -> tuple:
    """(new_name, None) | (None, reason). Never clobbers, never leaves a stub."""
    if fmt not in CONVERT_FORMATS:
        return None, "unknown format"
    src, reason = library_target(root, name)
    if not src:
        return None, reason
    binary = ffmpeg or _ffmpeg()
    if not binary:
        return None, ("no ffmpeg is available — installing VoiceStudio or Voicebox "
                      "provisions one")
    have = set(encoders) if encoders is not None else ffmpeg_encoders()
    if CONVERT_FORMATS[fmt]["encoder"] not in have:
        return None, f"this ffmpeg build cannot write {fmt}"
    dst = os.path.splitext(src)[0] + CONVERT_FORMATS[fmt]["ext"]
    if os.path.realpath(dst) == os.path.realpath(src):
        return None, f"that track is already {fmt}"
    if os.path.exists(dst):
        return None, f"a {fmt} of that track already exists"
    try:
        r = subprocess.run(convert_argv(binary, src, dst, fmt), capture_output=True,
                           text=True, timeout=CONVERT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        _rm(dst)
        return None, "the conversion timed out"
    except OSError as e:
        return None, f"could not start ffmpeg: {e}"
    if r.returncode != 0 or not render_ok(dst):
        _rm(dst)
        return None, ("the conversion failed\n"
                      + ((r.stdout or "") + (r.stderr or ""))[-600:]).strip()
    return os.path.basename(dst), None


def _rm(path) -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


# ── jobs: ONE render at a time, never a queue ────────────────────────────────
_JOB_LOCK = threading.Lock()
_JOB: dict | None = None

# The live engine child, so a cancel has something to signal. One render at a time is
# what makes a single slot correct here.
_PROC_LOCK = threading.Lock()
_PROC = None
CANCEL_GRACE_S = 5.0


def _register_proc(proc) -> None:
    global _PROC
    with _PROC_LOCK:
        _PROC = proc


def kill_process_group(proc, grace=CANCEL_GRACE_S, sleep=time.sleep) -> str:
    """SIGTERM the child's process GROUP, escalate to SIGKILL after `grace`.

    Returns what actually ended it ('term' | 'kill' | 'gone' | 'error') so the log can
    say. ⚠️ PLATFORM: `os.killpg`/`os.getpgid` are POSIX. macOS is the only platform
    this MOT Deck build runs on, but the fallback to proc.terminate()/kill() is kept so a
    hypothetical Windows host degrades to killing the direct child rather than raising.
    """
    if proc is None or proc.poll() is not None:
        return "gone"
    grp = None
    if hasattr(os, "killpg") and hasattr(os, "getpgid"):
        try:
            grp = os.getpgid(proc.pid)
        except OSError:
            grp = None
    def _signal(sig):
        try:
            if grp is not None:
                os.killpg(grp, sig)
            elif sig == signal.SIGKILL:
                proc.kill()
            else:
                proc.terminate()
            return True
        except (OSError, ProcessLookupError):
            return False
    if not _signal(signal.SIGTERM):
        return "gone" if proc.poll() is not None else "error"
    waited = 0.0
    while waited < grace:
        if proc.poll() is not None:
            return "term"
        sleep(0.2)
        waited += 0.2
    _signal(signal.SIGKILL)
    return "kill"


def job_cancel_requested() -> bool:
    with _JOB_LOCK:
        return bool(_JOB and _JOB.get("cancel"))


def cancel_job(log=print) -> tuple:
    """(ok, reason). Marks the single job cancelled and kills the engine's whole
    process group. Idempotent: a second click on an already-cancelling job is fine."""
    with _JOB_LOCK:
        if not (_JOB and _JOB.get("state") in ("queued", "running")):
            return False, "nothing is rendering"
        _JOB["cancel"] = True
    with _PROC_LOCK:
        proc = _PROC
    how = kill_process_group(proc)
    log(f"[music] render cancelled by the user ({how})", flush=True)
    return True, ""


def current_job():
    with _JOB_LOCK:
        return dict(_JOB) if _JOB else None


def job_busy() -> bool:
    with _JOB_LOCK:
        return bool(_JOB and _JOB.get("state") in ("queued", "running"))


def clear_job():
    """Drop the remembered job (tests; and the panel never needs a finished one twice)."""
    global _JOB
    with _JOB_LOCK:
        _JOB = None


def claim_job(params: dict):
    """(job, error) — atomically becomes THE render, or refuses because one is live.
    A queue was deliberately not built: two Metal renders would fight for the GPU
    and the second would be a surprise the user never asked to wait for."""
    global _JOB
    with _JOB_LOCK:
        if _JOB and _JOB.get("state") in ("queued", "running"):
            return None, "a song is already rendering — one at a time"
        _JOB = {
            # Millisecond timestamps collide when one terminal job is replaced in the
            # same clock tick. IDs are correlation identities, not display dates.
            "id": secrets.token_hex(12),
            "engine": params["engine"],
            "state": "queued",
            "started": time.time(),
            "seconds": params["seconds"],
            "steps": params["steps"],
            "seed": params["seed"],
            "prompt": params["prompt"],
            "format": params.get("format") or "",
            "cancel": False,
            "log": None,
            "wall": None, "error": None, "out": None,
        }
        return dict(_JOB), None


def job_log_tail(job, limit: int = 8000) -> str:
    """The last few KB of the live engine output — the input to `parse_progress`.

    Reading a file the subprocess is still writing is deliberate: it is the ONLY way
    to see progress from a one-shot engine, and a partial last line is harmless to a
    parser that is total over junk."""
    p = (job or {}).get("log")
    if not p:
        return ""
    try:
        size = os.path.getsize(p)
        with open(p, "rb") as fh:
            if size > limit:
                fh.seek(size - limit)
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _set(**kw):
    global _JOB
    with _JOB_LOCK:
        if _JOB:
            _JOB.update(kw)


def _run(argv, cwd=None, env_extra=None, timeout=MUSIC_TIMEOUT_S, log_path=None) -> str:
    """One engine invocation. Returns the combined output tail; raises MusicError on
    a non-zero exit or a timeout, MusicCancelled when the user stopped it.

    When `log_path` is given the child writes STRAIGHT INTO that file (line-buffered
    by the child, not by us) instead of into a pipe we only read at the end — that
    file is what makes live progress possible at all. The error tail is then read
    back off the same file, so nothing is lost by not piping.

    ⚠️ `start_new_session=True` is LOAD-BEARING, not hygiene: it puts the child in its
    own process group so a cancel can signal the WHOLE tree. minimax runs a python that
    spawns Metal work and acestep's binaries fork; terminating only the direct child
    would leave the GPU busy while the panel said "cancelled".
    """
    if job_cancel_requested():
        raise MusicCancelled("cancelled")
    env = dict(os.environ)
    for k, v in (env_extra or {}).items():
        env[k] = (v + os.pathsep + env[k]) if (k == "PYTHONPATH" and env.get(k)) else v
    # Both engines print progress with flush=True; PYTHONUNBUFFERED is belt and
    # braces for anything in the chain that does not.
    env.setdefault("PYTHONUNBUFFERED", "1")
    fh = None
    try:
        if log_path:
            fh = open(log_path, "a", encoding="utf-8", errors="replace")
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=fh,
                                    stderr=subprocess.STDOUT, start_new_session=True)
        else:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True,
                                    start_new_session=True)
    except OSError as e:
        if fh:
            fh.close()
        raise MusicError(f"could not start the engine: {e}")
    _register_proc(proc)
    piped = ""
    try:
        if job_cancel_requested():
            kill_process_group(proc)
        try:
            # communicate() is what WAITS, in both branches — with log_path the child
            # writes to the file and there is nothing to read, but the timeout still
            # has to be armed or a wedged engine would never be reaped.
            piped = proc.communicate(timeout=timeout)[0] or ""
        except subprocess.TimeoutExpired:
            kill_process_group(proc)
            try:
                proc.communicate(timeout=10)
            except Exception:                                    # noqa: BLE001
                pass
            raise MusicError(f"the render timed out after {timeout // 60} minutes")
    finally:
        _register_proc(None)
        if fh:
            fh.close()
    tail = (_tail_file(log_path, STDERR_TAIL) if log_path else piped[-STDERR_TAIL:])
    if job_cancel_requested():
        raise MusicCancelled("cancelled")
    if proc.returncode != 0:
        raise MusicError(f"engine exited {proc.returncode}\n{tail}".strip())
    return tail


def _tail_file(path, limit) -> str:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > limit:
                fh.seek(size - limit)
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def render_minimax(root, params, workdir, out_path, snapshot, log_path=None) -> str:
    py = venv_python(root)
    if not os.path.isfile(py):
        raise MusicError("the music venv is missing — install the engine again")
    lyr = os.path.join(workdir, "lyrics.txt")
    with open(lyr, "w", encoding="utf-8") as fh:
        fh.write(params.get("lyrics", "") or "")
    cmd = minimax_cmd(py, snapshot, params, lyr, out_path)
    tail = _run(cmd["argv"], cwd=cmd["cwd"], env_extra=cmd["env"], log_path=log_path)
    if not render_ok(out_path):
        raise MusicError("the engine finished but produced no audio\n" + tail)
    return out_path


def render_acestep(root, params, workdir, out_path, log_path=None) -> str:
    models = acestep_models(root)
    lm, synth = acestep_bin(root, "ace-lm"), acestep_bin(root, "ace-synth")
    for b in (lm, synth):
        if not (os.path.isfile(b) and os.access(b, os.X_OK)):
            raise MusicError(f"missing engine binary {os.path.basename(b)} — reinstall acestep")
    req = os.path.join(workdir, "req.json")
    with open(req, "w", encoding="utf-8") as fh:
        json.dump(acestep_request(params), fh, indent=2)
    _run(ace_argv(lm, models, req), log_path=log_path)
    req2 = ace_stage2_request(req)
    if not os.path.isfile(req2):
        raise MusicError("ace-lm produced no stage-2 request — see data/logs/bridge.log")
    tail = _run(ace_argv(synth, models, req2), log_path=log_path)
    # ace-synth names its own output (<stem>00.<ext>); find it rather than assume.
    made = sorted(glob.glob(os.path.join(workdir, "req0*.wav"))
                  + glob.glob(os.path.join(workdir, "req0*.mp3")))
    made = [m for m in made if render_ok(m)]
    if not made:
        raise MusicError("the engine finished but produced no audio\n" + tail)
    shutil.move(made[0], out_path)
    return out_path


def _job_event(callback, state: str, job: dict) -> None:
    """Best-effort state nudge; the job record remains the source of truth."""
    if callback is None:
        return
    try:
        callback(str(state), dict(job or {}))
    except Exception:                                                # noqa: BLE001
        pass


def _transition(job: dict, state: str, **kw) -> dict:
    """Move only this exact job and return the same atomic state snapshot.

    A terminal state releases the one-render slot.  Capturing the event payload under
    the same lock prevents a newly claimed render from lending its id to the previous
    render's delayed terminal nudge.
    """
    global _JOB
    with _JOB_LOCK:
        if not (_JOB and _JOB.get("id") == (job or {}).get("id")):
            return {}
        _JOB.update(kw)
        _JOB["state"] = state
        return dict(_JOB)


def _publish_track(staged: str, directory: str, name: str) -> str:
    """Expose complete audio atomically on the library's own filesystem."""
    fd, temporary = tempfile.mkstemp(prefix=".motdeck-track-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as output, open(staged, "rb") as source:
            shutil.copyfileobj(source, output)
            output.flush()
            os.fsync(output.fileno())
        stem, suffix = os.path.splitext(name)
        with _JOB_LOCK:
            if _JOB and _JOB.get("cancel"):
                raise MusicCancelled("cancelled")
            for n in range(10000):
                base = stem if n == 0 else f"{stem} ({n})"
                dest = os.path.join(directory, base + suffix)
                # Converted siblings share metadata; a new song must own its stem.
                if any(os.path.lexists(os.path.join(directory, base + ext))
                       for ext in (*LIBRARY_EXTS, ".json")):
                    continue
                try:
                    os.link(temporary, dest)
                    return dest
                except FileExistsError:
                    continue
        raise MusicError("could not find an unused track name")
    finally:
        os.unlink(temporary)


def run_job(root, params, job, snapshot="", render=None, log=print,
            on_state=None):
    """The job body. Public so tests can drive the state machine without a thread."""
    started = time.time()
    state_job = _transition(job, "running")
    _job_event(on_state, "running", state_job)
    workdir = None
    try:
        if job_cancel_requested():
            raise MusicCancelled("cancelled")
        tmp_root = os.path.join(str(root), "data", "tmp")
        try:
            os.makedirs(tmp_root, exist_ok=True)
        except OSError:
            tmp_root = None
        workdir = tempfile.mkdtemp(prefix="motdeck-music-", dir=tmp_root)
        name = track_name(params["engine"], fmt=params.get("format", ""))
        out_path = os.path.join(workdir, name)
        log_path = os.path.join(workdir, "engine.log")
        _set(log=log_path)
        if render is not None:
            render(root, params, workdir, out_path)
        elif params["engine"] == "minimax":
            render_minimax(root, params, workdir, out_path, snapshot, log_path)
        else:
            render_acestep(root, params, workdir, out_path, log_path)
        if job_cancel_requested():
            raise MusicCancelled("cancelled")
        if not render_ok(out_path):
            raise MusicError("the engine finished but produced no audio")
        out_path = _publish_track(out_path, music_dir(root), name)
        name = os.path.basename(out_path)
        wall = round(time.time() - started, 1)
        meta = {"engine": params["engine"], "prompt": params["prompt"],
                "lyrics": params.get("lyrics", ""), "seconds": params["seconds"],
                "steps": params["steps"], "seed": params["seed"], "wall": wall,
                "format": params.get("format", ""), "created": time.time()}
        try:
            with open(sidecar_path(out_path), "x", encoding="utf-8") as fh:
                json.dump(meta, fh, indent=2)
        except OSError:
            pass                       # the audio is what matters
        state_job = _transition(job, "done", wall=wall, out=name)
        _job_event(on_state, "done", state_job)
        log(f"[music] render {params['engine']} ok — {name} "
            f"({params['seconds']}s song, {params['steps']} steps, seed {params['seed']}) "
            f"in {wall}s", flush=True)
    except MusicCancelled:
        # A cancelled render leaves NOTHING behind: a half-written wav would look like
        # a track in the library and, worse, its sidecar would enter the ETA history as
        # a measurement of a render that never finished.
        wall = round(time.time() - started, 1)
        state_job = _transition(job, "cancelled", wall=wall, error=None, out=None)
        _job_event(on_state, "cancelled", state_job)
        log(f"[music] render {params['engine']} cancelled after {wall}s "
            f"— partial output removed", flush=True)
    except MusicError as e:
        wall = round(time.time() - started, 1)
        state_job = _transition(job, "failed", wall=wall, error=str(e)[:STDERR_TAIL])
        _job_event(on_state, "failed", state_job)
        log(f"[music] render {params['engine']} FAILED after {wall}s: "
            f"{str(e)[:400]}", flush=True)
    except Exception as e:                                       # noqa: BLE001
        wall = round(time.time() - started, 1)
        state_job = _transition(job, "failed",
                                wall=wall, error=f"unexpected: {e}"[:STDERR_TAIL])
        _job_event(on_state, "failed", state_job)
        log(f"[music] render {params['engine']} FAILED (unexpected) after {wall}s: {e}",
            flush=True)
    finally:
        if workdir is not None:
            shutil.rmtree(workdir, ignore_errors=True)
    return current_job()


def start_job(root, params, snapshot="", render=None, log=print, on_state=None):
    """(job, error). Claims the single slot, then renders on a background thread."""
    job, err = claim_job(params)
    if err:
        return None, err
    _job_event(on_state, "queued", job)
    t = threading.Thread(target=run_job, args=(root, params, job),
                         kwargs={"snapshot": snapshot, "render": render, "log": log,
                                 "on_state": on_state},
                         daemon=True)
    try:
        t.start()
    except RuntimeError as exc:
        message = f"could not start the render worker: {exc}"
        state_job = _transition(job, "failed", error=message)
        _job_event(on_state, "failed", state_job)
        return None, message
    return job, None
