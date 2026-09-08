"""Unit tests for REFERENCE-AUDIO VOICE CONTROL + the voice library.

WHY THIS SLICE EXISTS: OmniVoice is a zero-shot model — `Model.generate()` in
mlx_audio/tts/models/omnivoice/omnivoice.py takes ref_audio / ref_text /
ref_audio_max_duration_s and has NO speaker table at all. It therefore renders a
DIFFERENT random voice every ▶ speak, and no --voice can fix that. Determinism = the
same clip, every render.

What is pinned here, and why each one is load-bearing:

  * THE CLONING VERDICT. `is_cloning_model` reads the checkpoint's own config, never
    a name token. mlx-audio ROUTES on `model_type` (MODEL_REMAPPING["omnivoice"]), so
    a model that loads as OmniVoice necessarily declares it.
  * ARGV. `--ref_audio` appears ONLY when pinned and NEVER on the gguf branch —
    llama-tts has no such flag (it takes --tts-speaker-file, a different mechanism),
    and a pin that silently did nothing would be worse than a refusal.
  * NAME SAFETY. A clip name becomes a FILENAME: basename-only, allowlisted
    characters, suffix forced from the recorder's fmt, and an existing file is never
    clobbered (a recording cannot be re-made).
  * CONTAINMENT. `library_target` must refuse anything that realpaths outside
    data/voices — it is the input to a delete.

Run: python3 bridge/tests/test_voice_ref.py     (from repo root)
"""
import os
import sys
import tempfile
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


# ── is_cloning_model: the decision table ───────────────────────────────────────
check("OmniVoice's own model_type is a cloning verdict",
      voice.is_cloning_model({"model_type": "omnivoice"}) is True)
check("the Qwen3-TTS Base variant is cloning (tts_model_type)",
      voice.is_cloning_model({"tts_model_type": "base"}) is True)
check("voice_design is cloning", voice.is_cloning_model({"tts_model_type": "voice_design"}))
check("CustomVoice is NOT cloning (it has named speakers)",
      voice.is_cloning_model({"tts_model_type": "custom_voice"}) is False)
check("a Kokoro-ish config is not cloning",
      voice.is_cloning_model({"model_type": "kokoro"}) is False)
check("case and whitespace do not change the verdict",
      voice.is_cloning_model({"model_type": "  OmniVoice "}) is True)
check("a non-dict config is never a verdict",
      voice.is_cloning_model(None) is False and voice.is_cloning_model("omnivoice") is False
      and voice.is_cloning_model([1, 2]) is False)
check("a surprise type on the key cannot raise",
      voice.is_cloning_model({"model_type": {"a": 1}}) is False)
check("an empty config is not a verdict", voice.is_cloning_model({}) is False)

