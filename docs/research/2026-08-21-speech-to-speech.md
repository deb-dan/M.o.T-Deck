# Speech-to-Speech (S2S) voice chat — landscape for a local Apple-Silicon lane

Research only, 2026-08-21. Brief: Debi found `nvidia/NVIDIA-NemotronLabs-VoiceChat-11B` and wants an
**instantaneous voice-chat surface** as its own chat type, **additive** — the existing TTS/STT/conv
lanes stay exactly as they are. Evidence is URL / file:line. ⚠️ marks unverified claims.

> **HEADLINE, up front, because it reframes the ask:**
> 1. **VoiceChat 11B cannot run on this Mac today.** It is **F32, 44.4 GB**, hybrid Mamba/Transformer,
>    and its runtime is NeMo + vLLM + Triton + CUDA kernels (`mamba-ssm`, `causal-conv1d`). No MLX or
>    GGUF port exists. Its *licence is fine* (OpenMDW-1.1, genuinely permissive). It is blocked on
>    **runtime**, not law. Not adoptable; watch it.
> 2. **The real Mac-feasible finding is not Moshi — it is that `mlx-vlm` now ships a complete
>    Qwen3-Omni implementation *with the Talker and the code2wav vocoder*,** i.e. native speech
>    **output** on MLX, with a streaming path, committed **yesterday**.
> 3. **The honest trade-off must be said plainly: an S2S model answers from ITS OWN weights.** You
>    cannot bolt Debi's 35B chat brain onto a fused S2S model. Bolting your brain on *is* the cascade —
>    which is what conv mode already is. Choosing S2S = choosing a smaller brain for lower latency.

---

## 1. NVIDIA-NemotronLabs-VoiceChat-11B — correct find, wrong machine

