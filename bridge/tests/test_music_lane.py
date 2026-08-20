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
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
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
check("an INSTRUMENTAL passes no --lyrics-file at all (an empty file's meaning is undocumented)",
      "--lyrics-file" not in music.minimax_cmd("p", "/s", inst, "/w/l.txt", "/o.wav")["argv"])
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
check("the planning numbers are the spec's, NOT the understated measured RSS",
      music.MUSIC_RAM_GB == {"minimax": 32, "acestep": 9})
check("minimax on an empty machine within a 48GB budget: allowed",
      music.ram_gate("minimax", 0, 48 * GB) is None)
check("minimax with a 20GB model loaded: REFUSED",
      music.ram_gate("minimax", 20 * GB, 48 * GB) is not None)
check("the refusal names the way out", "eject" in
      (music.ram_gate("minimax", 20 * GB, 48 * GB) or ""))
check("acestep with the same 20GB model loaded: allowed (9 + 20 <= 48)",
      music.ram_gate("acestep", 20 * GB, 48 * GB) is None)
check("BOUNDARY IS INCLUSIVE — exactly filling the budget is allowed",
      music.ram_gate("minimax", 16 * GB, 48 * GB) is None)
check("one byte over the boundary is refused",
      music.ram_gate("minimax", 16 * GB + 1, 48 * GB) is not None)
check("acestep refused when it genuinely cannot fit",
      music.ram_gate("acestep", 40 * GB, 48 * GB) is not None)
check("junk 'other bytes' degrades to zero rather than crashing a request",
      music.ram_gate("acestep", None, 48 * GB) is None)
check("a junk budget refuses (fail toward the guard, never past it)",
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
    ({"engine": "acestep", "prompt": "x" * 2001}, "an over-long prompt"),
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

# ══ 8. wiring: bridge endpoints, log name, ledger, script, panel ═════════════
APP = (ROOT / "bridge" / "app.py").read_text()
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
check("the GGUFs are symlinked from the HF cache, not copied",
      'ln -sf "$p"' in SH)

YML = (ROOT / "harness.yaml").read_text()
check("build.music_minimax_pin exists and is the measured revision",
      "music_minimax_pin" in YML and REV in YML)
check("build.acestep_pin exists and is the measured commit",
      "acestep_pin" in YML and "9761469d95fc204b5468623c68a1a2203e50b1f9" in YML)

PANEL = (ROOT / "bridge" / "panel" / "index.html").read_text()
check("the Music view exists", 'id="view-music"' in PANEL)
check("the sidebar has a Music entry", 'id="nav-music"' in PANEL and "showView('music')" in PANEL)
check("showView routes to it", "document.getElementById('view-music').hidden" in PANEL)
check("the palette can reach Music AND the prompt",
      "{t:'Music'" in PANEL and "{t:'Generate music'" in PANEL)
check("the log dialog lists the music install log", "'music-install'" in PANEL)
check("the panel POLLS ONLY WHILE SOMETHING RUNS",
      "function musicNeedsPoll()" in PANEL and "if (musicPollT || !musicNeedsPoll()) return;" in PANEL)
check("the poll is retired when leaving the view",
      "else stopMusicPoll();" in PANEL and "function stopMusicPoll()" in PANEL)
check("all three sections are rendered",
      "function renderMusicEngines(" in PANEL and "function renderMusicCreate(" in PANEL
      and "function renderMusicLibrary(" in PANEL)
check("the engine picker auto-picks when only one is installed",
      "musicEngine = inst[0] || null" in PANEL)
check("a running render disables Generate and shows an elapsed clock",
      "elapsed" in PANEL.split("function musicPaintState")[1][:900]
      and "btn.disabled = !!running" in PANEL)
check("the UI says outright that a render cannot be stopped",
      "cannot be stopped" in PANEL)
check("there is deliberately NO cancel endpoint or button",
      "/api/music/cancel" not in PANEL and "/api/music/cancel" not in APP)
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

print()
print(f"{'FAIL' if FAILS else 'OK'} — {len(FAILS)} failure(s)")
if FAILS:
    for f_ in FAILS:
        print("  -", f_)
sys.exit(1 if FAILS else 0)
