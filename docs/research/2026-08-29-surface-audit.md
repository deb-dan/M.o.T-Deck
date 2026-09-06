# Surface audit — every first-party surface against the Generate-page lens

**Date:** 2026-08-29 · **Author:** audit agent (Fable brief) · **Status:** findings only, no code changed
**Lens:** `docs/research/2026-08-29-generate-page-redesign.md` — §1's five named failures
(paragraph verdicts at rest · plumbing at the user's face · file-path tables · measurement
prose everywhere · power affordances at full rank), §3's house rules (v1.5.34 chip-first
grammar, impeccable, the §4.7 buried-layer rule: *a sentence ships at rest only as an action
label, a live decision-demanding state, or the first-run invitation*), and the
at-rest / one-tap / buried hierarchy. Doctrine 8b governs the Music field survey.
**Method:** code read (`bridge/panel/*.html`) **and** every surface loaded live on the
running bridge at :8700 (element counts are from real renders, this Mac, 16 chat models +
4 audio models + 2 music engines + 6 tracks + 3 comfy outputs on disk).
**Out of scope per the brief:** third-party embedded UIs (stock ComfyUI, Unsloth, Hermes
tab, OpenCode, Odysseus tabs). comfy.html is included only as the calibration reference.

---

## 0. TL;DR

The A1111 disease is **not** app-wide. The app's daily surfaces — Chat, MOT Deck home,
the Models list — already live in the v1.5.34 chip grammar and pass with polish-level
findings only. The disease concentrates in four places that were written as *explainer
cards* rather than *chips*: **Music** (the whole create flow is helper-sentence-per-field,
plumbing-first — structurally the same page as comfy.html at lower volume),
**Capabilities → Tools** (a three-paragraph support article at rest that duplicates two
existing Help sections verbatim-in-substance), the **Audio tab's curated "Get voice
models" section** (seven essay cards with dependency plumbing as standing copy), and the
**office AI panel's empty state** (a six-paragraph Help article as the invitation).
Everything else is copy-demotion: single paragraphs on goose/aider, policy sentences
repeated on every changeset card, absolute paths printed at rest in three detail panes.

One structural note the lens makes visible: **every surface that renders through
`.cap-row` inherits the disease**, because `.cap-row`'s grammar is *name + standing
`.cap-desc` sentence per row*. Capabilities gets away with it (settings pages are the one
category where a one-line description per control is the field convention — macOS System
Settings does the same); Music does not, because Music is a *creation* surface wearing a
*settings* page's grammar.

---

## 1. Ranked table (non-clean surfaces, by user exposure)

| # | Surface | Exposure | At-rest count¹ | Verdict | Fix class |
|---|---|---|---|---|---|
| 1 | Chat (composer + lanes) | daily | ~18 chrome elements (+3/msg) | **MINOR** | copy-demotion (cheap) |
| 2 | MOT Deck home | daily | ~64, near-zero sentences | **MINOR** | copy-demotion (cheap) |
| 3 | Models — chat tab (list + detail) | daily-ish | list ~40 (chips) · detail ~14 | **MINOR** | copy-demotion (cheap) |
| 4 | Music | weekly | ~55, **~14 standing sentences** | **TEXTY → structural** | its own slice (already ruled: the alternative surface) |
| 5 | office.html chrome — AI panel + changeset card | when editing | empty state = 6 paragraphs | **TEXTY** (panel) / MINOR (card) | copy-demotion, contained |
| 6 | Capabilities — Tools tab | occasional | 3 standing paragraphs + toggle list | **TEXTY** | copy-demotion (the paragraphs already exist in Help) |
| 7 | Models — Audio tab (curated section) | occasional | 7 cards, ~18 standing sentences | **TEXTY** | structural-lite: cards → v1.5.34 rows |
| 8 | goose.html chrome | occasional | ~10 (1 paragraph + 1 footer essay) | **MINOR** | copy-demotion (cheap) |
| 9 | aider.html chrome | occasional | ~9 (1 paragraph + 1 footer) | **MINOR** | copy-demotion (cheap) |
| 10 | Capabilities — General/Models tabs | occasional | ~30 rows, 1-line descs | **MINOR** | copy-demotion (a few jargon lines) |
| 11 | Customize navigation dialog | rare | 1 intro paragraph + rows | **MINOR** | copy-demotion (cheap) |
| 12 | Load-consent panel (fit advisor) | rare, decision moment | 5–7 elements | **MINOR** | one line |
| — | comfy.html (calibration) | — | ~60, ~25 standing sentences | **DISASTER-CLASS** (already condemned) | redesign in flight (spec v2) |

