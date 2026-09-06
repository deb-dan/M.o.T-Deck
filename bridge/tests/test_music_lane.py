"""MUSIC LANE v1 — the decision tables that keep two GPU engines honest (2026-08-20).

Built to docs/handoff/FABLE-MUSIC-LANE-SPEC.md. What each group here is guarding, and
why it is load-bearing rather than decorative:

1. THE MINIMAX COMMAND. The measurement prototype died TWICE on the same thing: an HF
   snapshot is a symlink farm, so `sys.path[0]` and `--model-dir`'s default both
   resolve to the flat blobs dir where the port's sibling module has no name and the
   manifest's relative weight paths do not exist. The fix is three-part — cwd,
   PYTHONPATH, explicit --model-dir — and all three are pinned BY STRUCTURE here,
   because losing any one of them is a render that fails minutes into a job.
2. THE ACESTEP REQUEST. `duration` is float SECONDS, `output_format` is a JSON field
   with no CLI flag, and stage 2 reads the `<stem>0.json` stage 1 wrote. Wrong field
   names would be a silent wrong-length song, not an error.
3. THE RAM GATE. minimax's MEASURED 2.2GB max-RSS is known-understated (MLX/Metal
   wired memory is invisible to it); the planning number is 32GB. The gate exists so
   a render never lands on top of a loaded 20GB chat model.
4. VALIDATION TOTALITY. Every field comes off the wire; junk in any of them must
   produce a refusal with a sentence in it, never a subprocess.
5. INSTALL DETECTION FROM DISK. `installed` is never a stored flag — a wiped HF cache
   or a half-finished download must read as not-installed immediately, because the
   alternative is a Generate button that starts a job which cannot work.
6. CONTAINMENT. /file and /delete both take a name off the wire; library_target is
   the whole boundary (the `_deletable_target` discipline).
7. THE JOB STATE MACHINE. One render at a time, a failure that carries the engine's
   own words, and a sidecar that makes a track reproducible.

Run: python3 bridge/tests/test_music_lane.py
"""
import json
import os
import re
import signal
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# ⚠️ THE APP LAYER IS NO LONGER ONE FILE (router/core split, 2026-08-28).
# bridge/app.py is a FACADE over bridge/core/*.py + bridge/routers/*.py, so the
# source-text assertions below read bridge/appsrc.py's assembled view of the whole
# app layer instead of one file. Read bridge/appsrc.py's header for why the
# assertions are source-text in the first place and why order is part of it.
from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402
from bridge import music                                        # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


GB = 1024 ** 3
P = {"engine": "minimax", "prompt": "gritty rock", "lyrics": "[Verse]\nhello",
     "seconds": 60, "steps": 30, "seed": 42, "seed_given": True}


# ══ 1. minimax command ═══════════════════════════════════════════════════════
cmd = music.minimax_cmd("/v/bin/python", "/snap", P, "/w/lyrics.txt", "/out/x.wav")
argv = cmd["argv"]
check("minimax runs the venv interpreter", argv[0] == "/v/bin/python")
check("minimax runs generate.py", "generate.py" in argv)
check("SYMLINK FARM 1/3 — cwd is the snapshot", cmd["cwd"] == "/snap")
check("SYMLINK FARM 2/3 — PYTHONPATH is the snapshot", cmd["env"]["PYTHONPATH"] == "/snap")
check("SYMLINK FARM 3/3 — --model-dir is passed EXPLICITLY",
      "--model-dir" in argv and argv[argv.index("--model-dir") + 1] == "/snap")
check("the prompt is a separate argv element (never shell-interpolated)",
      argv[argv.index("--prompt") + 1] == "gritty rock")
for flag, val in (("--seconds", "60"), ("--steps", "30"), ("--seed", "42"),
                  ("--output", "/out/x.wav")):
    check(f"minimax carries {flag} {val}",
          flag in argv and argv[argv.index(flag) + 1] == val)
check("lyrics travel as a FILE, not an argument",
      "--lyrics-file" in argv and argv[argv.index("--lyrics-file") + 1] == "/w/lyrics.txt")
inst = dict(P); inst["lyrics"] = "   \n "
ia = music.minimax_cmd("p", "/s", inst, "/w/l.txt", "/o.wav")["argv"]
check("an INSTRUMENTAL passes no --lyrics-file", "--lyrics-file" not in ia)
# ⚠️ THE BUG THIS PINS (found 2026-08-20 by reading generate.py at the pin): the two
# lyrics arguments are an argparse mutually-exclusive group with required=True, so
# passing NEITHER is a usage error — every instrumental minimax render failed before
# it reached the GPU. The port's own help says to use [Instrumental].
check("an INSTRUMENTAL still passes --lyrics (the group is argparse-REQUIRED)",
      "--lyrics" in ia and ia[ia.index("--lyrics") + 1] == "[Instrumental]")
check("the instrumental token is the one the port documents",
      music.MINIMAX_INSTRUMENTAL == "[Instrumental]")
check("every argv element is a string (subprocess would raise otherwise)",
      all(isinstance(a, str) for a in argv))
check("the engine is never asked to launch a server", not any(
    "server" in a for a in argv))

# ══ 2. acestep request + argv ════════════════════════════════════════════════
A = dict(P); A["engine"] = "acestep"; A["steps"] = 8
req = music.acestep_request(A)
check("acestep field: caption is the prompt", req["caption"] == "gritty rock")
check("acestep field: lyrics is the single source of truth for vocals",
      req["lyrics"] == "[Verse]\nhello")
check("acestep field: duration is FLOAT seconds (not ms, not a string)",
      isinstance(req["duration"], float) and req["duration"] == 60.0)
check("acestep field: inference_steps", req["inference_steps"] == 8)
check("acestep field: seed", req["seed"] == 42)
check("acestep field: output_format is a JSON field (there is NO cli flag for it)",
      req["output_format"] == "wav24")
check("an instrumental acestep request carries an EMPTY lyrics string, not a missing key",
      music.acestep_request({**A, "lyrics": ""})["lyrics"] == "")
check("the acestep request has exactly the six documented keys",
      set(req) == {"caption", "lyrics", "duration", "seed", "inference_steps",
                   "output_format"})
av = music.ace_argv("/b/ace-lm", "/m", "/w/req.json")
check("ace argv = binary --models <dir> --request <file>",
      av == ["/b/ace-lm", "--models", "/m", "--request", "/w/req.json"])
check("stage 2 reads the <stem>0.json stage 1 wrote",
      music.ace_stage2_request("/w/req.json") == "/w/req0.json")
check("stage-2 naming survives a dotted stem",
      music.ace_stage2_request("/w/my.song.json") == "/w/my.song0.json")

# ══ 3. RAM gate ══════════════════════════════════════════════════════════════
check("the minimax planning number is the honest 14GB, not the pre-measurement 32",
      music.MUSIC_RAM_GB == {"minimax": 14, "acestep": 9})
check("minimax on an empty machine within a 48GB budget: no warning",
      music.ram_gate("minimax", 0, 48 * GB) is None)
check("minimax with a 40GB model loaded: WARNED",
      music.ram_gate("minimax", 40 * GB, 48 * GB) is not None)
check("minimax alongside a 20GB chat model now FITS (14 + 20 <= 48)",
      music.ram_gate("minimax", 20 * GB, 48 * GB) is None)
check("the warning names both ways out", 
      all(w in (music.ram_gate("minimax", 40 * GB, 48 * GB) or "")
          for w in ("Eject", "generate anyway")))
check("the warning states the numbers rather than just refusing",
      "48 GB" in (music.ram_gate("minimax", 40 * GB, 48 * GB) or ""))
check("acestep with the same 20GB model loaded: no warning (9 + 20 <= 48)",
      music.ram_gate("acestep", 20 * GB, 48 * GB) is None)
check("BOUNDARY IS INCLUSIVE — exactly filling the budget is allowed",
      music.ram_gate("minimax", 34 * GB, 48 * GB) is None)
check("one byte over the boundary warns",
      music.ram_gate("minimax", 34 * GB + 1, 48 * GB) is not None)
check("acestep warned when it genuinely cannot fit",
      music.ram_gate("acestep", 40 * GB, 48 * GB) is not None)
check("junk 'other bytes' degrades to zero rather than crashing a request",
      music.ram_gate("acestep", None, 48 * GB) is None)
check("a junk budget warns (fail toward the guard, never past it)",
      music.ram_gate("minimax", 0, "nonsense") is not None)
check("an unknown engine claims no RAM and is not gated here",
      music.ram_gate("nope", 0, 1) is None)

# ══ 4. validation totality ═══════════════════════════════════════════════════
V = music.validate_generate
INST = ["minimax", "acestep"]
ok, err = V({"engine": "acestep", "prompt": "jazz", "seconds": 30}, INST)
check("a good request validates", err is None and ok["engine"] == "acestep")
check("steps default to the ENGINE's design point, not a shared number",
      ok["steps"] == 8 and V({"engine": "minimax", "prompt": "x"}, INST)[0]["steps"] == 30)
check("seconds default to 60 when omitted",
      V({"engine": "acestep", "prompt": "x"}, INST)[0]["seconds"] == 60)
check("an omitted seed is CHOSEN and recorded (a render must be reproducible)",
      ok["seed"] >= 0 and ok["seed_given"] is False)
