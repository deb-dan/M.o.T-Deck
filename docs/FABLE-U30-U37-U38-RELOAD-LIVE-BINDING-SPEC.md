# U30/U37/U38 — visible history and process-bound model facts

**Date:** 2026-09-05
**Owner:** GPT-5.6 Sol, implemented and reviewed directly
**Status:** implementation candidate; not shipped or versioned.

**Binding:** `CLAUDE.md`, `docs/DOCTRINE-PROACTIVE-BUILD.md`, live-fact-over-pin,
never-clobber, process-provenance, and “PROVE THE PREMISE, NOT THE PATCH.”

## Rejected designs

- LOffice reload must not call Hermes `session.resume`. That operation creates or
  rebinds live gateway state; repainting stored text is read-only.
- “Latest 30” was an arbitrary hidden truncation. The implemented read uses Hermes's
  actual page endpoint and exposes its 500-row page ceiling when it may have been hit.
- The first item in `/v1/models` is not a universal active-model authority. MLX may
  enumerate cached models. A process-bound launch record is required.
- OpenCode config files on disk do not prove what an already-running process loaded.
  The running process's `/provider` response is the relevant authority.

## U30 — one read-only LOffice history repaint

`GET /api/hermes/session/{stored_id}/history` calls Hermes v2026.8.16's read-only
`GET /api/sessions/{id}/messages` endpoint with its dashboard token and
`include_compacted=true`. It reads that endpoint's documented `messages` field and
fails honestly if the response shape changes; it never silently substitutes an empty
transcript. It never invokes
gateway resume, never creates a live session, and never edits a workbook or transcript.

At LOffice boot, after the AI DOM and stored session id exist, `agentRestoreHistory()`
runs once for that stored id. It clears only previously rendered transcript bubbles,
then renders chronological user/assistant text and available assistant reasoning through
the existing safe text/body renderer. Tool rows are intentionally omitted: the stored
message page does not carry enough event grammar to reconstruct truthful approval/tool
cards. If Hermes reports a full 500-row page, the UI says older messages *may* exist;
it does not claim a known total.

Failures leave the stored ids intact and render one honest retry-on-reload status.
`ai-clear` remains the only destructive transcript action. A newly sent turn is not
overpainted by a delayed restore response.

Permanent evidence covers the real Dashboard response field, compacted display rows,
stored text/reasoning, ignored tool rows, missing sessions, response-shape drift, the
500-row warning, HTML-sensitive content, one-shot boot ordering, and proof that the
route never falls back to `session.resume`.

## U37 — exact runner launch provenance

After the exact owned runner child answers readiness, `start_component.sh` atomically
writes `data/runner.active.json` containing version, PID, kernel birth stamp, engine,
registry model id, and wire id. Readers accept it only while it matches the current
locked `runner.owner` claim and live process birth.

This record, not list ordering, supplies the active id for MLX. A recognized exact
llama.cpp alias/path remains usable as observed wire evidence for a legacy process;
an ambiguous MLX list without a valid launch record yields no live identity rather
than relabelling the saved pin as observed fact.

VoiceStudio, DeepSeek, OpenCode, and Hermes consume the validated launch model at
their own next start. If no valid live record exists they explicitly log that they are
falling back to the saved runner pin. Aux is not called “live” from the main runner's
record. Tests cover matching/mismatched birth, stale PID, missing record, llama.cpp
alias, MLX cache ambiguity, and fallback language.

## U38 — OpenCode's running `/provider` response

OpenCode is asked for the same directory-scoped `/provider` payload its UI consumes
after its exact owned child starts. M.O.T records only the connected flag and model-key
set in `data/opencode.runtime-catalog.json`, bound to that child's PID and birth. The
marker is removed before every launch and is not a second model registry.

`/api/deps` accepts the marker only while the ownership claim still matches, then
compares it with current offerable registry keys through the same
`modelreg.opencode_model_key()` helper used by the seeder. A mismatch is two-observation
debounced and offers Restart OpenCode—the action that provably reloads its in-memory
catalog. Unreadable/unbound markers abstain rather than comparing disk files and
pretending they are runtime state.

The legacy slash-to-underscore key contract can collide (`a/b` versus `a_b`). This
candidate does not silently change persisted OpenCode model addresses; the required
collision-safe migration is recorded separately in UNFORGET.

## Release ceiling

Repository tests make these candidates only. Closure requires the real installed app:

- LOffice ask → reload → transcript appears once → continue → explicit clear;
- runner switch/restart across llama.cpp and any available MLX model, with the launch
  marker matching the actual child;
- OpenCode running during a registry change, then a truthful stale warning and a
  Restart that clears it;
- no live YAML, credential, session, workbook, or model artifact changed outside the
  explicit action being tested.
