"""Unit tests for the SECOND STT engine — mlx-audio / Parakeet (`stt-mlx-audio`).

Sibling of test_voice_stt.py. Both engines stay selectable: a whisper entry and a
parakeet entry are two ordinary registry rows and the default-STT picker chooses.
Nothing here may weaken the whisper path, and that is asserted directly.

What is pinned:

  * stt_argv's new branch — the exact flag surface of `mlx_audio.stt.generate`, read
    from parse_args in OUR OWN pinned venv (mlx-audio 0.4.7). `--output-path` is a
    PREFIX not a directory (save_as_json writes f"{output_path}.json"), which is the
    single fact that lets stt_read_output stay unchanged.
  * that stt_read_output and stt_text_from_payload really are unchanged for the
    Parakeet payload shape ({"text": ..., "sentences": [...]}).
  * stt_bin_for — which console script each format resolves to.
  * is_parakeet_config / is_parakeet_cfg — the NeMo fingerprint, in BOTH copies, and
    that they agree with each other and never fire on a whisper config.
  * audio_format_probed — the two STT verdicts, strict and lenient.
  * the bridge/panel wiring facts.

Run: python3 bridge/tests/test_parakeet_stt.py   (from repo root)
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# ⚠️ THE APP LAYER IS NO LONGER ONE FILE (router/core split, 2026-08-28).
# bridge/app.py is a FACADE over bridge/core/*.py + bridge/routers/*.py, so the
# source-text assertions below read bridge/appsrc.py's assembled view of the whole
# app layer instead of one file. Read bridge/appsrc.py's header for why the
# assertions are source-text in the first place and why order is part of it.
from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402
from bridge import voice                                        # noqa: E402
import seed_registry as SR                                      # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


def raises(fn):
    try:
        fn()
    except Exception:                                           # noqa: BLE001
        return True
    return False


PK = "/opt/motdeck/data/mlx-venv/bin/mlx_audio.stt.generate"
PY = "/opt/motdeck/data/mlx-venv/bin/python"
E_PK = {"id": "parakeet-tdt-0.6b-v3", "kind": "audio", "format": "stt-mlx-audio",
        "path": "/opt/motdeck/data/models/parakeet-tdt-0.6b-v3"}
E_WH = {"id": "whisper-base-mlx", "kind": "audio", "format": "stt-mlx",
        "path": "/opt/motdeck/data/models/whisper-base-mlx"}

# ── formats ──────────────────────────────────────────────────────────────────
print("\nformats")
check("stt-mlx-audio is a recognised STT format",
      "stt-mlx-audio" in voice.STT_FORMATS)
check("whisper is STILL a recognised STT format (both engines stay selectable)",
      "stt-mlx" in voice.STT_FORMATS)
check("both reach AUDIO_FORMATS, so /api/dl/start accepts the hint",
      set(voice.STT_FORMATS) <= set(voice.AUDIO_FORMATS))
check("a parakeet entry is an STT entry", voice.is_stt_entry(E_PK))
check("a parakeet entry is NOT a TTS entry (it must never reach ▶ speak)",
      not voice.is_tts_entry(E_PK))
check("a parakeet entry is partitioned out of the chat lists",
      voice.is_audio_entry(E_PK))
check("the Audio tab calls it an mlx engine — a plain '-mlx' suffix test would have "
      "labelled it llama.cpp", voice.audio_entry_view(E_PK)["engine"] == "mlx")
check("…and gives it the stt role", voice.audio_entry_view(E_PK)["role"] == "stt")

# ── stt_bin_for ──────────────────────────────────────────────────────────────
print("\nstt_bin_for")
check("stt-mlx-audio resolves mlx-audio's own console script",
      voice.stt_bin_for("stt-mlx-audio", "/r").endswith(
          "/data/mlx-venv/bin/mlx_audio.stt.generate"))
check("stt-mlx still resolves mlx_whisper",
      voice.stt_bin_for("stt-mlx", "/r").endswith("/data/mlx-venv/bin/mlx_whisper"))
check("an unknown/junk format falls back to whisper rather than raising",
      all(voice.stt_bin_for(v, "/r").endswith("mlx_whisper")
          for v in ("", None, "tts-mlx", 7)))
check("both live in the SAME venv — no new venv, no new pin",
      os.path.dirname(voice.stt_bin_for("stt-mlx-audio", "/r"))
      == os.path.dirname(voice.stt_bin_for("stt-mlx", "/r")))

# ── stt_argv: the console-script form ────────────────────────────────────────
print("\nstt_argv (console script)")
argv = voice.stt_argv(E_PK, "/tmp/x/conv.wav", "/tmp/x", PK, PY, use_script=True)
check("the console script is argv[0]", argv[0] == PK)
check("--model carries the registry path",
      argv[argv.index("--model") + 1] == E_PK["path"])
check("--audio carries the audio file (it is a FLAG here, not positional as in the "
      "whisper CLI)", argv[argv.index("--audio") + 1] == "/tmp/x/conv.wav")
check("--output-path is a PREFIX <dir>/<stem>, not a directory — save_as_json writes "
      "f'{output_path}.json'",
      argv[argv.index("--output-path") + 1] == "/tmp/x/conv")
check("--format json (the default is txt, which stt_read_output cannot parse)",
      argv[argv.index("--format") + 1] == "json")
check("the stem is derived from the AUDIO file, so it matches what stt_transcribe "
      "then passes to stt_read_output",
      voice.stt_argv(E_PK, "/tmp/x/in.wav", "/tmp/x", PK, PY)[
          voice.stt_argv(E_PK, "/tmp/x/in.wav", "/tmp/x", PK, PY)
          .index("--output-path") + 1] == "/tmp/x/in")
check("no --verbose is passed (this CLI's verbose is a store_true flag, not a value)",
      "--verbose" not in argv)
check("every element is a string (subprocess would raise on anything else)",
      all(isinstance(a, str) for a in argv))

# ── stt_argv: the module fallback form ───────────────────────────────────────
print("\nstt_argv (module fallback)")
fb = voice.stt_argv(E_PK, "/tmp/x/conv.wav", "/tmp/x", PK, PY, use_script=False)
check("the fallback runs the venv python", fb[0] == PY)
check("…with -m mlx_audio.stt.generate (the package DOES expose a runnable module)",
      fb[1] == "-m" and fb[2] == "mlx_audio.stt.generate")
check("the flags are byte-identical to the console-script form, so ONE reader "
      "handles both", fb[3:] == argv[1:])

# ── the whisper path is untouched ────────────────────────────────────────────
print("\nthe whisper path is untouched")
w = voice.stt_argv(E_WH, "/tmp/x/conv.wav", "/tmp/x", "/bin/mlx_whisper", PY)
check("whisper still takes the audio POSITIONALLY", w[1] == "/tmp/x/conv.wav")
check("whisper still writes with -f json -o <dir>",
      w[w.index("-f") + 1] == "json" and w[w.index("-o") + 1] == "/tmp/x")
check("whisper still silences its per-segment stdout",
      w[w.index("--verbose") + 1] == "False")
check("whisper never grows an --audio flag", "--audio" not in w)
check("whisper never grows an --output-path flag", "--output-path" not in w)
check("a non-STT format is still refused outright",
      raises(lambda: voice.stt_argv({"format": "tts-mlx", "path": "/m"},
                                    "/a", "/o", PK)))
check("an unknown format is refused too, naming both engines",
      raises(lambda: voice.stt_argv({"format": "stt-onnx", "path": "/m"},
                                    "/a", "/o", PK)))

# ── the readers need no change ───────────────────────────────────────────────
print("\nstt_read_output / stt_text_from_payload against the PARAKEET payload")
PARAKEET_JSON = {"text": "  what is the weather in tallinn  ",
                 "sentences": [{"text": "what is the weather in tallinn",
                                "start": 0.0, "end": 2.1, "duration": 2.1,
                                "tokens": []}]}
check("the top-level `text` key is read first — the same key whisper uses",
      voice.stt_text_from_payload(PARAKEET_JSON) == "what is the weather in tallinn")
with tempfile.TemporaryDirectory() as d:
    with open(os.path.join(d, "conv.json"), "w") as f:
        json.dump(PARAKEET_JSON, f)
    check("stt_read_output finds <stem>.json exactly where --output-path put it",
          voice.stt_read_output(d, "conv") == "what is the weather in tallinn")
    with open(os.path.join(d, "empty.json"), "w") as f:
        json.dump({"text": "", "sentences": []}, f)
    check("an EMPTY transcript still reads as '' — the failure signal is carried "
          "over verbatim to the second engine (its exit code is UNVERIFIED)",
          voice.stt_read_output(d, "empty") == "")
check("a `sentences` payload with no top-level text does not crash the reader",
      voice.stt_text_from_payload({"sentences": [{"text": "hi"}]}) == "")

# ── is_parakeet_config: the NeMo fingerprint ─────────────────────────────────
print("\nthe NeMo/Parakeet config fingerprint")
# Trimmed from the REAL mlx-community/parakeet-tdt-0.6b-v3 config.json (244 KB).
REAL_PARAKEET = {
    "sample_rate": 16000, "rnnt_reduction": "mean_volume",
    "model_defaults": {"enc_hidden": 1024, "pred_hidden": 640,
                       "tdt_durations": [0, 1, 2, 3, 4], "num_tdt_durations": 5},
    "tokenizer": {"type": "bpe", "model_path": "nemo:tokenizer.model"},
    "preprocessor": {
        "_target_": "nemo.collections.asr.modules.AudioToMelSpectrogramPreprocessor",
        "sample_rate": 16000, "features": 128},
    "encoder": {"_target_": "nemo.collections.asr.modules.ConformerEncoder",
                "feat_in": 128, "n_layers": 24, "d_model": 1024},
    "decoder": {"_target_": "nemo.collections.asr.modules.RNNTDecoder",
                "vocab_size": 8192},
    "joint": {"_target_": "nemo.collections.asr.modules.RNNTJoint"},
}
MLX_WHISPER_CFG = {"n_mels": 80, "n_audio_ctx": 1500, "n_audio_state": 512,
                   "n_audio_head": 8, "n_audio_layer": 6, "n_vocab": 51865,
                   "n_text_ctx": 448, "n_text_state": 512}
HF_WHISPER_CFG = {"_name_or_path": "openai/whisper-medium",
                  "architectures": ["WhisperForConditionalGeneration"],
                  "transformers_version": "4.45.0", "num_mel_bins": 80,
                  "d_model": 1024, "encoder_layers": 24, "decoder_layers": 24,
                  "is_encoder_decoder": True}
# nvidia/parakeet-tdt-0.6b-v3 is a TRANSFORMERS repo with a parakeet NAME. It must
# NOT be classified as ours — this is the whisper-medium incident, second edition.
HF_PARAKEET_CFG = {"architectures": ["ParakeetForCTC"], "model_type": "parakeet_tdt",
                   "transformers_version": "4.56.0", "d_model": 1024}
check("the REAL parakeet config is recognised", SR.is_parakeet_config(REAL_PARAKEET))
check("a whisper ModelDimensions config is NOT parakeet",
      not SR.is_parakeet_config(MLX_WHISPER_CFG))
check("a transformers whisper config is NOT parakeet",
      not SR.is_parakeet_config(HF_WHISPER_CFG))
check("a TRANSFORMERS repo that is merely CALLED parakeet is NOT ours",
      not SR.is_parakeet_config(HF_PARAKEET_CFG))
check("two nemo `_target_` blocks are enough…", SR.is_parakeet_config(
    {"preprocessor": {"_target_": "nemo.x"}, "encoder": {"_target_": "nemo.y"}}))
check("…and ONE is not (a single hydra key proves nothing)", not SR.is_parakeet_config(
    {"preprocessor": {"_target_": "nemo.x"}, "encoder": {"_target_": "torch.y"}}))
check("an explicitly declared model_type:parakeet counts on its own",
      SR.is_parakeet_config({"model_type": "parakeet"}))
check("…but not when the config is also waving transformers keys",
      not SR.is_parakeet_config({"model_type": "parakeet",
                                 "architectures": ["Whatever"]}))
check("the whisper transformers VETO is NOT applied to the SHAPE rule — a NeMo config "
      "carrying d_model must still be recognised",
      SR.is_parakeet_config(dict(REAL_PARAKEET, d_model=1024,
                                 architectures=["EncDecRNNTBPEModel"])))
check("junk input is total", not any(
    SR.is_parakeet_config(v) for v in (None, "x", 7, [], {},
                                       {"encoder": "notadict"},
                                       {"encoder": {"_target_": 5},
                                        "decoder": {"_target_": None}})))
check("is_mlx_whisper_config still REJECTS the real parakeet config (the two probes "
      "are disjoint — no config can be both)",
      not SR.is_mlx_whisper_config(REAL_PARAKEET))

# ── the bridge's replicated copy ─────────────────────────────────────────────
print("\nthe replicated copy in bridge/app.py")
sys.path.insert(0, str(ROOT / "bridge"))
import app as A                                                 # noqa: E402
check("shape-key tuple is identical to seed_registry's",
      A.AUDIO_PARAKEET_SHAPE_KEYS == SR.PARAKEET_SHAPE_KEYS)
check("target prefix is identical",
      A.AUDIO_PARAKEET_TARGET_PREFIX == SR.PARAKEET_TARGET_PREFIX)
check("minimum block count is identical",
      A.AUDIO_PARAKEET_MIN_NEMO_BLOCKS == SR.PARAKEET_MIN_NEMO_BLOCKS)
check("declared model_type set is identical",
      A.AUDIO_PARAKEET_MODEL_TYPES == SR.PARAKEET_MODEL_TYPES)
for label, cfg in (("real parakeet", REAL_PARAKEET), ("mlx whisper", MLX_WHISPER_CFG),
                   ("hf whisper", HF_WHISPER_CFG), ("hf parakeet", HF_PARAKEET_CFG),
                   ("junk", None)):
    check(f"the two implementations agree on the {label} config",
          A.is_parakeet_cfg(cfg) == SR.is_parakeet_config(cfg))

# ── audio_probe_verdict (the HF-search lane) ─────────────────────────────────
print("\naudio_probe_verdict")
PK_FILES = [("config.json", 244093), ("model.safetensors", 2508288736),
            ("tokenizer.model", 360916), ("vocab.txt", 46772), ("README.md", 1081)]
v = A.audio_probe_verdict("mlx-community/parakeet-tdt-0.6b-v3", REAL_PARAKEET,
                          PK_FILES, ["mlx", "automatic-speech-recognition"],
                          "automatic-speech-recognition")
check("a real mlx parakeet repo is Get-able as stt-mlx-audio",
      v["format"] == "stt-mlx-audio" and v["can_get"] is True)
v2 = A.audio_probe_verdict("nvidia/parakeet-tdt-0.6b-v3", HF_PARAKEET_CFG,
                           [("config.json", 900), ("model.safetensors", 2)],
                           ["transformers", "nemo"], "automatic-speech-recognition")
check("the TRANSFORMERS parakeet repo is refused with the honest reason",
      v2["format"] == "transformers" and v2["can_get"] is False
      and "not an MLX conversion" in v2["block_reason"])
v3 = A.audio_probe_verdict("mlx-community/whisper-base-mlx", MLX_WHISPER_CFG,
                           [("config.json", 900), ("weights.safetensors", 2)],
                           ["mlx"], "automatic-speech-recognition")
check("a whisper MLX repo still lands on stt-mlx, not the new lane",
      v3["format"] == "stt-mlx")
v4 = A.audio_probe_verdict("mlx-community/parakeet-tdt-0.6b-v3", REAL_PARAKEET,
                           [("config.json", 244093)], ["mlx"],
                           "automatic-speech-recognition")
check("a parakeet verdict with NO weights in the tree degrades to unknown rather "
      "than offering a Get that would 400",
      v4["format"] == "unknown" and v4["can_get"] is False)
check("the Get size counts the whole mlx file set (weights + config + BOTH tokenizer "
      "files — this repo ships no tokenizer.json) and EXCLUDES the README",
      A.audio_probe_size("stt-mlx-audio", PK_FILES)
      == 2508288736 + 244093 + 360916 + 46772)

# ── audio_format_probed (the local / cache scan) ─────────────────────────────
print("\naudio_format_probed")
with tempfile.TemporaryDirectory() as d:
    def mk(name, cfg):
        p = os.path.join(d, name)
        os.makedirs(p, exist_ok=True)
        open(os.path.join(p, "model.safetensors"), "w").write("x")
        if cfg is not None:
            with open(os.path.join(p, "config.json"), "w") as f:
                json.dump(cfg, f)
        else:
            open(os.path.join(p, "config.json"), "w").write("{not json")
        return p, os.listdir(p)

    p, fl = mk("parakeet-tdt-0.6b-v3", REAL_PARAKEET)
    check("a real parakeet folder classifies as stt-mlx-audio (strict)",
          SR.audio_format_probed("parakeet-tdt-0.6b-v3", fl, p, True) == "stt-mlx-audio")
    p, fl = mk("whisper-base-mlx", MLX_WHISPER_CFG)
    check("a whisper folder still classifies as stt-mlx (strict)",
          SR.audio_format_probed("whisper-base-mlx", fl, p, True) == "stt-mlx")
    p, fl = mk("whisper-medium", HF_WHISPER_CFG)
    check("the transformers whisper-medium is STILL dropped (this fix must not "
          "loosen that)", SR.audio_format_probed("whisper-medium", fl, p, True) is None)
    p, fl = mk("parakeet-tdt-hf", HF_PARAKEET_CFG)
    check("a transformers parakeet folder is dropped too",
          SR.audio_format_probed("parakeet-tdt-hf", fl, p, True) is None)
    p, fl = mk("parakeet-mine", None)
    check("an UNREADABLE config in the HF cache fails closed",
          SR.audio_format_probed("parakeet-mine", fl, p, True) is None)
    check("…but in OUR OWN tree it falls back to the name, and the name says parakeet",
          SR.audio_format_probed("parakeet-mine", fl, p, False) == "stt-mlx-audio")
    p, fl = mk("whisper-mine", None)
    check("…and a whisper-named folder falls back to whisper, not to the new engine",
          SR.audio_format_probed("whisper-mine", fl, p, False) == "stt-mlx")
    p, fl = mk("some-chat-model", REAL_PARAKEET)
    check("a folder with NO family token is not audio at all, whatever its config "
          "says (the token list is still the safety margin)",
          SR.audio_format_probed("some-chat-model", fl, p, True) is None)
check("'parakeet' joined the STT token list", "parakeet" in SR.AUDIO_STT_TOKENS)
check("'whisper' is still in it", "whisper" in SR.AUDIO_STT_TOKENS)
check("no GENERIC word crept into the token lists — that is what would start eating "
      "chat models",
      not ({"audio", "voice", "speech", "model", "asr"}
           & set(SR.AUDIO_STT_TOKENS) | {"audio", "voice", "speech"}
           & set(SR.AUDIO_TTS_TOKENS)))
check("a downloaded parakeet registers as an audio entry with the dir as its path",
      voice.audio_download_entry(
          {"id": "parakeet-tdt-0.6b-v3", "path": "/m/parakeet", "size_bytes": 1},
          "stt-mlx-audio") == {"id": "parakeet-tdt-0.6b-v3",
                               "name": "parakeet-tdt-0.6b-v3", "kind": "audio",
                               "format": "stt-mlx-audio", "path": "/m/parakeet",
                               "size_bytes": 1, "source": "download", "repo": None,
                               "mmproj": None})

# ── wiring, read out of the sources ──────────────────────────────────────────
print("\nwiring")
VSRC = (ROOT / "bridge" / "voice.py").read_text()
ASRC = _APP_SOURCE
PSRC = (ROOT / "bridge" / "panel" / "index.html").read_text()
check("stt_transcribe dispatches the binary BY FORMAT, not by hardcoding whisper",
      "mlx_bin or stt_bin_for(entry_format(entry), root)" in VSRC)
check("the exit code is still deliberately not gated on (the invariant is carried "
      "defensively because mlx-audio's exit behaviour is UNVERIFIED)",
      "p.returncode deliberately NOT checked" in VSRC
      and "UNVERIFIED for stt-mlx-audio" in VSRC)
check("both STT engines share the ONE global render lock",
      VSRC.count("_RENDER_LOCK.acquire(blocking=False)") >= 2)
check("the panel offers Parakeet as a curated starter with the right format hint",
      "mlx-community/parakeet-tdt-0.6b-v3" in PSRC
      and "fmt: 'stt-mlx-audio'" in PSRC)
check("the starter card carries the CC BY 4.0 attribution the licence requires",
      "CC BY 4.0 — © NVIDIA" in PSRC)
check("the panel names the real reason to switch (silence, not speed)",
      "hallucinating" in PSRC or "emits NOTHING on silence" in PSRC)
check("every MLX-shaped verdict list in app.py names BOTH stt formats (a list that "
      "forgot one would make a real repo unbuyable or un-sized)",
      ASRC.count('("tts-mlx", "stt-mlx", "stt-mlx-audio")') >= 2)
check("the STT endpoint dispatches on the entry, not on a hardcoded engine",
      "def stt_transcribe(" in VSRC and "stt_bin_for(" in VSRC)

print("")
print(("FAIL" if FAILS else "OK") + f" — {len(FAILS)} failure(s)")
for f in FAILS:
    print("  - " + f)
sys.exit(1 if FAILS else 0)
