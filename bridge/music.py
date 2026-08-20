"""Harness-native MUSIC lane (FABLE-MUSIC-LANE-SPEC, 2026-08-20).

Same shape as the voice capability and deliberately NOT a component: no port, no
manifest entry, no daemon, no Swift change. A render is a ONE-SHOT SUBPROCESS run
as a background job; the only persistent cost is disk.

Two engines, both measured on Debi's Mac before adoption and both kept because both
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
import os
import random
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

# ── constants ────────────────────────────────────────────────────────────────
ENGINES = ("minimax", "acestep")

# Planning numbers for the RAM ledger, NOT measured RSS. minimax's measured 2.2GB
# max-RSS is known-understated: MLX/Metal wired memory does not show up there, and
# the research put a real render at 32-48GB. The ledger must plan for the truth.
MUSIC_RAM_GB = {"minimax": 32, "acestep": 9}

# Steps mean DIFFERENT things per engine (flow steps vs DiT inference steps) — the
# defaults are each engine's own design point, not a shared knob.
DEFAULT_STEPS = {"minimax": 30, "acestep": 8}
MAX_STEPS = {"minimax": 30, "acestep": 20}

SECONDS_MIN, SECONDS_MAX = 10, 300
SECONDS_DEFAULT = 60
PROMPT_MAX = 2000
LYRICS_MAX = 20000            # generous: a full lyric sheet, still bounded
SEED_MAX = 2 ** 31 - 1

MUSIC_TIMEOUT_S = 1800        # 30 minutes per render (spec)
STDERR_TAIL = 2000            # bytes of engine output carried into a failure

MINIMAX_REPO = "PocketAiHub/MiniMax-Music3-MLX"
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


# ── paths ────────────────────────────────────────────────────────────────────
def music_dir(root) -> str:
    """Where finished songs live. Created on demand (gitignored: it is under data/)."""
    d = os.path.join(str(root), "data", "music")
    os.makedirs(d, exist_ok=True)
    return d


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
    """None = allowed, else the refusal text. Boundary INCLUSIVE (fitting exactly
    is allowed), same predicate shape as the runner/aux/voice gates."""
    need = music_need_bytes(engine)
    try:
        other = int(other_bytes or 0)
        budget = int(budget_bytes or 0)
    except (TypeError, ValueError):
        other, budget = 0, 0
    if need and (need + other) > budget:
        return (f"a {engine} render needs about {need / 1024**3:.0f} GB and "
                f"{other / 1024**3:.1f} GB of models are loaded — that exceeds the "
                f"{budget / 1024**3:.0f} GB model-RAM budget; eject the chat model first")
    return None


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
        # A render with no seed is unreproducible, so the harness picks one and
        # RECORDS it in the sidecar rather than leaving the engine's default unknown.
        seed = random.randint(0, SEED_MAX)
        seed_given = False
    else:
        seed = _as_int(raw_seed, None)
        if seed is None or seed < 0 or seed > SEED_MAX:
            return None, f"seed must be a whole number between 0 and {SEED_MAX}"
        seed_given = True

    return {"engine": engine, "prompt": prompt, "lyrics": lyrics,
            "seconds": int(seconds), "steps": int(steps), "seed": int(seed),
            "seed_given": bool(seed_given)}, None


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
        # No lyrics ⇒ no flag: an instrumental must not be asked for with an empty
        # file, whose meaning to the port is not documented.
        argv[2:2] = ["--lyrics-file", str(lyrics_file)]
    return {"argv": argv, "cwd": str(snapshot),
            "env": {"PYTHONPATH": str(snapshot)}}


def acestep_request(params: dict) -> dict:
    """PURE: the AceRequest JSON (docs/ARCHITECTURE.md shapes, as the measurement
    prototype used them). `duration` is float SECONDS; `lyrics` is the single source
    of truth for vocals; `output_format` is a JSON field with no CLI flag."""
    return {
        "caption": params["prompt"],
        "lyrics": params.get("lyrics", "") or "",
        "duration": float(params["seconds"]),
        "seed": int(params["seed"]),
        "inference_steps": int(params["steps"]),
        "output_format": "wav24",
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


def track_name(engine: str, when=None) -> str:
    t = time.localtime(when if when is not None else time.time())
    return f"{engine}-{time.strftime('%Y%m%d-%H%M%S', t)}.wav"


# ── library ──────────────────────────────────────────────────────────────────
def sidecar_path(wav_path: str) -> str:
    return os.path.splitext(str(wav_path))[0] + ".json"


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
        if not n.lower().endswith(".wav"):
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
    if not name.lower().endswith(".wav"):
        return None, "refused: only .wav tracks"
    root_real = os.path.realpath(music_dir(root))
    target = os.path.realpath(os.path.join(root_real, name))
    if not target.startswith(root_real + os.sep):
        return None, "refused: that path is outside the music folder"
    if not os.path.isfile(target):
        return None, "no such track"
    return target, None


def delete_track(root, name) -> tuple:
    """Delete a wav AND its sidecar. (ok, reason)."""
    target, reason = library_target(root, name)
    if not target:
        return False, reason
    try:
        os.remove(target)
    except OSError as e:
        return False, f"could not delete: {e}"
    try:
        sc = sidecar_path(target)
        if os.path.isfile(sc):
            os.remove(sc)
    except OSError:
        pass                       # the audio is gone; a stale sidecar is harmless
    return True, ""


# ── jobs: ONE render at a time, never a queue ────────────────────────────────
_JOB_LOCK = threading.Lock()
_JOB: dict | None = None


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
            "id": f"{int(time.time() * 1000):x}",
            "engine": params["engine"],
            "state": "queued",
            "started": time.time(),
            "seconds": params["seconds"],
            "steps": params["steps"],
            "seed": params["seed"],
            "prompt": params["prompt"],
            "wall": None, "error": None, "out": None,
        }
        return dict(_JOB), None


def _set(**kw):
    global _JOB
    with _JOB_LOCK:
        if _JOB:
            _JOB.update(kw)


def _run(argv, cwd=None, env_extra=None, timeout=MUSIC_TIMEOUT_S) -> str:
    """One engine invocation. Returns the combined output tail; raises MusicError on
    a non-zero exit or a timeout, with that tail in the message."""
    env = dict(os.environ)
    for k, v in (env_extra or {}).items():
        env[k] = (v + os.pathsep + env[k]) if (k == "PYTHONPATH" and env.get(k)) else v
    try:
        r = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        raise MusicError(f"the render timed out after {timeout // 60} minutes")
    except OSError as e:
        raise MusicError(f"could not start the engine: {e}")
    tail = ((r.stdout or "") + (r.stderr or ""))[-STDERR_TAIL:]
    if r.returncode != 0:
        raise MusicError(f"engine exited {r.returncode}\n{tail}".strip())
    return tail


def render_minimax(root, params, workdir, out_path, snapshot) -> str:
    py = venv_python(root)
    if not os.path.isfile(py):
        raise MusicError("the music venv is missing — install the engine again")
    lyr = os.path.join(workdir, "lyrics.txt")
    with open(lyr, "w", encoding="utf-8") as fh:
        fh.write(params.get("lyrics", "") or "")
    cmd = minimax_cmd(py, snapshot, params, lyr, out_path)
    tail = _run(cmd["argv"], cwd=cmd["cwd"], env_extra=cmd["env"])
    if not render_ok(out_path):
        raise MusicError("the engine finished but produced no audio\n" + tail)
    return out_path


def render_acestep(root, params, workdir, out_path) -> str:
    models = acestep_models(root)
    lm, synth = acestep_bin(root, "ace-lm"), acestep_bin(root, "ace-synth")
    for b in (lm, synth):
        if not (os.path.isfile(b) and os.access(b, os.X_OK)):
            raise MusicError(f"missing engine binary {os.path.basename(b)} — reinstall acestep")
    req = os.path.join(workdir, "req.json")
    with open(req, "w", encoding="utf-8") as fh:
        json.dump(acestep_request(params), fh, indent=2)
    _run(ace_argv(lm, models, req))
    req2 = ace_stage2_request(req)
    if not os.path.isfile(req2):
        raise MusicError("ace-lm produced no stage-2 request — see data/logs/bridge.log")
    tail = _run(ace_argv(synth, models, req2))
    # ace-synth names its own output (<stem>00.<ext>); find it rather than assume.
    made = sorted(glob.glob(os.path.join(workdir, "req0*.wav"))
                  + glob.glob(os.path.join(workdir, "req0*.mp3")))
    made = [m for m in made if render_ok(m)]
    if not made:
        raise MusicError("the engine finished but produced no audio\n" + tail)
    shutil.move(made[0], out_path)
    return out_path


def run_job(root, params, job, snapshot="", render=None, log=print):
    """The job body. Public so tests can drive the state machine without a thread."""
    started = time.time()
    _set(state="running")
    tmp_root = os.path.join(str(root), "data", "tmp")
    try:
        os.makedirs(tmp_root, exist_ok=True)
    except OSError:
        tmp_root = None
    workdir = tempfile.mkdtemp(prefix="harness-music-", dir=tmp_root)
    name = track_name(params["engine"])
    out_path = os.path.join(music_dir(root), name)
    try:
        if render is not None:
            render(root, params, workdir, out_path)
        elif params["engine"] == "minimax":
            render_minimax(root, params, workdir, out_path, snapshot)
        else:
            render_acestep(root, params, workdir, out_path)
        wall = round(time.time() - started, 1)
        meta = {"engine": params["engine"], "prompt": params["prompt"],
                "lyrics": params.get("lyrics", ""), "seconds": params["seconds"],
                "steps": params["steps"], "seed": params["seed"], "wall": wall,
                "created": time.time()}
        try:
            with open(sidecar_path(out_path), "w", encoding="utf-8") as fh:
                json.dump(meta, fh, indent=2)
        except OSError:
            pass                       # the audio is what matters
        _set(state="done", wall=wall, out=name)
        log(f"[music] render {params['engine']} ok — {name} "
            f"({params['seconds']}s song, {params['steps']} steps, seed {params['seed']}) "
            f"in {wall}s", flush=True)
    except MusicError as e:
        wall = round(time.time() - started, 1)
        _set(state="failed", wall=wall, error=str(e)[:STDERR_TAIL])
        log(f"[music] render {params['engine']} FAILED after {wall}s: "
            f"{str(e)[:400]}", flush=True)
    except Exception as e:                                       # noqa: BLE001
        wall = round(time.time() - started, 1)
        _set(state="failed", wall=wall, error=f"unexpected: {e}"[:STDERR_TAIL])
        log(f"[music] render {params['engine']} FAILED (unexpected) after {wall}s: {e}",
            flush=True)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return current_job()


def start_job(root, params, snapshot="", render=None, log=print):
    """(job, error). Claims the single slot, then renders on a background thread."""
    job, err = claim_job(params)
    if err:
        return None, err
    t = threading.Thread(target=run_job, args=(root, params, job),
                         kwargs={"snapshot": snapshot, "render": render, "log": log},
                         daemon=True)
    t.start()
    return job, None
