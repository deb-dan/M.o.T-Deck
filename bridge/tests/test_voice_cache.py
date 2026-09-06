"""Unit tests for VOICE RENDER PERF + the clip-folder sources (2026-08-13).

WHAT THIS SLICE FIXES, and therefore what these tests are guarding:

  * THE REPLAY CACHE. Re-speaking the SAME reply re-rendered from scratch. The cache
    key must cover every input that can change the audio — model, resolved voice,
    reference clip PATH **and its stat**, transcript, text — because there is
    deliberately no invalidation anywhere: if the key is wrong, the user hears the
    wrong voice, which is far worse than a slow render.
  * THE ref_text SELF-HEAL. `generate_audio` handed a clip with no transcript loads
    whisper-large-v3-turbo on EVERY render and throws it away again. Pin-time
    transcription only helps clips pinned AFTER that shipped, so `needs_ref_text`
    identifies the entries that must be healed at render time.
  * CLIP FOLDERS. The listing endpoint reads a directory named by a QUERY PARAMETER,
    so `folder_allowed` is the entire boundary: an exact-match allowlist of folders
    the user themselves added — no prefixes, no descent into children.

Run: python3 bridge/tests/test_voice_cache.py    (from repo root)
"""
import os
import sys
import tempfile
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

FAILS = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


# ── render_cache_key: PURE, and total over every field ──────────────────────────
K = voice.render_cache_key
BASE = K("m", "serena", "/a/b.wav", "hello there", "the text", "12:99")

check("the key is deterministic", K("m", "serena", "/a/b.wav", "hello there",
                                    "the text", "12:99") == BASE)
check("a different model is a different key",
      K("m2", "serena", "/a/b.wav", "hello there", "the text", "12:99") != BASE)
check("a different voice is a different key",
      K("m", "vivian", "/a/b.wav", "hello there", "the text", "12:99") != BASE)
check("a different clip is a different key",
      K("m", "serena", "/a/c.wav", "hello there", "the text", "12:99") != BASE)
check("a different transcript is a different key",
      K("m", "serena", "/a/b.wav", "hello THERE", "the text", "12:99") != BASE)
check("a different text is a different key",
      K("m", "serena", "/a/b.wav", "hello there", "other text", "12:99") != BASE)
check("A DIFFERENT CLIP STAMP IS A DIFFERENT KEY (re-recorded at the same path)",
      K("m", "serena", "/a/b.wav", "hello there", "the text", "13:99") != BASE)
# The separator matters: with a printable join, ("a|b", "c") and ("a", "b|c") collide.
check("field boundaries cannot be forged by field CONTENT",
      K("m", "a", "b", "c", "d", "") != K("m", "a", "b", "c\x00d", "", ""))
check("None and '' are the same absent field",
      K("m", None, None, None, "t", None) == K("m", "", "", "", "t", ""))
check("junk inputs never raise", isinstance(K(1, 2.5, [], {}, None, object()), str))
check("the key is a hex digest", len(BASE) == 64 and all(c in "0123456789abcdef"
                                                         for c in BASE))


# ── ref_stamp ───────────────────────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "clip.wav")
    with open(p, "wb") as f:
        f.write(b"x" * 10)
    s1 = voice.ref_stamp(p)
    check("a real clip stamps to '<size>:<mtime>'", s1.startswith("10:"))
    with open(p, "wb") as f:
        f.write(b"y" * 40)
    os.utime(p, (time.time() + 5, time.time() + 5))
    check("rewriting the clip changes the stamp", voice.ref_stamp(p) != s1)
    check("a missing clip stamps to ''", voice.ref_stamp(os.path.join(td, "no.wav")) == "")
    check("no clip stamps to ''", voice.ref_stamp("") == "" and voice.ref_stamp(None) == "")


# ── RenderCache: LRU + a byte budget ────────────────────────────────────────────
c = voice.RenderCache(max_entries=3, max_bytes=1000)
check("a miss returns None", c.get("nope") is None)
c.put("a", b"1" * 10)
c.put("b", b"2" * 10)
c.put("c", b"3" * 10)
check("a hit returns the exact bytes", c.get("a") == b"1" * 10)
c.put("d", b"4" * 10)          # 'a' was just touched, so 'b' is now the oldest
check("the LRU evicts the LEAST RECENTLY USED, not the oldest inserted",
      c.get("b") is None and c.get("a") == b"1" * 10 and c.get("d") == b"4" * 10)
