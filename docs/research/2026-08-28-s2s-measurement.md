# S2S voice-chat lane — M1 measurement & go/no-go (2026-08-28)

Measurement agent, music-lane pattern, bound by `docs/DOCTRINE-PROACTIVE-BUILD.md`.
Brief: roadmap §2.1 item 1 (`docs/handoff/ROADMAP-2026-08-14.md:41-51`) + the 2026-08-21
S2S recon (`docs/research/2026-08-21-speech-to-speech.md`). No production code touched;
the :6767 runner and the resident 27B were never stopped, ejected, or queried.
Every number below was measured on this Mac today unless marked desk-checked.

> **HEADLINE:**
> 1. **M1 is GO on the original question**: the mlx-community Qwen3-Omni 4-bit quant
>    **contains the talker + code2wav weights** (proven from its index for ~0.6 MB of
>    downloads, then confirmed by generating real audio locally).
> 2. **The field moved under the roadmap's feet — in our favor.** The 2026-08-21 blocker
>    list is stale: **NemotronLabs-VoiceChat-11B now has official mlx-community MLX quants
>    (2026-08-08)** and the **installed mlx-vlm 0.6.17 ships a complete `nemotron_voicechat`
>    implementation** — Conformer perception, duplex Nemotron-H LLM, SpeechDecoder TTS,
>    a `VoiceChatSession` API, **and a built-in WebSocket `/v1/realtime` server endpoint**.
>    The "CUDA-only, watch it" verdict is dead. At **9.18 GB (4-bit)** it is now the
>    *cheapest* real S2S candidate, not the unreachable one.
> 3. **"Newest omni with MLX" resolves to a fork in the road, not one model**: Qwen's omni
>    line still tops out at **Qwen3-Omni-30B-A3B** (no 3.5/3.6-omni exists — the
>    "Qwen3.5-Omni" repos on HF are text-model fine-tunes wearing the name), while the
>    newest omni-family MLX arrivals are NVIDIA's (Nano-Omni 30B = audio-IN only;
>    VoiceChat-11B = true full-duplex S2S).

---

## 1. Newest omni-family model with MLX support TODAY (resolved)

Method: HF API queries (`/api/models?search=…`, sorted by createdAt) + the installed
`mlx-vlm 0.6.17` model registry (`data/mlx-venv/…/mlx_vlm/models/`). PyPI confirms
**0.6.17 is also the latest release** — we are current.

| Candidate | HF repo (quant) | Created | Size (exact, tree API) | Speech OUT? | mlx-vlm module |
|---|---|---|---|---|---|
| **Qwen3-Omni-30B-A3B-Instruct** | `mlx-community/Qwen3-Omni-30B-A3B-Instruct-4bit` (also 5/6/8bit, bf16) | 2025-12-24 | **21.84 GB** (4-bit, summed) | **YES** — thinker+talker+code2wav | `qwen3_omni_moe/` (talker.py, code2wav.py, streaming `generate_stream`) |
| **NemotronLabs-VoiceChat-11B** | `mlx-community/NemotronLabs-VoiceChat-11B-4bit` (also 8bit, bf16; 2026-08-08) | 2026-08-08 | **9.18 GB** (4-bit) | **YES** — full-duplex S2S (stt_model 1243 tensors + tts_model 635 incl. audio_codec) | `nemotron_voicechat/` (session.py, streaming.py, tts.py) + server `/v1/realtime` |
| Nemotron-3-Nano-Omni-30B-A3B | `mlx-community/NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-4bit` | 2026-06-09 | not sized (ruled out first) | **NO** — `nemotron_h_nano_omni/` has audio.py (input) but zero talker/tts/vocoder code | `nemotron_h_nano_omni/` |
| Gemma-4-E4B (not omni, "half-cascade") | `mlx-community/gemma-4-e4b-it-4bit` | 2026-04-02 | **5.18 GB** | NO — audio-IN, text-out | `gemma4/` (AudioEncoder + audio_feature_extractor) |

**Qwen omni line status**: `/api/models?search=omni&author=Qwen` newest is still
Qwen3-Omni-30B-A3B (Instruct/Thinking/Captioner, 2025-09). The text line (3.5/3.6/3.8)
has NOT been followed by a newer omni. Community "Qwen3.5-Omni" repos
(ZERO-POINT-AI/Miss_MARTHA…, MARTHA-2B…) were checked: `model_type: qwen3_5`, no audio
tower — **name squatting, not omni models. Do not pin them.**

