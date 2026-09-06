# OmniVoice provenance — which one are we using, and does it differ?

Research, 2026-08-14 (Opus-5 research agent, Fable brief). Sources cited inline.
NO code changed. Debi's question: *"Which of the omnivoices did we use, and are there
any differences? It seems the k2-fsa is the real one but I might be wrong."*

## Short answer

**Debi is right: `k2-fsa/OmniVoice` IS the original.** Everything else — including
what MOT Deck runs and what VoiceStudio runs — is the *same weights* in a
different container. There is exactly ONE OmniVoice model in this story.

- **k2-fsa** = the Kaldi / next-gen-Kaldi ("k2-fsa") speech research org (Daniel
  Povey et al., the sherpa-onnx / icefall people). They published OmniVoice on
  2026-03-30: paper [arXiv:2604.00688](https://arxiv.org/abs/2604.00688), code
  [github.com/k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice), weights
  [huggingface.co/k2-fsa/OmniVoice](https://huggingface.co/k2-fsa/OmniVoice)
  (819k downloads, 1264 likes — it is the real, upstream, widely-used thing).
- Architecture: a **bidirectional Qwen3-0.6B** backbone (`base_model: Qwen/Qwen3-0.6B`
  in the HF card) doing **diffusion-LM-style iterative masked decoding** into 8-codebook
  acoustic tokens, decoded by the **HiggsAudioV2** tokenizer at 24 kHz. 613M params.
  581k-hour open-source multilingual training set, 600+ (646) languages, RTF ~0.025.
- It ships **PyTorch safetensors only** — `model.safetensors` (2.45 GB) +
  `audio_tokenizer/model.safetensors` (806 MB). **There is NO official ONNX build.**
  (Our CLAUDE.md note calling the cached copy "the k2/onnx build" is **wrong** —
  it is the plain PyTorch checkpoint. Community ONNX exports exist as HF Spaces only.)

## The lineage of what we run

| Repo | What it is | dtype / size | Tags |
|---|---|---|---|
| `k2-fsa/OmniVoice` | **the original** | F32, 3.27 GB total | `library_name: omnivoice`, no licence tag |
| `mlx-community/OmniVoice-bf16` | earliest MLX upload, 2026-04-03, bare (no README, no card) | BF16 | 363 dl, 9 likes |
| `theoracleguy/OmniVoice-bf16` | 2026-04-16, `library_name: mlx-audio` | BF16, 1.38 GB | 1152 dl — the most-downloaded MLX copy |
| `mlx-community/OmniVoice` | 2026-05-15, **F32** despite the plain name | F32, 3.27 GB | `base_model: k2-fsa/OmniVoice` |
| `mlx-community/OmniVoice-bfloat16` | 2026-05-15, what mlx-audio's own README **recommends** | BF16, 2.04 GB | same |
| `-fp32`, `-8bit`, `-4bit` | quantised siblings, same day | — | (the `-4bit` repo carries an `8-bit` tag — upstream mislabel) |

All of the MLX repos declare `base_model: k2-fsa/OmniVoice` and report **exactly
612,577,280/288 parameters** — the same number as the original. So they are a
**format conversion, not a fork**: `mlx_audio/tts/models/omnivoice/convert.py`'s
docstring literally says *"Convert k2-fsa/OmniVoice weights to mlx-audio format"*,
and the remap is mechanical (split the fused `audio_embeddings`/`audio_heads` per
codebook, rename `llm.*` → `backbone.*`, cast dtype). **No retraining, no
fine-tuning, no different data.** Differences between them are dtype/quantisation
only (fp32 → bf16 → 8/4-bit), i.e. size and a small amount of numerical precision.

`theoracleguy/OmniVoice-bf16` is not a different model — it is another person's
bf16 conversion of the same checkpoint (and the one with the most downloads simply
because it landed two weeks earlier than the mlx-community set).

## What VoiceStudio does with it

VoiceStudio (AGPL-3.0) runs **the same k2-fsa checkpoint**, as its **default engine**,
through its own bundled PyTorch `omnivoice/` code on **MPS** on Apple Silicon — not
through sherpa-onnx (sherpa-ONNX is a *separate, opt-in* engine in its 14-engine
matrix, for other models). Its acknowledgments credit
["VoiceStudio (k2-fsa)" → github.com/k2-fsa/OmniVoice](https://github.com/debpalash/VoiceStudio)
as "the core voice synthesis model". It also lists a lazy **"OmniVoice GGUF"** engine
(CPU) — same model again, third container.

So `K2-fsa/OmniVoice` in the HF cache is VoiceStudio's own copy of the upstream
PyTorch weights. mlx-audio cannot load that directory as-is, **but `convert.py`
accepts a local directory** (`--model <path>`), so that 3.3 GB in the cache is
convertible rather than dead weight — we would not need to re-download.

**"800+ voices" is not a model capability.** VoiceStudio's Voice Gallery is a
CDN-loaded content repo ([debpalash/omnivoice-gallery](https://github.com/debpalash/omnivoice-gallery))
of two item types: `preset` = *"a validated `instruct` string"* (e.g.
`"female, middle-aged, low pitch, british accent"`), and `voice` = a
community-contributed **reference clip** hosted as a GitHub Release asset. The k2
model ships **zero** named voices — it has no speaker table at all. This matches
what MOT Deck already found the hard way (voice identity comes only from
`ref_audio`, or from `instruct`).

## Capability comparison: our MLX path vs the k2 original

Read from the installed venv (`mlx_audio/tts/models/omnivoice/`, pin 0.4.7).

| Capability | k2 original | our MLX path |
|---|---|---|
| Voice cloning (`ref_audio` + optional `ref_text`) | ✅ | ✅ (encode runs on **PyTorch CPU**, ~0.5 s per 1 s of audio; decode in MLX) |
| Voice design (`instruct`: gender/age/pitch/whisper/accent/dialect) | ✅ | ✅ — `instruct` is threaded into the prompt as `<\|instruct_start\|>…<\|instruct_end\|>` (omnivoice.py:192) |
| Auto voice (no prompt → random voice) | ✅ | ✅ (and this is exactly the "different voice every render" Debi saw) |
| 646 languages / `language` tag | ✅ | ✅ |
| Non-verbal tags (`[laughter]`, `[sigh]`…), pinyin + CMU pronunciation control | ✅ | Text-level features, so they should pass through — **untested by us** |
| `speed` factor | ✅ | ✗ — MLX exposes `duration_s` + an internal duration estimator instead |
| Whisper auto-transcribe of the reference | ✅ | ✅ (this is the whisper-large-v3-turbo load MOT Deck now avoids by storing `ref_text`) |
| Batch / multi-GPU inference CLI | ✅ | batch API exists (`generate_batch`), no multi-GPU (irrelevant on a Mac) |
| Training / fine-tuning | ✅ | ✗ (inference only) |
| Runs on Apple GPU without PyTorch in the hot path | ✗ (MPS via torch) | ✅ — this is the whole reason we use MLX |

**No quality claim anywhere says the MLX conversion sounds different.** Same weights;
the only honest quality axes are dtype (bf16 vs fp32 vs 4/8-bit) and `num_steps`.
The **one real functional gap** is `speed`; the one real *cost* is that voice-cloning
encode still needs torch on CPU.

## ⚠️ LICENCE FINDING — MOT Deck's own gate is being defeated

The k2-fsa HF README says, verbatim:

> *"Our code is released under the Apache 2.0 License. **The pre-trained model is
> licensed under the CC-BY-NC** due to constraints from its training data (e.g. Emilia)."*

The `k2-fsa/OmniVoice` repo carries **no licence tag at all**. But every
`mlx-community/OmniVoice*` repo tags itself **`license: apache-2.0`** — which is the
*code* licence, not the weights licence. VoiceStudio's gallery repo asserts a *third*
thing ("OpenRAIL-M (same as the engine)") and its engine matrix says "Built-in".

Consequence for us: our Audio-tab licence badging **DISABLES Get for `cc-by-nc*`**
(that is why Spark-TTS and Voxtral-TTS were rejected), yet OmniVoice came through
**green/enabled** purely because the downstream conversion is mislabelled. Debi's use
is personal so nothing is *broken*, but the policy is currently inconsistent, and any
future "can I sell audio made with this" question has a CC-BY-NC answer, not Apache.
Fable's call whether to (a) note it on the card, (b) add a known-relicence override
table, or (c) leave it.

## Verdict for Debi, plain

We are using **the real OmniVoice** — the same 613M-parameter k2-fsa model, converted
to Apple's MLX format so it runs on the GPU without PyTorch. VoiceStudio is running
that *identical* checkpoint too, just through PyTorch/MPS. There is no "better" or
"more official" OmniVoice to switch to; the differences between the repos are file
format and precision, not the voice. The k2 build can do one thing ours can't
(a `speed` knob, plus training), ours can do one thing theirs can't (native MLX/Metal
inference). Their "800+ voices" is a downloadable library of *voice-design phrases and
reference clips*, not a capability of the model — and because our path supports
`instruct`, those design phrases would work here verbatim.

## Sources

- https://github.com/k2-fsa/OmniVoice (README, master)
- https://huggingface.co/k2-fsa/OmniVoice (+ `/raw/main/README.md`, HF API)
- https://arxiv.org/abs/2604.00688
- https://huggingface.co/api/models?author=mlx-community&search=OmniVoice
- https://huggingface.co/mlx-community/OmniVoice, `-bfloat16`, `-bf16`, `-fp32`, `-8bit`, `-4bit`
- https://huggingface.co/theoracleguy/OmniVoice-bf16
- https://github.com/debpalash/VoiceStudio (README)
- https://github.com/debpalash/omnivoice-gallery (README)
- local: `data/mlx-venv/.../mlx_audio/tts/models/omnivoice/{README.md,convert.py,omnivoice.py,duration.py}`
