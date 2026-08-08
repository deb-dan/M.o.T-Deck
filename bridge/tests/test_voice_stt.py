"""Unit tests for the STT half of the voice capability (bridge/voice.py, Phase D).

Sibling of test_voice_tts.py and pinned for the same reasons: the argv surface is the
contract with a tool we cannot run in the sandbox, and the failure semantics are
counter-intuitive (exit 0 means nothing).

What is pinned here:

  * stt_argv, BOTH forms — the console-script form must carry `-f json -o <dir>`
    because the mlx_whisper CLI WRITES FILES and prints no transcript to stdout
    (Fable spec amendment §6). The library fallback must pass the model as
    path_or_hf_repo, never positionally after the audio.
  * the suffix decision table — what we accept, what we normalise, and above all
    WHICH inputs need ffmpeg. A wav must NOT need it: that is the one path that
    works on a machine with no optional voice component installed.
  * validate_stt_request — every refusal, including the size cap.
  * stt_read_output — file first, stdout second, and '' (the failure signal) when
    neither has a transcript. mlx_whisper prints a traceback and exits 0 on a bad
    model, so an empty read IS the error.
  * the bridge wiring facts, read out of app.py's source (never imported — it builds
    httpx clients at import time): the endpoint exists, it reads ?fmt=, it returns
    413/409/400, and it defaults to voice.stt_model.

Run: python3 bridge/tests/test_voice_stt.py   (from repo root)
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from bridge import voice  # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


MB = "/opt/harness/data/mlx-venv/bin/mlx_whisper"
MP = "/opt/harness/data/mlx-venv/bin/python"
FF = "/opt/harness/data/ffmpeg/bin/ffmpeg"

STT = {"id": "whisper-base-mlx", "kind": "audio", "format": "stt-mlx",
       "path": "/M/whisper-base", "size_bytes": 145_000_000}
TTS = {"id": "qwen3-tts-q4", "kind": "audio", "format": "tts-gguf",
       "path": "/M/b.gguf", "mmproj": "/M/m.gguf"}
CHAT = {"id": "gemma-4-31b", "format": "gguf", "path": "/M/g/model.gguf"}

# ── stt_argv: the console-script form (preferred) ────────────────────────────
a = voice.stt_argv(STT, "/tmp/x/in.wav", "/tmp/x", MB, MP)
check("script argv starts with the resolved mlx_whisper console script", a[0] == MB)
check("script argv is exactly the spec §6 surface",
      a == [MB, "/tmp/x/in.wav", "--model", "/M/whisper-base",
            "-f", "json", "-o", "/tmp/x", "--verbose", "False"])
check("script argv writes JSON (-f json) — the CLI does not print the transcript",
      a[a.index("-f") + 1] == "json")
check("script argv points -o at the temp dir we later read",
      a[a.index("-o") + 1] == "/tmp/x")
check("script argv silences per-segment stdout (--verbose False)",
      a[a.index("--verbose") + 1] == "False")
check("script argv passes the audio as ONE positional element",
      a[1] == "/tmp/x/in.wav")
check("script argv never invokes `python -m mlx_whisper` (no runnable __main__)",
      "-m" not in a)

# ── stt_argv: the library fallback ───────────────────────────────────────────
b = voice.stt_argv(STT, "/tmp/x/in.wav", "/tmp/x", MB, MP, use_script=False)
check("fallback argv runs the MLX venv interpreter", b[0] == MP)
check("fallback argv is python -c <program> <audio> <model>",
      b[1] == "-c" and b[2] == voice.STT_INLINE_PROGRAM
      and b[3] == "/tmp/x/in.wav" and b[4] == "/M/whisper-base")
check("fallback program passes the model as path_or_hf_repo (NOT positionally)",
      "path_or_hf_repo=sys.argv[2]" in voice.STT_INLINE_PROGRAM)
check("fallback program prints json to stdout (the only channel it has)",
      "print(json.dumps(" in voice.STT_INLINE_PROGRAM)
check("both forms name the SAME model path",
      a[a.index("--model") + 1] == b[4] == STT["path"])

for bad in (TTS, CHAT, {"format": "stt-onnx"}, {}):
    try:
        voice.stt_argv(bad, "/a.wav", "/t", MB, MP)
        check(f"stt_argv rejects a non-STT entry {bad.get('format')!r}", False)
    except ValueError:
        check(f"stt_argv rejects a non-STT entry {bad.get('format')!r}", True)

# ── suffix normalisation + the conversion decision table ─────────────────────
TABLE = [
    ("wav", "wav", False), (".WAV", "wav", False), ("audio/wav", "wav", False),
    ("audio/x-wav", "wav", False), ("audio/wave", "wav", False),
    ("webm", "webm", True), ("audio/webm;codecs=opus", "webm", True),
    ("mp4", "mp4", True), ("audio/mp4", "mp4", True), ("audio/x-m4a", "m4a", True),
    ("m4a", "m4a", True), ("mp3", "mp3", True), ("audio/mpeg", "mp3", True),
    ("ogg", "ogg", True), ("flac", "flac", True),
]
for raw, want, conv in TABLE:
    check(f"normalize_audio_suffix({raw!r}) → {want!r}",
          voice.normalize_audio_suffix(raw) == want)
    check(f"stt_needs_conversion({raw!r}) is {conv}",
          voice.stt_needs_conversion(raw) is conv)

for bad in ("", None, "txt", "audio/aiff", "application/octet-stream", "  ", "exe"):
    check(f"normalize_audio_suffix rejects {bad!r}",
          voice.normalize_audio_suffix(bad) is None)
check("an unknown suffix counts as needing conversion (it never reaches ffmpeg — "
      "validate_stt_request refuses it first)",
      voice.stt_needs_conversion("txt") is True)
check("wav is the ONLY suffix that needs no external tool",
      [s for s in voice.STT_SUFFIXES if not voice.stt_needs_conversion(s)] == ["wav"])

# ── ffmpeg argv ──────────────────────────────────────────────────────────────
f = voice.ffmpeg_argv(FF, "/t/in.webm", "/t/conv.wav")
check("ffmpeg argv is 16k mono wav",
      f == [FF, "-nostdin", "-y", "-i", "/t/in.webm", "-ac", "1",
            "-ar", "16000", "-f", "wav", "/t/conv.wav"])
check("ffmpeg argv carries -nostdin (a bridge child has no terminal to prompt on)",
      "-nostdin" in f)
check("ffmpeg sample rate is the module constant", voice.STT_SAMPLE_RATE == 16000)

# ── validate_stt_request ─────────────────────────────────────────────────────
check("valid request passes", voice.validate_stt_request(b"\x00\x01", "webm", STT) is None)
check("empty audio refused", "no audio" in (voice.validate_stt_request(b"", "wav", STT) or ""))
check("None audio refused", voice.validate_stt_request(None, "wav", STT) is not None)
big = b"\x00" * (voice.VOICE_MAX_AUDIO_BYTES + 1)
check("over-cap audio refused with the size in the message",
      "too large" in (voice.validate_stt_request(big, "wav", STT) or ""))
check("exactly-at-cap audio is allowed",
      voice.validate_stt_request(b"\x00" * voice.VOICE_MAX_AUDIO_BYTES, "wav", STT) is None)
check("the cap is 25MB", voice.VOICE_MAX_AUDIO_BYTES == 25 * 1024 * 1024)
check("unknown container refused",
      "unsupported audio format" in (voice.validate_stt_request(b"x", "txt", STT) or ""))
check("no model configured → the message names where to fix it",
      "Models → Audio" in (voice.validate_stt_request(b"x", "wav", None) or ""))
check("a TTS model cannot be used for STT",
      "not a speech-to-text model" in (voice.validate_stt_request(b"x", "wav", TTS) or ""))
check("a CHAT model cannot be used for STT",
      voice.validate_stt_request(b"x", "wav", CHAT) is not None)
check("an STT entry with no path is refused",
      "no model path" in (voice.validate_stt_request(
          b"x", "wav", dict(STT, path="")) or ""))

# ── payload → text ───────────────────────────────────────────────────────────
check("text key wins", voice.stt_text_from_payload({"text": "  hello there "}) == "hello there")
check("segments are joined when text is absent",
      voice.stt_text_from_payload(
          {"segments": [{"text": " one"}, {"text": "two "}]}) == "one two")
check("text wins OVER segments",
      voice.stt_text_from_payload({"text": "A", "segments": [{"text": "B"}]}) == "A")
check("empty text falls through to segments",
      voice.stt_text_from_payload({"text": "   ", "segments": [{"text": "x"}]}) == "x")
for junk in (None, 42, [], {}, {"text": ""}, {"segments": "nope"}):
    check(f"stt_text_from_payload({junk!r}) → ''", voice.stt_text_from_payload(junk) == "")
check("a bare string payload is accepted", voice.stt_text_from_payload(" hi ") == "hi")

# ── stt_read_output: file first, stdout second, '' = failure ────────────────
with tempfile.TemporaryDirectory() as d:
    check("no file + no stdout → '' (the failure signal)",
          voice.stt_read_output(d, "in", "") == "")
    check("no file + junk stdout → ''", voice.stt_read_output(d, "in", "Traceback…") == "")
    check("stdout json is read when no file exists (the fallback form)",
          voice.stt_read_output(d, "in", '{"text": "from stdout"}') == "from stdout")
    check("a leading warning line before the json is tolerated",
          voice.stt_read_output(d, "in", 'UserWarning: x\n{"text":"ok"}') == "ok")
    with open(os.path.join(d, "in.json"), "w") as fh:
        json.dump({"text": "from file"}, fh)
    check("the json FILE wins over stdout",
          voice.stt_read_output(d, "in", '{"text":"from stdout"}') == "from file")
    check("the stem selects the file (conv.json vs in.json)",
          voice.stt_read_output(d, "conv", "") == "")
    with open(os.path.join(d, "empty.json"), "w") as fh:
        fh.write("")
    check("an empty json file falls back to stdout",
          voice.stt_read_output(d, "empty", '{"text":"so"}') == "so")
    with open(os.path.join(d, "bad.json"), "w") as fh:
        fh.write("{not json")
    check("a corrupt json file falls back to stdout, never raises",
          voice.stt_read_output(d, "bad", '{"text":"sb"}') == "sb")

# ── ffmpeg resolution: explicit candidate list, ours LAST ────────────────────
cands = voice.ffmpeg_candidates("/R")
check("the candidate list is explicit (a Finder-minimal PATH cannot hide brew's)",
      "/opt/homebrew/bin/ffmpeg" in cands and "/usr/local/bin/ffmpeg" in cands)
check("our provisioned copy is LAST (a real install, with ffprobe, should win)",
      cands[-1] == "/R/data/ffmpeg/bin/ffmpeg")
check("the list is rooted at the given root, not the module's",
      all(c.startswith("/R/") or c.startswith("/opt/") or c.startswith("/usr/")
          for c in cands))


with tempfile.TemporaryDirectory() as d:
    r = Path(d)
    check("ffmpeg_bin returns None when neither PATH nor data/ffmpeg has one "
          "(or the real PATH one when the host has it)",
          voice.ffmpeg_bin(r) in (None, __import__("shutil").which("ffmpeg")))
    (r / "data" / "ffmpeg" / "bin").mkdir(parents=True)
    ours = r / "data" / "ffmpeg" / "bin" / "ffmpeg"
    ours.write_text("#!/bin/sh\n")
    ours.chmod(0o755)
    got = voice.ffmpeg_bin(r)
    check("our provisioned ffmpeg is found when PATH has none",
          got == str(ours) or got == __import__("shutil").which("ffmpeg"))

# ── the global lock is SHARED with TTS (one multi-GB load at a time) ─────────
check("stt and tts share one render lock",
      voice.render_lock() is voice._RENDER_LOCK)
lock = voice.render_lock()
check("lock acquired → stt_transcribe raises VoiceBusy, not a queue",
      lock.acquire(blocking=False))
try:
    # sys.executable stands in for the mlx_whisper script purely so the
    # engine-missing check (which, like tts_render, runs BEFORE the lock) passes and
    # we reach the lock itself. wav input ⇒ no ffmpeg needed either.
    voice.stt_transcribe(STT, b"RIFFxxxx", "wav", ROOT, mlx_bin=sys.executable)
    check("stt_transcribe raises VoiceBusy while the lock is held", False)
except voice.VoiceBusy:
    check("stt_transcribe raises VoiceBusy while the lock is held", True)
except voice.VoiceError as e:
    check("stt_transcribe raises VoiceBusy while the lock is held (got: %s)" % e.message,
          False)
finally:
    lock.release()

# a missing engine is reported BEFORE the lock is taken (never queue behind a render
# only to fail on a missing binary)
try:
    voice.stt_transcribe(STT, b"RIFFxxxx", "wav", Path("/nonexistent-harness-root"))
    check("a missing MLX runtime is reported without touching the lock", False)
except voice.VoiceBusy:
    check("a missing MLX runtime is reported without touching the lock", False)
except voice.VoiceError as e:
    check("a missing MLX runtime is reported without touching the lock",
          "install_mlx.sh" in e.message)

# validation runs BEFORE the lock: a bad request must not even queue behind a render
try:
    voice.stt_transcribe(STT, b"", "wav", ROOT)
    check("stt_transcribe validates before touching the lock", False)
except voice.VoiceBusy:
    check("stt_transcribe validates before touching the lock", False)
except voice.VoiceError as e:
    check("stt_transcribe validates before touching the lock", "no audio" in e.message)
check("the lock is free after a validation refusal", lock.acquire(blocking=False))
lock.release()

# ── bridge wiring, read from app.py's SOURCE (never imported) ───────────────
APP = (ROOT / "bridge" / "app.py").read_text()
check("POST /api/voice/stt exists", '@app.post("/api/voice/stt")' in APP)
check("the endpoint reads the raw body (no multipart parser)", "await req.body()" in APP)
check("the endpoint honours ?fmt=", 'query_params.get("fmt")' in APP)
check("the endpoint defaults to voice.stt_model", '_voice_cfg()["stt_model"]' in APP)
check("the no-model message names Models → Audio",
      "set a default STT model in Models → Audio" in APP)
check("413 on the size cap", "VOICE_MAX_AUDIO_BYTES" in APP and "status_code=413" in APP)
check("409 on VoiceBusy", "VoiceBusy" in APP and "status_code=409" in APP)
check("the engine log tail is forwarded on 500", '"log": e.log_tail' in APP)
check("the transcription runs off the event loop",
      "asyncio.to_thread(_voice.stt_transcribe" in APP)
check("ship.sh copies every bridge/*.py (voice.py must reach the snapshot)",
      "bridge/*.py" in (ROOT / "scripts" / "ship.sh").read_text()
      or 'bridge"/*.py' in (ROOT / "scripts" / "ship.sh").read_text())

# ── install + shell wiring ──────────────────────────────────────────────────
IM = (ROOT / "scripts" / "install_mlx.sh").read_text()
check("install_mlx.sh installs mlx-whisper at the pin",
      'mlx-whisper==${MLX_WHISPER_PIN}' in IM)
check("install_mlx.sh reads the pin from harness.yaml", "_yb mlx_whisper_pin" in IM)
HY = (ROOT / "harness.yaml").read_text()
check("harness.yaml pins mlx-whisper 0.4.3 (spec §6)", 'mlx_whisper_pin: "0.4.3"' in HY)
SW = (ROOT / "app" / "main.swift").read_text()
check("the shell grants the webview's media-capture request",
      "requestMediaCapturePermissionFor" in SW and "decisionHandler(type == .camera ? .deny : .grant)" in SW)
BA = (ROOT / "scripts" / "build_app.sh").read_text()
check("build_app.sh's Info.plist carries NSMicrophoneUsageDescription",
      "NSMicrophoneUsageDescription" in BA)

print()
print(f"{'FAIL' if FAILS else 'OK'} — {len(FAILS)} failure(s)")
if FAILS:
    for f_ in FAILS:
        print("  -", f_)
sys.exit(1 if FAILS else 0)