# ── voices_for_entry carries the verdict (one config read, no second probe) ────
with tempfile.TemporaryDirectory() as td:
    def _model(name, cfg_text, voices=None):
        d = os.path.join(td, name)
        os.makedirs(os.path.join(d, "voices") if voices else d, exist_ok=True)
        with open(os.path.join(d, "config.json"), "w") as f:
            f.write(cfg_text)
        for v in (voices or []):
            open(os.path.join(d, "voices", v + ".pt"), "wb").write(b"x")
        return {"id": name, "kind": "audio", "format": "tts-mlx", "path": d}

    omni = _model("omni", '{"model_type": "omnivoice", "sample_rate": 24000}')
    custom = _model("cv", '{"tts_model_type": "custom_voice", "talker_config":'
                          ' {"spk_id": {"serena": 0, "ryan": 1}}}')
    base = _model("base", '{"tts_model_type": "base", "talker_config": {"spk_id": {}}}')
    kok = _model("kokoro", '{"model_type": "kokoro"}', voices=["af_heart", "am_adam"])
    junk = _model("junk", "not json at all")
    voice.clear_voices_cache()

    vo = voice.voices_for_entry(omni)
    check("OmniVoice: cloning true, no names, no dead-end note",
          vo["cloning"] is True and vo["voices"] == [])
    vc = voice.voices_for_entry(custom)
    check("CustomVoice: names win, cloning false",
          vc["voices"] == ["serena", "ryan"] and vc["cloning"] is False)
    vb = voice.voices_for_entry(base)
    check("Base: declared-but-empty spk_id is a cloning verdict too",
          vb["cloning"] is True and vb["voices"] == [] and vb["note"])
    vk = voice.voices_for_entry(kok)
    check("Kokoro: voices/*.pt stems still win, cloning false",
          vk["voices"] == ["af_heart", "am_adam"] and vk["cloning"] is False)
    vj = voice.voices_for_entry(junk)
    check("an unreadable config asserts NOTHING about cloning", vj["cloning"] is False)
    check("an entry whose path does not exist is not called cloning",
          voice.voices_for_entry({"id": "x", "kind": "audio", "format": "tts-mlx",
                                  "path": "/no/such/dir"})["cloning"] is False)
    check("a gguf entry never gets a cloning verdict",
          voice.voices_for_entry({"id": "g", "kind": "audio", "format": "tts-gguf",
                                  "path": "/m/b.gguf"})["cloning"] is False)

    # the VIEW the panel branches on
    view = voice.audio_entry_view(dict(omni, ref_audio=os.path.join(td, "clip.wav"),
                                       ref_text="hello there"))
    check("audio_entry_view exposes cloning", view["cloning"] is True)
    check("the view carries the clip NAME, never the full path",
          view["ref_audio"] == "clip.wav" and td not in str(view["ref_audio"]))
    check("the view carries ref_text", view["ref_text"] == "hello there")
    check("an unpinned entry reports ref_audio None",
          voice.audio_entry_view(omni)["ref_audio"] is None)

# ── argv: --ref_audio only when pinned, never on gguf ──────────────────────────
MLX = {"id": "omnivoice", "kind": "audio", "format": "tts-mlx", "path": "/M/omni"}
GGUF = {"id": "q-gguf", "kind": "audio", "format": "tts-gguf",
        "path": "/M/b.gguf", "mmproj": "/M/m.gguf"}

a = voice.tts_argv(MLX, "hi", "/tmp/o/out.wav", "/bin/llama-tts", "/venv/bin/python")
check("no ref pinned ⇒ no --ref_audio in the argv", "--ref_audio" not in a)
a = voice.tts_argv(dict(MLX, ref_audio="/lib/debi.wav"), "hi", "/tmp/o/out.wav",
                   "/bin/llama-tts", "/venv/bin/python")
check("a pinned clip becomes --ref_audio <path>",
      a[a.index("--ref_audio") + 1] == "/lib/debi.wav")
check("no transcript ⇒ no --ref_text", "--ref_text" not in a)
a = voice.tts_argv(dict(MLX, ref_audio="/lib/debi.wav", ref_text="one two"), "hi",
                   "/tmp/o/out.wav", "/bin/llama-tts", "/venv/bin/python")
check("a transcript becomes --ref_text <text>", a[a.index("--ref_text") + 1] == "one two")
a = voice.tts_argv(dict(MLX, ref_text="orphan"), "hi", "/tmp/o/out.wav",
                   "/bin/llama-tts", "/venv/bin/python")
check("ref_text WITHOUT a clip is not emitted (a caption alone is not a voice)",
      "--ref_text" not in a)
a = voice.tts_argv(dict(MLX, voice="serena", ref_audio="/lib/debi.wav"), "hi",
                   "/tmp/o/out.wav", "/bin/llama-tts", "/venv/bin/python")
check("a name and a clip may coexist (the engine ignores what it cannot use)",
      "--voice" in a and "--ref_audio" in a)
g = voice.tts_argv(dict(GGUF, ref_audio="/lib/debi.wav", ref_text="x"), "hi",
                   "/tmp/o/out.wav", "/bin/llama-tts", "/venv/bin/python")
