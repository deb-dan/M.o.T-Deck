# VISUAL CRAFT — the research behind the six mockups (2026-08-29)

**Status: this document covers TWO rounds.** Round 1 (directions A–C per page) was rejected
wholesale by Debi — "they all take so much space and don't use space well, all very give away
to just the image/music/video… I want to be able to see everything at a glance, like Draw
Things, yet not overconvoluted, and can click on what I want to expand on it and when left,
goes back to normal, also like VoiceStudio." Round 2 (directions F–H per page) is built to the
**workbench, not a shrine** principle in §2. §1 and §3 are round-1 material and are kept
because the craft rules still bind; §3 is superseded as a recommendation by §3b.

**Scope.** Debi's round-1 verdict on the redesigned pages was "the compose page still feels bland",
with `/comfy` reading visually inert on screenshot evidence: a centred image in a fixed box,
flat wrapping chip rows, large empty margins, no compositional interest. The IA
(7-at-rest, the sentence rule, the chip grammar) is SETTLED and survives untouched. This
round is visual craft only. Deliverables: `docs/mockups/2026-08-29/{compose,generate}-{a,b,c}.html`.

Bound by `docs/DOCTRINE-PROACTIVE-BUILD.md` §8b — the named examples are the floor of the
reference set, never the design to copy; the governing lens stays our own principles.

---

## 1. What each source taught

### pbakaus/impeccable — read from source (`skill/reference/*`, `DESIGN.md`, the 61-rule detector registry)

The load-bearing file is `reference/craft-floor.md`, and it names our exact defect twice.

- **The craft floor's Motion clause**: *"one authored moment, not scattered effects and not
  one identical entrance on every section. Exponential ease-out from an already-visible
  default."* Both shipped pages have zero authored moments — every state change is an
  `innerHTML` swap. Inert is the literal diagnosis.
- **The craft floor's Spacing clause**: *"tight groups, generous separation, more space above
  a heading than below it. Read the computed values."* Both shipped pages are
  `display:grid; gap:12px` end to end — the detector's own `monotonous-spacing` rule, and the
  single largest source of the blandness. One repeated interval means nothing has rank.
- **The craft floor's Browser-surfaces clause**, quoted because it is the cheapest win we
  are not taking: *"the parts you did not draw still carry the design. Text selection, the
  caret, custom scrollbars, focus rings, underline offset, and the numerals in tabular data
  all ship with browser defaults that belong to no design system… This is the cheapest signal
  that a page was built rather than assembled, and the one models skip most reliably."*
  `compose.html` ships a raw `<audio>` element and browser-default selection, caret and
  scrollbars. All six mockups theme every one of these.
- **`reference/animate.md` — the motion thesis**: *"The focal moment must come from this
  product and surface concept. A generic fade-and-rise, hover lift, parallax layer, or scroll
  reveal is not a thesis."* Its duration table: 100–150 ms immediate feedback · 150–300 ms
  routine state · 300–500 ms layout/overlay · 500–800 ms an authored entrance; *"exit faster
  than entrance"*; `cubic-bezier(0.16, 1, 0.3, 1)` for confident arrivals; no bounce.
