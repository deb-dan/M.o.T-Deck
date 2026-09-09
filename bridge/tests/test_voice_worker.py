"""Unit tests for the PERSISTENT TTS WORKER (bridge/voice_worker.py + voice.VoiceWorker).

The worker itself can never run here: mlx is Apple-Silicon only. So this suite splits
in two, and the split IS the design:

  * the PROTOCOL half is pure python with every mlx import hidden inside a function,
    so bridge/voice_worker.py imports and is fully testable on Linux;
  * the STATE-MACHINE half runs REAL subprocesses against a FAKE worker script that
    speaks the same JSON-lines protocol. That exercises spawn, load, render, model
    change, death, timeout and the ledger — everything except the engine call.

What is pinned, and why each one is load-bearing:

  * CLI PARITY (render_kwargs). generate_audio()'s signature defaults differ from the
    CLI's: max_tokens is 1200 in the signature and None on the CLI, and voice defaults
    to "af_heart". A worker that silently truncated long replies, or imposed a Kokoro
    voice on Qwen3-TTS, would be a worse bug than the slowness it fixes.
  * TOTALITY. A malformed line, an unknown command and a failed render are all
    ok:false replies — the loop never dies on input.
  * LIFECYCLE. Respawn on model CHANGE; voice is per-request (never a reload); kill
    on clear/unload/delete; no idle timeout.
  * LOCKING. The worker path must NOT take voice._RENDER_LOCK — that is the whole
    point of the change (speaking no longer blocks dictation).
  * LEDGER. A resident worker's size counts; a dead one's does not.

Run: python3 bridge/tests/test_voice_worker.py    (from repo root)
"""
import json
import os
import subprocess
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
from bridge import voice            # noqa: E402
from bridge import voice_worker as vw   # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


# ── protocol: encode / decode / validate ────────────────────────────────────────
line = vw.encode_response({"id": 1, "ok": True})
check("a response is exactly one line", line.endswith("\n") and line.count("\n") == 1)
check("a response is ascii-safe json",
      json.loads(vw.encode_response({"id": 1, "ok": False, "error": "naïve"}))["error"]
      == "naïve")

r = vw.make_response(7, True, out="/tmp/a.wav")
check("make_response echoes the id", r["id"] == 7 and r["ok"] is True)
check("a successful response carries no error key", "error" not in r)
check("make_response passes extras through", r["out"] == "/tmp/a.wav")
check("a non-int id degrades to 0", vw.make_response("x", False, "e")["id"] == 0)
check("an error response always has a message",
      vw.make_response(1, False, "")["error"] == "unknown error")

req, err = vw.decode_request('{"id":1,"cmd":"ping"}')
check("a good line decodes", err == "" and req["cmd"] == "ping")
check("a malformed line is an error, not an exception",
      vw.decode_request("{not json")[1].startswith("malformed json"))
check("an empty line is an error", vw.decode_request("  \n")[1] == "empty request")
check("a json ARRAY is refused", vw.decode_request("[1,2]")[1] == "request must be a json object")

check("ping validates", vw.validate_request({"cmd": "ping"}) == "")
check("an unknown cmd is named in the error",
      "unknown cmd" in vw.validate_request({"cmd": "sing"}))
check("load needs a model", vw.validate_request({"cmd": "load"}) == "load needs a model path")
check("tts needs text", vw.validate_request({"cmd": "tts", "out": "/x.wav"}) == "tts needs text")
check("tts needs an out path",
      vw.validate_request({"cmd": "tts", "text": "hi"}) == "tts needs an out path")
check("tts with both is valid",
      vw.validate_request({"cmd": "tts", "text": "hi", "out": "/x.wav"}) == "")
check("the command vocabulary is exactly ping/load/tts",
      set(vw.COMMANDS) == {"ping", "load", "tts"})

