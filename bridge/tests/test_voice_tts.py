"""Unit tests for the harness-native voice capability (bridge/voice.py, Phase B).

bridge/voice.py imports nothing heavier than the stdlib, so it is imported directly.
bridge/app.py is NOT imported (it builds httpx clients at import time) — the two
wiring facts that matter there are pinned by reading its source with ast/text, the
same trick test_mtp_detect.py uses.

What is pinned here, and why each one exists:

  * tts_argv — the exact argv of both engines, verified on Debi's Mac 2026-08-07.
    llama-tts at b10295 is the rewritten mtmd tool: `-m backbone -mm mmproj -p text
    -o out.wav`. There is NO --voice and NO -mv/--vocoder-model (OuteTTS+vocoder is
    dead at our pin), so a spec/recon regression trips here.
    mlx-audio MUST carry --join_audio: without it the tool writes out_000.wav
    segments and our success check on out.wav would report a false failure.
  * validate_tts_request — every refusal path, so a bad request fails at the door
    instead of spawning a multi-GB model load.
  * render_ok — THE exit-0-on-failure invariant. mlx-audio catches all exceptions,
    prints a traceback and returns normally; llama-tts is an upstream "playground".
    Success is "a non-empty wav exists", never the return code.
  * split_audio / api_models wiring — an audio model must never reach the chat
    lists (runner switch / aux / chat picker). This is the regression that must be
    impossible.

Run: python3 bridge/tests/test_voice_tts.py   (from repo root)
"""
import ast
import os
import re
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


LB = "/opt/harness/data/llamacpp/build/bin/llama-tts"
MP = "/opt/harness/data/mlx-venv/bin/python"

GGUF = {"id": "qwen3-tts-q4", "kind": "audio", "format": "tts-gguf",
        "path": "/M/qwen3-tts/backbone-Q4_K_M.gguf",
        "mmproj": "/M/qwen3-tts/mmproj-Q8_0.gguf", "size_bytes": 1_380_000_000}
MLX = {"id": "qwen3-tts-8bit", "kind": "audio", "format": "tts-mlx",
       "path": "/M/qwen3-tts-8bit", "size_bytes": 1_800_000_000}
STT = {"id": "whisper-turbo", "kind": "audio", "format": "stt-mlx", "path": "/M/whisper"}
CHAT_GGUF = {"id": "gemma-4-31b", "format": "gguf", "path": "/M/g/model.gguf"}
CHAT_MLX = {"id": "qwen-35b-mlx", "format": "mlx", "path": "/M/q"}

# ── tts_argv: llama.cpp (tts-gguf) ───────────────────────────────────────────
a = voice.tts_argv(GGUF, "hello there", "/tmp/x/out.wav", LB, MP)
check("gguf argv starts with the resolved llama-tts binary", a[0] == LB)
check("gguf argv is exactly the verified b10295 surface",
      a == [LB, "-m", "/M/qwen3-tts/backbone-Q4_K_M.gguf",
            "-mm", "/M/qwen3-tts/mmproj-Q8_0.gguf",
            "-p", "hello there", "-o", "/tmp/x/out.wav"])
check("gguf argv uses -mm (mmproj), NEVER -mv/--vocoder-model (dead at b10295)",
      "-mm" in a and "-mv" not in a and "--vocoder-model" not in a)
check("gguf argv has no --voice (llama-tts has no such flag)", "--voice" not in a)
check("gguf argv passes text as ONE argv element (never shell-quoted)",
      a[a.index("-p") + 1] == "hello there")
check("gguf argv omits --tts-lang when no lang is set", "--tts-lang" not in a)
check("gguf argv adds --tts-lang when the entry carries one",
      voice.tts_argv({**GGUF, "lang": "en"}, "t", "/o.wav", LB, MP)[-2:]
      == ["--tts-lang", "en"])
check("gguf argv ignores a blank lang",
      "--tts-lang" not in voice.tts_argv({**GGUF, "lang": "  "}, "t", "/o.wav", LB, MP))
check("gguf argv adds -n when max_frames is set",
      voice.tts_argv({**GGUF, "max_frames": 512}, "t", "/o.wav", LB, MP)[-2:]
      == ["-n", "512"])
check("gguf argv omits -n by default", "-n" not in a)
check("gguf argv keeps lang before -n when both are set",
      voice.tts_argv({**GGUF, "lang": "en", "max_frames": 8}, "t", "/o.wav", LB, MP)[-4:]
      == ["--tts-lang", "en", "-n", "8"])
