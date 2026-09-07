# A6 — real fit-estimate validation on this Mac

Status: measured candidate evidence for the v1.5.88 wave. This document calibrates
advisory estimates; it does not create a hard launch blocker and does not claim that one
measured architecture represents every model using the same runtime.

## Measurement contract

`scripts/measure_fit_real.py` launches exactly one caller-selected model on an unused
loopback port, submits a real one-token completion, samples macOS `phys_footprint` from
the exact child PID, parses the complete llama.cpp allocation log where available, and
writes an atomic JSON receipt. It never edits the registry, manifest, live runner port,
or another process. An occupied port is a refusal; cleanup signals only the new process
group that this invocation created.

For llama.cpp, context is an allocated server setting, so prediction is compared with
the engine's own model/KV/working-buffer total. For MLX, the server has no equivalent
context launch flag: the measured prompt is a workload, API usage is the token truth,
and physical footprint is the comparison. Mapped GGUF pages mean process
`phys_footprint` is not a substitute for the engine allocation total; both are retained.

Every family was run on the same machine in a first/cold-enough launch and an immediate
relaunch or second workload. The live 27B runner was stopped through its existing
ownership record during the measurement window and restored to the exact prior model.

## Results

All byte figures below are GiB. The full receipts are in the sibling `outputs/`
workspace root and contain paths, exact timings, API usage, allocation buffers and log
tails.

| Architecture / run | Workload | Estimate | Engine allocation | Peak physical | Estimate error vs engine |
|---|---:|---:|---:|---:|---:|
| Non-Gemma SWA, Laguna first | 16k context | 15.67 | 15.71 | 0.90 | -0.26% |
| Non-Gemma SWA, immediate relaunch | 16k context | 15.67 | 15.71 | 0.90 | -0.26% |
| Non-Gemma SWA, warm | 64k context | 17.83 | 17.87 | 2.78 | -0.21% |
| MLA, DeepSeek Coder V2 Lite first | 16k context | 10.47 | 10.51 | 4.36 | -0.40% |
| MLA, immediate relaunch | 16k context | 10.47 | 10.51 | 4.36 | -0.40% |
| MLA | 64k context | 23.73 | 23.73 | 17.02 | +0.02% |
| Qwen3.5 vision model, text-only | 16k context | 7.19 | 7.34 | 0.80 | -2.02% |
| Same model + projector | 16k context | 9.57 | 7.61 | 2.61 | +25.82% |
| Qwen3.5 vision model, text-only | 64k context | 8.79 | 9.12 | 2.31 | -3.68% |
| Same model + projector | 64k context | 11.16 | 9.39 | 4.12 | +18.92% |
| MLX Qwen3.5 27B, first short prompt | 84 API tokens | 15.90 | n/a | 14.42 | +10.25% vs physical |
| MLX Qwen3.5 27B, immediate short prompt | 84 API tokens | 15.90 | n/a | 14.42 | +10.26% vs physical |
| MLX Qwen3.5 27B, long prompt | 4,148 API tokens | 17.23 | n/a | 17.50 | -1.50% vs physical |

The temporary MLA file is `DeepSeek-Coder-V2-Lite-Instruct-Q2_K.gguf` at exact
Hugging Face snapshot `8f248fa2072348f77a8bc37754e470de1f61866e`. It was not added
to the model registry or made a product default.

## Corrections earned by measurement

The installed MLX 27B repository is a multimodal wrapper whose decoder contract lives
under `text_config`. The old flat reader priced its KV and recurrent state as zero.
Inspection of the pinned `mlx_lm.models.qwen3_5` and `gated_delta` implementation proved
64 decoder layers: 16 full-attention layers with ordinary KV, and 48 linear-attention
layers with persistent float32 gated-delta state plus a short convolution state. The
server's real prefill chunk is 2,048 tokens.

`bridge/core/fit.py` now reads that nested contract, prices only the full-attention KV,
adds the exact Qwen3.5 recurrent-state shape, and bounds temporary prefill work by the
pinned server chunk rather than scaling it to a theoretical 256k context. The local and
remote MLX paths share this calculation. Existing ten-percent lazy-evaluation headroom
remains a conservative cross-architecture floor.

The vision pair proves that projector residency is not fully represented in the
llama.cpp allocation lines: adding the real projector increased physical footprint by
about 1.8–1.9 GiB, while the parsed engine allocation rose only about 0.25 GiB. The
existing 2.38 GiB vision allowance is conservative by roughly 22% on this model. It is
retained as an advisory margin rather than tuned to a single projector.

## Honest limits

- The MLA and SWA formulas are now real-load validated for the exact measured models and
  contexts, not every architecture that can be described as MLA or sliding-window.
- The new MLX mixed-attention/state calculation is exact to the pinned Qwen3.5 runtime
  shape. Conventional valid configs retain the earlier all-attention fallback; malformed
  configs retain only the explicitly labelled weights-plus-headroom estimate and do not
  inherit a false validation claim.
- Peak physical footprint depends on prompt length, allocator state and mapped pages.
  These receipts are calibration evidence, not a guaranteed ceiling.
- Warm/cold labels describe launch order on this machine. macOS filesystem caching is
  not forcibly purged, so “first” is not claimed to be a laboratory cold boot.
- The fit engine remains advisory. Quiet/Advise/Advise early/Custom headroom behavior is
  unchanged, and no estimate becomes a hard refusal merely because A6 measured it.

## Regression discovered during the walk

The measurement journey used the public model-eject operation and exposed a shipped
v1.5.87 router-split regression: `_eject_runner()` successfully stopped the owned runner
and then raised `NameError` at `time.sleep()` because `bridge/routers/models.py` had not
imported `time`. The app therefore returned HTTP 500 after performing the stop. The
missing import and an executable wait/clear-state regression test are part of the same
candidate wave; the installed journey must be repeated after shipping before closure.
