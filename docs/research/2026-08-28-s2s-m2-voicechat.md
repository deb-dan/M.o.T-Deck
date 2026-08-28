# S2S voice-chat lane — M2: VoiceChat-11B measured on this Mac (2026-08-28)

Measurement agent (M2 of the S2S lane), bound by `docs/DOCTRINE-PROACTIVE-BUILD.md`.
Follows `docs/research/2026-08-28-s2s-measurement.md` (M1) and executes its ranked
recommendation: profile **mlx-community/NemotronLabs-VoiceChat-11B-4bit** first.
No production code touched; the :6767 runner and resident 27B were never stopped or
signaled. Every number below was measured on this Mac today (64 GB, resident 27B up).

> **HEADLINE:**
> 1. **The model ran, end to end, on this Mac, through our installed mlx-vlm 0.6.17 —
>    real audio in, real audio out, correct answer, accurate live transcription.**
>    The whole loop (Conformer STT → duplex LLM → SpeechDecoder TTS → codec) works
>    from the 9.18 GB 4-bit quant with zero extra installs.
> 2. **But it does NOT hold wall clock in live duplex streaming: RTF = 1.29** (mean
>    103.4 ms of compute per 80 ms frame, p95 108 ms — steady, compute-bound, no
>    jitter to hide in). Alongside an actively generating 27B it degrades to
>    **RTF 1.86**. Live-mic full-duplex "instantaneous" conversation is out of reach
>    on this hardware at 4-bit with mlx-vlm 0.6.17.
> 3. **Offline/turn mode is right at the line: RTF 0.95–1.00 vs the timeline** —
>    a push-to-talk turn works today, and the duplex architecture still pays off:
>    the model started answering **while the user was still mid-question** (answer
>    text began at timeline frame 30; user speech ended at frame 56).
> 4. **The `/v1/realtime` WebSocket server works as shipped** — OpenAI-realtime-
>    *flavored* (not compatible), single-session, no auth, model-per-session; full
>    protocol shape captured below for the M3 surface spec.
> 5. **The download completed** (M1's blocker): **~10 min via Xet**, not the feared
>    50–120 min — `hf download` uses the Xet chunk store (hf_xet is already in the
>    venv) and sustained ~15 MB/s where M1's raw-HTTP curl was throttled to ~3 MB/s.
>    **The lane's installer should go through huggingface_hub/Xet, not raw ranges.**

---

## 1. The acquisition (kept — this may become the real install)

- Repo: `mlx-community/NemotronLabs-VoiceChat-11B-4bit` (OpenMDW-1.1)
- **Pinned revision sha: `dffd203fef7a380081da89479c55848e50b98413`**
- Location (KEPT): `~/.cache/huggingface/hub/models--mlx-community--NemotronLabs-VoiceChat-11B-4bit/`
  (standard HF cache; snapshot dir `snapshots/dffd203…`; **8.6 GiB on disk** = the
  advertised 9.18 decimal-GB). `mlx_vlm` loads it from the repo id directly, so a
  future component can either point at the cache or `hf download --local-dir` into
  `data/models/`.
- Download: `data/mlx-venv/bin/hf download <repo> --revision dffd203…` — **~10 min
  wall**, resumable, no partials left behind. RAM was vm_stat/memory_pressure-checked
  before every load (22–42 % free range across the session; lowest 22 % during the
  contended run — never paged).

## 2. Runtime surface verified (installed mlx-vlm 0.6.17, read + executed)

- `mlx_vlm/models/nemotron_voicechat/`: `Model.create_session(processor)` →
  `VoiceChatSession` (`session.py:28`) with `.generate(audio, extra_decoding_seconds=…)`
  → `VoiceChatResult(text, audio 22.05 kHz, user_transcript, …)` and
  `.create_streaming_session(profile=True)` → `VoiceChatStreamingSession`
  (`streaming.py:193`) with `.push_audio()/.flush()/.cancel()` emitting
  `VoiceChatEvent`s (kinds: `assistant_text_delta`, `user_transcript_delta`, `audio`,
  `function_delta`, `done`, `cancelled`).
- **Built-in profiler is real and was used**: `VoiceChatProfile.summary()`
  (`streaming.py:56-107`) reports per-stage per-80 ms-frame timings and computes
  `realtime_factor` itself — the RTF numbers below are the runtime's own.
- Loader: `mlx_vlm.utils.load(repo, lazy=True, strict=True)` — exactly what the
  realtime server does (`server/realtime.py:25-37`).
- `function_delta` events exist in the protocol — the model has a tool-calling
  channel (not exercised today).

## 3. The numbers

Input for all runs: a real spoken question rendered at 16 kHz (`say`, 4.46 s:
"Hey there. What is the capital of France? …"). Model answered correctly in
every run and its live STT transcript of the question was word-accurate.

| Measurement | Value |
|---|---|
| Load (lazy call → session ready) | 2.4–3.3 s |
| Load incl. full weight materialization | **4.1–6.4 s** |
| Weights resident (mx active memory) | **8.58 GB** |
| MLX peak during inference | **10.89 GB** |
| Process peak memory footprint (`/usr/bin/time -l`) | **17.45 GB** |
| Offline turn, cold (16.46 s timeline: 4.46 s speech + 12 s decode) | 16.4–23.1 s wall → RTF 1.00–1.41 |
| Offline turn, warm | **15.6 s wall → RTF 0.95** |
| Streaming duplex RTF (clean, profiler, 251 frames after 5 cold) | **1.29** (mean 103.4 ms / 80 ms frame) |
| Streaming duplex RTF while 27B was generating | **1.86** (mean 149 ms, p95 208 ms) |
| Greeting onset (duplex text channel) | frame 8 = **0.64 s** into timeline |
| Answer onset vs user speech | answer text at frame 30 (2.4 s) — **user still speaking until frame 56 (4.48 s)** |
| WS server: session.updated (incl. model attach, warm cache) | 0.94 s |
| WS server: first audio delta after send start | 0.99 s |
| Output audio | 22.05 kHz pcm16, ~1764 samples (80 ms) per frame, **continuous channel** (audio event every frame, silence included) |
| Runner :6767 baseline / during VoiceChat / after cleanup | 10.8–14.1 / **8.5** / **14.2 tok/s** |

Clean streaming stage profile (mean / p50 / p95 ms per 80 ms frame — remarkably flat,
i.e. compute-bound, no long tail):

| Stage | mean | p50 | p95 |
|---|---|---|---|
| perception (Conformer) | 26.9 | 26.7 | 28.2 |
| rnnt (live user transcript) | 0.7 | 0.6 | 1.3 |
| language (duplex LLM) | 25.5 | 25.3 | 26.5 |
| **tts (SpeechDecoder)** | **46.1** | 45.9 | 48.0 |
| codec | 4.1 | 4.1 | 4.4 |
| **total** | **103.4** | 102.9 | 108.0 |

Notes on the table:
- **TTS is the wall**: 46 ms of the 103 ms frame budget. Perception+language together
  (~52 ms) would fit 80 ms; the speech decoder pushes it over. An 8-bit quant would be
  slower still; there is no obvious config lever in 0.6.17 to buy back 23 ms/frame.
- The 17.45 GB macOS peak footprint vs 10.89 GB MLX peak: phys-footprint counts Metal
  wired allocations on top of the MLX pool. The ledger should budget on the footprint
  number, not the weights number: **plan 18 GB, not M1's 11 GB.** (M1's "9.18 GB +
  margin" was a paper figure; this is the measured envelope.)
- The audio channel is **continuous** — an `audio` event every frame including
  silence. TTFA as a metric collapses into "greeting at 0.6 s, answer overlapping the
  question"; render logic must gate on the text channel or do VAD on output, not on
  audio-event presence.
- Duplex text channel quality quirk at 4-bit: greeting garbled ("Hello! How can it
  today today") and the answer sentence was emitted twice in every run. Audio output
  was intelligible-length and matched the text. Worth re-checking on 8-bit before
  blaming the model.

## 4. Alongside the resident 27B (measured, both directions)

- 27B probe (200 tokens, temp 0, same prompt): **baseline 10.8–14.1 tok/s** →
  **during VoiceChat streaming inference 8.5 tok/s (~30–40 % slower)** → **after
  cleanup 14.2 tok/s (fully recovered)**. (A probe taken during the model *download*
  read 2.5 tok/s — that was network/disk contention noise, recorded for honesty.)
- Other direction: VoiceChat streaming RTF degraded 1.29 → **1.86** while the 27B
  generated. **Voice chat and a chat completion cannot run concurrently on this
  Mac** — the surface must serialize them or accept ~2x slowdown on both.
- Memory pressure never left "normal"; lowest observed free was 22 % during the
  contended run. No swap, runner RSS unchanged-class throughout.

## 5. `/v1/realtime` WebSocket server (task 3 — protocol captured live)

Started `data/mlx-venv/bin/python -m mlx_vlm.server --host 127.0.0.1 --port 8917`
(scratch port; 8899 was occupied by an unrelated pre-existing process, left alone).
Startup to uvicorn-ready: ~5 s, model NOT loaded at startup — it loads on first
`session.update` (0.94 s with warm cache).

Protocol shape (all verified on the wire): **OpenAI-realtime-flavored, NOT
drop-in-compatible.**

- On connect, server sends `session.created` (`state: "configuring"`, declares
  `pcm16/16000` in, `pcm16/22050` out). No auth of any kind — bind localhost and
  front through the bridge.
- Client MUST send `session.update` with `session.model` (or `?model=` query param);
  optional `system_prompt`, `seed`, `max_streaming_seconds`. One reconfigure only.
  Reply: `session.updated` with `frame_samples: 1280` (80 ms @ 16 kHz).
- Audio in: `input_audio_buffer.append` `{audio: base64 pcm16, sample_rate}` — any
  chunk size; server slices to 1280-sample frames internally.
- Events out (each with `event_id`, `frame_index`):
  `conversation.item.input_audio_transcription.delta` (live user STT),
  `response.text.delta`, `response.function.delta`,
  `response.audio.delta` `{delta: base64 pcm16, sample_rate: 22050, channels: 1,
  audio_codes}` — **every frame, silence included**, `response.done`,
  `response.cancelled`, `error`.
- `input_audio_buffer.commit` → `input_audio_buffer.committed`, flushes, emits
  `response.done`, **and the server ends the session loop** — commit is
  end-of-conversation, not end-of-utterance. A continuous conversation just keeps
  appending (turn-taking is the model's own duplex behavior). `session.ping`/`pong`
  exists for keepalive.
- **Exactly one session server-wide** (verified): a second concurrent connect gets
  `error {code: server_busy}` + WS close **1013**. This maps 1:1 onto the existing
  `_voice_spawn_guard` 409 pattern (`bridge/routers/voice.py:941-945`).
- Full spoken turn over the WS (4.46 s question + 6 s silence, committed): correct
  answer, word-accurate transcript, 10.48 s output audio, 16.5 s total wall —
  consistent with the RTF ~1.3-1.5 measured in-process plus JSON/base64 overhead.

## 6. VERDICT for the M3 spec

- **VoiceChat-11B-4bit is THE pick for the Voice Chat surface v1 — but as a
  push-to-talk / turn-ish surface, not the "instantaneous" full-duplex dream.**
  Measured: RTF 0.95 offline / 1.29 streaming. A live mic feed falls behind wall
  clock ~23 s per minute of conversation and never catches up. What IS real today:
  speak → model answers correctly with ~real-time playback, live transcript free,
  answer generation overlapping the tail of the question. That is already a better
  voice mode than the cascade, in one 8.6 GiB worker with a permissive license.
- **Qwen3-Omni's measurement is now OPTIONAL, not blocking.** It cannot rescue the
  realtime goal (M1 already showed its architecture is thinker-completes-first,
  seconds-class TTFA; it is 2.4x the RAM). Measure it only if M3 wants a smarter
  *turn-based* brain; do not hold the surface spec for it.
- **Recommended component shape:** resident **worker** (voice-worker pattern, like
  music/voice), NOT a bridge-inline load: `data/mlx-venv/bin/python -m
  mlx_vlm.server --host 127.0.0.1 --port <scratch>` with the bridge proxying
  `/v1/realtime` WS frames and enforcing the spawn guard (server's own single-session
  limit + close-1013 maps onto the existing 409). Model attach per session (0.9 s
  warm) means the worker can idle loaded-but-cheap.
  - **Ledger gate: 18 GB planning figure** (measured 17.45 GB peak footprint;
    music.py:56-style planning number, warn-don't-refuse per Debi's ruling).
  - Coexists with the 27B (fits in free RAM, no paging) but **not with concurrent
    27B generation** — serialize, or accept 1.86 RTF + 8.5 tok/s on both.
  - Client contract for the surface: pcm16/16 k up, pcm16/22.05 k down, gate UI on
    text deltas (audio channel is continuous), render the free transcript, headphones
    remain a hard precondition (no AEC — unchanged 08-15 finding).
  - Installer: huggingface_hub/Xet path (~10 min), pin sha `dffd203…`, resumable by
    default. Not raw-range curl.
- Open item for M3, cheap: try the **8-bit quant only if** the 4-bit text-channel
  garble/repetition reproduces annoyingly in practice — it will be slower (worse
  RTF), so it only makes sense for turn-mode quality, never for the realtime goal.

## Honest limits

- One machine, one afternoon, one voice ("Aria"), one English test utterance
  (plus a 6-16 s silence tail). No long-conversation (2-min audio context cap
  untested), no barge-in-interruption test, no tool-calling (`function_delta`)
  exercise, no mic (synthetic `say` speech — real mics add noise the Conformer
  may handle differently).
- RTF numbers are with the 27B resident-but-idle; a truly solo measurement was not
  taken (the fence forbids touching the runner). Idle llama-server should not
  contend for GPU, so 1.29 is treated as effectively solo — inference, not proof.
- The contaminated first streaming run (RTF 1.86) had my own 27B probe running for
  ~23 s of its 39 s window — recorded as the "alongside" number, which is exactly
  what it measured.
- Runner probes used 200 max_tokens; the 27B spent them all on thinking tokens
  (empty content) — tok/s is still the right load signal, but no output-quality
  check was done on the runner.
- `time -l` "peak memory footprint" (17.45 GB) may double-count some Metal-wired
  pages vs the MLX pool; 18 GB is deliberately the conservative reading.
- Scripts/logs/audio artifacts live in this session's scratchpad `s2s/`
  (`measure_voicechat.py`, `ws_client.py`, `runner_probe.py`, event JSON, reply
  WAVs) — session-scoped; rebuild from this doc if needed. Model weights are the
  only kept-outside-scratchpad artifact (HF cache, §1).

**Session hygiene (verified):** scratch mlx_vlm server killed, port 8917 free
(`lsof` clean), no stray mlx_vlm/measurement processes; runner pid 64588 untouched,
up 18 h 36 m, probing at baseline speed (14.2 tok/s) after cleanup; memory back to
41 % free. The pre-existing unrelated listener on 8899 was not touched. No partial
downloads left. This document is the only repo write.

---
*Restart/refresh: nothing to restart — no harness component was modified. The
resident runner (:6767) and 27B were left running and verified healthy.*