check("tts_argv is pure — same input, equal output",
      voice.tts_argv(GGUF, "hello there", "/tmp/x/out.wav", LB, MP) == a)
check("every argv element is a str (subprocess would reject otherwise)",
      all(isinstance(x, str) for x in
          voice.tts_argv({**GGUF, "max_frames": 8}, "t", "/o.wav", LB, MP)))

# ── tts_argv: MLX (tts-mlx) ──────────────────────────────────────────────────
b = voice.tts_argv(MLX, "hi", "/tmp/tts-abc/out.wav", LB, MP)
check("mlx argv runs the mlx-venv python, not the llama binary", b[0] == MP)
check("mlx argv invokes the generate module",
      b[1:3] == ["-m", "mlx_audio.tts.generate"])
check("mlx argv is exactly the recon'd 0.4.7 surface",
      b == [MP, "-m", "mlx_audio.tts.generate", "--model", "/M/qwen3-tts-8bit",
            "--text", "hi", "--join_audio",
            "--output_path", "/tmp/tts-abc", "--file_prefix", "out"])
check("mlx argv ALWAYS carries --join_audio (else it writes out_000.wav segments)",
      "--join_audio" in b)
check("mlx --output_path is the DIR of out_path", b[b.index("--output_path") + 1] == "/tmp/tts-abc")
check("mlx --file_prefix is the STEM of out_path (→ <dir>/out.wav)",
      b[b.index("--file_prefix") + 1] == "out")
check("mlx argv omits --voice when unset", "--voice" not in b)
check("mlx argv adds --voice when the entry names one",
      voice.tts_argv({**MLX, "voice": "Chelsie"}, "t", "/d/o.wav", LB, MP)[-2:]
      == ["--voice", "Chelsie"])
check("mlx argv survives an out_path with no directory component",
      voice.tts_argv(MLX, "t", "out.wav", LB, MP)[-3:] == [".", "--file_prefix", "out"])

# ── tts_argv: rejections ─────────────────────────────────────────────────────
for bad in ({"format": "stt-mlx"}, {"format": "gguf"}, {"format": ""}, {}):
    try:
        voice.tts_argv(bad, "t", "/o.wav", LB, MP)
        check(f"unsupported format {bad.get('format')!r} raises ValueError", False)
    except ValueError:
        check(f"unsupported format {bad.get('format')!r} raises ValueError", True)

# ── validate_tts_request ─────────────────────────────────────────────────────
check("valid gguf request passes", voice.validate_tts_request("hello", GGUF) is None)
check("valid mlx request passes", voice.validate_tts_request("hello", MLX) is None)
check("empty text is refused", voice.validate_tts_request("", GGUF) is not None)
check("whitespace-only text is refused", voice.validate_tts_request("   \n ", GGUF) is not None)
check("non-string text is refused", voice.validate_tts_request(None, GGUF) is not None)
check("text at exactly the cap is allowed",
      voice.validate_tts_request("x" * voice.VOICE_MAX_CHARS, GGUF) is None)
check("text one char over the cap is refused",
      voice.validate_tts_request("x" * (voice.VOICE_MAX_CHARS + 1), GGUF) is not None)
check("the cap is 2000 chars", voice.VOICE_MAX_CHARS == 2000)
check("the subprocess timeout is 120s", voice.VOICE_TIMEOUT_S == 120)
check("missing entry is refused (capability off)",
      voice.validate_tts_request("hi", None) is not None)
check("an STT entry is refused as a TTS target",
      voice.validate_tts_request("hi", STT) is not None)
check("a CHAT model is refused as a TTS target",
      voice.validate_tts_request("hi", CHAT_GGUF) is not None)
check("tts-gguf without mmproj is refused (llama-tts needs -m AND -mm)",
      voice.validate_tts_request("hi", {**GGUF, "mmproj": None}) is not None)
check("tts-gguf with a blank mmproj is refused",
      voice.validate_tts_request("hi", {**GGUF, "mmproj": "  "}) is not None)
check("tts-mlx does NOT require mmproj",
      voice.validate_tts_request("hi", MLX) is None)
check("an entry with no path is refused",
      voice.validate_tts_request("hi", {**MLX, "path": ""}) is not None)
