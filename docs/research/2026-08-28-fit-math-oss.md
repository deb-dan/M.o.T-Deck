# Fit math in the serious local-LLM projects — the exact formulas, with receipts

**2026-08-28. Deep research for the RAM fit advisor.** Primary sources throughout: upstream code
(llama.cpp master ≈ our b10662, ollama main + v0.5.7, gguf-parser-go), local readable source
(mlx 0.32.0 / mlx-lm 0.31.3 in `data/mlx-venv`, Unsloth Studio vendored at
`~/Library/Application Support/MOT Deck/vendor/unsloth`), and **measurements taken on this machine
today** with our own b10662 `llama-fit-params` binary. Machine of record: Apple M5 Pro, 64 GiB
unified (`hw.memsize` 68719476736), Metal `max_recommended_working_set_size` **55,662,788,608 B =
51.84 GiB (~81% of RAM)**, `iogpu.wired_limit_mb = 0` (system default).

The headline finding up front: **the naive formula is validated to the MiB on this machine when —
and only when — the architecture corrections are applied** (§9 validation table: the hybrid-Mamba
correction alone is a 4× KV error on our own resident models), and **llama.cpp b10662 ships its own
fit engine** (`--fit`, on by default, and a standalone `llama-fit-params` binary we already have in
`data/llamacpp/build/bin/`) that we can shell out to as ground truth for GGUF (§1.6).

---

## 1. llama.cpp itself (what our b10662 actually does)

### 1.1 The memory it logs at load

