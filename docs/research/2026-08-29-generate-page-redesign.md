# Generate page redesign — research for spec v2

**Date:** 2026-08-29 · **Author:** research agent (Fable brief) · **Status:** findings + proposed IA, no code changed
**Trigger:** Debi's verdict on the shipped /comfy page (v1.5.36): "really looks a bit like a disaster…
even feels and looks sort of worse than comfyui… what's with the 'license text', and the 'graph'
button… Even apps like Draw Things that look simple… didn't even reach."
**Read for this doc:** `docs/FABLE-COMFY-SURFACE-SPEC.md` · `docs/research/2026-08-29-comfyui-tab.md` ·
`bridge/panel/comfy.html` (shipped) · `docs/FABLE-STUDIO-DESIGN-SPEC.md` · `docs/USER-EXPLAINERS.md`
(Generate section) · github.com/pbakaus/impeccable · the v1.5.34 commit message (chip-first) ·
v1.5.36 commit message (what shipped and why).
**Doctrine 8b (Debi, 2026-08-29, binding here): an example is not the spec.** Draw Things was an
example Debi *named*, not the design target. The survey therefore spans local SD frontends,
polished commercial generation UIs, the native-macOS creation-tool lens, and the A1111
anti-pattern; the **governing lens is ours** — impeccable, the Studio design spec, the Editorial
voice, and the v1.5.34 chip-first grammar. Where the field converges the proposal adopts; where
it diverges the proposal argues from our principles, never from any one app's popularity. §4.0
carries the decision→evidence traceability table.

---

## 0. TL;DR

The shipped page is honest and mechanically sound, and it is the **Models view before v1.5.34**:
every verdict is a paragraph, every caveat is card prose, every button carries its essay. v1.5.34
already cured this exact disease elsewhere in the app — *rows carry only the verdict chip; the
sentence, the arithmetic and the hedge live in a styled tooltip; one verdict object so chip and
hover cannot contradict* — and the Generate page ignored that grammar completely.

Eleven products were surveyed — local SD frontends (Draw Things, Fooocus, SwarmUI, InvokeAI,
Krita AI, ComfyUI's own App Mode), the commercial UIs (Midjourney web, Ideogram, Firefly, with
Leonardo as the deliberate pro-tool counter-example), the native-macOS lens (Pixelmator/Photomator,
Image Playground), and A1111 as the anti-pattern. The ten that non-technical people praise
converge on one shape:

> **AT REST:** prompt + Generate + the picture. **ONE TAP:** settings and models. **BURIED:** everything else.

The proposal in §4 is that shape argued from OUR principles (doctrine 8b: the field corroborates,
it does not govern) in the Editorial/Studio language, with the v1.5.34 chip grammar carrying all
of the page's honesty (sha, disk, licenses, measured runs, the Wan defect) into hovers and a
compact model sheet — nothing honest is deleted, everything honest is demoted from prose to
chip+tooltip. §4.0 traces every decision to its principle and its evidence. §5 maps each
surviving mechanic to its new home. §6 lists the real forks for Debi.

---

## 1. Diagnosis — owning the shipped page's sins precisely

Read from `bridge/panel/comfy.html` (comfy-s1-2026-08-29a). With the two curated models on disk
and nothing running, the page at rest shows roughly **sixty discrete text elements**. The honest
mechanics underneath are right (see §5); the surface is wrong in five specific, recurring ways:

1. **Paragraph-length warnings ON the cards.** The Wan colour-defect verdict is a full
   `.verdict.tight` sentence on the card *and repeated* beside the Generate button. The corrupt-file
   case is a two-sentence warnbox. The measured-run line carries the parenthetical essay
   "(measured phys_footprint of the ComfyUI process, not an estimate)" *on every card, always*.
   v1.5.34's whole point: the chip states the verdict; provenance wording lives in the hover.
2. **License plumbing in the user's face.** Each card wears a license badge (fine) **plus** a
   "licence text ↗" link as a third action in the button row — a legal-document link given equal
   rank with Download. The cap-line above the cards narrates sha256/HEAD-verification mechanics in
   two sentences of body copy, for every visitor, forever.
3. **File-path tables.** Every card lists each weight file as `directory/filename` in mono plus
   size plus state, with shared-file sub-rows — an installer's manifest rendered as marketing copy.
   The gallery caption prints the absolute output directory in mono in its intro line. The footer
   prints both storage paths again.
4. **Measurement prose everywhere.** "never run on this Mac — the next one is the measurement,
   so it may take a while", "Frame counts snap to 4n+1 — this model's latents move four frames at
   a time…", "One job at a time — ComfyUI runs them in order. You can leave this tab; the result is
   waiting when you come back." Each of these is a true sentence that belongs in a hover or in Help
   — and nearly all of them **already exist in `docs/USER-EXPLAINERS.md` §Generate**, so the page
   is duplicating Help onto the canvas.
5. **Per-button essays and power-user affordances at full rank.** "Open template in ComfyUI" sits
   beside Download on every card; "Graph" sits on every gallery item next to Reveal. Both are
   power-exit affordances shown to the exact user this page exists to shield. The footer is a
   security essay (stock-nodes/supply-chain) shown on every load.

What is **not** wrong: the token discipline (ALL-DESIGNS holds — six looks resolve through
tokens), the cadence rule, per-section render isolation, and every underlying honesty mechanism.
This is an information-architecture failure, not a theming or plumbing failure. The fix is
demotion, not deletion.

Also structural: the page is four stacked co-equal sections (Models · Make something · Running ·
Gallery) plus a footer. The *product* is "Make something"; on the shipped page it is the second
item, below a wall of acquisition cards. Draw Things, Fooocus, and App Mode all put the prompt
and the picture first and let acquisition be a visit, not a residence.