check("a supplied seed is kept and flagged as given",
      V({"engine": "acestep", "prompt": "x", "seed": 7}, INST)[0]["seed"] == 7)
for body, why in [
    (None, "a non-dict body"),
    ({}, "no engine"),
    ({"engine": "nope", "prompt": "x"}, "an unknown engine"),
    ({"engine": 7, "prompt": "x"}, "a non-string engine"),
    ({"engine": "acestep"}, "no prompt"),
    ({"engine": "acestep", "prompt": "   "}, "a whitespace prompt"),
    ({"engine": "acestep", "prompt": 5}, "a non-string prompt"),
    ({"engine": "acestep", "prompt": "x" * 8001}, "an over-long prompt"),
    ({"engine": "acestep", "prompt": "x", "format": "flac"}, "a format the engine cannot write"),
    ({"engine": "minimax", "prompt": "x", "format": "mp3"}, "mp3 asked of minimax"),
    ({"engine": "acestep", "prompt": "x", "format": 7}, "a non-string format"),
    ({"engine": "acestep", "prompt": "x", "seconds": 9}, "9 seconds"),
    ({"engine": "acestep", "prompt": "x", "seconds": 301}, "301 seconds"),
    ({"engine": "acestep", "prompt": "x", "seconds": "soon"}, "junk seconds"),
    ({"engine": "acestep", "prompt": "x", "seconds": []}, "list seconds"),
    ({"engine": "acestep", "prompt": "x", "steps": 0}, "zero steps"),
    ({"engine": "acestep", "prompt": "x", "steps": 21}, "21 acestep steps"),
    ({"engine": "minimax", "prompt": "x", "steps": 31}, "31 minimax steps"),
    ({"engine": "acestep", "prompt": "x", "steps": "lots"}, "junk steps"),
    ({"engine": "acestep", "prompt": "x", "seed": -1}, "a negative seed"),
    ({"engine": "acestep", "prompt": "x", "seed": "abc"}, "a junk seed"),
    ({"engine": "acestep", "prompt": "x", "seed": 1.5}, "a fractional seed"),
    ({"engine": "acestep", "prompt": "x", "lyrics": "y" * 20001}, "over-long lyrics"),
]:
    p, e = V(body, INST)
    check(f"REFUSED: {why}", p is None and isinstance(e, str) and len(e) > 5)
p, e = V({"engine": "minimax", "prompt": "x"}, ["acestep"])
check("an engine that is not INSTALLED is refused, and the message says so",
      p is None and "not installed" in (e or ""))
check("20 minimax steps (inside its range) is fine",
      V({"engine": "minimax", "prompt": "x", "steps": 20}, INST)[1] is None)
check("a numeric string seconds is accepted (an <input> yields strings)",
      V({"engine": "acestep", "prompt": "x", "seconds": "45"}, INST)[0]["seconds"] == 45)
check("True is not silently taken as steps=1",
      V({"engine": "acestep", "prompt": "x", "steps": True}, INST)[0] is None)
check("empty-string steps means 'use the default', not an error",
      V({"engine": "acestep", "prompt": "x", "steps": ""}, INST)[0]["steps"] == 8)
check("the prompt is stripped before use",
      V({"engine": "acestep", "prompt": "  jazz  "}, INST)[0]["prompt"] == "jazz")
check("300 seconds (the cap) is allowed",
      V({"engine": "acestep", "prompt": "x", "seconds": 300}, INST)[1] is None)
check("10 seconds (the floor) is allowed",
      V({"engine": "acestep", "prompt": "x", "seconds": 10}, INST)[1] is None)

# ══ 5. install detection from fake disk trees ════════════════════════════════
REV = "0505e3f04ddfb883e0a2fbd8ad1a34c2f313e514"
check("the HF snapshot path is derived, not stored",
      music.hf_snapshot_dir("Org/Name", "abc", "/c")
      == "/c/models--Org--Name/snapshots/abc")
check("HF_HUB_CACHE wins over HF_HOME",
      music.hf_cache_root({"HF_HUB_CACHE": "/x", "HF_HOME": "/y"}) == "/x")
check("HF_HOME gets its /hub suffix",
      music.hf_cache_root({"HF_HOME": "/y"}) == "/y/hub")
check("the default cache root is the documented one",
      music.hf_cache_root({}).endswith(os.path.join(".cache", "huggingface", "hub")))

with tempfile.TemporaryDirectory() as td:
    cache = os.path.join(td, "cache")
    snap = music.hf_snapshot_dir(music.MINIMAX_REPO, REV, cache)
    ok_, s_, why = music.minimax_installed(td, REV, cache)
    check("minimax ABSENT: no venv → not installed, with a reason",
          ok_ is False and why)
    os.makedirs(os.path.join(td, "data", "music-venv", "bin"))
    open(music.venv_python(td), "w").close()
    ok_, s_, why = music.minimax_installed(td, REV, cache)
    check("minimax PARTIAL: venv but no weights → not installed", ok_ is False)
    os.makedirs(snap)
    open(os.path.join(snap, "generate.py"), "w").close()
    ok_, s_, why = music.minimax_installed(td, REV, cache)
    check("minimax PARTIAL: entry point but no sibling module → not installed",
          ok_ is False and "minimax_mlx_model.py" in why)
    open(os.path.join(snap, "minimax_mlx_model.py"), "w").close()
    check("minimax PARTIAL: no manifest → not installed",
          music.minimax_installed(td, REV, cache)[0] is False)
    open(os.path.join(snap, "model_manifest.json"), "w").close()
    ok_, s_, why = music.minimax_installed(td, REV, cache)
    check("minimax PRESENT: installed, and the snapshot dir comes back",
          ok_ is True and s_ == snap and why == "")
    check("a DIFFERENT pin reads as not installed (the pin is half the path)",
          music.minimax_installed(td, "deadbeef", cache)[0] is False)

    # acestep
    check("acestep ABSENT", music.acestep_installed(td)[0] is False)
    bd = os.path.join(td, "data", "acestep", "src", "build")
    os.makedirs(bd)
    for b in ("ace-lm", "ace-synth"):
        p = os.path.join(bd, b); open(p, "w").close(); os.chmod(p, 0o755)
    ok_, _s, why = music.acestep_installed(td)
    check("acestep PARTIAL: built but no model files → not installed",
          ok_ is False and "model files" in why)
    md = os.path.join(td, "data", "acestep", "models")
    os.makedirs(md)
    for f in music.ACESTEP_GGUFS[:-1]:
        open(os.path.join(md, f), "w").close()
    check("acestep PARTIAL: three of four GGUFs → still not installed",
          music.acestep_installed(td)[0] is False)
    open(os.path.join(md, music.ACESTEP_GGUFS[-1]), "w").close()
    check("acestep PRESENT: both binaries + all four GGUFs",
          music.acestep_installed(td)[0] is True)
    os.chmod(os.path.join(bd, "ace-lm"), 0o644)
    check("a NON-EXECUTABLE binary reads as not installed (a failed build)",
          music.acestep_installed(td)[0] is False)
    check("engine_installed routes both engines and refuses a third",
          music.engine_installed(td, "nope")[0] is False)

# ══ 6. library listing, sidecar pairing, containment ═════════════════════════
with tempfile.TemporaryDirectory() as td:
    d = music.music_dir(td)
    check("the music dir is created under data/music", d.endswith(os.path.join("data", "music")))
    check("an empty library lists nothing", music.library_entries(td) == [])
    a = os.path.join(d, "acestep-20260820-100000.wav")
    b = os.path.join(d, "minimax-20260820-110000.wav")
    open(a, "w").write("aaa")
    time.sleep(0.02)
    open(b, "w").write("bb")
    json.dump({"engine": "minimax", "prompt": "rock", "seconds": 60, "steps": 30,
               "seed": 7, "wall": 115.5}, open(music.sidecar_path(b), "w"))
    open(os.path.join(d, "notes.txt"), "w").write("x")
    lib = music.library_entries(td)
    check("only .wav files are listed", len(lib) == 2)
    check("newest first", lib[0]["name"] == os.path.basename(b))
    check("the sidecar's metadata is married to its wav",
          lib[0]["engine"] == "minimax" and lib[0]["seed"] == 7 and lib[0]["wall"] == 115.5)
    check("a wav with NO sidecar is still listed (never lose a real file)",
          lib[1]["name"] == os.path.basename(a) and lib[1]["engine"] == "")
    check("size comes off disk", lib[1]["size_bytes"] == 3)
    open(music.sidecar_path(a), "w").write("{not json")
    check("a CORRUPT sidecar degrades to no metadata, it does not blank the library",
          len(music.library_entries(td)) == 2)

    good, why = music.library_target(td, os.path.basename(a))
    check("a real track resolves", good and os.path.isfile(good))
    for bad, label in [
        ("../../etc/passwd", "traversal"),
        ("/etc/passwd", "an absolute path"),
        ("sub/x.wav", "a subpath"),
        ("", "an empty name"),
        (None, "None"),
        (".", "a bare dot"),
        ("..", "dot-dot"),
        (".hidden.wav", "a dotfile"),
        ("nope.wav", "a track that does not exist"),
        ("notes.txt", "a non-wav file that IS in the folder"),
        (7, "a number"),
    ]:
        t, r = music.library_target(td, bad)
        check(f"CONTAINMENT refuses {label}", t is None and isinstance(r, str) and r)
    ok_, why = music.delete_track(td, os.path.basename(b))
    check("delete removes the wav AND its sidecar",
          ok_ and not os.path.exists(b) and not os.path.exists(music.sidecar_path(b)))
    check("delete of a refused name changes nothing",
          music.delete_track(td, "../x.wav")[0] is False and os.path.isfile(a))
    check("render_ok: a non-empty file is the ONLY success signal", music.render_ok(a))
    empty = os.path.join(d, "empty.wav"); open(empty, "w").close()
    check("render_ok: an EMPTY file is a failure (both engines can exit 0 with nothing)",
          music.render_ok(empty) is False)
    check("render_ok: a missing file is a failure", music.render_ok(os.path.join(d, "no.wav")) is False)
    check("render_ok: None is a failure", music.render_ok(None) is False)