¹ "standing text elements a fresh user reads before acting", counted on the live render;
approximate by nature.

**CLEAN:** Models HF browser (search row only) · Memory ledger/strip (chip at rest,
detail one tap down — the v1.5.34 poster child) · Help (prose is its charter) · Logs
dialog (raw log lines are the product; 22 source chips is heavy but it is a power
surface) · Capabilities — Skills tab (one collapsed disclosure: `▸ 60 built-in · 11
learned`).

---

## 2. Per-surface findings

### 2.1 Chat — MINOR (daily; copy-demotion)

**At rest** (fresh session): title/stamp header, 5 mode chips, model chip, vision pill,
audio chip, the mode-note, the caps-strip, input + attach + talk + Send + the 3-position
audio switch ≈ **18 chrome elements**. Message rows add a *hover-revealed* action row
(index.html:551 — "Per-message actions (LM-Studio parity): hover-revealed chip row") and
one faint stats stamp.

**Violations (worst 3):**
1. **Two overlapping status readouts at rest.** `#chat-note` ("web search on · shell
   off", index.html:2234) *and* the caps-strip ("web ✓ · research ✗ · memory ✓ · 77/77
   tools", index.html:2236) sit side by side saying overlapping things in two different
   grammars. One chip cluster should carry it; "77/77 tools" is a number only a builder
   loves.
2. **The raw model filename at full rank.**
   `Qwen3.6-27B-Fable-Fus-711-UnHeretic-NM-DAU-NEO-MAX-NEO-Q4_K_S ⌄` is the composer's
   model chip. It is honest data, not prose — but it is an installer's filename worn as
   a title, repeated again as the sender name on **every assistant message**. A display
   name (short) with the full id on hover is the chip-grammar answer.
3. (Borderline, recorded not charged) the per-reply `60.0 tok/s · 317 tok · 15.4s`
   stamp is standing on every reply (stampMsg, index.html:11702; formatter :11689). It
   is faint, small, and LM-Studio-parity — category convention covers it.

**What it does right:** the composer is the app's best chip discipline — mode chips,
closed model/voice pickers as chips with popovers, Send as the one filled accent,
actions hover-only, the audio switch as one surface. Nothing here is a paragraph.

### 2.2 MOT Deck home — MINOR (daily; copy-demotion)

**At rest:** ~64 elements — 10 component cards × (name · status · `pin … · port …` ·
Stop), 8 metric tiles, the activity feed (≤8 rows), header + stamp. **Almost zero
sentences** — this page's charter *is* "Status of every component, every port, every
pin" (index.html:2158), and it keeps to data.

**Violations:**
1. **A raw commit sha at rest:** the Odysseus card reads `pin c9dd68d890a7… · port
   7860`. The pin *concept* belongs here; the hex string belongs on hover. Same for
   `· llama.cpp` riding the RUNNER card's pin line.
2. The feed's technical register ("live updates on — status polling relaxed to 30s") is
   a builder's sentence in the user's activity feed — true, harmless, hover-class.

**Right:** verdict-per-card with debounced health (the ok|transient|lost work), metric
tiles as pure STATUS numbers, `MEMORY FOR A MODEL — 13.0 GB usable · pressure normal`
already in the STATUS+DELTA family.

### 2.3 Models — chat tab — MINOR (the positive calibration, as briefed)

**At rest:** header + RESCAN/SEARCH chips + 2 sub-tabs + the memory strip (chip + one
STATUS+DELTA line + DETAILS) + 16 rows × ~6 chips each + detail pane. The list is
**exactly the v1.5.34 grammar**: every row is name + chips (`TOOLS · Q4_K_S · GGUF ·
LM STUDIO · 15.9 GB · FITS ~7.7 GB`), verdicts provenance-worded, arithmetic behind
"SHOW THE ARITHMETIC" (fitDetailHtml, index.html:9334 — the comment above it names the
cure: "chip + ONE line, with the arithmetic and the hedge behind a disclosure").

**Residual violations, all in the detail pane:**
1. **Absolute file path printed at rest** (`.md-path`, index.html:11095):
   `/Users/debik/.lmstudio/models/DavidAU/…/…Q4_K_S.gguf` in mono under the Load group —
   the §1-failure-3 pattern surviving in the cured view. Reveal-style affordance or
   hover is the fix. (Same class at :9830 for audio model paths.)
2. **A mechanics paragraph at rest** under Apply & reload: "Sampling applies to CHAT on
   your next message. Apply & reload restarts the runner (60–90s) so these also become
   the launch defaults the Agent and Hermes lanes inherit." (bridge-supplied `av.note`,
   rendered at index.html:10962). Sentence-on-hover; chip says `applies on reload`.