check("llama-tts NEVER gets --ref_audio (it has no such flag)",
      "--ref_audio" not in g and "--ref_text" not in g)

# these flags are exactly what mlx_audio.tts.generate's parse_args declares
check("the flag names match the engine's argparse (--ref_audio/--ref_text)",
      "--ref_audio" in voice.tts_argv(dict(MLX, ref_audio="/a.wav"), "t", "/o/o.wav",
                                      "/b", "/p"))

# ── worker protocol: the reference travels PER REQUEST, like the voice ─────────
kw = vw.render_kwargs("hi", "serena", "/tmp/x/out.wav", "/lib/debi.wav", "one two")
check("render_kwargs passes the clip through", kw["ref_audio"] == "/lib/debi.wav")
check("render_kwargs passes the transcript through", kw["ref_text"] == "one two")
kw0 = vw.render_kwargs("hi", None, "/tmp/x/out.wav")
check("CLI PARITY: an absent reference is None, never '' "
      "(generate_audio branches on falsy and would raise on an empty path)",
      kw0["ref_audio"] is None and kw0["ref_text"] is None)
check("an EMPTY-STRING reference normalises to None",
      vw.render_kwargs("hi", None, "/o.wav", "", "")["ref_audio"] is None)
check("whitespace is stripped off the clip path",
      vw.render_kwargs("hi", None, "/o.wav", " /a.wav ")["ref_audio"] == "/a.wav")
check("the reference does not disturb the rest of the CLI-parity dict",
      kw["max_tokens"] is None and kw["join_audio"] is True
      and kw["stt_model"] == vw.CLI_PARITY_KWARGS["stt_model"])

# ── validation: suffix / size / existence ─────────────────────────────────────
check("wav/mp3/flac/m4a are the accepted containers",
      voice.REF_AUDIO_SUFFIXES == ("wav", "mp3", "flac", "m4a"))
for s, want in [("wav", "wav"), (".WAV", "wav"), ("audio/mpeg", "mp3"),
                ("clip.flac", "flac"), ("audio/x-m4a", "m4a"), ("wave", "wav")]:
    check(f"normalize_ref_suffix({s!r}) = {want}", voice.normalize_ref_suffix(s) == want)
for s in ("webm", "mp4", "ogg", "", None, "txt", 7, {"a": 1}):
    check(f"normalize_ref_suffix rejects {s!r}", voice.normalize_ref_suffix(s) is None)

with tempfile.TemporaryDirectory() as td:
    good = os.path.join(td, "ok.wav")
    open(good, "wb").write(b"RIFF" + b"\0" * 2000)
    empty = os.path.join(td, "empty.wav")
    open(empty, "wb").close()
    big = os.path.join(td, "big.wav")
    with open(big, "wb") as f:
        f.write(b"\0" * (voice.REF_AUDIO_MAX_BYTES + 1))
    wrong = os.path.join(td, "clip.webm")
    open(wrong, "wb").write(b"\0" * 10)

    check("a real wav validates", voice.validate_ref_audio(good) is None)
    check("a missing file is refused", "no such clip" in voice.validate_ref_audio(
        os.path.join(td, "nope.wav")))
    check("an EMPTY file is refused", "empty" in voice.validate_ref_audio(empty))
    check("an oversized clip is refused by size, not by luck",
          "too large" in voice.validate_ref_audio(big))
    check("an unsupported container is refused before it reaches the engine",
          "unsupported clip format" in voice.validate_ref_audio(wrong))
    check("no path at all is refused", voice.validate_ref_audio("") is not None)

    # validate_ref_choice: the entry half
    check("a clip may be pinned on a tts-mlx entry",
          voice.validate_ref_choice(MLX, good) is None)
    check("clearing is always allowed", voice.validate_ref_choice(MLX, "") is None)
    check("a gguf entry is refused, and the message names the real mechanism",
          "--tts-speaker-file" in (voice.validate_ref_choice(GGUF, good) or ""))
    check("an STT entry is refused",
          voice.validate_ref_choice({"id": "w", "kind": "audio", "format": "stt-mlx"},
                                    good) is not None)
    check("a missing entry is refused", voice.validate_ref_choice(None, good) is not None)
    check("a non-string path is refused", voice.validate_ref_choice(MLX, 7) is not None)
    check("a non-string ref_text is refused",
          voice.validate_ref_choice(MLX, good, 7) is not None)
    check("an over-long transcript is refused",
          "too long" in (voice.validate_ref_choice(MLX, good,
                                                   "x" * (voice.REF_TEXT_MAX + 1)) or ""))
    check("a transcript at the cap is fine",
          voice.validate_ref_choice(MLX, good, "x" * voice.REF_TEXT_MAX) is None)