check("the entry count is bounded", c.stats()["entries"] <= 3)

cb = voice.RenderCache(max_entries=100, max_bytes=100)
cb.put("x", b"z" * 60)
cb.put("y", b"z" * 60)
check("the BYTE budget evicts even when the count is fine",
      cb.stats()["bytes"] <= 100 and cb.get("x") is None and cb.get("y") is not None)
check("a payload larger than the whole budget is refused, not stored",
      cb.put("huge", b"z" * 500) is False and cb.get("huge") is None)
check("refusing an oversized payload does not evict the good entry",
      cb.get("y") is not None)
check("empty / non-bytes are never cached",
      cb.put("e", b"") is False and cb.put("e", "str") is False
      and cb.put("", b"data") is False)
cb.put("y", b"z" * 20)
check("re-putting a key replaces its bytes AND its accounting",
      cb.get("y") == b"z" * 20 and cb.stats()["bytes"] == 20)
cb.clear()
check("clear empties both the map and the byte count",
      cb.stats()["entries"] == 0 and cb.stats()["bytes"] == 0)
check("stats reports hits and misses", set(["hits", "misses", "entries", "bytes"])
      <= set(voice.cache_stats().keys()))
check("the module singleton round-trips",
      (voice.cache_put("k1", b"wav"), voice.cache_get("k1"))[1] == b"wav")
voice.cache_clear()
check("cache_clear drops the singleton's entries", voice.cache_get("k1") is None)


# ── entry_cache_key: uses the RESOLVED voice ────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    # A CustomVoice-shaped model dir: config declares serena first, so a model-default
    # render resolves to 'serena' — and must therefore share a cache slot with an
    # explicit serena pin rather than occupying a second one.
    md = os.path.join(td, "cv")
    os.makedirs(md)
    with open(os.path.join(md, "config.json"), "w") as f:
        f.write('{"tts_model_type":"custom_voice","talker_config":'
                '{"spk_id":{"serena":0,"vivian":1}}}')
    voice.clear_voices_cache()
    e_default = {"id": "cv", "kind": "audio", "format": "tts-mlx", "path": md}
    e_pinned = dict(e_default, voice="serena")
    check("a model-default render and its resolved pin share ONE cache slot",
          voice.entry_cache_key(e_default, "hi") == voice.entry_cache_key(e_pinned, "hi"))
    check("a different pin is a different slot",
          voice.entry_cache_key(dict(e_default, voice="vivian"), "hi")
          != voice.entry_cache_key(e_pinned, "hi"))
    check("different text is a different slot",
          voice.entry_cache_key(e_pinned, "bye") != voice.entry_cache_key(e_pinned, "hi"))
    voice.clear_voices_cache()


# ── needs_ref_text: the self-heal decision table ────────────────────────────────
A = {"kind": "audio", "format": "tts-mlx"}
check("a clip with NO transcript needs healing",
      voice.needs_ref_text(dict(A, ref_audio="/a/b.wav")) is True)
check("a clip WITH a transcript does not",
      voice.needs_ref_text(dict(A, ref_audio="/a/b.wav", ref_text="hello")) is False)
check("a whitespace-only transcript still needs healing",
      voice.needs_ref_text(dict(A, ref_audio="/a/b.wav", ref_text="   ")) is True)
check("no clip means nothing to heal", voice.needs_ref_text(dict(A)) is False)
check("a gguf model is NEVER healed (llama-tts has no ref_audio at all)",
      voice.needs_ref_text({"kind": "audio", "format": "tts-gguf",
                            "ref_audio": "/a/b.wav"}) is False)
check("an STT entry is never healed",
      voice.needs_ref_text({"kind": "audio", "format": "stt-mlx",
                            "ref_audio": "/a/b.wav"}) is False)
check("junk never raises", voice.needs_ref_text(None) is False
      and voice.needs_ref_text({}) is False)


