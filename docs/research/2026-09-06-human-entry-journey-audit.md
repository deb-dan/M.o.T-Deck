# Installed human-entry journey audit

**Date:** 2026-09-06
**Installed release:** 1.5.82
**Scope:** a read-only informational snapshot of every declared M.O.T tab, plus the
meaningful-action evidence already produced for surfaces affected by v1.5.80–v1.5.82.

This document does not promote page load, HTTP 200, process health, stored config, or
an API call into proof that a person can use the corresponding feature. It separates:

- **walked** — the installed surface and its first meaningful action were exercised;
- **visible only** — the installed surface was inspected, but no meaningful action was
  taken in this audit;
- **conditional** — the page is honestly waiting for user-owned setup or content;
- **unaffected / out of scope** — the third-party product is reachable and this release
  did not change or claim its downstream workflow;
- **reproduced gap** — the installed UI currently contradicts or conceals an authority.

Only an **affected** row can block a release for lack of a meaningful-action walk.
Whole-app visibility is useful preservation evidence; it does not turn every upstream
application into an M.O.T acceptance test.

## Current matrix

| Surface | Visible installed state | Meaningful-action evidence | Classification / remaining boundary |
|---|---|---|---|
| M.O.T Deck / component cards | 10/10 component processes answer their configured health probes | Start/stop/restart and ship lifecycle were walked in the v1.5.80–v1.5.82 releases | **Walked for lifecycle, not proof of every component's product workflow.** “Online” means the configured service probe answered. |
| Chat / Agent / embedded Hermes lanes | Composer, lane state and live runner are visible | Chat↔Hermes↔Chat, mid-turn reload, bridge replacement, recovery, completion and explicit Stop were walked | **Walked.** Direct-history insertion remains at-least-once (U139). |
| Models | Registry and live runner are visible | LM Studio membership reconciliation, deleted-row behavior, Rescan and live switch were walked | **Walked for the current LM Studio adapter.** More managers remain U91. Aux is optional; no selected Aux model or binding is a valid state. |
| Odysseus native tab | Bridge handoff lands in the authenticated upstream workspace | Reopen, login handoff, cookie reuse and a real authenticated workspace were walked in 1.5.82 | **Walked.** This is the 1.5.81 backend-truth/human-entry incident that created doctrine §12. |
| Hermes native dashboard | Dashboard and `/chat` load; the dashboard currently reports its on-demand generation gateway as stopped while the dashboard service itself is online | The M.O.T Hermes lane and its affected recovery paths were walked | **Unaffected / out of scope beyond health.** Dashboard availability and M.O.T's embedded Hermes generation lane are separate contracts. A native-dashboard prompt is required only when M.O.T changes or claims that prompt journey. |
| Unsloth native tab | Opens at `/login`; auth is initialized, bootstrap password change is complete, and the bootstrap plaintext is no longer present | The M.O.T install/bootstrap boundary has focused evidence; no user-owned training action was performed | **Unaffected / normal user-owned authentication.** Unsloth is its own app. A release that does not change its auth or job handoff does not owe a signed-in training/inference run. |
| OpenCode native tab | Prompt UI opens with a preserved Parable 4B selection while M.O.T's one-model runner currently serves Qwen3.8 27B | Catalog/restart behavior and OpenCode turns were walked in earlier slices; no new native prompt in this audit | **Reproduced known U13/U20-class model-truth gap.** Preserving the user's valid selection is intentional, but llama.cpp serves the resident model; OpenCode has no requested→actual label or load-on-select handoff. |
| DeepSeek native tab | UI opens but requires a workspace before Send is enabled | A real turn from a seeded M.O.T provider was walked when the component landed | **Unaffected / normal upstream prerequisite.** Choosing a workspace is an explicit user action; no fresh turn is required unless its integration changes. |
| Aider lane | PTY is attached and currently waiting at Aider's own “create a git repo?” prompt | Installed parser/start/reattach behavior was walked | **Unaffected / normal upstream prompt.** A file edit is required only for a release affecting the edit journey. |
| Goose UI | Composer, current 27B model and M.O.T workspace are visible | Temporary provider + minted key + real prompt + exact cleanup were walked in 1.5.81 | **Walked.** Upstream provider deletion still leaves a config stanza (U144). |
| LOffice | A real `.xlsx` is open in the embedded full editor | AI ask/reload/history was walked in 1.5.80 | **Partly walked.** Two simultaneous editor surfaces (U6) and Word ribbon text-analysis in a real `.docx` (U7) remain explicitly unwalked. |
| VoiceStudio | Opens at the one-time UI-scale choice | Install/launch contracts are covered; this release did not change synthesis | **Unaffected / normal onboarding.** No fresh synthesis is required for an unrelated release. |
| Voicebox | Opens with no voice profiles; generation controls are disabled until a profile is created or imported | Install/launch and empty-state contracts are covered | **Unaffected / honest empty state.** Profile creation is user work, not a release prerequisite unless that handoff changes. |
| ComfyUI native tab | Existing workflow and Run controls are visible | Its integration was not affected by this release | **Unaffected / out of scope beyond health and preservation.** |
| M.O.T Generate | Curated SDXL/Wan state and a prior output are visible | Earlier render/download integrity journeys exist; this release did not affect them | **Unaffected / prior owning-slice evidence remains valid.** |
| M.O.T Music | Both engines report ready and a prior render is playable | Earlier real renders exist; this release did not affect them | **Unaffected / prior owning-slice evidence remains valid.** |
| Capabilities / API / Help / Logs | First-party pages are reachable | Individual settings, key lifecycle and status actions were walked in their owning slices | **Affected-row proof only.** A future change to a control reopens that control's human journey; page load alone never inherits closure. |

## Findings that change current claims

1. **U145 is the only newly fixed hard entry failure from this audit so far.** The
   Odysseus native tab had no human path to the protected credential until 1.5.82.
2. **Aux is optional; U147 is withdrawn.** No selected Aux model, listener, endpoint,
   or task/utility binding is a valid configuration. The copy describes what Aux is
   for when configured; absence is not a contradiction or a defect. U142 remains a
   separate ownership-safe credential transaction for an explicitly managed binding.
3. **The OpenCode selected-versus-served mismatch is live, not theoretical.** It is the
   already-recorded U13/U20 architecture limit, not evidence that 1.5.81 changed the
   user's chosen model. It must remain visible in release reporting until the product
   offers load-on-select or an exact requested→actual label.
4. **Unsloth is not another Odysseus password-rotation incident.** Its bootstrap has
   completed and its password is user-owned. That is normal for its own app, and no
   authenticated job is owed by an unrelated M.O.T release.
5. **Hermes has two valid, separate contracts.** Dashboard health proves dashboard
   availability; M.O.T's embedded Hermes lane proves the generation integration. A
   native-dashboard prompt is not an additional universal release requirement.

## Release rule produced by this audit

For every release, the matrix is limited to **affected** human surfaces, but every
affected row must execute the installed-shell entry and first meaningful action. A
whole-app audit may record unaffected visible state, but must not turn ordinary
third-party login, onboarding, optional configuration or lack of fresh user content
into alleged assurance gaps. Conversely, a large backend gate cannot close an affected
human handoff such as the Odysseus credential change without walking it.
