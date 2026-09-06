# Runner flags + warmup measurement on b10662 (2026-08-28, Fable measurement agent)

Answers the "measure first" mandate from `2026-08-28-gemini-research-verdict.md` item 2:
are the Gemini fork's runner argv flags (`-b 2048 -ub 1024 --flash-attn`) worth adopting,
and what would a 1-token post-switch warmup probe actually buy?

**Doctrine note (honesty):** every number below was measured today on a SCRATCH
llama-server on :6899. The live runner on :6767 was never touched (health-checked
read-only once at the end: 200). No production code, pins, or components changed.
This machine was NOT quiet during measurement — see "Honest limits."

## Setup (reproducible)

- Binary: `data/llamacpp/build/bin/llama-server`, `version: 0.3.0-dev (build 10662,
  commit 18443257a)`, AppleClang 21, Darwin arm64. Same binary MOT Deck launches
  (read from `scripts/start_component.sh` runner branch).
- Model: the real resident 27B — `Qwen3.6-27B-Fable-Fus-711-UnHeretic-NM-DAU-NEO-MAX-NEO-Q4_K_S.gguf`
  (17.09 GB, from `~/.lmstudio/models/DavidAU/...MTP-GGUF/`).
- Baseline argv = the live runner's exact argv (verified via `ps` against the running
  :6767 process), with three documented deviations on the scratch instance:
  `--port 6899`, `--ctx-size 32768` (memory safety; 65536 live), and **no `--mmproj`**
  (saves 1.8 GB, text-only bench). Everything else identical:
  `--no-context-shift --no-cont-batching --cache-ram -1 --fit off --parallel 1
  --api-key ... --repeat-penalty 1.1 --repeat-last-n 256`.
- Memory safety check that made the 27B usable: the scratch instance mmaps the SAME
  gguf file as the live runner, so weight pages are shared page cache. Scratch RSS
  showed 19.5 GB but system-wide free stayed at 24-25% before/after load
  (`memory_pressure -Q`). Swap was near-full (10.7/11 GB) the whole time regardless.
- Prompts: built from repo docs text (`docs/MOT-DECK-INTERNALS.md` + `docs/motdeck-architecture.md`
  + the rest of docs/), trimmed via the server's `/tokenize`:
  "8k" file = **7,745 tokens**, "24k" file = **23,493 tokens**.
- Requests: native `/completion`, `cache_prompt: false` (forces full prefill every run),
  `temperature: 0`, `n_predict: 200` (`ignore_eos: true` from condition B onward — the
  first condition A's 24k runs stopped at EOS after 1 token, so 24k gen-tok/s exists
  only for B and the A rerun). Timings are the server's own `timings` object
  (`prompt_ms` / `prompt_per_second` / `predicted_per_second`), which b10662 returns
  in the `/completion` response.

## 1. What b10662's defaults actually are (settles the Gemini claim)

From `llama-server --help` and the verbose (`-lv 4`) startup log of the scratch
instance running our EXACT baseline argv:

| Flag | b10662 default | Effective on our argv (log-proven) |
|---|---|---|
| `-b` (batch) | **2048** | `n_batch = 2048` |
| `-ub` (ubatch) | 512 | `n_ubatch = 512` |
| `--flash-attn` | **auto** | `flash_attn = auto` → **`resolve_fused_ops: Flash Attention enabled`** |

So of Gemini's three flags, **two are literal no-ops on b10662**: `-b 2048` is the
default, and flash-attn `auto` already resolves to ON for this model on Metal.
The only flag that changes anything is `-ub 1024`.

`/props` on this build does not expose flash-attn/batch state; the `-lv 4` startup
log is where the effective values are visible.

## 2. Prefill A/B: baseline vs Gemini flags

