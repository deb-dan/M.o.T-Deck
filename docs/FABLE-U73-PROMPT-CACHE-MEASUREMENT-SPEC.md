# U73 — measure prompt-cache behavior before reserving slots

**Date:** 2026-09-05  
**Status:** done-verified as measured/no-change; no launch flag was changed.

## Question

Does alternating the real Chat, Agent, Hermes, and LOffice prompt shapes materially
increase time-to-first-token or prompt-evaluation work on the pinned runner, and would
multiple persistent slots improve that enough to justify their memory and scheduling
cost on this Mac?

## Controls

- Use the same loaded model, context size, sampling, prompt bodies and one-token output
  cap for all samples. Record engine pin and exact launch flags.
- Warm the engine, then run repeated A/A, A/B/A, and representative real-lane sequences.
  Read llama.cpp's returned timing fields and `/metrics`; do not estimate from wall time
  alone.
- Run enough repetitions to report median and range. Separate prompt evaluation from
  queueing and generation.
- Record resident memory/KV allocation before and after. Multiple slots can consume
  memory even if latency improves.
- Do not expose API keys, user transcript text, or private prompts in the report. Use
  generated deterministic prompt shapes of comparable size.
- Do not change live launch flags during ordinary use. Any A/B requires an explicit
  reversible runner restart and restores the exact previous command afterward.

## Decision rule

No change is the default. `--parallel 2` and `--slot-save-path` are separate hypotheses:
parallel slots may reduce cache replacement but increase KV memory; saved slots may add
disk I/O and lifecycle/state concerns. Adopt neither unless the measured repeated-lane
benefit is material, stable, and survives memory-pressure and correctness checks.

If adopted, permanent tests must pin the supported llama.cpp arguments, path
containment/permissions, clean shutdown, model-switch invalidation, failed-save recovery,
and truthful status reporting. If the result is neutral or harmful, record the numbers
and close U73 as measured/no-change rather than manufacturing an optimization.

## 2026-09-05 control results

The real v1.5.80 runner was `llama.cpp b10662`, the live 27B GGUF, `--parallel 1`,
`--cache-ram -1`, metrics enabled, and otherwise unchanged. A synthetic A/A/B/A/A/B
sequence used two unrelated system shapes much larger than the app's ordinary prompts
and requested one output token. Credentials and prompt text were not logged.

| Sample | Prompt tokens evaluated | Prompt evaluation |
| --- | ---: | ---: |
| cold A | 18,490 | 79,716 ms |
| repeated A | 4 | 184 ms |
| cold B switch | 16,442 | 76,801 ms |
| A after B | 4 | 216 ms |
| repeated A again | 4 | 162 ms |
| B after A | 4 | 188 ms |

The hostile A/B switch did **not** evict the earlier prompt cache even with one active
slot. Both returns evaluated only the four-token user suffix. This measurement provides
no evidence for adding a second parallel slot or slot-save directory, while those flags
would add memory/state cost. The correct U73 result for this pin and machine is therefore
no launch change. Re-measure after a runner pin/cache-policy change or a real regression;
do not carry these timings forward as a universal performance claim.

A second independent A/B run used larger deterministic prefixes and repeated each warm
return instead of relying on one observation. Cold A evaluated 24,057 tokens in
112,776 ms; cold B evaluated 30,058 in 164,571 ms. The three later A returns each
evaluated four tokens (median 203 ms, range 171–237 ms); the two later B returns did the
same (median 198 ms, range 179–216 ms). Runner RSS increased from 20,481 MiB to
26,399 MiB while retaining the two deliberately huge prefixes. That memory increase is
additional evidence against allocating more slots without a reproduced need.

This does not claim a universal four-lane benchmark: it proves that two unrelated
prefixes substantially larger than normal lane prompts coexist at this engine/model
pin. A future real-lane regression, a runner/cache-policy change, or a model whose KV
budget differs materially is the trigger to repeat a four-shape measurement. Until
then, “no launch change” is the narrow evidence-backed decision.