Every buffer is logged per backend at load; these lines are the *actual allocation*, and Ollama's
current scheduler literally regex-parses them as its source of truth (§2.2). Formats
(ollama `llm/llama_server.go:2700-2712`, matching our binary's output):

```
MTL0_Mapped model buffer size =  1918.35 MiB     (mmap'd weights, Metal)
CPU_Mapped  model buffer size =   308.23 MiB     (host-side tensors: token embeddings etc.)
MTL0 KV buffer size           =  1920.00 MiB     (llama_kv_cache, per memory module)
MTL0 RS buffer size           =    50.25 MiB     (recurrent state — Mamba/hybrid archs)
MTL0 compute buffer size      =   501.00 MiB     (graph scratch, sched_reserve)
CPU output buffer size        =     0.95 MiB     (logits)
```

Plus the aggregate KV line, from `src/llama-kv-cache.cpp` (master):

```cpp
LLAMA_LOG_INFO("%s: size = %7.2f MiB (%6u cells, %3d layers, %2u/%u seqs), K (%s): %7.2f MiB, V (%s): %7.2f MiB\n", ...)
```

(The old single `KV self size` line became this per-cache line after the memory-module refactor;
"cells / layers / seqs" now name every input of the formula below.)

The device line worth parsing on Metal: `llama_prepare_model_devices: using device MTL0 (Apple M5
Pro) (unknown id) - 53083 MiB free` — measured today. "Free" on Metal =
`recommendedMaxWorkingSetSize − currentAllocatedSize`, i.e. the 51.84 GiB ceiling, not total RAM.

### 1.2 The exact KV-cache formula

`src/llama-kv-cache.cpp` creates, per layer that has KV:

```cpp
ggml_tensor * k = ggml_new_tensor_3d(ctx, type_k, n_embd_k_gqa, kv_size, n_stream);
ggml_tensor * v = ggml_new_tensor_3d(ctx, type_v, n_embd_v_gqa, kv_size, n_stream);
```

with `src/llama-hparams.cpp`:

```cpp
uint32_t llama_hparams::n_embd_k_gqa(uint32_t il) const {
    return n_embd_head_k(il) * n_head_kv(il);   // GQA: n_head_kv, NOT n_head
}
```

So the base formula per model is:

```
KV_bytes = Σ_layers [ n_head_kv(il) × (head_dim_k(il) + head_dim_v(il)) ] × kv_cells × bytes_per_elem
```

Critical details our advisor must copy:

- **GQA**: `n_head_kv` from GGUF `<arch>.attention.head_count_kv` (may be a **per-layer array** —
  hybrid archs use 0 for non-attention layers). Never `head_count`.
- **head_dim**: use GGUF `attention.key_length` / `attention.value_length` when present (Qwen3.5
  has key_length 256 while embd/heads = 4096/16 = 256 happens to agree; DeepSeek MLA and others
  do NOT agree) — fall back to `embedding_length / head_count` only when absent.
- **kv_cells**: `n_ctx` padded — `llama-context.cpp`: `cparams.n_ctx = GGML_PAD(cparams.n_ctx, 256)`;
  non-unified caches split per slot and pad each stream to 256.
- **bytes_per_elem** per `--cache-type-k/-v`: f32 4.0, f16/bf16 2.0, **q8_0 1.0625 (34/32)**,
  q5_1 0.75, q5_0 0.6875, q4_1 0.625, q4_0/iq4_nl 0.5625. (Block quants carry scale bytes — Ollama's
  "q8_0 = 1, q4_0 = 0.5" is an under-count; Unsloth's table is exact. `llama-context.cpp` throws
  `"quantized V cache requires Flash Attention"` — without FA, V is f16 regardless of the flag.)
- **n_stream**: 1 when `--kv-unified`, else `n_seq_max` (= `--parallel` slots). Unified shares one
  n_ctx pool across slots; non-unified gives each slot `n_ctx / n_parallel` cells (padded).

### 1.3 SWA (sliding window) — KV does NOT scale with n_ctx on those layers

`src/llama-kv-cache-iswa.cpp`:

```cpp
uint32_t size_swa = GGML_PAD(std::min(size_base, hparams.n_swa*(unified ? n_seq_max : 1) + n_ubatch), 256);
if (swa_full) size_swa = size_base;
```

SWA layers cap at `window + n_ubatch` cells regardless of context; only the non-SWA layers pay full
`n_ctx`. Which layers are SWA comes from the per-arch pattern (`set_swa_pattern`, e.g. Gemma 3 is
5:1 swa:global, gpt-oss alternates). `--swa-full` (help.txt line 35) reverts to full-size and is
the flag that makes naive math "accidentally right". `--ctx-checkpoints N` (b10662, help line 430)
adds N window-sized snapshots per slot on top.

### 1.4 Compute buffers

Sized by reserving a worst-case graph (`llama-context.cpp`: `model.build_graph` +
`ggml_backend_sched_reserve`), then logged as `compute buffer size`. Practically (Unsloth measured
it exhaustively, §6.2): a **flat term** ≈ `n_vocab×n_ubatch×4` (f32 logits) + `4×n_embd×n_ubatch×4`
scratch, plus a **context-linear term**: the FA KQ-mask costs ~`n_ubatch×2` B per context token;
a *quantized* KV cache adds a dequant scratch ≈ `0.74–2.02 × n_embd` B per token. Our own
measurement (§9): the 9B's Metal compute buffer is flat at 501 MiB from 8k through 65k ctx, then
jumps to 1337 MiB at 262k — the "Metal compute spike at long ctx" is real and roughly linear once
the mask dominates.

### 1.5 mmap, Metal, wired — what actually counts against unified memory

- `src/llama-mmap.cpp`: weights map **MAP_SHARED** (+`MAP_POPULATE` prefetch on Linux,
  `POSIX_MADV_WILLNEED` ranges elsewhere). File-backed and clean → the OS *may* evict pages under
  pressure; that's the "mmap paging relief" GGUF has and MLX doesn't.
- Metal (`ggml/src/ggml-metal/ggml-metal-device.m`): the mapped region is wrapped **zero-copy** —
  `newBufferWithBytesNoCopy:... options:MTLResourceStorageModeShared` — and, on macOS ≥ 15,
  registered in an **MTLResidencySet** with `requestResidency`. So while the model is hot, mapped
  weights are GPU-resident and count in `device.currentAllocatedSize`; ggml warns when
  `currentAllocatedSize > recommendedMaxWorkingSetSize`. Practical rule for the advisor: **on
  Apple Silicon, count the full weights against the working-set ceiling (51.84 GiB here), not
  against "free RAM"** — the paging relief is real only for cold layers (e.g. CPU-offloaded MoE
  experts) and on load, not for steady-state decode.
- KV + compute buffers are *allocated* (not file-backed) — always resident, wired while in the
  residency set. This is why Unsloth refuses hand-set over-commit contexts on Metal outright:
  wired pages are not reclaimable, Jetsam can't help, and the documented failure is a **kernel
  panic**, not an OOM error (vendored `core/inference/llama_cpp.py:9979-9982`, citing an M1 Max
  32 GB report).
- b10662 flags: `--mmap/--no-mmap/--mlock` are **deprecated for `--load-mode
  {auto,none,mmap,mlock,mmap+mlock,dio}`** (help.txt lines 87-104; auto = mmap unless a device
  can't). `--no-mmap` = read into allocated (dirty, swappable-not-evictable) memory; `mlock` wires
  it (Darwin hint in llama-mmap.cpp: raise `vm.user_wire_limit`/`vm.global_user_wire_limit`).
  Also new: `--tensor-read-lazy` (per-layer embeddings read from disk on demand).

### 1.6 llama.cpp's own fit engine — ship-blocking discovery

b10662 has a built-in fitter, **on by default** (help.txt lines 157-165): `--fit on`,
`--fit-target MiB` (margin left free per device, **default 1024**), `--fit-ctx` (min context it may
shrink to, **default 4096**; `common_params.fit_params_min_ctx`). `common/fit.cpp`
(`common_params_fit_impl`):

1. loads the model with `mparams.no_alloc = true; load_mode = LLAMA_LOAD_MODE_NONE` — reads real
   tensor/buffer sizes without allocating;
2. targets = `free − margin` per device; if ctx is auto, linearly interpolates ctx between
   `n_ctx_min` and model max to fit;
3. distributes layers back-to-front by regula falsi;
4. **MoE-aware**: first tries all dense weights on GPU with expert tensors
   (`blk\.\d+\.ffn_(up|down|gate_up|gate)_(ch|)exps`) offloaded to CPU, then converts layers back
   to full front-to-back with any surplus.

And we already ship the standalone binary: **`llama-fit-params`** prints fitted args and, with
`--verbose`, the projection: measured today on our Qwen3.5-9B-Q4_0 —
`common_params_fit_impl: projected to use 6167 MiB of device memory vs. 53033 MiB of free device
memory / will leave 46866 >= 1024 MiB free, no changes needed`. **This is a zero-maintenance
oracle for the GGUF side of our advisor** (runs in ~0.3 s, no tensor data read, no allocation).

### 1.7 MoE reality

Nothing in the loader streams experts: a 35B-A3B GGUF's **full expert weights are created as
tensors and become resident** (mmap'd, so resident-on-touch — but routing touches all experts
across a real workload). "Active params" only predict *compute*, never weight residency. The only
levers are placement: `--cpu-moe` / `--n-cpu-moe N` and fit.cpp's exps-to-CPU step above, which
moves expert tensors to host RAM (still consuming *host* memory — on Apple unified, the same pool,
minus the wired ceiling). Advisor rule: **weights term = full file size, always; MoE only changes
where it sits and the GPU/CPU split accounting.** (Ollama got multi-GPU MoE placement wrong for
months — issue #14351.)

---

## 2. Ollama's scheduler and memory predictor

### 2.1 The classic estimator (v0.5.7, `llm/memory.go` + `llm/ggml.go`)

The famous pre-load estimate, verified against tag v0.5.7:

- KV (`llm/ggml.go:363-376`):
  `kv = ctx × block_count × (embd_head_k + embd_head_v) × head_count_kv × bytes_per_elem` —
  the same GQA formula, but **flat across layers** (no SWA, no per-layer arrays, no hybrid) and
  with coarse `bytesPerElement` (`llm/ggml.go:552-561`: q8_0→1, q4_0→0.5, else 2).
- Graph (compute) size: per-arch closed forms in `GraphSize()` (e.g. llama:
  `partialOffload = 4b·embd + max(4b(1+embd+max(ctx,embd)) + embd²·9/16 + 4ctx(b·heads +
  embd_heads·heads_kv), 4b(embd+vocab) + embd·vocab·105/128)`), with fallback
  `graphPartialOffload = GQA() × kv / 6`; on Metal `graphPartialOffload = graphFullOffload`.
- Layer fit loop (`llm/memory.go`): `layerSize = blk.0 size + kv/block_count`; fills GPUs
  back-to-front while `free > overhead(envconfig.GpuOverhead) + used + layerSize`, keeps "one
  layer worth of memory as a buffer", requires `2×layerSize` minimum, projector weights charged
  to GPU 0 (`gpuZeroOverhead = projectorWeights + projectorGraph`).

### 2.2 What Ollama does NOW (main, verified 2026-08) — the big lesson

They largely **gave up on predicting and switched to measuring**, keeping only a deliberately
crude, conservative pre-check:

```go
// llm/llama_server.go:2676-2698
// PredictServerVRAM estimates VRAM usage ... intentionally conservative — it overestimates
weights = stat(modelPath).Size()
kvCache = 2 * layers * kvHeads * headDim * numCtx * 2          // f16, no SWA/MoE/hybrid
return weights + kvCache
```

then **parses llama-server's own buffer-size log lines** (`memoryParsingWriter`,
`llama_server.go:2700-2790`: regexes over `model|KV|compute|output|RS buffer size = N MiB`,
`using device ... N MiB free`, `offloaded X/Y layers to GPU`, and even
`common_params_fit_impl: ... (N overflowing)`) to know the truth per device, classifying
`*_Mapped` as GPU memory except `CPU_Mapped`, stripping `_Mapped/_REPACK/_Private` suffixes.

Margins (server/sched.go, verified at lines shown):

- **80% rule** — don't start a load whose prediction exceeds 80% of free memory
  (`sched.go:549-550: if predictedForLoad > freeMemory*80/100`, and again `:1064`, `:1235`).
- **Batch surcharges** (`:803-804, :906-914`): batch ≥ 2048 → +2 GiB and must fit in **60%** of
  available; ≥ 1024 → +768 MiB and 75%; else no surcharge.
- **mmap host pressure headroom** (`:1255-1258`): `max(8 GiB, totalMemory/10)` kept free of
  mmap'd model bytes before counting on page-cache relief.
- **mmproj**: projector memory + flat **1 GiB** headroom for encoder buffers
  (`llama_server.go:86-87 mmprojOffloadHeadroom = 1<<30`).
- OOM retry ladder: auto-ctx steps down 32768 → 4096 → reject; then evict other models once
  (`reduceAutoNumCtxForLoadOOM`, `oomRetryAttempted`).

### 2.3 Known failure modes (why prediction-only loses)

- SWA models grossly over-estimated until PR #9987 ("Improve memory estimates for sliding window
  attention") — Gemma spillover to CPU for no reason.
- KV over-reservation on new archs: GLM-4.7-flash KV "6 GB where <1 GB is right" (#13789);
  inverted estimates on Qwen 3.6/Gemma 4 multi-GPU (#16310); over-committing VRAM (#11202);
  free-memory over-reporting (#13018); silent f16 fallback when KV quant unsupported by arch
  (#13337 — estimate assumes q8_0, runtime allocates f16).

**Precedent for us**: predict conservatively for admission, *measure from the runner's own logs*
for truth, and keep an explicit band (80%) plus workload surcharges.

---

## 3. LM Studio

Closed-source app, but the shape is public and it is *the* UX precedent for an advisory (not
blocking) verdict:

- **Fit indicators** on each model/quant: "Full GPU Offload Possible" / partial / "Likely too
  large for this machine", recomputed live as the **context-length slider and GPU-offload slider
  move at load time** — the estimate visibly reprices KV per the slider (their 0.3.x blogs and
  docs describe the estimator accounting for context length, flash attention, and vision).
- **Model Loading Guardrails**: a user-configurable strictness setting (App Settings → Hardware):
  Off / Relaxed / Balanced / Strict / Custom (custom threshold in bytes). It gates loads on the
  *estimate*; the GUI offers **"Load anyway"** override — but the CLI/REST (`lms load`, incl.
  `--estimate-only` flag on the beta CLI) has *no override*, a documented pain point
  (lmstudio-bug-tracker #1631, #1544; the settings have even shipped with Relaxed/Strict behavior
  swapped, #128). Their estimator is acknowledged beta and "doesn't fully account for KV-cache
  growth during long generations".
- **mlx-engine** (github.com/lmstudio-ai/mlx-engine, OSS): thin loader over mlx-lm/mlx-vlm; the
  guardrail estimate on the MLX side is essentially weights-size-based + the same context pricing;
  MLX models get no mmap relief (§4), which their "likely too large" verdict treats the same as
  GGUF — a known source of false confidence on the GGUF side and false alarm on MLX.

**Steal**: per-strictness guardrail with user override; live re-estimation under the ctx slider;
"--estimate-only" as an API verb. **Avoid**: advisory in GUI but hard-blocking in API.

---

## 4. MLX (our `data/mlx-venv`: mlx 0.32.0, mlx-lm 0.31.3)

- **Allocation model**: lazy unified memory. Weights load via safetensors and materialize as Metal
  buffers on first eval — **no file-backed mmap relief**: an N-GiB MLX model is N GiB of dirty,
  resident memory for its whole life (swappable only via compressor/swap, at catastrophic decode
  cost). Advisor rule: MLX weights term = Σ safetensors sizes, always fully charged.
- **APIs** (docstrings read from our venv):
  - `mx.get_active_memory()` (excludes cache), `mx.get_cache_memory()`, `mx.get_peak_memory()`;
  - `mx.set_memory_limit(bytes)` — "guideline for the maximum amount of memory ... **defaults to
    1.5× max_recommended_working_set_size**" when Metal is available (over-commit by design;
    exceeding it swaps before erroring);
  - `mx.set_cache_limit(bytes)` — buffer-cache cap, defaults to the memory limit;
  - `mx.set_wired_limit(bytes)` — macOS ≥ 15; "must stay strictly below total memory"; **the
    system ceiling it must not exceed is `iogpu.wired_limit_mb`** (raiseable via
    `sudo sysctl iogpu.wired_limit_mb=N`; 0 = default ≈ 75-81% of RAM);
  - `mx.device_info()` — on this machine:
    `{'max_recommended_working_set_size': 55662788608, 'memory_size': 68719476736, ...}`.
- **What mlx-lm itself does** (local files):
  - `mlx_lm/generate.py:230-266` — `wired_limit()` context manager: if `model_bytes >
    0.9 × max_recommended_working_set_size`, warns, and sets
    `mx.set_wired_limit(max_recommended_working_set_size)` for the generation, restoring after;
  - `mlx_lm/server.py:1889-1890` — the server just sets the wired limit to
    `max_recommended_working_set_size` at startup;
  - generation stats report `peak_memory = mx.get_peak_memory()/1e9` (`generate.py:737,751`) —
    free measured data for our validation loop.
- **KV cache in MLX**: python-side list of per-layer K/V arrays (`mlx_lm/models/cache.py`),
  same GQA math — `n_kv_heads × head_dim × 2 × bytes(dtype)` per token — read
  `config.json:num_key_value_heads/head_dim`; quantized KV via `QuantizedKVCache` (typically
  8-bit, ~1.07 B/elem incl. group scales). `RotatingKVCache` implements SWA-style caps for
  applicable models. No compute-buffer reserve: MLX grows lazily toward `set_memory_limit`,
  so peak > weights+KV by a workload-dependent margin — budget ~10% of weights, and trust
  `get_peak_memory` after first use.
- **The fraction the ecosystem uses**: Unsloth Studio's MLX engine caps at
  `0.85 × max_recommended_working_set_size` (`mlx_inference.py:1408-1426`) and its GGUF Apple arm
  uses the same **0.85** (`llama_cpp.py:3030 _APPLE_UNIFIED_MEMORY_FRACTION`, comment: "Apple
  unified memory is shared with the OS, so tighter than VRAM").

---

## 5. HF ecosystem & GGUF calculators

- **accelerate `estimate-memory`** (docs verified): loads on `meta` device, reports largest layer
  + total per dtype and "Training using Adam" = **4× total** (params + grads + 2 Adam moments) —
  load-only, explicitly *not* inference; they cite EleutherAI's transformer-math "+up to 20% for
  inference". Good for HF-format sanity checks, useless for KV/ctx questions.
- **gpustack/gguf-parser-go** — the best-maintained OSS GGUF estimator (v0.20.x, active CI,
  regression tests against known models; estimation in `file_estimate__llamacpp.go`). Reads
  header-only (works on remote URLs/HF repos), models: weights per offload split, KV per ctx and
  cache type, compute graph, **MoE, mmproj (with `--visual-max-image-size`!), LoRA adapters,
  drafters, SWA (Gemma/Llama-4), RPC/tensor-split multi-device, Apple UMA vs non-UMA**, claims
  ±100 MiB typical accuracy, and even estimates max tokens/s from device FLOPS/bandwidth.
  **Steal its edge-case list wholesale**; it is the external cross-check for our engine
  (`gguf-parser --path model.gguf --ctx-size N --cache-type-k q8_0 --json`).
- **Community**: HF space `hf-accelerate/model-memory-usage`; `Vokturz/can-it-run-llm` (adds GPU
  filter + LoRA configs; classic formula `weights + kv + activations + overhead`);
  KolosalAI/model-memory-calculator (browser-side GGUF header reader — same architecture as our
  `modeltools.py` cursor); dozens of "VRAM calculator" pages, all naive-formula (GQA at best,
  no SWA/MoE/hybrid) — precision theater; do not copy.
- **LocalAI** uses min(detected VRAM, configured budget) for admission + a watchdog that unloads
  idle/stuck models; its fit warnings are gguf-parser-style. **llamafile** is llama.cpp math
  verbatim (same loader), nothing new. **Msty/Jan/GPT4All** wrap llama.cpp defaults; none publish
  estimation math beyond what's above — nothing further worth stealing.

---

## 6. Unsloth (scope addition) — and the discovery that it's our richest local reference

The vendored tree at `~/Library/Application Support/MOT Deck/vendor/unsloth/studio/backend` contains
a **complete, production-hardened GGUF+MLX fit engine** — the most architecture-complete estimator
found anywhere in this research, llama.cpp's own fitter included. All refs below are that tree.

### 6.1 Inference-side planner (read this file before writing ours)

`core/inference/llama_cpp.py`:

- `_estimate_kv_cache_bytes` (**:10866-11048**) — 5-path, arch-aware:
  1. **MLA** (DeepSeek-V2/3, GLM-4.7/5, Kimi): one compressed latent per token/layer,
     `key_len = kv_lora_rank + rope_dim`, **no separate V**; per-layer `head_count_kv` arrays where
     KDA linear-attention layers are 0 ("counting every block overstates by 3.9×, 78 GiB of
     phantom cache at 1M ctx");
  2. **Hybrid Mamba** (Qwen3.5/3.6!): only `ceil(n_layers / full_attention_interval)` layers hold
     KV + constant `_mamba_recurrent_state_bytes(n_parallel)`;
  3. **SWA** (Gemma 2/3/3n/4, gpt-oss, Cohere2): per-layer pattern; compact cells
     `min(cells, swa×(slots if unified else 1) + n_ubatch)` padded to 256, `--swa-full` and
     `--ctx-checkpoints` handled; fallback heuristic 1-global-in-4 when the pattern is missing;
  4. **GQA** with explicit key/value lengths, per-layer kv-head arrays;
  5. legacy `embd/n_heads` fallback.
  Plus: `nextn_predict_layers` (MTP blocks) excluded from the target cache only on the archs
  llama.cpp excludes them (`_TARGET_KV_EXCLUDES_NEXTN_ARCHS`); Gemma `shared_kv_layers`
  subtracted; no-flash-attn pads V width to model max and forces V to ≥ f16.
- `_kv_bytes_per_elem` (**:3156-3168**) — the exact table copied in §1.2.
- Cell layout (**:3171-3183**): 256-padding, unified vs per-slot streams — mirrors §1.2.
- Compute buffers: flat term `_estimate_compute_buffer_bytes` (**:11355-11387**):
  `n_vocab×ub×4 + 4×n_embd×ub×4` (+1 output buffer per extra slot; validated against measured
  {1:36, 2:492, 4:1388, 8:3220} MiB) × safety; **context-linear** term `_compute_buffer_ctx_bytes`
  (**:11389-11463**): f16 KV → KQ-mask only (`ub×2` B/tok ×1.5 safety); quantized KV → dequant
  scratch `2.25 × n_embd` B/tok (MLA 1.25×); ×4 mask copies on multi-device layer split
  (`GGML_SCHED_MAX_COPIES`); per-arch overrides (deepseek4 indexer: flat 2 GiB + 72,000 B/tok!).
- Vision: `_MMPROJ_VRAM_SAFETY = 1.4` (**:11297**) — encoder runtime buffers ≈ +0.4× the mmproj
  file on top of its weights; projector priced at a ctx floor of 8192.
- Adapters: `--lora`/`--control-vector` files are **not mmap'd** (staged + uploaded) — charged
  fully resident (routes/inference.py:10040-10055).
- Margins: `_CTX_FIT_VRAM_FRACTION = 0.97` of VRAM (fragmentation/CUDA-ctx/MoE-routing measured
  2-3%) (**:3026**); **Apple = 0.85 of `min(max_recommended_working_set_size, available_now)`**
  (**:3030**, `_apple_metal_memory_budget_bytes` **:8209** — "both inputs describe the MACHINE,
  not the moment"; take the min with psutil-available); floor reserve 512 MiB/card (**:3096**);
  honors llama.cpp's own `--fit-target` 1024 MiB / `fit_params_min_ctx` 4096 (**:3098-3060**);
  min useful ctx 8192 (**:3050**).
- Metal over-commit: hand-set ctx beyond the priced ceiling is **refused with a message**, not
  clamped (env override `UNSLOTH_ALLOW_METAL_CTX_OVERCOMMIT=1`) because the failure mode is a
  panic (**:9954-10044**). The canonical wire model is `memory_contract.py`
  (`build_memory_estimate`: weights/kv/compute/drafter/projector itemized, `gpu_bytes` tri-state).

### 6.2 Training-side estimation (for our queued Tune surface)

- **Published minimums** (unsloth.ai/docs "Unsloth Requirements", table verbatim): QLoRA(4-bit) /
  LoRA(16-bit) GB by params: 3B→3.5/8, 7B→5/19, 8B→6/22, 9B→6.5/24, 14B→8.5/33, 27B→22/64,
  32B→26/76, 70B→41/164, 405B→237/950. Implied rule of thumb: **QLoRA ≈ 0.6-0.8 GB per B params;
  LoRA-16 ≈ 2.4-2.7 GB per B** (batch 1, short ctx, gradient checkpointing on). No closed formula
  published — the table is empirical minimums, "may vary by architecture".
- **The composition to use in our engine** (standard accounting their numbers reduce to):
  `base_weights (0.5 B/param nf4 + ~3% quant constants | 2 B/param bf16)`
  `+ adapter params × (2 grad + 8 AdamW-fp32 | 4 AdamW-8bit + 2 weight)` where
  `adapter_params = Σ_targets r × (d_in + d_out)` — megabytes at r≤64, negligible next to
  `+ activations ≈ seq_len × batch × n_layers × n_embd × bytes × checkpointing_factor` (Unsloth's
  "unsloth" gradient-checkpointing offloads these to CPU/disk — that is where the "70% less
  memory" lives) `+ logits n_vocab × seq × 4` (their chunked CE avoids materializing this).
- **In the vendored code**: 8-bit AdamW default — "half the optimizer state"
  (`core/training/diffusion_lora_trainer.py:776`, `diffusion_dit_trainer.py:2421`); per-family
  empirical VRAM floor tables (`diffusion_train_common.py:584-599`, `qlora_vram_gb` per model
  family) — i.e. even Unsloth ships *lookup tables with headroom*, not formulas, for training fit;
  pre-run behavior is "free everything else, then admit" (`training.py:1591-1693` frees export/chat
  VRAM before auto GPU selection) rather than a byte-accurate forecast. **Recommendation: do the
  same for Tune v1** — per-recipe empirical bands (their table) + the composition above for
  explanation, refined by measured `torch.cuda.max_memory_allocated`/`mx.get_peak_memory` after
  the first step of a run.

---

## 7. The edge cases that make naive formulas wrong — with the correction

| # | Edge case | Naive error | Correction (and source) |
|---|---|---|---|
| 1 | **GQA vs MHA** | uses `head_count` | use `attention.head_count_kv` (llama-hparams.cpp); 8× on Llama-70B |
| 2 | **Per-layer kv-head arrays** | scalar kv heads | `head_count_kv` may be an array; 0 ⇒ layer holds no KV (Kimi hybrid: 3.9× error) |
| 3 | **head_dim ≠ embd/heads** | derives head_dim | read `attention.key_length`/`value_length` (Qwen3 = 256; MLA k≠v) |
| 4 | **MoE** | prices active params | full expert weights resident (§1.7); only placement moves |
| 5 | **SWA (Gemma!)** | KV linear in ctx | swa layers cap at `window×streams + n_ubatch` cells, per pattern (§1.3); Gemma-3 ≈ 5/6 layers capped |
| 6 | **Hybrid Mamba (Qwen3.5/3.6)** | all layers hold KV | only `ceil(layers/full_attention_interval)` + constant recurrent state (**4× on our own models**, §9) |
| 7 | **MLA (DeepSeek/GLM/Kimi)** | K+V per head | one latent `kv_lora_rank+rope_dim`, no V, kv_heads=1 (128× if you use n_head) |
| 8 | **Quantized KV** | 1.0 / 0.5 B | q8_0 = 34/32 = 1.0625 B (block scales); q4_0 = 0.5625; V-quant requires flash-attn else silently f16; some archs unsupported → f16 fallback (ollama #13337) |
| 9 | **Vision tower** | ignores mmproj | mmproj file (ours: 1.84 GB F32!) + ~0.4× runtime encoder buffers (Unsloth 1.4×; Ollama flat +1 GiB) |
| 10 | **Parallel slots** | one KV pool | unified: shared n_ctx; non-unified: per-slot streams each padded to 256; recurrent state × slots |
| 11 | **Flash attention off** | same compute | V padded to max width, V-quant impossible, KQ f32 scratch grows; FA=auto in b10662 |
| 12 | **Compute spike at long ctx** | flat graph | ctx-linear term: KQ mask ~2·ub B/tok; quantized-KV dequant scratch ~2.25×n_embd B/tok (measured §9: +836 MiB at 262k) |
| 13 | **MTP/NextN & drafters** | ignored | nextn layers excluded from target KV on some archs only; drafter = own weights + own KV + rollback state (Unsloth `_estimate_mtp_overhead_bytes`) |
| 14 | **Rope scaling** | ctx "supported" = trained | rope scaling changes usable ctx, not KV/token — cap advisor ctx at `context_length` × scaling factor, warn past `n_ctx_train` (our runner already logs that warning) |
| 15 | **ctx padding** | exact n_ctx | GGML_PAD to 256 cells (+ per-stream) |
| 16 | **Adapters** | free | --lora not mmap'd, fully resident |
| 17 | **Embeddings on CPU** | all weights on GPU | token-embd often CPU_Mapped: device ≠ file size (our 9B: 4.6 vs 5.3 GiB, §9) |

---

## 8. RECOMMENDED FORMULA SET for our engine

**Inputs we already can read.** `bridge/modeltools.py` has the bounded GGUF KV cursor
(`_Cursor`/`gguf_chat_template`, modeltools.py:115-216) — extend it to return a dict of hparams
instead of one string (same skip logic; the keys are all in the header before the tokenizer
arrays): `general.architecture`, `block_count`, `attention.head_count[_kv]` (scalar **or array**),
`attention.key_length/value_length[,_swa]`, `embedding_length`, `context_length`, `vocab_size`,
`expert_count`, `*.sliding_window[_pattern]`, `full_attention_interval`, `ssm.*`,
`nextn_predict_layers`, `shared_kv_layers`, `kv_lora_rank`, `rope.scaling.*`, plus file size and
mmproj file size from the registry. MLX: `config.json` (`num_hidden_layers`,
`num_key_value_heads`, `head_dim`, `sliding_window`, quant config) + Σ safetensors bytes.

**The estimate (GGUF):**

```
weights      = file_size(gguf) + file_size(mmproj) + Σ file_size(adapters/drafters)
kv           = arch_kv(n_ctx_padded, hparams, cache_type, slots, unified, flash_attn)
                 -- the 5-path dispatch of §6.1 (GQA / SWA / hybrid / MLA / legacy)
compute_flat = (n_vocab·ub·4 + 4·n_embd·ub·4) × 1.1
compute_ctx  = n_ctx × ( ub·2·1.5                     if kv f16/bf16/f32
                       | 2.25·n_embd·(ub/512)          if kv quantized (1.25 if MLA) )
vision_rt    = 0.4 × mmproj_size        (when vision on)
total        = weights + kv + compute_flat + compute_ctx + vision_rt
```

**The estimate (MLX):** `total = Σ safetensors + kv(config, dtype) + 0.10 × weights` (lazy-eval
headroom), refined by `mx.get_peak_memory()` after first generation. No mmap discount ever.

**The budget (this product = Apple Silicon first):**

```
ceiling = mx.device_info()['max_recommended_working_set_size']   # 51.84 GiB here; == what
                                                                  # llama.cpp Metal sees as "free" base
budget  = 0.85 × min(ceiling, available_now)                      # Unsloth's Apple rule, both jobs:
                                                                  # OS share + load-window drift
```

**The bands** (advisory verdict, per our doctrine — warn, never refuse; one exception below):

- **fits**: `total ≤ 0.80 × budget` — Ollama's 80% admission rule;
- **tight**: `0.80 × budget < total ≤ budget` — loads, but expect pageouts/UI pressure; show the
  itemized breakdown (weights/KV/compute — LM Studio and Unsloth both itemize) and the "q8_0 KV
  halves the context cost" hint (Unsloth's exact suggestion);
- **over**: `total > budget` — advisory red; offer remedies (smaller quant, lower ctx, q8_0 KV,
  `--n-cpu-moe` for MoE). **Hand-set ctx that over-commits on Metal is the one case to refuse
  with an override env**, per Unsloth's panic evidence (§6.1) — a warning that precedes a kernel
  panic is not a warning.
- Surcharges: batch ≥ 2048 → +2 GiB, ≥ 1024 → +768 MiB (Ollama), and n_parallel > 1 multiplies
  KV per §1.2.

**Ground truth, two tiers (do both):**

1. **Pre-load oracle (GGUF)**: shell out to our own `llama-fit-params -m X -c N --verbose`
   (~0.3 s, no_alloc) and parse `projected to use N MiB ... vs M MiB free`. Our formula set then
   only needs to be fast/explanatory (and to cover MLX, which has no oracle).
2. **Post-load truth**: parse the runner's `... buffer size = N MiB` lines (Ollama's regexes,
   §2.2, are copy-ready) and `mx.get_peak_memory()` for MLX; feed measured-vs-predicted back into
   the advisor's displayed confidence.

**Cross-check in CI**: run `gguf-parser` (gpustack) against the same headers; alert on >10%
disagreement with our formulas.

---

## 9. Validation plan — with today's measured anchors

Free data points measured on this machine (b10662, M5 Pro 64 GiB):

**Qwen3.5-9B-Q4_0** (file 5295 MiB; hparams read by our own dump: 33 blocks, nextn 1 → 32 target,
`full_attention_interval 4` → **8 attention layers**, kv_heads 4, k=v=256 → f16 KV =
4×256×2×2 = 4096 B/layer/token × 8 = **32 KiB/token**):

| ctx | fit-params projected (MiB) | Δ from 8192 | formula KV Δ | compute buf |
|---|---|---|---|---|
| 8,192 | 5,399 | — | — | 501 + 24 MiB |
| 32,768 | 6,167 | +768 | 24,576 tok × 32 KiB = **768** ✓ | 501 MiB |
| 65,536 | 7,191 | +1,792 | 57,344 × 32 KiB = **1,792** ✓ | 501 MiB |
| 262,144 | 14,171 | +8,772 | 253,952 × 32 KiB = 7,936 ✓ + compute +836.46 ✓ | **1,337 MiB** |

The hybrid-corrected formula is **exact to the MiB** (KV linear at 32 KiB/tok; the naive
33-layer version predicts 132 KiB/tok — 4.1× wrong). Also visible: RS buffer 50.25 MiB constant
(Mamba state), and device-projected weights ≈ 4.6 GiB < 5.3 GiB file (CPU-side token embeddings +
MTP tensors — edge case #17).

**Remaining plan:**

1. **Resident 27B** (`RVN-Q4_K_S` / the DavidAU Qwen3.6-27B, both 64 blocks, fai 4 → 16 attn
   layers, kv 4, k=v 256 → predicted **64 KiB/token**; at its logged n_ctx 65536: KV = 4.0 GiB;
   weights 17,086 MB + mmproj F32 1,843 MB + ~0.4× encoder ≈ 737 MB): run `llama-fit-params` at
   8k/64k and diff against the live process RSS + `footprint` (`footprint <pid>` reports wired);
   the runner already logs at `-lv 3` — drop to `-lv 1` once to capture the buffer lines.
2. **A SWA model** (pull Gemma-3-4B GGUF): verify KV flattens past the 1024-token window on 5/6
   layers; compare `--swa-full` on/off.
3. **KV quant**: same 9B at `-ctk q8_0 -ctv q8_0 -fa on` — expect ×0.53125 on KV and the
   quantized compute-ctx rate to appear.
4. **MoE** (the Muse-Glimmer-30B Q4_K_S, 16.1 GB): confirm full-file residency and try
   `--n-cpu-moe` placement deltas.
5. **MLX side**: load any mlx-community model in our venv, record
   `mx.get_active_memory()` after load (≈ Σ safetensors) and `mx.get_peak_memory()` after a 4k-ctx
   generation; verify the +10% headroom band.
6. **Parallel slots**: 9B with `-np 4` unified vs not — KV ×1 vs cells/4-per-stream, RS ×4.
7. Wire the post-load log parser (§8 tier 2) and store measured-vs-predicted per model in the
   registry — the advisor shows its own historical error.

---

## Sources

**llama.cpp (ggml-org/llama.cpp, master ≈ our b10662)**: `src/llama-kv-cache.cpp` (KV tensor
creation + logs), `src/llama-hparams.cpp` (`n_embd_k_gqa`), `src/llama-kv-cache-iswa.cpp` (SWA
sizing), `src/llama-context.cpp` (ctx padding, graph reserve, V-quant/FA constraint),
`src/llama-mmap.cpp` (MAP_SHARED/madvise/mlock, Darwin wire-limit sysctls),
`ggml/src/ggml-metal/ggml-metal-device.m` (newBufferWithBytesNoCopy, MTLResidencySet,
recommendedMaxWorkingSetSize warning), `common/fit.cpp` (`common_params_fit_impl`); local:
`~/Library/Application Support/MOT Deck/data/llama-server.help.txt` (lines 25-165, 426-460:
`--fit*`, `--load-mode`, `--swa-full`, `--ctx-checkpoints`, `--kv-unified-per-slot`),
`data/llamacpp/build/bin/llama-fit-params` runs of 2026-08-28.

**Ollama (ollama/ollama)**: main `server/sched.go` (:536-550 80% rule, :803-914 batch headroom +
surcharges, :1255 mmapHostPressureHeadroom), `llm/llama_server.go` (:86 mmprojOffloadHeadroom,
:2676 PredictServerVRAM, :2700+ memoryParsingWriter); v0.5.7 `llm/ggml.go` (:363-376 GraphSize KV,
:552 kvCacheBytesPerElement), `llm/memory.go` (EstimateGPULayers); issues
[#16310](https://github.com/ollama/ollama/issues/16310),
[#13789](https://github.com/ollama/ollama/issues/13789),
[#11202](https://github.com/ollama/ollama/issues/11202),
[#13018](https://github.com/ollama/ollama/issues/13018),
[#14351](https://github.com/ollama/ollama/issues/14351),
[#13337](https://github.com/ollama/ollama/issues/13337), PR
[#9987](https://github.com/ollama/ollama/pull/9987) (SWA estimates).

**LM Studio**: [lms load docs](https://lmstudio.ai/docs/cli/local-models/load) (+ beta
`--estimate-only`), bug-tracker
[#1631](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/1631),
[#1544](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/1544),
[#128](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/128),
[0.3.14](https://lmstudio.ai/blog/lmstudio-v0.3.14) /
[0.3.27](https://lmstudio.ai/blog/lmstudio-v0.3.27) blogs, github.com/lmstudio-ai/mlx-engine.

**MLX**: local venv docstrings (`mx.set_wired_limit/set_memory_limit/set_cache_limit/
get_active_memory/get_peak_memory/device_info`), `mlx_lm/generate.py:230-266,714,737`,
`mlx_lm/server.py:1889-1890` (local files);
[MLX metal API docs](https://ml-explore.github.io/mlx/build/html/python/metal.html).

**HF / calculators**:
[accelerate model_size_estimator](https://huggingface.co/docs/accelerate/usage_guides/model_size_estimator),
[gpustack/gguf-parser-go](https://github.com/gpustack/gguf-parser-go)
(`file_estimate__llamacpp.go`),
[Vokturz/can-it-run-llm](https://huggingface.co/spaces/Vokturz/can-it-run-llm),
[KolosalAI/model-memory-calculator](https://github.com/KolosalAI/model-memory-calculator),
[LocalAI VRAM management](https://localai.io/docs/advanced/vram-management/).

**Unsloth**: vendored `~/Library/Application Support/MOT Deck/vendor/unsloth/studio/backend/` —
`core/inference/llama_cpp.py` (:3026, :3030, :3050-3100, :3156-3183, :8209, :9954-10044,
:10866-11048, :11297-11463), `routes/inference.py` (:9039, :9915), `core/inference/
memory_contract.py`, `core/inference/mlx_inference.py` (:1408-1426), `core/training/
diffusion_train_common.py` (:584-599), `diffusion_lora_trainer.py` (:776), `training.py`
(:1591-1693); [Unsloth Requirements docs](https://unsloth.ai/docs/get-started/fine-tuning-for-beginners/unsloth-requirements).

**Local artifacts**: `bridge/modeltools.py` (GGUF cursor to extend),
`data/models.json` (registry), GGUF header dumps + `llama-fit-params` measurements of 2026-08-28
(this machine).
