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
import json
import os
import re
import shutil
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
# NARROWED 2026-08-13 (persistent worker): the call is now wrapped in a
# functools.partial so the ledger spawn_guard can be passed as a keyword —
# asyncio.to_thread's own *args are positional-only. The INVARIANT is unchanged:
# a render never runs on the event loop.
check("the render runs off the event loop (asyncio.to_thread)",
      re.search(r"asyncio\.to_thread\([\s\S]{0,120}_voice\.tts_render", asrc) is not None)
check("the render is handed the ledger spawn guard",
      "spawn_guard=_voice_spawn_guard" in asrc)
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

# ── named voices (the per-model voice picker) ────────────────────────────────
# WHY: mlx-audio picks a RANDOM named voice per render when --voice is absent, so
# the same model sounds like a different person every reply. The pin lives on the
# registry entry; these tests hold the offer list honest and, above all, hold the
# line that a tts-gguf NEVER gets a --voice (llama-tts has no such flag).
QWEN_MLX = {"id": "Qwen3-TTS-12Hz-1.7B-Base-8bit", "kind": "audio",
            "format": "tts-mlx", "path": "/M/Qwen3-TTS-12Hz-1.7B-Base-8bit"}
KOKORO = {"id": "Kokoro-82M-bf16", "kind": "audio", "format": "tts-mlx",
          "path": "/M/Kokoro-82M-bf16"}
UNKNOWN_MLX = {"id": "some-new-tts-mlx", "kind": "audio", "format": "tts-mlx",
               "path": "/M/some-new-tts"}

check("voices_for finds the Qwen3-TTS pair by id",
      voice.voices_for(QWEN_MLX) == ["serena", "vivian", "ryan", "aiden", "dylan", "eric", "uncle_fu", "sohee", "ono_anna"])
