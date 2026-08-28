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
