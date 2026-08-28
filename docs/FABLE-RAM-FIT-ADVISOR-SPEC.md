# FABLE SPEC — the RAM fit advisor (Debi's ruling, 2026-08-28)

**The ruling this implements:** RAM information is first-class across the app — what the
machine has, what's used, what's free — and every model (installed OR downloadable) carries
a FIT VERDICT in the LM Studio grammar: fits fully / likely fits / too large. And the
verdict is NUANCED, never black-and-white: fit is a function of context size, KV-cache
quantization, and load parameters, so "too large" must say *at these settings* and offer
the settings that would make it fit. Gates inform and recommend (the advisory-gates
ruling); the advisor is the engine that makes those warnings truthful and actionable.

## 1. The fit engine (bridge-side, one source of truth)

New `bridge/core/fit.py` (the RAM-ledger idea finally built as the M1 research shaped it):

    fit(model, settings) → { verdict, need_gb, breakdown, remedies }

- **need** = weights size (on-disk quant size for GGUF/MLX — we have it for installed
  models and for HF browser results) + KV cache estimate (n_ctx × arch dims × KV quant —
  derive arch dims from the GGUF header / MLX config via modeltools where known; a
  labeled ESTIMATE with stated assumptions where not) + engine overhead (measured class
  constants, stated) + a system buffer (visible, not hidden padding).
- **have** = unified memory total − current pressure (vm_stat / host_statistics via a
  small measured probe; include what OUR components hold — the runner's resident model
  is the big one and we know it).
- **verdict** at CURRENT default settings: `fits` (comfortable margin) / `tight`
  (fits but little headroom — the "likely" band) / `over` (doesn't fit at these settings).
- **remedies** when `tight`/`over`: the settings that change the answer, computed, not
  generic — "at 16k ctx: needs ~14.2GB (fits)", "with q8_0 KV: −2.1GB", "eject the
  current runner model: +16GB free". Remedies are the SOPHISTICATION Debi named: the
  advisor teaches, it does not just classify.
- Voice/music workers use the same engine with their measured peaks (VoiceChat-11B:
  17.45GB measured) — one engine, every heavy thing.

## 2. Where it shows (the LM Studio grammar, our voice)

- **A memory strip** on the Models view (and a compact tile on MOT Deck): total ·
  in use (named: which model/component holds it) · free. Live via the SSE bus.
- **Every installed model row/detail**: verdict chip + need-vs-free line.
- **Every HF browser result**: verdict chip per downloadable file/quant (size is in the
  HF metadata), BEFORE download — "you can download it, and here's what running it will
  take" (download ≠ run; both facts shown, neither blocked).
- **The load/switch flow**: the advisory-gate consent dialog uses the same engine —
  verdict, breakdown, remedies, proceed-anyway. One engine, one grammar, no divergence
  between what the browser said and what the loader says.
- Verdicts recompute when settings change (the Load-group params — n_ctx/KV-quant/
  offload — are the advisor's INPUTS; if the Load-group UI slice isn't built yet, the
  advisor exposes the settings parameter in its API and the UI offers the remedies as
  one-click "check at 16k" recalculations, which becomes the natural seed of that slice).

## 3. Honesty rules

- Estimates are labeled estimates, with the assumption visible on hover/detail
  (impeccable: no false precision; a ± band beats a fake exact number).
- The verdict NEVER disables a button. Download always downloadable; load always
  attemptable through the consent flow. The advisor's job is that nobody is surprised.
- All-designs rule applies to the chips/strip; tokens reachable by every look.
- Fit math gets an executable test table (known models × settings → expected bands),
  and the measured constants carry their provenance (which measurement, when).

## 4. Slicing

S1: fit engine + memory strip + verdicts on installed models + the consent-dialog
integration (retrofit of the advisory-gates ruling rides this).
S2: HF browser verdicts per quant file + remedies-as-recalculation UI.
Sequencing: after the capability-audit builder releases index.html.

## 2b. The app-wide RAM ledger (Debi's extension, same ruling, same slice)

The fit advisor's "have" side becomes a full LIVE LEDGER, not one number:

- **Our stack, itemized**: every component the supervisor runs has a known pid (runner,
  Hermes, Odysseus, SearXNG, VoiceStudio, Voicebox, ComfyUI, Unsloth, OpenCode, the
  bridge itself, the app shell) — show each one's live memory footprint by name,
  including child processes (the runner's model is the headline; voice/music workers
  when resident). Sampled cheaply (proc_pid_rusage/ps class, cached a few seconds,
  pushed over the SSE bus like everything else).
- **Outside the app**: the rest of the machine, honestly — total · our stack · "other
  apps" as a bucket, expandable to the TOP external consumers by process name (the
  Activity-Monitor-lite view: e.g. Chrome 6.2GB, standalone Unsloth 2.1GB) so "why is
  it tight" is answerable without leaving MOT Deck. Read-only: we NAME external
  processes, we never touch them.