check("track names are engine-stamped and time-ordered",
      music.track_name("acestep").startswith("acestep-")
      and music.track_name("acestep").endswith(".wav"))

# ══ 7. job state machine ═════════════════════════════════════════════════════
music.clear_job()
check("no job at rest", music.current_job() is None and music.job_busy() is False)
job, err = music.claim_job(P)
check("claiming the slot yields a queued job", err is None and job["state"] == "queued")
check("the job carries what the user asked for",
      job["engine"] == "minimax" and job["seconds"] == 60 and job["seed"] == 42)
j2, err2 = music.claim_job(P)
check("a SECOND claim is refused while one is live (never a queue)",
      j2 is None and "one at a time" in (err2 or ""))
check("job_busy reports the live job", music.job_busy() is True)

with tempfile.TemporaryDirectory() as td:
    seen = {}

    def fake_ok(root, params, workdir, out_path):
        seen["workdir"] = workdir
        seen["out"] = out_path
        open(out_path, "w").write("RIFF")
        return out_path

    music.run_job(td, P, job, render=fake_ok, log=lambda *a, **k: None)
    fin = music.current_job()
    check("a completed job is done, timed, and names its output",
          fin["state"] == "done" and fin["out"].endswith(".wav") and fin["wall"] is not None)
    check("the workdir is cleaned up afterwards", not os.path.isdir(seen["workdir"]))
    lib = music.library_entries(td)
    check("the finished track lands in the library", len(lib) == 1)
    check("the SIDECAR records everything needed to make the song again",
          lib[0]["engine"] == "minimax" and lib[0]["seed"] == 42
          and lib[0]["steps"] == 30 and lib[0]["seconds"] == 60
          and lib[0]["prompt"] == "gritty rock" and lib[0]["wall"] is not None)
    check("the slot is free again once a render finishes", music.job_busy() is False)

    music.clear_job()
    job2, _ = music.claim_job(P)

    def fake_fail(root, params, workdir, out_path):
        raise music.MusicError("engine exited 1\nMetal: out of memory")

    music.run_job(td, P, job2, render=fake_fail, log=lambda *a, **k: None)
    f = music.current_job()
    check("a failed job is marked failed", f["state"] == "failed")
    check("THE ENGINE'S OWN WORDS reach the user (the tail is carried, not swallowed)",
          "out of memory" in (f["error"] or ""))
    check("a failed render frees the slot", music.job_busy() is False)
    check("a failed render adds NO track and NO sidecar (only `lib` from before)",
          len(music.library_entries(td)) == len(lib))

    music.clear_job()
    job3, _ = music.claim_job(P)

    def fake_boom(root, params, workdir, out_path):
        raise RuntimeError("something nobody predicted")

    music.run_job(td, P, job3, render=fake_boom, log=lambda *a, **k: None)
    f3 = music.current_job()
    check("an UNEXPECTED exception still fails the job cleanly (never a wedged slot)",
          f3["state"] == "failed" and "unexpected" in (f3["error"] or "")
          and music.job_busy() is False)

music.clear_job()

# exit-0-with-no-audio is caught in the ENGINE renderers (run_job trusts whatever
# renderer it is handed), so pin it there — this is the invariant both engines need.
MUS = (ROOT / "bridge" / "music.py").read_text()
for fn in ("render_minimax", "render_acestep"):
    body = MUS.split(f"def {fn}(")[1].split("\ndef ")[0]
    check(f"{fn} defines success as render_ok, never the exit code",
          "render_ok(" in body and "produced no audio" in body)
check("a non-zero exit carries the engine's output tail into the error",
      "engine exited" in MUS and "STDERR_TAIL" in MUS)
check("a hung render is bounded by the 30-minute timeout",
      "timed out after" in MUS and "timeout=timeout" in MUS)

check("the render timeout is the spec's 30 minutes", music.MUSIC_TIMEOUT_S == 1800)

# ══ 7b. the RAM warning is an OVERRIDE, not a wall ═══════════════════════════
# The gate went from refusal to warning-with-confirm on Debi's ruling. The flag that
# turns a warning into a spend is therefore the most dangerous boolean in the lane:
# it must be impossible to set by accident, and impossible to skip silently.
for body, want in [({"confirm": True}, True), ({"confirm": "true"}, True),
                   ({"confirm": "TRUE"}, True), ({"confirm": "1"}, True),
                   ({"confirm": "yes"}, True),
                   ({}, False), (None, False), ({"confirm": False}, False),
                   ({"confirm": 1}, False), ({"confirm": "maybe"}, False),
                   ({"confirm": "0"}, False), ({"confirm": None}, False),
                   ({"confirm": []}, False), ("confirm", False)]:
    check(f"wants_confirm({body!r}) is {want}", music.wants_confirm(body) is want)

# ══ 7c. output formats (VERIFIED at the pins, not assumed) ═══════════════════
check("acestep's four encoders are exactly what ARCHITECTURE.md documents",
      music.ACESTEP_FORMATS == ("wav24", "wav32", "wav16", "mp3"))
check("minimax writes wav and ONLY wav (generate.py has no format argument at all)",
      music.MINIMAX_FORMATS == ("wav",))
check("the default acestep format is unchanged from v1 (wav24)",
      music.DEFAULT_FORMAT["acestep"] == "wav24")
check("an mp3 render is named .mp3, a wav render .wav",
      music.track_name("acestep", 0, "mp3").endswith(".mp3")
      and music.track_name("acestep", 0, "wav24").endswith(".wav"))
check("an unknown format still yields a .wav name rather than an extensionless file",
      music.track_name("acestep", 0, "nonsense").endswith(".wav"))
check("the format reaches the acestep request",
      music.acestep_request({**A, "format": "mp3"})["output_format"] == "mp3")
check("a junk format on the request falls back to the default, never onto the wire",
      music.acestep_request({**A, "format": "flac"})["output_format"] == "wav24")
check("the request still has exactly the six documented keys with a format set",
      set(music.acestep_request({**A, "format": "wav32"}))
      == {"caption", "lyrics", "duration", "seed", "inference_steps", "output_format"})
check("a valid acestep format validates through",
      V({"engine": "acestep", "prompt": "x", "format": "mp3"}, INST)[0]["format"] == "mp3")
check("an omitted format resolves to the engine's default in validation",
      V({"engine": "minimax", "prompt": "x"}, INST)[0]["format"] == "wav")

# ══ 7d. progress parsing + ETA ═══════════════════════════════════════════════
PP = music.parse_progress
check("tqdm percentage is read", PP("  45%|####      | 9/20")[0] == 0.45)
check("a bare N/M counter is read", PP("[3/5] Loading DAV decoder")[0] == 0.6)
check("the PHASE text comes back with it", "Loading" in PP("[3/5] Loading DAV decoder")[1])
check("MINIMAX'S RESTARTING STAGES: only the LAST segment is read, and within it the "
      "max wins so a bar never goes backwards",
      PP("[1/5] a\n[2/5] b\n[3/5] c\n[1/5] d\n[2/5] e\n[4/5] f")[0] == 0.8)
check("step counters partway through a run read partway through",
      PP("step 4/8 done")[0] == 0.5)
for junk in ("", None, 7, "no numbers here at all", "\n\n\n", "0/0 nothing",
             "[9/5] impossible", "999%|", "loading… please wait"):
    f_, ph = PP(junk)
    check(f"junk progress {junk!r} yields no false bar",
          (f_ is None or 0.0 <= f_ <= 1.0) and isinstance(ph, str))
check("a 100% line is read as complete by the PARSER (the CAP is applied on display)",
      PP("100%|##########| 20/20")[0] == 1.0)

E = music.estimate_wall
check("with NO history the measured calibration is used (60s minimax ≈ 115.5s)",
      E("minimax", 60) == 115.5)
check("acestep's calibration point", E("acestep", 60) == 24.5)
check("BETWEEN the two minimax points it interpolates rather than extrapolating a rate",
      100.0 < E("minimax", 100) < 676.0)
check("SUPERLINEARITY is honoured: 145s costs far more than 2x the 60s render",
      E("minimax", 145) == 675.6)
check("outside the known range it scales the nearest point proportionally",
      E("acestep", 120) == 49.0)
hist = [{"engine": "acestep", "seconds": 60, "wall": 30.0},
        {"engine": "minimax", "seconds": 60, "wall": 999.0}]
check("REAL history on this machine beats the calibration table",
      E("acestep", 60, hist) == 30.0)
check("history for a DIFFERENT engine is ignored", E("acestep", 60, [hist[1]]) == 24.5)
for junk in (None, "sixty", 0, -5, []):
    check(f"a junk length {junk!r} yields no estimate", E("minimax", junk) is None)