---

## 2. Comparative patterns

### 2.1 Draw Things (the example Debi named — one datapoint, not the target)

The local-first native reference: on-device Stable Diffusion for Apple platforms, App Store
4.4/5, praised precisely for the no-terminal happy path ("No Python, no virtual environments,
no terminal" — thinkdifferent.blog).

- **First open:** the app immediately offers the default model download **with the exact size
  shown** ("1641.53 MiB" in GIGAZINE's 2022 hands-on); after that one confirmation the user is
  on a working generate screen. Cold-start funnel: open → one size-labeled download prompt →
  type prompt → Generate.
- **At rest (Mac/iPad, current UI per the official wiki's User Interface page):** canvas center;
  Positive+Negative prompt box with the Generate button ("Stars icon, bold orange color") at its
  lower-right; a Settings sidebar showing a model dropdown + ~5 core sliders (Steps, Text
  Guidance, Size, Sampler, Strength); a Configurations preset picker; a file bar; Version History
  on the right. On iPhone both side menus collapse behind icons, leaving essentially canvas +
  prompt + Generate.
- **The core disclosure mechanism:** the Settings sidebar has a three-way verbosity switch —
  **Basic / Advanced / All**. Basic shows model + key sliders; Advanced surfaces img2img and
  upscalers; All is the long tail (seed, shift, refiner…). Progressive disclosure as a *user
  setting*, not a per-control scatter.
- **Model handling:** management lives *inside* the generate screen — model dropdown → "Manage"
  opens a popup with **Official and Community sections**; app-hosted models download with one tap
  on a cloud icon, sizes stated, data-usage warning before large ones. Switching to an
  undownloaded model triggers the same size-labeled prompt in place. **License display: not
  found in any source — unverified, possibly absent.** Import-your-own is the documented rough
  edge ("it gets really complicated" — greggant.com).
- **Progress:** per-step tiles ("watch orange squares turn blue") + live canvas preview per step
  + an ETA that **recalculates after the first step** (GIGAZINE 2025 watched it jump from
  ~1 min to 30+ min on a 20 GB model — i.e. measured-rate ETA, same instinct as our
  LIES-TO-USER rule). Errors: thin in sources; no dedicated error-states docs. Unverified.
- **The honest counterweight:** reviewers also say "the interface looks kind of confusing" and
  the model picker's "grid layout is worthless, I can't read the full file names" (greggant.com);
  AlternativeTo notes a learning curve on advanced tools. The happy path is one-download-one-tap
  simple; the density concentrates in All mode and importing. Draw Things is therefore a bar to
  *clear*, not a design to copy — even the example app fails our sheet-legibility bar in places.
- Sources: wiki.drawthings.ai (User_Interface, Quick_Start, Basic_Settings,
  Install_a_Model_or_LoRA) · gigazine.net 2022 + 2025 hands-ons · App Store listing ·
  blog.greggant.com 2024 tutorial · thinkdifferent.blog · github.com/drawthingsai/community-models

### 2.2 Fooocus — the canonical "MidJourney-simple over SD"

- **At rest:** one page — image output/gallery area on top, prompt box with an orange **Generate**
  button beside it, and exactly two small checkboxes below: **Advanced** and **Input Image**.
  No visible sliders, no model picker, no sampler settings. That is the entire default surface.
- **Where complexity lives:** the **Advanced** checkbox opens a right panel with tabs — Setting
  (performance preset, aspect ratio, count, negative, seed), Style (curated presets), Model
  (checkpoint/LoRA), Advanced (guidance/sharpness/debug). The heavy engineering (GPT-2 prompt
  expansion, tuned samplers, negative ADM guidance) is **baked in as defaults, not exposed as
  controls**.
- **Model management:** none in the generate flow. First launch **auto-downloads** the preset's
  default checkpoint; the inpaint model downloads lazily on first inpaint use. Switching lives in
  Advanced → Model.
- **Stated philosophy (README):** "similar to many online image generators like Midjourney, the
  manual tweaking is not needed, and users only need to focus on the prompts and images"; and
  "between pressing 'download' and generating the first image, the number of needed mouse clicks
  is strictly limited to less than 3."
- Sources: github.com/lllyasviel/Fooocus · stable-diffusion-art.com/fooocus ·
  techtactician.com/stable-diffusion-fooocus-guide-part-2-image-generation

### 2.3 SwarmUI — the Generate tab over Comfy backends

- **At rest:** prompt box bottom-center, purple Generate button, large central image display, a
  left column of **grouped, collapsible** parameters (core/resolution open; refiner, init-image,
  ControlNet etc. collapsed/toggled until enabled), bottom panel with sub-tabs (Models, history).
  Every parameter carries a small `?` linking to its explanation — **the essay is one click away,
  never on the panel**.
- **Advanced gate:** a "Display Advanced Options" checkbox gates the long tail; the raw ComfyUI
  graph is a whole separate **Comfy Workflow tab** (the power exit as a *place*, not a button on
  every card).
- **Model management split twice:** *selecting* = a Models sub-tab under Generate;
  *acquiring* = a downloader in a separate **Utilities** tab (HF/Civitai URL). Core components
  auto-download during setup.
- Caveat: exact default open/closed state per group only partially verified from docs.
- Sources: github.com/mcmonkeyprojects/SwarmUI · its docs/Basic Usage.md

### 2.4 InvokeAI — the linear UI

- **At rest:** three regions — left Settings Panel (accordion sections: model, generation, size,
  reference images, LoRAs, an **Advanced** section holding the ControlNet-class options), center
  viewer, right Gallery organized into Boards. A vertical tab rail separates **Generate / Canvas /
  Upscaling / Workflows / Models / Queue** — model management and the queue are **their own tabs**,
  not sections stacked on the generate page.
- **The graph is quarantined** in the Workflows tab, which itself has "Add to Linear View":
  right-click any node input to promote just that field into a simple form — author-curated
  simplicity over a graph, same idea as our slot-map templates.
- **Model manager:** browse/install from URL/HF/Civitai with its own install queue and progress;
  starter-model suggestions on first run. Nothing about acquisition appears in the generate flow
  beyond the model dropdown.
- Caveat: per-section collapse defaults unverified (their support site was unreachable).
- Sources: invoke.ai/features/gallery · invoke.ai/releases (6.13.0) · github.com/invoke-ai/InvokeAI

### 2.5 Krita AI plugin — the most radical demotion

- **At rest, in the docked panel:** a Style dropdown, a prompt field, a strength slider, a
  Generate button. Four controls. No sampler, no CFG, no resolution, no model names.
- **Where complexity lives:** in **Styles** — named presets bundling checkpoint + LoRAs + sampler
  + steps + CFG + VAE, edited in a separate configuration dialog. The panel deliberately stays at
  "prompt + strength + generate".
- **Model management happens at setup time, outside the flow entirely:** a "Configure" button
  opens an installer that downloads a managed ComfyUI server **plus required models
  automatically**. There is no model-download UI in the painting flow at all.
- **README philosophy:** "an unobtrusive tool that integrates and synergizes with image editing
  workflows"; "strong defaults" while letting users "customize presets, bring your own models."
- Source: github.com/Acly/krita-ai-diffusion

### 2.6 ComfyUI's own answer — templates, subgraphs, App Mode

- **Template browser** (shipped, in our pin): categorized workflow cards; loading one
  auto-checks required model files and (on desktop) offers a **Download button per missing
  file** — model name/URL/dir embedded in node properties. Acquisition is a *dialog that appears
  exactly when needed*, not a standing section.
- **Subgraphs** (2025): fold node clusters into one node; the author curates **which widgets are
  visible and in what order** via the Subgraph Parameter Panel.
- **App Mode + App Builder** (announced ~2026-03): the graph "disappears and is replaced by a
  clean, purpose-built interface: just the inputs your user needs"; the author picks which inputs
  are exposed, "everything else stays in the graph… invisible to the end user, locked in place."
  Upstream's own verdict on what a non-technical Comfy surface is: **a form with the graph gone**.
- Sources: docs.comfy.org/interface/features/template · blog.comfy.org/p/subgraph-official-release ·
  blog.comfy.org/p/from-workflow-to-app-introducing · docs.comfy.org/interface/app-mode

### 2.7 AUTOMATIC1111 — the anti-pattern, and which of its sins our page repeated

The A1111 txt2img tab renders, at full rank, before the first image: the checkpoint dropdown as
the app's *first* control; a tab row where **Checkpoint Merger and Train sit co-equal with
txt2img**; prompt + negative prompt + styles; sampler and schedule dropdowns (pure jargon,
unexplained in-UI); steps, Hires. fix (expanding), Refiner, width/height, batch count *and* batch
size, CFG, a three-affordance seed row, a Script dropdown (X/Y/Z plots) — ~20 controls plus 8
tabs, with 300+ options in Settings. Model management is folder-drop ("Put the file into
`models/Stable-Diffusion`" — the official wiki's literal instruction). Errors are raw tracebacks
(`torch.cuda.OutOfMemoryError… PYTORCH_CUDA_ALLOC_CONF` advice) leaking into the UI; issue #3841
documents an OOM freezing the whole page with Interrupt dead. Beginner-routing reviews are
unanimous ("over 300 options … overwhelming for beginners" — propelrc), and Fooocus's README is
the field's explicit corrective ("users can forget all those difficult technical parameters").

**Its named failure modes, mapped against our shipped page:**

| A1111 failure mode | Did comfy.html repeat it? |
|---|---|
| Everything at full rank, no staging | **Yes, in prose form** — every caveat/verdict/manifest as standing copy; acquisition cards above the composer |
| Jargon with no in-UI explanation | Inverted — we over-explain instead of under-explaining; the reader's screenful is equally spent either way |
| Power features co-equal with basics | **Yes** — "licence text ↗" beside Download; "Graph" beside Reveal; "Open template in ComfyUI" on every card |
| Model plumbing first on screen | **Yes** — Models is the first section; the checkpoint-dropdown-first mistake, in card form |
| Raw internals as standing UI | **Partly** — file paths and phys_footprint provenance printed at rest (our *errors*, unlike A1111's, are honest and named — that part must survive) |

Fair note: one comparison (techtactician) calls A1111 "simple" *relative to ComfyUI's graph* —
the anti-pattern is specifically about beginner onboarding, which is exactly this page's charter.
Sources: github.com/AUTOMATIC1111/stable-diffusion-webui/wiki/Features ·
papayabytes.substack.com/p/automatic1111-txt2img ·
propelrc.com/comfyui-vs-automatic1111-vs-fooocus · A1111 issue #3841 · Fooocus README.

### 2.8 The native-macOS lens — Pixelmator Pro / Photomator / Image Playground

The platform's own answer to "ML for non-technical people", and the closest cultural fit for a
Mac-native motdeck (Pixelmator is Apple-owned since 2024; pixelmator.com now 301s to
apple.com/pixelmator-pro):

- **One named verb per capability, in context.** Remove Background is a single menu item, zero
  configuration; ML Super Resolution is one command (PetaPixel's "real-life Enhance! button");
  ML Enhance is one click adjusting 30+ parameters invisibly. No ML panel of knobs exists at rest.
- **Zero-to-one controls, exposed AFTER the result.** Photomator's Smart Deband has "no controls;
  you just run it and see the results"; Denoise shows exactly one Intensity slider, *after* the
  ML pass, non-destructive (DPReview 3.1 review).
- **The deepest mechanic — automation writes into ordinary controls.** ML Enhance "manipulates
  their associated sliders, so you can re-adjust them": the automatic result lands in the same
  controls the user could have moved by hand, so there is no separate expert mode to graduate
  into. Our analog, adopted in §4.1: a run's *actual* values (the snapped 4n+1 frame count, the
  seed used, the resolved size) land in the result's caption chips and write back into the
  More ▸ fields — the honest record IS the editable state.
- **Apple Image Playground at rest:** a "Describe an image" field + tappable concept chips + a
  Style picker + person/photo pickers — about five affordances, no seed/steps/sampler/resolution
  anywhere; generation shows swipeable preview candidates, not a progress log. Apple's frame:
  "built from the ground up to be easy to use … suggestions, quick previews."
- Caveats: no Pixelmator manifesto says "progressive disclosure" verbatim — the mechanics are the
  citation; Image Playground's blank-canvas layout is assembled from Apple's step docs, not
  screenshots.
- Sources: apple.com/pixelmator-pro · dpreview.com Photomator 3.1 review · petapixel.com
  2019-12-18 · support.apple.com mac-help/mchld5412d00 · apple.com/newsroom 2024-12 ·
  macrumors.com 2024-11-01.

### 2.9 The commercial generation UIs — four complexity-hiding strategies

All login-gated; inventories rest on official help docs + walkthroughs (caveats in §7).

- **Midjourney web** (docs.midjourney.com · howtogeek.com walkthrough): one **Imagine bar** at the
  top of Create with an image-upload affordance and ONE settings icon; results as a
  reverse-chronological feed below. The pop-out holds everything: Image Size, three Aesthetics
  sliders (Stylization/Weirdness/Variety), Model version + Standard/Raw + Draft + Speed — and its
  settings are **sticky defaults**. The Discord-era `--parameter` text language still works typed
  into the prompt: **the power exit is a syntax, not a panel** — invisible to everyone who doesn't
  type it. Strategy: *one bar + one drawer + a parallel expert language.*
- **Ideogram** (docs.ideogram.ai): prompt box atop a community feed; a compact control row under
  the prompt (model, speed, count, aspect, Magic Prompt toggle, visibility); ONE "More settings"
  expander for style/character refs, palette, seed, negative, tile. Two details worth stealing:
  **Magic Prompt** absorbs prompt-writing skill ("you don't need a perfect prompt"), and active
  hidden state (style/character refs) **surfaces back as thumbnails pinned near the prompt** —
  hidden settings stay visible when they are non-default. Strategy: *compact row + one expander +
  state echo.* (Our More ▸ dot in §4.1 is the same state-echo idea.)
- **Adobe Firefly** (helpx.adobe.com): the signature move is **temporal staging** — before the
  first generation the screen is a prompt bar plus a Try-prompt inspiration gallery, *zero
  settings*; the full properties panel (model, aspect, content type, a ~63-thumbnail Styles
  gallery, color/lighting/camera presets, intensity slider) **appears only with the first
  results**. Style keywords typed in the prompt are auto-detected and mapped onto panel presets,
  keeping text and GUI synchronized. Strategy: *no controls until there is a result to control.*
- **Leonardo.ai** (the deliberate counter-example): a dense left panel at rest — model selector,
  presets, count, dimensions, negative toggle, guidance/seed/pipeline switches — the pro-tool
  pole; reviewers frame it as "a comprehensive workshop" vs competitors' "simple path to a
  beautiful image". Proof the field has both poles and that Debi's verdict places this page at
  the other one.
- **Recraft / Freepik** (brief): Recraft is a Figma-style canvas where generation is one tool
  among many (prompt panel + saved-style system); Freepik's headline control is **which vendor's
  model** (40+ engines) — an aggregator IA. Neither shape fits a one-engine curated surface;
  noted for completeness.
- Sources: docs.midjourney.com Creating-on-Web · howtogeek.com midjourney-web ·
  docs.ideogram.ai (Prompt Box, Quick Start) · helpx.adobe.com firefly text-to-image set ·
  dupple.com/learn/how-to-use-leonardo-ai · makeuseof.com leonardo guide ·
  recraft.ai/docs interface-overview · photutorial.com freepik-ai-suite-review.

### 2.10 The convergence — one shape, eleven products

| Layer | Fooocus | SwarmUI | InvokeAI | Krita AI | Comfy App Mode | Draw Things | Midjourney | Ideogram | Firefly | Image Playground | A1111 (anti) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| At rest | prompt + Generate + images + 2 checkboxes | prompt + Generate + image + core params | prompt + Invoke + viewer + gallery | style + prompt + strength + Generate | author-chosen inputs only | canvas + prompt + Generate + Basic sliders | one bar + feed | prompt + control row + feed | prompt bar + gallery | describe field + chips + style | ~20 controls + 8 tabs |
| One tap | Advanced panel | collapsed groups, `?` per param | accordion + Advanced section | Styles dialog | (author-defined) | Basic→Advanced→All switch | one settings drawer | one "More settings" expander | panel appears WITH results | — | (nothing left to disclose) |
| Model mgmt | invisible (auto-download) | separate Utilities tab | separate Models tab | setup-time installer | missing-model dialog on demand | dropdown → Manage popup, sizes stated | version dropdown in drawer | model dropdown in row | version dropdown in panel | none | folder-drop |
| Power exit | debug flag | separate Comfy tab | separate Workflows tab | (none) | the graph, elsewhere | All mode | `--params` text syntax | — | — | — | it IS the power surface |

Eleven products, and the ten that non-technical people praise share every column. Nobody puts
licenses, file paths, verification mechanics, or security rationale on the generate surface.
Nobody shows acquisition as a standing section once models exist. Everybody makes the result area
the biggest thing on screen and gives disclosure exactly one gate. **The shipped /comfy page is
the only surface in this table whose first screenful is model cards — its nearest structural
relative in the table is A1111.**

---

## 3. The house rules the page broke (and must obey in v2)

- **v1.5.34 chip-first grammar** (the binding precedent, from its commit message): "rows carry
  only the verdict chip; the sentence/arithmetic/hedge moved to a styled tooltip (hover + tap +
  keyboard, one verdict object so chip and hover cannot contradict)"; strips use Debi's
  **STATUS+DELTA grammar** ("Free now: ~17.9 GB · +18.5 GB on eject"); verdicts are
  **provenance-worded** (measured-now / measured-here / estimate). The panel already has the
  machinery (`fitpill` + `fitChipClass` + `tipBind` in index.html); comfy.html re-implements none
  of it and writes paragraphs instead.
- **Impeccable** (github.com/pbakaus/impeccable), applied principle by principle to this page:
  - *No card-in-card nesting:* **violated** — the shipped model card is card → warnbox/verdict
    boxes → file-row list, three nested framed layers. v2: one row, chips, hovers (§4.2); the
    only framed layer inside a frame is the tooltip, which is transient.
  - *Deliberate visual hierarchy (no skipped/flattened rank):* **violated** — "licence text ↗"
    shares rank with Download; Graph with Reveal; a security footer with the product. v2: exactly
    one primary per region (Generate; the state chip per model row), power affordances in ⋯
    overflow, legal/mechanics in hovers.
  - *Strip to essence (the `distill` posture):* **violated** — ~60 standing text elements at
    rest, most duplicating USER-EXPLAINERS. v2: the §4.7 rule of thumb — a sentence ships at
    rest only as an action label, a live decision-demanding state, or the first-run invitation.
  - *Line length / reading burden:* **violated in spirit** — 70ch explainer paragraphs on a
    working surface. v2: chips ≤ ~4 words; tooltips carry the sentence; Help carries the essay.
  - *No pure black/gray, tint everything; no gray-on-color; no bounce easing; no overused fonts:*
    **already satisfied** — the token system, the Editorial serif/SF stack and the Studio Avenir
    swap all comply; v2 changes none of it.
  - The v2 builder still owes the deterministic detector pass per Studio spec §3 (fetch the rule
    list, apply every hand-checkable rule, report each) — this section is the IA subset only.
- **Studio design spec**: "clean neutral ground… generous-but-dense content area… restrained
  radii, hairline borders over shadows, one accent" and the Models-page bar: "model rows with
  name/size/pills **aligned in columns**", not essay cards. The Generate page must read as the
  same product as the v1.5.34 Models view in all six looks.
- **Copy provenance** (FABLE-RAM-FIT-ADVISOR-SPEC §3b): Draw Things / LM Studio class references
  are behavioral evidence; every shipped sentence is ours, same grammar *class*, zero verbatim
  lifts, checked against extracted strings where any are used.
- **ALL-DESIGNS**: unchanged — the shipped page already passes; v2 keeps tokens-only color.
- **LIES-TO-USER / advisory-gates**: unchanged and non-negotiable — demotion to a hover must
  never soften a verdict into invisibility at the moment it matters (see §4.4: verdict chips are
  *at rest* when true, detail on hover).

---

## 4. Proposed IA — the wireframe in words

Design language: Editorial (default) with the Studio axis exactly as comfy.html already does it;
all copy ours; chips/tooltips reuse the v1.5.34 grammar (ideally the same CSS classes, extracted
or mirrored — one verdict object per chip, chip and hover can never contradict).

### 4.0 Decision → evidence traceability (doctrine 8b)

Every structural decision below, with what carries it — our principle first, field evidence as
corroboration, never the reverse:

| Decision | Governing principle (ours) | Field corroboration |
|---|---|---|
| Result stage biggest, composer under it, no standing Models section | impeccable hierarchy: the product at top rank | all ten praised products (§2.10); A1111/our-page as the counter-case |
| Chips + one-object tooltips carry all verdicts | v1.5.34 chip-first (binding precedent, same app) | SwarmUI's `?`-per-param (essay one click away) |
| ONE disclosure gate (More ▸), not scattered expanders | impeccable distill; Studio "aligned, quiet" | Fooocus Advanced checkbox · Ideogram "More settings" · Draw Things Basic/Advanced/All |
| Dot on More ▸ when values differ from defaults | LIES-TO-USER (hidden edits must not be silent) | Ideogram's pinned-reference state echo |
| Model management = a sheet behind the model chip, in-flow not a separate tab | our S1 charter (acquisition is part of this page's job — unlike cloud apps) | Draw Things dropdown→Manage popup (the in-flow precedent); Comfy's own missing-model dialog |
| Sheet = rows with aligned columns, not cards | Studio spec Models-page bar, verbatim | InvokeAI/SwarmUI model tabs |
| Licenses/paths/sha as hover detail, not standing copy | copy-provenance + impeccable distill; honesty preserved per LIES-TO-USER | zero of eleven products show these at rest (§2.10) |
| Health defects as amber chips at rest, detail on hover, repeated on the composer chip when selected | advisory-gates ruling: visible at the moment of choice, never blocking | (no field equivalent — ours is *more* honest than the field; kept on principle) |
| Measured-rate-only ETAs | LIES-TO-USER | Draw Things' recalculating ETA (same instinct, observed) |
| Run's actual values written back into caption chips + More ▸ fields | one-source-of-truth (chip/hover cannot contradict) | Pixelmator ML-Enhance-writes-into-sliders; Firefly prompt↔preset sync |
| First-run = invitation in the stage, two Get buttons, sizes on the buttons | disk-first UX (spec) + graceful absence | Draw Things' size-labeled first-open prompt; Firefly's zero-controls-before-first-result |
| Power exits (Graph, Open-template, ComfyUI tab) demoted to overflow/one pill | impeccable hierarchy; the page's charter (shield the non-technical user) | Midjourney's invisible `--syntax`; SwarmUI/InvokeAI's separate tabs |

### 4.1 AT REST (target: 7 visible elements, one screenful, no scroll to reach Generate)

```
┌────────────────────────────────────────────────────────────────┐
│ Generate                                    ● engine · ⛁ disk │  ① title + status chips
│                                                                │
│ ┌────────────────────────────────────────────────────────────┐ │
│ │                                                            │ │
│ │                    [ result stage ]                        │ │  ② the picture — biggest
│ │        latest output large; empty = one quiet line         │ │     thing on the page
│ │                                                            │ │
│ └────────────────────────────────────────────────────────────┘ │
│  ▢ ▢ ▢ ▢ ▢ ▢ ▢                                   12 items · 84 MB │  ③ recent strip + total chip
│                                                                │
│ ┌ prompt ──────────────────────────────────────────────────┐  │
│ │ a fox moving quickly through a snowy forest…             │  │  ④ prompt box
│ └──────────────────────────────────────────────────────────┘  │
│  [Image | Clip]   [Wan 2.1 · ready ▾]   More ▸    [Generate]  │  ⑤⑥⑦ mode · model chip ·
└────────────────────────────────────────────────────────────────┘      More · Generate
```

The seven: **① status chips** (engine dot + disk chip, one cluster), **② result stage**,
**③ recent strip** (with one total-size chip), **④ prompt**, **⑤ Image/Clip toggle**,
**⑥ model chip**, **⑦ Generate** (+ the closed **More ▸** disclosure, which shares rank with ⑥).
No Models section. No footer essay. No file paths. No license links. Zero sentences at rest when
everything is healthy.

- **Status chips** replace the pill row: `● ComfyUI` (green/red dot; hover = version · port ·
  torch; red state's chip reads `engine off` and its hover names Components). The disk chip shows
  STATUS+DELTA only when it earns the space: hidden when free space is comfortable and nothing is
  downloading; visible as `Free ~48 GB` during any download or when free < a threshold. (This
  narrows the S1 spec's "free space in the surface header" — flagged as open question Q2.)
- **Model chip** (`Wan 2.1 · ready`): the *only* standing trace of model management. Hover = the
  card's honest summary in tooltip form (size on disk · license chip · last run measured numbers ·
  any health verdict). Click = the **Models sheet** (§4.2). When the selected model has a
  measured health defect, the chip itself carries the amber mark (§4.4).
- **Result stage**: newest output large (image or playable video), with a one-line caption chip
  row under it (`38.3s · seed 512 · 1024×1024` — chips, not prose). While a job runs, the stage
  is the progress surface (§4.5). Empty state: one line — "What you make lands here and stays." —
  and nothing else.
- **Recent strip**: last N thumbnails + `12 items · 84 MB` total chip (hover: "Everything is
  kept; delete in Finder via Reveal." — the keep-forever policy demoted to its natural home).
  Click a thumb → item detail (§4.3). "All results ▸" expands the full grid in place (or scrolls
  to it — Q1).
- **More ▸** (closed by default, Fooocus's Advanced gate in our idiom): opens the existing grid —
  width · height · steps · seed · (video: frames · fps) · negative prompt. The 4n+1 frames rule
  becomes a hover on the frames field. Defaults come from the template as today; a dot on
  "More" when any value differs from defaults, so hidden edits are never silent.
- **Write-back rule** (the Pixelmator mechanic, §2.8): when a run completes, the values actually
  used — the snapped frame count, the seed that was drawn, the resolved size — land in the result
  caption chips AND write back into the More ▸ fields, so what the user sees is what they can
  edit and re-run. Exception: the seed field stays blank/random after a run (the shipped page's
  deliberate reset, kept) — the drawn seed lives in the caption chip, and the chip is
  click-to-reuse (click it → that seed fills the field). One source of truth: the job record
  feeds chips, fields and hovers alike.

### 4.2 ONE TAP — the Models sheet (acquisition, compacted)

Opened from the model chip (and auto-opened as the first-run body, §4.6). A **sheet/section of
rows, not cards** — the v1.5.34 Models-view grammar:

```
MODELS                                    Free now: ~48.2 GB · −9.8 GB on download
─────────────────────────────────────────────────────────────────
Wan 2.1 T2V 1.3B   video   9.8 GB   [Apache-2.0]  [colour shift here]   [On disk ✓]  ⋯
SDXL base 1.0      image   6.9 GB   [RAIL++-M]                          [Get 6.9 GB] ⋯
─────────────────────────────────────────────────────────────────
Both starters: 16.8 GB · 2.8 GB over the 14 GB budget
```

- **One row per model**: name · role · size · **license chip** · health chip (only if a measured
  defect exists) · **state chip** (the action). Aligned columns per the Studio spec.
- **State chip carries `cardAction()`'s exact states** as chip labels: `Get 9.8 GB` /
  `Downloading 42%` (with a thin progress underline on the row) / `Verifying…` /
  `Resume · 2.4 of 9.8 GB` / `Re-download` (corrupt) / `On disk ✓`. Hover on `On disk ✓`:
  "sha256-verified against the pinned hash on download; size re-checked now." Hover on `Get`:
  the disk arithmetic in STATUS+DELTA ("needs 9.8 GB · 47.8 free · leaves ~38"). The corrupt
  chip's hover carries the truncated/stale-file sentence. **No mechanics prose on the sheet.**
- **License chip** hover = the license note sentence + the "read the licence text ↗" link.
  The link exists exactly there, nowhere else. Green/amber/red classes as today.
- **File manifest** (directory/filename/size/state per file, shared-file notes) moves into the
  row's expando or the state chip's hover detail — visible on intent, never at rest. Registry
  drift likewise: an amber chip on the affected row, sentence on hover.
- **Row overflow ⋯**: "Open template in ComfyUI" (the power affordance, demoted to a menu item —
  Q4 offers moving it to Help instead) · "Reveal files" · "Licence text".
- **Sheet footer**: the cap-overshoot honesty as ONE line (kept — it is a Debi ruling), and
  nothing else. The sha/HEAD-verification narration is gone from standing copy (it lives in the
  state-chip hovers and in Help).

### 4.3 ONE TAP — item detail

Click a gallery thumb → overlay/detail: the output full-size; a chip row (`size · model · shape ·
seed · wall time · peak mem` — provenance-worded on hover); **Reveal** as the one button;
**Graph** demoted into the detail's overflow ⋯ ("The exact graph that produced this") — or to
Help entirely (Q3). Missing/size-changed/orphan states stay as amber/red chips on the thumb with
the sentence on hover — the honesty survives, the paragraph does not.

### 4.4 The Wan colour-defect (pattern for all measured health verdicts)

- The model row wears one amber chip: **`colour shift here`** (wording final at spec time).
- Hover: the full measured sentence — what was observed, the date, SDXL-was-fine-same-engine,
  the bf16 A/B queue note.
- When that model is *selected* in the composer, the **model chip itself** goes amber and carries
  the same mark (`Wan 2.1 · colour shift`), same hover — the moment-of-choice visibility the
  advisory doctrine requires, at chip rank instead of a repeated verdict box. One verdict object
  feeds row chip, model chip and both hovers.

### 4.5 States (the moments that used to be paragraphs)

- **Engine down:** status chip `engine off` (red dot); Generate disabled; in its place one short
  line with an action: "Engine is off — **Start it** ▸" (deep-link to Components or a direct
  start if the components lane allows). No warnbox essay; the old sentence lives in the hover.
- **Generating:** Generate becomes **Stop**; the result stage shows the in-progress surface —
  progress bar + `step 14 of 30` + elapsed; ETA **only** when a measured rate for this
  model+mode exists (LIES-TO-USER); ws-drop → "(polling)" as a faint chip suffix. The "one job
  at a time / you can leave this tab" sentence → hover on the progress area, and Help.
- **Never measured yet:** a small provenance chip near Generate — `first run = measurement` —
  hover carries the old sentence. After a run: `last: 38s · peak 13.3 GB` chip, hover states
  provenance ("measured on this Mac, phys_footprint").
- **Missing model at submit** (the 409 refusal): a compact refusal directly under the composer:
  one line naming the file + its size + a **`Get 6.9 GB`** chip-button that starts the download.
  Named, actionable, three elements — not a warnbox with a `<ul>`.
- **Download running while composing:** the model chip of the affected model shows live percent;
  the disk chip appears in the header for the duration.
- **Fence violation** (custom nodes found): an amber chip appears in the header only when true
  (`3 node packs — not ours`, hover = the supply-chain sentence). When false — the normal case —
  the page says nothing about it at all. The standing footer essay is deleted; its text already
  exists in USER-EXPLAINERS.
- **Section render failure:** keep the per-section try/catch (a walked defect), but the in-section
  message shrinks to one line + retry note.

### 4.6 First run (nothing downloaded)

The composer renders but Generate is disabled with the reason chip (`no model yet`). The result
stage hosts the invitation — Fooocus-grade brevity:

> **Turn a sentence into a picture or a clip — on this Mac, offline.**
> [ Get the image model · 6.9 GB ]  [ Get the video model · 9.8 GB ]
> one line: "Downloads are sha-verified; sizes are exact; nothing downloads until you press."

Two buttons, a heading, one sentence. License chips ride ON the buttons' hover, not beside them.
The current three-paragraph empty state (engine explanation, weights explanation, sharing note)
moves to Help verbatim — it is good copy in the wrong place. "Models are shared with the ComfyUI
tab" = hover on the Get buttons.

### 4.7 BURIED (Help / hover-only / overflow — never at rest)

| Content | New home |
|---|---|
| Stock-nodes / supply-chain essay | Help (already in USER-EXPLAINERS §Generate); header chip **only when violated** |
| Storage paths (models dir, output dir) | Help + the Reveal buttons (which *show* the place instead of printing it) |
| Keep-everything gallery policy | hover on the gallery total chip + Help |
| sha256 / HEAD-verification mechanics | hover on state chips + Help |
| License full-text links | inside the license chip's hover |
| Measurement provenance parentheticals | provenance-worded tooltips (v1.5.34 audio-tab pattern) |
| "Open template in ComfyUI" | model-row ⋯ overflow (or Help — Q4) |
| Graph (exact API JSON) | item-detail ⋯ overflow (or Help — Q3) |
| 4n+1 frames rule, "one job at a time", "leave the tab" | field/area hovers + Help |
| Build stamp | keep, one faint line at the very bottom (it has debugging value) |

Rule of thumb for the spec: **a sentence may ship at rest only if it is (a) an action's label,
(b) a state that is true right now and demands a decision, or (c) the first-run invitation.**
Everything else is a chip whose hover carries the sentence, or Help.

---

## 5. What must SURVIVE, mapped (the honesty ledger)

Every mechanic below exists in the shipped page and is non-negotiable; the redesign relocates,
never removes:

| Honest mechanic (shipped) | Where it lives in v2 |
|---|---|
| sha-verified, resumable downloads; `.part` never reported as downloaded | state chips on model rows (`Get / Downloading / Verifying / Resume · 2.4 of 9.8 / Re-download / On disk ✓`), verification sentence on hover |
| Disk verdicts, advisory never blocking | STATUS+DELTA line in the Models sheet header + `Get` chip hover arithmetic; header disk chip when downloading/tight |
| Measured last-run (wall s + peak bytes), never estimated ETAs | `last: 38s · peak 13.3 GB` chip near Generate + on model-row hover; ETA only from measured rate |
| "First run is the measurement" honesty | `first run = measurement` provenance chip, sentence on hover |
| Wan colour-defect verdict at the moment of choice | amber health chip on row AND on the composer's model chip when selected; one verdict object (§4.4) |
| Missing-model refusal that names the file and offers the download | compact under-composer refusal: one line + `Get` chip-button (§4.5) |
| Keep-everything gallery with per-item + total sizes | recent strip + total chip at rest; sizes in item detail; policy on hover |
| Missing / size-changed / orphan gallery item states | amber/red chips on thumbs, sentence on hover |
| Cap-overshoot statement (16.8 vs 14 GB, Debi's ruling) | one line in the Models sheet footer |
| Stock-nodes fence + violation surfacing | header chip only-when-true; gate test unchanged |
| Engine-down graceful absence (never a dead panel) | `engine off` chip + Start action line (§4.5) |
| Registry drift / corrupt-file detection | amber chips on the affected row, detail on hover |
| Shared-file dedup awareness (umt5/t5 encoders) | row expando / hover manifest; download math unchanged underneath |
| Per-section render isolation (walked defect) | kept; failure message shrunk to one line |
| SSE + adaptive 1s/15s cadence; ws-drop → polling | unchanged; "(polling)" as a faint chip suffix |
| Open-in-ComfyUI deep link (power exit) | row/item ⋯ overflow (Q3/Q4); the header "ComfyUI tab ↗" link may remain as the one power-exit pill |
| ALL-DESIGNS token discipline, skin sync, no external `<head>` resources | unchanged, verbatim |

Nothing in this table gets a standing paragraph. That is the entire redesign.

---

## 6. Open questions for Debi (the real forks)

1. **Gallery placement.** (a) Recent strip under the result stage + "All results ▸" expanding in
   place (proposed — keeps one screenful), or (b) the full grid as a standing section below the
   fold as today, or (c) a separate sheet like Models. The strip is the Draw Things/Fooocus
   answer; the standing grid is the InvokeAI answer.
2. **Disk chip visibility.** The S1 spec says "free space in the surface header" always; the
   proposal shows it only while downloading or when space is tight (plus always in the Models
   sheet). Keeping it always-on costs one chip and stays within the ≤7 budget — Debi's call, since
   it amends a spec line.
3. **Graph button.** Demote to item-detail ⋯ overflow (proposed) or remove from the UI entirely
   and mention only in Help? It is provenance gold for power users but was named in the verdict.
4. **"Open template in ComfyUI".** Model-row ⋯ overflow (proposed) or Help-only? Same tension.
5. **Model picker at rest with one model.** When only one model covers the selected mode, does
   the model chip still show (proposed — it is also the health-verdict carrier) or collapse into
   the mode toggle?
6. **First-run auto-open.** Should first run land directly in the Models sheet (acquisition-first)
   or on the composer with the two Get buttons in the stage (proposed — the product's face stays
   the product)?

## 7. Honest limits

- Draw Things was documented from its official wiki + two dated hands-on reviews, not from
  driving the app; license display in its model catalog and its error-dialog behavior are
  unverified.
- SwarmUI default group-collapse states and InvokeAI section-collapse defaults are partially
  verified (docs coverage gaps; their support site was unreachable) — the *mechanism* (collapsed
  groups / accordion + Advanced gate) is verified, the exact default list is not.
- Impeccable was read via its README/detector summaries; the deterministic rules cited (card
  nesting, gray-on-color, pure-black, easing, hierarchy) are its stated set, but the full 61-rule
  detector list was not enumerated rule-by-rule against comfy.html — the v2 builder should run
  the detector pass per the Studio spec §3, which already binds this.
- No mockups were produced — this is IA, not pixels; the "≤7 elements" claim is an inventory
  argument, not a rendered measurement. The v2 builder verifies the one-screenful claim at the
  panel's real default size, in all looks.
- Element counts for the shipped page (~60 at rest) were derived by reading comfy.html's render
  functions with two models on disk, not by DOM-counting a live render.
- The commercial UIs (§2.9) are login-gated: docs.midjourney.com and leonardo.ai's own guide
  403'd fetches and one Adobe helpx fetch timed out, so those inventories rest on official-doc
  search snippets and third-party walkthroughs. Fast-moving details (Firefly panel side, current
  default models, exact slider ranges, Ideogram's default output count) were not pinned and are
  not load-bearing for any §4 decision.
- A1111's inventory is from its official wiki + a dated walkthrough, not a live install; the
  "300+ settings" figure is a reviewer's count, not ours.
- Pixelmator/Photomator progress-UI chrome is undocumented in reviews (they describe outcomes as
  immediate — which is itself the datapoint); the "writes into ordinary sliders" mechanic is
  DPReview's firsthand observation.
