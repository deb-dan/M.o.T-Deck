# Research — faster STT + a licensed starter voice-clip set

**Date:** 2026-08-14 · **Author:** Opus-5 research agent (Fable brief) · **Status:** ⚠️ PENDING FABLE QA
**Constraint honoured:** no code changed. Everything below is evidence + recommendation.

---

## ▣ RECOMMENDATIONS BOX — what Fable should green-light

| # | Recommendation | Confidence | Cost |
|---|---|---|---|
| **R1** | **Adopt NVIDIA Parakeet TDT 0.6B v3 as the default STT — via `mlx-audio`, which is ALREADY INSTALLED.** `data/mlx-venv/bin/mlx_audio.stt.generate` exists today and `mlx_audio/stt/models/parakeet/` ships in the pinned 0.4.7. **No new venv, no new pin, no new dependency, no torch.** The argv is a near-twin of the mlx_whisper one and the output JSON has a top-level `text` key, so `stt_read_output()` works **unchanged**. | **High** (source-verified in our own venv) | Small — one new `stt-parakeet` format + a classifier branch |
| **R2** | **The real reason to switch is not speed — it is that Whisper hallucinates on silence and Parakeet does not.** In `conv` mode a phantom transcript is *auto-sent as a message*. The empty-transcript skip is the only guard, and Whisper actively defeats it by inventing "Thank you." / "Bye." from room tone. A CTC/RNNT-TDT model emits **empty** on silence. This is a correctness fix, not a perf tweak. | **High** | — |
| **R3** | **Do NOT expect an engine swap to buy the next 500 ms.** Per-turn user-perceived latency added by *us* is ~1.7 s (800 ms VAD hangover + ~0.9 s one-shot STT). Of that 0.9 s, most is process spawn + `import mlx` + model load, **not inference**. See §3 — including a challenge to the Gate-2 conclusion recorded in CLAUDE.md. | **Medium-High** (reasoned; one measurement pending) | — |
| **R4** | **Cheapest real latency win: cache the VAD noise floor across listening windows.** The 600 ms re-arm warm-up exists because `vadInit` throws away the learned floor. Keep the frame-buffer reset (that is what prevents resuming mid-utterance) but **seed `noise` from the previous window's median**. Saves ~600 ms per conversational turn for a handful of lines and no new risk surface. | **High** | Very small |
| **R5** | **Second cheapest: retune `VAD_HANGOVER` 800 → 550-600 ms** *only after* R1 lands. Parakeet is far more robust to a clipped tail than Whisper is (Whisper's 800 ms was chosen to stop *its* hallucination). Saves 200-250 ms. Do not go below ~500 ms — that starts splitting utterances at natural pauses, and in `conv` mode a split **sends two messages**. | **Medium** | Very small, but needs an ear test |
| **R6** | **Build a persistent STT worker ONLY after the corrected Gate-2 measurement (§3.4).** It is a cheap clone of `bridge/voice_worker.py` and would remove the fixed overhead entirely — but it also puts a second multi-GB model resident against the 48 GB ledger and re-opens the render-lock question. Measure first. | **Medium** | Medium |
| **R7** | **Voice clips: ship Plan A — 13 clips from VCTK 0.92 (CC BY 4.0).** Only source that fills all 13 accent slots at studio quality under one redistribution-friendly licence, recorded *explicitly for speaker-adaptive TTS*. Fetch per-clip from the HF datasets-server, assemble ~10 s by concatenating 2-3 utterances, store the ground-truth transcript as `ref_text` (free — skips the whisper round-trip entirely). | **Medium-High** | Medium (a fetch script) |
| **R8** | **Also ship a "generate synthetic seed voices" button** using Kokoro-82M (Apache-2.0), already a curated starter. Zero human identity, zero attribution. It cannot fill the Irish/Scottish/Indian slots and its British males are weak — so it is the *alternative*, not the plan. | **Medium** | Small |
| **R9** | **REJECT** for clip sourcing: EARS, Expresso, DAPS, L2-ARCTIC, Speech Accent Archive (all **CC BY-NC**), Google English Dialects (**CC BY-SA** — ShareAlike infects trimmed clips), LibriVox/LJSpeech (named living volunteers; LibriVox itself bans AI voices on-platform), and every TTS project's bundled sample wavs (**undocumented provenance**). | **High** | — |

**One-line verdict:** adopt Parakeet because it is free to adopt and it stops phantom messages; get the latency from VAD-constant tuning and floor caching, not from the engine; ship VCTK-13 for voices with a synthetic fallback.

---

# Q1 — Faster / better STT on Apple Silicon

## 1. The headline finding: we already own it

`data/mlx-venv` (pinned `mlx-audio==0.4.7`) already contains a full STT subsystem that nothing in MOT Deck currently uses.

```
data/mlx-venv/bin/mlx_audio.stt.generate          ← console script, already installed
data/mlx-venv/lib/python3.12/site-packages/mlx_audio/stt/models/
  canary  cohere_asr  fireredasr2  fun_asr_nano  glmasr  granite_speech
  lasr_ctc  mega_asr  mms  moonshine  nemo  nemotron_asr  parakeet
  qwen2_audio  qwen3_asr  sensevoice  voxtral  voxtral_realtime  wav2vec  whisper
```

`mlx_audio/stt/models/parakeet/` is a complete implementation — `conformer.py`, `rnnt.py`, `ctc.py`, `tokenizer.py`, with `ParakeetTDT`, `ParakeetRNNT`, `ParakeetCTC`, `ParakeetTDTCTC` classes. The upstream docs confirm the intended invocation ([mlx-audio Parakeet docs](https://blaizzy.github.io/mlx-audio/models/stt/parakeet/)).

### 1.1 The argv is a near-twin of ours

Read from `mlx_audio/stt/generate.py::parse_args` in our venv:

```
mlx_audio.stt.generate --model <path> --audio <file> --output-path <prefix>
                       --format json [--language en] [--stream]
                       [--chunk-duration 30.0] [--gen-kwargs '{...}']
```

Compare our current `stt_argv()` (bridge/voice.py:843):

```
mlx_whisper <audio> --model <path> -f json -o <dir> --verbose False
```

Both write a file, neither prints the transcript usefully. Crucially — `save_as_json()` writes to **`f"{output_path}.json"`**, so passing `--output-path <out_dir>/<stem>` produces exactly `<out_dir>/<stem>.json`, which is **precisely the path `stt_read_output(out_dir, stem)` already looks for** (bridge/voice.py:957).

And the payload: for Parakeet, `save_as_json` emits `{"text": ..., "sentences": [...]}`; for Whisper `{"text": ..., "segments": [...]}`. `stt_text_from_payload()` (bridge/voice.py:933) reads `payload["text"]` first — **so it works unchanged for both.** The `sentences` fallback branch is never reached because `text` is always present.

> **This is the cleanest integration seam I have seen in this codebase.** The entire engine swap is a new branch in one pure function plus a new format string.

### 1.2 No ffmpeg needed for our path

`mlx_audio/audio_io.py` header, verbatim:

```
- Reading: Uses miniaudio to support WAV, MP3, FLAC, and Vorbis formats.
           Uses ffmpeg for M4A/AAC, OGG, Opus, and WebM format support.
```

`conv`/`auto` mode already encodes **16 kHz mono WAV client-side** (`wavFromPcm`). WAV → miniaudio → **no external binary**. This preserves the existing "a wav needs no external tool at all" property. (Manual `● talk` via MediaRecorder produces mp4/webm and *would* need ffmpeg — same as today.)

### 1.3 Model loading works even though the config has no `model_type`

Worth flagging because it looks fragile and isn't. NeMo-format `config.json` files omit `model_type`; `ModelConfig.from_dict` injects `"parakeet"` (comment in `parakeet.py:114-128`). And independently, `get_model_class()` (mlx_audio/utils.py:279-296) falls back to **dash-split name-part matching** against the `stt/models/` directory listing — so a local dir named `parakeet-tdt-0.6b-v3` resolves via the `parakeet` token even with a bare config.

**But this cuts against our classifier** — see §5.1. That is the one piece of real integration work.

### 1.4 Streaming exists

`Model.generate(..., stream=True)` returns a generator of `StreamingResult`, with `chunk_duration` (default 5.0 s for streaming) and `overlap_duration` (1.0 s). Not needed for v1 — our architecture is per-utterance — but it is the door to true streaming ASR later without changing engines again.

---

## 2. Candidate comparison

| Engine | License (code / weights) | Runtime | Fits `data/mlx-venv`? | English quality | Silence behaviour | Streaming | Verdict |
|---|---|---|---|---|---|---|---|
| **Parakeet TDT 0.6B v3** (via mlx-audio) | mlx-audio MIT / weights **CC-BY-4.0** ([nvidia card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3), [mlx-community](https://huggingface.co/mlx-community/parakeet-tdt-0.6b-v3)) | **MLX** | ✅ **already there** | Top of HF Open ASR Leaderboard for English; 25 EU languages | **Emits empty** (RNNT/TDT) | ✅ `stream=True` | **🥇 ADOPT** |
| `parakeet-mlx` (senstella) | Apache-2.0, standalone pkg ([PyPI](https://pypi.org/project/parakeet-mlx/), [GitHub](https://github.com/senstella/parakeet-mlx)) | MLX | new dep, **requires ffmpeg** for its CLI | same weights | same | ✅ | ❌ **Redundant** — mlx-audio gives the same model with no new pin and no ffmpeg |
| **whisper-base** (current default) | MIT / MIT | mlx-whisper (**pulls torch**, ~2 GB) | ✅ installed | Weakest whisper; poor on names/accents | ⚠️ **Hallucinates** phrases | ❌ | Keep as fallback only |
| **whisper-large-v3-turbo** | MIT / MIT | mlx-whisper | ✅ | Much better than base | ⚠️ hallucinates; 1.6 GB load | ❌ | Quality option, but slower + still hallucinates |
| **Moonshine v2 streaming** | permissive, **ONNX** ([arXiv 2602.12241](https://arxiv.org/abs/2602.12241), [HF](https://huggingface.co/moonshine-ai/moonshine-streaming-tiny)) | **onnxruntime** — not MLX | ❌ new runtime + new venv | good for size | good | ✅ native streaming | ⏸️ **Interesting later.** ONNX-on-CPU is a different discipline from our MLX/Metal stack. mlx-audio *has* a `moonshine` dir — worth a look if v2 lands there |
| **whisper.cpp** | MIT | separate C++ binary | ❌ new binary + new pin | = whisper | ⚠️ hallucinates | ✅ | ⏸️ Only merit is dropping torch. A whole llama.cpp-style pin+bump lane for no accuracy gain |
| Canary / Voxtral / Qwen3-ASR (in mlx-audio) | varies — **check per-model, several are NC** | MLX | ✅ | Canary is strong | varies | varies | ⏸️ Not now. Voxtral was already rejected on licence for TTS |
| Kyutai / mimi-based STT | — | torch-heavy | ❌ | — | — | ✅ | ❌ Full-duplex research stack; wrong shape for us |

### 2.1 Adversarial note on the benchmark claims

Third-party numbers circulating: *"parakeet-mlx 0.4995 s avg latency per sample vs mlx-whisper large-v3-turbo 1.0230 s"* and *"117× real-time"* ([mac-whisper-speedtest](https://github.com/anvanvan/mac-whisper-speedtest), [Soniqo benchmarks](https://soniqo.audio/benchmarks)). **Treat these as directional only:**

- They compare against **large-v3-turbo**, not our **base**. whisper-base is ~10× smaller than turbo; on raw inference base may well be *faster* than Parakeet 0.6B.
- "117× real-time" is a throughput figure over long files. It says nothing about the **fixed cost per invocation**, which is what a 3-10 s utterance is dominated by.
- The Open ASR Leaderboard that Parakeet tops is heavy on **read** English speech. Conversational, near-field, accented dictation is a different distribution. Parakeet's lead is real but narrower than the marketing implies.
- One widely-shared post ([arunbaby.com](https://www.arunbaby.com/speech-tech/0073-whisper-vs-parakeet-asr-decision/)) argues *against* Parakeet for production pipelines, largely on language coverage and ecosystem maturity. For English dictation on one Mac, those objections do not bite.

**The honest case for Parakeet here is not the benchmark. It is (a) zero adoption cost and (b) no silence hallucination.**

---

## 3. The real latency budget — and why an engine swap barely moves it

### 3.1 Where the time actually goes in `conv` mode

Per conversational turn, in order:

| Phase | Cost | Owner |
|---|---|---|
| User stops speaking → VAD closes the utterance | **800 ms** (`VAD_HANGOVER`) | **OURS** |
| WAV encode + POST | ~10-30 ms | ours, negligible |
| STT one-shot subprocess | **~750-900 ms** measured | mostly **ours** (see §3.2) |
| LLM generation (TTFT + stream) | seconds, model-dependent | runner |
| TTS first render | 5-15 s cold, **instant on cache hit** | OmniVoice |
| Playback | length of reply | — |
| Grace + segmenter re-arm warm-up | 300 ms + **600 ms** | **OURS** |

**User-perceived delay between "I stopped talking" and "the reply starts generating" ≈ 1.7 s, and ~1.6 s of it is ours, not the engine's.**

The 600 ms warm-up sits *after* playback, so it delays the next capture rather than the reply — but in a back-and-forth conversation the user feels it as "the mic is deaf for half a second after it stops talking."

### 3.2 Decomposing the 0.9 s

The one-shot path pays, every single utterance:

1. `posix_spawn` a Python interpreter — ~30-50 ms
2. `import mlx.core` + `import mlx_whisper` (and transitively numpy, and for mlx-audio, more) — **~300-500 ms**, CPU-bound bytecode + dylib init
3. Read + materialise the model weights — whisper-base 139 MB → ~100-200 ms warm
4. Metal kernel setup / first-op JIT — variable
5. **Actual inference** on a 3-10 s clip — likely only ~150-300 ms for base

That puts **fixed overhead at roughly 0.5-0.7 s of the measured 0.75-0.9 s.** Inference is the minority term.

### 3.3 ⚠️ Challenge to the recorded Gate-2 conclusion

CLAUDE.md records:

> *"GATE 2 RESULT: whisper-base one-shot = 0.90 s run1 / 0.75 s run2 — cold start does NOT dominate; auto-dictation v1 rides the EXISTING one-shot /api/voice/stt, NO persistent STT worker needed."*

**That inference does not follow from that observation.** `run2 ≈ run1` shows only that the **OS page cache** does not help much. It is *equally* consistent with a large **constant** overhead — because `import mlx` is CPU work re-done from scratch in a fresh interpreter every time, and the page cache cannot make it cheaper. Both hypotheses predict `run2 ≈ run1`. The experiment cannot distinguish them.

The decision it justified (ride the one-shot endpoint for v1) was still the **right call** — v1 shipped, it works, and a resident STT model would have been premature. But the stated *reason* is not established, and it should not be carried forward as settled fact into the persistent-worker decision.

### 3.4 The corrected Gate 2 — the measurement that actually decides R6

Run **in one process**, from the SNAPSHOT dir (`~/Library/Application Support/MOT Deck`), timing a load-once/transcribe-twice:

```
data/mlx-venv/bin/python - <<'PY'
import time
t0=time.time()
from mlx_audio.stt.utils import load_model
t1=time.time()
m = load_model("<path to parakeet or whisper model dir>")
t2=time.time()
from mlx_audio.stt.generate import generate_transcription
for i in range(3):
    t=time.time()
    generate_transcription(model=m, audio="<some 5s .wav>", output_path="/tmp/x", format="json")
    print(f"infer {i}: {time.time()-t:.3f}s")
print(f"import {t1-t0:.3f}s  load {t2-t1:.3f}s")
PY
```

Then compare **`import + load`** against **steady-state `infer`**.

- If `import + load` ≫ `infer` (expected) → **a persistent worker is the only thing that meaningfully cuts STT latency**, and it would take ~0.9 s down to ~0.2-0.3 s. R6 becomes worth building.
- If they are comparable → the one-shot path is near-optimal and R6 should be dropped.

**Run this before committing to R6. It is a five-minute test that decides a medium-sized slice.**

### 3.5 So where does the next 500 ms come from? — plainly

**Not from the engine.** Ranked by return-on-risk:

1. **Noise-floor caching across listening windows (R4) — up to 600 ms, near-zero risk.** The `vadInit` reset on re-arm is correct in intent (it prevents resuming mid-utterance from before the gate) but it is doing *two* things: clearing the frame buffer **and** discarding the learned noise floor. Only the first is load-bearing. Carry the floor forward and the warm-up can be cut to near zero for the 2nd..Nth window of a session. Keep the full 600 ms warm-up for the *first* window only.
2. **`VAD_HANGOVER` 800 → 550-600 ms (R5) — 200-250 ms, small risk.** The 800 ms was tuned around Whisper's need for trailing silence and its hallucination behaviour. Parakeet does not need that margin. **Do this only after R1 lands**, and ear-test it — a hangover that is too short splits utterances, and in `conv` mode a split *sends two messages*.
3. **Persistent STT worker (R6) — up to ~600 ms, medium risk + ledger cost.** Gated on §3.4.
4. **Engine swap alone — approximately 0 ms.** Parakeet 0.6B is *larger* than whisper-base; its steady-state inference is likely a wash or slightly worse, and its cold load is worse (1.2 GB bf16 vs 139 MB). **Adopt it for accuracy and silence behaviour, not for speed.**

> **Combined realistic win: ~800 ms per turn (R4 + R5), with no new dependency and no resident model.** That is more than the "next 500 ms" the brief asked about, and it comes entirely from our own constants.

### 3.6 The silence-hallucination argument, stated properly

This is the strongest reason to move, and it is a **correctness** argument.

Whisper is a sequence-to-sequence model with a language-model decoder trained on 30 s windows. On silence or non-speech it reliably emits high-frequency training artifacts — "Thank you.", "Bye.", subtitle credits. This is a well-known, extensively documented failure mode.

CLAUDE.md already records the two mitigations built around it: the segmenter keeps only a **200 ms tail** ("800 ms of trailing silence is exactly what makes whisper hallucinate") and an **empty transcript is silently skipped** as "the second line of defence."

But in `conv` mode the consequence of a false positive escalated: **a hallucinated transcript is not appended to a box the user can edit — it is auto-sent as a message and answered aloud.** The recorded honest limit ("loud NON-speech can still open an utterance, and in conv mode that now SENDS a message") is *exactly* the case where Whisper is at its worst, because the empty-transcript guard is precisely the guard Whisper defeats.

Parakeet is a Conformer encoder with an RNNT/TDT transducer decoder. It has no autoregressive text prior to fall back on and emits nothing when there is no speech. **It converts "phantom message sent" into "empty transcript, skipped" — which is the behaviour the design already assumes.**

---

## 4. Recommended engine ranking

1. **🥇 Parakeet TDT 0.6B v3 via mlx-audio** — `mlx-community/parakeet-tdt-0.6b-v3` (CC-BY-4.0). Already installed. No hallucination. Best English accuracy. Streaming available later. **Pin: nothing new** — it rides the existing `build.mlx_audio_pin: 0.4.7`.
2. **🥈 whisper-large-v3-turbo** — keep offered as a quality alternative for users who need whisper's 99-language coverage. Already a curated starter.
3. **🥉 whisper-base** — demote from default to fallback. Keep because it is 139 MB and works on a machine with no room.
4. **⏸️ Moonshine v2** — revisit if/when mlx-audio's `moonshine` module supports the v2 streaming checkpoints. Do not add an onnxruntime lane for it now.
5. **❌ parakeet-mlx (standalone), whisper.cpp** — strictly worse trades given R1.

### 4.1 What to pin

**Nothing.** That is the point. `mlx_audio==0.4.7` is already pinned in `install_mlx.sh`. The model is a download like any other. Optionally add a curated Audio-tab starter card:

```
mlx-community/parakeet-tdt-0.6b-v3   ~1.2 GB   CC-BY-4.0   stt-parakeet
mlx-community/parakeet-tdt-0.6b-v3-8bit (if it exists)  ~600 MB
```

Attribution required by CC-BY-4.0 — must appear on the card (see §6.3).

---

## 5. Integration notes (the actual work)

### 5.1 ⚠️ The classifier is the hard part, not the argv

`scripts/seed_registry.py::is_mlx_whisper_config` **requires** the 11-key Whisper `ModelDimensions` shape (`n_mels`, `n_audio_state`, `n_audio_head`, `n_audio_layer`, `n_vocab`, `n_text_state`). A NeMo/Parakeet `config.json` has **none of these** — it is a completely different schema (encoder/decoder/joint/preprocessor blocks, ~56 KB / 4000 lines for the v3 repo). It also often carries **no `model_type` at all**.

So today, a downloaded Parakeet model would be classified **not-stt-mlx** and silently vanish from the Audio tab. Three places need a new branch:

1. `scripts/seed_registry.py::audio_format_probed` — add an `stt-parakeet` verdict.
2. `bridge/app.py::audio_probe_verdict` (the HF-search probe) — same rule, and its constants are byte-identically test-pinned to seed_registry's, so **both must move together**.
3. `bridge/voice.py::stt_argv` — the new argv branch + `STT_FORMATS`.

**Suggested detection rule, strongest-evidence-first** (mirroring the `voices_from_config` discipline already in the codebase):
- `config["model_type"] == "parakeet"` → `stt-parakeet`; else
- presence of NeMo transducer keys (e.g. `joint` + `decoder` + `encoder` with a `preprocessor` block) → `stt-parakeet`; else
- **last resort**, dash-split dirname contains `parakeet` — this is what mlx-audio itself does, so matching it keeps us consistent with the loader.

Note the **transformers veto must NOT be applied here**. It is currently applied on the ASR lane only, and a NeMo config may legitimately carry keys that look transformers-ish. Applying the veto would condemn every Parakeet repo. (This is the same class of bug the veto was narrowed to avoid for mlx-audio TTS conversions.)

### 5.2 Argv branch

```
stt-parakeet →  [<mlx-venv>/bin/mlx_audio.stt.generate,
                 "--model", <path>,
                 "--audio", <audio_path>,
                 "--output-path", os.path.join(out_dir, stem),
                 "--format", "json"]
```

`stt_read_output(out_dir, stem)` needs **no change**. `stt_text_from_payload` needs **no change**. The exit-0 invariant (empty transcript == failure) should be carried over verbatim and re-asserted by test.

⚠️ **Verify on the Mac:** whether `mlx_audio.stt.generate` also exits 0 on failure. It is a different CLI from `mlx_whisper` and this has not been checked. The invariant may need to become "empty *or* nonzero exit".

### 5.3 Ledger

Parakeet 0.6B bf16 ≈ **1.2 GB** resident vs whisper-base 139 MB. In the one-shot model this is transient and the ledger correctly ignores it. **If R6 (persistent worker) ships, it must count against `memory.budget_gb`** exactly as `_resident_voice_bytes()` does for TTS today, with the same `spawn_guard` 409 path.

### 5.4 Language

Parakeet v3 covers 25 European languages but **not** the ~99 Whisper does. For English dictation this is irrelevant; keep whisper-large-v3-turbo on the starters card so the coverage is still one download away.

---

# Q2 — A licensed starter voice-clip set

*(Research delegated to a sub-agent; findings verified against the cited sources and reproduced here in condensed form. The full source-by-source detail is in §6.5.)*

## 6.1 Source comparison

| Source | Licence | Accents | Native clip len | Quality | Redistribute clips? | Synthesis consent |
|---|---|---|---|---|---|---|
| **VCTK 0.92** | **CC BY 4.0** ([DataShare full record](https://datashare.ed.ac.uk/handle/10283/3443?show=full)) | English(regions), Scottish, NorthernIrish, Irish, Welsh, **American**, Canadian, **Indian**, **Australian**, NZ, SouthAfrican | ~3.6 s mean | **48 kHz FLAC, hemi-anechoic, DPA 4035 — best available** | ✅ with attribution | **Strongest** — recorded *for speaker-adaptive TTS*; corpus is literally the "Voice Cloning Toolkit" corpus |
| GLOBE_V2 | **CC0-1.0** ([HF](https://huggingface.co/datasets/MushanW/GLOBE_V2)) | 164 accent labels | ~5 s | 44.1 kHz, filtered Common Voice | ✅ no obligations | CV = ASR framing |
| Google English Dialects (SLR-83) | CC BY-**SA** 4.0 ([OpenSLR 83](https://www.openslr.org/83/)) | Irish, Scottish, Welsh, N/Mid/S England | ~4-6 s | 48 kHz wav | ⚠️ **ShareAlike infects trimmed clips** | volunteer donation |
| Common Voice | CC0-1.0 | sparse free-text | ~4-6 s mp3 | consumer mics | ✅ | ASR framing |
| LibriVox / LJSpeech | PD (**US-certain only**) | **none labelled** | minutes | 64-128 kbps mp3, home rec | ✅ | ⚠️ named living volunteers; [LibriVox bans AI voices on-platform](https://wiki.librivox.org/index.php?title=Recording_%26_Text_Policies) |
| LibriTTS-R / Hi-Fi TTS | CC BY 4.0 | none / 10 spk | varies | 24-44.1 kHz | ✅ | as LibriVox |
| EARS, Expresso, DAPS, L2-ARCTIC, Speech Accent Archive | **CC BY-NC(-SA)** | (excellent) | — | — | ❌ **NO** | — |
| Kokoro-82M synthetic | model Apache-2.0 | US/UK M+F **only** | any | 24 kHz, dry | ✅ | no human speaker |
| F5-TTS / XTTS / OpenVoice bundled wavs | **undocumented / NC** | — | — | — | ❌ | — |

**There is no curated, provenance-clean "cloning reference pack" shipped by any TTS project. It does not exist.**

## 6.2 Plan A (recommended) — VCTK-13

Concatenate 2-3 consecutive `mic1` utterances per speaker → ~10 s → peak-normalise → 24 kHz mono wav. Store the concatenated transcript as **`ref_text`** — this is *free ground truth* and skips the auto-transcribe round-trip entirely.

| Slot | Speaker | Age/Sex | VCTK accent · region |
|---|---|---|---|
| US-M 1 | **p311** | 21 M | American · Iowa |
| US-M 2 | **p334** | 18 M | American · Chicago |
| US-M 3 | **p345** | 22 M | American · Florida *(alt p360 New Jersey)* |
| US-F 1 | **p294** | 33 F | American · San Francisco |
| US-F 2 | **p339** | 21 F | American · Pennsylvania *(alt p299 CA, p306 NY)* |
| UK-M 1 | **p232** | 23 M | English · Southern England (nearest RP) |
| UK-M 2 | **p243** | 22 M | English · London |
| UK-M 3 | **p287** | 23 M | English · York *(alt p256 Birmingham)* |
| UK-F 1 | **p225** | 23 F | English · Southern England (the canonical VCTK voice) |
| UK-F 2 | **p276** | 24 F | English · Oxford *(alt p267 Yorkshire)* |
| Other 1 | **p245** | 25 M | **Irish** · Dublin *(alt p364 Donegal)* |
| Other 2 | **p252** | 22 M | **Scottish** · Edinburgh *(swap p262, 23 F, for gender balance)* |
| Other 3 | **p376** | 22 M | **Indian** *(swap p248, 23 F, for gender balance)* |

Extras if wanted: p326/p374 (Australian), p335 (NZ), p314 (South African), p253 (Welsh), p302/p303 (Canadian).
Speaker table: [speaker-info.txt mirror](https://raw.githubusercontent.com/OlaWod/PitchVC/main/test/spk_gender/speaker-info.txt).

**Hard exclusions:** `p315` (transcript lost to disk error — no `ref_text` possible), `p280` (accent "Unknown/France", mic2 missing).

## 6.3 Fetch mechanism

The canonical VCTK download is a **10.94 GB zip** with no per-speaker path. Unacceptable for a starter pack.

**Working path:** the HF datasets-server serves individual clips from the `sanchit-gandhi/vctk` parquet mirror:

```
GET https://datasets-server.huggingface.co/rows
    ?dataset=sanchit-gandhi%2Fvctk&config=default&split=train&offset=<N>&length=<K>
```

Each row carries `speaker_id`, `text`, `accent`, `region`, `gender`, the original `wav48_silence_trimmed/pNNN/pNNN_NNN_micX.flac` path, and `audio[0].src` = a signed HTTPS URL to a 48 kHz FLAC. `num_rows_total` = 88,156 (mic1 + mic2 interleaved, speaker-ordered).

**Verified constraints — build against these:**
- Signed URLs **expire** (`?Expires=&Signature=`). Fetch-metadata-then-download in one pass; never hardcode.
- `/filter?where=` returned an **empty body** for this dataset in repeated tests. Do not depend on it — page `/rows` by offset (rows are speaker-ordered, so build an offset index once and cache it).
- Prefer `_mic1.flac` (DPA 4035 omni) — universal convention in TTS recipes.
- The datasets-server is a convenience service, **not a CDN contract**. It rate-limits; assets are ephemeral. Degrade gracefully with honest error text.

Fallback: `hf_hub_download` a parquet shard, or DuckDB over `hf://datasets/sanchit-gandhi/vctk/**/*.parquet`.

**Total payload: 13 × ~200 KB ≈ 3 MB.** Small enough to ship, but **fetch-on-demand is preferable** so provenance is re-verified at fetch time — and it keeps a third-party mirror out of our repo.

**Where they live:** `data/voices/starter/` — a subdir of the existing library so the clip picker finds them with no new code. ⚠️ Fable's call whether the picker should visually distinguish starter clips from user recordings (the picker currently shows bare stems).

**Delivery mechanism:** a `scripts/fetch_starter_voices.sh` in the `ensure_*.sh` idiom (idempotent, non-fatal, print-path-on-stdout) is a better fit than the bridge download manager — the download manager is built around whole-HF-repo model downloads with a registry entry at the end, and 13 loose wavs are not a model.

## 6.4 Licence text to display on the card

```
Reference voice clips (VCTK)
────────────────────────────
Source:    CSTR VCTK Corpus: English Multi-speaker Corpus for CSTR
           Voice Cloning Toolkit (version 0.92)
Authors:   Junichi Yamagishi, Christophe Veaux, Kirsten MacDonald
Publisher: University of Edinburgh, The Centre for Speech Technology
           Research (CSTR), 2019
DOI:       https://doi.org/10.7488/ds/2645
Licence:   Creative Commons Attribution 4.0 International (CC BY 4.0)
           https://creativecommons.org/licenses/by/4.0/

Changes made: individual utterances were extracted, concatenated into
~10-second single-speaker excerpts, loudness-normalised and resampled.
No other modification.

The University of Edinburgh and the corpus authors do not endorse this
software or any audio it generates.
```

Plus, next to any generated audio:

```
Voices in this list are AI-generated. Reference clips come from open
speech corpora whose speakers were recorded for speech-synthesis
research, or are machine-generated and depict no real person.
Audio licences do not grant voice, likeness or publicity rights — do
not use these voices to impersonate any real person.
```

For Parakeet (CC-BY-4.0) on the Audio tab:
```
Parakeet TDT 0.6B v3 — © NVIDIA, CC BY 4.0
https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
```

## 6.5 Ethics — the one point that must not be glossed

**A CC BY / CC0 / public-domain licence gives you the right to copy the recording. It does not give you the right to impersonate the person in it.** Creative Commons says so in its own deed: the licence covers copyright and similar rights, and *"other rights such as publicity, privacy, or moral rights may limit how you use the material"* ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)).

- **Tennessee ELVIS Act** (effective 1 Jul 2024) makes **voice** an explicitly protected property right, covers *simulations* of a voice, and uniquely reaches **the providers of tools** used to make unauthorised simulations ([Holland & Knight](https://www.hklaw.com/en/insights/publications/2024/04/first-of-its-kind-ai-law-addresses-deep-fakes-and-voice-clones)). Federal NO FAKES / No AI FRAUD are still bills.
- **EU AI Act Art. 50** deepfake-disclosure obligations apply **from 2 August 2026** ([artificialintelligenceact.eu/article/50](https://artificialintelligenceact.eu/article/50/)). Whether a purely personal, non-professional local tool falls outside it is **genuinely unresolved** — I will not pretend otherwise. Practical read: private local playback is not the target; anything *published* is.

**Risk ladder:**

| Practice | Risk |
|---|---|
| Local generation from a **synthetic** seed, never published | Negligible |
| Local generation from a **VCTK** clip, never published | **Low** |
| Ship 13 VCTK clips with correct CC BY attribution | **Low** — expressly permitted |
| Ship CC BY-SA clips trimmed/normalised | Medium — likely an adaptation ⇒ SA attaches |
| Ship CC BY-NC clips | **Do not** |
| Clone a named LibriVox volunteer and publish | Medium-high |
| Clone a public figure | **High** |

**Proposed norm:** ship only sources whose speakers were recorded *for speech synthesis* (VCTK) or who waived copyright explicitly (CC0), and whose licence permits redistribution; never NC, never SA-for-adaptations; offer a synthetic generator as a first-class alternative; show licence + speaker ID in the UI next to every bundled clip.

## 6.6 Plan B — synthetic Kokoro seeds

Generate slots 1-10 locally from Kokoro-82M (Apache-2.0, already a curated starter), ~12 s of neutral prose each — `af_bella` (A-), `af_heart` (A), `bf_emma` (B-), `bf_isabella`, `am_michael`/`am_fenrir`/`am_puck` (C+), `bm_george`/`bm_fable` (C), `bm_lewis` (D+) per [VOICES.md](https://huggingface.co/hexgrad/Kokoro-82M/raw/main/VOICES.md). **Avoid `am_adam` — graded F+.**

**Slots 11-13 cannot be filled synthetically** — Kokoro has no Irish, Scottish, Australian, or Indian-English voices.

**Honest assessment of whether synthetic seeds work as cloning references:** mechanically yes, empirically **unverified**. The favourable evidence is real — zero-shot TTS *"tend[s] to preserve the acoustic environment of the audio prompt, leading to degradation … when the audio prompt contains noise"* ([arXiv 2406.05699](https://arxiv.org/pdf/2406.05699)), and a dry synthetic prompt has no room to inherit. The counter-arguments are also real: you are cloning a vocoder's output with another vocoder; synthetic voices may not sit where real speakers sit in the cloner's speaker-embedding space; and **no published benchmark of TTS-output-as-cloning-reference could be found.** Settle it with an A/B on the Mac before claiming either way.

---

## 7. Three biggest uncertainty flags

1. **The Gate-2 conclusion in CLAUDE.md is not supported by its own evidence (§3.3).** `run2 ≈ run1` is equally consistent with "cold start dominates" and "cold start is irrelevant", because `import mlx` is CPU work the page cache cannot help. The v1 decision it justified was still correct, but the **persistent-worker decision must not inherit it** — run the in-process measurement in §3.4 first.
2. **Whether `mlx_audio.stt.generate` honours the exit-0 invariant is UNVERIFIED.** Our entire STT error model rests on "empty transcript IS the failure signal", derived from `mlx_whisper`'s behaviour. `mlx_audio.stt.generate` is a *different* CLI from a *different* package. If it exits nonzero on failure the invariant needs widening; if it exits 0 and writes a zero-byte json, the existing `getsize > 0` check saves us. **Cannot be tested in the sandbox — mlx is Apple-only.**
3. **VCTK's shipped `license_text.txt` could not be read** (DataShare's bitstream URL returned an empty body). The authoritative DataShare `dc.rights` field says CC BY 4.0 and the HF mirror agrees, but **read the shipped file locally before treating the §6.4 attribution block as final.** Related: VCTK's *consent forms* are not published — "speakers consented to cloning" is a strong inference from the corpus's stated purpose and name, **not a documented grant**, and should not be overstated to the user.

**Runners-up worth recording:** the HF datasets-server is a convenience service that rate-limits, expires its URLs, and silently failed `/filter` in testing — a fetch script built on it needs a real fallback; `sanchit-gandhi/vctk` is a third-party mirror not verified byte-for-byte against CSTR's zip; and every accent label in every corpus here is **self-reported**, so all 13 picks need an ear check before being pinned as starters.

---

## Sources

**STT:** [senstella/parakeet-mlx](https://github.com/senstella/parakeet-mlx) · [parakeet-mlx PyPI](https://pypi.org/project/parakeet-mlx/) · [mlx-audio Parakeet docs](https://blaizzy.github.io/mlx-audio/models/stt/parakeet/) · [nvidia/parakeet-tdt-0.6b-v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) · [mlx-community/parakeet-tdt-0.6b-v3](https://huggingface.co/mlx-community/parakeet-tdt-0.6b-v3) · [mac-whisper-speedtest](https://github.com/anvanvan/mac-whisper-speedtest) · [Soniqo benchmarks](https://soniqo.audio/benchmarks) · [Whisper vs Parakeet — a dissenting view](https://www.arunbaby.com/speech-tech/0073-whisper-vs-parakeet-asr-decision/) · [Moonshine v2 (arXiv 2602.12241)](https://arxiv.org/abs/2602.12241) · [moonshine-streaming-tiny](https://huggingface.co/moonshine-ai/moonshine-streaming-tiny) · plus direct source reads of `data/mlx-venv/.../mlx_audio/stt/{generate.py,utils.py,models/parakeet/parakeet.py}`, `mlx_audio/audio_io.py`, `mlx_audio/utils.py`, and `bridge/voice.py`.

**Voices:** [VCTK DataShare (full record)](https://datashare.ed.ac.uk/handle/10283/3443?show=full) · [VCTK HF card](https://huggingface.co/datasets/CSTR-Edinburgh/vctk/blob/main/README.md) · [VCTK speaker-info.txt](https://raw.githubusercontent.com/OlaWod/PitchVC/main/test/spk_gender/speaker-info.txt) · [tfds vctk.py accent labels](https://github.com/tensorflow/datasets/blob/master/tensorflow_datasets/audio/vctk.py) · [GLOBE_V2](https://huggingface.co/datasets/MushanW/GLOBE_V2) · [ylacombe/english_dialects](https://huggingface.co/datasets/ylacombe/english_dialects) · [OpenSLR 83](https://www.openslr.org/83/) · [LREC 2020 British Isles corpora](https://aclanthology.org/2020.lrec-1.804/) · [LibriTTS-R (SLR 141)](https://www.openslr.org/141/) · [Hi-Fi TTS (SLR 109)](https://www.openslr.org/109/) · [LibriVox public domain](https://librivox.org/pages/public-domain/) · [LibriVox recording policies](https://wiki.librivox.org/index.php?title=Recording_%26_Text_Policies) · [LibriVox API](https://librivox.org/2011/04/28/librivox-api-opds/) · [LJSpeech](https://keithito.com/LJ-Speech-Dataset/) · [Common Voice CC0](https://www.mozillafoundation.org/en/blog/common-voice-18-dataset-release/) · [EARS](https://github.com/facebookresearch/ears_dataset) · [Expresso](https://huggingface.co/datasets/ylacombe/expresso) · [DAPS](https://huggingface.co/datasets/corvj/daps) · [L2-ARCTIC](https://huggingface.co/datasets/KoelLabs/L2Arctic) · [Speech Accent Archive](https://accent.gmu.edu/) · [Kokoro VOICES.md](https://huggingface.co/hexgrad/Kokoro-82M/raw/main/VOICES.md) · [F5-TTS](https://github.com/SWivid/F5-TTS) · [F5-TTS licensing discussion](https://github.com/SWivid/F5-TTS/discussions/997) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) · [ELVIS Act — Holland & Knight](https://www.hklaw.com/en/insights/publications/2024/04/first-of-its-kind-ai-law-addresses-deep-fakes-and-voice-clones) · [EU AI Act Art. 50](https://artificialintelligenceact.eu/article/50/) · [Noise robustness in zero-shot TTS (arXiv 2406.05699)](https://arxiv.org/pdf/2406.05699)