check("voices_for matches on the REPO when the id has no family token",
      voice.voices_for({"kind": "audio", "format": "tts-mlx", "id": "8bit",
                        "repo": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"})
      == ["serena", "vivian", "ryan", "aiden", "dylan", "eric", "uncle_fu", "sohee", "ono_anna"])
check("voices_for matches case-insensitively",
      voice.voices_for({**QWEN_MLX, "id": "QWEN3-TTS-XL"}) == ["serena", "vivian", "ryan", "aiden", "dylan", "eric", "uncle_fu", "sohee", "ono_anna"])
check("voices_for returns the Kokoro ids", voice.voices_for(KOKORO)[0] == "af_heart")
check("Kokoro list is a useful size (not one, not fifty)",
      6 <= len(voice.voices_for(KOKORO)) <= 10)
check("every offered Kokoro id looks like a real voice token",
      all(re.fullmatch(r"[abe][fm]_[a-z]+", v) for v in voice.voices_for(KOKORO)))
check("voices_for returns a COPY (a caller cannot corrupt the table)",
      voice.voices_for(KOKORO) is not voice.KNOWN_VOICES["kokoro"])
check("voices_for is EMPTY for every tts-gguf — llama-tts has no --voice",
      voice.voices_for(GGUF) == []
      and voice.voices_for({**GGUF, "id": "qwen3-tts-gguf"}) == []
      and voice.voices_for({**GGUF, "id": "kokoro-gguf"}) == [])
check("voices_for is empty for an unrecognised mlx family (→ free text in the UI)",
      voice.voices_for(UNKNOWN_MLX) == [])
check("voices_for is empty for an STT model", voice.voices_for(STT) == [])
check("voices_for is empty for chat models and junk",
      voice.voices_for(CHAT_MLX) == [] and voice.voices_for(CHAT_GGUF) == []
      and voice.voices_for(None) == [] and voice.voices_for({}) == [])

check("normalize_voice trims", voice.normalize_voice("  Ethan \n") == "Ethan")
check("normalize_voice maps None/'' to the CLEAR sentinel ''",
      voice.normalize_voice(None) == "" and voice.normalize_voice("   ") == "")

check("a known voice validates", voice.validate_voice_choice(QWEN_MLX, "Chelsie") is None)
check("an UNKNOWN name still validates (the table is an offer, not a whitelist)",
      voice.validate_voice_choice(QWEN_MLX, "af_river") is None)
check("empty string validates — it is the CLEAR operation",
      voice.validate_voice_choice(QWEN_MLX, "") is None)
check("a free-text voice on an unrecognised mlx model validates",
      voice.validate_voice_choice(UNKNOWN_MLX, "whoever") is None)
check("a missing entry is refused", voice.validate_voice_choice(None, "x") is not None)
_g = voice.validate_voice_choice(GGUF, "Chelsie")
check("a tts-gguf is refused", _g is not None)
check("the tts-gguf refusal names llama.cpp and 'no voice parameter'",
      "llama.cpp" in _g and "no voice parameter" in _g)
check("an STT model is refused",
      voice.validate_voice_choice(STT, "x") is not None)
check("a chat model is refused",
      voice.validate_voice_choice(CHAT_MLX, "x") is not None)
check("a non-string voice is refused",
      voice.validate_voice_choice(QWEN_MLX, 7) is not None
      and voice.validate_voice_choice(QWEN_MLX, ["a"]) is not None)
check("a voice longer than the cap is refused",
      voice.validate_voice_choice(QWEN_MLX, "v" * (voice.VOICE_NAME_MAX + 1)) is not None)
check("a voice exactly at the cap is accepted",
      voice.validate_voice_choice(QWEN_MLX, "v" * voice.VOICE_NAME_MAX) is None)

# argv round-trip: the whole point of the picker is this one flag.
check("a pinned voice reaches the mlx argv",
      voice.tts_argv({**QWEN_MLX, "voice": "Ethan"}, "t", "/d/o.wav", LB, MP)[-2:]
      == ["--voice", "Ethan"])
check("a whitespace-only voice never reaches the argv",
      "--voice" not in voice.tts_argv({**QWEN_MLX, "voice": "   "}, "t", "/d/o.wav", LB, MP))
check("a voice key on a tts-gguf entry is IGNORED by tts_argv (no such flag)",
      "--voice" not in voice.tts_argv({**GGUF, "voice": "Chelsie"}, "t", "/o.wav", LB, MP))

check("audio_entry_view carries the offer list to the panel",
      voice.audio_entry_view(QWEN_MLX)["voices"] == ["serena", "vivian", "ryan", "aiden", "dylan", "eric", "uncle_fu", "sohee", "ono_anna"])
check("audio_entry_view reports the pinned voice",
      voice.audio_entry_view({**QWEN_MLX, "voice": "Ethan"})["voice"] == "Ethan")
check("audio_entry_view reports no voices for a gguf",
      voice.audio_entry_view(GGUF)["voices"] == [])

# ── config-derived voices (the AUTHORITATIVE picker source) ──────────────────
# The static table guesses at a FAMILY; a family is not a checkpoint. Base and
# CustomVoice share every token and have opposite behaviour, so only config.json
# can separate them — these tests pin that it is what we actually read.
print("\n-- config-derived voices --")

# The real CustomVoice shape (research-verified: tts_model_type discriminates,
# talker_config.spk_id lists the nine speakers, two of them dialects).
CV_CFG = {
    "tts_model_type": "custom_voice",
    "talker_config": {
        "spk_id": {"serena": 0, "vivian": 1, "ryan": 2, "aiden": 3, "dylan": 4,
                   "eric": 5, "uncle_fu": 6, "sohee": 7, "ono_anna": 8},
        "spk_is_dialect": {"dylan": True, "eric": True, "serena": False},
    },
}
BASE_CFG = {"tts_model_type": "base",
            "talker_config": {"spk_id": {}, "speaker_encoder": {"dim": 512}}}

_cv = voice.voices_from_config(CV_CFG)
check("voices_from_config reads all nine CustomVoice speakers",
      _cv["voices"] == ["serena", "vivian", "ryan", "aiden", "dylan",
                        "eric", "uncle_fu", "sohee", "ono_anna"])
check("voices_from_config preserves the checkpoint's own order",
      _cv["voices"][0] == "serena" and _cv["voices"][-1] == "ono_anna")
check("voices_from_config reports the model type",
      _cv["model_type"] == "custom_voice")
check("voices_from_config marks the two dialect speakers",
      _cv["dialects"]["dylan"] is True and _cv["dialects"]["eric"] is True
      and _cv["dialects"]["serena"] is False)
check("dialect flags are limited to DECLARED voices (a stray key cannot leak)",
      voice.voices_from_config(
          {"talker_config": {"spk_id": {"a": 0},
                             "spk_is_dialect": {"a": 1, "ghost": True}}}
      )["dialects"] == {"a": True})
_b = voice.voices_from_config(BASE_CFG)
check("voices_from_config finds no names in the Base checkpoint",
      _b["voices"] == [] and _b["model_type"] == "base")
check("voices_from_config survives every surprise type",
      all(voice.voices_from_config(x)["voices"] == []
          for x in (None, [], "config", 7, {"talker_config": "nope"},
                    {"talker_config": {"spk_id": None}},
                    {"talker_config": {"spk_id": [1, 2]}},
                    {"tts_model_type": 5})))
check("a LIST spk_id still yields names (a shape we have not seen, but might)",
      voice.voices_from_config(
          {"talker_config": {"spk_id": ["alpha", "beta"]}})["voices"]
      == ["alpha", "beta"])
check("a non-string tts_model_type is simply unknown, never a crash",
      voice.voices_from_config({"tts_model_type": {"a": 1}})["model_type"] is None)

# voices_for_entry against REAL directories.
_vd = tempfile.mkdtemp(prefix="voices-")
try:
    def _mk(name, cfg=None, pt=()):
        d = os.path.join(_vd, name)
        os.makedirs(os.path.join(d, "voices") if pt else d, exist_ok=True)
        if cfg is not None:
            with open(os.path.join(d, "config.json"), "w") as f:
                json.dump(cfg, f)
        for v in pt:
            open(os.path.join(d, "voices", v + ".pt"), "wb").close()
        return d

    voice.clear_voices_cache()
    cvd = _mk("Qwen3-TTS-CustomVoice-8bit", CV_CFG)
    bad = _mk("Qwen3-TTS-Base-8bit", BASE_CFG)
    kok = _mk("Kokoro-82M-bf16", {"model_type": "style_tts2"},
              pt=("af_heart", "am_adam", "bf_emma"))
    mys = _mk("SomeNewTTS-mlx", {"model_type": "whatever"})

    def _e(path, mid=None):
        return {"kind": "audio", "format": "tts-mlx",
                "id": mid or os.path.basename(path), "path": path}

    r = voice.voices_for_entry(_e(cvd))
    check("voices_for_entry reads the CustomVoice config off disk",
          r["voices"][0] == "serena" and len(r["voices"]) == 9
          and r["source"] == "config" and not r["note"])
    check("voices_for_entry carries the dialect flags through",
          r["dialects"].get("eric") is True)

    r = voice.voices_for_entry(_e(bad))
    check("voices_for_entry offers NO voices for the Base checkpoint",
          r["voices"] == [] and r["source"] == "config")
    check("the Base checkpoint gets the honest reference-audio note",
          voice.NO_VOICES_NOTE in r["note"])
    check("the Qwen note NAMES the verified CustomVoice sibling repo",
          voice.QWEN_CUSTOMVOICE_REPO in r["note"])
    check("a non-Qwen nameless model gets the note WITHOUT the Qwen hint",
          voice.QWEN_CUSTOMVOICE_REPO not in voice.voices_for_entry(
              _e(_mk("Nameless-TTS-mlx", BASE_CFG)))["note"])

    r = voice.voices_for_entry(_e(kok))
    check("voices_for_entry lists Kokoro's voices/*.pt stems",
          r["voices"] == ["af_heart", "am_adam", "bf_emma"] and r["source"] == "dir")
    check("a voices/ dir yields no spurious note", r["note"] == "")

    r = voice.voices_for_entry(_e(mys))
    check("a config with NO verdict falls through to free text (no note, no chips)",
          r["voices"] == [] and r["note"] == "" and r["source"] == "none")

    r = voice.voices_for_entry({"kind": "audio", "format": "tts-mlx",
                                "id": "kokoro-82m", "path": "/nope/not/here"})
    check("an unreadable model dir falls back to the STATIC table (last resort)",
          r["voices"][0] == "af_heart" and r["source"] == "table")
    check("voices_for_entry is empty for tts-gguf and stt",
          voice.voices_for_entry(GGUF)["voices"] == []
          and voice.voices_for_entry(STT)["voices"] == []
          and voice.voices_for_entry(None)["voices"] == [])

    # Cache: the panel polls /api/models, so this runs constantly.
    voice.clear_voices_cache()
    voice.voices_for_entry(_e(cvd))
    _seen = []
    _real_read = voice.read_model_config
    voice.read_model_config = lambda p: (_seen.append(p), _real_read(p))[1]
    try:
        voice.voices_for_entry(_e(cvd))
        check("a repeat lookup is served from cache (no re-read per poll)",
              _seen == [])
        with open(os.path.join(cvd, "config.json"), "w") as f:
            json.dump(BASE_CFG, f)
        os.utime(os.path.join(cvd, "config.json"), (1, 1))
        after = voice.voices_for_entry(_e(cvd))
        check("a CHANGED config busts the cache (a re-download must not go stale)",
              _seen != [] and after["voices"] == [])
    finally:
        voice.read_model_config = _real_read
        with open(os.path.join(cvd, "config.json"), "w") as f:
            json.dump(CV_CFG, f)          # undo the cache-bust edit

    voice.clear_voices_cache()
    av = voice.audio_entry_view(_e(bad))
    check("audio_entry_view carries voice_note for a nameless model",
          av["voices"] == [] and voice.NO_VOICES_NOTE in (av["voice_note"] or ""))
    av = voice.audio_entry_view(_e(cvd))
    check("audio_entry_view carries dialects + voice_source for a named model",
          av["dialects"].get("dylan") is True and av["voice_source"] == "config"
          and av["voice_note"] is None and av["tts_model_type"] == "custom_voice")
finally:
    shutil.rmtree(_vd, ignore_errors=True)
    voice.clear_voices_cache()


# Bridge wiring, read from app.py's SOURCE (importing app builds httpx clients).
APP_SRC = (ROOT / "bridge" / "app.py").read_text()
check("app.py exposes POST /api/voice/entry-voice",
      '@app.post("/api/voice/entry-voice")' in APP_SRC)
check("the endpoint validates through voice.validate_voice_choice",
      "_voice.validate_voice_choice(" in APP_SRC)
check("the endpoint writes through the atomic _registry_update helper",
      "def _registry_update(" in APP_SRC and "_registry_update(mid," in APP_SRC)
check("_registry_update writes atomically (tmp + os.replace), like its siblings",
      re.search(r"def _registry_update\(.*?_os\.replace\(tmp, reg\)", APP_SRC, re.S)
      is not None)
check("an empty voice CLEARS the key rather than storing null",
      '{"voice": v or None}' in APP_SRC)

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1)
print("all voice-tts tests passed")
