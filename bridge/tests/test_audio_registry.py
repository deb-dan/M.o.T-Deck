"""Unit tests for Phase A of the harness-native voice capability — the AUDIO half of
the model registry (FABLE-VOICE-CAPABILITY-SPEC).

Three surfaces, all pure or temp-dir-backed (no network, no real models):

  * voice.audio_download_entry — the download→registry seam. The Get buttons pass an
    explicit format hint rather than sniffing filenames, and the llama.cpp pair must
    collapse into ONE tts-gguf entry (path = backbone, mmproj = projector), never two.
  * seed_registry.audio_format_for — the Rescan classifier. Every NEGATIVE case here
    is load-bearing: a chat model misclassified as audio disappears from the chat
    lists entirely (api_models partitions audio out), so misses are cheap and false
    positives are not.
  * api_models — the invariant itself: an audio entry NEVER appears in `installed`.
    Exercised against the REAL endpoint with a temp ROOT, not by reading source.

Run: python3 bridge/tests/test_audio_registry.py   (from repo root)
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
# Neutralize any SOCKS proxy env so importing the app's httpx clients succeeds.
for _v in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
    os.environ.pop(_v, None)

from bridge import voice                      # noqa: E402
import seed_registry as sr                    # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


def touch(path, size=0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\0" * size)


# ══ 1. voice.audio_download_entry — the download→registry builder ═══════════════
# What _gguf_registry_entry produces for the Qwen3-TTS pair (backbone + mmproj
# requested together, so both land in ONE DOWNLOADS entry → ONE registry entry).
GGUF_BASE = {"id": "Qwen3-TTS-12Hz-1.7B-Base-Q4_K_M",
             "name": "Qwen3-TTS-12Hz-1.7B-Base-Q4_K_M", "format": "gguf",
             "path": "/M/Qwen3-TTS/Qwen3-TTS-12Hz-1.7B-Base-Q4_K_M.gguf",
             "mmproj": "/M/Qwen3-TTS/mmproj-Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf",
             "size_bytes": 1_030_000_000, "ctx": None, "source": "download",
             "vision": True, "repo": "ggml-org/Qwen3-TTS-12Hz-1.7B-Base-GGUF"}

e = voice.audio_download_entry(GGUF_BASE, "tts-gguf")
check("gguf pair → kind:'audio'", e["kind"] == "audio")
check("gguf pair → format tts-gguf", e["format"] == "tts-gguf")
check("gguf pair → path is the BACKBONE gguf", e["path"] == GGUF_BASE["path"])
check("gguf pair → mmproj is the PROJECTOR gguf", e["mmproj"] == GGUF_BASE["mmproj"])
check("gguf pair → ONE entry carrying both halves (not two)",
      isinstance(e, dict) and e["path"] != e["mmproj"])
check("gguf pair → keeps size_bytes", e["size_bytes"] == 1_030_000_000)
check("gguf pair → keeps repo provenance", e["repo"] == GGUF_BASE["repo"])
check("gguf pair → keeps source", e["source"] == "download")
check("gguf pair → drops the chat-only 'vision' flag", "vision" not in e)
check("gguf pair → drops the chat-only 'ctx' field", "ctx" not in e)
check("gguf pair → is_audio_entry", voice.is_audio_entry(e))
check("gguf pair → is_tts_entry", voice.is_tts_entry(e))
check("gguf pair → validates as a renderable TTS request",
      voice.validate_tts_request("hi", e) is None)

MLX_BASE = {"id": "Kokoro-82M-bf16", "name": "Kokoro-82M-bf16", "format": "mlx",
            "path": "/M/Kokoro-82M-bf16", "mmproj": None, "size_bytes": 408_000_000,
            "ctx": None, "source": "download", "vision": False,
            "repo": "mlx-community/Kokoro-82M-bf16"}
e = voice.audio_download_entry(MLX_BASE, "tts-mlx")
check("mlx tts → format tts-mlx + dir path",
      e["format"] == "tts-mlx" and e["path"] == "/M/Kokoro-82M-bf16")
check("mlx tts → mmproj stays None (mlx-audio takes a dir, nothing else)",
      e["mmproj"] is None)
check("mlx tts → is_tts_entry", voice.is_tts_entry(e))

e = voice.audio_download_entry(
    {"id": "whisper-base-mlx", "format": "mlx", "path": "/M/whisper-base-mlx",
     "mmproj": None, "size_bytes": 143_000_000, "source": "download"}, "stt-mlx")
check("mlx stt → format stt-mlx", e["format"] == "stt-mlx")
check("mlx stt → is_stt_entry, NOT is_tts_entry",
      voice.is_stt_entry(e) and not voice.is_tts_entry(e))
check("mlx stt → refused as a TTS render target",
      voice.validate_tts_request("hi", e) is not None)

# An mmproj on a NON-gguf format would be dead weight and would show a bogus path in
# the detail pane — it is dropped, not carried.
e = voice.audio_download_entry({**MLX_BASE, "mmproj": "/M/stray.gguf"}, "tts-mlx")
check("mlx entry never carries an mmproj even if the base had one", e["mmproj"] is None)

try:
    voice.audio_download_entry(GGUF_BASE, "gguf")
    check("a non-audio format hint raises", False)
except ValueError:
    check("a non-audio format hint raises", True)
try:
    voice.audio_download_entry(GGUF_BASE, "")
    check("an empty format hint raises", False)
except ValueError:
    check("an empty format hint raises", True)

# ══ 2. seed_registry.audio_format_for — the conservative Rescan classifier ══════
MLX_FILES = ["config.json", "model.safetensors", "tokenizer.json"]
GGUF_TTS_FILES = ["Qwen3-TTS-12Hz-1.7B-Base-Q4_K_M.gguf",
                  "mmproj-Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf"]

check("mlx dir named *TTS* → tts-mlx",
      sr.audio_format_for("Qwen3-TTS-12Hz-1.7B-Base-8bit", MLX_FILES) == "tts-mlx")
check("mlx dir named Kokoro → tts-mlx",
      sr.audio_format_for("Kokoro-82M-bf16", MLX_FILES) == "tts-mlx")
check("mlx dir named OuteTTS → tts-mlx",
      sr.audio_format_for("OuteTTS-1.0-0.6B", MLX_FILES) == "tts-mlx")
check("mlx dir named whisper* → stt-mlx",
      sr.audio_format_for("whisper-large-v3-turbo", MLX_FILES) == "stt-mlx")
check("gguf backbone + mmproj with a TTS name → tts-gguf",
      sr.audio_format_for("Qwen3-TTS-12Hz-1.7B-Base-Q4_K_M", GGUF_TTS_FILES) == "tts-gguf")
check("gguf pair with a neutral DIR name but a TTS FILE name → tts-gguf",
      sr.audio_format_for("downloaded-thing", GGUF_TTS_FILES) == "tts-gguf")

# ── negatives: every one of these is a chat model that must stay a chat model ──
check("plain mlx chat dir → None",
      sr.audio_format_for("Qwen3.6-35B-A3B-8bit", MLX_FILES) is None)
check("VISION mlx chat dir → None (vision_config is not audio)",
      sr.audio_format_for("Qwen3-VL-4B-Instruct-4bit", MLX_FILES) is None)
check("vision GGUF chat pair (gguf + mmproj, no TTS token) → None",
      sr.audio_format_for("gemma-4-31b-vision-Q4_K_M",
                          ["gemma-4-31b-vision-Q4_K_M.gguf", "mmproj-F16.gguf"]) is None)
check("a LONE tts-named gguf without its mmproj → None (llama-tts needs both)",
      sr.audio_format_for("some-tts-model", ["some-tts-model-Q4_K_M.gguf"]) is None)
check("a tts-named dir with neither shape → None",
      sr.audio_format_for("my-tts-notes", ["README.md"]) is None)
check("an mlx dir missing config.json → None",
      sr.audio_format_for("whisper-base-mlx", ["model.safetensors"]) is None)
check("an mlx dir missing safetensors → None",
      sr.audio_format_for("whisper-base-mlx", ["config.json"]) is None)
check("empty file list → None", sr.audio_format_for("Kokoro-82M", []) is None)
check("STT beats TTS when both tokens are present (never a tts-mlx whisper)",
      sr.audio_format_for("whisper-tts-hybrid", MLX_FILES) == "stt-mlx")

# ══ 3. scan_audio_local / local_entries_for — against a real temp tree ══════════
tmp = tempfile.mkdtemp(prefix="audioreg-")
models = os.path.join(tmp, "models")
touch(os.path.join(models, "Kokoro-82M-bf16", "config.json"), 10)
touch(os.path.join(models, "Kokoro-82M-bf16", "model.safetensors"), 400)
touch(os.path.join(models, "Qwen3-TTS-Q4_K_M", "Qwen3-TTS-Q4_K_M.gguf"), 900)
touch(os.path.join(models, "Qwen3-TTS-Q4_K_M", "mmproj-Qwen3-TTS-Q8_0.gguf"), 100)
touch(os.path.join(models, "qwen-35b-chat", "model.gguf"), 700)      # scan_local shape
touch(os.path.join(models, "gemma-vision", "model.gguf"), 600)       # chat + vision
touch(os.path.join(models, "gemma-vision", "mmproj.gguf"), 60)

au = sr.scan_audio_local(models)
by_id = {m["id"]: m for m in au}
check("scan_audio_local finds exactly the two voice folders",
      sorted(by_id) == ["Kokoro-82M-bf16", "Qwen3-TTS-Q4_K_M"])
check("scan_audio_local leaves the chat folders alone",
      "qwen-35b-chat" not in by_id and "gemma-vision" not in by_id)
k = by_id["Kokoro-82M-bf16"]
check("mlx audio entry: path is the DIR", k["path"] == os.path.abspath(
      os.path.join(models, "Kokoro-82M-bf16")))
check("mlx audio entry: size sums safetensors only", k["size_bytes"] == 400)
check("mlx audio entry: source local (app-owned ⇒ deletable)", k["source"] == "local")
check("mlx audio entry: kind audio", k["kind"] == "audio")
g = by_id["Qwen3-TTS-Q4_K_M"]
check("gguf audio entry: path is the backbone",
      os.path.basename(g["path"]) == "Qwen3-TTS-Q4_K_M.gguf")
check("gguf audio entry: mmproj is the projector",
      os.path.basename(g["mmproj"]).startswith("mmproj-"))
check("gguf audio entry: size is the backbone's", g["size_bytes"] == 900)
check("every scanned audio entry survives voice.is_audio_entry",
      all(voice.is_audio_entry(m) for m in au))

le = sr.local_entries_for(models)
ids = [m["id"] for m in le]
check("local_entries_for keeps the plain chat folders", "qwen-35b-chat" in ids)
check("local_entries_for emits no duplicate ids", len(ids) == len(set(ids)))
check("local_entries_for: the vision chat pair stays a CHAT entry",
      next(m for m in le if m["id"] == "gemma-vision").get("kind") != "audio")

# A folder matching BOTH scanners (model.gguf + mmproj.gguf, TTS-named) must yield ONE
# entry — the audio one. This is the double-listing trap local_entries_for exists for.
touch(os.path.join(models, "my-tts-voice", "model.gguf"), 500)
touch(os.path.join(models, "my-tts-voice", "mmproj.gguf"), 50)
le2 = sr.local_entries_for(models)
dupes = [m for m in le2 if m["id"] == "my-tts-voice"]
check("a folder matching BOTH scanners yields exactly one entry", len(dupes) == 1)
check("…and that one entry is the AUDIO one", dupes[0].get("kind") == "audio")

# ══ 4. scan_audio_hf_cache ═════════════════════════════════════════════════════
hub = os.path.join(tmp, "hub")
snap = os.path.join(hub, "models--mlx-community--whisper-base-mlx", "snapshots", "abc123")
touch(os.path.join(snap, "config.json"), 10)
touch(os.path.join(snap, "weights.safetensors"), 137)
chat = os.path.join(hub, "models--mlx-community--Qwen3-35B-8bit", "snapshots", "def456")
touch(os.path.join(chat, "config.json"), 10)
touch(os.path.join(chat, "model.safetensors"), 9000)
cache = sr.scan_audio_hf_cache(hub)
check("hf cache: picks up the whisper repo",
      [m["id"] for m in cache] == ["whisper-base-mlx"])
check("hf cache: ignores the chat repo entirely",
      not any("Qwen3" in m["id"] for m in cache))
check("hf cache: path is the snapshot dir", cache[0]["path"] == os.path.abspath(snap))
check("hf cache: source audio-hf-cache (read-only ⇒ NOT deletable)",
      cache[0]["source"] == "audio-hf-cache")
check("hf cache: classified stt-mlx", cache[0]["format"] == "stt-mlx")
check("hf cache: a missing hub dir is not an error",
      sr.scan_audio_hf_cache(os.path.join(tmp, "nope")) == [])

# ══ 5. merge semantics ═════════════════════════════════════════════════════════
existing = [
    {"id": "dl-chat", "source": "download", "format": "gguf", "ctx": 95536},
    {"id": "dl-voice", "source": "download", "kind": "audio", "format": "tts-gguf"},
    {"id": "gone-from-cache", "source": "audio-hf-cache", "kind": "audio",
     "format": "stt-mlx"},
]
merged = sr.merge(existing, [], [], [], cache)
mids = [m["id"] for m in merged]
check("merge preserves source='download' CHAT entries", "dl-chat" in mids)
check("merge preserves source='download' AUDIO entries", "dl-voice" in mids)
check("merge drops an audio-hf-cache entry that is no longer in the cache",
      "gone-from-cache" not in mids)
check("merge adds the freshly scanned cache entry", "whisper-base-mlx" in mids)
check("merge still preserves ctx on kept entries",
      next(m for m in merged if m["id"] == "dl-chat")["ctx"] == 95536)

# id collision: the same model already reached the registry via a download → the
# cache copy is DROPPED (not suffixed), so the user never sees two rows for one model.
collide = sr.merge([{"id": "whisper-base-mlx", "source": "download", "kind": "audio",
                     "format": "stt-mlx", "path": "/data/models/whisper-base-mlx"}],
                   [], [], [], cache)
check("hf-cache entry DROPS on id collision with a download entry",
      len(collide) == 1 and collide[0]["source"] == "download")

# Existing behaviour must be untouched: lmstudio still suffixes on collision.
lms = sr.merge([], [], [{"id": "x", "source": "lmstudio-import"}],
               [{"id": "x", "source": "local"}])
check("lmstudio -lms suffix on collision still works",
      sorted(m["id"] for m in lms) == ["x", "x-lms"])

# ══ 6. THE INVARIANT — audio never reaches the chat `installed` list ════════════
# Against the REAL /api/models handler with a temp ROOT (not a source read).
from bridge import app  # noqa: E402

apiroot = Path(tempfile.mkdtemp(prefix="audioapi-"))
shutil.copy(ROOT / "harness.yaml", apiroot / "harness.yaml")
(apiroot / "data").mkdir()
(apiroot / "data" / "models.json").write_text(json.dumps({"models": [
    {"id": "chat-gguf", "format": "gguf", "path": "/m/a.gguf", "size_bytes": 10},
    {"id": "chat-mlx", "format": "mlx", "path": "/m/b", "size_bytes": 20},
    GGUF_BASE | {"id": "voice-gguf", "kind": "audio", "format": "tts-gguf"},
    {"id": "voice-mlx", "kind": "audio", "format": "tts-mlx", "path": "/m/k"},
    {"id": "voice-stt", "kind": "audio", "format": "stt-mlx", "path": "/m/w"},
    # kind MISSING but an audio format — the belt-and-suspenders case.
    {"id": "voice-nokind", "format": "tts-mlx", "path": "/m/n"},
]}))
_saved = (app.ROOT, app._live_model_id, app._port_alive_sync)
app.ROOT, app._live_model_id, app._port_alive_sync = apiroot, (lambda p: None), (lambda p: False)
try:
    payload = json.loads(bytes(app.api_models().body).decode())
finally:
    app.ROOT, app._live_model_id, app._port_alive_sync = _saved

inst = [m["id"] for m in payload["installed"]]
aud = [m["id"] for m in payload["audio"]]
check("api_models: chat models land in `installed`",
      sorted(inst) == ["chat-gguf", "chat-mlx"])
check("api_models: AUDIO MODELS NEVER APPEAR IN `installed`",
      not any(i.startswith("voice-") for i in inst))
check("api_models: every audio model lands in `audio`",
      sorted(aud) == ["voice-gguf", "voice-mlx", "voice-nokind", "voice-stt"])
check("api_models: an entry with an audio FORMAT but no `kind` is still partitioned out",
      "voice-nokind" in aud and "voice-nokind" not in inst)
check("api_models: audio views carry role/engine for the Audio tab rows",
      {a["id"]: (a["role"], a["engine"]) for a in payload["audio"]}["voice-stt"]
      == ("stt", "mlx")
      and {a["id"]: a["engine"] for a in payload["audio"]}["voice-gguf"] == "llamacpp")
check("api_models: the `voice` block is exposed for the default pills",
      isinstance(payload.get("voice"), dict) and "tts_model" in payload["voice"])
check("api_models: the RAM ledger ignores audio models (transient by design)",
      payload["ledger"]["used_bytes"] == 0)

# ══ 7. app wiring the download path actually uses (source-pinned) ══════════════
src = (ROOT / "bridge" / "app.py").read_text()
check("dl_start accepts the voice_format hint", 'body.get("voice_format")' in src)
check("dl_start accepts an explicit mmproj filename", 'body.get("mmproj")' in src)
check("_mk_download carries voice_format", "voice_format=voice_format" in src)
check("_run_download converts via voice.audio_download_entry",
      "_voice.audio_download_entry(base, vf)" in src)
check("an explicit mmproj overrides the lone-sibling heuristic", "if mmproj_req:" in src)
check("deleting a model clears it as a voice default too",
      'was_voice = [k for k in ("tts_model", "stt_model")' in src)

pan = (ROOT / "bridge" / "panel" / "index.html").read_text()
check("panel persists the sub-tab under harness-models-section",
      "'harness-models-section'" in pan)
check("panel Get buttons pass the voice_format hint", "voice_format: s.fmt" in pan)
check("the Qwen3-TTS gguf offer names BOTH files",
      "Qwen3-TTS-12Hz-1.7B-Base-Q4_K_M.gguf" in pan
      and "mmproj-Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf" in pan)
check("the Kokoro card carries the misaki/torch warning",
      "misaki" in pan and "torch-free" in pan)

shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(apiroot, ignore_errors=True)

print()
print(f"{'FAILED: ' + ', '.join(FAILS) if FAILS else 'ALL PASS'}")
sys.exit(1 if FAILS else 0)