check("junk history rows are skipped rather than crashing the estimate",
      E("acestep", 60, [{"engine": "acestep", "seconds": "x", "wall": None}, "nope"]) == 24.5)
check("an unknown engine with no history has no estimate", E("nope", 60) is None)

pv = music.progress_view({"engine": "acestep", "seconds": 60, "state": "running",
                          "started": time.time()}, "[3/5] x")
check("THE 95% CAP: a running job never displays a completed bar",
      pv["progress"] <= music.PROGRESS_DISPLAY_CAP and music.PROGRESS_DISPLAY_CAP == 0.95)
check("a 100% RENDER line is capped to 95% while the job is still running",
      music.progress_view({"engine": "acestep", "seconds": 60, "state": "running",
                           "steps": 8, "started": time.time()},
                          "100%|#| 8/8")["progress"] == 0.95)
check("the view carries an ETA even when the engine says nothing",
      music.progress_view({"engine": "acestep", "seconds": 60, "state": "running",
                           "started": time.time()}, "")["eta_s"] == 24.5)
check("with no engine output the bar falls back to elapsed/estimate",
      music.progress_view({"engine": "acestep", "seconds": 60, "state": "running",
                           "started": time.time() - 12}, "")["source"] == "estimate")
check("a RENDER line WINS over the estimate",
      music.progress_view({"engine": "acestep", "seconds": 60, "state": "running",
                           "started": time.time()}, "[1/5] Sampling")["source"] == "engine")
check("a SETUP line does NOT claim to be engine progress",
      music.progress_view({"engine": "acestep", "seconds": 60, "state": "running",
                           "started": time.time()},
                          "[3/5] Loading the decoder")["source"] == "estimate")
check("a DONE job reads as complete", music.progress_view(
    {"engine": "acestep", "seconds": 60, "state": "done"})["progress"] == 1.0)
check("a FAILED job has no progress to show", music.progress_view(
    {"engine": "acestep", "seconds": 60, "state": "failed"})["progress"] is None)
check("progress_view is total over a junk job", music.progress_view(None)["progress"] is None)

# ══ 7e. templates ════════════════════════════════════════════════════════════
B = music.builtin_templates()
check("there are six starter templates", len(B) == 6)
check("every starter has a unique id", len({t["id"] for t in B}) == 6)
check("the starters cover the promised ground", {t["id"] for t in B}
      == {"neo-soul", "rock", "lofi", "cinematic", "edm", "folk"})
for t in B:
    # THE LOAD-BEARING ONE: a starter can never be a request the bridge would refuse.
    p_, e_ = V({"engine": "acestep", "prompt": t["prompt"], "lyrics": t["lyrics"],
                "seconds": t["seconds"]}, INST)
    check(f"starter {t['id']} validates unchanged", e_ is None)
    check(f"starter {t['id']} has a substantial caption", 700 < len(t["prompt"]) < 2400)
    check(f"starter {t['id']} declares a name and a tag", t["name"] and t["tag"])
    check(f"starter {t['id']} is marked builtin", t["builtin"] is True)
check("the two instrumental starters carry NO lyrics",
      all(next(t for t in B if t["id"] == i)["lyrics"] == "" for i in ("lofi", "cinematic")))
check("the vocal starters carry section tags the engines understand",
      all("[Chorus]" in next(t for t in B if t["id"] == i)["lyrics"]
          for i in ("neo-soul", "rock", "edm", "folk")))
B[0]["prompt"] = "MUTATED"
check("builtin_templates hands out COPIES — the table cannot be edited through it",
      music.builtin_templates()[0]["prompt"] != "MUTATED")

with tempfile.TemporaryDirectory() as td:
    check("with nothing saved, all_templates is just the starters",
          len(music.all_templates(td)) == 6 and music.user_templates(td) == [])
    t, err = music.save_template(td, {"name": "My thing", "prompt": "warm jazz",
                                      "lyrics": "", "seconds": 45, "engine": "acestep"})
    check("a template saves", err is None and t["name"] == "My thing")
    check("a saved template is NOT builtin and remembers the form",
          t["builtin"] is False and t["seconds"] == 45 and t["engine_hint"] == "acestep")
    check("it survives a reload from disk", len(music.user_templates(td)) == 1)
    check("starters come FIRST so a growing collection cannot bury them",
          music.all_templates(td)[0]["builtin"] is True
          and music.all_templates(td)[-1]["builtin"] is False)
    check("the templates file is written atomically (no .tmp left behind)",
          not os.path.exists(music.templates_path(td) + ".tmp"))
    for bad, why in [(None, "a non-dict"), ({}, "no name"),
                     ({"name": " ", "prompt": "x"}, "a blank name"),
                     ({"name": "n"}, "no prompt"),
                     ({"name": "n", "prompt": "  "}, "a blank prompt"),
                     ({"name": "n" * 61, "prompt": "x"}, "an over-long name"),
                     ({"name": "n", "prompt": "x" * 8001}, "an over-long prompt"),
                     ({"name": "n", "prompt": "x", "lyrics": "y" * 20001}, "over-long lyrics")]:
        r_, e_ = music.save_template(td, bad)
        check(f"REFUSED template: {why}", r_ is None and e_)
    check("a junk length degrades to the default rather than refusing the save",
          music.validate_template({"name": "n", "prompt": "x", "seconds": "soon"})[0]["seconds"]
          == music.SECONDS_DEFAULT)
    ok_, why = music.delete_template(td, t["id"])
    check("a user template deletes", ok_ and music.user_templates(td) == [])
    check("A BUILT-IN CAN NEVER BE DELETED (it is code — it would come back on restart)",
          music.delete_template(td, "rock")[0] is False
          and len(music.builtin_templates()) == 6)
    check("deleting something that is not there says so",
          music.delete_template(td, "nope")[0] is False)
    check("deleting nothing at all is refused", music.delete_template(td, "")[0] is False)
    open(music.templates_path(td), "w").write("{not a list")
    check("a CORRUPT templates file degrades to the starters, it does not blank the page",
          music.user_templates(td) == [] and len(music.all_templates(td)) == 6)

# ══ 7f. output folder ════════════════════════════════════════════════════════
with tempfile.TemporaryDirectory() as td:
    check("the default output dir is data/music",
          music.music_dir(td) == music.music_base_dir(td))
    out = os.path.join(td, "elsewhere", "songs")
    p_, why = music.validate_output_dir(td, out)
    check("a repo-relative folder is accepted and created", p_ and os.path.isdir(p_))
    music.write_settings(td, {"output_dir": p_})
    check("the library then follows the setting",
          os.path.realpath(music.music_dir(td)) == os.path.realpath(p_))
    open(os.path.join(p_, "acestep-x.wav"), "w").write("a")
    check("listing follows the configured folder", len(music.library_entries(td)) == 1)
    check("CONTAINMENT now anchors on the CONFIGURED folder",
          music.library_target(td, "acestep-x.wav")[0]
          and music.library_target(td, "../../etc/passwd")[0] is None)
    music.write_settings(td, {"output_dir": os.path.join(td, "gone", "away")})
    check("a configured folder that disappeared still resolves (it is recreated)",
          os.path.isdir(music.music_dir(td)))
    music.write_settings(td, {})
    check("clearing the setting returns to the default",
          music.music_dir(td) == music.music_base_dir(td))
    check("settings survive a round trip", music.read_settings(td) == {})
    open(music.settings_path(td), "w").write("[]")
    check("a junk settings file degrades to defaults",
          music.read_settings(td) == {} and music.music_dir(td) == music.music_base_dir(td))
    for bad, why in [("", "an empty path"), (None, "None"), (7, "a number"),
                     ("/etc", "a folder outside home and the repo"),
                     ("vendor/hermes", "anything inside vendor/")]:
        r_, e_ = music.validate_output_dir(td, bad)
        check(f"OUTPUT DIR refuses {why}", r_ is None and isinstance(e_, str) and e_)
    f = os.path.join(td, "afile"); open(f, "w").write("x")
    check("a path that is a FILE is refused", music.validate_output_dir(td, f)[0] is None)
    check("~ is expanded rather than taken literally",
          "~" not in (music.validate_output_dir(td, "~")[0] or ""))

# ══ 7g. convert ══════════════════════════════════════════════════════════════
check("convert targets are mp3 and m4a only (no video in this slice)",
      set(music.CONVERT_FORMATS) == {"mp3", "m4a"})
check("mp3 goes through libmp3lame, m4a through aac",
      music.CONVERT_FORMATS["mp3"]["encoder"] == "libmp3lame"
      and music.CONVERT_FORMATS["m4a"]["encoder"] == "aac")
cav = music.convert_argv("/f/ffmpeg", "/d/a.wav", "/d/a.mp3", "mp3")
check("convert argv names the encoder, the bitrate and both files",
      cav[0] == "/f/ffmpeg" and "-c:a" in cav
      and cav[cav.index("-c:a") + 1] == "libmp3lame"
      and cav[cav.index("-b:a") + 1] == "192k"
      and cav[cav.index("-i") + 1] == "/d/a.wav" and cav[-1] == "/d/a.mp3")
check("every convert argv element is a string", all(isinstance(x, str) for x in cav))
FAKE_ENC = (" V....D libx264              H.264\n"
            " A....D aac                  AAC (Advanced Audio Coding)\n"
            " A....D libmp3lame           MP3 (MPEG audio layer 3)\n")
