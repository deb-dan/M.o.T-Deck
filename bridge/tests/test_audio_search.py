"""Unit tests for the Audio tab's HF SEARCH half (T2) — bridge side.

Everything under test is PURE: licence classification, the config-probe decision
table, size accounting and the search-query table. No network is touched (the
sandbox has none, and a test that needed HuggingFace to be up would be a liability
on the Mac too) — the wiring is asserted by reading app.py's source instead.

Run: python3 bridge/tests/test_audio_search.py   (from repo root)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

# ⚠️ THE APP LAYER IS NO LONGER ONE FILE (router/core split, 2026-08-28).
# bridge/app.py is a FACADE over bridge/core/*.py + bridge/routers/*.py, so the
# source-text assertions below read bridge/appsrc.py's assembled view of the whole
# app layer instead of one file. Read bridge/appsrc.py's header for why the
# assertions are source-text in the first place and why order is part of it.
from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402

from bridge import app as A                                    # noqa: E402

fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# ── licences ──────────────────────────────────────────────────────────────────
check("apache-2.0 is offerable",
      A.audio_license_badge("apache-2.0") == {"license": "apache-2.0",
                                              "badge": "ok", "reason": ""})
check("mit is offerable", A.audio_license_badge("MIT")["badge"] == "ok")
for nc in ("cc-by-nc-4.0", "cc-by-nc-sa-4.0", "cc-by-nc-nd-4.0", "CC-BY-NC"):
    check(f"{nc} is NOT offerable", A.audio_license_badge(nc)["badge"] == "nc")
# OpenRAIL is use-restricted, NOT non-commercial (Fable fix 2026-08-13): amber
# badge with the true reason, Get stays enabled.
for rl in ("creativeml-openrail-m", "openrail", "bigscience-openrail-m"):
    b = A.audio_license_badge(rl)
    check(f"{rl} is amber + offerable",
          b["badge"] == "unknown" and b["reason"] == "use-restricted licence")
check("the nc reason is the one the button shows",
      A.audio_license_badge("cc-by-nc-sa-4.0")["reason"] == A.LICENSE_NC_REASON)
for unk in ("", None, "other", "unknown", 3, [], {"a": 1}):
    check(f"{unk!r} → licence unknown", A.audio_license_badge(unk)["badge"] == "unknown")
check("an unknown licence is STILL offerable (Debi's machine, her call)",
      A.audio_license_badge("")["badge"] == "unknown")
check("a permissive-but-unlisted licence is ok, not unknown",
      A.audio_license_badge("bsd-3-clause")["badge"] == "ok")

# ── known-mistagged repos (LICENSE_OVERRIDES) ─────────────────────────────────
# k2-fsa's README licenses the WEIGHTS cc-by-nc; every mlx-community/OmniVoice*
# repo tags itself apache-2.0 (the CODE licence), which defeated the gate.
APACHE_TAGGED = {"cardData": {"license": "apache-2.0"}}
for repo in ("mlx-community/OmniVoice-bfloat16", "mlx-community/OmniVoice",
             "mlx-community/OmniVoice-4bit", "theoracleguy/OmniVoice-bf16",
             "k2-fsa/OmniVoice", "someone/omnivoice-experiment",
             "SHOUTY/OMNIVOICE-8BIT"):
    row = A.audio_license_row(repo, APACHE_TAGGED)
    check(f"{repo} is overridden to amber",  row["badge"] == "unknown")
    check(f"{repo} carries the exact override reason",
          row["reason"] == "weights CC-BY-NC per upstream README; code Apache-2.0")
    check(f"{repo} names the weights term in its pill",
          row["license"] == "cc-by-nc (weights)")
    check(f"{repo} cites the upstream README",
          row["source_url"] == "https://huggingface.co/k2-fsa/OmniVoice")
check("the override reason is the module constant, not a copy",
      A.LICENSE_OVERRIDES["omnivoice"]["reason"] == A.OMNIVOICE_LICENSE_REASON)
# The whole point: Get stays ENABLED (badge is not "nc"), so the probe handler's
# can_get override cannot fire for an OmniVoice row.
check("an overridden row is NOT the nc badge that disables Get",
      A.audio_license_row("mlx-community/OmniVoice-bfloat16",
                          APACHE_TAGGED)["badge"] != "nc")

# MiniMax-Music3 — the SECOND confirmed mistag of the same class (2026-08-20 research).
# Abiray/MiniMax-Music3-GGUF claims apache-2.0 over a custom Community License.
for repo in ("Abiray/MiniMax-Music3-GGUF", "MiniMaxAI/MiniMax-Music3",
             "PocketAiHub/MiniMax-Music3-MLX", "Comfy-Org/MiniMax-Music-3-repack",
             "SHOUTY/MINIMAX-MUSIC3-Q4", "someone/minimax-music3-gguf"):
    row = A.audio_license_row(repo, APACHE_TAGGED)
    check(f"{repo} is overridden to amber", row["badge"] == "unknown")
    check(f"{repo} carries the exact override reason",
          row["reason"] == A.MINIMAX_MUSIC3_LICENSE_REASON)
    check(f"{repo} names the weights term in its pill",
          row["license"] == "minimax-community (weights)")
    check(f"{repo} cites the upstream LICENSE file",
          row["source_url"]
          == "https://huggingface.co/MiniMaxAI/MiniMax-Music3/blob/main/LICENSE")
check("the Music3 reason is the module constant, not a copy",
      A.LICENSE_OVERRIDES["minimax-music3"]["reason"] == A.MINIMAX_MUSIC3_LICENSE_REASON)
check("the Music3 reason names the licence, not a guess at cc-by-nc",
      "Community License" in A.MINIMAX_MUSIC3_LICENSE_REASON
      and "cc-by-nc" not in A.MINIMAX_MUSIC3_LICENSE_REASON.lower())
check("an overridden Music3 row is NOT the nc badge that disables Get",
      A.audio_license_row("Abiray/MiniMax-Music3-GGUF", APACHE_TAGGED)["badge"] != "nc")
check("both upstream spellings resolve to the SAME record",
      A.license_override("Comfy-Org/MiniMax-Music-3")
      == A.license_override("MiniMaxAI/MiniMax-Music3") != {})
check("a music repo of another family is untouched",
      A.license_override("ACE-Step/Ace-Step1.5") == {}
      and A.license_override("Serveurperso/ACE-Step-1.5-GGUF") == {})

check("a repo with no override falls through to the tag",
      A.audio_license_row("mlx-community/Kokoro-82M-bf16", APACHE_TAGGED)
      == A.audio_license_badge("apache-2.0"))
check("an unlisted repo with an nc TAG is still disabled",
      A.audio_license_row("SparkAudio/Spark-TTS-0.5B",
                          {"cardData": {"license": "cc-by-nc-sa-4.0"}})["badge"] == "nc")
check("an unlisted untagged repo is still amber-but-offerable",
      A.audio_license_row("kitten/whatever", {})["badge"] == "unknown")
check("license_override is a substring match, case-insensitively",
      A.license_override("MLX-COMMUNITY/OmniVoice")
      == A.license_override("x/omnivoice-y") != {})
check("license_override returns {} for anything unlisted",
      all(A.license_override(x) == {} for x in
          ("mlx-community/Kokoro-82M-bf16", "", "   ", None, 3, [], {"a": 1})))
check("license_override hands back a COPY (the table cannot be mutated)",
      A.license_override("x/omnivoice") is not A.LICENSE_OVERRIDES["omnivoice"])
check("every override record carries the four keys the UI reads",
      all(set(rec) == {"license", "badge", "reason", "source_url"}
          for rec in A.LICENSE_OVERRIDES.values()))
check("no override silently DISABLES a Get (that needs a deliberate nc verdict)",
      all(rec["badge"] != "nc" for rec in A.LICENSE_OVERRIDES.values()))

check("hf_license reads cardData.license",
      A.hf_license({"cardData": {"license": "Apache-2.0"}}) == "apache-2.0")
check("hf_license reads a LIST cardData.license",
      A.hf_license({"cardData": {"license": ["mit", "apache-2.0"]}}) == "mit")
check("hf_license falls back to the license:* tag",
      A.hf_license({"tags": ["mlx", "license:cc-by-nc-sa-4.0"]}) == "cc-by-nc-sa-4.0")
check("hf_license prefers cardData over the tag",
      A.hf_license({"cardData": {"license": "mit"},
                    "tags": ["license:apache-2.0"]}) == "mit")
check("hf_license survives junk",
      all(A.hf_license(x) == "" for x in (None, [], "x", {}, {"tags": [1, None]})))

# ── whisper shape: replicated constants must NOT drift from seed_registry ──────
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import seed_registry as SR                                     # noqa: E402

check("required-key tuple is identical to seed_registry's",
      A.AUDIO_WHISPER_REQUIRED == SR.MLX_WHISPER_REQUIRED)
check("veto-key tuple is identical to seed_registry's",
      A.AUDIO_WHISPER_VETO == SR.MLX_WHISPER_VETO)

MLX_WHISPER_CFG = {"n_mels": 80, "n_audio_ctx": 1500, "n_audio_state": 512,
                   "n_audio_head": 8, "n_audio_layer": 6, "n_vocab": 51865,
                   "n_text_ctx": 448, "n_text_state": 512}
HF_WHISPER_CFG = {"_name_or_path": "openai/whisper-medium",
                  "architectures": ["WhisperForConditionalGeneration"],
                  "transformers_version": "4.45.0", "num_mel_bins": 80,
                  "d_model": 1024, "encoder_layers": 24, "decoder_layers": 24,
                  "is_encoder_decoder": True}
check("is_mlx_whisper_cfg accepts a real ModelDimensions config",
      A.is_mlx_whisper_cfg(MLX_WHISPER_CFG))
check("is_mlx_whisper_cfg REJECTS the transformers whisper-medium config",
      not A.is_mlx_whisper_cfg(HF_WHISPER_CFG))
check("is_mlx_whisper_cfg agrees with seed_registry on both configs",
      A.is_mlx_whisper_cfg(MLX_WHISPER_CFG) == SR.is_mlx_whisper_config(MLX_WHISPER_CFG)
      and A.is_mlx_whisper_cfg(HF_WHISPER_CFG) == SR.is_mlx_whisper_config(HF_WHISPER_CFG))
check("is_mlx_whisper_cfg survives junk",
      not any(A.is_mlx_whisper_cfg(x) for x in (None, [], "cfg", 3, {})))

# ── the gguf pair ─────────────────────────────────────────────────────────────
QWEN_GGUF = [("Qwen3-TTS-12Hz-1.7B-Base-Q4_K_M.gguf", 960_000_000),
             ("Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf", 1_800_000_000),
             ("mmproj-Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf", 420_000_000),
             ("mmproj-Qwen3-TTS-12Hz-1.7B-Base-F16.gguf", 800_000_000),
             ("README.md", 4000)]
back, proj = A.gguf_tts_pair(QWEN_GGUF)
check("gguf pair picks the Q4_K_M backbone (same as the curated starter)",
      back == "Qwen3-TTS-12Hz-1.7B-Base-Q4_K_M.gguf")
check("gguf pair picks the Q8_0 projector (same as the curated starter)",
      proj == "mmproj-Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf")
check("no mmproj ⇒ no pair (llama-tts needs both halves)",
      A.gguf_tts_pair([("model-Q4_K_M.gguf", 10)]) == (None, None))
check("no backbone ⇒ no pair",
      A.gguf_tts_pair([("mmproj-x.gguf", 10)]) == (None, None))
check("without a Q4_K_M the SMALLEST backbone wins",
      A.gguf_tts_pair([("a-Q8_0.gguf", 99), ("b-Q5.gguf", 5),
                       ("mmproj-a.gguf", 1)])[0] == "b-Q5.gguf")
check("gguf pair survives junk", A.gguf_tts_pair(None) == (None, None)
      and A.gguf_tts_pair([(None, 1), (3, 4)]) == (None, None))

# ── the probe decision table ──────────────────────────────────────────────────
MLX_FILES = [("config.json", 900), ("model.safetensors", 1_800_000_000),
             ("tokenizer.json", 5000), ("merges.txt", 400), ("README.md", 3000)]
NPZ_FILES = [("config.json", 900), ("weights.npz", 137_000_000)]


def V(repo="x/y", cfg=None, files=MLX_FILES, tags=(), pipeline=""):
    return A.audio_probe_verdict(repo, cfg, files, tags, pipeline)


check("a config declaring tts_model_type is tts-mlx",
      V(cfg={"tts_model_type": "custom_voice"})["format"] == "tts-mlx")
check("a config with talker_config is tts-mlx",
      V(cfg={"talker_config": {"spk_id": {}}})["format"] == "tts-mlx")
check("the mlx-audio tag alone is enough for tts-mlx",
      V(tags=["mlx-audio", "text-to-speech"], cfg={"model_type": "kokoro"}
        )["format"] == "tts-mlx")
check("an mlx-whisper ModelDimensions config is stt-mlx",
      V(repo="mlx-community/whisper-base-mlx", cfg=MLX_WHISPER_CFG,
        files=NPZ_FILES, pipeline="automatic-speech-recognition")["format"] == "stt-mlx")
med = V(repo="openai/whisper-medium", cfg=HF_WHISPER_CFG,
        pipeline="automatic-speech-recognition", tags=["transformers", "whisper"])
check("THE WHISPER-MEDIUM INCIDENT: a transformers checkpoint is vetoed",
      med["format"] == "transformers")
check("…and its Get is disabled with a reason",
      med["can_get"] is False and "mlx_whisper" in med["block_reason"])
check("the transformers veto does NOT fire on the TTS lane "
      "(an mlx-audio conversion may carry `architectures`)",
      V(cfg={"architectures": ["Qwen3TTS"], "tts_model_type": "base"},
        pipeline="text-to-speech")["format"] == "tts-mlx")
check("a text-to-speech pipeline + MLX shape is tts-mlx, warned as unverified",
      V(cfg={"model_type": "whatever"}, pipeline="text-to-speech")["format"] == "tts-mlx"
      and "unverified" in V(cfg={"model_type": "w"}, pipeline="text-to-speech")["warn"])
g = V(repo="ggml-org/Qwen3-TTS-12Hz-1.7B-Base-GGUF", files=QWEN_GGUF, tags=["gguf"])
check("a gguf backbone+mmproj pair with a TTS token is tts-gguf",
      g["format"] == "tts-gguf" and g["file"].endswith("Q4_K_M.gguf")
      and g["mmproj"].startswith("mmproj-") and g["can_get"] is True)
check("a VISION chat model (gguf+mmproj, no tts token) is NOT tts-gguf",
      V(repo="unsloth/gemma-4-31B-GGUF",
        files=[("gemma-Q4_K_M.gguf", 9), ("mmproj-gemma.gguf", 1)],
        tags=["gguf"])["format"] == "unknown")
check("a bare mlx repo with no signals at all is unknown, Get off",
      V(cfg={"model_type": "llama"})["can_get"] is False)
check("a TTS-shaped verdict with NO weights degrades to unknown "
      "(whole-repo mode would 400)",
      V(cfg={"tts_model_type": "base"}, files=[("README.md", 3)])["format"] == "unknown")
check("…and says why", "safetensors" in
      V(cfg={"tts_model_type": "base"}, files=[("README.md", 3)])["block_reason"])
check("weights.npz counts as MLX weights (whisper-base-mlx ships npz)",
      V(repo="mlx-community/whisper-base-mlx", cfg=MLX_WHISPER_CFG,
        files=NPZ_FILES)["format"] == "stt-mlx")
check("audio_probe_verdict never raises on junk",
      all(isinstance(A.audio_probe_verdict(*a), dict) for a in
          [(None, None, None, None, None), (3, [], "x", 7, {}),
           ("r", {"a": 1}, [(None, None)], [1, None], "")]))
check("every verdict carries the four keys the panel reads",
      all(set(V(cfg=c).keys()) >= {"format", "warn", "file", "mmproj",
                                   "can_get", "block_reason"}
          for c in (None, MLX_WHISPER_CFG, {"tts_model_type": "base"})))

# ── size accounting ───────────────────────────────────────────────────────────
check("mlx size = the denylisted repo sum (README excluded)",
      A.audio_probe_size("tts-mlx", MLX_FILES) == 900 + 1_800_000_000 + 5000 + 400)
check("gguf size = backbone + the CHOSEN projector only, not every quant",
      A.audio_probe_size("tts-gguf", QWEN_GGUF, back, proj)
      == 960_000_000 + 420_000_000)
check("an unclassified repo reports no size (never guess)",
      A.audio_probe_size("unknown", MLX_FILES) == 0)

# ── voices ────────────────────────────────────────────────────────────────────
check("voices come from talker_config.spk_id",
      A.audio_probe_voices({"talker_config": {"spk_id": {"serena": 0, "ryan": 1}}},
                           MLX_FILES) == ["serena", "ryan"])
check("Kokoro's voices/*.pt files are the second mechanism",
      A.audio_probe_voices({}, [("voices/af_heart.pt", 5), ("voices/am_adam.pt", 5),
                                ("config.json", 1)]) == ["af_heart", "am_adam"])
check("an empty spk_id declares NO voices (the Base checkpoint's fingerprint)",
      A.audio_probe_voices({"talker_config": {"spk_id": {}}}, MLX_FILES) == [])
check("audio_probe_voices survives junk",
      A.audio_probe_voices(None, None) == [] and A.audio_probe_voices(3, [(1, 2)]) == [])

# ── the query table (the three web-verified facts) ────────────────────────────
src = _APP_SOURCE
check("`library=` is NEVER sent to the HF API (it is silently ignored)",
      '"library"' not in src and "'library'" not in src)
check("the TTS lane is the UNION of mlx-audio and mlx (mlx-audio misses Kokoro)",
      [d["filter"] for d in A.AUDIO_SEARCH_QUERIES["tts"]] == ["mlx-audio", "mlx"]
      and all(d["pipeline_tag"] == "text-to-speech"
              for d in A.AUDIO_SEARCH_QUERIES["tts"]))
check("the STT lane filters mlx + the ASR pipeline tag",
      A.AUDIO_SEARCH_QUERIES["stt"] ==
      ({"filter": "mlx", "pipeline_tag": "automatic-speech-recognition"},))
check("the GGUF lane filters gguf with no pipeline tag",
      A.AUDIO_SEARCH_QUERIES["tts-gguf"] == ({"filter": "gguf"},)
      and A.AUDIO_GGUF_DEFAULT_TERM == "tts")
check("the kinds the endpoint accepts are exactly the query table's keys",
      set(A.AUDIO_SEARCH_KINDS) == set(A.AUDIO_SEARCH_QUERIES))

# ── wiring (read from source; no server is started) ───────────────────────────
for frag in ('@app.get("/api/models/hf/audio")',
             '@app.get("/api/models/hf/audio/probe")',
             "async def hf_audio_search", "async def hf_audio_probe",
             # BOTH licence call sites now go through the ONE override-aware seam
             # (this assertion changed honestly: the seam moved, the badge logic
             # underneath it is byte-identical).
             "lic = audio_license_row(repo, m)",
             "lic = audio_license_row(repo, meta)",
             "/raw/main/config.json"):
    check(f"app.py wires {frag}", frag in src)
check("audio_license_badge is only reached THROUGH audio_license_row",
      src.count("audio_license_badge(hf_license(") == 1)
check("an nc licence overrides can_get in the probe handler",
      'if lic["badge"] == "nc":' in src and 'v["can_get"] = False' in src)
check("the probe sorts nothing it did not measure — size comes from audio_probe_size",
      '"size_bytes": audio_probe_size(' in src)

print(("\nFAILED: " + ", ".join(fails)) if fails
      else "\nall audio-search checks passed")
sys.exit(1 if fails else 0)
