# Installed human-entry journey audit

**Date:** 2026-09-06
**Installed release:** 1.5.82
**Scope:** read-only visible-state audit of every declared M.O.T tab, plus the
meaningful-action evidence already produced by the v1.5.80–v1.5.82 release walks.

This document does not promote page load, HTTP 200, process health, stored config, or
an API call into proof that a person can use the corresponding feature. It separates:

- **walked** — the installed surface and its first meaningful action were exercised;
- **visible only** — the installed surface was inspected, but no meaningful action was
  taken in this audit;
- **conditional** — the page is honestly waiting for user-owned setup or content;
- **reproduced gap** — the installed UI currently contradicts or conceals an authority.

## Current matrix

| Surface | Visible installed state | Meaningful-action evidence | Classification / remaining boundary |
|---|---|---|---|
| M.O.T Deck / component cards | 10/10 component processes answer their configured health probes | Start/stop/restart and ship lifecycle were walked in the v1.5.80–v1.5.82 releases | **Walked for lifecycle, not proof of every component's product workflow.** “Online” means the configured service probe answered. |
| Chat / Agent / embedded Hermes lanes | Composer, lane state and live runner are visible | Chat↔Hermes↔Chat, mid-turn reload, bridge replacement, recovery, completion and explicit Stop were walked | **Walked.** Direct-history insertion remains at-least-once (U139). |
| Models | Registry and live runner are visible | LM Studio membership reconciliation, deleted-row behavior, Rescan and live switch were walked | **Walked for the current LM Studio adapter.** More managers remain U91. Aux-to-Odysseus wiring is absent here (U147). |
| Odysseus native tab | Bridge handoff lands in the authenticated upstream workspace | Reopen, login handoff, cookie reuse and a real authenticated workspace were walked in 1.5.82 | **Walked.** This is the 1.5.81 backend-truth/human-entry incident that created doctrine §12. |
| Hermes native dashboard | Dashboard and `/chat` load; the dashboard currently reports its on-demand generation gateway as stopped while the dashboard service itself is online | Embedded M.O.T Hermes generation was walked; no fresh prompt was sent through the upstream dashboard in this audit | **Visible only.** Do not equate dashboard health with a native-dashboard turn. The stopped gateway may be normal idle/on-demand state; prove a native turn before calling it a defect. |
| Unsloth native tab | Opens at `/login`; auth is initialized, bootstrap password change is complete, and the bootstrap plaintext is no longer present | No authenticated training/inference action was performed | **Conditional, user-owned credential.** The old “auto-fills the bootstrap credential” wording applies only to first bootstrap and must not be read as persistent auto-login. Component health is unauthenticated reachability, not authenticated readiness. |
| OpenCode native tab | Prompt UI opens with a preserved Parable 4B selection while M.O.T's one-model runner currently serves Qwen3.8 27B | Catalog/restart behavior and OpenCode turns were walked in earlier slices; no new native prompt in this audit | **Reproduced known U13/U20-class model-truth gap.** Preserving the user's valid selection is intentional, but llama.cpp serves the resident model; OpenCode has no requested→actual label or load-on-select handoff. |
| DeepSeek native tab | UI opens but requires a workspace before Send is enabled | A real turn from a seeded M.O.T provider was walked when the component landed | **Conditional.** Choosing a workspace is an explicit user action. A green server does not prove a current native-tab turn. |
| Aider lane | PTY is attached and currently waiting at Aider's own “create a git repo?” prompt | Installed parser/start/reattach behavior was walked; no file edit was made in this audit | **Conditional.** The pending upstream prompt is visible and actionable; no claim that editing was re-walked in 1.5.82. |
| Goose UI | Composer, current 27B model and M.O.T workspace are visible | Temporary provider + minted key + real prompt + exact cleanup were walked in 1.5.81 | **Walked.** Upstream provider deletion still leaves a config stanza (U144). |
| LOffice | A real `.xlsx` is open in the embedded full editor | AI ask/reload/history was walked in 1.5.80 | **Partly walked.** Two simultaneous editor surfaces (U6) and Word ribbon text-analysis in a real `.docx` (U7) remain explicitly unwalked. |
| VoiceStudio | Opens at the one-time UI-scale choice | No synthesis in this audit | **Conditional / visible only.** The onboarding is usable, but process health does not prove a completed voice job. |
| Voicebox | Opens with no voice profiles; generation controls are disabled until a profile is created or imported | No profile or generation was created | **Conditional / visible only.** This is honest empty state, not a service failure. |
| ComfyUI native tab | Existing workflow and Run controls are visible | No workflow was queued in this audit | **Visible only.** HTTP and loaded canvas do not prove execution. |
| M.O.T Generate | Curated SDXL/Wan state and a prior output are visible | Earlier render/download integrity journeys exist; no new render in this audit | **Visible only for 1.5.82.** Prior output is evidence of history, not a fresh release walk. |
| M.O.T Music | Both engines report ready and a prior render is playable | Earlier real renders exist; no new render in this audit | **Visible only for 1.5.82.** A prior song is not a new render receipt. |
| Capabilities / API / Help / Logs | First-party pages are reachable | Individual settings, key lifecycle and status actions were walked in their owning slices | **Affected-row proof only.** A future change to a control reopens that control's human journey; page load alone never inherits closure. |

## Findings that change current claims

1. **U145 is the only newly fixed hard entry failure from this audit so far.** The
   Odysseus native tab had no human path to the protected credential until 1.5.82.
2. **Aux copy is presently too broad (U147).** Aux does not currently serve Odysseus
   background tasks on this installation: there is no selected Aux model, listener,
   endpoint, or task/utility binding. The UI must state the actual connection state.
3. **The OpenCode selected-versus-served mismatch is live, not theoretical.** It is the
   already-recorded U13/U20 architecture limit, not evidence that 1.5.81 changed the
   user's chosen model. It must remain visible in release reporting until the product
   offers load-on-select or an exact requested→actual label.
4. **Unsloth is not another Odysseus password-rotation incident.** Its bootstrap has
   completed and its password is user-owned. The gap is claim scope: unauthenticated
   health proves the Studio server, not that the current browser is signed in or that a
   training job works.
5. **Hermes has two health layers.** The dashboard may be online while its generation
   gateway is idle/stopped. The embedded M.O.T lane was walked; the upstream dashboard
   chat was only inspected here.

## Release rule produced by this audit

For every release, the matrix is limited to **affected** human surfaces, but every
affected row must execute the installed-shell entry and first meaningful action. A
whole-app audit may name older unwalked surfaces, as this one does, but must not turn
them into alleged regressions without a counterexample. Conversely, a large backend
gate cannot erase them or promote them to “fully working.”