check("a build WITH both encoders offers both",
      set(music.convert_formats(music.ffmpeg_encoders(run=lambda a: FAKE_ENC,
                                                      ffmpeg="/f"))) == {"mp3", "m4a"})
check("A BUILD WITHOUT libmp3lame SIMPLY DOES NOT OFFER MP3 (absent, not greyed out)",
      music.convert_formats(music.ffmpeg_encoders(
          run=lambda a: " A....D aac  AAC\n", ffmpeg="/f")) == ["m4a"])
check("no ffmpeg at all offers nothing",
      music.convert_formats(music.ffmpeg_encoders(run=lambda a: "", ffmpeg="/f")) == [])
check("a probe that throws offers nothing rather than breaking the page",
      music.convert_formats(music.ffmpeg_encoders(
          run=lambda a: (_ for _ in ()).throw(OSError("boom")), ffmpeg="/f")) == [])

with tempfile.TemporaryDirectory() as td:
    d = music.music_dir(td)
    w = os.path.join(d, "acestep-20260820-120000.wav")
    open(w, "w").write("RIFF")
    json.dump({"engine": "acestep", "seconds": 60, "wall": 24.5},
              open(music.sidecar_path(w), "w"))
    enc = {"libmp3lame", "aac"}
    check("converting refuses an unknown format",
          music.convert_track(td, os.path.basename(w), "ogg", ffmpeg="/f", encoders=enc)[0] is None)
    check("converting refuses a track that is not there",
          music.convert_track(td, "nope.wav", "mp3", ffmpeg="/f", encoders=enc)[0] is None)
    check("converting refuses a traversal name",
          music.convert_track(td, "../x.wav", "mp3", ffmpeg="/f", encoders=enc)[0] is None)
    check("converting refuses when this build lacks the encoder",
          music.convert_track(td, os.path.basename(w), "mp3", ffmpeg="/f",
                              encoders={"aac"})[0] is None)
    m = os.path.splitext(w)[0] + ".mp3"
    open(m, "w").write("ID3")
    check("NEVER CLOBBERS — an existing conversion is refused, not overwritten",
          music.convert_track(td, os.path.basename(w), "mp3", ffmpeg="/f",
                              encoders=enc)[0] is None
          and open(m).read() == "ID3")
    check("converting an mp3 TO mp3 is refused as already-that-format",
          music.convert_track(td, os.path.basename(m), "mp3", ffmpeg="/f",
                              encoders=enc)[0] is None)
    lib = music.library_entries(td)
    check("CONVERTED FILES ARE LISTED beside their source", len(lib) == 2)
    check("each carries its own extension",
          {e["ext"] for e in lib} == {"wav", "mp3"})
    check("THE SIDECAR IS SHARED — both rows know the prompt and the render time",
          all(e["wall"] == 24.5 for e in lib))
    a4 = os.path.join(d, "acestep-20260820-130000.m4a")
    open(a4, "w").write("ftyp")
    check("an .m4a is addressable and listed too",
          # realpath both sides: macOS tempdirs live under /var -> /private/var,
          # and library_target answers with the realpath
          music.library_target(td, os.path.basename(a4))[0] == os.path.realpath(a4)
          and len(music.library_entries(td)) == 3)
    check("a .txt in the same folder is still refused",
          music.library_target(td, "notes.txt")[0] is None)
    os.remove(a4)
    ok_, _r = music.delete_track(td, os.path.basename(m))
    check("deleting the mp3 leaves the wav AND the shared sidecar alone",
          ok_ and os.path.isfile(w) and os.path.isfile(music.sidecar_path(w)))
    ok_, _r = music.delete_track(td, os.path.basename(w))
    check("deleting the LAST audio of a stem finally removes the sidecar",
          ok_ and not os.path.exists(music.sidecar_path(w)))

# ══ 8. wiring: bridge endpoints, log name, ledger, script, panel ═════════════
APP = _APP_SOURCE
for route in ('@app.get("/api/music/status")', '@app.post("/api/music/install")',
              '@app.post("/api/music/generate")', '@app.get("/api/music/jobs")',
              '@app.get("/api/music/library")', '@app.get("/api/music/file/{name}")',
              '@app.post("/api/music/delete")'):
    check(f"endpoint exists: {route}", route in APP)
check("the install log is viewable in-panel (the voicebox-install lesson)",
      '"music-install"' in APP and "_LOG_NAMES" in APP)
check("generate answers to the SAME ledger every other loader answers to",
      "_music.ram_gate(" in APP and "_loaded_models_bytes()" in APP
      and "_budget_bytes()" in APP)
check("a ledger refusal is a 409, not a silent start",
      "status_code=409" in APP.split("def music_generate")[1][:2000])
check("validation runs BEFORE the ledger, and the ledger BEFORE the job is claimed",
      APP.split("def music_generate")[1].index("validate_generate")
      < APP.split("def music_generate")[1].index("ram_gate")
      < APP.split("def music_generate")[1].index("start_job"))
check("acestep's cmake precondition is checked BEFORE anything is spawned",
      "brew install cmake" in APP
      and APP.split("def music_install")[1].index("cmake_bin")
      < APP.split("def music_install")[1].index("Thread"))
check("install runs on a BACKGROUND thread with the component-install timeout",
      "_MUSIC_INSTALL_TIMEOUT = 7200" in APP and "_music_install_thread" in APP)
check("installed is computed FROM DISK on every status, never from a stored flag",
      "engine_installed(ROOT" in APP)
check("the licence line reuses LICENSE_OVERRIDES rather than duplicating the record",
      'license_override("MiniMaxAI/MiniMax-Music3")' in APP)
check("the music module is imported DEFENSIVELY like voice", "_MUSIC_ERR" in APP)
check("/file serves audio with the right MIME", 'media_type="audio/wav"' in APP)
check("one [music] render line per job reaches the bridge log",
      "[music] render" in APP or "[music] render" in (ROOT / "bridge" / "music.py").read_text())

SH = (ROOT / "scripts" / "install_music.sh").read_text()
check("the installer takes both engines", "minimax) do_minimax" in SH and "acestep) do_acestep" in SH)
check("pins are read from harness.yaml, never hardcoded in the script",
      "_yb music_minimax_pin" in SH and "_yb acestep_pin" in SH)
check("the installer writes the panel-viewable install log",
      "data/logs/music-install.log" in SH)
check("the acestep build uses cmake DIRECTLY, never upstream's Linux-only buildcpu.sh",
      "buildcpu.sh" in SH and "NOT ./buildcpu.sh" in SH and "cmake -S" not in SH
      and '"$cmake_bin" -S' in SH)
check("NEVER launch upstream's server.sh (it binds 0.0.0.0)", "server.sh" not in SH)
check("the minimax venv is deliberately NOT data/mlx-venv",
      "data/music-venv" in SH and "mlx-venv" in SH)
check("the snapshot's sibling module is verified before the install claims success",
      "minimax_mlx_model.py" in SH)
check("cmake is resolved by EXPLICIT path list (Finder-minimal PATH rule)",
      "/opt/homebrew/bin/cmake" in SH)
check("the GGUFs are re-linked from the pinned HF snapshot, not copied",
      'ln -sfn "$p"' in SH and 'revision=sys.argv[3]' in SH
      and 'snapshots/"$gguf_pin"/"$f"' in SH)
check("a user-owned model file is never overwritten by the managed snapshot link",
      "refusing to replace non-symlink model file" in SH)

YML = (ROOT / "harness.yaml").read_text()
check("build.music_minimax_pin exists and is the measured revision",
      "music_minimax_pin" in YML and REV in YML)
check("build.acestep_pin exists and is the measured commit",
      "acestep_pin" in YML and "9761469d95fc204b5468623c68a1a2203e50b1f9" in YML)
check("build.music_acestep_gguf_pin is an exact HF snapshot commit",
      bool(re.search(r'music_acestep_gguf_pin:\s*"[0-9a-f]{40}"', YML)))

PANEL = (ROOT / "bridge" / "panel" / "index.html").read_text()
check("the Music view exists", 'id="view-music"' in PANEL)
# STUDIO PHASE 2: the sidebar is RENDERED from the nav registry, so the row is a
# registry entry (with its own id, icon and native tab) rather than literal markup.
check("the sidebar has a Music entry",
      "id:'music'" in PANEL and "showView('music')" in PANEL
      and 'id="nav-' in PANEL)
check("showView routes to it", "document.getElementById('view-music').hidden" in PANEL)
# ⚠️ WIDENED AT THE CONSOLIDATION SLICE (Debi 2026-08-29), NOT WEAKENED. ⌘K "Music" now
# opens the STUDIO — the one Music door, the same call the sidebar row makes — so the
# palette must also carry a NAMED way to the Classic look rather than making it the
# thing you get by accident. Both prompt-jumps stay reachable, and the Classic one says
# which surface it lands on instead of being a second "Generate music".
check("the palette can reach Music AND the prompt",
      "{t:'Music'" in PANEL and "{t:'Generate music (Classic)'" in PANEL)
check("...and names the Classic look as its own destination",
      "{t:'Music Classic'" in PANEL and "f:openMusicClassic}" in PANEL)