3. **The AUX RUNNER footer speaks internal names:** "no model set — use "Set aux" on a
   small installed model · serves Odysseus background tasks (titles, search queries,
   memory)" (index.html:9477). "Odysseus" is a component name, not a user concept, at
   rest on the daily models page.

**Right:** everything the redesign doc holds up — one verdict object, chips that cannot
contradict their hovers, `Get` never blocked, the memory strip.

### 2.4 Models — Audio tab — TEXTY in its lower half (structural-lite)

**At rest:** the installed rows are chip-perfect (`STT · DEFAULT · MLX · DOWNLOADED ·
2.3 GB · FITS ~5.6 GB`) — v1.5.34 applied, including the provenance-worded audio
verdicts that slice added. Then the **"Get voice models" curated section** (VOICE_STARTERS,
index.html:10464–10520; rendered at :10521) is seven pre-v1.5.34 essay cards, ~18
standing sentences.

**Violations:**
1. **Dependency plumbing as standing copy** (§1 failure 4, verbatim class):
   "⚠ Needs the misaki package; its 'en' extra pulls PyTorch, so it is installed WITHOUT
   extras to keep the MLX venv torch-free — Kokoro support is best-effort."
   (index.html:10494). misaki/PyTorch/venv on a Get button's card is the sha-mechanics
   cap-line of comfy.html.
2. **Four-sentence verdict essays per card:** the Parakeet card carries model-selection
   reasoning ("Unlike Whisper it emits NOTHING on silence instead of hallucinating a
   phrase, which is what stops conversation mode sending phantom messages…",
   index.html:10500-ish) — true, valuable, hover/Help material.
