# Memory UX Patterns — how the best software presents fit, usage, and warnings

**Date:** 2026-08-28 · **Mission:** the UX layer of our RAM fit advisor + ledger. Philosophy is already fixed by Debi's rulings: **advisory not blocking; nuanced verdicts with remedies; parameter-aware fit.** This doc is a pattern library for the builder: what the field does, exact copy where we could extract it, what to steal, what to refuse.

Primary sources: LM Studio's shipped renderer bundle (string tables extracted verbatim from `/Applications/LM Studio.app/Contents/Resources/app/.webpack/renderer/main_window.js`) and Unsloth Studio's shipped frontend (English i18n master at `~/.unsloth/studio/.../studio/frontend/dist/assets/i18n-gD4LNAoW.js`; live instance on :8899). Everything quoted from those two is exact shipped copy, not paraphrase.

---

## 1. LM Studio end-to-end (the reference)

### 1a. Fit badges on search results — all four states, exact copy

LM Studio computes a per-file (i.e., **per-quant**) `willFitEstimation` and renders a colored badge on every downloadable GGUF/MLX file. The complete state machine, from the shipped string table (`download.option.willFitEstimation.*`):

| State key | Badge title (exact) | Hover description (exact) |
|---|---|---|
| `fullGPUOffload` | **Full GPU Offload Possible** | "This model might fit entirely in your GPU's memory. This could considerably speed up inference." |
| `partialGPUOffload` | **Partial GPU Offload Possible** | "This model might fit partially in your GPU's memory. This could often considerably speed up inference." |
| `fitWithoutGPU` | **Likely Fit** | "This model is likely to fit in your machine's memory." |
| `willNotFit` | **Likely too large** | "The memory requirements for successfully using this model file might exceed the available resources on your machine. Downloading this file is NOT recommended." |

**The hover hedge** — one shared caveat string appended to every verdict tooltip:

> "There may be other factors that prevent it from loading, such as the model's architecture, model file integrity, or the amount of memory available on your computer."

Anatomy worth copying: every title is hedged in the label itself ("Possible", "Likely"), never in fine print alone. Verdicts are **per-quant, at download time** — the badge sits next to each quant row (Q4_K_M, Q8_0, …), so the user's remedy ("pick a smaller quant") is visually adjacent to the warning. Anatomy worth rejecting: "Downloading this file is NOT recommended" (shouty caps, and it conflates *download* with *run* — downloading a too-big file is harmless), and zero numbers anywhere in the badge layer — the user never sees *how much* too large.

### 1b. Load-time: context slider + live estimate

At load time LM Studio shows a load-parameters panel (context length slider, GPU offload layers, Flash Attention, etc.) with a live **"Estimated Memory Usage"** readout, broken into **"Total"** and **"GPU"** (`loader.guardrails.estimatedMemoryUsage`, `.total`, `.gpu`). Moving the context slider re-runs the guardrail check (`checkModelGuardrails` RPC returns `{canLoad, estimatedUsageBytes, estimatedVramUsageBytes, estimatedModelUsageBytes, ...}`) and the estimate updates live. Context slider copy:

- Title: "Context Length"; info: "Specifies the maximum number of tokens the model can consider at once…"
- Inline warning: **"Setting a high value for context length can significantly impact memory usage"**

When the estimate is unavailable they say so plainly: "Memory estimate unavailable for this model" — a fifth, honest state most products lack.

### 1c. The blocking banner + graded override

When the check fails, a `ResourceGuardrailsBanner` renders:

- Headline: **"Not enough resources to load the model with the current settings"** (note: *with the current settings* — parameter-aware phrasing, the remedy is implied)
- More-info: "It appears your system does not have enough memory to load this model." / "You can adjust the model loading guardrails in settings or hold ⌥ to load anyway." / "Loading a model that is too large may overload your system and cause it to freeze."
- Plus an "Options" affordance and a checkbox: **"(Not recommended) Always allow 'Load Anyway' without holding Alt/Option"**

