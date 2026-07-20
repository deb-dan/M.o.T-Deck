# 08 — Interface strategy (look and feel)

*Part of the Harness doc set. Index: [00_START_HERE.md](00_START_HERE.md). Written 2026-07-20 from Debi's direction. **This changes no locked decisions or milestones** — it sharpens the interface layer's direction and adds one governance rule.*

---

## Debi's stated position (2026-07-20)

- Odysseus: **functions good, UI not liked** — "the arrangement is a bit weird"; fonts/layout need work.
- **Jan and Cherry Studio interfaces are liked.** Use them as the taste reference.
- Components must stay updateable (no forking their UIs) — but the interfaces should get better: fonts, arrangement, "the luxury stuff."
- Preferred end shape: **one main harness interface that feeds into Odysseus / Jan / Hermes**, possibly driving Hermes through Odysseus.

## Governance rule (doctrine amendment, binding)

**All UI design and look-and-feel work is handled by Fable 5 (the orchestrator) only.** No delegation of design decisions, visual taste, layout, typography, or interaction patterns to builder subagents. Builders may *implement* UI only from a Fable-authored spec precise enough to leave no design choices open (exact spacing, type, states). This amends DELEGATION-DOCTRINE.md §2 ("spec'd UI edits" remain delegable — the *spec* is always Fable's).

## The ladder (cheapest first — climb only when the current rung grates)

**Rung A — reskin the webview (M2, alongside the Odysseus tab).**
WKWebView supports injected user stylesheets/scripts (`WKUserScript`). Mission Control injects CSS into the embedded Odysseus tab: fonts, colors, spacing, hiding unwanted sidebar items — the editorial aesthetic applied over their DOM. No fork: upstream updates keep flowing; the skin is a separate CSS file in OUR repo. Honest cost: brittle to upstream class renames — treat skin breakage as a normal pin-bump chore (a contract test can diff the class names the skin depends on). This directly addresses "fonts, etc." at near-zero engineering.

**Rung B — deep-link tabs instead of one Odysseus tab (M2, free).**
The "weird arrangement" is largely Odysseus's navigation. Mission Control can mount *multiple* tabs pointing at specific Odysseus routes (chat, deep research, documents) — its features become YOUR tabs; its arrangement disappears. Combine with Rung A's skin.

**Rung C — liked clients as-is (already sanctioned, zero work).**
Desktop Jan and/or Cherry Studio pointed at the runner endpoint remain manual-convenience chat clients (00 §Accepted #8, 06 §3). If Jan's chat UI is liked, daily plain chat can simply live there until Rung D exists. No Bridge involvement, adopt or delete freely.

**Rung D — native panes: the main interface (M3+, the luxury, now with direction).**
Mission Control grows its own native UI in Debi's aesthetic that talks to component *APIs* instead of embedding their UIs: a chat pane on the runner endpoint, a research launcher calling Odysseus's API (Odysseus becomes a headless service — its UI never seen), Hermes dispatch + activity feed (already planned M3). This is exactly "one main interface that feeds into odysseus, jan ai, hermes." Tripwire discipline (00 §Accepted #6) applies **per pane**: build a native pane only where the reskinned/embedded version still grates after living with it — not wholesale. Mine Cherry Studio's five patterns (06 §3) when designing panes; borrow arrangement taste from Jan/Cherry, never code from AGPL Cherry.

## What this does NOT change

- M0 and M1 exit criteria — untouched. Nothing on this ladder starts before the handshake is green.
- The "never build a chat client from scratch *as commodity*" principle — Rung D panes are deliberate luxuries that must each pass the tripwire, not a wholesale client rebuild.
- Compose-not-fork: no component's UI code is forked at any rung.

## Order of operations when interface work begins (M2)

1. Rung B (deep-linked tabs) — hours.
2. Rung A (injected skin: fonts first, then spacing/colors) — a day, iterated.
3. Live with A+B ≥ a couple of weeks.
4. Only then shortlist which single pane (likely chat) earns Rung D treatment.