# ── CLI parity (the quiet-difference guard) ────────────────────────────────────
kw = vw.render_kwargs("hello there", "serena", "/tmp/x/out.wav")
check("render_kwargs splits out into output_path + file_prefix",
      kw["output_path"] == "/tmp/x" and kw["file_prefix"] == "out")
check("join_audio is ALWAYS on (else the engine writes out_000.wav parts)",
      kw["join_audio"] is True)
check("max_tokens is None like the CLI, NOT the signature's 1200",
      kw["max_tokens"] is None)
check("an empty voice becomes None, never '' and never af_heart",
      vw.render_kwargs("t", "", "/tmp/o.wav")["voice"] is None
      and vw.render_kwargs("t", None, "/tmp/o.wav")["voice"] is None)
check("a real voice is passed through trimmed", kw["voice"] == "serena")
check("verbose is off (the engine's chatter belongs in the log, not the protocol)",
      not kw["verbose"])
check("audio_format is wav", kw["audio_format"] == "wav")
for k, v in (("temperature", 0.7), ("top_p", 0.9), ("top_k", 50),
             ("repetition_penalty", 1.1), ("speed", 1.0), ("lang_code", "en")):
    check(f"CLI parity kwarg {k}={v}", kw[k] == v)
check("a bare filename still yields a usable output_path",
      vw.render_kwargs("t", None, "out.wav")["output_path"] == ".")

# ── _render_ok: the exit-0-on-failure invariant, restated worker-side ──────────
with tempfile.TemporaryDirectory() as td:
    empty = os.path.join(td, "empty.wav")
    open(empty, "wb").close()
    full = os.path.join(td, "full.wav")
    open(full, "wb").write(b"RIFF....")
    check("_render_ok: missing file is a failure", not vw._render_ok(os.path.join(td, "no.wav")))
    check("_render_ok: EMPTY file is a failure", not vw._render_ok(empty))
    check("_render_ok: a non-empty wav is success", vw._render_ok(full))

# ── TtsWorker.handle is total (no mlx needed for these branches) ───────────────
w = vw.TtsWorker()
check("ping before load reports loaded:false", w.handle({"id": 1, "cmd": "ping"})["loaded"] is False)
check("tts before load is refused, not crashed",
      w.handle({"id": 2, "cmd": "tts", "text": "hi", "out": "/tmp/a.wav"})["error"]
      == "no model loaded — send load first")
check("an unknown cmd returns ok:false", w.handle({"id": 3, "cmd": "nope"})["ok"] is False)


class _BoomWorker(vw.TtsWorker):
    def _load(self, path):
        raise RuntimeError("no mlx here")


b = _BoomWorker()
resp = b.handle({"id": 4, "cmd": "load", "model": "/M/x"})
check("a load exception becomes an error reply, not a crash",
      resp["ok"] is False and "no mlx here" in resp["error"])
check("a failed load leaves no half-loaded state", b.model is None and b.model_path == "")


class _FakeGen(vw.TtsWorker):
    """Model loads fine; generate writes (or doesn't) as told."""

    def __init__(self, write=True):
        super().__init__()
        self.write = write
        self.seen = None

    def _load(self, path):
        return object()

    def _generate(self, kwargs):
        self.seen = kwargs
        if self.write:
            p = os.path.join(kwargs["output_path"], kwargs["file_prefix"] + ".wav")
            open(p, "wb").write(b"RIFF" + b"\0" * 100)


