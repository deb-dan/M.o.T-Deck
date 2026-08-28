# FABLE SPEC — the Studio design: a real second design, one new button (2026-08-28)

**Debi's ruling, verbatim intent:** the current Editorial design stays untouched and default.
This is NOT a theme pack and does NOT touch the existing ◐ theme button or the ▣ chrome
button. It is a SECOND COMPLETE DESIGN for the first-party panel — the Unsloth / LM Studio /
Jan class of look — switched by its OWN new button, instantly, everything at once.

## 1. The axis

- New root attribute `data-design="studio"` (absence = Editorial, byte-identical today).
- Persisted in NEW localStorage key `harness-design`. The existing `harness-theme` and
  `harness-chrome` keys and their buttons are NOT touched, NOT repurposed, NOT read by the
  new axis beyond graceful coexistence (below).
- ONE new button in the top-right chrome cluster (distinct glyph — suggest ✦ — with a
  tooltip "Studio design"), plus an Appearance row and a ⌘K entry. One click = the whole
  app flips; one click back = Editorial exactly as it was.
- Coexistence rule: under `data-design="studio"`, the studio design OWNS its palette and
  provides its own light and dark variants; the ◐ button keeps working by mapping to
  studio-light/studio-dark (it must never be dead), and theme PACKS (gold/cyber) simply
  don't apply while studio is active (the Appearance select says so in its title — grey-
  not-hide). Leaving studio restores whatever theme/chrome the user had.

## 2. What "a real design" means here (scope: bridge/panel/index.html surfaces only)

Not a reskin: layout, typography, spacing, component shapes, and information hierarchy are
all in scope. LOffice/oo/aider pages are NOT in scope (LOffice is already its own product
look). The DOM CONTRACT IS SACRED: same ids, same handlers, same beacons, same test-pinned
structure — the design is expressed through CSS scoped under `html[data-design="studio"]`
plus, where unavoidable, additive classes/wrappers applied by a single `designApply()`
(no logic forks; renderers stay shared).

Reference class (screenshot Unsloth live on :8899 for calibration; LM Studio/Jan from
memory of the category): clean neutral ground, quiet sidebar, generous-but-dense content
area, sans-serif UI voice, restrained radii, hairline borders over shadows, one accent.

Per-surface bar:
- **Sidebar**: quiet flat nav (no serif wordmark styling in studio — a compact wordmark),
  clear active state, section labels small and quiet, component rows with status dots.
- **MOT Deck (main)**: the hero shrinks to a functional page title; component cards become
  clean rows/cards with clear primary state, aligned metadata, and visible actions on
  hover — the LM Studio "server page" feel, not the editorial magazine feel.
- **Chat lane**: the flagship. Clean composer (single rounded field, send affordance),
  message rhythm like a modern chat (no 20% indents; avatars/roles as quiet labels),
  code blocks and cards keep their grammar but restyled flat+hairline. Session list as a
  compact modern list.
- **Models page**: LM-Studio-class — prominent search, model rows with name/size/pills
  aligned in columns, a clean detail pane; download manager rows flat with progress bars.
- **Capabilities/Logs**: same system — flat cards, hairlines, consistent 8px spacing grid.

## 3. Impeccable rules (binding on the studio design)

From pbakaus/impeccable's anti-pattern set, adopted as hard rules for this design:
never pure black/pure gray (tint everything toward the accent's temperature); never gray
text on colored backgrounds; no card-in-card-in-card nesting; no bounce/elastic easing
(fast ease-out only); typography is deliberate (one UI sans + the existing mono for data;
the serif stays Editorial's signature and does NOT appear in studio); contrast per WCAG on
every state including disabled ink (measure, don't eyeball — the theme-pack fence has the
pattern). The builder must FETCH impeccable's README/detector list and run our studio CSS
against every deterministic rule it can apply by hand, reporting each.

## 4. Tests

- A design fence (the theme-pack fence pattern): every studio rule lives under
  `html[data-design="studio"]` scoping — zero leakage into Editorial (assert Editorial's
  computed styles unchanged with the attribute absent — byte-comparing the stylesheet's
  unscoped portion is acceptable).
- Persistence key, button wiring, ⌘K entry, ◐ mapping under studio, packs-don't-apply
  gating, `designApply()` idempotence.
- All existing suites stay green (nav_panel, studio_chrome, theme_packs, float surfaces).

## 5. Deliverables

Screenshots of every surface in studio-light AND studio-dark (main, chat with a real
conversation, models with the real registry, capabilities), plus Editorial-unchanged
proof. Honest limits per doctrine. This is design QA'd by Fable's eyes before ship.