check("the too-long message names the cap",
      str(voice.VOICE_MAX_CHARS) in voice.validate_tts_request("x" * 5000, GGUF))

# ── render_ok — the exit-0-on-failure invariant ──────────────────────────────
_TD = tempfile.mkdtemp(prefix="harness-voice-test-")
missing = os.path.join(_TD, "nope.wav")
empty = os.path.join(_TD, "empty.wav")
real = os.path.join(_TD, "real.wav")
open(empty, "wb").close()
with open(real, "wb") as f:
    f.write(b"RIFF....WAVEfmt ")
check("render_ok: absent file → False", voice.render_ok(missing) is False)
check("render_ok: ZERO-BYTE file → False (an engine that exits 0 having written "
      "nothing must count as a failure)", voice.render_ok(empty) is False)
check("render_ok: non-empty file → True", voice.render_ok(real) is True)
check("render_ok: a directory is not a render", voice.render_ok(_TD) is False)
check("render_ok never raises on a nonsense path", voice.render_ok("\0/bad") is False)

vsrc = (ROOT / "bridge" / "voice.py").read_text()
check("tts_render never gates success on returncode (the engines exit 0 on failure)",
      "p.returncode == 0" not in vsrc and "check=True" not in vsrc
      and "if not render_ok(out_path):" in vsrc)
check("tts_render always cleans its temp dir (finally + rmtree)",
      re.search(r"finally:\s*\n\s*if tmp_dir:\s*\n\s*shutil\.rmtree", vsrc) is not None)
check("tts_render passes a timeout to subprocess.run",
      "timeout=VOICE_TIMEOUT_S" in vsrc)
check("the render lock is non-blocking (a 2nd render is refused, never queued)",
      "_RENDER_LOCK.acquire(blocking=False)" in vsrc)
# ENGINE binaries are resolved by explicit path, never by PATH lookup (Finder-minimal
# PATH rule). Phase D narrowed this from "the module contains no which()" to "the
# ENGINE resolvers contain none": ffmpeg_bin deliberately tries the user's own ffmpeg
# via which() FIRST — but only as the first entry of an EXPLICIT candidate list
# (ffmpeg_candidates), so a Finder PATH cannot make it silently unfindable.
_engine_src = "".join(
    ast.get_source_segment(vsrc, n) or ""
    for n in ast.parse(vsrc).body
    if isinstance(n, ast.FunctionDef)
    and n.name in ("llama_tts_bin", "mlx_python", "mlx_whisper_bin",
                   "tts_argv", "stt_argv", "tts_render", "stt_transcribe"))
check("engine binaries are resolved by explicit path, never by PATH lookup",
      "which(" not in _engine_src)
check("ffmpeg's PATH lookup is backed by an explicit candidate list",
      "/opt/homebrew/bin/ffmpeg" in vsrc and "/usr/local/bin/ffmpeg" in vsrc)
check("llama_tts_bin points at our pinned llama.cpp build",
      voice.llama_tts_bin("/R") == "/R/data/llamacpp/build/bin/llama-tts")
check("mlx_python points at the existing mlx venv",
      voice.mlx_python("/R") == "/R/data/mlx-venv/bin/python")

# ── tts_render behaviour without any engine present ──────────────────────────
try:
    voice.tts_render(GGUF, "hi", root="/definitely/not/here")
    check("tts_render raises VoiceError when llama-tts is absent", False)
except voice.VoiceError as e:
    check("tts_render raises VoiceError when llama-tts is absent",
          "llama-tts" in e.message and "install_llamacpp" in e.message)
try:
    voice.tts_render(MLX, "hi", root="/definitely/not/here")
    check("tts_render raises VoiceError when the mlx venv is absent", False)
except voice.VoiceError as e:
    check("tts_render raises VoiceError when the mlx venv is absent",
          "install_mlx" in e.message)
check("a missing engine does NOT leave the render lock held",
      voice.render_lock().acquire(blocking=False) is True)
voice.render_lock().release()
check("VoiceBusy is a VoiceError (one except clause can catch both)",
      issubclass(voice.VoiceBusy, voice.VoiceError))
check("VoiceError carries a log tail attribute",
      voice.VoiceError("x").log_tail == "" and voice.VoiceError("x", "tail").log_tail == "tail")