with tempfile.TemporaryDirectory() as td:
    g = _FakeGen()
    check("load reports the path back", g.handle({"id": 1, "cmd": "load", "model": "/M/q"})["model"] == "/M/q")
    check("a second load of the SAME model is a no-op",
          g.handle({"id": 2, "cmd": "load", "model": "/M/q"})["cached"] is True)
    out = os.path.join(td, "out.wav")
    ok = g.handle({"id": 3, "cmd": "tts", "text": "hi", "voice": "ryan", "out": out})
    check("a good render replies ok with the byte count", ok["ok"] and ok["bytes"] > 0)
    check("the per-request voice reaches the engine", g.seen["voice"] == "ryan")
    check("the SAME worker renders again without reloading", g.model_path == "/M/q")

    bad = _FakeGen(write=False)
    bad.handle({"id": 1, "cmd": "load", "model": "/M/q"})
    r2 = bad.handle({"id": 2, "cmd": "tts", "text": "hi", "out": os.path.join(td, "b.wav")})
    check("EXIT-0 INVARIANT: no wav ⇒ ok:false even though generate_audio returned",
          r2["ok"] is False and "no audio" in r2["error"])

# ── serve(): the loop survives garbage and keeps going ────────────────────────
import io  # noqa: E402

buf = io.StringIO()
rc = vw.serve(iter(['{"id":1,"cmd":"ping"}\n', "garbage\n", '{"id":2,"cmd":"ping"}\n']), buf)
lines = [json.loads(x) for x in buf.getvalue().splitlines()]
check("serve answers every line, including the garbage one", len(lines) == 3)
check("the garbage line got an error reply and the loop continued",
      lines[0]["ok"] and lines[1]["ok"] is False and lines[2]["ok"])
check("serve returns 0 at EOF", rc == 0)

# ── the FAKE worker: real subprocesses, real pipes ────────────────────────────
FAKE = r'''
import json, os, sys, time
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "garbage":
    sys.stdout.write("hello i am not json\n"); sys.stdout.flush()
for line in sys.stdin:
    try:
        req = json.loads(line)
    except ValueError:
        continue
    cmd, rid = req.get("cmd"), req.get("id")
    if cmd == "load":
        if mode == "loadfail":
            print(json.dumps({"id": rid, "ok": False, "error": "fake load failure"}), flush=True)
            continue
        print(json.dumps({"id": rid, "ok": True, "model": req.get("model"), "secs": 0.0}), flush=True)
    elif cmd == "tts":
        if mode == "hang":
            time.sleep(30); continue
        if mode == "die":
            sys.exit(3)
        out = req["out"]
        if mode != "nowav":
            open(out, "wb").write(b"RIFF" + b"\0" * 64)
        # echo the reference back so the test can prove the pin reached the engine
        # cwd is the ROOT the worker was spawned in; the temp render dir is deleted
        open(os.path.join("data", "seen.json"), "w").write(
            json.dumps({"ref_audio": req.get("ref_audio"), "ref_text": req.get("ref_text"),
                        "voice": req.get("voice")}))
        print(json.dumps({"id": rid, "ok": True, "out": out, "bytes": 68}), flush=True)
    else:
        print(json.dumps({"id": rid, "ok": True}), flush=True)
'''


def fake_root(mode="ok"):
    """A ROOT whose bridge/voice_worker.py is the fake. Returns the tempdir path."""
    d = Path(tempfile.mkdtemp(prefix="vw-root-"))
    (d / "bridge").mkdir()
    (d / "data" / "logs").mkdir(parents=True)
    (d / "data" / "tmp").mkdir(parents=True)
    (d / "bridge" / "voice_worker.py").write_text(FAKE)
    os.environ["FAKE_MODE"] = mode
    return d


MLX_ENTRY = {"id": "qwen3-tts-mlx", "kind": "audio", "format": "tts-mlx",
             "path": "/M/qwen3", "size_bytes": 3_600_000_000}
MLX_OTHER = {"id": "kokoro-82m", "kind": "audio", "format": "tts-mlx",
             "path": "/M/kokoro", "size_bytes": 320_000_000}
GGUF_ENTRY = {"id": "qwen3-tts-q4", "kind": "audio", "format": "tts-gguf",
              "path": "/M/b.gguf", "mmproj": "/M/m.gguf", "size_bytes": 1_400_000_000}