Sources: [model card](https://huggingface.co/nvidia/NVIDIA-NemotronLabs-VoiceChat-11B) · HF API ·
`config.json` · [OpenMDW-1.1](https://github.com/OpenMDW/OpenMDW/blob/main/1.1/LICENSE.OpenMDW-1.1)

| Fact | Value |
|---|---|
| Architecture | **True end-to-end full-duplex S2S**, one unified model. Fast Conformer encoder → Nemotron Nano v2 **9B** LLM backbone → NVIDIA TTS decoder + codec. Separate output channel for tool-calls. |
| Params / size | 11B. HF API: `F32: 11,095,109,073` params, `usedStorage` **44,411,750,825 B = 44.4 GB**, one `model.safetensors`. |
| Runtime | `Runtime Engine: vLLM`; Supported HW: A100/H100/H200/B100/B200/RTX-6000; **OS: Linux**. Install requires `causal-conv1d`, `mamba-ssm` (CUDA-only kernels), NeMo `speechlm2`. Interactive mode = an **NVIDIA Triton container over WebSocket**. |
| Latency | 448 ms smooth turn-taking, 480 ms interruption (Full-Duplex-Bench 1.0) — **measured on H100**. |
| Intelligence | Big Bench Audio **37.0%** — best of the open full-duplex field by a wide margin (`overview.md`). |
| Tool calling | First open FD model with it. `<TOOLCALL>[…]</TOOLCALL>`, on-hold messages while a tool runs. |
| Licence | **OpenMDW-1.1 — permissive.** Read in full: "deal in the Model Materials without restriction", explicit "no restrictions … with respect to any outputs", retain-notice + patent-retaliation only. **No NC clause, no geographic exclusion.** Clean for local personal use. |

**Mac feasibility TODAY: no.** Three independent blockers: (a) F32 44.4 GB weights with no quant
published; (b) Mamba2 SSM kernels are CUDA — MLX has Mamba support but nobody has ported *this*
model; (c) the only interactive path is a Triton/vLLM container. ⚠️ Nobody has attempted an MLX port
(no `*VoiceChat*mlx*` repo on HF). The one derivative, `pipecat-ai/NVIDIA-NemotronLabs-VoiceChat-11B-Spark`,
is **GPTQ for DGX Spark + vLLM** — still CUDA. Also note `overview.md` says *"ready for research
purposes only"* and the 2-minute audio context window, ~5-tool ceiling, and "not suitable for noisy
or reverberant environments".

**Verdict: WATCH-ITEM, not a candidate.** Re-check when either an MLX port or a GGUF appears. Because
the licence is permissive, the moment a port lands this becomes the strongest candidate in the field.

## 2. Moshi (kyutai-labs) — the only *shipped, official* MLX full-duplex S2S

Sources: [repo README](https://github.com/kyutai-labs/moshi) · HF API trees · local clone

- **Official MLX implementation confirmed**: `moshi_mlx/` in-repo, `pip install moshi_mlx`
  (v**0.3.0**, `moshi_mlx/moshi_mlx/__init__.py`), README section *"MLX implementation for local
  inference on macOS"*, "tested on a MacBook Pro M3". A Swift/ExecuTorch artifact repo also exists
  (`lmz/moshi-swift`) but is unofficial-looking and untouched since 2025-06.
- **Sizes (HF tree API, exact bytes):** q4 `model.q4.safetensors` **4,805,545,317** + Mimi codec
  `tokenizer-…safetensors` **384,644,900** → **≈5.2 GB**. q8 → **8,168,805,411** + Mimi → **≈8.55 GB**.
  bf16 also published. Voices: **Moshiko** (male), **Moshika** (female) — fixed, not clonable.
- **Licence — clean:** code MIT (Python) / Apache (Rust); **weights CC-BY-4.0** (README: "All models
  are released under the CC-BY 4.0 license"). ⚠️ **NC TRAP NEARBY:** the newer
  `kyutai/moshika-rl-seamless` (2026-06) is **cc-by-nc-4.0**, as are `nu-dialogue/j-moshi*` and the
  Hibiki derivatives. Pin the **cc-by-4.0** `moshiko-mlx-q8` / `moshika-mlx-q8`, not the RL variant.
- **Latency:** README claims 160 ms theoretical (80 ms Mimi frame + 80 ms acoustic delay), **~200 ms
  practical on an L4 GPU**. ⚠️ **No Mac/MLX latency number is published anywhere** — this is exactly
  what a measure script must establish.
- **Integration shape — better than expected:** `python -m moshi_mlx.local_web` runs an **aiohttp
  server on `--port 8998` (`--host localhost`)** serving its own web UI and a **WebSocket at
  `/api/chat`** carrying **Opus** frames both ways (`sphn.OpusStreamReader/Writer`, `local_web.py:279,
  305, 317-318, 327, 389-390`). That is *exactly* the component shape the harness already knows:
  loopback port + health + a tab. The bundled web UI also does **echo cancellation**, which the
  README says materially improves quality — and which our own barge-in research (2026-08-15) found we
  do not have.
- **FUSED — and this is the RAM-ledger consequence:** Moshi is one 7B model that *is* the brain, the
  ASR and the TTS. It cannot use our loaded chat model, cannot be pointed at :6767, and its weights
  are a **second resident claimant** on the 48 GB budget alongside `runner.model`.
- **The disqualifying weakness, stated plainly:** NVIDIA's own comparison table (`overview.md`) puts
  **Moshi at 4.4% on Big Bench Audio** vs VoiceChat 37.0% and Freeze-Omni 33.4%. Moshi is a
  conversational-dynamics marvel and a **poor knowledge assistant**. It is English-only. Upstream is
  also quiet — **last commit 2026-05-16** (a typo fix), ~3 months stale.

## 3. The rest of the field, ranked by Mac story

| Model | Runtime on Mac | Size | Licence | Latency class | Verdict |
|---|---|---|---|---|---|
| **Qwen3-Omni-30B-A3B** | **MLX, real** — `mlx-vlm` has `qwen3_omni_moe/{thinker,talker,code2wav}.py`; `examples/qwen3_omni_demo.py:54` returns `(thinker_result, audio_wav)`; `generate_stream()` at `qwen3_omni_moe.py:673` | **21.8 GB** at 4-bit (5 shards, summed) | apache-2.0 per mlx-community card (⚠️ upstream tags `license:other`) | Turn-based, **streaming chunks**; 3B active params ⇒ fast | **TOP MAC CANDIDATE** |
| **Gemma 4 E4B / 12B** | MLX, excellent, already in our world | 4-8 GB | apache-2.0 | n/a | **Audio-IN, TEXT-OUT only** — card: "generating text output"; audio = ASR + speech-translation. *Not S2S* but see §4. |
| **Freeze-Omni 7B** | none | — | — | 33.4% BBA (2nd-best FD brain) | ⚠️ no MLX/GGUF found; unexamined |
| **Mercury (`ga642381/Mercury-M12…M20`)** | transformers `custom_code`, `raon_duplex` | — | **cc-by-nc-4.0** | full-duplex, 80 ms frames | **REJECT** — NC, anonymous-review checkpoints, base model *withheld*, empty result tables |
| **GLM-4-Voice-9b** | none (chatglm `custom_code`) | ~9B + separate tokenizer/decoder | unstated on repo | — | **REJECT** — 2024-vintage, no MLX, 3-repo assembly |
| **Ultravox / Voxtral / Qwen2-Audio** | **llama.cpp mtmd** (`docs/multimodal.md:105-130`) | small | permissive | — | **speech-in only**, explicitly "audio input, vision input" |
| **LLaMA-Omni / mini-omni** | none current | — | — | — | superseded; no 2026 MLX presence |

**llama.cpp state (HEAD 2026-08-21):** audio **input** is supported via `mtmd` (Ultravox 0.5,
Qwen2-Audio, Voxtral, Qwen2.5-Omni — the last annotated *"Capabilities: audio input, vision input"*).
Audio **output** exists only as a **separate 3-stage TTS pipeline** (`tools/mtmd/README-dev.md:41-46`,
`tools/tts`, our own `llama-tts`). **There is no unified duplex S2S path in llama.cpp.** Anything
S2S on this machine must be MLX (or Rust/Candle-Metal, which Moshi also offers).

## 4. Integration sketch — what a "Voice Chat (S2S)" surface needs

Shared to both candidates:
- **Full-duplex audio transport.** We have the mic half already: the AudioWorklet + energy VAD of the
  conv lane (`bridge/panel/index.html:5574` `VAD_FLOOR`, `:5606` `hangoverFor`, `:6029` `convStep`).
  S2S needs **less**, not more: no VAD segmentation at all — raw continuous PCM up, continuous PCM
  down, with turn-taking decided by the *model*. The `convGated` feedback interlock and the 300 ms
  `CONV_GRACE_MS` become unnecessary *and actively wrong* — a full-duplex model is **supposed** to
  hear itself being interrupted. ⚠️ **But we have no echo cancellation** (2026-08-15 bargein report:
  `echoCancellation:true` guarantees only `remote-only`), so without headphones the model will hear
  its own output as user speech. **Headphones are a hard precondition for a v1.** Moshi's bundled web
  UI does its own AEC — a strong argument for embedding *their* client rather than building ours.
- **A resident model slot + ledger accounting.** Exactly the shipped voice-worker pattern:
  `_resident_voice_bytes()` (`bridge/app.py:2166`), `_loaded_models_bytes(exclude_slot=…)` (`:2183`),
  `_voice_spawn_guard` (`:2207`) → 409 "eject a chat model first", and the music lane's
  `MUSIC_RAM_GB` warn-with-override. Budget numbers to gate on: **Moshi q8 ≈ 9 GB**, **Qwen3-Omni
  4-bit ≈ 22 GB** — the latter genuinely competes with a 35B chat model on a 48 GB budget.
- **Its own chat surface.** Both models emit **text alongside audio** (Moshi's "inner monologue";
  Qwen3-Omni's thinker text), so the transcript renders for free and the surface looks like a chat.
  The transcript is the model's own text stream — **not** a re-transcription.
- **What it must NOT do:** reuse the Chat/Agent/Hermes lanes' model picker, or appear to obey
  `runner.model`. The S2S model *is* the model. The UI must say so on the surface, in the register the
  Sampling group already uses for lane honesty.

**The trade-off, said plainly (Fable's call to make, not a builder's):** conv mode answers with a
35B brain in ~2-4 s. Moshi answers in ~0.2 s with a brain that scores **4.4%** where our lane's model
scores far higher — it will be charming and frequently wrong. Qwen3-Omni sits in between: a real
30B-A3B assistant brain with genuine speech output, but **turn-based, not full-duplex** — no
barge-in, no backchannel. **These are three different products.** S2S is not an upgrade to conv mode;
it is a second thing, which is precisely why Debi's "its own chat type, additive" framing is right.

## 5. Ranked adopt candidates + measurement-first plan

1. **Qwen3-Omni-30B-A3B-Instruct-4bit via mlx-vlm — RECON→MEASURE FIRST.** The only option that is
   simultaneously Mac-native, actively maintained (mlx-vlm commit 2026-08-20), speech-**out** capable,
   and smart enough to be useful. Rides `data/mlx-venv` and the existing download manager. Costs: 22 GB
   resident; turn-based so "instantaneous" means ~1 s, not 200 ms. ⚠️ **Unverified:** that the
   mlx-community 4-bit quant actually *contains* talker+code2wav weights (`config.enable_audio_output`
   drives construction, `qwen3_omni_moe.py:41-44`) — the index.json exceeded the fetch limit and the
   sandbox proxy blocks huggingface.co. **This is measurement item #1 and it is a go/no-go.**
2. **Moshi (moshiko/moshika-mlx-q8) — MEASURE IN PARALLEL, adopt only for the *experience*.** The only
   true full-duplex thing that runs on this Mac today, official MLX, clean CC-BY-4.0, and it arrives
   with its own loopback server + AEC web client (component-shaped). Adopt as a **toy/demo lane**, and
   say in the UI that it is not a knowledge assistant. Do not pin the NC variants.
3. **Gemma-4-E4B as a "half-cascade" — the sleeper, and the cheapest win.** Not S2S, but it takes
   **audio in** and emits text on MLX, which would collapse our STT+LLM into one model and remove a
   whole hop of conv-mode latency (and whisper's hallucination class) while **keeping a real brain**.
   ⚠️ 30-second audio cap; needs its own measurement. Worth a Fable decision on its own.
4. **VoiceChat 11B — watch.** Permissive licence, best brain in the field, blocked purely on runtime.
   Trigger to revisit: any MLX port, GGUF, or an int4/int8 release from NVIDIA.
5. **Rejected:** Mercury (NC + anonymous), GLM-4-Voice (stale, no MLX), LLaMA-Omni/mini-omni
   (superseded), Ultravox/Voxtral (speech-in only), moshika-rl-seamless & j-moshi (**cc-by-nc-4.0**).

**Measurement-first plan — the music-lane pattern (`scripts/measure_music.sh` + a runbook), before
any lane is built.** A throwaway `data/s2s-trial-venv` (Moshi pins `moshi_mlx==0.3.0`; Qwen3-Omni
needs current `mlx-vlm` — **neither may touch `data/mlx-venv`**), `/usr/bin/time -l` RESULT lines,
disk+RAM guards, an eject-the-chat-model instruction, and a printed cleanup one-liner. Measure:

- **M1 (go/no-go):** does the mlx-community Qwen3-Omni 4-bit load with `enable_audio_output` true and
  return non-None `audio_wav` from `examples/qwen3_omni_demo.py`? If no, find/convert a quant that does.
- **M2:** Qwen3-Omni **wall time + peak RSS** for one short spoken turn, and separately
  **time-to-first-audio-chunk** via `generate_stream` (`:673`) — the streaming number is the one that
  decides whether this feels instantaneous.
- **M3:** Moshi `python -m moshi_mlx.local -q 8` — model load time, peak RSS, and **measured
  round-trip latency** (the 200 ms figure is an L4 GPU number and must not be quoted for a Mac).
- **M4 (ears, and Debi's call):** the same three questions asked of both. Moshi will win on feel and
  lose on substance; the ruling on that trade-off is a design decision, not a benchmark.
- **M5 (cheap, separate):** Gemma-4-E4B audio-in → text on MLX: latency vs our whisper/Parakeet hop.

⚠️ **Honest limits of this report:** nothing was run — no model was downloaded and no audio produced;
every size is from the HF tree API, every capability claim from source read at HEAD or a model card.
PyPI and api.github.com are unreachable from this sandbox, and huggingface.co is reachable only via
the fetch tool (which the Qwen3-Omni weight index exceeded) — hence M1 being a go/no-go rather than a
fact. All latency figures published anywhere in this space are **NVIDIA/L4/H100 GPU numbers**; there
is **no published Apple-Silicon S2S latency measurement for any model here.**
