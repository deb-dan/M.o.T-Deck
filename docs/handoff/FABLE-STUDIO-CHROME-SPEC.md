# FABLE SPEC — STUDIO CHROME (the "deep theme", v1)
2026-08-20 · Fable 5 · decision-free build spec for an Opus builder.
Reference: Debi's Unsloth screenshots + docs/research/2026-08-20-unsloth-recon.md (§2)
+ the panel control inventory (this spec bakes its findings in).

## What this is
A third visual mode, **Studio**, alongside the editorial default and the light palette:
uniform control sizing, real buttons, and ICON buttons where a glyph says it better than
a word (mic instead of "talk"). It is a CHROME mode, not a color theme — it composes
with light/dark exactly like the old compact axis did. Debi's ruling: add, never remove —
editorial stays the default, light/dark stay independent.

## D1 — Studio REPLACES the parked compact axis (⚠️ surface to Debi, already trailed)
The compact block (27 rules, `html[data-chrome="compact"]`) was three failed attempts at
what Studio actually is. Keeping both would be two half-themes on one button.
- The ▣ topbar chip now toggles **Studio**: `data-chrome="studio"`,
  `localStorage['harness-chrome'] = 'studio' | 'editorial'`. Pre-paint script updated to
  read `'studio'` (a stored legacy `'compact'` value is treated as `'editorial'` — silent
  migration, no modal).
- Delete the compact block wholesale. Rewrite `test_compact_chrome.js` →
  `test_studio_chrome.js`, KEEPING its two hard-won mechanisms verbatim: the
  cascade/specificity resolver (a rule must WIN and REACH the screen) and the VALUE-level
  no-op detector (resolved hex, computed contrast ≥ 1.3:1 against every surface a control
  sits on; no aliasing of --card/--card2/--line2; hover must move in the stated
  direction). Those tests are why compact's third attempt finally landed — they are
  non-negotiable.
- `chromeProbe()` stays, retargeted (probe `#chat-send` too — it becomes an icon button).
- ▣ chip title → "Toggle Studio chrome (uniform buttons + icons)". ⌘K entry renamed.

## D2 — Tokens (namespaced, inside the studio block; values are FINAL)
Reuse the measured compact colors — they were contrast-verified (1.41–1.84 ratios):
```
--st-btn:   #332b50   (light: #e3d9c0)     ground
--st-hi:    #453b6b   (light: #d5c7a6)     hover — dark lightens, light darkens
--st-edge:  #574b83   (light: #b9a878)     border
--st-font:  -apple-system,"SF Pro Text","Segoe UI",system-ui,sans-serif
--st-h:     28px      control height       --st-hs: 22px   small controls
--st-r:     8px       radius               --st-gap: 8px
--st-fs:    12px      label size           --st-fs-s: 11px small labels
```
Text on controls: `var(--fg)` (7.7:1 on --st-btn, verified). The ONE filled control per
surface keeps the cream/gold fill with ink `#171420` (see D5 landmines).