check("worker_argv is [interpreter, script] and nothing else",
      voice.worker_argv("/venv/bin/python", "/r/bridge/voice_worker.py")
      == ["/venv/bin/python", "/r/bridge/voice_worker.py"])
check("the worker is launched by the MLX venv python, resolved by absolute path",
      voice.mlx_python("/r") in voice.worker_argv(voice.mlx_python("/r"),
                                                  voice.worker_script("/r"))
      and voice.worker_script("/r").endswith("bridge/voice_worker.py"))
check("the worker log lives at data/logs/voice-worker.log",
      voice.worker_log_path("/r").endswith("data/logs/voice-worker.log"))

R = fake_root()
try:
    voice.worker_stop()          # clean slate
    check("nothing resident before the first render", voice.worker_resident() is None)

    wav = voice.tts_render_worker(MLX_ENTRY, "hello", root=R, mlx_py=sys.executable)
    check("a worker render returns the wav bytes", wav.startswith(b"RIFF"))
    res = voice.worker_resident()
    check("the model is now RESIDENT", res and res["model"] == "qwen3-tts-mlx")
    check("residency reports the size the ledger will charge",
          res["size_bytes"] == 3_600_000_000)
    pid1 = res["pid"]

    voice.tts_render_worker(MLX_ENTRY, "again", root=R, mlx_py=sys.executable)
    check("a SECOND render reuses the SAME process (no reload)",
          voice.worker_resident()["pid"] == pid1)
    check("two renders counted on one worker", voice.worker_resident()["renders"] == 2)

    # a voice change must NOT respawn — the voice travels per request
    voice.tts_render_worker(dict(MLX_ENTRY, voice="serena"), "v", root=R,
                            mlx_py=sys.executable)
    check("changing the VOICE does not respawn the worker",
          voice.worker_resident()["pid"] == pid1)

    # REFERENCE AUDIO: same rule, and it is the ONLY voice control a zero-shot
    # model has — a clip change that cost a 3.6GB reload would be unusable.
    voice.tts_render_worker(dict(MLX_ENTRY, ref_audio="/lib/sample.wav",
                                 ref_text="one two"), "r", root=R, mlx_py=sys.executable)
    seen = json.loads((R / "data" / "seen.json").read_text())
    check("the pinned CLIP reaches the worker over the protocol",
          seen["ref_audio"] == "/lib/sample.wav" and seen["ref_text"] == "one two")
    check("changing the REFERENCE CLIP does not respawn the worker",
          voice.worker_resident()["pid"] == pid1)
    voice.tts_render_worker(MLX_ENTRY, "plain", root=R, mlx_py=sys.executable)
    check("an unpinned render sends an EMPTY reference (the worker normalises to None)",
          json.loads((R / "data" / "seen.json").read_text())["ref_audio"] == "")

    # a model change MUST respawn
    voice.tts_render_worker(MLX_OTHER, "other", root=R, mlx_py=sys.executable)
    res2 = voice.worker_resident()
    check("changing the MODEL respawns", res2["model"] == "kokoro-82m" and res2["pid"] != pid1)
    check("the ledger now reflects the NEW model's size", res2["size_bytes"] == 320_000_000)

    check("worker_stop_if_model ignores a different id",
          voice.worker_stop_if_model("not-me") is False and voice.worker_resident())
    check("worker_stop_if_model kills the matching id",
          voice.worker_stop_if_model("kokoro-82m") is True)
    check("after a stop nothing is resident (the ledger claim goes with it)",
          voice.worker_resident() is None)
    check("worker_stop is idempotent", voice.worker_stop() is False)

    # ── the ledger gate ───────────────────────────────────────────────────────
    refusals = []

    def deny(size):
        refusals.append(size)
        return "loading that voice model would exceed the model-RAM budget"

    try:
        voice.tts_render_worker(MLX_ENTRY, "hi", root=R, mlx_py=sys.executable,
                                spawn_guard=deny)
        check("a budget refusal raises VoiceBudget", False)
    except voice.VoiceBudget as e:
        check("a budget refusal raises VoiceBudget with the refusal text",
              "budget" in e.message)
    check("the guard is asked about the model's real size", refusals == [3_600_000_000])
    check("a refused spawn leaves NOTHING resident", voice.worker_resident() is None)
    check("VoiceBudget is a VoiceError (so no caller can miss it)",
          issubclass(voice.VoiceBudget, voice.VoiceError))

    allowed = []

    def allow(size):
        allowed.append(size)
        return None

    voice.tts_render_worker(MLX_ENTRY, "hi", root=R, mlx_py=sys.executable,
                            spawn_guard=allow)
    check("a passing guard lets the spawn through", voice.worker_resident() is not None)
    voice.tts_render_worker(MLX_ENTRY, "hi again", root=R, mlx_py=sys.executable,
                            spawn_guard=allow)
    check("the guard is NOT re-asked for an already-resident model", len(allowed) == 1)

    # ── the global one-shot lock must stay FREE during a worker render ────────
    held = []

    def probe():
        held.append(voice.render_lock().acquire(blocking=False))
        if held[-1]:
            voice.render_lock().release()

    t = threading.Thread(target=probe)
    t.start()
    t.join()
    check("the one-shot render lock is not held by the worker path", held == [True])

    # ── tts_render routing ────────────────────────────────────────────────────
    calls = []
    orig = voice.tts_render_worker
    voice.tts_render_worker = lambda *a, **k: (calls.append(a[0]["id"]) or b"WAV")
    try:
        voice.tts_render(MLX_ENTRY, "hi", root=R)
        check("tts_render routes tts-mlx to the worker", calls == ["qwen3-tts-mlx"])
        try:
            voice.tts_render(GGUF_ENTRY, "hi", root=R)
        except voice.VoiceError as e:
            check("tts-gguf still takes the ONE-SHOT llama-tts path",
                  "llama-tts not found" in e.message)
        check("tts-gguf never touched the worker", calls == ["qwen3-tts-mlx"])
        try:
            voice.tts_render(MLX_ENTRY, "hi", root=R, use_worker=False,
                             mlx_py="/definitely/not/here/python")
        except voice.VoiceError as e:
            check("use_worker=False falls back to the one-shot MLX path",
                  "MLX runtime is missing" in e.message)
        check("the fallback did not call the worker", calls == ["qwen3-tts-mlx"])
    finally:
        voice.tts_render_worker = orig
