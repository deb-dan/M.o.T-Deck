# 07 — Salvage report: motdeck v1 ("MOT Deck project" folder)

## ⟳ STATE UPDATE — 2026-08-07

Frozen archaeology — still accurate as history, and its post-mortem lesson ("the project-killer was
provisioning UX, not architecture") was borne out: one-switch provisioning and the fat offline
installer are both shipped. Current state → `CLAUDE.md`; system reference → `docs/MOT-DECK-INTERNALS.md`.
---


*Part of the MOT Deck doc set. Index: [00_START_HERE.md](00_START_HERE.md). Reviewed 2026-07-20 under quarantine rules: read-only, evaluated against the locked decisions, nothing merged silently.*

---

## Verdict

**v1 is not a failed separate project — it is this project's own scaffold, one iteration back.** The doc set's "build state: mid-M0, Bridge and Mission Control exist and work" describes exactly the code in the `MOT Deck project` folder: FastAPI Bridge (~136 lines: status/plan/install/start/stop/logs), dark editorial panel with ⌘K, Swift WKWebView shell, compiled `dist/MOT Deck.app`, Hermes installed in `data/hermes-venv`. The planning docs (00–06) were written as its continuation. **The v1 codebase remains the working M0 scaffold; nothing gets rebuilt from zero.**

## Why it stalled (post-mortem, Debi's words + evidence)

Installs were cumbersome and multi-step ("install this, install that"), failures were silent (Hermes Start button died with an empty log — recorded in v1's CLAUDE.md), and the panel felt barebones. Diagnosis: **not an architecture failure — a provisioning-UX failure.** This upgrades the one-switch requirement from nice-to-have to "addresses the proven project-killer." Build order implication: error surfacing on status cards + fully scripted installs are the load-bearing 80%; the dependency-closure approval dialog is polish on top.

## Salvage — carry forward

1. **The codebase itself.** Bridge, panel, Swift shell, scripts (`bootstrap.sh` with stdin drain, `install_component.sh` with plan-then-approve, `doctor.sh`). Already uses `uv` for venvs/installs — faster than pip; the 02 manifests should adopt `uv` too.
2. **Port bug caught: :7000 conflicts with macOS AirPlay Receiver.** v1's `motdeck.yaml` used 7860 for exactly this reason; the doc set had reintroduced :7000. **Fixed 2026-07-20: Odysseus is :7860 throughout this doc set.**
3. **Known-gotchas list (v1 CLAUDE.md)** — all still true: zsh doesn't expand `~` inside quotes; uvicorn crashes on `--log-config /dev/null`; new scripts need `chmod +x`; multi-line pastes answer interactive prompts (drain stdin / use `--yes`); submodule dirs are `vendor/hermes` and `vendor/odysseus` (not `vendor/hermes-agent`).
4. **Blue-green update pattern** (v1 architecture §6.1): stage new version on a parallel port with its own venv → contract tests → atomic switch or discard; pin changes are git commits. Richer than the current pin/rollback story — fold into the M1 update verb. `bridge/contract_tests/` exists as a seed.
5. **Shelved, not rejected — gearbox** (v1 §7): policy-routed local/cloud proxy with privacy globs, escalation, daily budget (`policies/routing.yaml` drafted). Irrelevant while MOT Deck is local-only; revive only if cloud keys ever enter.
6. **Shelved, not rejected — adapter topology** (v1 §4.3): register Hermes as an MCP server *inside* Odysseus, so the workspace chat can drive the agent. Strongest known answer to "one interface" for chat-driven agent work; a genuine M3 candidate alongside the activity-feed integration.
7. **Unified memory sketch** (v1 §8): workspace as durable memory layer, nightly distillation of agent session memory into a note. Good M3+ raw material.

## Rejected — contradicts locked decisions (documented so it can't creep back)

| v1 idea | Why rejected |
|---|---|
| Odysseus Cookbook as canonical model server | Locked: headless Jan :6767 behind the runner slot. Cookbook ties inference to Odysseus and breaks runner swappability. |
| `ddgs` (DuckDuckGo) instead of SearXNG | The workaround existed only because v1 believed SearXNG required Docker. The native from-source recipe (02 §SearXNG) makes it obsolete. Locked: shared native SearXNG :8080. |
| "Odysseus is AGPL" | Stale fact — MIT (verified). Jan likewise Apache-2.0, not AGPL. |
| Hermes via `mcp_serve.py` :8721 as the primary integration | Current plan: Hermes runs as its own daemon against the runner endpoint; simpler M0/M1. The MCP-into-Odysseus shape returns, if at all, as the M3 adapter (salvage #6). |
| v1 roadmap M2–M5 (buildkit, GH Actions Windows builds, visual verification, Tailscale) | Out of scope for the current milestones; revisit only after M3 if ever. |

## Code audit (2026-07-20, second pass — every file read, not just the handoff docs)

Full read of `bridge/app.py`, `panel/index.html`, `app/main.swift`, `app/Config.swift`, all seven scripts, contract tests, stubs, and the relevant vendored entrypoints. Failure archaeology per the doctrine (symptom → root cause → evidence → status):

1. **Hermes Start silently fails** → **v1 invokes Hermes wrongly, twice over.** `start_component.sh` runs `python mcp_serve.py --port 8721`, but the pinned Hermes's `mcp_serve.py` is a **stdio** MCP server (docstring usage: `hermes mcp serve`) with **no `--port` flag** — it exits before writing anything, `nohup` swallows the error, the pid file points at a corpse, and `:8721` never opens so the status card can never go green. Worse, the install step's promise to "point Hermes provider at the gearbox endpoint" was never implemented (gearbox is a 9-line stub) — installed Hermes had **no model config at all**. Evidence: `vendor/hermes/mcp_serve.py` lines 1–30; `bridge/gearbox.py`; empty `data/logs/hermes.log`. **Status: root cause verified; fix = new plan's M0 tasks (run the Hermes daemon against a real endpoint via directly-written `config.yaml`; abandon the `:8721` invocation entirely).** The v1 ":8721 MCP" integration premise is invalid against this pin — consistent with the new topology (Hermes daemon → runner endpoint), so no plan change needed.
2. **MOT Deck.app "compiled and ready" (v1 CLAUDE.md)** → **false in the current location.** `app/Config.swift` bakes `motdeckRoot = /Users/debikunu/Documents/Claude/Projects/MOT Deck project`; the folder now lives under `/Users/debik/Claude Proj Rootz/`. The app's `startBridge()` guard fails silently (missing venv python at the old path) → "Bridge failed to start" after 20 retries. Evidence: `Config.swift` line 2; `main.swift` lines 71–73. **Status: verified; fix = re-run `scripts/build_app.sh` from the new location (it regenerates Config.swift).**
3. **`data/` venvs are stale** — venv `activate` scripts embed absolute `VIRTUAL_ENV` paths from the old location; sourcing them prepends a nonexistent bin dir. **Status: verified by construction; fix = venvs excluded from the move — re-run `bootstrap.sh` + panel installs (this also exercises the exact flow M0 is meant to harden).**
4. **Confirmed accurate in the docs:** Bridge API surface (status/plan/install/start/stop/logs, update→501), panel behavior (⌘K palette, plan→approve dialog with log tail on failure, cards, feed, 6s poll), bootstrap idempotency + stdin drain + disk check, contract-test seed (pins parse; upstream entrypoint moved-file tripwires), Odysseus on :7860. The install-failure path DOES surface logs in the dialog; it's the **start** path whose error reporting is thin (`act()` shows only the last stderr line) — M0 task 1 remains correctly scoped.

## Disposition of the folder

`MOT Deck project/` stays untouched as the working scaffold + v1 archive. Its `CLAUDE.md` describes v1's state and NEXT ACTION (launch `dist/MOT Deck.app`, fix Hermes start-error surfacing) — still the literal next build step, now tracked from this doc set's M0. When work resumes, update THIS folder's docs; treat v1's CLAUDE.md as historical until the repo is re-pointed at the new plan.