- **Where it lives**: the MOT Deck tile grows into the entry point (today's "Disk free"
  grammar) → expands to the full ledger view (a section on MOT Deck or beside Models —
  builder proposes, Fable design-QAs). The Models strip (§2) shows the compact form.
- **Ties together**: the fit verdicts cite the ledger's named holders in remedies
  ("eject Qwen3.6-27B: +16GB", "stop ComfyUI: +1.8GB"); the consent dialog shows the
  same names. macOS memory nuance stated honestly where it matters (compressed memory
  and swap exist — surface memory PRESSURE alongside raw free, since free-RAM alone
  understates what macOS can absorb; label accordingly, no false alarms).

## 3b. Copy provenance rule (Debi, 2026-08-28)

LM Studio is closed-source: its extracted strings are RESEARCH EVIDENCE, not copy to
ship. The advisor's user-facing text is written in OUR editorial voice — same grammar
CLASS as the best references (verdict → reason → remedy → proceed; the gap on the chip),
but no sentence lifted verbatim from any closed-source product. Near is fine; identical
is not. (Open-source strings may be adapted where their license permits, still preferring
our voice.) A test may pin OUR strings; none may match LM Studio's shipped strings —
the builder checks its final copy against the extracted table and reports zero collisions.

---

# SPEC v2 — the synthesis (Fable, 2026-08-28, after the three-research pass)

Supersedes §1's formula sketch. The three research docs are BINDING sources:
`2026-08-28-fit-math-oss.md` · `2026-08-28-macos-memory-accounting.md` ·
`2026-08-28-memory-ux-patterns.md`. The builder reads all three end to end.

## V2-1. The engine, corrected by research

- **GGUF fit = ask the oracle, not a formula.** `llama-fit-params` (already in
  data/llamacpp/build/bin, ~0.3s, no allocation) is the primary source per model ×
  settings; results cached by (model, ctx, kv-quant, build). Our own formula set (the
  research's recommended one, incl. the hybrid-Mamba/SWA/GQA/MLA corrections) runs as
  the CROSS-CHECK and the instant-UI estimate while the oracle runs — a >10% divergence
  is logged and the oracle wins. The naive formula was measured 4.1× wrong on our own
  models; nobody re-derives KV math by hand again.
- **MLX fit = the estimator formulas** (the 5-path KV set found in the Unsloth tree,
  adapted with provenance comments) — no oracle exists; label estimates accordingly.
- **The budget** = 0.85 × min(Metal recommendedMaxWorkingSetSize [measured 81% of RAM
  on this machine — read live, never hardcode], effective-available-now from the ledger).
  Bands: fits < 80% of budget ≤ tight ≤ 100% < over. All advisory per the ruling, with
  ONE exception the research legitimated: a hand-raised Metal over-commit is a
  documented kernel-panic risk — that specific case refuses with the reason and an env
  override (the nuance Debi named: gates are sophisticated, not absent).
- **Workers** (voice/music): measured lifetime peaks via ri_lifetime_max_phys_footprint,
  quoted with provenance.

## V2-2. The ledger, corrected by research

phys_footprint via proc_pid_rusage (NEVER RSS — measured 8.5GB understatement),
tree-summed (footprint excludes clean shared pages, so summing is honest); WebKit XPC
attributed via the responsibility API (Activity Monitor's own mechanism) with a labeled
not-attributable fallback; pressure + kern.memorystatus effective-available headline the
system view (measured here: 0.9GB "free" + 18GB swap at NORMAL pressure — raw free is a
liar); compression/swap shown; sampling 2s-watched / 15s-idle / 0-unsubscribed with
delta-suppressed SSE emits; the footprint(1) CLI only as click-to-drill-down. Present as
"memory footprint", never "RAM used".

## V2-3. The UX, corrected by research

Per-surface pattern library in the UX doc governs. Non-negotiables: gap-on-the-chip
("Over by ~7 GB"); verdict → reason → remedy → proceed everywhere; warn-once discipline
(alarm-fatigue research: cry-wolf trains overrides); the guardrail SPECTRUM as a setting
(our default = advisory, mirroring the field's own Relaxed lean) with the graded
override interaction; remedies live-recalc on ctx/kv-quant changes (debounced, ± bands);
headless/API paths NEVER blocked harder than the GUI (the lms#499 lesson). Copy per
§3b: our voice, zero verbatim collisions with closed-source strings.

## V2-4. Validation gate (before any verdict ships)

The research's 7-step plan executes as part of the build: predicted-vs-measured on the
resident 27B (KV at its running 65k ctx: 4 GiB, known), the 9B at 4 ctx sizes (oracle
already validated to the MiB), one MLX model, one worker peak. A gate test pins the
table; a verdict may not ship with any prediction >15% off measured without a written
argument. Estimates display the band, not false precision.