- **`reference/layout.md`**: the squint test (*"with detail blurred, can you still identify
  the primary element, the secondary element, and the major groups in order?"*), a 4-unit
  base rather than 8-only, and *"density does the amount of information per region fit use
  frequency, decision complexity, and visitor mode"* — which is what makes compose-b and
  generate-b legitimate rather than merely denser.
- **The bans that shaped what these mockups do NOT do**: no eyebrow/kicker above a heading
  (a hard ban, "no brief earns it back" — an early `PLATE` label in generate-a was cut for
  it), no side-stripe accent border on a rounded box, no zero-blur block shadow, no glass as
  decoration, no ghost card (a 1px border under a wide soft shadow — declare elevation once),
  no glyph/emoji icons standing in for an icon system, no SVG imitating a photograph.
- **`reference/quieter.md`** supplies the counterweight this round needs most:
  *"'Quieter' doesn't mean boring or generic… Subtlety requires precision. Quiet without
  intent collapses to generic."* That is exactly what happened to the shipped pages — the
  distillation was right and the precision was never spent.

### emilkowalski/skills — animation and interaction craft (sonner, vaul)

The most valuable thing here is a **gate that produces zero lines of code**, which is the
opposite of the reflex the brief invites.

- **The frequency gate.** 100+/day actions get *no animation, ever*; tens/day get
  near-imperceptible or nothing; occasional gets standard motion; rare/first-time is where
  "the delight budget lives". Verbatim: *"animating something that shouldn't animate… The
  gate exists to produce zero lines of code sometimes. That's a success, not a dodge."*
  This is why compose-b and generate-b carry no staged entrance at all, and why every
  mockup's chip hover is 150 ms and not a flourish.
- **The three easing tokens, taken exactly** (*"built-in CSS easings are too weak"*, and
  never approximate `cubic-bezier(0.4,0,0.2,1)` "because it looks familiar"):
  `--ease-out: cubic-bezier(0.23, 1, 0.32, 1)`, `--ease-in-out: cubic-bezier(0.77, 0, 0.175, 1)`,
  `--ease-drawer: cubic-bezier(0.32, 0.72, 0, 1)`.
- **Durations**: press 100–160 ms · tooltip 125–200 ms · dropdown 150–250 ms · modal/drawer
  200–500 ms. *"UI animations stay under 300 ms."*
- **Press**: `scale(0.97)` (range 0.95–0.98) at 100–160 ms ease-out, on every pressable, and
  *"respond on pointer-down, not on release — waiting for click to show feedback feels dead."*
  *"No `:active` state on button"* is listed as a defect. Both shipped pages have none.
- **Entrances**: never `scale(0)` — *"nothing in the real world appears from nothing"*; start
  at `scale(0.95–0.97)` + `opacity: 0`. `transform` and `opacity` only, plus `clip-path` as the
  sanctioned fourth property. `transition: all` is always a finding.
- **`transform-origin` at the trigger** for anything anchored to one; modals exempt.
- **Stagger 30–80 ms**, and *"stagger is decorative — it must never block interaction."*
- **Progress does not ease.** *"`linear` is correct here — progress shouldn't ease."*
- **Transitions, not keyframes, for anything rapidly retriggered** — keyframes restart,
  transitions retarget.
- **Reduced motion means fewer and gentler, not zero** — keep the opacity and state changes
  that carry meaning, drop the travel.
- **The inert checklist**, which reads as a description of our shipped pages: no `:active`;
  feedback only on release; content that teleports on a conditional render; panels with no
  spatial connection to their trigger; everything arriving at once; symmetric timing everywhere.
- And the restraint that keeps this from becoming a motion demo: *"When unsure whether motion
  feels right, the strongest move is often to delete it."* Delight *"is the result of getting
  the other seven right, not confetti tacked on top."*

### jakubkrehel/skills — interface craft

This is where the physical vocabulary comes from, and it corrects a mistake a dark page
invites.

- **Dark-mode depth.** The three-layer light-mode shadow stack is *invisible on dark
  backgrounds*; dark collapses to **one white ring** — `0 0 0 1px oklch(1 0 0 / 0.08)`,
  hover `/ 0.13` — and the *lift* is carried by an inner top highlight rather than a drop
  shadow. Diagnostic: *"One or two [shadow] recipes is a system; nine is a page where
  everyone invented their own elevation."*
- **Shadows vs borders is a hard split**: shadows for depth, borders for dividers, never a
  shadow on a divider.
- **Concentric radius** — `outer = inner + padding`, and *"the most common thing that makes
  an interface feel off"*; past ~24 px of padding, stop doing the math and pick each layer.
- **Image outlines**, non-negotiable: `outline: 1px solid oklch(1 0 0 / 0.1); outline-offset: -1px`
  — never a tinted near-black, because *"tinted outlines pick up the surrounding surface
  colour and read as dirt on the image edge."* Directly applicable to every thumbnail and
  every result on `/comfy`.
- **The 2× grouping rule**: the gap between groups must be at least twice the gap inside one,
  *"or the grouping reads as noise"*. Our `gap:12px` everywhere fails this by construction.
- **Grouping tools in strict order**: negative space → background shapes → separator lines
  *last*, and only for dense data (a track list qualifies; a hero does not).
- **"Content bleeds, controls float"** — media to the viewport edges, controls inside layout
  margins and `env(safe-area-inset-*)`, full-width buttons inset ~16 px with a visible radius.
  This is the whole structural argument for generate-c.
- **Typography roles bind size + line-height + weight** (Display 36/1.1/600 · Title 24/1.2/600 ·
  Heading 18/1.3/600 · Body 16/1.5/400 · Caption 13/1.4/400); emphasis is one weight step, never
  a size change; `-0.02em` on large headings, nothing on body; `text-wrap: balance` on headings
  and `pretty` on descriptions; **`font-variant-numeric: tabular-nums` on any value that changes**
  — timers, counters, step counts, sizes. Every clock and step readout in these mockups is tabular.
- **Progressive disclosure needs an affordance**: peeking items should show **16–32 px** past
  the container edge; *"content hidden with zero cue may as well not exist."*
- **The HIGH-severity triggers** that constrained the riskiest direction: state carried by
  colour alone; a state change carried by motion alone; content clipped or unreachable at
  320 px or 200 % zoom; a control behind a cue-less disclosure. Generate-c's idle behaviour
  dims to 35 % and never hides *because of this list*, not as a style preference.
- **The generic tells**, quoted because they are a checklist we can be audited against:
  breakpoints at exactly 640/768/1024/1280 (*"which tells you they were never chosen"*),
  built-in easing keywords everywhere, `transition: all`, nine box-shadows, uniform spacing
  plus separator lines compensating for it, mismatched nested radii, four weights one step apart.
- **Prefer the cheaper fix**: delete → use the platform → reuse what the project has →
  correct the value → add. *"A fix written at step 5 where step 1 was available is its own finding."*

### Our own system (`bridge/panel/compose.html`, `comfy.html`, `assets/studio-design.css`, `docs/FABLE-STUDIO-DESIGN-SPEC.md`)

Every mockup inlines the Editorial `:root` token block verbatim and writes no literal colour
below it, so the ALL-DESIGNS rule still holds in principle even though each file commits to
one look for presentation. Editorial's signature is the serif (`New York / Iowan Old Style`)
and the mono micro-caps; the studio design deliberately does not use the serif, and its own
sheet already encodes the impeccable arguments (11 px interactive floor, tinted neutrals, one
easing, elevation blur < 16 px). The chip grammar — one verdict object per chip, label ≤ 5
words, sentence in the tooltip — and the `.say`-only sentence rule are carried unchanged into
all six mockups.

---

## 2. The directions, one line each

### Round 1 — SUPERSEDED. Debi rejected all six: "they all take so much space and don't use space well, all very give away to just the image/music/video."

| File | Direction | The idea |
|---|---|---|
| `compose-a.html` | **The Sleeve** | Editorial-maximal: an asymmetric 7/5 stage — the song's name set in the serif at display scale on the left rail, a square sleeve plate on the right, the raw `<audio>` element replaced by a drawn transport, and one authored arrival when a song finishes. |
| `compose-b.html` | **The Desk** | Studio-precise: a standing library rail plus a bench — the waveform *is* the scrubber, controls are tactile (segmented, stepper, raised/recessed), a level meter exists only while work is live, and there is no staged entrance anywhere. |
| `compose-c.html` | **The Spine** | Composed around time: one vertical thread, the composer at its live end, every song a node on it; the newest node *is* the stage. Pressing Compose makes the prompt you typed physically travel down and become the node being rendered (FLIP continuity). |
| `generate-a.html` | **The Plate** | Editorial-maximal: the result matted and captioned like a book plate, 8/4 against a museum label that stacks the chips as a record; the wait is a band sweep and a step counter drawn on the plate itself. |
| `generate-b.html` | **The Light Table** | Studio-precise: a standing filmstrip rail, a fitted viewport with a checker ground and a docked reporting toolbar, a scanline over the picture during a job; density sized to the real job, which is comparing variants. |
| `generate-c.html` | **The Aperture** | The picture is the page: full-bleed result, all seven elements as floating chrome over it, a peeking filmstrip, and chrome that dims to 35 % when you stop touching anything and returns in 200 ms — it never hides. |

### Round 2 — the workbench directions

**The organizing principle, and it is the spec rather than a mood: a WORKBENCH, NOT A SHRINE.** Composer, current result, history, engine/model state, settings and queue are all on screen at once in one composed dense layout that stays calm. No zone owns the page at rest; the media object is *a* citizen, not *the* monument. Any zone click-expands to focus in place and collapses back on Esc or click-away. Round 1's A–C are all shrines by this test. (`compose-d`, `generate-d` and `generate-e` are an abandoned mid-flight sketch from a superseded brief — on disk, not candidates, and deliberately not completed: `compose-e` was never written because the pivot landed first.)

| File | Direction | The idea |
|---|---|---|
| `compose-f.html` | **The Bento** | A 12 × 12 mosaic of seven zones in exactly three tile footprints; every zone carries the same 28 px mono label bar, hairline and 12 px pad, and any tile FLIPs out to fill the bench while the rest dims. |
| `compose-g.html` | **The Rack** | Rails and stacks — a 48 px icon rail, a history panel, a work column of stacked panels, an inspector — with *three* expansion idioms live: rail collapse (a grid-template swap), stack accordion, and zone focus. |
| `compose-h.html` | **The Ledger** | The page is a run ledger: fourteen songs as 26 px rows carrying sparkline, engine, length, settings, render time and size; the composer is the top row, and the "current track" is simply whichever row is expanded in place. |
| `generate-f.html` | **The Bento** | The same mosaic for images — result, prompt, a 24-cell results grid, settings, models, queue with per-step tiles, disk — the picture holding one tile rather than the page. |
| `generate-g.html` | **The Rack** | The same rails-and-stacks frame: results rail, canvas, composer, queue strip, inspector carrying size/steps/seed/negative plus the model list, with all three expansion idioms. |
| `generate-h.html` | **The Ledger** | Twenty-four runs as 30 px rows — thumbnail, prompt, model, size, steps, seed, time, file — expanding in place into the full picture and its full settings. |

**Where the round-2 zone chrome actually comes from.** Not a moodboard: read live out of **VoiceStudio's own shipped bundle on `:3900`** (`assets/ui-*.css`), so all six speak a language this product already has —
`.glass-panel { border:1px solid var(--chrome-border); border-radius:0; padding:12px }` ·
`--chrome-bar-h:28px` · `--chrome-label-size:11px` · `--chrome-label-track:.06em` (mono, uppercase, on **every** panel) ·
`--chrome-pill-h:20px` · `--chrome-radius-pill:3px` · `--chrome-border:#ffffff14` · `--chrome-border-strong:#ffffff1f` ·
`--chrome-hover-bg:#ffffff0a` · `--transition-fast:.12s ease` · `--transition-smooth:.2s cubic-bezier(.4,0,.2,1)` ·
and the rail geometry G copies outright: `.rail-right { grid-template-columns: minmax(180px,220px) minmax(0,4fr) 48px }` with `.sidebar-collapsed { 46px … }` — **collapse expressed as a grid-template swap rather than as elements moving.**

**What the density research added on top** (Ableton/Logic · Blender/Figma · Linear/Raycast · bento systems · Resolve/TouchDesigner · Shortcuts/Mission Control/Stage Manager) — the rules that changed the build, not just the prose:

- **Blender's one-scalar model.** `unit = round(18 × scale) + 2 × line_width` = **20 px at 1.0**; header `1.25u`; panel margins `0.4u` / `0.1u`. And its entire UI is **11 pt flat** — panel titles are the same size as body; hierarchy comes from weight, colour and indentation. That is why these mockups rank zones by *area and ink*, never by heading size.
- **Blender's property rails.** `UI_ITEM_PROP_SEP_DIVIDE 0.4f` — label 40 % / field 60 %, one global constant for every row in the application, with blank spacers so the field column never jitters.
- **The bento law, stated generally:** a mosaic reads as one system when **footprint is a closed enumeration on a shared unit grid and every other property — radius, gutter, content inset, type scale, border treatment — is held constant across footprints.** Size is then the only free variable, so size can carry meaning. Raycast ships this as an API (`columns` 1–8, seven aspect ratios, three named insets). Apple holds a **constant 16 pt content margin** on a 169 pt tile and on a 360 × 376 one — the inset does not scale with the tile. F uses three footprints and one 12 px inset everywhere.
- **Vercel Geist: the step index *is* the role** — 400 means "default border" in every hue, so a zone goes neutral→danger by swapping hue with zero re-tuning. And its stated rule, adopted: *"Earn borders and backgrounds only when they communicate selection, interaction, or real grouping. Prefer spacing and alignment."* Hence one hairline per zone boundary, **no row dividers inside a zone** (F, G), and dividers only in the genuinely tabular case (H, at 3.5 % white).
- **Linear: theme by generator, not by token list** — three inputs in a perceptually uniform space, and *"when a row is selected, we regenerate the entire theme with the selected background as the new base."* Their calm pass shipped **fewer separators** and a sidebar *"a few notches dimmer"* — **dimming chrome is the hierarchy mechanism, not promoting content.** That is the focus treatment in all six.
- **Raycast's density trade, verbatim:** *"When shown, it is recommended not to show any accessories on the `List.Item` and instead show the additional information in the `List.Item.Detail` view."* Accessories and detail are **mutually exclusive budgets** — exactly what H does when a row expands.
- **Resolve's real insight:** it does not swap workspaces, it **swaps representations inside a fixed frame** — chrome ring, slot geometry and the underlying document are page-invariant. Growth is **zero-sum against a named neighbour**, never a floating overlay: *"makes the Keyframe Editor wider, while at the same time hiding controls at the center to make room."* G's accordion is precisely this.
- **TouchDesigner: hue = family = wiring legality; lightness = generator vs filter.** Colour as a type system rather than decoration — the reason all six use exactly one accent and let state ride on ground + ink + a glyph.
- **Expansion physics, applied numerically.** Container expansion 240–300 ms; a large expansion 300–400 ms; **never past 400** (*"At 500 ms, animations start to feel like a real drag"*); the collapse **15–20 % shorter** than the expansion — these run **260 ms in / 200 ms out (23 % shorter)** on `cubic-bezier(0.23,1,0.32,1)`. Layout manipulation that is *not* a zoom (Blender's split/join/dock/close) runs **0.10–0.15 s** — hence 120 ms hover/press and 200 ms rail collapse. Animate **transform and opacity only**: never `width/height/top/left`, never a blur radius, never text scale.
- **The one finding that changed the build after it was already working:** IBM Carbon gives **background dimming its own slowest token — `slow-02`, 700 ms — against `slow-01` 400 ms for a large expansion.** The scrim must fade *slower* than the thing it backs, so it recedes instead of competing. All six were re-tuned from a 200 ms dim to **620 ms**.
- **The accessibility fence that constrains this whole round.** WebKit names *"scaling and zooming animations"* as a primary vestibular trigger — our core interaction is on that list, as are plane-shifting and animated peripheral rails. Under `prefers-reduced-motion` the zoom degrades to an **opacity crossfade** (what macOS itself does), using **`0.01 ms` rather than `0`** so `transitionend` still fires, and the feature stays usable with the motion gone.
- **Stage Manager's failure, taken as a warning:** a fixed-capacity auto-curated rail with no user override, in permanently reserved space — *"apps cannot be 'ejected' manually."* The user pays rent for a list they cannot edit. G's rails are user-collapsible and nothing here auto-curates membership.

---

## 3. What I would argue for, and why

### Compose → **C, The Spine** (with A's type as the fallback)

The argument is not that it is prettier. It is that compose is the only one of the two pages
whose product has **no visual form**. A picture can carry a page by itself; a song cannot, and
that is the real reason the compose page reads blandest — its hero is a filename and a browser
audio widget. A and B both answer that by drawing something *around* the song (a sleeve, a
meter). C answers it by making the page's structure carry the meaning instead: time. Songs are
made in sittings, one after another, and a thread with beads on it says that with no artwork at all.

It is also the only one of the three with a motion thesis that passes impeccable's own test —
*"the focal moment must come from this product and surface concept"*. A's plate reveal and B's
meter are good; either could appear on a different product unchanged. The prompt physically
becoming the track it makes cannot: it is a statement about what this page *is*, and it is
Emil's continuity/shared-element pattern used for its actual purpose rather than as decoration.
It also happens to fix a real comprehension gap in the shipped page — today, pressing Compose
makes the composer sit still while an unrelated box elsewhere starts a progress bar.

Honest cost: FLIP is the most fragile thing in this round (I already caught it silently never
starting under `requestAnimationFrame` throttling, and had to force a reflow instead), and its
reduced-motion path has to degrade to a crossfade, which loses the whole point for those users.
If Debi wants the lower-risk answer, **A** is it: it needs no JS beyond what the page already
has, and it fixes the blandness with type, rhythm and depth alone.

### Generate → **A, The Plate** (B is the right *second* page, not the right first)

Generate's problem is diagnosable to one line of shipped CSS: `#stage` is
`place-items:center` inside `min-height:min(52vh,460px)`. A portrait result therefore floats in
a wide empty rectangle with a border drawn around the emptiness. That is the "big empty
margins" complaint exactly, and it is a proportion bug, not a decoration deficit. A fixes it at
the root — the frame is sized to the picture and the leftover column is *given a job* (the
label), which converts dead space into the highest-information region on the page. It also
lands three separate research rules at once that the current page fails: the neutral image
outline, the deliberate tight/generous rhythm, and one authored arrival.

C is the most striking of the three and I expect it to win a first look. I am not arguing for
it as the default because generate is an Operate-mode surface in impeccable's taxonomy, where
*"predictable structure, stable density and navigable linearity are affordances"* — and
auto-dimming chrome, however carefully bounded, trades exactly that away. It is the right
answer for a full-screen *review* mode reachable from A, not the answer for the page you sit in.

B is the correct destination the day someone makes twelve variants of one prompt, which is the
real workflow — but it is the second page, opened deliberately, not the one that greets a
first-time user with a standing filmstrip of nothing.

**The one thing I would take from all six regardless of which direction wins:** the spacing
scale, the three easing tokens, `scale(0.97)` on every pressable, tabular figures on every
changing number, and the browser-surface theming. Those are cheap, invisible individually, and
they are most of the difference between "clean" and "alive".

---

## 3b. Round 2 — what I would argue for

**Both pages: H, The Ledger — with F, The Bento, as the safe pick.**

H is the only one of the three where the number of things visible at once **scales with the window** rather than being fixed by the layout, which is the literal reading of "see everything at a glance". It is also the only one that puts the media object fully in its place: a 40 × 26 cell in a row. Every run's settings are legible in a column without opening anything, so "what did I set for that good one" — the actual repeated question on both pages — is answered by reading, not by clicking. And the expand-in-place never moves anything above it, so the ledger never loses your place.

Its risk is honest: a table is the least *lovable* of the three at first glance, and the two pages' rows carry different columns, so it is the direction most likely to read as "a database" to someone expecting a creative tool.

F is the safe pick and would photograph best in a deck: seven named zones, one hero, three footprints, everything at once, and the least new interaction vocabulary. G is the most professional-feeling and the most work — three expansion idioms is genuinely more surface to get right, and its rails re-open the "how much space does chrome deserve" argument that Stage Manager lost.

## 4. Honest limits

- **These are mockups, not code to lift.** They inline tokens, hardcode data, and carry no
  poll loop, no error states, no six-look coverage, no sheets, no first-run invitation and no
  install path. Any of them becoming real is a separate build against the shipped renderers.
- **The pictures are abstract colour fields, deliberately.** Drawing a convincing fox would be
  claiming a render we did not make, and impeccable bans SVG imitating a photograph. This means
  the mockups understate how a real photographic result will change the balance of generate-a
  and generate-c — a busy image needs more scrim than a soft gradient does.
- **No `prefers-reduced-motion` run was executed**, only authored. Every file has a path; none
  was walked with the OS setting on.
- **No contrast measurement.** Ratios were reasoned from the shipped Editorial tokens, which
  are already in the product; the new values (the inner highlights, the scrim alphas, the idle
  35 %) were not measured with a tool. Under `prefers-contrast: more` nothing is provided.
- **Only Editorial dark is shown.** Light, gold, cyber and both studio variants were not built
  in any mockup — that is the ALL-DESIGNS work a shipped version would owe.
- **Walked** at 1280×880 and 380×780 in the browser pane: all six render, all six run their
  press → progress → arrival cycle back to rest, and no page has horizontal overflow at 380.
  Caught and fixed in that pass: a FLIP that never started under rAF throttling (compose-c),
  a `position:fixed` on a shared class that let two children escape their own grid (generate-c),
  a non-wrapping toolbar that pushed its trailing controls off the right edge (generate-b), and
  three fixed bottom elements at three magic offsets that collided at narrow widths (generate-c).
  **Not walked**: keyboard-only traversal, screen readers, 200 % zoom, touch, or any browser
  other than the pane's.