finally:
    voice.worker_stop()

# ── failure modes: hang, death, load failure, protocol garbage ────────────────
voice.WORKER_TIMEOUT_S_SAVED = voice.WORKER_TIMEOUT_S
try:
    voice.WORKER_TIMEOUT_S = 2
    R2 = fake_root("hang")
    try:
        voice.tts_render_worker(MLX_ENTRY, "hi", root=R2, mlx_py=sys.executable)
        check("a hung render times out", False)
    except voice.VoiceError as e:
        check("a hung render times out with a plain message", "did not answer" in e.message)
    check("a timed-out worker is KILLED, not left wedged", voice.worker_resident() is None)

    R3 = fake_root("die")
    try:
        voice.tts_render_worker(MLX_ENTRY, "hi", root=R3, mlx_py=sys.executable)
        check("a dying worker surfaces an error", False)
    except voice.VoiceError as e:
        check("a dying worker surfaces 'exited'", "exited" in e.message)
    check("a dead worker is not resident", voice.worker_resident() is None)

    R4 = fake_root("loadfail")
    try:
        voice.tts_render_worker(MLX_ENTRY, "hi", root=R4, mlx_py=sys.executable)
        check("a failed load raises", False)
    except voice.VoiceError as e:
        check("a failed load reports the worker's own message",
              "fake load failure" in e.message)
    check("a failed load leaves nothing running", voice.worker_resident() is None)

    R5 = fake_root("nowav")
    try:
        voice.tts_render_worker(MLX_ENTRY, "hi", root=R5, mlx_py=sys.executable)
        check("a render with no wav raises", False)
    except voice.VoiceError as e:
        check("the bridge re-checks render_ok even when the worker said ok",
              "produced no audio" in e.message)