The **hold-Alt-to-override** is their signature move: the override always exists, but it costs a physical modifier key — friction-graded consent instead of a modal. The `bypassGuardrails` flag flows through the whole load pipeline.

### 1d. The guardrails setting — their advisory-vs-blocking spectrum

Settings → "Model loading guardrails". Exact copy:

> "Loading models beyond system resource limits may cause system instability or freezing. Guardrails prevent accidental overloading. Adjust these limits here if necessary, but be aware that loading models near the system's limit may reduce stability."

Five modes (UI label → subtitle, exact):

| Mode | Subtitle |
|---|---|
| **OFF (Not Recommended)** | "No precautions against system overload" |
| **Relaxed** | "Mild precautions against system overload" |
| **Balanced** | "Moderate precautions against system overload" |
| **Strict** | "Strong precautions against system overload" |
| **Custom** | "Set your own limit for maximum model size that can be loaded" — with "Memory Limit: ___ GB", "Models will not load if loading them would exceed this limit." |

Internally the modes are `off/low/medium/high/custom` (low=Relaxed … high=Strict; the schema literally maps `high→"strict"`). The shipped default observed in the bundle's settings defaults is **Relaxed** — i.e., LM Studio itself defaults toward the advisory end and only mildly blocks. This is the direct precedent for Debi's advisory ruling: they built a *spectrum with the user in control*, defaulted it loose, and kept a physical-gesture escape hatch even when it blocks. Where they diverge from us: their guardrail is fundamentally a **blocker with an override**, not an advisor — the framing is "precautions against overload," the UI is a refusal banner.

### 1e. Hardware / resources panel

A Hardware page (Settings → Hardware) lists RAM and VRAM capacity per device, and the chat view has a resource footer with live RAM/CPU tickers. Related per-model memory levers surfaced with honest cost framing: "Keep Model in Memory" — "Reserve system memory for the model, even when offloaded to GPU. Improves performance but requires more system RAM"; "Limit Model Offload to Dedicated GPU Memory" with ON/OFF subtitles spelling out exactly what spills to shared memory; KV-cache quantization — "Lower values reduce memory usage but may decrease quality. The effect varies significantly between models."

### 1f. What LM Studio gets wrong (per issues/reports)

- **Estimate misses, and the override isn't everywhere.** [lms#499 / bug-tracker#1631]: guardrail estimated ~22.9 GB for a model+context that *actually loads and runs* when GUI "Load anyway" is used — and CLI/REST has **no `Load Anyway` equivalent**, so headless users are hard-blocked by a wrong number. Lesson: a blocking check is only as good as its estimator, and every surface (GUI/CLI/API) needs the same override.
- **False precision without visible math.** The banner says "not enough resources" but never shows its arithmetic (what it thinks weights+KV+overhead cost vs. what it thinks is free), so users can't tell a real OOM from an estimator bug — which breeds distrust and reflexive overriding (cry-wolf).
- **Verdict without magnitude at search time.** Badges carry no numbers; "Likely too large" for a file that's 200 MB over vs. 40 GB over reads identically.
- **"NOT recommended" caps** and download-blocking framing for something that only matters at load time.
- **Fit verdicts ignore what's already loaded.** Estimates are vs. machine capacity, not vs. current availability with other models resident.

---

## 2. Ollama