check("...while ⌘K Music opens the one door, exactly as the sidebar row does",
      "{t:'Music', k:'♫', f:()=>navOpen('compose')}" in PANEL)
check("the log dialog lists the music install log", "'music-install'" in PANEL)
check("the panel POLLS ONLY WHILE SOMETHING RUNS",
      "function musicNeedsPoll()" in PANEL and "if (musicPollT || !musicNeedsPoll()) return;" in PANEL)
# 2026-08-21: the retire still happens on leaving, but it now has exactly ONE honest
# exception — a music PEEK keeps that view on screen over another page, so its poll must
# survive the navigation underneath it. The exception is asserted here BY NAME so it can
# never quietly widen into "the poll leaks".
check("the poll is retired when leaving the view",
      "else if (!(peekState && peekState.view === 'music')) stopMusicPoll();" in PANEL
      and "function stopMusicPoll()" in PANEL)
check("…and closing a music peek retires it too (the only exception closes itself)",
      "if (st.view === 'music' && curView !== 'music' && typeof stopMusicPoll === 'function')"
      in PANEL)
check("all three sections are rendered",
      "function renderMusicEngines(" in PANEL and "function renderMusicCreate(" in PANEL
      and "function renderMusicLibrary(" in PANEL)
check("the engine picker auto-picks when only one is installed",
      "musicEngine = inst[0] || null" in PANEL)
check("a running render disables Generate and shows an elapsed clock",
      "elapsed" in PANEL.split("function musicPaintState")[1][:2600]
      and "btn.disabled = !!running" in PANEL)
# v1 promised "a render cannot be stopped". That was over-caution, not a finding, and
# v1.2 built the cancel — so the promise must be GONE from every surface, not merely
# contradicted by a new button.
check("the 'cannot be stopped' copy is gone from the panel",
      "cannot be stopped" not in PANEL)
check("ledger refusals surface inline in the bridge's own words",
      "musicErr = (res && res.error)" in PANEL)
check("Get is ARMED — the first click states the download size, the second spends it",
      "btn._armed" in PANEL and "Download ${e.size_gb} GB?" in PANEL)
check("delete is two-step (a generated track cannot be re-made)",
      "del._armed" in PANEL and "sure?" in PANEL)
check("only ONE row carries an <audio> element",
      "const playing = musicPlay || musicLib[0].name;" in PANEL)
check("the player is styled INLINE — the Music view adds zero CSS rules",
      "a.style.width = '100%'" in PANEL and ".music-audio" not in PANEL)
check("reveal-in-Finder rides the existing /api/open allowlist",
      "action: 'reveal'" in PANEL)
check("a background re-render cannot eat a half-typed prompt",
      "document.activeElement" in PANEL.split("function renderMusicCreate")[1][:2400])
check("THE ONCE-A-SECOND TICKER REPAINTS STATE, it does not rebuild the form",
      "box._sig = sig" in PANEL
      and "musicPaintState(job, running); return;" in PANEL
      and "renderMusicCreate();" in PANEL.split("musicPollT = setInterval")[1][:900])

# ══ 9. wiring for v1.1 (warning-with-override, progress, templates, dir, formats) ══
for route in ('@app.get("/api/music/templates")', '@app.post("/api/music/templates")',
              '@app.post("/api/music/templates/delete")',
              '@app.get("/api/music/settings")', '@app.post("/api/music/settings")',
              '@app.post("/api/music/convert")'):
    check(f"endpoint exists: {route}", route in APP)
GEN = APP.split("def music_generate")[1][:3000]
check("the ledger warning is only skipped when the caller EXPLICITLY confirmed",
      "wants_confirm(body)" in GEN and "needs_confirm" in GEN)
check("an unconfirmed over-budget render is still a 409, never a silent start",
      "status_code=409" in GEN)
check("an over-budget render that WAS confirmed is recorded in the bridge log",
      "confirmed by the user" in APP)
check("progress rides the SAME job dict rather than a second one",
      "progress_view" in APP and "_music_job_view" in APP)
check("the ETA is fitted to what renders actually cost on THIS machine",
      "_music_history" in APP and "library_entries(ROOT)" in APP)
check("the temp log path is never handed to the panel", 'job.pop("log"' in APP)
check("converting reuses the voice lane's ONE ffmpeg resolver, never a second one",
      "from . import voice as _voice" in MUS and "ffmpeg_bin" in MUS
      and "shutil.which(\"ffmpeg\")" not in MUS)
check("/file answers with the right MIME per extension",
      '"audio/mpeg"' in APP and '"audio/mp4"' in APP)
check("the engines' output is streamed to a FILE so progress can be watched",
      "log_path" in MUS and "stderr=subprocess.STDOUT" in MUS)

check("the panel renders the templates strip", "function renderMusicTemplates(" in PANEL)
check("a template PREFILLS and does not generate by itself",
      "function musicUseTemplate(" in PANEL
      and "if (andGo) musicGenerate();" in PANEL)
check("the user can save the current form as a template",
      "function musicSaveTemplate(" in PANEL and "/api/music/templates" in PANEL)
check("a user template deletes two-step; a built-in has no delete drawn",
      "function musicDelTemplate(" in PANEL and "t.builtin ? ''" in PANEL)
check("the RAM warning offers a way through, in the bridge's own words",
      "res.needs_confirm" in PANEL and "Generate anyway" in PANEL
      and "musicGenerate(true)" in PANEL)
check("a confirmed render sends confirm:true", "body.confirm = true" in PANEL)
check("the progress bar REUSES the download-bar classes — still zero new CSS",
      'class="dlbar"' in PANEL.split("function renderMusicCreate")[1][:9000]
      and "mus-fill" in PANEL)
check("elapsed and an estimated time-left are both shown",
      "left (estimated)" in PANEL and "function musicClock(" in PANEL)
check("the output folder is always visible and changeable",
      "function renderMusicOutDir(" in PANEL and "saving to:" in PANEL
      and "function musicSetOutDir(" in PANEL)
check("the folder is a TYPED path (WKWebView has no folder picker)",
      'id="mus-dir"' in PANEL and "webkitdirectory" not in PANEL)
check("a format picker is drawn only when the engine has more than one",
      "fmts.length > 1" in PANEL and 'id="mus-fmt"' in PANEL)
check("library rows offer only the conversions this ffmpeg can do",
      "convert_formats" in PANEL and "/api/music/convert" in PANEL)
check("a conversion that already exists is not offered again",
      "haveExts.indexOf(f) >= 0" in PANEL)
# ══ 10. v1.2 — the deck, the phase-aware bar, the power-law ETA, and CANCEL ══════
# THE LIVE BUG, root-caused from the pinned sources and reproduced here as the exact
# log minimax writes: generate.py routes EVERY stage through one `progress()` helper
# ("[N/5] message"), the pipeline constructor emits 1,2,3 and .generate() RESTARTS at
# 1. A global maximum therefore pinned the bar at 3/5 = 0.60 with the phase text frozen
# on "Loading … DAV decoder into MLX…" for the whole render — Debi's screenshot.
MINIMAX_LOG = (
    "[1/5] Loading MiniMax-Music3 autoregressive model into MLX…\n"
    "[2/5] Loading MiniMax-Music3 flow transformer into MLX…\n"
    "[3/5] Loading MiniMax-Music3 DAV decoder into MLX…\n"
    "[1/5] Generating MiniMax-Music3 acoustic tokens with MLX…\n"
    "[2/5] Sampling MiniMax-Music3 flow transformer (30 steps)…\n"
)
S = music.progress_scan
sc = S(MINIMAX_LOG, 30)
check("PHASE MODEL: minimax's restarted counter is read as the RENDER phase",
      sc["kind"] == "render")
check("the phase text is the RENDER line, not the frozen loader line",
      "Sampling" in sc["phase"] and "Loading" not in sc["phase"])
check("the render fraction comes from the render segment only", sc["frac"] == 0.4)
loader_only = S("\n".join(MINIMAX_LOG.splitlines()[:3]), 30)
check("while only the loader has spoken the phase is SETUP", loader_only["kind"] == "setup")
check("the loader's own counter never drives the bar — setup rides ELAPSED",
      music.overall_progress(loader_only, 0.0) == 0.0
      and music.overall_progress(loader_only, 30.0) == 0.075
      and music.overall_progress(loader_only, 600.0) == music.SETUP_SHARE)
check("SETUP IS CAPPED at its share, however long the load takes",
      music.overall_progress(loader_only, 99999.0) <= music.SETUP_SHARE)
check("the render phase maps onto the REST of the bar",
      abs(music.overall_progress(sc, 300.0) - (0.15 + 0.85 * 0.4)) < 1e-9)
check("THE REGRESSION IS GONE: the full minimax log no longer reads 0.60-and-stuck",
      abs(music.overall_progress(sc, 300.0) - 0.60) > 0.05)
# the loader line contains the word "decoder" — setup must be tested BEFORE render
check("'Loading … DAV decoder' is SETUP despite containing 'decod'",
      music.counter_kind(5, "Loading MiniMax-Music3 DAV decoder into MLX…", 30, "") == "setup")
check("a tqdm total equal to the requested step count is RENDER whatever it says",
      music.counter_kind(30, "", 30, "setup") == "render")
check("an unrecognised counter INHERITS the phase rather than inventing one",
      music.counter_kind(7, "", None, "render") == "render"
      and music.counter_kind(7, "", None, "") == "setup")