## D3 — The uniform control grammar
Inside `html[data-chrome="studio"]`, every interactive control resolves to:
height `--st-h` (or `--st-hs` where noted), radius `--st-r`, font `--st-fs`/`--st-font`,
`text-transform: none` (mixed case — the editorial small-caps mono stays editorial's),
letter-spacing normal, background `--st-btn`, border `1px solid --st-edge`, hover
`--st-hi`. Concretely, per surface (selector lists come from the inventory — restate
EVERY state the base sheet styles at higher/equal specificity):
- **Topbar**: the four `.chip-icon` chips → 28×28 icon buttons, glyphs at 14px.
- **Mission Control**: bare `<button>` + `button.primary` on cards, checklist, dialogs.
  Primary keeps the cream fill + `#171420` ink + weight 600 (restate — landmine L1).
- **Chat lane chips** (`.mode-chip` incl. `#mode-browse`, `#chat-model-btn`,
  `#chat-audio-btn`): height `--st-hs`, mixed case 11px, gold-filled `.on` keeps
  `#171420` ink; `#chat-model-btn.empty` faint state restated (landmine L3).
- **Composer buttons → ICON BUTTONS** (the headline change, see D4).
- **Session rail**: `#cs-new`, `.cs-act button` at `--st-hs`; `.cs-del.armed` red
  restated (landmine L2 class).
- **Models/Capabilities**: `.chip`, `.caps-tab`, `.cap-btn`, `.mp-act`, `.hfget`,
  `.dlacts button`, `.art-btn`, log-footer buttons → the grammar at `--st-hs`;
  `.cap-btn.arm`/`.go`, `.caps-tab.on`, `.mp-act.on`, `.md-del.armed` states restated
  (landmine L2). `.cap-sw` toggles: keep mechanism, scale track to 40×22 (already) but
  square the knob radius to 6px so it reads as the same family.
- **Deliberately untouched** (exemptions, asserted as negatives in the test):
  `.msg-act` rows (copy/edit/fork/delete stay quiet text — same exemption compact made),
  `details` summaries, `.statusline`, pills (`.mpill`, `.cap-pill`, `.fitpill`),
  `.ap-btn` approval chips (their pill radius is their identity), inputs/textareas/
  selects (only font-family may change), and the entire content column (prose, serif).
- **Known inline-style fighters** (inventory §6): the scattered
  `style="margin-left:8px"`-class inline styles are margins only — they do not fight
  this grammar; leave them. The `.cap-inp` inline width stays.

## D4 — The icon set (inline SVG, the only new assets)
One hidden `<svg><defs>` block after `<body>` opens, 6 symbols, each 16×16 viewBox,
`stroke="currentColor"`, `fill="none"`, stroke-width 1.5, round caps, built ONLY from
primitives (line/rect/circle/path-arc) per these descriptions — no freehand paths:
- `#i-send` — arrow up: vertical line x=8 from y=13 to y=4, plus two lines meeting its
  top (4,8→8,4 and 12,8→8,4).
- `#i-mic` — capsule rect x=6 y=2 w=4 h=7 rx=2; arc from (4,8) to (12,8) bowing down to
  y=12 (a half-circle stand); line (8,12)→(8,14); line (5.5,14)→(10.5,14).
- `#i-auto` — waveform: 5 vertical lines at x=2,5,8,11,14 with heights 4,8,12,8,4
  centered on y=8.
- `#i-conv` — headset: arc from (3,9) to (13,9) bowing up to y=2; rect 2.5×4 at each end
  (x=2 y=9, x=11.5 y=9, rx=1).
- `#i-attach` — plus: (8,3)→(8,13) and (3,8)→(13,8).
- `#i-theme` — half-moon: circle cx=8 cy=8 r=5 with a fill split (reuse ◐ if an SVG
  half-fill is awkward — builder's call which of the two, tag it).
Usage: `<svg class="st-ico"><use href="#i-mic"/></svg>`. In studio mode the composer
buttons render icon + tooltip (title attrs already exist); in editorial mode the text
labels render exactly as today. Implementation rule: the buttons carry BOTH children
(`.st-only` icon span / `.ed-only` text span) toggled purely by CSS under the studio
selector — renderers stay mode-blind, zero JS branching on the theme.
Mappings: Send→`#i-send` (this is the one FILLED button: gold bg, ink `#171420`),
● talk→`#i-mic` (recording state: icon color `--bad`, same signal as today),
auto→`#i-auto` (`.on` → gold icon), conv→`#i-conv` (`.on`/label states move to icon
color + title; the conv chip's status text `● listening/…/▸ speaking` renders as a small
11px status word NEXT to the icon in studio — state must never become invisible),
⊕ attach→`#i-attach`, topbar ◐→`#i-theme` (▣/⌘K/↻ keep their glyphs at 14px).

## D5 — Specificity landmines (from the compact post-mortem; restate, don't rediscover)
L1 `html[…] button` (0,1,2) outranks `button.primary` (0,1,1) → restate primary's fill,
ink and weight inside the block. L2 studio `.cap-btn` (0,2,1) outranks `.arm`/`.go`
(0,2,0) → restate both; same for `.cs-del.armed`, `.md-del.armed`, `.caps-tab.on`,
`.mp-act.on`, `.mode-chip.on`. L3 `#chat-model-btn` (1,1,1) outranks `.empty` (1,1,0) →
restate. L4 `.msg-act` must stay text: the bare-`button` rule must be scoped to
`:not(.msg-act)` or rely on `.cmsg .msg-act` (0,2,0) losing to (0,1,2) — it DOESN'T lose
(classes tie differently): scope the bare-button rule with `:where()` on exemptions or
explicitly exclude — builder picks the mechanism, the TEST asserts the outcome (msg-act
row computed background stays `none`).

## D6 — Scope fence
Phase 1 = everything above, panel-only (`bridge/panel/index.html` + the test rewrite;
no bridge, no Swift, no vendor). NOT in phase 1: sidebar/topbar CUSTOMIZATION
(pin/reorder/hide à la Unsloth — separate Fable spec, will adopt the recon's
`{id, pinned}` order-is-render-order model + two-tier persistence), the
`--ui-font-scale` ratio (recon §2 ADOPT list — phase 3), any change to editorial/light.

## Acceptance (Debi, after ship)
Click ▣ → every button in the app becomes the same-height rounded button family; the
composer shows an up-arrow Send, a mic, a waveform and a headset icon with hover
tooltips; recording still turns the mic red; lane chips read Agent/Chat/Hermes in
mixed-case; ▣ again → today's editorial text chips return byte-identical; ◐ light mode
composes with both. The feed logs the chromeProbe line naming studio=on values.