CLI-native and minimal. `ollama ps` is the whole ledger: columns `NAME  ID  SIZE  PROCESSOR  UNTIL`. `SIZE` is the *loaded* footprint (weights + KV at the configured context, so it's parameter-aware without saying so). `PROCESSOR` is the fit verdict compressed into one cell: `100% GPU`, `100% CPU`, or the brutally honest split `48%/52% CPU/GPU` — partial offload rendered as a ratio. `UNTIL` shows eviction in humane relative time ("4 minutes from now"), teaching the keep-alive model in passing. Fit failure is a pre-flight refusal with numbers: `Error: model requires more system memory (446.3 GiB) than is available (443.6 GiB)` — estimate vs. free, both quantified, checked against *currently free* memory not installed capacity. **Steal:** the estimate-vs-available two-number sentence (the single best error grammar in the field), the CPU/GPU split as a fraction, and UNTIL. **Worst:** it's a hard block with no override and no remedy in the message (nothing suggests a smaller tag or lower `num_ctx`), it's invisible until failure (no advisory before pull), and third-party guides have to explain the fixes the error should have offered.

## 3. One tight paragraph each

**Jan** — Model hub tags each model "Recommended"/"Slow on your device"/"Not enough RAM"-style suitability chips against detected hardware, and v0.7.9 added automatic context-length capping to avoid OOM. **Steal:** auto-capping context to fit instead of warning — the remedy applied silently as a default (with the cap visible). **Worst:** the recommendation checker has compared against the wrong denominator (checked RAM when GPU active — janhq/jan#2339), yielding confident false verdicts; a wrong chip is worse than none.

**GPT4All** — the download list prints a static **"RAM required: 8 GB"** line per model next to file size. **Steal:** the two-number card (download size ≠ memory-to-run — users constantly conflate these; showing both kills the confusion). **Worst:** it's a hardcoded metadata field — quant-, context-, and machine-blind; no verdict, the user does the comparison in their head.

**koboldcpp** — launcher auto-guesses GPU layers (`-1` = auto, `--autofit` gauges free VRAM and sets layers/tensor-split), and newer builds show the **predicted layer count as a live overlay label** that updates as you change launcher settings. **Steal:** showing the *computed consequence* ("41/48 layers on GPU") live next to the knob, not just a byte estimate. **Worst:** the estimate is admittedly rough, the community's advice is "trial and error anyway," and it's all expert-facing dials with no plain-language verdict.

**text-generation-webui** — computes a VRAM estimate for llama.cpp models from params × context × cache type and **auto-adjusts `gpu_layers` to the maximum that fits** the detected free VRAM; the estimate updates as you change the sliders. **Steal:** "set the knob to the best value that fits" as the default behavior, with the estimate shown. **Worst:** engineer-grade UI; the estimate appears as raw numbers among ~30 other widgets, with no hierarchy or verdict.

**ComfyUI** — fully automatic "smart memory" management: weights shuffle between VRAM/RAM/disk with no user-facing fit UI at all; when the guess is wrong you get an OOM traceback and a flag-school of CLI remedies (`--disable-smart-memory`, `--reserve-vram`, `--cache-none`). **Steal:** the ambition — degrade automatically instead of refusing (their blog frames it as "dynamic VRAM"). **Worst:** total invisibility — no ledger of what is resident where, so failures are undebuggable to normal users and the GitHub tracker fills with "why is my RAM full" regressions (#12541, #8298).

## 4. Unsloth Studio (installed here; training-side reference — primary source)

Extracted from the shipped English string table; this is the closest thing to Debi's rulings already shipping.

- **Train surface: per-model VRAM verdicts with numbers and hedges.** Model rows in the train flow carry: `Needs ~{est}GB VRAM (GPU: {total}GiB)`, `~{est}GB VRAM (tight on {total}GiB)`, `~{est}GB VRAM`, plus two compact badges: **"OOM"** and **"Tight"**. Three-tier verdict (fits / tight / OOM) with the estimate *and* the denominator in one line — magnitude-honest where LM Studio is mute.
- **The readout formula — the ledger as arithmetic, shown live:** `Weights {model} + context {context} = {total} of {budget} usable VRAM` (and with speculative decoding: `Weights {model} + KV {kv} + MTP draft {spec} = {total} of {budget} usable VRAM`). Verdict lines: **"With current settings OOM likely"** and — the best advisory-verdict-with-remedy sentence found anywhere in this research — **"Larger than VRAM, will offload to CPU. A smaller quantization runs faster"**: consequence first, not refusal, remedy second, no drama.
- **Parameter-aware training warnings:** method picker hints are memory-first ("4-bit quantization. Lowest VRAM, fastest to start." / "16-bit adapters. Balanced quality and memory." / "Trains all weights. Highest quality, needs the most VRAM."), and per-hyperparameter tooltips state memory direction ("Higher uses more VRAM", "Simulates larger batch sizes without extra VRAM", "Trade compute for memory by recomputing activations"). Situational escalations: "This architecture trains in 16-bit LoRA: 4-bit is not available for it, so the run needs far more VRAM than QLoRA."
- **Ledger/monitor surfaces:** a floating GPU monitor (auto-opens on API traffic), per-device VRAM `used/free/total`, a **"Show VRAM usage bar"** option that charts *each downloaded model's* estimated use under its row — "weights, KV cache at the context it will load with, and any speculative draft reserve" — and a loaded-models card "listing every model currently in memory (chat, speech, image, video), with a button to eject each one."
- **Lifecycle honesty:** idle auto-unload ("Free VRAM after this many idle seconds. 0 keeps it loaded, minimum 60."), "Keep model in GPU memory — Stay in VRAM between prompts," and edge-case candor ("This system caps locked memory at {limit}… raise the limit with ulimit -l").
- **Gap vs. their docs' famous claims:** the docs lead with "80% less VRAM" marketing; the app itself never editorializes — it just shows the arithmetic. Right instinct. What the app lacks: the estimate has no ± band, and the OOM/Tight thresholds aren't user-tunable (no guardrails-style spectrum).

## 5. Rapid field sweep

**Msty** — deliberately a thin client over any endpoint; its model cards carry rough size/suitability hints but nothing beyond what's covered above. Skipped: nothing novel for fit UX.
**AnythingLLM / Open WebUI** — server-side chat frontends; memory is Ollama's problem underneath. Open WebUI's one notable: user-exposed keep-alive/unload controls per model. Otherwise skipped: no fit verdicts of their own.
**Backyard AI** — model manager reportedly tags recommended models for your hardware, but no verifiable copy or documentation surfaced; skipped as low-signal.
**llamafile / RamaLama** — single-file/container runners; RamaLama's notable idea is *detecting* the GPU stack and pulling the right runtime automatically (fit-by-construction), but neither has memory-fit presentation. Skipped.
**Nvidia ChatRTX** — the anti-pattern exhibit: a hard 8 GB VRAM install gate; below it the product simply won't run, and users file forum requests begging for "adjustable system requirements / VRAM scalability." Blocking at its purest — include only as a cautionary citation.
**Web VRAM calculators** (vramcalc.com, willitrunai.com, hardwarehq.io, apxml…) — an entire cottage industry exists because runners don't show their math. Their shared grammar: pick model + quant + context → live-updating total with a per-component breakdown and a GPU-model comparison table. The demand proof for our ledger view.

## 6. OS-level reference UX

**Activity Monitor memory pressure** — the canonical proof that *pressure, not usage,* is the honest metric. The graph is a composite of free RAM, compression ratio, and swap activity — not a fill bar. Semantics: **green** = "your computer is using all of its RAM efficiently" (full RAM can be green — full is healthy); **yellow** = "might eventually need more RAM" — compression underway, consider closing things; **red** = "needs more RAM" — swapping, act now. Three states, each phrased as *what it means for you*, never a percentage. Direct steal for our memory strip: a full ledger is not a warning; only pressure is.

**iStat Menus / Stats menubar** — at-a-glance grammar: one tiny always-visible glyph (pie/bar/pressure graph) in the menubar → click for a rich popover (usage, pressure, swap, compressed, top-5 memory apps with the implied remedy "quit one of these") → deep view in the app. Three disclosure levels, and the detail includes *actionable culprits*, not just totals.

**Game launcher min/rec spec grammar** — the oldest fit-verdict UX: a two-column **Minimum / Recommended** table, per-component rows (GPU / RAM / storage). Why it works: two tiers turn a binary into a gradient ("will it run" vs. "will it run well"); per-component rows localize the failure ("your GPU is the problem, not your RAM"); and named tiers set expectations before purchase. Known failure, per community consensus: "Minimum often means 'it will launch,' not 'it will be playable'" — which spawned third-party verdict engines (Can You Run It, sysrqmts) whose whole product is comparing *your* hardware against the table and highlighting the failing component. Lessons: (1) requirements tables without a personalized verdict push the comparison work onto the user; (2) tier names must map to *experience* ("runs" / "runs well"), not legal cover.

## 7. Warning & consent copy patterns

**The four-part grammar that works** (visible in the best examples above): **verdict → reason → remedy → proceed.** Ollama has verdict+reason with numbers but no remedy/proceed; LM Studio has verdict+proceed but hides the numbers; Unsloth's "Larger than VRAM, will offload to CPU. A smaller quantization runs faster" nails verdict+consequence+remedy and, being advisory, needs no proceed. Nobody ships all four. We will.

**Progressive disclosure:** chip (2–4 words, hedged, colored) → hover/tap (one-sentence reason + the two numbers) → full breakdown (component arithmetic à la Unsloth's readout / the VRAM-calculator grammar). LM Studio's badge→tooltip→banner and iStat's glyph→popover→app confirm three levels is the norm; each level must add numbers, not just words.

**Anti-patterns, with exhibits:**
- *Scary modal / hard gate:* ChatRTX's VRAM floor; LM Studio's CLI hard-block with no override (lms#499). A gate that's ever wrong destroys all future trust.
- *False precision:* single-figure byte estimates presented as truth ("22.92 GB" that loads fine). Estimates need `~` and a band, or they need the math shown.
- *Cry-wolf:* the alarm-fatigue literature is unambiguous — clinicians override 49–96% of drug-interaction alerts because most are noise; browser-SSL research made "warn rarely, mean it" the doctrine. Every wrong "Likely too large" trains the user to alt-click through the real one. Warn only on the tier that changes behavior, and never re-warn on a choice the user already acknowledged (LM Studio's "always allow Load Anyway" checkbox is their apology for re-warning).
- *Verdict without magnitude:* a red chip that reads identically at 0.2 GB over and 40 GB over.
- *Warning at the wrong moment:* blocking *download* for a *load-time* problem.

## 8. Live-recalc interaction grammar

Where a parameter change live-updates a resource estimate (LM Studio load panel, koboldcpp overlay, textgen-webui, Unsloth readout, every web VRAM calculator), the shared grammar:

- **Recalc on every change, render debounced** (~100–300 ms feel; estimates are arithmetic, so compute is instant — the debounce is visual, to stop number-flicker while dragging).
- **Units:** GB with one decimal; `~` prefix on every estimate; keep the denominator visible ("of 24 GB usable"). Unsloth's `= {total} of {budget}` and Ollama's "(446.3 GiB) than is available (443.6 GiB)" are the models. Beware GB/GiB mixing (Unsloth mixes them in one string — don't).
- **± bands:** effectively nobody ships them (closest: hedge words and `~`). Shipping "≈ 9.8–11.2 GB" would be a genuine differentiator; at minimum, `~` plus a footnote of what's excluded from the estimate.
- **Verdict re-derives with the number:** the chip flips fits→tight→won't-fit as the slider moves — the user *watches* the boundary, which teaches the mental model better than any docs (koboldcpp's live layer count is this in expert form).
- **Show the consequence, not just the total** where possible: "41/48 layers on GPU", "will offload to CPU", "auto-capped context to 16k".

---

## 9. PATTERN LIBRARY — per-surface recommendations for our builder

Editorial voice for all copy: calm, numeric, second-person-optional, hedge in the words not the punctuation, remedy in the same breath as the verdict. Never caps, never exclamation, never "NOT recommended." Chips, not walls. A verdict is one line; arithmetic lives one level down.

### 9.1 Search / catalog results (per model, per quant)

**States (5):** `fits-gpu` · `fits` (RAM/unified, or partial offload) · `tight` · `over` · `unknown` (estimate unavailable — always an explicit state, never a silent green).

**Chip copy grammar** — `{verdict} · ~{est} GB` (magnitude always on the chip):
- `Fits · ~6.4 GB` (green)
- `Fits, partial GPU · ~9 GB` (green, when split)
- `Tight · ~13 GB of 16` (amber — denominator appears the moment it matters)
- `Over by ~7 GB` (red — the *gap*, not just the total; this is the number the user actually needs)
- `No estimate` (gray)

**Hover (level 2):** one sentence, both numbers, one hedge, one remedy. Grammar: *"Needs about {est} GB at {ctx} context; {avail} GB usable now. {remedy}."* e.g. "Needs about 13 GB at 8k context; 14.2 GB usable now. Q4 of this model runs comfortably." Add one shared caveat line (our version of LM Studio's hedge): "Estimate — architecture and what's already loaded can move this."
**Disclosure:** chip → hover sentence → tap opens the per-quant table with fit chips per row (LM Studio's per-quant verdicts, plus our numbers).
**Visual:** chip after the size figure; download size and run size are *both* shown (GPT4All's two-number lesson). Fit is computed against **usable-now** (Ollama's lesson), with hover noting when a currently-loaded model is the reason.
**Never:** block or shame the download. Red chip + honest gap + remedy, and the download button stays plain.

### 9.2 Installed-models list

**Each row:** name · quant · disk size · a **passive fit chip at its default load config** (same grammar as 9.1) · if currently loaded: footprint + placement split (`4.1 GB · 100% GPU`, or `60/40 GPU/RAM`) + idle-unload countdown if any (Ollama's UNTIL, humanized: "unloads in 4 min") + eject button (Unsloth's loaded-models card).
**Optional bar** (Unsloth's steal, our best visual): a slim stacked bar under each row — weights + KV-at-configured-context — against the usable budget line. Off by default, one toggle: "Show memory bars."
**Disclosure:** row → expand for the arithmetic line: `Weights 5.9 + context 1.8 = 7.7 of 21 GB usable`.

### 9.3 Load consent (the moment that embodies the advisory ruling)

**States:** `fits` — load silently, no ceremony, ledger updates. `tight` — load proceeds, one non-blocking inline notice: *"Will be tight: ~15.1 of 16 GB after loading. Other apps may slow. Lower context to 8k for ~2 GB headroom."* `over` — load pauses on an **inline panel, not a modal**:

> **Probably won't fit** — needs ~19 GB, ~14 GB usable now.
> Why: 8-bit weights (12.4 GB) + 32k context (6.2 GB).
> — Load Q4 instead (~10 GB) · — Drop context to 8k (~13.9 GB) · — Free 5 GB: eject Qwen-14B ·
> **Load anyway** (plain button, always present, never modifier-gated — but it *does* say what to expect: "may swap heavily; system can stall")

Verdict → reason → remedies (each with its post-remedy number, tappable to apply) → proceed. The remedies are LM Studio's missing half; the always-available proceed is our ruling; the expected-consequence phrasing is Unsloth's "will offload to CPU" honesty. If the user proceeds on `over`, remember it for that model+config and **don't re-warn** (cry-wolf rule) — show the tight-state notice thereafter.
**Live-recalc in this panel:** ctx slider and quant picker are right there; estimate and verdict re-derive as they move (visual debounce ~200 ms, `~` on all figures, denominator fixed on screen).

### 9.4 Memory strip (always-visible, app chrome)

**Pressure, not fill** (Activity Monitor's lesson). One compact segment: a small bar or dot in three states — calm / elevated / critical — derived from a composite (usable headroom + swap activity), plus the single most useful number: `9.7 GB free`. Full-but-calm shows **calm**.
**States & copy (tooltip):** calm — "Memory is comfortable. 9.7 GB usable."; elevated — "Getting tight — 2.1 GB usable. Ejecting an idle model would free 4 GB."; critical — "Swapping now. Eject a model or expect stalls." Culprit-plus-remedy in the tooltip (iStat's top-apps lesson, scoped to *our* residents).
**Disclosure:** strip → tooltip → click opens the full ledger. The strip never animates to grab attention except on entering critical, once.

### 9.5 Full ledger view

The place where all arithmetic is visible — our answer to the VRAM-calculator cottage industry.
- **Top: budget line.** Total unified/VRAM → reserved (OS + our floor) → **usable** — stated as a sum, in one line, so "usable" is never a mystery number.
- **Stacked residents:** every loaded artifact (chat, embedding, STT, image — Unsloth's cross-modality completeness) as a stacked horizontal bar: weights / KV / draft-reserve segments, each labeled, each with eject. Non-model pressure (other apps) as a hatched segment, honest that it's an estimate.
- **What-if row:** a phantom entry — "if you load X at ctx Y" — rendered translucent on the same bar; this is where search/load surfaces deep-link.
- **History sparkline** (pressure over the session) and the eviction schedule (which model unloads when, and why).
- **Copy grammar throughout:** the Unsloth readout sentence, our voice: `Weights 5.9 + context 1.8 + draft 0.4 = 8.1 of 21.3 GB usable`. Every estimate `~`-prefixed; GiB/GB picked once (GB, one decimal) and never mixed.

### 9.6 Settings: our advisory spectrum

We keep a spectrum like LM Studio's but flip the frame from "precautions" to *when to speak up*: **Quiet** (verdict chips only, never a load-time panel) · **Advise** (default — chips + the 9.3 consent panel on `over` only) · **Advise early** (panel on `tight` too) · **Custom headroom** (reserve N GB). No mode ever removes the Load-anyway button; there is no "off" because nothing blocks. One extra: "Don't warn again for models I've overridden" — on by default.

---

## 10. What LM Studio gets wrong that we will get right

1. **Blocking with a wrong number → we advise with the math shown.** Their guardrail hard-refuses on an estimate that's demonstrably wrong at times (lms#499), and headless surfaces have no override. Ours never blocks, and every verdict exposes its arithmetic — an estimator error is visible and correctable, not a wall.
2. **Verdicts without magnitude → gap numbers on the chip.** "Likely too large" says nothing about *how much*. We print `Over by ~7 GB` at the first level of disclosure.
3. **Warning without remedy → remedy buttons with post-remedy numbers.** Their banner offers settings-or-alt-key; ours offers "load Q4 (~10 GB) / drop ctx to 8k / eject X to free 5 GB," each one tap.
4. **Fit vs. machine capacity → fit vs. usable-now.** We compute against current availability including loaded residents (Ollama's semantics), and say which resident is the reason.
5. **Download-time scolding → load-time advice.** No "NOT recommended" on downloads; disk is cheap, the verdict belongs to the load moment (and to a calm chip before it).
6. **Modifier-key consent → plain, honest consent.** Hold-Alt is clever but hidden; our Load-anyway is a visible button whose label states the expected consequence.
7. **Re-warning forever → warn once, remember the override.** Cry-wolf discipline: an acknowledged risk is not re-litigated.
8. **GUI-only mercy → parity across surfaces.** Same verdicts, same override, same numbers in UI, CLI, and API.
9. **No unknown-state honesty at search time → "No estimate" chip.** They have the string at load time; we surface uncertainty everywhere rather than defaulting to green.
10. **Capacity-only hardware panel → pressure-based strip + full ledger.** Activity Monitor semantics (pressure, three meanings-for-you states) plus Unsloth's component arithmetic, unified.

---

## Sources

**Primary (local, read-only):**
- LM Studio.app renderer bundle string tables — `/Applications/LM Studio.app/Contents/Resources/app/.webpack/renderer/main_window.js` (all §1 quotes verbatim; guardrail schema `off/relaxed/balanced/strict/custom`; `guardrailCheckResultSchema`; defaults)
- Unsloth Studio shipped frontend — `~/.unsloth/studio/unsloth_studio/lib/python3.13/site-packages/studio/frontend/dist/assets/i18n-gD4LNAoW.js` (all §4 quotes verbatim); live instance `http://localhost:8899`

**Web:**
- [LM Studio guardrail estimate wrong / no CLI Load-anyway — lms#499](https://github.com/lmstudio-ai/lms/issues/499) · [bug-tracker#1631](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/1631)
- [LM Studio per-model defaults docs](https://lmstudio.ai/docs/app/advanced/per-model) · [LM Studio hardware guide (substack)](https://hakedev.substack.com/p/the-complete-guide-to-lm-studio-hardware) · [NVIDIA on LM Studio offload](https://blogs.nvidia.com/blog/ai-decoded-lm-studio)
- [Ollama OOM error format — ollama#8667](https://github.com/ollama/ollama/issues/8667) · [ollama#7423](https://github.com/ollama/ollama/issues/7423) · [LLM Configurator: ollama memory error guide](https://llmconfigurator.com/en/guides/troubleshooting/ollama-more-system-memory)
- [Jan hub recommendation bug — jan#2339](https://github.com/janhq/jan/issues/2339) · [Jan troubleshooting](https://www.jan.ai/docs/desktop/troubleshooting)
- [GPT4All models & RAM requirements — llm-gpt4all](https://pypi.org/project/llm-gpt4all/) · [GPT4All FAQ](https://docs.gpt4all.io/gpt4all_help/faq.html)
- [koboldcpp auto GPU layers — #390](https://github.com/LostRuins/koboldcpp/issues/390) · [koboldcpp wiki](https://github.com/LostRuins/koboldcpp/wiki) · [releases (predicted-layers overlay)](https://github.com/LostRuins/koboldcpp/releases)
- [textgen-webui VRAM estimation & auto gpu-layers — DeepWiki](https://deepwiki.com/oobabooga/text-generation-webui/8.2-performance-optimization-and-vram-management)
- [ComfyUI dynamic VRAM blog](https://blog.comfy.org/p/dynamic-vram-in-comfyui-saving-local) · [smart-memory OOM discussion #14462](https://github.com/Comfy-Org/ComfyUI/discussions/14462) · [memory regression #12541](https://github.com/Comfy-Org/ComfyUI/issues/12541) · [overcommit #8298](https://github.com/Comfy-Org/ComfyUI/issues/8298)
- [Apple: check if your Mac needs more RAM (memory pressure)](https://support.apple.com/guide/activity-monitor/check-if-your-mac-needs-more-ram-actmntr34865/mac) · [OS X Daily on pressure colors](https://osxdaily.com/2026/04/27/how-to-tell-if-a-mac-needs-more-ram-using-memory-pressure/)
- [iStat Menus](https://bjango.com/mac/istatmenus/) · [iStat Menus 7 review](https://thesweetbits.com/tools/istat-menus-review/)
- [System Requirements Lab / Can You Run It](https://www.systemrequirementslab.com/cyri) · [sysrqmts](https://sysrqmts.com/) · [essay on why it works](https://webiano.digital/the-oddly-useful-website-that-judges-your-gaming-pc/)
- [Alarm fatigue — Wikipedia](https://en.wikipedia.org/wiki/Alarm_fatigue) (49–96% override rates) · [Atlassian on alert fatigue](https://www.atlassian.com/incident-management/on-call/alert-fatigue) · [UX Collective: alerting without overwhelming](https://uxdesign.cc/how-to-design-to-alert-users-without-overwhelming-them-4bb41feda9f0)
- [ChatRTX VRAM-gate complaint thread](https://forums.developer.nvidia.com/t/request-for-adjustable-system-requirements-vram-scalability/325679)
- VRAM calculator field: [vramcalc.com](https://vramcalc.com/) · [willitrunai](https://willitrunai.com/blog/vram-requirements-for-ai-models) · [hardwarehq](https://hardwarehq.io/vram-calculator)
- Field sweep context: [local-llm.net comparisons](https://www.local-llm.net/compare/) · [Msty overview](https://www.local-llm.net/tools/msty/)