check("a loader bar counting FILES never moves the render fraction",
      S("Fetching 3/7 shards\nFetching 6/7 shards", 30)["kind"] == "setup")
check("a two-stage engine's second sweep starts a new segment (no stuck 100%)",
      S("step 8/8 sampling\nstep 1/8 sampling", 8)["frac"] == 0.125)
for junk in ("", None, 7, "no numbers", "[9/5] impossible", "999%|"):
    r = S(junk, 30)
    check(f"progress_scan is total over {junk!r}",
          isinstance(r, dict) and (r["frac"] is None or 0.0 <= r["frac"] <= 1.0))
check("overall_progress is total over a junk scan",
      music.overall_progress(None, 10) is not None
      and music.overall_progress({"kind": "render", "frac": "x"}, 10) is not None)

# THE POWER-LAW ETA. minimax is superlinear (b ≈ 2), so proportional scaling
# under-promised badly — Debi was shown "1m 32s left" twelve minutes into a 220s song.
fit = music.power_fit([(60, 115.5), (145, 675.6)])
check("two points give a real power-law fit", fit is not None and 1.8 < fit[1] < 2.2)
e220 = music.estimate_wall("minimax", 220)
check(f"the fit predicts a 220s minimax render in a sane band (got {e220})",
      e220 is not None and 1100.0 < e220 < 2400.0)
check("…and it is far above the old proportional answer (which is what lied)",
      e220 > 675.6 * 220 / 145)
check("a 220s render at 13 minutes elapsed is NEVER reported as nearly done",
      music.remaining_secs(780.0, 0.35, e220) > 300.0)
check("the estimate still honours an exact measured point", music.estimate_wall("minimax", 145) == 675.6)
check("one point only stays proportional (no curve to fit)", music.estimate_wall("acestep", 120) == 49.0)
check("a wild library cannot produce a wild exponent",
      music.POWER_B_MIN <= (music.power_fit([(10, 1.0), (20, 5000.0)]) or (0, 0))[1]
      <= music.POWER_B_MAX)
check("power_fit refuses a single distinct length", music.power_fit([(60, 1.0), (60, 2.0)]) is None)
check("power_fit is total over junk rows",
      music.power_fit([("x", 1), (60, 0), (0, 5), (60, 100.0), (120, 400.0)]) is not None)
R = music.remaining_secs
check("with no progress at all the estimate is simply the estimate", R(10, 0, 100) == 90.0)
check("a SPENT estimate with no engine progress says nothing rather than lying",
      R(500, 0, 100) is None)
check("once the render is measurable the observed rate leads",
      abs(R(100, 0.5, 100) - 100.0) < 1e-6)
check("remaining is never negative", R(100, 0.99, 10) >= 0)
for junk in ((None, None, None), ("x", "y", "z"), (10, None, None)):
    check(f"remaining_secs is total over {junk}", R(*junk) is None or R(*junk) >= 0)

# CANCEL — the state machine, driven with a fake renderer so no GPU is needed.
music.clear_job()
check("cancel refuses when nothing is rendering", music.cancel_job(log=lambda *a, **k: None)[0] is False)
with tempfile.TemporaryDirectory() as td:
    CP = dict(P); CP["engine"] = "acestep"
    job, err = music.claim_job(CP)
    check("a fresh job is not cancelled", job["cancel"] is False)

    def _cancelling_render(root, params, workdir, out_path):
        # the engine "started", wrote a partial file, then the user hit Cancel
        with open(out_path, "w") as fh:
            fh.write("partial")
        music.cancel_job(log=lambda *a, **k: None)
        raise music.MusicCancelled("cancelled")

    music.run_job(td, CP, job, render=_cancelling_render, log=lambda *a, **k: None)
    j = music.current_job()
    check("a cancelled render ends in the CANCELLED state", j["state"] == "cancelled")
    check("a cancelled render is not reported as a failure", not j.get("error"))
    check("a cancelled render names no output track", not j.get("out"))
    left = os.listdir(music.music_dir(td))
    check("the PARTIAL audio file is deleted", not any(x.endswith(".wav") for x in left))
    check("no sidecar survives, so a cancelled render can never enter the ETA history",
          not any(x.endswith(".json") for x in left))
    check("a cancelled render leaves an empty library", music.library_entries(td) == [])
music.clear_job()
check("MusicCancelled is a MusicError (one except-path for the caller)",
      issubclass(music.MusicCancelled, music.MusicError))
check("the engines start in their OWN PROCESS GROUP so a cancel reaches the whole tree",
      "start_new_session=True" in MUS)
check("cancel SIGTERMs the group first and escalates to SIGKILL",
      "SIGTERM" in MUS and "SIGKILL" in MUS and "killpg" in MUS
      and "CANCEL_GRACE_S = 5" in MUS)


class _FakeProc:
    def __init__(self, dies_after=0):
        self.pid, self.n, self.dies = 4242, 0, dies_after
        self.sent = []

    def poll(self):
        self.n += 1
        return 0 if self.n > self.dies else None


_orig_killpg, _orig_getpgid = os.killpg, os.getpgid
try:
    sent = []
    os.killpg = lambda g, s: sent.append(s)                      # noqa: E731
    os.getpgid = lambda p: 999                                   # noqa: E731
    how = music.kill_process_group(_FakeProc(dies_after=1), grace=1.0, sleep=lambda s: None)
    check("a child that dies on SIGTERM is never SIGKILLed",
          how == "term" and sent == [signal.SIGTERM])
    sent2 = []
    os.killpg = lambda g, s: sent2.append(s)                     # noqa: E731
    how2 = music.kill_process_group(_FakeProc(dies_after=99), grace=0.4, sleep=lambda s: None)
    check("a child that ignores SIGTERM is SIGKILLed after the grace period",
          how2 == "kill" and sent2 == [signal.SIGTERM, signal.SIGKILL])
    check("the whole process GROUP is signalled, never just the direct child",
          all(isinstance(s, int) for s in sent2))
finally:
    os.killpg, os.getpgid = _orig_killpg, _orig_getpgid
check("an already-dead child is a no-op, not an error",
      music.kill_process_group(None) == "gone")

# THE CANCEL PATH, RUN FOR REAL against actual subprocesses — no GPU needed, and the
# only way to know that start_new_session + killpg + communicate() actually compose.
with tempfile.TemporaryDirectory() as td:
    tail = music._run([sys.executable, "-c", 'print("[2/5] Sampling 30 steps")'],
                      log_path=os.path.join(td, "e.log"))
    check("_run streams a child's output to the job log and reads the tail back",
          "Sampling" in tail)
    check("_run also works without a log file (the piped branch)",
          "hi" in music._run([sys.executable, "-c", 'print("hi")']))
    try:
        music._run([sys.executable, "-c", "import sys;sys.exit(3)"])
        check("a non-zero exit raises", False)
    except music.MusicError as e:
        check("a non-zero exit raises with the code in it", "exited 3" in str(e))
    music.clear_job()
    music.claim_job(dict(P, engine="acestep"))
    outcome = {}

    def _body():
        try:
            music._run([sys.executable, "-c", "import time;time.sleep(30)"],
                       log_path=os.path.join(td, "c.log"))
            outcome["r"] = "finished"
        except music.MusicCancelled:
            outcome["r"] = "cancelled"
        except Exception as e:                                   # noqa: BLE001
            outcome["r"] = "error: " + str(e)[:60]

    th = threading.Thread(target=_body)
    th.start()
    time.sleep(0.8)
    ok_, _reason = music.cancel_job(log=lambda *a, **k: None)
    th.join(20)
    check("cancel_job reports success while a render is live", ok_ is True)
    check("A LIVE CHILD IS ACTUALLY KILLED and the run raises MusicCancelled "
          f"(got {outcome.get('r')!r})", outcome.get("r") == "cancelled")
    check("the render thread did not have to wait out the 30-minute timeout",
          not th.is_alive())
music.clear_job()

# THE SEED RANGE — verified against generate.py at the pin, NOT taken from the spec.
check("the seed ceiling is the ENGINE's own bounded_int(0, 2**31 - 1)",
      music.SEED_MAX == 2 ** 31 - 1)
check("the seed help states that exact range (single-sourced from the constant)",
      str(music.SEED_MAX) in music.SEED_HELP and "4294967295" not in music.SEED_HELP)
check("the help explains reproducibility and the empty case",
      "same song" in music.SEED_HELP and "empty" in music.SEED_HELP)
check("a seed one past the engine's ceiling is refused before any subprocess",
      V({"engine": "minimax", "prompt": "x", "seed": 2 ** 31}, INST)[1] is not None)

# WIRING — bridge + panel
check("the cancel endpoint exists", '@app.post("/api/music/cancel")' in APP)
check("the cancel endpoint answers 409 when nothing is rendering",
      "status_code=409" in APP.split("def music_cancel")[1][:600])
check("the seed range travels to the panel rather than being retyped there",
      '"seed_max"' in APP and '"seed_help"' in APP)
check("the panel renders the seed help it was given, not a hardcoded range",
      "seed_help" in PANEL and "4294967295" not in PANEL)
check("the panel has a Cancel control and it is two-step armed",
      'id="mus-cancel"' in PANEL and "function musicCancel(" in PANEL
      and "/api/music/cancel" in PANEL)
check("Cancel is only shown while a render is running",
      "can.hidden = !running" in PANEL)