# ── clip folders ────────────────────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    (root / "data").mkdir()
    fdir = root / "clips"
    fdir.mkdir()
    sub = fdir / "deeper"
    sub.mkdir()
    for n in ("a.wav", "b.mp3", "c.flac", "notes.txt", "d.WAV"):
        (fdir / n).write_bytes(b"x")
    (sub / "hidden.wav").write_bytes(b"x")

    check("normalize_folder resolves a real directory",
          voice.normalize_folder(str(fdir)) == os.path.realpath(str(fdir)))
    check("normalize_folder refuses a FILE", voice.normalize_folder(str(fdir / "a.wav")) is None)
    check("normalize_folder refuses a nonexistent path",
          voice.normalize_folder(str(root / "nope")) is None)
    check("normalize_folder refuses empty",
          voice.normalize_folder("") is None and voice.normalize_folder(None) is None)
    check("normalize_folder expands ~", voice.normalize_folder("~") == os.path.realpath(
          os.path.expanduser("~")))

    ents = voice.folder_entries(str(fdir))
    names = [e["name"] for e in ents]
    check("folder_entries lists only audio files", sorted(names) == ["a.wav", "b.mp3",
                                                                    "c.flac", "d.WAV"])
    check("folder_entries is NON-RECURSIVE (a subfolder's clips never appear)",
          "hidden.wav" not in names)
    check("folder_entries carries stem/path/size",
          all({"name", "stem", "path", "size"} <= set(e.keys()) for e in ents))
    check("folder_entries caps", len(voice.folder_entries(str(fdir), cap=2)) == 2)
    check("folder_entries on a nonexistent folder is [] (never raises)",
          voice.folder_entries(str(root / "nope")) == []
          and voice.folder_entries(None) == [])

    # The allowlist IS the boundary for a query-parameter-driven directory read.
    check("an unconfigured folder is not allowed",
          voice.folder_allowed(str(fdir), []) is False)
    check("a configured folder is allowed",
          voice.folder_allowed(str(fdir), [str(fdir)]) is True)
    check("a CHILD of a configured folder is NOT allowed (exact match, no prefixes)",
          voice.folder_allowed(str(sub), [str(fdir)]) is False)
    check("a traversal out of a configured folder is not allowed",
          voice.folder_allowed(str(fdir) + "/../", [str(fdir)]) is False)
    check("a trailing slash / non-normalised form of a configured folder IS allowed",
          voice.folder_allowed(str(fdir) + "/./", [str(fdir)]) is True)
    check("junk is never allowed", voice.folder_allowed("", [str(fdir)]) is False
          and voice.folder_allowed(None, None) is False)

    check("no folders file yet ⇒ []", voice.load_folders(root) == [])
    voice.save_folders([str(fdir)], root)
    check("folders round-trip through the json", voice.load_folders(root) == [str(fdir)])
    check("the folders file lives under data/",
          os.path.isfile(os.path.join(str(root), "data", voice.FOLDERS_FILENAME)))
    voice.save_folders([str(fdir), str(fdir), "  "], root)
    check("load_folders de-duplicates and drops blanks",
          voice.load_folders(root) == [str(fdir)])
    with open(voice.folders_path(root), "w") as f:
        f.write("{not json")
    check("a corrupt folders file degrades to [] (never raises)",
          voice.load_folders(root) == [])
    voice.save_folders([f"/x/{i}" for i in range(50)], root)
    check("the folder list is capped", len(voice.load_folders(root))
          == voice.FOLDER_LIST_MAX)

    # Suggested folders are EXISTENCE-GATED: an offer that leads nowhere is worse
    # than no offer.
    voice.save_folders([], root)
    check("no suggested folder is offered when none of them exist",
          voice.suggested_folders(root) == [])
    made = root / "vendor" / "voicestudio" / "data" / "outputs"
    made.mkdir(parents=True)
    sug = voice.suggested_folders(root)
    check("an existing suggested folder IS offered",
          any(s["path"] == os.path.realpath(str(made)) for s in sug))
    check("a suggested folder carries a human label",
          all(s.get("label") for s in sug))
    voice.save_folders([os.path.realpath(str(made))], root)
    check("an already-configured folder is no longer suggested",
          not any(s["path"] == os.path.realpath(str(made))
                  for s in voice.suggested_folders(root)))