Conditions: **A** = baseline argv (defaults: ub 512, fa auto→on). **B** = baseline +
`-b 2048 -ub 1024 --flash-attn on`. Since `-b`/`-fa` are no-ops, B isolates `-ub 1024`
by construction — no separate condition C needed. 3 runs per prompt per condition,
plus a rerun of A after the environment changed (see limits), plus an interleaved
paired series. Medians (ranges) in prompt-processing tok/s:

| Condition | 8k prefill tok/s | 24k prefill tok/s | 8k gen tok/s (200 tok) |
|---|---|---|---|
| A (first pass) | 261.2 (260.1-304.3) | 277.6 (237.0-278.6) | 7.2 (7.1-10.2) |
| B (Gemini flags) | 298.1 (295.2-300.2) | **244.8** (243.9-255.9) | 12.8 (12.8-13.6) |
| A (rerun, later env) | **337.1** (328.2-340.1) | 191.3 (170.6-204.3) | 13.7 (13.6-13.9) |

Read that table honestly: the *environment* moved more than any flag did. Between A
and B the Gemini-fork daemons burning RAM were killed (coordinator action, not mine),
and during the A-rerun 24k series something else loaded the machine (its gen tok/s —
which `-ub` cannot affect — collapsed to 2.6-10.2). B "beat" first-pass A at 8k and
*lost* to it at 24k; rerun-A then beat B at 8k. Cross-condition comparisons at the
±10% level are not valid on this machine today.

**Interleaved tie-breaker** (fresh instance per run, A and B alternating back-to-back,
one 7,745-token prefill each, so ambient drift mostly cancels within a pair):

| Pair | A (ub 512) tok/s | B (ub 1024) tok/s | B delta |
|---|---|---|---|
| 1 | 242.6 | 259.6 | +7.0% |
| 2 | 260.3 | 313.3 | +20.4% (contaminated: gen tok/s doubled 7.6→14.0 mid-pair — ambient load lifted) |
| 3 | 341.5 | 323.8 | −5.2% |

Sign flips across pairs; the one big delta is provably an environment shift.
**`-ub 1024` shows no reproducible prefill win.** If it has one on quiet hardware it
is small (single-digit %); today it cannot be established at even the 3% bar.
Generation speed was identical between A and B whenever the machine was comparably
loaded (12.8-14.0 tok/s quiet, ~7 tok/s under contention) — as expected, `-ub` is a
prefill-only knob.

## 3. Warmup effect (fresh process, cold Metal state)

Three fresh scratch processes on baseline argv; "cold" = very first 1-token request
the process ever served, "warm" = the identical request immediately after
(`prompt_ms` from server timings; wall times tracked too, same story):

| Fresh run | cold 1st request | warm 2nd request | delta the probe would hide |
|---|---|---|---|
| 1 | 91.0 ms | 70.9 ms | **20.1 ms** |
| 2 | 139.9 ms | 146.6 ms | ~0 (noise; loaded moment) |
| 3 | 70.7 ms | 69.6 ms | **1.1 ms** |

Median delta ≈ 1 ms, worst observed 20 ms. **Why so small: b10662 already warms the
model itself at load** — the startup log prints
`common_init_: warming up the model with an empty run - please wait ... (--no-warmup to disable)`
— so Metal shader/pipeline setup is done before `/health` ever returns 200.
The Gemini TTFT table's premise (cold shaders on first user turn) is stale for this build.

Model load time (process spawn → `listening`/health 200), from the servers' own log
clocks across all 12 fresh launches today: **1.24-1.90 s** (median ≈ 1.6 s).
CAVEAT: every launch was page-cache-HOT (the live runner mmaps the same file). A
disk-cold 17 GB load would be several seconds longer; measuring it would have required
evicting the live runner's cache, which the fence forbade.

So the honest sentence for the warmup slice: **"a model switch takes ~1.6 s to
healthy (cache-hot; disk-cold will be worse), and a warmup probe would hide a further
~1-20 ms of first-turn delay."**

## 4. The probe's own cost + interference