check("the progress line reads the bridge's blended remaining time",
      "pv.remaining_s" in PANEL)
check("when the remaining time cannot be said honestly the panel says THAT",
      "taking longer than estimated" in PANEL)

check("the per-page studio deck is one attribute on #view-music",
      'data-mview="studio"' in PANEL and "function toggleMusicView(" in PANEL
      and "v.dataset.mview = 'studio'" in PANEL)
check("the deck choice is persisted and classic is the default",
      "harness-music-view" in PANEL and "let musicView = 'classic'" in PANEL)
check("the deck toggle is independent of the theme and the global chrome axes",
      "harness-theme" not in PANEL.split("function toggleMusicView")[1][:500]
      and "harness-chrome" not in PANEL.split("function toggleMusicView")[1][:500])
check("the hero is EMPTIED in classic view, so classic carries no trace of the deck",
      "if (!musicStudio()){ box.hidden = true; box.innerHTML = ''; return; }" in PANEL)
check("the gallery cards exist and prefill on click",
      "function musicTplCard(" in PANEL and "musicUseTemplate(" in PANEL)
check("the card's inner chips cannot double-fire the card's own click",
      "event.stopPropagation()" in PANEL.split("function musicTplCard")[1][:1400])
check("a prefill SCROLLS to the form in BOTH views",
      "function musicScrollToCreate(" in PANEL
      and "else musicScrollToCreate();" in PANEL)
check("templates are a disclosure that opens by default only on an empty library",
      "function musicTplsOpen(" in PANEL and "!musicLib.length" in PANEL
      and "function toggleMusicTpls(" in PANEL)
check("both textareas auto-grow through the CHAT composer's growInput (shared, not copied)",
      "function growMusicInput(el){ growInput(el, MUSIC_GROW_MAX); }" in PANEL
      and PANEL.count("function growInput(") == 1
      and 'oninput="growMusicInput(this)"' in PANEL)
check("library rows show the recorded step count (it was stored but never displayed)",
      "steps` : ''" in PANEL or "steps`)" in PANEL)
check("the prompt moved behind a chip instead of being printed on every row",
      "function musicTogglePrompt(" in PANEL and "▸ prompt" in PANEL)
check("a row can re-use ALL of its settings in one click",
      "function musicReuse(" in PANEL and "seed: t.seed" in PANEL
      and "musicEngine = t.engine" in PANEL)
check("templates and library re-use share ONE prefill implementation",
      "function musicFill(" in PANEL and PANEL.count("function musicFill(") == 1)
check("the Policies nav stub is gone (its alert was a silent no-op in WKWebView)",
      "Policies UI lands in M2" not in PANEL)
check("every music activity-feed line passes a TAG and a MESSAGE (the `undefined` bug)",
      "feed('music'," in PANEL and "feed(`music:" not in PANEL)

# ══ WAVEFORM ANALYSIS (Compose v2) ═══════════════════════════════════════════
# THE RULE THIS SECTION EXISTS FOR: the Compose waveform's colour is the page's one
# saturated object, and nothing in this lane knows a song's musical structure. So the
# analysis may report ONLY what it measured, and it must return "no sections" rather
# than split audio that has no runs. Every function below is pure and table-tested.
print()
print("── waveform analysis (Compose v2) ──")

import array as _array                                            # noqa: E402
import math as _math                                              # noqa: E402


def _tone(sr, secs, amp):
    """A mono s16 buffer whose amplitude follows `amp(t)` — the only fixture needed."""
    out = _array.array("h")
    for i in range(int(sr * secs)):
        t = i / sr
        out.append(int(max(-1.0, min(1.0, amp(t) * _math.sin(2 * _math.pi * 220 * t)))
                       * 32000))
    return out


SR = music.ANALYSIS_SR
flat = _tone(SR, 30, lambda t: 0.5)
env_flat = music.envelope(flat, SR)
check("the envelope is one value per 0.25 s frame",
      abs(len(env_flat) - 30 / music.ANALYSIS_FRAME_S) <= 1)
check("a constant tone measures a constant envelope",
      max(env_flat) - min(env_flat) < 0.02)
check("NO SECTIONS ARE INVENTED: flat audio segments into nothing",
      music.segment(env_flat) == [])

# quiet 20 s → loud 40 s: a real change of level, and the only one there is.
two = _tone(SR, 20, lambda t: 0.12) + _tone(SR, 40, lambda t: 0.9)
secs2 = music.segment(music.envelope(two, SR))
check("audio that DOES change level segments into runs", len(secs2) == 2)
check("…the boundary lands where the audio actually changes",
      18 <= secs2[0]["end"] <= 22)
check("…the quieter run is ranked below the louder one",
      secs2[0]["level"] < secs2[1]["level"])
check("…and both are labelled by what was MEASURED, never by a musical role",
      all(s["label"] in music.ANALYSIS_LEVEL_NAMES for s in secs2))
check("no musical role can ever be produced by this lane",
      set(music.ANALYSIS_LEVEL_NAMES) == {"quiet", "steady", "loud"})

# A one-second dip inside a long loud passage is NOT a section.
blip = (_tone(SR, 20, lambda t: 0.9) + _tone(SR, 1, lambda t: 0.05)
        + _tone(SR, 20, lambda t: 0.9))
check("a one-second dip is merged away rather than drawn as its own section",
      all((s["end"] - s["start"]) >= music.ANALYSIS_MIN_SECTION_S - 0.3
          for s in music.segment(music.envelope(blip, SR))))
check("audio too short to have runs returns nothing", music.segment([0.4, 0.4, 0.4]) == [])

bars = music.peak_bars(music.envelope(two, SR))
check("the bars are normalised to this track's own loudest moment",
      abs(max(bars) - 1.0) < 1e-6 and min(bars) >= 0)
check("…and there are never more bars than the page can draw",
      len(bars) <= music.ANALYSIS_PEAKS)
check("the level clustering is DETERMINISTIC (the same audio is the same colour twice)",
      music.segment(music.envelope(two, SR)) == secs2)

with tempfile.TemporaryDirectory() as _d:
    _root = Path(_d)
    _mus = _root / "data" / "music"
    _mus.mkdir(parents=True)
    _wav = _mus / "acestep-20260101-000000.wav"
    import wave as _wave                                          # noqa: E402
    with _wave.open(str(_wav), "wb") as _fh:
        _fh.setnchannels(1); _fh.setsampwidth(2); _fh.setframerate(SR)
        _fh.writeframes(two.tobytes())
    a, reason = music.track_analysis(_root, _wav.name)
    check("track_analysis answers for a real file on disk", bool(a) and not reason)
    check("…with mode 'sections' only when the audio segmented",
          a["mode"] == "sections" and len(a["sections"]) == 2)
    check("…and marks itself DERIVED, with the method that produced it",
          a.get("derived") is True and "energy envelope" in a.get("method", ""))
    side = json.loads((_mus / "acestep-20260101-000000.json").read_text())
    check("…and caches into the track's own sidecar",
          isinstance(side.get("analysis"), dict))
    check("…keyed on the FILE's own identity, so a replaced file is re-measured",
          side["analysis"]["fingerprint"] == music.analysis_fingerprint(str(_wav)))
    a2, _ = music.track_analysis(_root, _wav.name, decode=lambda p: (None, 0))
    check("a cached analysis is served without decoding again", a2["peaks"] == a["peaks"])
    # A title written afterwards must not destroy the cached analysis (one sidecar,
    # two writers — the classic way a cache and a name quietly delete each other).
    music.set_track_title(_root, _wav.name, "Night Bus")
    side2 = json.loads((_mus / "acestep-20260101-000000.json").read_text())
    check("naming a track keeps its cached analysis (one sidecar, two writers)",
          side2.get("title") == "Night Bus" and isinstance(side2.get("analysis"), dict))
    # Flat audio: real bars, honest 'ramp', and an empty section list.
    _wav2 = _mus / "acestep-20260101-000001.wav"
    with _wave.open(str(_wav2), "wb") as _fh:
        _fh.setnchannels(1); _fh.setsampwidth(2); _fh.setframerate(SR)
        _fh.writeframes(flat.tobytes())
    b, _ = music.track_analysis(_root, _wav2.name)
    check("flat audio comes back as mode 'ramp' with NO sections",
          b["mode"] == "ramp" and b["sections"] == [])
    check("…and still carries real bars, so the page draws the amplitude it measured",
          len(b["peaks"]) > 8)
    # Containment is library_target's, and undecodable audio is a refusal, not a guess.
    none, why = music.track_analysis(_root, "../../etc/passwd")
    check("analysis refuses a path instead of a name", none is None and "refused" in why)
    none2, why2 = music.track_analysis(_root, "missing.wav")
    check("…and an absent track is 'no such track', never an empty waveform",
          none2 is None and why2 == "no such track")
    junk = _mus / "acestep-20260101-000002.wav"
    junk.write_bytes(b"not audio at all")
    none3, why3 = music.track_analysis(_root, junk.name, decode=lambda p: (None, 0))
    check("audio that cannot be decoded says so rather than drawing something",
          none3 is None and "could not be decoded" in why3)

print()
print(f"{'FAIL' if FAILS else 'OK'} — {len(FAILS)} failure(s)")
if FAILS:
    for f_ in FAILS:
        print("  -", f_)
sys.exit(1 if FAILS else 0)