# ── wiring (read from the real sources, so a rename trips this) ─────────────────
APP = _APP_SOURCE
check("/api/voice/tts consults the replay cache before rendering",
      "entry_cache_key(entry, text)" in APP and "cache_get(ckey)" in APP)
check("a cache hit is labelled in the response header",
      '"X-MOT-Deck-Voice-Cached": "1"' in APP)
check("voice response header names remain valid HTTP field-name tokens",
      '"X-MOT-Deck-Voice-Model"' in APP
      and '"X-MOT Deck-' not in APP)
check("a completed render is stored in the cache",
      "cache_put(ckey, wav)" in APP)
check("the render is TIMED and the breakdown logged",
      "[voice] render " in APP and "stats.get('load_secs')" in APP
      and "stats.get('spawned')" in APP)
check("/api/voice/tts self-heals a missing ref_text",
      "needs_ref_text(entry)" in APP and "_heal_ref_text(" in APP)
check("pin-time and render-time transcription share ONE implementation",
      APP.count("async def _transcribe_clip(") == 1
      and APP.count("_transcribe_clip(path, audio)") == 2)
check("the self-heal PERSISTS the transcript", '_registry_update(entry.get("id"), '
      '{"ref_text"' in APP)
check("the library endpoint takes a ?folder= source",
      'def voice_library(folder: str = "")' in APP)
check("a folder listing is refused unless the folder is configured",
      "folder_allowed(folder, folders)" in APP)
check("the folder endpoints exist",
      "/api/voice/library/folders" in APP
      and "/api/voice/library/folders/add" in APP
      and "/api/voice/library/folders/remove" in APP)
check("removing a folder never deletes anything",
      "os.remove" not in APP.split("def voice_library_folder_remove")[1][:1200])
check("hidden models are filtered at the BRIDGE, not the panel",
      "_is_hidden(m)" in APP and "not _is_hidden(m)" in APP)
check("only read-only imports may be hidden",
      "HIDEABLE_SOURCES" in APP and "_hideable(entry)" in APP)
check("the hidden list is returned for the unhide affordance", '"hidden": hidden' in APP)
check("a model that is IN USE cannot be hidden out from under itself",
      "is {role} right now" in APP)
check("hidden models are also filtered out of the composer's audio popover",
      "audio if not _is_hidden(m)" in APP)

SEED = (ROOT / "scripts" / "seed_registry.py").read_text()
check("a rescan carries EVERY user decision forward, not just the voice",
      "USER_KEYS" in SEED and '"ref_audio"' in SEED and '"hidden"' in SEED)

PANEL = (ROOT / "bridge" / "panel" / "index.html").read_text()
check("the panel can add a clip FILE", "function pickClipFile(" in PANEL
      and "accept = 'audio/*'" in PANEL)
check("an added file is re-encoded to wav like a recording",
      "wavFromBuffer(buf)" in PANEL.split("function pickClipFile(")[1][:1400])
check("the panel renders the folder sources", "function renderClipFolders(" in PANEL)
check("a folder clip is pinned by ABSOLUTE PATH",
      "raw.startsWith('/') ? { id: id, path: raw }" in PANEL)
check("removing a folder says out loud that files are untouched",
      "the files themselves are NEVER touched" in PANEL)
check("the folder picker is a TYPED PATH (WKWebView folder pickers are unreliable)",
      "'/path/to/folder'" in PANEL)
check("the panel offers an explicit clear on a pinned voice/clip",
      "function clearPinLink(" in PANEL and "Un-pin " in PANEL)
check("the panel can hide and unhide imported models",
      "function isHideable(" in PANEL and "/api/models/hide" in PANEL
      and "hidden — " in PANEL)
check("audio rows carry a voices/cloning sub-badge",
      "function audioVoiceBadge(" in PANEL and "audioVoiceBadge(a)" in PANEL)

print()
print(f"{'FAIL' if FAILS else 'OK'} — {len(FAILS)} failure(s)")
if FAILS:
    for f_ in FAILS:
        print("  -", f_)
sys.exit(1 if FAILS else 0)