3. **Repo ids + license lines in mono at rest** on every card
   (`mlx-community/OmniVoice-bfloat16 · code Apache-2.0 · weights CC-BY-NC (upstream
   README)`) — the license-chip-with-hover pattern exists forty lines up the same page
   and is not used here. Also the section intro narrates plumbing ("Downloads land in
   MOT Deck's own models folder and appear above when they finish. Progress is in
   Downloads below.", :10522) and the SEARCH HF expander carries a standing caveat
   paragraph ("Tags lie about frameworks — click a result and MOT Deck reads its
   config.json before offering a Get.", index.html:2432) — one-tap layer, so charged at
   half price, but it is still a paragraph where a chip + hover would do.

**Right:** the installed list, the shared download manager, honest recommendation
ordering (recommendation stated as a chip-able word, not a ranking essay).

**Fix:** the redesign doc's §4.2 Models-sheet grammar, applied to these seven rows: name
· role · size · license chip · state chip; the essay to the row's hover/expando. This is
the one non-Music surface where the fix is rows-not-cards structural, not just wording.

### 2.5 Music — see §3 (the deep-dive). Verdict: **TEXTY, structural** — comfy.html's
sibling at ~60% volume, and the create-flow's product (Generate) sits below Engines and
Templates exactly as comfy's composer sat below the model cards.

### 2.6 Capabilities — General/Models MINOR · Tools TEXTY · Skills CLEAN

Settings-page convention (one short desc per control) covers most of the General tab.
Charged anyway:
1. **TEXTY, the worst prose-at-rest in index.html** — the Hermes toolsets intro
   (index.html:5582): two full paragraphs at rest, including "Fewer toolsets = a smaller
   system prompt = faster turns on a local model" and the entire cross-check essay
   ("Cross-checking Hermes's own *Skills → TOOLSETS* page? It loads its list once when
   it opens and never refreshes itself — so **MOT Deck reloads that tab for you** …
   press ⌘R there. The **Check** button below is the live answer either way."), plus a
   third paragraph explaining "Minimal" vs "Hermes's defaults". **This is duplicated
   Help on the canvas, literally:** Help's TOC already carries "Hermes tools — what
   those switches actually control" and "Why Hermes's own page used to disagree" —
   the same content, in its right home. §1 failure 4, exactly.
2. "Extraction cadence isn't configurable — Odysseus decides when to extract."
   (index.html:4816) — internal component name + an apology for a missing control,
   standing.
3. The Design/Theme descriptions (index.html:5056 area) each run 3 sentences and
   include implementation detail ("Studio's stylesheet is fetched the first time you
   turn it on") — trim to one sentence, rest on hover.

**Right:** the tab split (no endless scroll), Skills as one collapsed count, greyed
not-configured options named honestly, Appearance reachable in place.

### 2.7 Help — CLEAN

Prose at full rank is this view's charter; every word comes from USER-EXPLAINERS.md via
the API (view markup is empty, index.html:2520 comment). Filter + TOC + doc. The one
soft note: the intro paragraph explains the *file's editing model* ("editing this file is
the only step needed to change what the app shows") — maintainer-facing, could stay in
the .md as a comment rather than render. Not charged.

### 2.8 Logs dialog — CLEAN

Raw log lines are the product of this surface; the audience is exactly the person raw
text serves. 22 source chips at rest is dense but they are the navigation. `bridge ·
last 40 lines` is a correct STATUS line. No action needed; excluded from slices.

### 2.9 Customize navigation dialog — MINOR

One standing 5-sentence intro paragraph ("Drag ⠿ to reorder… A hidden tab is not gone —
it collects in the ⋯ menu… Nothing can be hidden on both bars at once — except Logs and
Help… The tab strip only exists in the app window, and it follows within a few
seconds."). A direct-manipulation surface should teach by shape: first sentence stays
(action label class), the three edge-case sentences go to hovers on the rows they
describe. Otherwise exemplary: rows, drag handles, live apply.

### 2.10 Memory ledger (strip + Details) — CLEAN

At rest: `MEMORY` chip + one STATUS+DELTA line + DETAILS. One tap: the Activity-Monitor
rows + one provenance paragraph at the bottom ("Memory footprint — what Activity
Monitor's Memory column shows… We name what other apps hold; we never touch them."). The
paragraph is on the one-tap layer, where the §4.7 rule permits sentences; hover would be
even tighter but this is the pattern the whole app should copy. The positive calibration
alongside the Models list.

### 2.11 goose.html — MINOR (copy-demotion, cheap)

**At rest:** ~10 elements — title, INSTALLED/MODEL/SESSION chips (good), Start/End,
**one standing paragraph** (goose.html:214): workspace absolute path in bold, a raw
endpoint URL (`http://127.0.0.1:6767/v1/chat/completions` interpolated into `#ep`),
"Enter is the answer", "/exit then Start resumes a fresh one" — path + URL + slash-command
jargon at rest, three §1 failures in one paragraph. Plus a **footer architecture essay**
(goose.html:223): "goose is a lane, not a component — it has no MOT Deck card to start
or stop… Its home and its history stay under `data/goose/`. The terminal keeps a dark
ground in every theme: the colours in it are goose's own." — inside-baseball reasoning
(our component taxonomy) as standing user copy.

**Right:** header chips carry state (INSTALLED · V1.48.0 · MODEL · SESSION LIVE); the
terminal is the product and dominates.

**Fix:** paragraph → chips (`workspace ▸ reveal` · `local runner` · `asks before writing`)
with sentences on hover; footer → Help (a "Goose" Help section already exists).

### 2.12 aider.html — MINOR (same disease, same cure)

One standing paragraph (aider.html:100): workspace path + `/undo`, `/diff` jargon +
"there is no replay"; footer taxonomy essay (aider.html:107). Additionally observed
live: "aider is already running in another window." rendered *while the header said NOT
CONNECTED* — flagging as a possible stale-state contradiction to eyeball (not audited
further; may be an honest cross-window lock message that outlived its trigger).

### 2.13 office.html chrome — AI panel TEXTY · changeset card MINOR · rail/strip largely clean

1. **The AI panel's empty state is a six-paragraph Help article at rest**
   (`#ai-empty`, office.html:1501–1527; `#ai-empty-blob` sibling at :1494): example
   prompts (fine — that part *is* the first-run invitation), then the CLEAN-function
   disambiguation paragraph, then the full apply/undo/save mechanics ("Apply puts the
   change in the editor: ⌘Z inside the sheet takes it back, and ⌘S writes it to the
   file. The one exception is a **sort**, which has to go through the file and is saved
   straight away…"), then the context-policy sentence ("the sheet travels with it, the
   earlier answers do not"). Every sentence is honest and hard-won (the L5 comment
   documents why) — and §4.7 gives the invitation one heading + a couple of example
   chips, not the mechanics. The sort-exception sentence explicitly belongs on the
   changeset card at the moment it is true ("the card says so before you press it" —
   so the card already carries it; the empty state repeats it).
2. **The changeset card repeats policy prose on every card** (csCardText,
   office.html:8615): "Nothing has been written: this is a proposal, and Apply is the
   only thing that touches the file. Apply keeps a checkpoint first, so this exact
   change can be undone." — two standing sentences per card, every time, forever. The
   card *is* a decision-demanding state (allowed layer), and the `proposed change · not
   applied` lang-chip (:8650) already carries the first sentence's fact; the checkpoint
   sentence is chip + hover material (`undoable ✓`). The op list, warning lines
   above-the-fold (Debi's amendment 2), and the three collapsed disclosures are
   exactly right and should not move.
3. The Quick/Agent lane chips, model name in the panel head (same raw-filename note as
   Chat), rail as a collapsed FILES tab — clean grammar. (Honest limit: the files rail's
   expanded state and the strip were read in code but not walked deeply live.)

### 2.14 Consent surfaces — load-consent MINOR

fitConsentHtml (index.html:9358): verdict head → reason → remedy buttons → Not now /
Load anyway, inline, never a modal — this is the §4.7 "decision-demanding state" done
properly, hedge demoted to the panel's last line. One charge: the hard-refusal path
prints "Set `<OVERRIDE_ENV>`=1 in the environment if you have a reason to try it
anyway" (index.html:9378) — an env-var instruction as body copy on a consumer surface;
Help material. The office changeset card is covered in 2.13.

### 2.15 comfy.html — DISASTER-CLASS (calibration reference only)

Re-confirmed live: the at-rest render with two models on disk matches the redesign doc's
§1 inventory (~60 standing elements; live text shows the budget-overshoot two-sentence
cap-line, sha/HEAD narration, per-file manifest rows, the Wan verdict paragraph twice,
`(measured phys_footprint of the ComfyUI process, not an estimate)` on four lines,
`licence text ↗` at button rank, Graph on every gallery item, the absolute output dir in
the gallery caption). Nothing new to add — the redesign doc owns it. Every other verdict
in this audit is calibrated against this page as the floor.

---

## 3. MUSIC — the deep-dive (for the redesigned-alternative surface)

Debi's ruling: a **new alternative Music surface behind its own new button**; the current
page stays; they choose later. This section is the input to that alternative's spec.

### 3.1 Full at-rest inventory (live render, classic view, 2 engines + 6 tracks)

Top to bottom, what a user reads before acting:

1. Kicker + **Music** + a two-sentence sub that is architecture prose:
   "…A render is a **one-shot subprocess: no server, no port, no model held in memory
   afterwards**." (index.html:2455) — subprocess/server/port jargon in the page's
   *subtitle*. (§1 failure: raw internals as standing UI.)
2. Stamp: `2 OF 2 ENGINES INSTALLED · 0 TRACK(S)` — chip-grammar, fine.
3. **ENGINES section, first** — two cards, each: name + INSTALLED + license chip + a
   standing spec line "~2 min per minute of song · highest quality · **needs about 14 GB
   of the model-RAM budget while it renders** · 11.1 GB" (renderer index.html:13989) —
   acquisition/plumbing above the product, the checkpoint-dropdown-first mistake in card
   form. Same structural sin that put comfy's Models section above "Make something".
4. `▸ TEMPLATES 6` — a disclosure, collapsed once tracks exist (v1.2 C2). Right.
5. **CREATE** — the product, third on the page. `.cap-row` grammar: every field carries
   a standing helper sentence (index.html:14314–14380):
   - Engine · "Both are installed — pick the trade-off you want." (:14314)
   - Prompt · "Describe the music — genre, instruments, mood, tempo." (:14332)
   - Lyrics · "Optional — leave empty for an instrumental. Section tags like [Verse] /
     [Chorus] shape the arrangement."
   - Length · "10–300 seconds."
   - Steps · "More steps = more compute. This engine's default is 30 (max 30) — leave
     empty to use it." (:14360)
   - Seed · "Any whole number from 0 to 2147483647. The same seed + the same settings +
     the same engine = the same song again. Leave it empty to roll a new one (it is
     recorded with the track)." (seed_help via :14324) — a per-field essay, §1 failure 4
     exactly; SwarmUI's `?`, our tooltip, or More▸ is its home.
   - (Format row when >1: "What the engine itself writes. Any track can also be
     converted afterwards from the library.")
   - Generate + SAVE AS TEMPLATE.
6. **LIBRARY** — header + count + "saving to:
   `/Users/debik/Library/Application Support/MOT Deck/data/music` CHANGE"
   (index.html:14218) — the absolute output path in mono at rest, §1 failure 3
   verbatim (comfy printed its output dir the same way). Then per track: raw filename
   as title (`minimax-20260820-235921.wav`), engine + format chips, a metadata line
   (`8 days ago · 245s · rendered in 1591.7s · seed 1728872057 · 30 steps · 41.2 MB
   ▸ PROMPT`), and 4–5 action chips (PLAY · MP3 · M4A · REVEAL · ✕) at equal rank.
   The metadata line is chips-adjacent (dot-separated data, not prose) — the two real
   charges are the **filename as the row's identity** (the prompt, one disclosure down,
   is the human identity of a track) and **five co-equal actions per row** (Play is the
   product; MP3/M4A/Reveal are overflow).

Rough count: **~55 standing elements, ~14 standing sentences** — comfy.html at ~60%
volume, same shape: plumbing first, essay-per-control, path at rest, product below the
fold. The **Studio view** (♫ hero, "Make music that **moves you**." index.html:13953)
adds a marketing-voice hero *on top of* everything above and repeats the engine RAM
lines a second time inside its engine mini-cards (:14304) — additive, not demoting;
the deck view answers "prettier", not "quieter".

**What Music does right (must survive into the alternative):** the templates disclosure
(collapsed once you have tracks; open on a fresh install where it *is* the teaching
material — Firefly's temporal-staging instinct, already ours); seed recorded with the
track and re-rollable; render progress reusing the download bar's language; engine choice
as a real named trade-off; per-track PROMPT disclosure; conversion offered from the
library instead of a format decision up front; nothing auto-deleted; the honest
`rendered in …s` measured numbers (provenance class, belongs on hover).

### 3.2 The essential verbs of the create flow

Ordered by what the field's praised products put at rest, argued from our principles:

- **Prompt** — the one true essential (every surveyed product).
- **Lyrics** — music's *second* essential, unlike image generation: Suno's Custom mode
  promotes Lyrics to a co-equal field with Style, and its empty state carries the
  instrumental default. Our current "[Verse]/[Chorus]" hint is real teaching — one-tap
  material (a `tags ▸` hint chip on the field), not standing copy.
- **Length** — the one number a non-technical user actually decides. A chip/slider at
  rest (`45s ▾`).
- **Engine** — only because two engines with a real quality-vs-minutes trade-off are
  installed; the model-chip pattern from the Generate redesign §4.1 maps 1:1 (chip at
  rest carrying `MiniMax · ~2 min/min`, sheet behind it with size/license/RAM chips +
  hovers).
- **Generate** — the one filled accent.

**Not essential (More ▸ / buried):** Steps (engine default exists; the "more steps =
more compute" sentence is its hover), Seed (caption-chip write-back + click-to-reuse,
exactly the Generate §4.1 rule — the drawn seed lives on the finished track, not as a
blank field asking a question up front), Format (default per engine; convert-later
already exists), output path (Reveal shows the place instead of printing it),
render-time/RAM telemetry (hover, provenance-worded), the subprocess architecture
sentence (Help).

### 3.3 Mapping the Generate-page IA onto music

| Generate §4 pattern | Music translation |
|---|---|
| **7-at-rest** | ① status chip cluster (engines dot; disk only while downloading) · ② **the player stage** — newest track as a real playable hero with caption chips (`45s · MiniMax · seed 172…` click-to-reuse) · ③ recent strip (tracks as titled-by-prompt rows/cards + `6 tracks · 154 MB` total chip) · ④ prompt box · ⑤ **Lyrics** (the music-specific 5th element — collapsed to a `+ lyrics` affordance when empty, a field when engaged) · ⑥ engine chip + length chip · ⑦ Generate, with More ▸ closed alongside. The page currently has **no result stage at all** — the library is a file list; the alternative's biggest single structural change is that the latest song becomes the biggest thing on the page, playable in place. |
| **One-tap sheet** | the Engines sheet behind the engine chip: one row per engine — name · `~25s/song` · RAM chip · size · license chip · state chip; the "needs about N GB of the model-RAM budget while it renders" sentence becomes the RAM chip's hover. Templates become the **style-preset layer** (Krita's Styles / Ideogram's style refs): named chips near the prompt, not a gallery section — with SAVE AS TEMPLATE writing into the same chips (state echo). |
| **Buried** | Steps/Seed/Format in More ▸ (dot when non-default); output path behind Reveal + Help; render telemetry on caption-chip hover; the subprocess sentence, the [Verse]/[Chorus] tag grammar essay, and the seed-determinism essay to Help (USER-EXPLAINERS has no Music section yet — the alternative surface's slice should add one, the same move that let comfy v2 delete its standing copy). |
| **Write-back** | a finished render's actual values (engine, resolved length, drawn seed, steps used) land in the track's caption chips and write back into More ▸ — the honest record is the editable state; re-run is "click the seed chip". |
| **First-run** | invitation in the stage, Fooocus-grade: one heading + `Get MiniMax · 11.1 GB` / `Get acestep · 7.6 GB` buttons with license on hover — replacing the standing Engines section, which then exists only as the sheet. |

### 3.4 How the field stages music complexity (quick check, doctrine 8b: corroboration, not spec)

Suno's default surface is a single describe-it box (Simple mode) with Custom mode as the
one gate that splits input into a ~200-char **Style** field and a 3,000-char **Lyrics**
field with `[Verse]/[Chorus]`-style section tags — i.e. the entire staging story is
*one mode switch*, and lyrics is the only "advanced" concept promoted to a field; the
July-2026 lyrics editor turned the tag grammar into UI labels rather than taught syntax
([Suno guide](https://aivideosensei.com/guides/suno-complete-guide),
[Custom-mode guide](https://hookgenius.app/learn/suno-custom-mode-guide/),
[v5.5 settings](https://hookgenius.app/learn/best-suno-settings-explained/)). Udio —
the UX reviewers call the field's best ([HowToGeek](https://www.howtogeek.com/udio-offers-the-best-user-experience-in-ai-music-right-now-heres-how-to-use-it/)) —
is a prompt bar with an **Advanced/Manual dropdown** hiding exactly our buried list:
seed (for reproducible clips), clip start/length, prompt/lyrics strength sliders, a
quality-vs-speed slider ([feature rundown](https://braintitan.medium.com/udio-introduces-new-udio-130-music-generation-model-and-more-advanced-features-3f08b9909f7b),
[udio.cloud](https://udio.cloud/udio-new-features/)). The local field is the
anti-pattern pole: ACE-Step's own Gradio demo (the upstream of our acestep.cpp engine)
ships tabbed panels of raw parameters (steps, guidance, seeds, scheduler) with no
staging at all — A1111 in music form. Convergence: **prompt + lyrics-as-the-one-promoted-field + duration at rest; seed/steps/strength behind exactly one gate; nobody
prints engine RAM, file paths, or render telemetry on the create surface.** Our
current page is nearer the Gradio pole; the ruled alternative should sit at the
Suno/Udio shape with our chip grammar carrying the honesty (measured render times,
RAM verdicts, licenses) that the commercial tools simply omit — ours demoted to
hovers, never deleted (LIES-TO-USER rule unchanged).

---

## 4. Proposed slicing

**Slice 1 — "copy demotion" batch (cheap, one slice, no IA changes):**
the MINOR set, mechanical demotions with zero new structure:
- goose.html + aider.html: paragraph + footer → chips with hovers; sentences to Help
  (Goose Help section exists; add Aider to it).
- office.html changeset card: the two policy sentences → the lang-chip + an `undoable ✓`
  chip with hover (card mechanics untouched).
- Models detail: `.md-path` at rest → Reveal/hover (index.html:11095, :9830); the
  Apply-&-reload note → hover (:10962; wording lives bridge-side — same demotion, one
  string move); AUX runner line de-jargoned (:9477).
- Chat: merge `#chat-note` + caps-strip into one chip cluster; model display-name with
  full id on hover.
- MOT home: pin sha → hover (keep `pin ✓` word); feed register pass.
- Caps General: the Odysseus extraction line, Design/Theme descs to one sentence each.
- Customize dialog: intro → first sentence + row hovers.
- Load-consent: env-var sentence → Help.
Each is a wording/one-element change; the whole batch is smaller than one comfy fix.

**Slice 2 — Capabilities → Tools demotion (cheap-to-medium, its own slice because the
copy is load-bearing):** the three paragraphs at index.html:5582 → one sentence + chips
(`19/25 on · 47 tools in prompt`) with the cross-check essay deleted in favor of the two
existing Help sections it duplicates; "Minimal"/"defaults" explanations onto the buttons'
hovers. Needs care because the paragraph documents live-reload behavior users may rely
on — the Help sections must be verified current before the canvas copy is deleted.

**Slice 3 — Audio tab curated section → rows (structural-lite, its own slice):** the
seven VOICE_STARTERS cards re-rendered in the v1.5.34 row grammar (name · role · size ·
license chip · state chip; desc/warn → hover/expando), per the Generate doc's §4.2. Also
sweeps the section intro and the SEARCH-HF caveat paragraph (index.html:2432) into
hovers.

**Slice 4 — office AI panel empty state (cheap, but wording is Debi-sensitive):**
`#ai-empty`/`#ai-empty-blob` → invitation-grade (heading + three example-prompt chips
that insert on click + one trust line); mechanics paragraphs → Help/USER-EXPLAINERS
(§Office section) and onto the changeset card hovers where they are true at the moment
of choice. The L5 history in the comments must ride along so the corrected sentences
don't regress.

**Music — its own slice, already ruled:** the alternative surface per §3, behind its own
button; current page untouched. It should ship together with a USER-EXPLAINERS §Music
section (the destination for every demoted sentence) — same pairing the comfy v2 spec
uses.

**Generate (comfy.html):** already owned by the redesign spec v2; not re-sliced here.

**Not sliced (CLEAN):** Help, Logs, HF browser, memory ledger, Caps Skills.

---

## 5. Honest limits

- Element counts are live-render reads via DOM text extraction on THIS machine's state
  (16 chat models, 6 tracks, populated sessions); a fresh install renders fewer rows but
  the same standing sentences. Counts are inventories, not pixel measurements.
- The office rail's expanded file list, the tier-1 grid states, and the strip were read
  in code but not walked live in depth; the AI panel and changeset card copy quoted here
  are from source (office.html:1494–1527, 8612–8620) and the live empty state.
- goose/aider were seen in their INSTALLED states; the install-flow copy
  (install plans, consent dialogs in `#dlg`) was not separately inventoried beyond the
  standing "Nothing runs until you approve." line (index.html:2554 — which is itself
  correct chip-grade brevity).
- The aider "already running in another window" / NOT CONNECTED contradiction was
  observed once, not reproduced or root-caused.
- The Suno/Udio paragraph rests on official-adjacent guides and reviews (login-gated
  products, same caveat class as the Generate doc §7); ACE-Step's Gradio characterization
  is from its public demo layout, not a fresh install.
- Chat was audited with history present; the true first-ever-run empty chat state was
  not separately walked.
- Severity verdicts are this audit's judgment calls against the comfy.html floor; Debi's
  eye outranks them, per doctrine 9.
