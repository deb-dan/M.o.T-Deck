# Music generation & text-to-video on Apple Silicon — research report

**Date:** 2026-08-20 · **Author:** Opus 5 research agent (Fable brief) · **Status:** findings only, no code written
**Constraints assumed:** Apple Silicon M-series, 64GB unified, `memory.budget_gb: 48`, no CUDA, no Docker,
everything pinned + vendored/venv'd, components = separate process + port + `/health` **or** native lane
(one-shot subprocess / persistent worker + registry entry + panel controls), weights license checked
**separately** from code license (the OmniVoice lesson).

---

## ▣ RECOMMENDATIONS BOX

### Music generation

| Verdict | Candidate | One-line reason |
|---|---|---|
| 🟢 **GREEN-LIGHT** (native lane, first pick) | **MiniMax-Music3 via `PocketAiHub/MiniMax-Music3-MLX`** | Debi's favourite demo is *actually feasible*: pure-MLX, 11.9GB int8, Apple-Silicon-only **by design**, standalone `generate.py` CLI = the exact voice-lane shape, ships SHA-256 manifest + unit tests + honest license tag. |
| 🟢 **GREEN-LIGHT** (component-with-tab, second pick) | **ACE-Step 1.5** (`ace-step/ACE-Step-1.5`) | The only candidate that already *is* the VoiceStudio pattern: **MIT code AND MIT weights** (verified), FastAPI REST on `:8001` with a real `GET /health`, uv install, official macOS launch scripts. |
| 🟡 **GATE on one benchmark** | **`acestep.cpp`** (GGML/Metal, GGUF ~7.7GB, port 8085, `/health`, MIT) | Architecturally the *most* house-doctrine-aligned thing in this whole report — it is to ACE-Step what llama.cpp is to our runner. Blocked only by: **zero published Metal numbers anywhere**. |
| 🟡 **GATE** (different job) | **Stable Audio 3 MLX** (`Stability-AI/stable-audio-3` → `optimized/mlx`) | Best engineering in the field (first-party pure MLX, 1.6–5.2GB peak RAM, 8–29× realtime, ships a repro benchmark script) but **generates no vocals** and carries the Stability Community License $1M revenue cap. SFX/instrumental lane, not a Suno replacement. |
| 🟠 **HOLD** | **HeartMuLa** via `Acelogic/heartlib-mlx` | Apache-2.0 end to end and the boldest quality claim, but **0.30× realtime** (sub-realtime) and bus-factor-1 port. |
| 🔴 **REFUSE** | **MusicGen / audiocraft** | **Weights are CC-BY-NC 4.0** — fails the exact same gate that correctly blocked Spark-TTS and Voxtral-TTS. Also frozen (pins Python 3.9 / torch 2.1) and by Meta's own admission "not able to generate realistic vocals". Debi's instinct to reject it is right, and for a stronger reason than staleness. |
| 🔴 **REFUSE** | **YuE** | Apache-2.0 (ideal license) but **≥80GB GPU memory for full songs** and CUDA+FlashAttention-2 only. Not runnable here at any quality. |
| ⚪ **NOT A MODEL** | **Qwen-Music** (arXiv 2607.11699) | Paper only, July 2026. No weights, no license, no repo found. Watch item. |

### Text-to-video

| Verdict | Candidate | One-line reason |
|---|---|---|
| 🔴 **REFUSE the category as a component, for now** | — | Best realistic case on this hardware is **~2.5 min for 5s at 576×1024**, and that case peaks at **34GB — 71% of the entire 48GB ledger**. Every cheaper configuration produces, in the words of the only Mac writeup that publishes its failures, "colored blobs". |
| 🔴 **REFUSE outright — legal** | **HunyuanVideo** (all versions) | **The license does not apply in the European Union.** Debi is in Estonia. Stated four times in four sections; bars use, reproduction *and the Output itself*. Not a commercial-use nuance — there is no grant at all. |
| 🔴 **REFUSE outright — legal** | **Open-Sora 2.0** | Tagged `apache-2.0` while **physically shipping `flux1-dev.safetensors` (23.8GB) under the FLUX.1-dev NON-COMMERCIAL license**, and initialized from it. Mislabelled weights + architecturally impossible on MPS (top-level `flash_attn` import). |
| 🔴 **REFUSE** | **Mochi-1**, **MiniMax H3**, **Step-Video-T2V** | Mochi: abandoned 19 months, crashes at *import* on Mac (`torch.cuda.get_device_properties(0)` at module level), wants an H100. H3: 33B + **EU users must apply to MiniMax**. Step-Video: 300B. |
| 🟡 **GATE — the one spike worth doing** | **Kandinsky-5.0-T2V-Lite (2B, MIT)** | Best license *and* smallest size in the entire field, SDPA support landed (which is what MPS needs). **Zero verified Apple Silicon runs by anyone.** If it works, it is the only honest video answer. If Fable wants video at all, fund this 2-hour spike and nothing else. |
| 🟡 **GATE — if video is wanted despite the above** | **LTX-2.3 int8 (~21GB) via `Blaizzy/mlx-video`** | `mlx-video` is **by Prince Canuma — the same author and same CLI shape as the `mlx-vlm` + `mlx-audio` we already pin into `data/mlx-venv`**. MIT runtime. Cost: the LTX-2.x Community License ($10M cap, derivative copyleft, watermark-tamper revocation clause). |
| 🔴 **REFUSE** | **Wan 2.2** on this hardware | Apache-2.0 (best license in video) but measured at **1h22m for 2 seconds of 480p** on an M1 Max 64GB. And **Wan 2.5/2.6/2.7 are API-only closed weights** despite widespread SEO claims otherwise. |

### Cross-cutting recommendations

1. **Music yes, video no.** Music generation on this hardware is a solved-enough problem with two viable shapes and an honest license story. Video is not, and the RAM ledger is the reason as much as the speed is.
2. **Any music lane must gate on the ledger like the voice worker does.** Music3-MLX wants 32GB minimum / 48GB recommended — i.e. **one music render can claim the entire `budget_gb: 48`**. It should refuse to spawn while a chat model is resident, exactly as `spawn_guard` already does for the TTS worker, and probably prompt "eject the chat model first".
3. **Badge the license, don't hide the model.** Music3's Community License is workable for personal use but requires *"prominently display MiniMax-Music3"* on any commercial surface and a separate agreement above $20M revenue. That is the OpenRAIL/amber precedent, not the CC-BY-NC/red precedent.
4. **There is no local music-generation MCP server in existence.** Every music MCP found is a cloud-API wrapper. Given ACE-Step already exposes HTTP, ours would be a thin and genuinely novel wrapper — but it is net-new work, not adoption.