finally:
    voice.WORKER_TIMEOUT_S = voice.WORKER_TIMEOUT_S_SAVED
    voice.worker_stop()
    os.environ.pop("FAKE_MODE", None)

# a missing interpreter must be a clean message, not a traceback
try:
    voice.tts_render_worker(MLX_ENTRY, "hi", root=fake_root(), mlx_py="/no/such/python")
    check("a missing MLX python raises", False)
except voice.VoiceError as e:
    check("a missing MLX python names install_mlx.sh", "install_mlx.sh" in e.message)
voice.worker_stop()

# ── busy: one in-flight request per worker ────────────────────────────────────
w = voice.VoiceWorker("x", "/M/x", 1, root=ROOT)
w._lock.acquire()
try:
    w.render("hi", "", "/tmp/x.wav")
    check("a second concurrent render is refused", False)
except voice.VoiceBusy as e:
    check("a second concurrent render raises VoiceBusy (→409, never a queue)",
          "already in progress" in e.message)
finally:
    w._lock.release()

# ── bridge wiring, read out of app.py's SOURCE (importing it builds clients) ──
APP = _APP_SOURCE
check("/api/voice/unload exists", '@app.post("/api/voice/unload")' in APP)
check("unload does NOT clear the default (it only frees RAM)",
      "worker_stop(\"unload requested\")" in APP)
check("/api/voice/config GET reports residency", '"resident": (_voice.worker_resident()' in APP)
check("the ledger counts a resident voice model", "_resident_voice_bytes()" in APP
      and "total += _resident_voice_bytes()" in APP)
check("the ledger charges nothing when no worker is alive (voice.worker_resident → None)",
      "worker_resident() or {}" in APP)
check("the spawn guard is handed to tts_render", "spawn_guard=_voice_spawn_guard" in APP)
check("a budget refusal is a 409, like the runner's",
      "except _voice.VoiceBudget" in APP)
check("clearing/changing the TTS default kills the worker",
      'if "tts_model" in updates and updates["tts_model"] != v_before["tts_model"]' in APP)
check("deleting a model kills it if resident", "worker_stop_if_model(mid" in APP)
# (2026-08-20) this used to pin the literal `"voice-worker")` — i.e. the CLOSING
# PAREN of the _LOG_NAMES tuple, which broke the moment another log name was added
# after it. The invariant was never "voice-worker is last"; it is "voice-worker is
# in _LOG_NAMES", so that is what is asserted now.
check("the worker log is viewable in-panel",
      '"voice-worker"' in APP.split("_LOG_NAMES = (")[1].split("\n\n")[0])
SH = (ROOT / "scripts" / "ship.sh").read_text()
check("ship.sh copies every bridge/*.py (voice_worker.py must reach the snapshot)",
      "bridge/*.py" in SH or 'bridge"/*.py' in SH)
PANEL = (ROOT / "bridge" / "panel" / "index.html").read_text()
check("the panel reads residency from /api/voice/config", "resident: r.resident || null" in PANEL)
check("the detail pane shows a resident pill", '<span class="mpill live">resident</span>' in PANEL)
check("the detail pane offers Unload", "voiceUnload()" in PANEL
      and "'/api/voice/unload'" in PANEL)
check("the voice worker log has a chip", "voice-worker" in PANEL)

print()
print(f"{'FAIL' if FAILS else 'OK'} — {len(FAILS)} failure(s)")
if FAILS:
    for f_ in FAILS:
        print("  -", f_)
sys.exit(1 if FAILS else 0)