# ── clip names become FILENAMES ───────────────────────────────────────────────
check("a plain name gets the recorder's suffix",
      voice.sanitize_clip_name("debi", "wav") == "debi.wav")
check("?fmt beats the typed suffix (the recorder knows its container)",
      voice.sanitize_clip_name("debi.mp3", "wav") == "debi.wav")
check("a name's own suffix is used when no fmt is given",
      voice.sanitize_clip_name("debi.flac") == "debi.flac")
check("a path is reduced to its basename",
      voice.sanitize_clip_name("../../etc/passwd", "wav") == "passwd.wav")
check("a traversal with no stem left is refused",
      voice.sanitize_clip_name("../", "wav") is None)
check("shell/url punctuation is stripped",
      voice.sanitize_clip_name("de$bi;rm -rf&", "wav") == "debirm -rf.wav")
check("an empty name is refused", voice.sanitize_clip_name("", "wav") is None)
check("a name with no usable format is refused",
      voice.sanitize_clip_name("debi", "") is None
      and voice.sanitize_clip_name("debi.webm") is None)
check(f"a name over {voice.VOICE_LIB_NAME_MAX} chars is refused",
      voice.sanitize_clip_name("x" * (voice.VOICE_LIB_NAME_MAX + 1), "wav") is None)
check("a name at the cap is accepted",
      voice.sanitize_clip_name("x" * voice.VOICE_LIB_NAME_MAX, "wav")
      == "x" * voice.VOICE_LIB_NAME_MAX + ".wav")
check("a NUL byte cannot reach the filesystem",
      "\x00" not in (voice.sanitize_clip_name("a\x00b", "wav") or ""))
check("junk input is total (None, not an exception)",
      voice.sanitize_clip_name(None, None) is None
      and voice.sanitize_clip_name(7, {"a": 1}) is None)

# ── the library: listing, never-clobber, containment ──────────────────────────
with tempfile.TemporaryDirectory() as td:
    R = Path(td)
    d = Path(voice.voices_dir(R))
    check("the library lives at data/voices", str(d).endswith(os.path.join("data", "voices")))
    check("listing an ABSENT library is empty, not an error", voice.library_entries(R) == [])
    d.mkdir(parents=True)
    (d / "debi.wav").write_bytes(b"RIFF" + b"\0" * 100)
    (d / "aunt.mp3").write_bytes(b"\0" * 50)
    (d / "notes.txt").write_text("not audio")
    (d / "sub").mkdir()
    lib = voice.library_entries(R)
    check("only audio files are listed, sorted",
          [c["name"] for c in lib] == ["aunt.mp3", "debi.wav"])
    check("a listing carries name, stem, path and size",
          lib[1]["stem"] == "debi" and lib[1]["size"] == 104
          and lib[1]["path"].endswith("debi.wav"))
    check("a subdirectory is not a clip", all(c["name"] != "sub" for c in lib))

    p1 = voice.unique_clip_path(str(d), "debi.wav")
    check("never-clobber: an existing name gets a ' (n)' suffix",
          os.path.basename(p1) == "debi (1).wav")
    (d / "debi (1).wav").write_bytes(b"x")
    check("never-clobber counts up",
          os.path.basename(voice.unique_clip_path(str(d), "debi.wav")) == "debi (2).wav")
    check("a free name is used as-is",
          os.path.basename(voice.unique_clip_path(str(d), "new.wav")) == "new.wav")

    p, why = voice.library_target("debi.wav", R)
    check("library_target resolves a real clip", p and p.endswith("debi.wav") and why is None)
    check("library_target refuses a traversal",
          voice.library_target("../../../etc/passwd", R)[0] is None)
    check("library_target refuses an absolute path outside the library",
          voice.library_target("/etc/passwd", R)[0] is None)
    check("library_target refuses a name that is not there",
          voice.library_target("ghost.wav", R)[0] is None)
    check("library_target refuses an empty name", voice.library_target("", R)[0] is None)
    check("library_target refuses the DIRECTORY itself",
          voice.library_target("sub", R)[0] is None)

