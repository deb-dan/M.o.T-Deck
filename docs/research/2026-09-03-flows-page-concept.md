# A blank page you can put rules on — concept round

**Date:** 2026-09-03 · **Author:** research agent (Opus, Fable brief) · **Status:** CONCEPT ONLY.
No code written, nothing built, no timeline proposed. Three shapes for Debi to choose between;
shape-is-scope, so the choice is the decision.
**Trigger (Debi, 2026-09-03, verbatim):** *"a new page that can be blank and different rules can be
created/added on the page… Researching led me to langflow… but all seem too technical and
overloaded, whereas i'm thinking of just input, processing and output.. of course processing
encompasses engine as well as possible tools.. but overall more simply with the sophistication more
behind the scenes rather than for user to rack/scratch brain over."* Plus: *"be creative, be best"*,
and explicit permission to disregard parts of the input research.
**Read for this doc:** the Gemini "Reactive Canvas" research doc (session input, quoted in §3) ·
`docs/research/2026-08-29-generate-page-redesign.md` (the IA lens and the §6 forks format) ·
`docs/research/2026-08-29-visual-craft.md` (workbench-not-shrine, round-3 history) ·
`docs/research/2026-08-29-surface-audit.md` (the sentence rule applied product-wide) ·
`docs/FABLE-RAM-FIT-ADVISOR-SPEC.md` · `docs/FABLE-AGENT-CHANGESET-SPEC.md` ·
`docs/FABLE-MUSIC-COMPOSE-SPEC.md` §"SPEC v2" (Debi's own round-3 block-grid spec) ·
`docs/FABLE-STUDIO-DESIGN-SPEC.md` · `docs/DOCTRINE-PROACTIVE-BUILD.md` · `docs/ROADMAP.md` ·
`docs/UNFORGET.md` · `bridge/nav.py` · `bridge/panel/index.html` (nav routing, `navOpen`/`showView`) ·
a full read of `bridge/routers/*.py` and `bridge/core/*` for the composable verbs (§0b) ·
langflow README + docs.langflow.org/concepts-components · IFTTT and Zapier help centres ·
Apple Shortcuts support pages.
**Bound by** `docs/DOCTRINE-PROACTIVE-BUILD.md` §8b: the named examples (Langflow, Shortcuts, IFTTT)
are the floor of the reference set, never the design target. The governing lens is ours.

---

## 0. TL;DR

Debi's instinct is not a smaller canvas. It is **a different object**. A canvas makes *plumbing* the
thing you manipulate — that is precisely why Langflow feels overloaded, and shrinking it does not
cure it. Input → processing → output is not a graph with three nodes; it is **a sentence with three
slots**, and a sentence needs no wires because the order is fixed and the connections are positional.

The recommendation is **Option 1, the Sentence Stack**: a blank page whose only standing control is
one field you type a wish into ("every morning, find news about local LLMs and put five bullets in my
Digest sheet"). The aux model turns that into a **rule card** — one line, three quiet slots, read as
English — and the parse is shown as editable chips, never hidden. Cards stack. Click one, it expands
in place to its three pickers and its last real output; click away, it collapses. That is the
workbench grammar Debi already ruled for Compose and Draw Things/VoiceStudio, applied to rules.

The user learns exactly **one** new concept: *a rule*. No ports, no types, no wires, no variables, no
canvas viewport, no "component". The sophistication — which model, whether it fits in RAM, what
order things run in, what gets staged for consent — is entirely behind the card.

Two things the codebase makes easy and one it makes hard:
- **Easy:** every output surface a rule needs already exists and already owns its media (Generate's
  gallery, Music's library, LOffice's changeset card). A rule's output should *land in the page that
  already owns it*, not in a viewport we invent. That is the Gemini doc's "living viewports" idea,
  taken for 10% of the cost.
- **Easy:** the resource-arbiter the Gemini doc spends two pages designing **already exists** —
  `bridge/core/fit.py` plus `GET /api/memory/fit`. Flows must call it, never re-implement it.
- **Hard, and the real cost of the idea:** there is **no scheduler, no cron, no recurring-run
  machinery of any kind** in this product. Grep over `bridge/`, `app/`, `harness.yaml` found only a
  15-second RAM sampler loop. "Every morning" is net-new infrastructure, and on a personal Mac it
  raises a genuine product question (§4) rather than an engineering one.

---

## 0b. What already exists, stated as verbs (the thing a rules page COMPOSES)

Evidence: full read of `bridge/routers/*.py` and `bridge/core/*` by a recon pass this session.
Endpoint paths below are quoted from that read; I have not personally re-verified each line, so treat
the *set* as verified and any single path as high-confidence-but-not-eyeballed-twice.

| Slot | Verb a user would name | What it actually is |
|---|---|---|
| IN | drop / pick a file | `POST /api/office/upload`, `GET /api/office/files`, the music + comfy libraries |
| IN | transcribe an audio file | `POST /api/voice/stt` |
| IN | read a sheet or doc | `office_read`, `office_sheet_stats` (MCP, `readOnlyHint`) |
| IN | search the web | **DOES NOT EXIST as a bridge verb.** SearXNG is a component on :8080 only; the one search path is Odysseus's own web search behind `POST /api/browse/toggle` |
| IN | an event happened | `GET /api/events` (SSE hub, `bridge/core/events.py`) — component/job/memory events |
| DO | ask the loaded model | `POST /api/chat/direct` (SSE) |
| DO | ask an agent with tools | `POST /api/ody/chat`, `POST /api/hermes/chat` (SSE; tool consent via `/api/hermes/approve`) |
| DO | use the small side model | `bridge/routers/aux.py` — exists *precisely* so background work doesn't fight the runner |
| DO | will this fit in RAM? | `bridge/core/fit.py` → `GET /api/memory/fit`, `/api/memory/fits` |
| OUT | make a picture or video | `POST /api/comfy/generate` (workflows already declare `needs` of image/video/audio) |
| OUT | make a song | `POST /api/music/generate` (single job slot, never queues) |
| OUT | say it out loud | `POST /api/voice/tts` |
| OUT | change a spreadsheet | `office_stage_changes` → **staged only**; `POST /api/office/changeset/{id}/apply` is a human button |
| OUT | save a file / reveal it | `POST /api/artifact/save`, `POST /api/open` |
| meta | what can this bridge do? | `GET /api/apiendpoints` — a self-describing endpoint catalogue |

Three facts from that table change the design:

1. **The write path is already solved, and solved the right way.** After the 2026-08-27 agent-consent
   incident, MCP writes were removed: an agent can only *stage* a changeset, and a human applies it
   in LOffice as one before→after card (`docs/FABLE-AGENT-CHANGESET-SPEC.md` §1). A rule that "writes
   to a sheet" therefore already has a consent surface — it does not need one invented, and it must
   **never** be allowed to apply its own changeset. That ruling holds for rules or the incident
   repeats with a schedule attached.
2. **The only saved, named, re-runnable artefact in the whole product today is a music prompt
   template** (`GET|POST /api/music/templates`). There is no flow, pipeline, or recipe concept
   anywhere; `docs/ROADMAP.md` and `docs/UNFORGET.md` mention none. This is net-new scope.
3. **Two worked examples have to be re-pointed to real verbs.** There is no search verb (so a
   "search" step in a first slice means *asking Odysseus with browse on*, and a thin first-party
   `/api/search` over SearXNG is a prerequisite, not a detail). And there is no stem separation —
   it is P6 in the ledger, explicitly not built. So the audio example below is *transcribe*, not
   *stems*. Real data only; a worked example that leans on a verb we don't have is a mockup lie.

**Cost of adding any page at all** (from `bridge/nav.py`, `bridge/panel/index.html`, `app/main.swift`,
`bridge/app.py`, `bridge/appsrc.py`): a lane is its own HTML doc plus its own router file, then a
four-place registration ritual that tests cross-assert — `NAV_ENTRIES` + `DEFAULT_SIDEBAR` +
`DEFAULT_TOPBAR` in `nav.py`, the mirror table in `index.html` (unique glyph, enforced by a census
test), a `HarnessTab` in `main.swift`, and the module name in both `_LANES` and `FILES`. Note the
strip is at **11 of `NAV_TOPBAR_MAX = 12` pins with exactly one free pin**, and `goose`, `comfy`
(Generate) and `gooseui` are each already declared-but-unpinned queuing for it, each with a written
argument for why it didn't spend it. A rules page joins that queue; it does not jump it.

---

## 1. The idea, in Debi's terms

A new page that starts blank. On it you put **rules** — as many as you like, each one a small standing
instruction the harness keeps for you. Every rule is the same three-part thought: *where the stuff
comes from* (and when), *what to do with it*, and *where the result goes*. Processing covers both the
engine and the tools, but you don't pick either unless you want to — the page already knows which
model is loaded, whether it fits, and which surface owns the kind of thing you're making. You should
be able to read a rule out loud in one breath and know exactly what it does, and you should be able to
build one by saying what you want rather than by assembling it. Nothing on the page is there to teach
you a system; the sophistication sits behind the card.

---

## 2. The shapes (shape-is-scope — this is the fork)

### Why Langflow feels overloaded, named precisely

So the concept can define itself against it, from its README and `docs.langflow.org/concepts-components`:

- **The object of manipulation is the plumbing.** A flow is built from *components* — "the building
  blocks of your flows. Like classes in an application" — and the docs' own advice is that
  understanding the **port system** is fundamental: ports "either accept input or produce output of a
  specific data type", and you "connect output ports to input ports of the same type (color)". The
  first thing the product asks you to learn is **its type system, rendered as colours** (Message =
  indigo, LanguageModel = fuchsia, JSON = red). That is a compiler's error message turned into a
  visual affordance, and it is upstream of every other complaint.
- **Config-first, product-second.** The unit of work you configure is a component's parameter form.
  Nodes are, in the Gemini doc's own accurate phrase, *"mostly passive forms rather than living,
  embedded interactive applications."*
- **The vocabulary is LLM-plumbing vocabulary.** Component categories are Inputs/Outputs, Data,
  Processing, Logic, Agents, Embeddings, Vector Stores, Memories, Tools, Helpers, Bundles. Plus
  *freezing* (preventing re-execution), *grouping*, *tweaks*, *global variables*, *playground*.
  Roughly a dozen new nouns before your first useful result.
- **Its front door is a developer's front door.** The quickstart is Python 3.10–3.14, `uv`, Docker;
  its outputs are an API endpoint, a JSON export, or an MCP server.
- **And it scales into spaghetti**, which the field admits: ComfyUI's own entry in the Gemini doc's
  survey table says *"extreme wiring complexity; UI easily becomes tangled."*

The lesson is not "fewer nodes". It is: **do not make the wiring the object.** Every option below is
scored on how many new nouns it costs.

**The field's simple end corroborates.** IFTTT's whole product is one sentence with two slots — *"At
its most basic, an Applet includes a Trigger and one Action"*, the trigger being "the *this*" and the
action "the *that*"; data passed between them is called **ingredients**, a deliberately non-technical
word for what Langflow calls a typed port. Apple Shortcuts is a **list**, not a canvas — *"Each
shortcut is made up of one or more actions"* — and its chaining is implicit: *"each action's output is
available as a Magic Variable… Magic Variables don't require you to save the output of an action for
later use"* (Apple's variables pages, read via search summaries — see Honest limits). Zapier's editor
is a linear step outline, and its own help centre positions the newer visual/diagram view as the thing
you need only *"to view every step within a complicated Zap that includes multiple nested paths."*
Complexity earns the canvas. Three slots do not.

**And Debi has already ruled on this grammar once.** `docs/FABLE-MUSIC-COMPOSE-SPEC.md` §"SPEC v2"
records her own round-3 structure for Compose: *"draggable block grid (~3/row, 2-3 rows, live reflow,
arrangement persisted)"* with *"ledger as ONE compact block"*. Blocks in a grid, arrangement
remembered, **no wires**. That is a house precedent, not an inference, and every option below should be
read against it.

---

### Option 1 — THE SENTENCE STACK (recommended)

**One screen, in workbench grammar.** Five zones, top to bottom:

1. **Header line.** `Rules · 4` and one live state chip — *"1 running · 2 due at 08:00 · 1 off"*. No
   prose. The chip is the page's whole status.
2. **The say-it line.** One full-width field, always present, the page's product and its empty state
   at once. Placeholder is a real example, not instructions. First-ever visit shows only this line
   plus two or three example sentences as clickable chips — the invitation *is* the control, which is
   the one sentence the buried-layer rule permits at rest.
3. **The stack.** One row per rule. A row is: state dot · the sentence, with its three slots set as
   quiet chips inside it · the last result as **one** glanceable thing on the right (a 32px thumb, a
   waveform sliver, a `3 cells staged` chip, or eight words of text) · `⋯`. Reading down the stack
   tells you everything you own and whether it worked. Density is the point.
4. **The expanded rule.** Click a row and it grows *in place*, pushing the rest down, into: the three
   slots as stacked pickers (FROM / DO / INTO), the last run's **real** output rendered in the row's
   own zone (image inline, audio in a themed player, text as text, a staged change as the same
   before→after grammar LOffice uses, with an *Open in LOffice* link — never a second Apply button),
   a small run history, and `Run now` · `Off`. Click away and it collapses back exactly. This is the
   VoiceStudio behaviour Debi named in her round-1 verdict, verbatim: *"can click on what I want to
   expand on it and when left, goes back to normal."*
5. **The ledger.** One compact block at the bottom: the last N runs across all rules, one line each,
   with the honest time. Compose's "ledger as ONE compact block" rule, reused.

**Worked example A — the morning digest.**
Debi types: *"every morning find news about local LLMs and put five bullets in my Digest sheet."*
The aux model returns a parse, shown immediately as a card *before* it is saved:

> ◦ **every morning at 08:00** · news about local LLMs → **five bullets, plainest possible** → **Digest.xlsx, sheet "Week"**

Every bold span is a chip; clicking one opens a small picker (the time, the query, the length, the
file). Nothing is hidden and nothing is a form. Save, and it becomes row 1 of the stack.
When it runs: the FROM leg asks Odysseus with browse on (today; a first-party `/api/search` over the
SearXNG we already ship would make it a real verb), the DO leg goes to the aux model if it can hold
the text or to `/api/chat/direct` if the loaded model is a better fit, and the INTO leg calls
`office_stage_changes`. The row then reads *"ran 09:14 (due 08:00 — Mac was asleep) · 5 cells staged"*
and the expanded zone shows the five bullets with *Review in LOffice*. **Debi applies it. The rule
never does.**

**Worked example B — drop an audio file, get notes.**
Debi drags a recording onto the say-it line. The page doesn't ask her to build anything; it proposes a
card: *"this file → transcribe, then notes → a new doc."* One click saves it, and the same rule now
accepts any file she drops on it later. Real verbs end to end: `POST /api/voice/stt` →
`POST /api/chat/direct` → `office_stage_changes` into a new doc. (**Not stems** — stem separation is
P6 and does not exist.)

**Worked example C — cover art for the last song.**
*"whenever I finish a song, make a square cover from its title."* FROM is an SSE event we already
publish; DO is the loaded model turning a title into an image prompt; INTO is
`POST /api/comfy/generate` — and the picture lands **in the Generate gallery**, where pictures already
live. The rule's row shows a thumb; the gallery is the home.

**What the user sees:** four sentences and four thumbnails. **What stays behind the scenes:** which
model served each leg; the aux-vs-runner decision; the `fit.py` verdict and the decision to wait
rather than evict; the single-file job queue; SSE subscriptions; the changeset TTL; retry policy;
`data/flows.json`.

**New concepts the user must learn: one — *a rule*.** The slots label themselves with prepositions.
There is no wire because there is nothing to wire: three slots, fixed order, positional chaining —
Shortcuts' Magic Variable insight with the variable deleted.

**Honest cost.** Roughly seven files: `bridge/panel/flows.html` (a lane doc; Generate is 2,859 lines
and Music 2,497, so budget that class), `bridge/routers/flows.py` (thin — the app-facade test fences
Python modules at 1,500 lines), `bridge/flows.py` (store + slot catalogue), `bridge/core/flowrun.py`
(the runner and its queue), the four-place nav ritual, an `app/main.swift` tab, and journey tests per
doctrine §6. **Two real risks, named.** (a) The sentence parse is the page's front door, so a bad
parse is a first-run failure — mitigated by the parse always being visible and editable, and by the
same page working with the pickers alone if the parser is off. (b) A rule card **is a sentence at
rest**, which brushes against the buried-layer rule from the Generate redesign. I think it passes, and
the argument matters: that rule bans *the product explaining itself* at rest. A rule's sentence is the
**user's own authored content** — the same category as a chat message, a track title, or a filename —
and the page would be unreadable without it. Where the rule bites is everything *around* the card, and
there the budget is chips only.

---

### Option 2 — THE RACK (three columns)

**One screen.** Three labelled columns — **IN · DO · OUT** — and each rule is one **row** spanning
them; the wire is the row itself. A left gutter carries the state dot and a `⋯`. Column headers are
the only labels on the page.

**Glance state.** You read *down* a column to see everything of one kind ("what do I have coming in?"),
and *across* a row to read one rule. That vertical read is the shape's genuine advantage and the reason
to consider it: it makes the harness's *capabilities* legible, not just its rules. A cell shows its
setting as a chip plus, for OUT cells, the last artefact thumb.

**Expand behaviour.** Click a **cell** → that cell grows into its picker while its row's other cells
stay put (a small in-row popover, not a modal). Click a **row's gutter** → the whole row expands
downward into the full run detail and output, exactly as in Option 1. So the rack has two expand
gestures, and that is its first tax.

**Worked example.** The morning digest reads: `⟨ 08:00 · local-LLM news ⟩ | ⟨ five bullets ⟩ | ⟨ Digest.xlsx › Week ⟩`.
Where the rack earns its keep is fan-out: *drop a recording* → **one** IN cell, then **two** OUT cells
in the same row (a transcript doc **and** a summary in a sheet), drawn as a split cell. Option 1 has to
express that as two rules sharing an input, which is honest but slightly redundant.

**What the user sees:** a grid of chips. **What stays behind the scenes:** identical to Option 1 —
same runner, same fit check, same consent path. The two options are the **same backend with a
different page**, which is worth knowing: choosing wrong is a re-skin, not a rebuild.

**New concepts: two-ish** — *a column is a stage* and *a row is one rule* — plus one implicit rule
users get wrong ("does a wider cell mean more?"). The three-slot trinity is more visible here than
anywhere; the cost is that it is visible **as a schema**, which is a step back toward Langflow's
register.

**Honest cost.** Same file set as Option 1 plus meaningfully more layout work (cells that span,
split, and reflow at panel width, with an honest story for a narrow window) and a second expand
gesture to teach. Slightly more effort, one more concept.

---

### Option 3 — THE BOARD (a minimal canvas)

Presented with its real defence, because Debi asked about a canvas and it deserves better than a
strawman.

**The honest defence.** Spatial memory is real: people remember *where* they put a thing better than
they remember what it was called. Debi's own Compose spec already asks for a draggable block grid with
persisted arrangement — so a board is not foreign to this product. And a board can hold **media** at a
size a row cannot, which suits Debi's "media a citizen" instinct.

**The defensible version, if it were built.** Blocks on a soft grid, **no ports, no wires, no types**.
Order comes from **left-to-right position within a lane**, drawn as one faint rail behind the blocks so
the sequence is *visible*, never inferred. Blocks snap to the rail; a block off the rail is inert and
says so. Effectively: Option 1 rotated 90°, with the rail as the sentence.

**Why I argue against it anyway.** The moment you have a plane, three things follow that you cannot
refuse: pan/zoom (a viewport is a new concept and a new place to get lost), overlap and z-order, and
**invisible connection state**. The Gemini doc's "proximity snapping" — *"when a Voicebox block is
physically dragged adjacent to an LLM dialogue output card, the system automatically detects interface
compatibility and creates an invisible, high-priority audio bus"* — is the failure mode stated as a
feature: a connection you cannot see is worse than a wire you can. Then the second rule wants a second
lane, lanes want alignment, and by the fourth rule you have rebuilt the thing Debi rejected. Option 3
costs the most and is the only option whose concept count *grows with use*.

**What I would salvage instead, and it is worth something.** The board instinct is not really about
authoring — it is about **looking at results**. A "wall" of everything the rules made (thumbs, players,
staged-change cards) laid out spatially is a genuinely good idea, and it is a *separate, later,
cheap* feature that composes with Option 1 or 2. Keep the wall; drop the canvas.

**New concepts: four or more** — block, rail/lane, placement-implies-order, viewport (+ inert-block
state). **Cost: highest**, and the only option that risks a build-step dependency (the Gemini doc's
Phase 1 names tldraw or ReactFlow; the panel is hand-written HTML with **zero build step** today, and
that would be the single largest architectural regression on the table).

---

### Option 0 — THE DRAWER (the anti-shape, for honest comparison)

No new page. A `Rules` drawer on the surfaces that already exist: on LOffice, "keep this sheet
updated"; on Generate, "make one of these every Monday"; on Music, "when a song finishes…". Each rule
is authored where its output lives, so the INTO slot is implied and the sentence shrinks to two slots.

**Why it is worth a paragraph:** it is by far the cheapest, it spends no tab pin (and there is exactly
one free), and it teaches nothing new — a drawer is a drawer.
**Why I don't recommend it:** Debi asked for **a blank page you put rules on**, and the drawer
gives up the one thing the blank page is for — seeing everything you own in one glance, which is the
whole workbench doctrine. It also scatters the run ledger across five surfaces. Listed so the
recommendation is a choice and not the only thing on the menu.

---

## 3. Reacting to the Gemini "Reactive Canvas" doc, plainly

It is a competent architecture document for a **different product** — a professional multimodal DAW
for someone who wants to build pipelines. Debi asked for the opposite: the fewest possible nouns.
Read as input, roughly a fifth of it is gold.

### Steal

- **The resource-arbiter instinct — but only the instinct, because the thing exists.** Its §4.1
  designs VRAM quotas, graceful eviction, and pre-warmed KV standby. We already have
  `bridge/core/fit.py` (`fit`, `estimate`, `budget`, `band`, `live_verdict`, `remedies`) behind
  `GET /api/memory/fit`, spec'd in `docs/FABLE-RAM-FIT-ADVISOR-SPEC.md`, and it already computes
  *remedies* rather than verdicts. Rules call it. What we take from §4.1 is the **product rule**, and
  it is the good bit: **a rule never evicts a model out from under Debi.** It waits, and its row says
  what it is waiting for.
- **Sequential execution.** Its eviction section is right that heavy things must not overlap — but the
  answer is a plain **one-at-a-time queue**, which Music already effectively has (single job slot,
  never queues) and Generate already exposes (`/api/comfy/jobs`, cancel). No arbiter, no quota
  algebra: a queue and an honest "waiting" chip.
- **"Living viewports" — reduced to one sentence that pays for itself.** Its §4.4 wants an OnlyOffice
  iframe and an audio scrubber embedded on the canvas. Take instead: **a rule's output IS the existing
  page zone.** Pictures land in Generate's gallery, songs in Music's library, sheet edits in LOffice's
  changeset card. The rule's own row shows a glance-sized proof and a link. Same benefit, none of the
  embedding, and it is also Debi's "media a citizen not a monument".
- **The Director agent — demoted to exactly one job.** Its §4.3 wants Hermes with administrative
  authority over canvas state, instantiating and repairing graphs. Take the **front door only**: a
  small model turning one English sentence into three slots, shown and editable. That is doctrine §5
  (*"prefer context-aware inference… do not resolve ambiguity by interrupting the user"*) satisfied
  cheaply, and it is the one place the sophistication genuinely belongs behind the scenes.
- **One grain of the self-healing idea.** Not autonomous repair — but a failed run must record the
  real error, retry **at most once**, and say it retried. Silent retries are how a schedule becomes a
  liar.
- **The survey table's honesty.** Its own ComfyUI row ("extreme wiring complexity; UI easily becomes
  tangled") and Langflow row ("nodes are mostly passive forms") are the best arguments in the document
  — against its own thesis.

### Drop

- **The infinite canvas, the wire spaghetti, and above all "proximity snapping".** An invisible bus
  created by dragging two blocks near each other is an undiagnosable state. §2 argues this out.
- **`CanvasNodeDescriptor`** — typed input ports keyed by `sourceNodeId`/`outputKey`, an optional
  `transformFn` holding "embedded JS mapping expression", plus `geometry.zIndex` and
  `resourceProfile.estimatedComputeFlops` as user-facing data model. This **is** the Langflow trap,
  transcribed into TypeScript. A rule needs about six fields, none of them a port and none of them JS.
- **The DAW timeline, multitrack stem strips, and mute/solo/bypass.** A real and good feature — for
  **Compose**, where P6's stem-separator dock is already the ruled home for it. It is not a rules
  page, and stem separation does not exist yet in any case.
- **JSON-RPC over WebSockets as a new canvas event bus, zero-copy transfers, SSD-serialised KV
  standby.** We have an SSE hub (`bridge/core/events.py`, `GET /api/events`). A second bus is invented
  infrastructure; the standby cache is a research project wearing a spec's clothes.
- **Unsloth as a canvas node** (its own table says it "requires exclusive GPU/VRAM allocation; pauses
  other inference tasks"). A training run is a project, not a step in a sentence. Its presence is what
  forces the whole arbiter apparatus — remove it and the arbiter shrinks to a queue.
- **Electron/Tauri/tldraw/ReactFlow (its Phase 1).** The panel is hand-written HTML, no build step,
  DOM contract test-pinned. Non-starter.
- **Its four-phase roadmap.** Not ours to accept, and it sequences the two hardest things (arbiter,
  director) last — which is exactly backwards for a product whose value shows up in the first ten
  minutes.

### One thing it gets right that I'd underline

Its diagnosis — *"interface fragmentation… forced to switch constantly between"* surfaces — is the
true reason this page should exist. It just concluded that the cure is a canvas that contains
everything. The cure is **a page of standing sentences that point at everything.**

---

## 4. Where rules would actually run (sketch, with the real questions flagged)

**Hard fact first:** there is **no scheduler**. An exhaustive grep of `bridge/`, `app/` and
`harness.yaml` for `apscheduler|crontab|cron|scheduler|interval|timer` found: a diffusion sampler
named "scheduler", a comment about upstream Hermes's cron ticker, `goosed` being spawned with
`--enable-scheduler` that **the bridge never calls**, and one real recurring loop — the 15-second RAM
sampler in `bridge/core/memory.py` (`start_sampler`), which samples memory and cannot run jobs. The
closest primitives are the SSE hub and the ~34 existing one-shot background-thread/task sites.

Three run modes, in ascending cost. **They are separable, and that separability is the main scoping
insight here.**

**(a) On demand — `Run now`.** Zero new machinery: the runner walks three slots and calls three
endpoints we already have. A rule that only runs on demand is *already* the useful thing — it is a
saved recipe, and this product has exactly one saved recipe today (music templates). Worth saying
plainly: **a first slice with no scheduler at all is a real product**, and it is where I'd start.

**(b) On an event.** Subscribe the runner to `GET /api/events`, which already carries component, job
and memory events — so "when a song finishes" and "when a download completes" are nearly free. "When a
file appears" needs one new primitive: a watched folder (`~/Harness/Inbox` or similar). Small.

**(c) On a clock.** Net-new, and it is not mainly an engineering question — **it is a product question,
because a personal Mac is asleep at 08:00.** Three candidate answers:
  - **A bridge-side ticker with a durable next-run ledger** (in `data/flows.json`), catching up on wake
    with a staleness cap, and the card **always** stating actual-vs-intended time — *"ran 09:14 (due
    08:00)"*. Recommended. It is the only one that cannot lie about when it ran, and the LIES-TO-USER
    rule outranks everything.
  - **launchd**, so rules fire with the app closed. Rejected on instinct: it means loading a 20GB model
    on a machine whose owner isn't there. Worth Debi's word, not mine.
  - **"When you're here."** Reframe the schedule itself: *"every morning"* on a personal machine
    honestly means *"the first time I open the Deck after 08:00."* This is my favourite answer and I am
    not sure it is right — it is question 2 in §5.

**Three invariants that hold in every mode**, and they are the ones I'd write into a spec first:
1. **One at a time.** A single queue through `fit.py`. Never two heavy things, never an eviction of a
   model the user is using. A waiting rule says what it waits for.
2. **A rule never applies a write.** Sheet and doc output stops at `office_stage_changes`; Debi presses
   Apply in LOffice. This is the 2026-08-27 incident's ruling and a schedule makes it *more* load-bearing,
   not less. Likewise agent tool calls keep their existing consent gate — which means an unattended rule
   that needs a tool must **park** and say so, not auto-approve. Worth an explicit line in any spec.
3. **A run is a record.** Every run writes an honest ledger line (when it was due, when it ran, what it
   made, what failed) or the page becomes folklore.

**Real questions I am flagging rather than answering:** what happens to a rule whose model was deleted
or whose file was renamed; whether two rules may share an output file; what a rule does when it is due
and the fit verdict says `over`; how a rule is paused vs deleted vs "off"; and whether run history is
capped by count, age, or disk.

---

## 5. Open questions for Debi (the ones that change the shape)

1. **Is a rule always exactly one IN, one DO, one OUT — or must it fan out?** If one-to-one is enough,
   Option 1 wins on every axis. If a single input routinely needs two or three outputs, the Rack (2)
   earns its extra concept. This is *the* fork.
2. **Do rules run when you are not looking?** (a) Only on demand · (b) also on events while the Deck is
   open · (c) truly on a clock, catching up when the Mac wakes · (d) even with the app closed
   (launchd). Each step up is a distinct slice, and (d) I would argue against.
3. **Is "processing" a picked verb or a sentence in your own words?** A picked verb means a small
   catalogue (summarize · rewrite · describe · make a picture · speak · transcribe) that is honest and
   finite. A sentence means the agent does it with tools — infinitely more capable, and it inherits the
   tool-consent gate, which unattended runs cannot satisfy. My instinct is **both, with the picked verb
   as the default and "in your own words" as the escape hatch** — but it changes the runner.
4. **Where does output live?** In the page that already owns that media (recommended — Generate's
   gallery, Music's library, LOffice's card), or also duplicated on the rules page itself? Decides
   whether this page needs an output surface at all, which is a large chunk of its cost.
5. **When a rule needs a model that isn't loaded:** load it if nothing else is using it, or always wait
   and say so? (a) is more useful, (b) can never surprise you mid-chat.
6. **What is it called?** "Flows" is Langflow's word and carries its register. Debi's own word was
   **rules**; **Recipes** is the other candidate. Naming here is design, not labelling.

---

## 6. Honest limits

- **This is a concept round. No code was written, nothing was built, no mockups were produced, and no
  timeline is proposed.** The effort sizes in §2 are judgments from file sizes and the registration
  ritual, not estimates from a plan. The scheduler's real cost was not sized at all.
- **The verb inventory in §0b is a recon pass's code read** of `bridge/routers/*.py` and `bridge/core/*`
  performed this session. The *set* of lanes and the load-bearing negatives (no scheduler, no search
  verb, no stem separation, no saved-pipeline concept, staged-only office writes) I consider verified —
  each was grepped for explicitly. Individual endpoint paths are quoted from that read and were not each
  re-eyeballed by me.
- **Langflow was read from its README and one docs page** (`concepts-components`), not from driving the
  app. The component-category list and the port-colour examples are that page's own summary; the version
  was not pinned and the product moves fast. The characterisation "config-first, node soup" is my
  inference from those two sources plus the Gemini doc's own survey row — it is an argument, not a
  measurement.
- **Apple Shortcuts is the weakest citation here.** Two direct fetches of Apple's "How content flows
  through a shortcut" page returned only its table of contents, so the Magic Variable wording comes from
  search-result summaries of Apple's *Use variables* / *Variable types* pages rather than a verbatim
  fetch. The claim being made is small (Shortcuts is a list, chaining is implicit) and is corroborated by
  Apple's own "made up of one or more actions" phrasing, but treat the quotation as second-hand.
- **IFTTT and Zapier** come from their help centres via search summaries, not from using the products.
  IFTTT's trigger/action/ingredients vocabulary is quoted from its own glossary and is solid; the Zapier
  claim is deliberately narrow (its own docs position the diagram view as the answer for *complicated*
  Zaps) and I did not find a stated design rationale, so no philosophy is attributed to them.
- **Nothing here has been tested against a live panel.** The one-screen and glance-state claims in §2
  are inventory arguments in the Generate-redesign tradition, not rendered measurements; a mockup round
  (as followed the Generate redesign, where hero layouts were rejected) is the natural next step if a
  shape is chosen, and it is where the density claims get proven or fail.
- **The tab-pin arithmetic is read from `bridge/nav.py`'s own comments** (11 of `NAV_TOPBAR_MAX = 12`,
  one free pin, three lanes already declared-but-unpinned). I did not run the nav tests to confirm the
  current saved state on this machine, and `data/nav.json` reflects Debi's own arrangement, which may
  differ from the defaults.
- **The one place I may be wrong in a way that matters:** Option 1 stakes the page's front door on a
  small model parsing a sentence into three slots. If that parse is unreliable on Debi's real phrasings,
  the page still works via the pickers but loses the thing that makes it feel like magic — and I have not
  tested a single parse. A cheap way to settle it before any build: run twenty of Debi's own sentences
  through the aux model and read the slots.