---

## Corrections and conflicts resolved during this research

These matter more than any single datapoint, because each one is a claim a future reader would otherwise have inherited wrong.

1. **🚨 `Abiray/MiniMax-Music3-GGUF` declares `License: apache-2.0` and its README says "Inherits the Apache-2.0 License from the original release". This is FALSE.** The upstream `MiniMaxAI/MiniMax-Music3` LICENSE file is a **custom "MiniMax-Music3 COMMUNITY LICENSE"** with attribution duties, a $20M revenue trigger, a safeguards obligation, and a 19-clause Acceptable Use Policy. **This is precisely the OmniVoice mistag repeating on a new model family, and it is the second confirmed instance** — evidence that our `LICENSE_OVERRIDES` table is not a one-off patch but a structural necessity. Note the contrast: the MLX port (`PocketAiHub`) tags itself **`license: minimax-music3-community`** and links the real LICENSE. One repackager was honest, one was not; **the tag cannot be trusted, only the file can.**
2. **ACE-Step 1.5 is MIT, not Apache-2.0.** My two sub-agents disagreed. Resolved from primary sources: [`LICENSE`](https://raw.githubusercontent.com/ace-step/ACE-Step-1.5/main/LICENSE) is verbatim MIT ("Copyright (c) 2026 ACEStep"), and the [HF API](https://huggingface.co/api/models/ACE-Step/Ace-Step1.5) returns `"license:mit"` in tags and `cardData.license: "mit"`. The Apache-2.0 reading came from **ACE-Step v1**, which genuinely *is* Apache-2.0 — two different repos, two different licenses. `usedStorage` also confirms **10,079,024,720 bytes = 10.08GB**.
3. **🚨 LOCALLY VERIFIED: our pinned `mlx-audio 0.4.8` has NO music-generation model.** A promising hypothesis was that ACE-Step had landed inside mlx-audio, making music generation nearly free for our stack. I checked the actual shipped venv rather than the README:
   ```
   data/mlx-venv/lib/python*/site-packages/mlx_audio/tts/models/
   → arktts bailingmm bark chatterbox … kokoro … qwen3_tts … voxtral_tts zonos2
   ```
   **No `ace_step`, no music model of any kind, at our pin.** (`mlx-audio` issue #536 requesting music-gen support was closed with no linked PR.) The `mlx-community/ACE-Step1.5-MLX` model card *does* document an `mlx_audio.tts` API for it — so support may exist upstream of 0.4.8 — but **it is not in what we ship**, and adopting it would be a pin bump with an unverified surface, not a free win. Treat "mlx-audio does music" as refuted until re-checked after a bump.
4. **Wan 2.5 / 2.6 / 2.7 are NOT open weights.** Multiple SEO blogs claim "Wan 2.5, Apache 2.0, on HuggingFace". Direct check of `huggingface.co/Wan-AI` shows 27 models and **nothing above 2.2**. The open line stopped at 2.2.
5. **`freeaimusictools.com` states ACE-Step 1.5 has "Apache 2.0 weights"** — wrong (MIT), and the site is affiliate/SEO content. Flagged because it ranks well and its performance numbers are also uncorroborated.
6. **A widely-recirculated "M3 Max 128GB, 155s/it" figure is HunyuanVideo, not Mochi.** It gets misattributed. There is no credible Mochi-on-Mac timing anywhere; the one guide that published numbers retracted them as "never reproducible on Apple Silicon".

---

## TOPIC 1 — Music generation

### 1a. MiniMax-Music3 — the headline finding

**The weights are genuinely open, and the "requires CUDA" limitation is already broken by the community.**

The upstream card ([MiniMaxAI/MiniMax-Music3](https://huggingface.co/MiniMaxAI/MiniMax-Music3)) states plainly under Limitations: *"Inference requires CUDA."* Taken at face value that ends the conversation. It does not, because of two independent routes:

- **[`PocketAiHub/MiniMax-Music3-MLX`](https://huggingface.co/PocketAiHub/MiniMax-Music3-MLX)** — "Experimental native Apple Silicon MLX inference… runs the complete autoregressive, flow-DiT, and DAV synthesis path locally on macOS **without CUDA or ComfyUI**."
- **ComfyUI** has first-class Music3 support ([docs](https://docs.comfy.org/tutorials/audio/minimax/minimax-music-3), [Comfy-Org/MiniMax-Music-3](https://huggingface.co/Comfy-Org/MiniMax-Music-3)) plus GGUF quants — but that route drags in ComfyUI, which is roadmap-gated here.

**Architecture** (from the upstream card): 8B Global LLM (initialized from Qwen3-8B) for long-range structure + 0.6B Local LLM for frame-level acoustics + Flow Matching (2.4B) + Flow-VAE decoder (123M) → **32kHz 16-bit stereo**, songs **up to 5 minutes**, conditioned on **lyrics with section tags** (`[Verse]`/`[Chorus]`/`[Bridge]`…) *and* a separate structured music description. Note the HF "2B params" badge is misleading — it indexes one component, not the stack.

**The MLX port, assessed:**

| Property | Value |
|---|---|
| Size | **11.9GB** on disk (INT8 tensorwise + ConvRot for the AR model and DiT; FP32 DAV decoder) |
| Requirements | Apple Silicon, macOS 14+, Python 3.11–3.13, **32GB unified minimum, 48GB+ recommended** |
| Speed | *"A 60-second song at 30 steps takes several minutes"* (vendor wording; no table) |
| Interface | **standalone `generate.py` CLI** — `--prompt`, `--lyrics-file`, `--seconds` (10–300), `--steps` (1–30), `--seed`, `--output` |
| License tag | **`minimax-music3-community`** — honest, links the real LICENSE |
| Provenance | weights are *unchanged* copies of a **pinned** Comfy-Org repack (commit `6444666e`); `model_manifest.json` records sizes + SHA-256 |
| Verification | ships `tests/test_minimax_mlx_model.py`; publishes a signal-check table for its example render (duration 59.9888s, stereo correlation 0.7086, 0% collapsed blocks, 0 clipped samples) |

**Why this is the first pick.** It is a one-shot subprocess with a CLI, pinned weights with checksums, deterministic seeding, and a hard Apple-Silicon-only target — which is to say it is *already shaped like our voice lane* (`tts_argv` → subprocess → read output file → registry entry). It needs no port, no `/health`, no tab, and no new component lifecycle.

**Honest limits, stated plainly:**
- **Single-maintainer, "Experimental" in its own title, 5 likes, downloads not tracked.** Bus factor 1.
- **"Several minutes" is not a number.** No published table, and I found no independent Mac benchmark. This is the single biggest unknown in the recommendation.
- **32GB min / 48GB recommended vs our `budget_gb: 48`** — a render can consume the whole ledger. Batch size is 1.
- The port itself documents a real MLX bug it works around: *"Direct multi-million-sample MLX Conv1d execution produced incorrect channel collapse during testing"* → chunked overlap-cropped decoding, plus a runtime check that **rejects outputs exhibiting the diagnosed stereo-collapse signature**. Good engineering, but it tells you the Metal path has sharp edges.
- Output will **not** match ComfyUI sample-for-sample (different RNG backends).
- License duties are real: display "MiniMax-Music3" on commercial surfaces; separate agreement above $20M revenue; a safeguards-implementation clause (§4) if you expose generation to third parties.

**License, precisely** ([LICENSE](https://huggingface.co/MiniMaxAI/MiniMax-Music3/blob/main/LICENSE)): custom **MiniMax-Music3 Community License**. Broad MIT-like grant *plus* (2) AUP compliance, (3.1) attribution on commercial UIs, (3.2) written authorization above $20M revenue, (4) safeguards obligation for third-party-facing services. Derived from Qwen3-8B (Apache-2.0), Stable Audio's DiT (MIT), DAC's VAE (MIT). **Not OSI open source; comfortably fine for personal use; badge it amber.**

### 1b. ACE-Step — the component-shaped option

**ACE-Step v1 (3.5B) — skip.** Apache-2.0 code *and* weights (they match), 8.28GB, but superseded and frozen (last org update Feb 2026, no releases ever published, 137+ open issues, README roadmap still lists 1.5 as unshipped). Its flagship Mac issue is the tell: [#274](https://github.com/ace-step/ACE-Step/issues/274) — Mac mini M4 16GB, *"about 50 minutes or more… SWAP is more than 6 gigabytes"* — open, unassigned, unanswered since June 2025, against a README claiming 26s/min of audio on an M2 Max. That gap between vendor table and user reality is the most useful adversarial datapoint on the v1 line.

**ACE-Step 1.5 — the real candidate.**

| Property | Value |
|---|---|
| License | **MIT — code and weights both** (verified against LICENSE + HF API). Card claims commercially-clean training data and no per-track restriction on outputs. |
| Size | **10.08GB** (verified `usedStorage`): DiT turbo 4.79GB + 5Hz-LM-1.7B 3.71GB + Qwen3-Embedding-0.6B 1.19GB + VAE 337MB |
| XL variant | 4B DiT (**actually 4.99B params, ~19.95GB on disk** — the README's "~9GB bf16" is the in-memory figure, not the download) |
| Capabilities | text→music with vocals, **50+ languages**, 10–600s, reference-audio conditioning, cover, **repaint/edit**, **stem separation**, multi-track "Lego", extend/complete, Vocal2BGM, BPM/key control, audio understanding, LRC timestamps, LoRA/LoKr training. ⚠️ extract/lego/complete are **base-model-only** — not available on `sft` or `turbo`. |
| **Integration shape** | **FastAPI REST on `:8001`** (`uv run acestep-api`, binds `127.0.0.1`), **`GET /health` → `{"status":"ok",…}`**, plus `/v1/models`, `POST /v1/init` (hot-swap DiT/LM without restart), `GET /v1/stats`, optional `ACESTEP_API_KEY` bearer auth, `ACESTEP_CHECKPOINTS_DIR` for a shared model dir. Gradio UI on 7860. Also CLI, Python API, VST3. |
| Install | **uv-based** (`uv sync`, Python 3.11–3.12) — matches our existing component conventions |
| macOS support | **Official.** `start_gradio_ui_macos.sh` / `start_api_server_macos.sh`, a macOS portable zip, repo description literally says "supporting Mac". |
| Maintenance | **Alive** — 11–12k stars, XL shipped Apr 2026, last update ~May 2026. But strained: 40–49 open PRs, and Mac issues get auto-closed as `stale`. |

**The critical caveat on its "MLX support", because it is easy to misread:** `--backend mlx` is the **LM backend only** — it occupies the same slot as `vllm`/`pt` and accelerates the 5Hz language model. **The DiT and VAE still run on PyTorch MPS.** So all the MPS exposure remains. Concretely:

- **M2 MacBook Air 16GB** ([first-hand blog with error text](https://en.bioerrorlog.work/entry/ace-step-15-local-m2-macbook)): 5–10 min per track, after first hitting `RuntimeError: MPS backend out of memory (MPS allocated: 11.74 GiB… max allowed: 18.13 GiB)`. Fix required `export PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0` — **disabling PyTorch's MPS safety cap is a de-facto prerequisite.**
- **M4 Mac mini 32GB** ([issue #1081](https://github.com/ace-step/ACE-Step-1.5/issues/1081)): needs *both* `PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0` **and** `PYTORCH_ENABLE_MPS_FALLBACK=1` (the latter implying ops still fall back to CPU). Reports a real memory leak — with Autoscore on, models reload after every generation until the system crashes. **Closed as "not planned", labelled `stale`, never diagnosed.**
- Two other traps: the shipped `start_gradio_ui_macos.sh` **defaults to the 1.7B LM**, which is sized for a 24GB discrete card — pin the **0.6B** on ≤32GB. And the VRAM tier table is CUDA-centric (`MAX_CUDA_VRAM`), so tier auto-detection on 64GB unified is unverified. Also set `CHECK_UPDATE=false` — it has a startup update check, which collides with our pin-and-bump discipline.
- Open issue [#995](https://github.com/ace-step/ACE-Step-1.5/issues/995) requests MLX for the 4B DiT — i.e. **XL has no MLX path at all**.

**Ecosystem health signal worth noting:** ACE-Step 1.5 is the only model in this survey with **MLX *and* GGUF *and* ONNX** conversions (`mlx-community/ACE-Step1.5-MLX` 12.6GB + a 4-bit variant, `Serveurperso/ACE-Step-1.5-GGUF`, `shreyask/ACE-Step-v1.5-ONNX`), plus a `diffusers` pipeline and a ComfyUI node.

**Community UI — `fspecii/ace-step-ui`:** React+TS frontend (`:3000`) + Express/SQLite backend (`:3001`) that **calls ACE-Step's API at `:8001`** — it is a client and library/persistence layer, **not** an inference server. Adds Spotify-style library, playlists, waveform player, queue/progress, bundled AudioMass editor + Demucs stem extraction. 4,088 stars but **last push 2026-06-04 (~2.5 months stale)**, its requirements table says **"NVIDIA GPU 4GB+ VRAM"** with zero Apple Silicon guidance, and **GitHub's API reports `"license": null`** despite an MIT badge in the README. Verdict: it duplicates a UI we would rather build in our own editorial idiom, and it is not Mac-tuned.

**⚠️ `ace-step/ACE-Step-DAW` is AGPL-3.0** — do not pull it in without a deliberate decision (arm's-length is fine per house doctrine, but it is a different license from the rest of the org).

### 1c. `acestep.cpp` — the sleeper, and the closest thing to house doctrine

Real upstream: [`ServeurpersoCom/acestep.cpp`](https://github.com/ServeurpersoCom/acestep.cpp) (320★, 526 commits, MIT), **forked into the official org** as [`ace-step/acestep.cpp`](https://github.com/ace-step/acestep.cpp) — a de-facto blessing.

Why it is worth Fable's attention specifically: **it is to ACE-Step what llama.cpp is to our runner.** Portable C++17 + GGML, **zero Python at runtime**, *"macOS auto-enables Metal and Accelerate BLAS"*. That erases the entire class of problem documented above — no PyTorch, no MPS high-watermark incantations, no bfloat16-on-MPS breakage, no CPU fallbacks.

- **GGUF weights ~7.7GB total** ([`Serveurperso/ACE-Step-1.5-GGUF`](https://huggingface.co/Serveurperso/ACE-Step-1.5-GGUF)): LM-4B Q8_0 4.2GB + Qwen3-Embedding Q8_0 748MB + DiT turbo Q8_0 2.4GB + VAE BF16 322MB. **Less than the 10.08GB fp32 bundle, and far less than XL's 20GB.**
- **Server on port 8085**, `GET /health → {"status":"ok"}`, `GET /props`, `POST /lm|/synth|/understand|/vae`, plus `ace-lm`/`ace-synth` CLIs. **Models load on first request (zero GPU at startup) and hot-swap from the UI** — which maps onto our Eject/ledger semantics almost too neatly.
- Full task coverage (text2music, cover, repaint, lego, extract, complete), LoRA adapters, and a `docs/ARCHITECTURE.md`.

**The gate:** **I found no published Apple Silicon benchmark for it.** Metal support is a documented build claim, not a number. Single maintainer, no releases, no CI, Windows binaries hosted on a personal domain. So: architecturally the best answer, empirically unverified. **One afternoon of measurement decides it.**

### 1d. Stable Audio 3 MLX — best engineering, wrong job

[`Stability-AI/stable-audio-3`](https://github.com/Stability-AI/stable-audio-3) ships `optimized/mlx/` — **`sa3_mlx`: first-party, official, "no PyTorch, transformers, or stable-audio-tools at runtime."** Three DiTs (`sm-music` 50M, `sm-sfx`, `medium` 1.4B), four modes (text→audio, audio→audio, **inpainting**, CFG + negative prompt), uv-based install, weights ~8.4GB as `.npz` auto-downloaded and symlinked from the HF cache.

Published numbers on **M4 Pro / 48GB** — and unusually, `scripts/benchmark.py` ships to reproduce exactly this table, each cell in its own subprocess for clean peak-RAM measurement:

| model | audio secs | wall (s) | ×realtime | peak RAM |
|---|---|---|---|---|
| sm-music | 30 | 1.53 | 19.6× | 1.94 GB |
| sm-music | 120 | 4.12 | 29.1× | 2.38 GB |
| sm-music | 380 | 13.46 | 28.2× | 2.58 GB |
| medium | 30 | 5.06 | 5.9× | 3.89 GB |
| medium | 120 | 14.68 | 8.2× | 5.21 GB |
| medium | 380 | 47.78 | 8.0× | 5.05 GB |

Those RAM figures are extraordinary next to Music3's 32GB floor — **it would barely register on the ledger.** They also benchmark on an **M1 8GB** (~10× realtime for `sm-music` at 1.6GB peak), which is a credibility signal: vendors who cherry-pick don't publish their slowest chip. Visible engineering care: FP16 DiT validated at 50–57dB PSNR vs FP32, but *"the decoder must stay FP32 because SAME-S's differential attention catastrophically cancels in FP16"*; progressive model freeing (`--free-models`, default on) explains the low peaks.

**Two blockers for the stated use case:**
1. **No vocals.** The predecessor's card says it outright, and adds *"the model is better at generating sound effects and field recordings than music."* Debi wants songs.
2. **Stability AI Community License** — free below **$1M annual revenue**, commercial license required above. Stability markets it as "free for commercial use", which is true *only* under that cap. Also **gated download** on the Open Small predecessor (accept-agreement + contact info), which breaks unattended offline provisioning.

Interface is **CLI only** (`./sa3`) — so it would be a native lane, not a component. Best fit: a future SFX/instrumental/inpainting capability, complementary to a song model rather than competing with it.

### 1e. The rest of the music field

| Model | Code lic. | **Weights lic.** | Size | Vocals | Apple Silicon | Maintained |
|---|---|---|---|---|---|---|
| MusicGen | MIT | 🔴 **CC-BY-NC 4.0** | 0.3/1.5/3.3B | ❌ (by design) | partial MLX port only | ❌ frozen (Py3.9/torch2.1) |
| YuE | Apache-2.0 | ✅ Apache-2.0 | 7B | ✅ | ❌ CUDA+FA2, **≥80GB** | ⚠️ |
| DiffRhythm / 2 | Apache-2.0 | ✅ Apache-2.0 | — | ✅ | ⚠️ **zero Mac reports found** | ✅ active |
| Stable Audio Open Small | — | 🟠 Stability Community (<$1M) | 341M–0.5B | ❌ | ✅ Arm/KleidiAI | ✅ |
| Stable Audio 3 MLX | — | 🟠 Stability Community (<$1M) | 50M / 1.4B, ~8.4GB | ❌ | ⭐ first-party pure MLX | ✅ Stability |
| **ACE-Step 1.5** | ✅ MIT | ✅ **MIT** | 3.5B, ~10GB | ✅ | 🟡 official, but DiT on MPS | ✅ very active |
| **MiniMax-Music3 (MLX)** | — | 🟠 Community ($20M) | ~12GB int8 | ✅ | ⭐ pure MLX port | ⚠️ bus-factor 1 |
| HeartMuLa (3B) | Apache-2.0 | ✅ Apache-2.0 | 3B, ~11GB/1min | ✅ | 🟡 MLX, **0.30× realtime** | ⚠️ 1-person port |
| Qwen-Music | — | ❓ no weights found | — | ✅ | — | paper only |

**MusicGen, for the record.** Two license files exist in the repo: `LICENSE` (MIT) and **`LICENSE_weights` (CC-BY-NC 4.0)**, and the HF metadata tag is literally `cc-by-nc-4.0`. It is the textbook code-vs-weights split. Ports exist but are thin — `andrade0/musicgen-mlx` admits the T5 text encoder is **not** ported to MLX, melody conditioning is **not** wired up, and there is **no sliding window so >30s is unimplemented**. No `musicgen.cpp`, no CoreML conversion, no maintained fork. **Debi's rejection stands, upgraded from "stale" to "stale AND non-commercially licensed AND cannot sing".**

**DiffRhythm** deserves a footnote: Apache-2.0 for code and weights, and its headline is *"full-length songs within 2 seconds"* — **tested on a 4090**. That number will not transfer. I could not find a single credible Apple Silicon benchmark. Architecturally interesting (block flow matching), practically unmeasured.

**HeartMuLa via [`Acelogic/heartlib-mlx`](https://github.com/Acelogic/heartlib-mlx)** is the interesting third option: Apache-2.0 throughout, claims parity with Suno, ships a web UI on `:8080`, and publishes M2 Max 32GB MLX-vs-MPS numbers (total 27.87s → 13.41s, 2.1× faster). **But read the throughput row the headline hides: 4.29 frames/sec = 0.30× realtime.** Faster than MPS; still slower than realtime. KV cache ~1GB per minute of audio → ~11GB for 1min, ~15GB for 5min, so 64GB is comfortable. Hold pending a maintainer beyond one person.

### 1f. MCP servers for music generation

**None wrap a local model.** Every one found is a paid-cloud-API wrapper: [`pasie15/mcp-server-musicgpt`](https://github.com/pasie15/mcp-server-musicgpt) (MusicGPT API, 24 tools), [`falahgs/mcp-minimax-music-server`](https://github.com/falahgs/mcp-minimax-music-server) (MiniMax *API*, not local weights), Epidemic Sound (library search, not generation). The one genuinely different entry is [`williamzujkowski/live-coding-music-mcp`](https://github.com/williamzujkowski/live-coding-music-mcp), which drives Strudel.cc for algorithmic live coding — no weights, no cloud inference. The HF Spaces named `ACE-Step-MCP` are hosted third-party and unaudited. **Conclusion: a local music MCP would be ours to write; ACE-Step's or acestep.cpp's HTTP surface makes it thin.**

---

## TOPIC 2 — Text-to-video

### The blunt verdict

**No open text-to-video model is practically usable on a 64GB M-series Mac today for anything beyond a preview.** Two independent reasons, and either alone is disqualifying under house constraints:

1. **Speed/quality.** The best Mac number found anywhere is **152.5s for 5 seconds at 576×1024** (LTX-2.3 MLX, M4 Max 128GB, video-only — a single unreplicated model-card claim). Every configuration cheap enough to be routine produces garbage: on an M1 Max 64GB, LTX-2 GGUF Q4 at 512×288/33 frames took **6m54s** and yielded *"colored blobs bouncing up and down. The robot subject is nowhere."* At 768×512 it took **13m42s** for ~1.3 seconds and was *"almost a still image"*. Wan2.2-A14B at 832×480/33 frames took **1h22m45s for 2 seconds** ([lilting.ch](https://lilting.ch/en/articles/ltx2-wan22-mac-local-video-gen) — weighted highest because it controls variables and publishes its failures).
2. **The RAM ledger.** The good case peaks at **34.2GB — 71% of `budget_gb: 48`** for one 5-second clip. CogVideoX-5B on an M4 Pro 64GB used enough that **64GB is described as the floor**; HunyuanVideo v1 on an M3 Max used **~100GB**. A video lane cannot coexist with a resident chat model.

**The most damning single fact:** Lightricks' own [LTX-Desktop](https://github.com/Lightricks/LTX-Desktop) platform table lists Windows/Linux + CUDA ≥16GB as "Local" and **macOS Apple Silicon as "API-only — LTX API key required."** The vendor ships no local generation on macOS in their own app.

### The MPS failure modes (why ComfyUI is the *worse* path on Mac)

Named, reproducible, and mostly unowned:

- **`RuntimeError: Undefined type Float8_e4m3fn`** — Metal has no FP8, and **the official ComfyUI LTX-2 and Wan 2.2 templates specify fp8 checkpoints**. The default workflow is dead on arrival. Reproduced on an unmodified stock template ([ComfyUI #9255](https://github.com/Comfy-Org/ComfyUI/issues/9255)).
- **NaN on LTX's official 2-stage sampler** while plain KSampler works — i.e. the pipeline the distilled model is *tuned for* is the one that fails.
- **`Output channels > 65536 not supported at the MPS device`** in VAE decode ([ComfyUI-LTXVideo #386](https://github.com/Lightricks/ComfyUI-LTXVideo/issues/386), M1 Ultra 128GB).
- **MPS SDPA blowing up on long latent sequences** — `RuntimeError: Invalid buffer size: 10973.48 GB` for CogVideoX1.5 ([diffusers #9972](https://github.com/huggingface/diffusers/issues/9972), **open ~21 months, labelled stale**). Same root cause as CogVideoX's hard 30-frame ceiling on Mac.
- `torch.compile` unavailable on MPS; IC-LoRAs CUDA-only; a 64GB Mac exposes only ~48GB to the GPU unless you `sudo sysctl iogpu.wired_limit_mb=57344`.
- **Mac support is unowned.** [ComfyUI-LTXVideo #473](https://github.com/Lightricks/ComfyUI-LTXVideo/issues/473) (M3 Max 48GB): *"The hardware is capable — the software stack isn't."* Closed as duplicate, no assignee. [Wan2.1 #208 "Apple Silicon Support"](https://github.com/Wan-Video/Wan2.1/issues/208): closed, no maintainer reply. [HunyuanVideo-1.5 #18 "Is MacOS supported?"](https://github.com/Tencent-Hunyuan/HunyuanVideo-1.5/issues/18): open since Nov 2025, zero replies.

### MLX is the better path, and it is not empty

Contrary to expectation, **mlx-community hosts 22+ video model conversions** — `mlx-community/ltx-2.5-mlx` (created 2026-08-12), `LTX-2-distilled-bf16`, `Bernini-v2-bf16/-int4`, `LongCat-Video-*`, `Phantom-Wan-1.3B` — and Apple's own [mlx-examples](https://github.com/ml-explore/mlx-examples) has a **"Video Models"** section with a `video/wan2.1` directory.

Two MIT runtimes:
- **[`Blaizzy/mlx-video`](https://github.com/Blaizzy/mlx-video)** (264★) — **same author as `mlx-vlm` and `mlx-audio`, which we already pin**, same CLI shape (`python -m mlx_video.ltx_2.generate --prompt …`), MLX ≥0.22 (we ship 0.32.0). Supports LTX-2/2.3 and Wan2.1/2.2 incl. the Wan2.2-Lightning 4-step LoRA. ⚠️ **Pace has stalled: ~+2 commits in three months** (135→137). Not abandoned; not fast-moving.
- **[`dgrauet/ltx-2-mlx`](https://github.com/dgrauet/ltx-2-mlx)** — deeper LTX feature set, ships `docs/PIPELINE_MATURITY.md` with Stable/Beta/Experimental flags, and notable memory engineering for exactly this machine class: `--low-ram` streams transformer blocks from disk, `--tile-frames`/`--tile-spatial` caps O(N²) attention activations. One telling detail: `LTX2_GEMMA_EVAL_EVERY` / `LTX2_DIT_EVAL_EVERY` env knobs exist **specifically to keep each Metal command buffer under the macOS ~10s GPU watchdog** — that watchdog is a real crash source.

⚠️ **Watch the encoder, not the "B" count.** `Bernini-R-1.3B-int4` is 12.7GB of which **11.4GB is an unquantized umt5-xxl text encoder**. "1.3B" does not mean small on disk. And measured MLX reality (M2 Max 32GB, Wan2.1-1.3B 4-bit): 256×256/9fr = 70s *("does not look like a cat")*, 512×512/9fr = 229s *("looks like a cat")*, 768×768/9fr = 584s. **9 frames ≈ 0.5 seconds.** That author grades LLM and image as "Practical" and **video as "Experimental"**: *"It works. But it is not comfortable."*

### Per-model video table

| Model | **Weights license** | Size | Apple Silicon reality | Maintained |
|---|---|---|---|---|
| **LTX-2.5 / 2.3** | 🟠 LTX-2.x Community: free <**$10M** rev (entity-aggregated); **derivative copyleft**; **watermark-tamper = revocation**; no competing-model training; NY law/ICC arbitration | bf16 ~38GB; GGUF Q4_K_M 15.1GB; **MLX int8 ~21GB / int4 ~12GB** | **best case: 152.5s / 5s @576×1024, 34.2GB peak (M4 Max 128GB, MLX, unreplicated)**. **Zero reports for 2.5; no MLX port of 2.5.** | ✅ very healthy |
| **Wan 2.2** | ✅ **genuine unmodified Apache-2.0** (best in field) — ⚠️ but 2.2 HF weight repos ship **no LICENSE file**; claim rests on card metadata + GitHub | A14B MoE (27B/14B active); GGUF working set ~24GB | **1h22m45s for 2s @832×480 (M1 Max 64GB)**; extrapolated **>3h for 5s**. `Wan2.1-MAC` fork's own demo uses **8 frames**. | ✅ 2.2 line extended; **2.5+ closed** |
| **HunyuanVideo** | 🔴 **NO EU GRANT** (see below) | 13B / 8.3B | 1.5 **crashes at init on MPS**; v1 ~60min for ~3s @848×480, **~100GB RAM** | ⚠️ Mac unowned |
| **Mochi-1** | ✅ Apache-2.0 (⚠️ no LICENSE file in weights repo) | 10.03B, bf16 20GB | **crashes at import** (`torch.cuda.get_device_properties(0)` module-level, unguarded); zero `mps` refs | 🔴 abandoned since 2025-01-08 |
| **CogVideoX-2b** | ✅ **real Apache-2.0** | 1.694B / **3.39GB** | FP16-native (**MPS-safe** — the 5B models are BF16, which the authors' own code notes MPS lacks) | 🟡 dormant ~11 months |
| **CogVideoX-5b** | 🔴 custom "CogVideoX License": commercial use **requires registration**, capped 1M visits/mo, **revocable**, PRC law | 5B | **verified**: M4 Pro 64GB, 512×384 — 25fr/3s = **12min**; 49fr = **40min @50% failure**; **>30 frames = white-screen corruption**; needed 2 source patches | 🟡 dormant |
| **Open-Sora 2.0** | 🔴 tagged apache-2.0 but **ships FLUX.1-dev (non-commercial) 23.8GB and is initialized from it**; also bundles Tencent's VAE | — | impossible: top-level `flash_attn` + `liger_kernel` imports (no macOS wheels), torch==2.4.0 pinned, zero `mps` refs | 🔴 dead behind 29k stars (**560 downloads/mo**) |
| **Kandinsky-5.0-T2V-Lite** | ✅ **MIT** | **2B**, 12GB VRAM, 16-step distilled variant | ⚠️ **completely untested by anyone.** SDPA support added (what MPS needs). "runs comfortably on M-series 32GB+" claims trace only to SEO sites with no methodology. | ✅ |
| MiniMax H3 | 🔴 Community License; **US/UK/EU/KR users must apply** | 33.1B, ~42.5GB | too big | ✅ |

### 🔴 HunyuanVideo — the hard legal stop

You asked me to verify the geographic restriction. It is worse than a commercial-use caveat, and it is stated **four times in four sections** of [the raw LICENSE](https://huggingface.co/tencent/HunyuanVideo/raw/main/LICENSE). Line 3, in caps, before the definitions:

> `THIS LICENSE AGREEMENT DOES NOT APPLY IN THE EUROPEAN UNION, UNITED KINGDOM AND SOUTH KOREA AND IS EXPRESSLY LIMITED TO THE TERRITORY, AS DEFINED BELOW.`

§1.l defines "Territory" as worldwide **excluding** the EU, UK and South Korea. §5.c: *"You must not use, reproduce, modify, distribute, or display the Tencent Hunyuan Works, **Output or results** of the Tencent Hunyuan Works outside the Territory. Any such use outside the Territory is unlicensed and unauthorized."* The Acceptable Use Policy's **item 1** is *"Outside the Territory"*. Identical in v1, I2V and 1.5.

**Estonia is an EU member state.** Note the scope: it bars personal/hobby use too, and **extends to the Output** — a video generated here is unlicensed output. Governing law is Hong Kong SAR with exclusive HK jurisdiction; there is no EU forum.

⚠️ **Adversarial note:** the 1.5 card carries `extra_gated_eu_disallowed: true` but also `gated: false`, and per HF's docs the flag only takes effect on already-gated repos — **so the download will probably still work from Estonia. Do not read that as permission.** Unlike most license questions there is no interpretive room here. (Not legal advice.)

### Runtime shape, for completeness

**ComfyUI does expose a proper managed-component surface** (aiohttp on `:8188`): `GET /system_stats` (python version, devices, vram — a real health probe), `POST /prompt` → `{prompt_id}`, `GET /history/{id}`, `POST /interrupt`, **`POST /free`** (unload models to free memory), `WS /ws` for `progress`/`executing`/`executed`. That maps cleanly onto our card semantics — `/system_stats` = health, `/free` = Eject, `/interrupt` = Stop, `/ws` = progress. **If ComfyUI ever comes off the roadmap gate, that is the shape.** But on MPS it is the *worse* runtime for video, per the failure modes above.

`mlx-video` and `ltx-2-mlx` ship **no HTTP server** — CLI + Python API only. Given our existing one-shot-subprocess voice architecture, that is arguably a feature. Draw Things does video natively on Mac with claimed Metal speedups but is **closed-source, App Store, GUI-only**. DiffusionKit is image-only.

---

## Uncertainty flags (ranked)

1. **🚩 No independent Apple Silicon benchmark exists for either music recommendation.** Music3-MLX publishes only *"several minutes"* for a 60s song, with no table and no third-party reproduction. `acestep.cpp`'s Metal support is a build claim with **zero published numbers anywhere**. Every music timing in this report is either a CUDA number or a first-party/author claim. Stable Audio 3's is the only one I'd bet on, purely because a reproduction script ships with it. **Fable should treat "how long does a song take" as unknown and fund one afternoon of measurement before committing to a shape.**
2. **🚩 Bus factor 1 on the single best-fitting artifact.** `PocketAiHub/MiniMax-Music3-MLX` is one person, self-labelled "Experimental", 5 likes, downloads untracked, and it documents working around a genuine MLX Conv1d correctness bug (channel collapse) with a chunked path plus a runtime rejection check. If it goes stale we inherit an unmaintained MLX reimplementation of a 3-component pipeline. The mitigation is that the *weights* are a pinned upstream repack with checksums — the port is the fragile half, not the model.
3. **🚩 License-tag trust is now demonstrably broken, twice.** The Music3 GGUF repo asserting Apache-2.0 over a custom Community License is the OmniVoice pattern recurring on a new family, and my own sub-agents disagreed on ACE-Step 1.5 (MIT vs Apache) until I read the file. Every license figure in this report that I did **not** fetch as a raw file should be re-verified before it becomes load-bearing — and I did not read the LTX-2.x, Hunyuan, CogVideoX or Wan licenses end to end, only their operative clauses.

**Other honest limits:** I ran nothing — no Apple hardware in this environment, so no timing here is mine. Reddit was unreachable to the crawlers (400s on r/LocalLLaMA, r/comfyui, r/StableDiffusion), so Mac evidence is blogs, GitHub issues and HF discussions rather than the subreddit threads requested. Exact last-commit dates for several ACE-Step repos were unobtainable (GitHub API rate-limited); those dates come from cached HTML. Kandinsky-5 on Apple Silicon is entirely untested by anyone I could find. GGUF/quantized *quality* is unmeasured everywhere — a 1.49GB Q4 from a 5GB F16 DiT is a community upload nobody has A/B'd. And the Open-Sora FLUX-derivative conclusion is my reading of verified facts, not an adjudicated one.

---

## Sources

**Music3:** [MiniMaxAI/MiniMax-Music3](https://huggingface.co/MiniMaxAI/MiniMax-Music3) · [its LICENSE](https://huggingface.co/MiniMaxAI/MiniMax-Music3/blob/main/LICENSE) · [PocketAiHub/MiniMax-Music3-MLX](https://huggingface.co/PocketAiHub/MiniMax-Music3-MLX) · [Abiray/MiniMax-Music3-GGUF (mislabelled license)](https://huggingface.co/Abiray/MiniMax-Music3-GGUF) · [Comfy-Org/MiniMax-Music-3](https://huggingface.co/Comfy-Org/MiniMax-Music-3) · [ComfyUI tutorial](https://docs.comfy.org/tutorials/audio/minimax/minimax-music-3) · [demo](https://minimax-ai.github.io/music3-demo/)

**ACE-Step:** [ACE-Step-1.5](https://github.com/ace-step/ACE-Step-1.5) · [LICENSE (MIT)](https://raw.githubusercontent.com/ace-step/ACE-Step-1.5/main/LICENSE) · [HF API](https://huggingface.co/api/models/ACE-Step/Ace-Step1.5) · [INSTALL.md](https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/INSTALL.md) · [API.md](https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/API.md) · [issue #1081](https://github.com/ace-step/ACE-Step-1.5/issues/1081) · [issue #995](https://github.com/ace-step/ACE-Step-1.5/issues/995) · [v1](https://github.com/ace-step/ACE-Step) · [v1 issue #274](https://github.com/ace-step/ACE-Step/issues/274) · [ServeurpersoCom/acestep.cpp](https://github.com/ServeurpersoCom/acestep.cpp) · [Serveurperso/ACE-Step-1.5-GGUF](https://huggingface.co/Serveurperso/ACE-Step-1.5-GGUF) · [mlx-community/ACE-Step1.5-MLX](https://huggingface.co/mlx-community/ACE-Step1.5-MLX) · [fspecii/ace-step-ui](https://github.com/fspecii/ace-step-ui) · [clockworksquirrel/ace-step-apple-silicon](https://github.com/clockworksquirrel/ace-step-apple-silicon) · [BioErrorLog M2 first-hand](https://en.bioerrorlog.work/entry/ace-step-15-local-m2-macbook)

**Other music:** [audiocraft](https://github.com/facebookresearch/audiocraft) · [LICENSE_weights (CC-BY-NC)](https://github.com/facebookresearch/audiocraft/blob/main/LICENSE_weights) · [andrade0/musicgen-mlx](https://github.com/andrade0/musicgen-mlx) · [YuE](https://github.com/multimodal-art-projection/YuE) · [DiffRhythm](https://github.com/ASLP-lab/DiffRhythm) · [DiffRhythm2](https://github.com/ASLP-lab/DiffRhythm2) · [sa3_mlx](https://github.com/Stability-AI/stable-audio-3/blob/main/optimized/mlx/README.md) · [stable-audio-open-small](https://huggingface.co/stabilityai/stable-audio-open-small) · [heartlib](https://github.com/HeartMuLa/heartlib) · [heartlib-mlx](https://github.com/Acelogic/heartlib-mlx) · [Qwen-Music paper](https://arxiv.org/abs/2607.11699) · [mlx-audio](https://github.com/Blaizzy/mlx-audio) · [mlx-audio #536](https://github.com/Blaizzy/mlx-audio/issues/536)

**MCP:** [mcp-server-musicgpt](https://github.com/pasie15/mcp-server-musicgpt) · [mcp-minimax-music-server](https://github.com/falahgs/mcp-minimax-music-server) · [live-coding-music-mcp](https://github.com/williamzujkowski/live-coding-music-mcp)

**Video:** [LTX-2 LICENSE](https://raw.githubusercontent.com/Lightricks/LTX-2/main/LICENSE.md) · [LTX-Desktop](https://github.com/Lightricks/LTX-Desktop) · [ComfyUI-LTXVideo #473](https://github.com/Lightricks/ComfyUI-LTXVideo/issues/473) · [#386](https://github.com/Lightricks/ComfyUI-LTXVideo/issues/386) · [Wan2.1-T2V-1.3B LICENSE](https://huggingface.co/Wan-AI/Wan2.1-T2V-1.3B/raw/main/LICENSE.txt) · [Wan-AI org](https://huggingface.co/Wan-AI) · [Wan2.1 #208](https://github.com/Wan-Video/Wan2.1/issues/208) · [Wan2.1-MAC](https://github.com/jasonpaulso/Wan2.1-MAC) · [HunyuanVideo LICENSE](https://huggingface.co/tencent/HunyuanVideo/raw/main/LICENSE) · [HunyuanVideo-1.5 #18](https://github.com/Tencent-Hunyuan/HunyuanVideo-1.5/issues/18) · [HunyuanVideo discussion #13](https://huggingface.co/tencent/HunyuanVideo/discussions/13) · [mochi-1-preview](https://huggingface.co/genmo/mochi-1-preview) · [CogVideoX-2b LICENSE](https://huggingface.co/zai-org/CogVideoX-2b/raw/main/LICENSE) · [CogVideoX-5b LICENSE](https://huggingface.co/zai-org/CogVideoX-5b/raw/main/LICENSE) · [CogVideoX-Mac-Setup](https://github.com/nicedreamzapp/CogVideoX-Mac-Setup) · [diffusers #9972](https://github.com/huggingface/diffusers/issues/9972) · [Open-Sora](https://github.com/hpcaitech/Open-Sora) · [Open-Sora tech report](https://arxiv.org/html/2503.09642v1) · [FLUX.1-dev LICENSE](https://huggingface.co/black-forest-labs/FLUX.1-dev/blob/main/LICENSE.md) · [Kandinsky-5](https://github.com/kandinskylab/kandinsky-5) · [Blaizzy/mlx-video](https://github.com/Blaizzy/mlx-video) · [dgrauet/ltx-2-mlx](https://github.com/dgrauet/ltx-2-mlx) · [mlx-community/ltx-2.5-mlx](https://huggingface.co/mlx-community/ltx-2.5-mlx) · [mlx-examples](https://github.com/ml-explore/mlx-examples) · [ComfyUI #9255](https://github.com/Comfy-Org/ComfyUI/issues/9255) · [ComfyUI API routes](https://docs.comfy.org/development/comfyui-server/comms_routes) · [lilting.ch Mac benchmarks](https://lilting.ch/en/articles/ltx2-wan22-mac-local-video-gen) · [MiniMax H3 "minimally open"](https://www.deeplearning.ai/the-batch/minimaxs-state-of-the-art-video-model-is-only-minimally-open)