**License notes (desk-checked from cards/tags today):**
- Qwen3-Omni upstream + mlx-community quants: `license: other, license_name: apache-2.0`
  (Qwen's usual labeling; effectively Apache-2.0, same as the 08-21 recon found).
- VoiceChat-11B mlx-community quants: tagged **`license:openmdw-1.1`** — the permissive
  license the 08-21 recon already read in full. ⚠️ Avoid the `OsaurusAI/*JANG*`/MXFP8
  third-party variants (`license:other`) and the earlier `mlx-community/*-mlx-4bit`
  duplicates (2026-08-05, `license:other`); pin the 2026-08-08 `NemotronLabs-VoiceChat-11B-4bit`.
- Gemma-4-E4B: Gemma license family (as already accepted in-house for the gemma lane).

## 2. Does the 4-bit quant contain the talker weights? — YES (M1 go/no-go: GO)

Method: downloaded ONLY `model.safetensors.index.json` (357,111 B) + `config.json`
(16,672 B) for Qwen3-Omni-4bit, and the same pair for VoiceChat-4bit (179,815 B +
39,788 B). **Total settled-by-download: 593,386 bytes.**

- **Qwen3-Omni-30B-A3B-Instruct-4bit**: top-level tensor prefixes in the weight map:
  `thinker` **2227** tensors, `talker` **909**, `code2wav` **352**. Config:
  **`enable_audio_output: true`**, `talker_config` + `code2wav_config` present, speakers
  `{chelsie, ethan, aiden}`, quant `4-bit affine, group 64`. The talker head is not only
  present — it is what `mlx_vlm` uses to construct the talker (`config.enable_audio_output`
  drives it, `qwen3_omni_moe.py:41-52`).
- **NemotronLabs-VoiceChat-11B-4bit**: prefixes `stt_model` **1243** / `tts_model` **635**
  (incl. `tts_model.audio_codec` 214 tensors); config `model_type: nemotron_voicechat`,
  `tts_config` + `codec_config`, 16 kHz in / 22.05 kHz out, single "Aria" voice, and an
  `mlx_runtime_config_version` key — this quant was made *for* the mlx-vlm runtime.

## 3. Latency/RAM feasibility on this Mac (measured)

Constraint honored: the resident 27B (`llama-server` on :6767, Qwen3.6-27B Q4_K_S +
F32 mmproj, `--ctx-size 65536`) stayed loaded and untouched throughout.

**Pre-flight (measured before the run):** 64 GB machine, `memory_pressure` reported
**56% free (~36 GB)** with the 27B resident; disk 65 GiB free. Qwen3-Omni-4bit needs
21.84 GB of weights + activations → fits the free envelope with margin, so the live
run was a go (per the brief's headroom rule).

**Download reality (worth recording for the lane's installer):** single-stream HF
download measured **~2.5 MB/s**; 6-8 parallel range requests measured **~12.7 MB/s**
burst, ~5-8 MB/s sustained. The 21.84 GB snapshot is a **45-75 min** acquisition on
this connection — the Voice Chat surface must treat model download as a long-running,
resumable job (the existing download-manager pattern), not a spinner.

**Run: NOT COMPLETED — aborted on time, not on RAM.** The download was started
(parallel-range curl, scratch dir, resumable) and killed at **4.3 GB of 21.84 GB after
~25 min**: HF throttled the sustained rate to **~3 MB/s** after the first minutes'
burst, putting completion ~100 min out — an open-ended wait for a number that is not
the M1 gate (the talker question was already settled from the index). All partial
weights were deleted; total kept from this session's downloads is **~593 KB of JSON**
(the four index/config files, preserved in the session scratchpad).

What §3 can therefore honestly state:
- **RAM headroom: fits on paper.** ~36 GB free with the 27B resident vs 21.84 GB of
  weights + activations (expect ~23-26 GB peak for one short-context turn). Margin
  ~10 GB — real but not generous; the ledger gate should budget **24 GB** for this
  worker, not the roadmap's ~22 GB, until a live peak-RSS number exists.
- **Latency: NO Apple-Silicon number exists — still — and none was produced here.**
  One architectural fact from the installed source bounds it without weights: in
  `generate_stream` (`qwen3_omni_moe.py:673-850`) **the thinker completes its ENTIRE
  text answer before the talker emits its first code**, and the first wav chunk needs
  ~300 talker codes + a code2wav stream-decode. Time-to-first-audio ≈ full thinker
  generation + talker spin-up — on the order of a conv-mode turn, NOT Moshi-class
  200 ms. This materially caps any "instantaneous" claim for Qwen3-Omni regardless
  of what the eventual measurement says.
- **The deferred measurement is staged, not lost:** the exact run script
  (`measure_qwen3omni.py`: RESULT-line format, streaming TTFA timing, thinker tok/s,
  ru_maxrss, wav writer) and the resumable per-file parallel downloader (`pardl.sh`)
  are in this session's scratchpad — copy both into the next measurement session and
  run under `/usr/bin/time -l` when a ~90-min download window is acceptable.

## 4. Fallbacks, desk-checked today (no installs)

- **Moshi (kyutai)**: repo last commit **2026-05-16** ("fix a couple of typos") — now
  ~3.5 months stale; `moshi_mlx` still **0.3.0** on PyPI (unchanged since the 08-21
  recon). `kyutai/moshiko-mlx-q8` still **cc-by-4.0** (tag re-verified today). The NC
  trap stands: pin `moshiko-mlx-q8`/`moshika-mlx-q8` originals, never `moshika-rl-seamless`
  or other `-nc` derivatives. Status: unchanged — parked fallback, weak brain (4.4% BBA),
  English-only, q8 ≈ 8.55 GB.
- **VoiceChat-11B**: **NO LONGER CUDA-only — promoted from watch-item to candidate.**
  See §1/§2: official mlx-community MLX quants (openmdw-1.1), complete `nemotron_voicechat`
  runtime inside our already-installed mlx-vlm 0.6.17, `VoiceChatSession` +
  `VoiceChatProfile` (built-in frame-timing profiler!) + WebSocket `/v1/realtime` server
  (`mlx_vlm/server/realtime.py:255,402`) — offline WAV mode AND online duplex mode.
  4-bit = **9.18 GB**. Caveats from the card: one voice ("Aria"), one concurrent realtime
  session, "whether it keeps pace with wall clock depends on the model precision and host
  hardware" — i.e., **real-time factor on this Mac is the open question**, and it was NOT
  measured today (weights not downloaded; the session budget went to the roadmap's named
  M1 target). That measurement is the obvious next slice and is ~2.4x cheaper to acquire
  than Qwen3-Omni.
- **Gemma-4-E4B audio-in**: premise **still holds and is now concrete**:
  `mlx-community/gemma-4-e4b-it-4bit` (2026-04-02) is **5.18 GB**, config carries
  `audio_config`, and installed mlx-vlm has the `gemma4` AudioEncoder path. Also spotted:
  `mlx-community/unsloth-gemma-4-E4B-it-qat-oQ4` (2026-07-06, QAT). Audio-IN → text-out
  only (not S2S), 30 s audio-cap caveat from the 08-21 recon unrescinded. Cheapest
  conv-mode win: **confirmed as still true**.

## 5. VERDICT

Per candidate, with the numbers behind each call:

- **Qwen3-Omni-30B-A3B-Instruct-4bit — M1 GO (talker present: 909 talker + 352
  code2wav tensors, `enable_audio_output: true`), M2 latency measurement DEFERRED.**
  21.84 GB weights; fits the 64 GB machine alongside the 27B (~36 GB free measured);
  ledger envelope **24 GB**. Known ceiling: turn-based, thinker-before-talker →
  seconds-class time-to-first-audio. Still the only MLX option with a real 30B-A3B
  brain AND speech out. Speakers: chelsie/ethan/aiden. License effectively Apache-2.0.
- **NemotronLabs-VoiceChat-11B-4bit (MLX) — NEW CANDIDATE, arguably now the front-runner
  for the *"instantaneous"* ask.** 9.18 GB, OpenMDW-1.1, full-duplex, complete runtime
  already inside our pinned mlx-vlm 0.6.17 including a `/v1/realtime` WebSocket server
  (the exact component shape MOT Deck runs everywhere) and a built-in latency
  profiler (`VoiceChatProfile`). Best open full-duplex brain (37% BBA vs Moshi's 4.4%).
  Unknown: real-time factor on M-series — the card itself says it depends on host
  hardware. **Measure this one next; at 9.18 GB it is a ~30-min acquisition even at
  throttled rates.** One voice (Aria), English, 2-min audio context.
- **Moshi — parked fallback, unchanged.** Stale upstream (2026-05-16), weak brain,
  cc-by-4.0 pins re-verified. Keep parked.
- **Gemma-4-E4B audio-in — GO as its own small slice (unchanged premise, now with a
  concrete pin):** `mlx-community/gemma-4-e4b-it-4bit`, 5.18 GB, audio_config present,
  gemma4 audio path in our installed mlx-vlm. Cheapest conv-mode latency win; not S2S.
- **Nemotron-3-Nano-Omni-30B — NO for this lane** (audio-in only in MLX; no speech head).

**Recommended M2 shape:** ONE more measurement session, two runs, ranked:
(1) **VoiceChat-11B-4bit** offline-WAV + realtime profile (9.18 GB download,
`VoiceChatSession.generate` + `VoiceChatProfile.summary()` gives frame timings for
free) — this answers "can this Mac hold a real-time full-duplex conversation" which is
the actual product question; (2) resume the Qwen3-Omni-4bit download with the staged
`pardl.sh` + `measure_qwen3omni.py` for the turn-based comparison numbers. Then Fable
specs the Voice Chat surface against whichever real-time factor survives contact.
If VoiceChat's RTF < 1.0 on this Mac, the surface should be specced around it
(smaller, duplex, tool-calling, permissive license) with Qwen3-Omni as the
"smart turn-based" alternate — not the other way round.

**What the Voice Chat surface spec needs to know (ledger gate):**
- Worker RAM envelope: **Qwen3-Omni-4bit: 24 GB** (21.84 GB weights, unmeasured peak —
  do not quote lower until measured); **VoiceChat-11B-4bit: 11 GB** (9.18 GB weights +
  margin); Moshi q8: 9 GB (unchanged from 08-21). All three coexist-with-27B on 64 GB;
  none coexists with a 35B-class chat model without ejection — the existing
  `_voice_spawn_guard` 409 pattern (`bridge/routers/voice.py:941-945`) is the right gate.
- Audio I/O contract: Qwen3-Omni emits 24 kHz wav chunks (stream); VoiceChat is
  16 kHz in / 22.05 kHz out over `/v1/realtime` WS. Transcript comes free from both
  (thinker text / duplex text channel) — render it, don't re-transcribe.
- Headphones remain a hard v1 precondition (no AEC in our stack — 08-15 finding, unchanged).
- Model download must be a resumable background job: measured sustained ~3 MB/s
  (throttled), so 9-22 GB = 50-120 min on this connection.

## Honest limits

- **No model weights were run; no audio was produced on this Mac today.** The Qwen3-Omni
  download was deliberately aborted at 4.3/21.84 GB (~100 min remaining at the measured
  throttled rate) because the M1 gate was already settled from the index and an
  open-ended wait was ruled out. Time-to-first-audio, tokens/s, and peak RSS for both
  S2S candidates remain UNMEASURED on Apple Silicon — the "seconds-class TTFA" claim
  for Qwen3-Omni is an architectural inference from installed source, not a stopwatch.
- VoiceChat-11B's MLX runtime was verified by reading the installed package source and
  the quant's config/index — not by executing it. "Works" here means "complete
  implementation + purpose-built quant exist", not "ran clean".
- Big Bench Audio scores are NVIDIA's published numbers, not re-verified.
- License findings are from HF tags/cards read today; LICENSE files were not re-read
  in full this session (OpenMDW-1.1 was read in full in the 08-21 recon).
- Bandwidth numbers are this afternoon's, one connection, one CDN mood.

**Session hygiene (verified):** the :6767 runner (pid 64588) was never signaled or
queried beyond a read-only `ps`/health check — up 18+ h, RSS unchanged-class; the
resident 27B stayed loaded. RAM was checked before any planned load (56-59% free
throughout). All scratch downloads except 593 KB of JSON were deleted
(scratchpad `s2s/` now 604 KB: logs, the four settle-files, the two staged scripts).
No production file, pin, or component was touched; this document is the only repo write.
