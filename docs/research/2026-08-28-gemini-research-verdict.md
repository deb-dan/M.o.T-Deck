# Verdict on the Gemini research/fork (2026-08-28, Fable) — fact-checked against OUR tree today

**Its copy predates this week's wave (one-editor LOffice, changeset agent lane, the campaign),
so several claims are stale; several others describe OUR EXISTING code as if newly built.**

## TRUE and worth adopting (ratified)
1. **app.py IS a monolith — 10,072 lines today (worse than its 9,521).** The satellite modules
   its "decoupling accomplished" table lists (music/voice/office/nav/modeltools/pty_aider, with
   our line counts and test names) ALREADY EXIST IN OUR TREE — that pillar describes us, not it.
   The genuinely new part is splitting app.py itself into routers/ + core/ behind a FACADE that
   re-exports every symbol the contract tests import (its facade pattern is the right call —
   50+ suites import bridge.app internals). ADOPT as its own slice, pure refactor, zero behavior
   change, full gate. AFTER the Hermes bump lands (same file).
2. **Proactive warmup: genuinely absent from our tree (grep: 0 hits).** A 1-token post-switch
   probe to compile Metal shaders + allocate KV before the first user turn is cheap and real
   (the TTFT breakdown table is directionally credible). ADOPT as a small slice after the
   modularization. Runner argv changes (-b/-ub/--flash-attn) are NOT adopted blind — argv is
   contract-pinned; measure first (flash-attn may already be default/set — check).
3. **SSE event bus replacing the 4s poll**: real improvement; our polling was a DELIBERATE
   accepted ruling (2026-08-20), so this is a revisit, not a fix. ADOPT-LATER (after
   modularization gives it a clean core/events.py home).
4. **index.html (12,294 lines) and office.html (9,177) are the same disease** — the research
   didn't say it, but the principle generalizes. Queue page-side modularization thinking for
   the tier-1 deletion slice (office.html shrinks a lot when the retired grid goes).

## ALREADY OURS / ALREADY DONE (no action)
- Module extraction table = our existing files (see above). "Contract facade" framing: our
  app.py already re-exports and hosts routes; the split is the missing half.
- Tool trimming ("77 tools -> Minimal preset"): our toolset levers + minimal preset shipped
  2026-08-15..20 (B2 per-skill lever, seconds-fast preset).
- `ship.sh --restart <component>`: shipped 2026-08-14.
- firstrun_fat downgrade protection: already queued as a builder slice since 2026-08-20 (the
  fat-dmg incident) — the research independently confirms it. Raise priority.
- RAM ledger: spawn_guard ledger exists (voice/music lanes are ledger-gated); the "load group"
  params (n_ctx/ngl/KV-quant/flash-attn UI) are the already-queued Load-group slice from the
  sampling work (D3). The research's pre-flight formula is a reasonable shape for that slice.
- LOffice copilot/keyboard-scoping/Univer items: superseded by v1.5.2–1.5.12 (Univer retired).
- OpenCode installer heredoc fix: OUR installer works (1.18.23 verified live today); its fix
  was for its fork's environment. Our install_music.sh does carry a python heredoc — hygiene
  suite is green, but converting to `python -c` is cheap hardening; fold into any music slice.
- harness.yaml "reset installed:false": that's the repo-vs-snapshot manifest split we
  root-caused today — no action (the audit error came from misreading exactly this).

## TASTE ITEMS — Debi decides
- 4-theme selector (Editorial/Luxury Gold/Cyber/Warm Paper) + sidebar collapse to 48px rail +
  chat spacing tightening. Real work, preserves DOM contract per its claims — but design is
  owned surface-by-surface here and current Appearance v2 shipped differently. If wanted:
  one slice, panel-only, behind the existing theme mechanism (harness-theme), Fable-spec'd.
- Music Studio "deck view" genre gallery: taste; Music lane already has Studio v1.2.

## REJECTED
- HarnessDev.app parallel dev bundle + stop_dev.sh: solves a problem OUR flow doesn't have
  (we ship from repo->snapshot with the gate; a second app bundle doubles the update surface).
  NOTE INSTEAD: the Gemini fork's own processes are STILL RUNNING on this Mac (:7900, :6807 —
  confirmed live today) burning RAM — Debi should stop/decommission that workspace's daemons.
- IPC exotica (UDS/shm/pybind): its own doc rejects them; agreed, for its own stated reasons.