# ── audio filtering: the leak that must be impossible ────────────────────────
REG = [CHAT_GGUF, GGUF, CHAT_MLX, MLX, STT]
chat, audio = voice.split_audio(REG)
check("chat half excludes every audio entry",
      [m["id"] for m in chat] == ["gemma-4-31b", "qwen-35b-mlx"])
check("audio half is exactly the audio entries",
      [m["id"] for m in audio] == ["qwen3-tts-q4", "qwen3-tts-8bit", "whisper-turbo"])
check("split_audio preserves order", chat[0] is CHAT_GGUF and audio[0] is GGUF)
check("split_audio partitions (no loss, no duplication)",
      len(chat) + len(audio) == len(REG))
check("split_audio on an empty/None registry is safe",
      voice.split_audio([]) == ([], []) and voice.split_audio(None) == ([], []))
check("an entry that forgot kind:'audio' is STILL caught by its format",
      voice.split_audio([{"id": "x", "format": "tts-mlx"}])[1] != [])
check("an entry with kind:'audio' but an odd format is still audio",
      voice.is_audio_entry({"id": "x", "kind": "audio", "format": "weird"}) is True)
check("a plain gguf chat model is never audio", voice.is_audio_entry(CHAT_GGUF) is False)
check("a non-dict registry row can't crash the partition",
      voice.is_audio_entry("nonsense") is False and voice.is_audio_entry(None) is False)
check("is_tts_entry / is_stt_entry are exclusive",
      voice.is_tts_entry(GGUF) and voice.is_tts_entry(MLX)
      and not voice.is_tts_entry(STT) and voice.is_stt_entry(STT)
      and not voice.is_stt_entry(MLX))
check("a chat model is neither tts nor stt",
      not voice.is_tts_entry(CHAT_MLX) and not voice.is_stt_entry(CHAT_MLX))
check("find_entry only searches what it is given",
      voice.find_entry(audio, "gemma-4-31b") is None
      and voice.find_entry(audio, "qwen3-tts-q4") is GGUF)
check("find_entry on a blank id → None",
      voice.find_entry(audio, "") is None and voice.find_entry(audio, None) is None)

v = voice.audio_entry_view(GGUF)
check("audio_entry_view labels the llama.cpp engine", v["engine"] == "llamacpp")
check("audio_entry_view labels the mlx engine",
      voice.audio_entry_view(MLX)["engine"] == "mlx"
      and voice.audio_entry_view(STT)["engine"] == "mlx")
check("audio_entry_view roles are tts/stt",
      v["role"] == "tts" and voice.audio_entry_view(STT)["role"] == "stt")
check("audio_entry_view always stamps kind:'audio'", v["kind"] == "audio")
check("audio_entry_view keeps the size for the disk ledger",
      v["size_bytes"] == 1_380_000_000)
check("audio_entry_view falls back to the id for a nameless entry",
      v["name"] == "qwen3-tts-q4")

# ── app.py wiring (source-level: app.py can't be imported without network deps) ──
asrc = (ROOT / "bridge" / "app.py").read_text()
ast.parse(asrc)   # the file must at least be syntactically whole
check("app.py partitions the registry before building `installed`",
      "models, _audio_models = _split_audio(models)" in asrc)
check("app.py returns the audio list separately from `installed`",
      '"audio": audio' in asrc)
check("the ledger counts CHAT models only",
      "models, _ = _split_audio(_registry_models())" in asrc)
check("the runner switch refuses an audio id", "_reject_if_audio(new_id)" in asrc)
check("aux set refuses an audio id", asrc.count("_reject_if_audio(new_id)") >= 2)
check("the new endpoints do not collide with the voice-MCP ones",
      asrc.count('@app.get("/api/voice/status")') == 1
      and asrc.count('@app.post("/api/voice/toggle")') == 1
      and asrc.count('@app.post("/api/voice/tts")') == 1
      and asrc.count('@app.get("/api/voice/config")') == 1
      and asrc.count('@app.post("/api/voice/config")') == 1)
check("the tts endpoint answers with audio/wav", 'media_type="audio/wav"' in asrc)
check("the tts endpoint maps VoiceBusy → 409",
      re.search(r"except _voice\.VoiceBusy[\s\S]{0,200}status_code=409", asrc) is not None)
check("the tts endpoint maps an over-long body → 413", "status_code=413" in asrc)
check("the render runs off the event loop (asyncio.to_thread)",
      "asyncio.to_thread(_voice.tts_render" in asrc)
