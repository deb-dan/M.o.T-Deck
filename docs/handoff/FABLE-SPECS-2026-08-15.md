# FABLE SPECS + VERDICTS — 2026-08-15 (working through the standing list, no deviation)

## A. Fable parts — COMPLETED HERE

### A1. QA verdicts on the pending tags
- **Toolset lever (upstream-API write path):** APPROVED. Writing through Hermes's own
  PUT preserves MCP names parked in the same list; a second writer would drift at pin
  bumps. Price (writes need Hermes running) accepted — same precedent as voice-MCP rows.
- **Drag-tab (shell owns strip clicks):** APPROVED. Lost pressed-highlight accepted;
  explicit segment widths accepted. Same-tab ghosts: APPROVED incl. no-persist rule.
- **Compact chrome:** PARKED per Debi (revisit later; ▣ + probe stays shipped; no
  further work until Debi re-opens it). Debi's intent differs from what was built —
  when revisited, start from Debi's reference screenshots, not from the axis we built.
- **Starter-fetch alternates:** APPROVED (accent-slot substitution only on true
  absence, always reported).
- **Max-turn guard:** DONE + revised to segment semantics (resets on tool calls) after
  Debi's correct objection. APPROVED as revised. `hermes.max_turn_s: 0` disables.
- **ship.sh hardening:** DONE (90s wait, loud failure, honest fingerprint). APPROVED.

### A2. Chat-column split — Fable review of DRAFT-CHAT-SPLIT-ISOLATION.md
VERDICT: adopt **option (a) ChatPane componentization**, phased exactly as drafted:
- **Phase 0 (build first, alone):** fix the security-grade coupling — approval/ask
  POSTs must carry the session id CAPTURED AT CARD RENDER, never the global
  `hermesSid`. Also stamp turn→history mapping per-pane-scope. Zero behavior change.
- **Phase 1:** extract ChatPane state object + element-scoped queries with ONE
  instance. Full suite green, byte-identical behavior.
- **Phase 2:** second column behind a chat-split toggle; global-by-design: mic (one),
  conv machine (one), currentAudio (one clip app-wide), voice defaults.
- Open decisions resolved: rail stays single (column A owns it; column B gets a
  session picker chip); per-column lane chips YES; Hermes allowed in column B v1;
  CSS id→class rewrite allowed with specificity kept via doubled class where needed;
  no --parallel claim in UI copy (two watchable conversations, one runner).
Phases 0+1 are delegable now; Phase 2 after Debi verifies Phase 1.

### A3. Snapshot vendor-bump procedure — DECISION
The **sanctioned mechanism is `./scripts/build_app.sh --fat` + re-provision**. The
runbook's rsync path is approved ONLY as a one-time expedient for PASS 2, with the
explicit check that contract tests run green from the snapshot afterward. If PASS 2
rsync misbehaves in any way, stop and do the fat rebuild. A future `ship.sh
--vendor hermes` sanctioned path is queued as an ops slice (delegable, spec: rsync +
editable reinstall + contract run, refusing when the repo checkout ≠ manifest pin).

### A4. PASS 2 / PASS 3 blocks (hand to Debi on request — copy from
UPDATE-RUNBOOK-2026-08-14.md; they are already complete there, PASS 2 §, PASS 3 §.)

## B. Builder specs — READY TO DELEGATE (in priority order)

### B1. ‼️ HERMES TOOLSET CORRECTNESS (Debi's top item) — dispatched 2026-08-15
Goal: prove-and-fix that our Capabilities switches match what Hermes actually hands
the model, end to end, with the truth surfaced in OUR UI. Spec: (1) our rows must
read back Hermes's OWN state (`GET /api/tools/toolsets` enabled field) rather than
trusting our last write — reconcile on every render; any drift shows a visible
`out of sync — Hermes says X` pill and a one-click "adopt Hermes's state". (2) A
verify affordance: a small `check` action that opens a summary "Hermes will hand the
model N tools: [names]" read live from Hermes (the same numbers its banner shows), so
Debi never has to cross-check two apps again. (3) The skills row explains the two
layers in one sentence (library stays enabled; prompt index removed). (4) Contract
pins for the enabled field. No name heuristics; fail open on missing fields.

### B2. Per-skill trimming (if the one-switch skills lever proves coarse)
`skills.disabled` list (frontmatter names — gotcha recorded in memory): a collapsible
per-skill list under the skills row, checkboxes writing through Hermes's API if one
exists, else the config list via the atomic yaml helper. Only build after Debi asks.

### B3. Persistent STT worker — GATED on the corrected measurement
Debi one-liner (research §3.4): run the in-process load-once/transcribe-thrice test;
if constant overhead > ~400ms/utterance, clone the TTS worker pattern for STT
(same protocol file, `stt` command; ledger + unload rules identical). Do not build
before the measurement.

### B4. silero-VAD upgrade — GATED on Debi reporting false triggers in practice.
Self-host @ricky0123/vad-web + ort-wasm (single-thread) via fetch_vendor_assets.sh;
segmenter interface stays (drop-in for the energy gate); constants preserved.

### B5. Barge-in — RESEARCH first (echo cancellation viability in WKWebView:
getUserMedia echoCancellation constraint vs our own playback; if the OS AEC cancels
our speaker output, mic can stay live during SPEAKING and a detected utterance
interrupts playback). Deliver a report, not code.

## C. Debi's hands (unchanged): PASS 1 block (in chat), split/voice-drop re-verify,
PAT revoke, ear-tests (575ms hangover; 0.4.8 render quality; bf16 vs fp32).
