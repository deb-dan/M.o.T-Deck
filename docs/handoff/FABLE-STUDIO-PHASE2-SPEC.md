# FABLE SPEC — STUDIO PHASE 2: sidebar/topbar customization + the form-fields ruling
2026-08-20 · Fable 5 · decision-free build spec. Reference: Unsloth's Appearance →
Sidebar navigation (recon §2: `{id, pinned}` where ARRAY ORDER IS RENDER ORDER,
unpinned collect in a "More" flyout, two-tier persistence). Debi's asks: pin/reorder/
hide any entry on the side or the top; pages (Music, Office) pinnable to either bar;
relief for the native tab strip, which is at ten tabs and rising.

## Scope
Panel + shell. Three deliverables: (A) the customization data model + settings UI,
(B) the native strip honoring it, (C) the form-fields ruling applied globally.

## A. Data model + persistence
One list per bar, order-is-render-order, exactly Unsloth's shape:
`sidebar: [{id, pinned}]`, `topbar: [{id, pinned}]`. Entry ids form ONE registry
shared by both bars (built in the panel from a static table + the components list):
`mc, chat, models, music, office, caps, policiesFuture(no), logs` (views) and
`odysseus, hermes, voicestudio, voicebox, comfyui, unsloth, aider` (tabs).
- A VIEW pinned to the TOPBAR = a native tab via the existing solo pattern
  (`?solo=<view>` — music already works; generalize the whitelist).
- A TAB pinned to the SIDEBAR = a component row that switches tabs (already built).
- `pinned:false` on the topbar = the tab is HIDDEN from the strip and collects in a
  native "⋯" overflow menu at the strip's right end (an NSMenu from a small button —
  this is the strip-width relief valve). `pinned:false` on the sidebar = hidden there.
- Rules: Mission Control is fixed first on the topbar and cannot be hidden (it is the
  bridge-wait surface); Chat is fixed first on the sidebar; an entry hidden on BOTH
  bars is refused with a note (nothing may become unreachable).
- Persistence two-tier like Unsloth: `localStorage['harness-nav'] v1` (instant) AND
  `data/nav.json` via `GET/POST /api/nav` (atomic write) so the SHELL can read it at
  launch (the shell cannot read localStorage). The shell polls /api/nav generation on
  the existing /api/status carrier (a `nav_gen` counter, same pattern as the hermes
  config generation) and rebuilds the strip when it changes.
- Reorder UI: an "Appearance" section in Capabilities → General (no new top-level
  view): two lists with ↑/↓ buttons and a pin/hide toggle per row (drag-and-drop is
  NOT required — buttons are enough and testable; judgment-tag if you add drag).

## B. Shell honoring it
`app/main.swift`: on launch and on nav_gen change, rebuild the tab strip from the
topbar list (order + pinned), mapping view-ids to solo URLs and component-ids to
their ports. The overflow "⋯" menu lists hidden tabs; selecting one temporarily
shows it (does not persist). All existing behaviors (split, drag, ghosts, ⌘R,
Hermes staleness keyed by TITLE) must survive a rebuilt strip — the tab table is
already dynamic; the rebuild must preserve loaded webviews by ID, not index
(webviews keyed by entry id from now on — the Phase-1 generalization made
primaries an array; this phase keys them by id so reorder never reloads a page).

## C. THE FORM-FIELDS RULING (Fable, closing the music-page gap)
In `data-chrome="studio"`, form fields join the uniform grammar — conservatively:
- `input.cap-inp`, `.cap-num`, `.cap-sel`, `select`, single-line text inputs:
  height `--st-h(28px)` where their row allows, radius `--st-r`, border
  `1px solid --st-edge`, background stays the INPUT ground (a new token
  `--st-inp: #221d38` dark / `#f4efe2` light — darker than --st-btn so fields read
  as wells, not buttons; contrast-check ≥1.3 vs their card surface in the tests),
  font `--st-font` at `--st-fs`.
- `textarea`: font + radius + border + the `--st-inp` ground only (no height rule).
- `.cap-range` slider: track color unchanged, thumb radius 6px (family match).
- Exemptions stand: chat composer `#chat-input` keeps its own 14px prose sizing
  (only ground/border/radius join), and the editorial mode remains untouched.
- Same discipline: rules inside the ONE studio block, resolver + value-level tests
  extended (fields on the Music page are the acceptance case — Debi's exact gap).

## Tests
Nav model pure fns (order, pin/hide, both-bars-hidden refusal, unknown-id drop),
persistence round-trip, nav_gen wiring, shell greps (strip rebuilt from the list,
webviews keyed by id, overflow menu, MC-fixed rule), solo whitelist generalization,
and the studio form-field rules by RESOLUTION on real field elements incl. the
music page (the compact post-mortem discipline). Full sweep green.

## Out of scope (recorded)
Drag-to-reorder polish; per-page custom icons; profile-menu customization
(Unsloth's second list); syncing nav.json into the fat seed defaults.