check("app.py imports voice defensively (a stale snapshot must still boot)",
      "_voice, _VOICE_ERR = None" in asrc)

# ── harness.yaml voice block ─────────────────────────────────────────────────
import yaml  # noqa: E402
hy = yaml.safe_load((ROOT / "harness.yaml").read_text())
check("harness.yaml has a top-level voice block", isinstance(hy.get("voice"), dict))
check("voice block declares both slots",
      set(hy["voice"]) == {"tts_model", "stt_model"})
check("both voice slots start empty (= capability off)",
      not hy["voice"]["tts_model"] and not hy["voice"]["stt_model"])
check("build.mlx_audio_pin is present and pinned",
      str((hy.get("build") or {}).get("mlx_audio_pin") or "").strip() != "")
check("install_mlx.sh reads the pin from harness.yaml",
      "mlx_audio_pin" in (ROOT / "scripts" / "install_mlx.sh").read_text())
check("ship.sh copies every bridge/*.py (voice.py must reach the snapshot)",
      'for _m in "$ROOT"/bridge/*.py' in (ROOT / "scripts" / "ship.sh").read_text())

# ── _set_yaml_scalar: it rewrites the USER'S manifest, so exercise it for real ──
# ast-extracted from app.py with a patched ROOT so nothing here touches the real file.
_ns = {"ROOT": None}
for _node in ast.parse(asrc).body:
    if isinstance(_node, ast.FunctionDef) and _node.name == "_set_yaml_scalar":
        exec(compile(ast.Module(body=[_node], type_ignores=[]), "<app>", "exec"), _ns)
set_scalar = _ns["_set_yaml_scalar"]
_YD = Path(tempfile.mkdtemp(prefix="harness-yaml-test-"))
_ns["ROOT"] = _YD
ORIG = (ROOT / "harness.yaml").read_text()


def write_and_load(*calls, base=ORIG):
    (_YD / "harness.yaml").write_text(base)
    for blk, key, val in calls:
        set_scalar(blk, key, val)
    txt = (_YD / "harness.yaml").read_text()
    return txt, yaml.safe_load(txt)


txt, doc = write_and_load(("voice", "tts_model", "qwen3-tts-q4"))
check("set_scalar writes the value", doc["voice"]["tts_model"] == "qwen3-tts-q4")
check("set_scalar leaves the sibling slot alone", doc["voice"]["stt_model"] is None)
check("set_scalar does not disturb any other block",
      doc["runner"] == yaml.safe_load(ORIG)["runner"]
      and doc["components"] == yaml.safe_load(ORIG)["components"])
check("set_scalar preserves the file's comments (no yaml round-trip)",
      txt.count("#") == ORIG.count("#"))
check("set_scalar keeps the trailing comment on the rewritten line",
      "# id of the default text-to-speech model" in txt)
check("set_scalar changes exactly one line",
      sum(1 for a, b in zip(ORIG.split("\n"), txt.split("\n")) if a != b) == 1)

txt, doc = write_and_load(("voice", "tts_model", "x"), ("voice", "tts_model", ""))
check("an empty value clears the slot (= capability off)",
      doc["voice"]["tts_model"] is None)
txt, doc = write_and_load(("voice", "stt_model", "whisper-turbo"))
check("the stt slot is settable independently",
      doc["voice"]["stt_model"] == "whisper-turbo" and doc["voice"]["tts_model"] is None)
check("set_scalar never touches a same-named key in ANOTHER block",
      write_and_load(("aux", "model", "small"))[1]["runner"]["model"]
      == yaml.safe_load(ORIG)["runner"]["model"])

NOVOICE = "\n".join(l for l in ORIG.split("\n")
                    if not (l.startswith("voice:") or l.startswith("  tts_model:")
                            or l.startswith("  stt_model:")))
txt, doc = write_and_load(("voice", "tts_model", "late"), base=NOVOICE)
check("a manifest MISSING the voice block gets it appended, not dropped",
      doc["voice"]["tts_model"] == "late")
txt, doc = write_and_load(("memory", "budget_gb", "40"), base=ORIG)
check("a missing KEY is inserted into an existing block, not appended at EOF",
      write_and_load(("memory", "nonesuch", "1"))[1]["memory"]["nonesuch"] == 1)

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1)
print("all voice-tts tests passed")