- Cost of the 1-token warmup request on a cold instance: **70-140 ms** wall
  (the three cold requests above: 100/146/76 ms wall).
- Concurrency: on a fresh cold instance, two tiny 1-token requests fired ~20 ms apart
  (probe + simulated user turn): first completed in **75 ms**, second in **141 ms** —
  it queued politely behind the first (our argv is `--parallel 1 --no-cont-batching`,
  so strictly serial) and completed normally. No errors, no pathological stall.
  Worst case a user turn racing the probe waits ~one tiny-request duration (<100 ms).

## Honest limits

- Shared, busy machine: the live :6767 runner was serving another builder throughout;
  ambient load swung measured throughput by ±30% (gen 2.6→14.0 tok/s across the day).
  Medians + the interleaved design partially compensate; they do not fully cure it.
- The environment CHANGED mid-measurement: the Gemini-fork daemons (incl. the 30B on
  :6807, RSS ~11 MB i.e. fully paged out) were killed between condition A and B. That
  is why A was rerun; first-pass A's absolute numbers are the pre-kill environment.
- Scratch deviations from live argv: ctx 32768 (not 65536) and no mmproj. Neither
  should change prefill *ratios* between conditions, but absolute numbers on the live
  runner will differ (bigger KV, mmproj resident).
- Load times are page-cache-hot only (see §3).
- "8k"/"24k" prompts are exactly 7,745 / 23,493 tokens of repo-docs text.

## VERDICT

**(a) Flags:**
- `-b 2048` — **SKIP.** It is the b10662 default; adding it to a contract-pinned argv
  is pure maintenance cost for zero change.
- `--flash-attn` (on) — **SKIP.** `auto` already resolves to enabled for this model on
  Metal (log-proven: `resolve_fused_ops: Flash Attention enabled`). No perf delta
  available to win. (If someone later wants it pinned as drift-protection against a
  future `auto` regression, that's a policy choice, not a performance one — the
  measurement gives no reason.)
- `-ub 1024` — **SKIP** under the <3% rule. Paired deltas were +7.0% / +20.4%
  (contaminated) / −5.2%; full-series 24k medians even favored ub 512. Not
  reproducible above today's noise floor. If anyone wants to revisit, re-run the
  interleaved series on a quiet machine; adopt only if it clears 3% consistently.

**(b) Warmup numbers for the warmup slice to cite:** switch-to-healthy ≈ **1.6 s**
(1.24-1.90 s, page-cache-hot; disk-cold worse); the probe would hide a further
**~1-20 ms** (median ~1 ms) of first-turn delay; the probe itself costs **70-140 ms**
and a racing user request just queues (~+70 ms). **On b10662 the bridge-level warmup
probe is not worth a slice** — the server already self-warms at load
(`--no-warmup` is what would *disable* it). The Gemini TTFT breakdown predates this
behavior. If the probe slice stays queued anyway, reframe it: the only first-turn
cost worth engineering around is the multi-second cold *load*, not shaders/KV.

**(c) b10662 surprises, plainly:**
1. **llama-server self-warms at model load** (empty-run warmup, on by default) — this
   single fact deletes most of the warmup-probe motivation.
2. **flash-attn is effectively already ON** via `auto` — settles the Gemini question.
3. **`-b` default is already 2048.**
4. `/props` does not expose flash-attn/batch state on this build; use `-lv 4` startup
   logs to verify effective values.
5. mmap page-cache sharing means a second instance of the *same* resident model costs
   almost no extra RAM and loads in ~2 s — useful fact for any future A/B tooling.

## Cleanup attestation

Scratch instance killed after each condition and at the end; final checks:
`lsof -i :6899` → free; `pgrep -fl 'llama-server.*6899'` → none. Live :6767 runner
untouched (one read-only /health = 200; the single-chat-request allowance was not
even used). No files written outside this doc and the session scratchpad
(prompt files, bench.py, scratch_ctl.sh, per-launch logs live there and are ephemeral).