# ── bridge wiring, read from the source (one writer, one guard) ───────────────
APP = _APP_SOURCE
check("POST /api/voice/entry-ref exists", '@app.post("/api/voice/entry-ref")' in APP)
check("GET /api/voice/library exists", '@app.get("/api/voice/library")' in APP)
check("POST /api/voice/library/save exists", '@app.post("/api/voice/library/save")' in APP)
check("POST /api/voice/library/delete exists", '@app.post("/api/voice/library/delete")' in APP)
check("entry-ref writes through the atomic _registry_update",
      "_registry_update(mid, patch, expected=entry)" in APP)
check("entry-ref validates before writing", "validate_ref_choice(entry, path, ref_text)" in APP)
check("a library name is resolved through the containment guard",
      "library_target(name, ROOT)" in APP)
check("delete is guarded by the same containment helper",
      'library_target(body.get("name"), ROOT)' in APP)
DELETE = APP.split("async def voice_library_delete(", 1)[1].split('\n@app.', 1)[0]
check("deleting a clip UN-PINS every entry that used it in the registry transaction",
      'for m in data["models"]:' in DELETE
      and 'm.pop("ref_audio", None)' in DELETE and 'm.pop("ref_text", None)' in DELETE
      and 'write_registry' in DELETE)
check("a saved clip never clobbers", "unique_clip_path(d, name)" in APP)
check("the save endpoint sanitizes the name server-side", "sanitize_clip_name(" in APP)
check("the save endpoint caps the body", "REF_AUDIO_MAX_BYTES" in APP)
check("a ref change does NOT restart the worker (it is per-request)",
      "entry-ref" in APP
      and not __import__("re").search(r"voice_entry_ref[\s\S]{0,2500}worker_stop", APP))

PANEL = (ROOT / "bridge" / "panel" / "index.html").read_text()
check("the panel has a 'clips' picker mode", "if (a.cloning) return 'clips';" in PANEL)
check("the panel pins a clip through /api/voice/entry-ref",
      "fetch('/api/voice/entry-ref'" in PANEL)
check("the panel reads the library", "fetch('/api/voice/library')" in PANEL)
check("the panel records and saves a clip",
      "/api/voice/library/save?name=" in PANEL and "🎙 record" in PANEL)
check("the recorder encodes a WAV client-side (miniaudio reads it with no ffmpeg)",
      "function wavFromBuffer(" in PANEL and "decodeAudioData" in PANEL)
check("'model default' is labelled honestly for a cloning model",
      "Random voice per render — pin a clip for a consistent voice" in PANEL)
check("the note points at the library directory",
      "to grow this list" in PANEL)

print()
print(f"{'FAIL' if FAILS else 'OK'} — {len(FAILS)} failure(s)")
if FAILS:
    for f_ in FAILS:
        print("  -", f_)
sys.exit(1 if FAILS else 0)
