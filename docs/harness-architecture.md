# AI Harness — Architecture Document

> **NAMING (2026-08-21):** the product is now **MOT Deck** (*Mixture of Tools*), its home
> screen **MOT Main**. `harness` remains the internal codename — every path, key and
> identifier below is unchanged.

## ⟳ STATE UPDATE — 2026-08-07 (supersedes sections below where they conflict)

This is the original v0.1 design (2026-07-10). It remains the best statement of *intent*; the built
system has moved past it — far more than "Next" below suggests (voice/goose/comfy/office/music
surfaces, isolation ladder, local API, and much more have since shipped; see
`docs/ROADMAP.md` for the current done/next picture). **Authoritative today:
`docs/HARNESS-INTERNALS.md`** (code-derived — ports, the two builds + snapshot rule,
`harness.yaml` keys, the four chat lanes, session stores, models/registry, path-guard, endpoint
index, ops gotchas, install footprint, test index), with decisions and dated history in
`CLAUDE.md`, the deferred-work ledger in `docs/UNFORGET.md`, and the user-facing view in
`docs/USER-EXPLAINERS.md`.

Corrections and deltas:

- **Odysseus is MIT**, not AGPL-3.0 (verified against its LICENSE). The only AGPL component in the
  harness is SearXNG. Pins today: Hermes `v2026.7.30`, Odysseus commit `25c9e73`.
- **We own the model runner.** There is no "Cookbook"/Jan serving layer: the Bridge launches
  `llama-server` (llama.cpp pin `b10295`) for GGUF and `mlx_lm.server` / `mlx_vlm.server` for MLX,
  always on **:6767**, plus an optional aux runner on **:6768**. Jan was removed in July 2026.
- **Port map:** Bridge :8700 · runner :6767 · aux :6768 · Hermes dashboard :9119 (not :8721 MCP) ·
  Odysseus :7860 · SearXNG :8080 · gearbox :8710 **reserved but shelved**.
- **The gearbox (policy-based local↔cloud routing) is SHELVED** — the harness is local-only by
  choice. `policies/routing.yaml` and `inference.cloud` are historical.
- **The updater** (§blue-green + auto-rollback) was not built as designed; pin bumps are manual and
  gated by `bridge/contract_tests/`. `POST /api/components/{name}/update` is still a 501 stub.
- **Grown well beyond this doc:** two app builds (lean dev vs fat offline installer with a
  provisioned snapshot — ship only via `./scripts/ship.sh`), the four chat lanes, model registry +
  download manager + RAM ledger, the Hermes path-guard plugin fence with an audit log, the
  artifacts/canvas renderer, and the Capabilities panel.
- **Next:** voice components as first-class tabs (`docs/handoff/FABLE-VOICE-TABS-SPEC.md`), a
  2nd-Mac `.dmg` first-run test, then M5 remote access.

---


**Version:** 0.1 (draft) · **Date:** 2026-07-10 · **Author:** Debi Daniel (with Claude)
**Scope:** Personal use · macOS-first (Apple Silicon) · webapp access later

---

## 1. Vision

A single self-hosted AI workspace that merges two upstream open-source projects —
[Hermes Agent](https://github.com/NousResearch/hermes-agent) (agent runtime, MIT) and
[Odysseus](https://github.com/pewdiepie-archdaemon/odysseus) (web workspace, AGPL-3.0) —
without forking either, so each can be updated with one click. The harness adds a thin
bridge layer that connects them, routes between local and cloud models by policy, and
gives the agent the ability to compile, test, and visually verify software (e.g. Flutter
macOS apps).

## 2. Design principles

1. **Never modify vendored code.** Hermes and Odysseus are pinned git submodules. All
   glue lives in the bridge. This is what keeps updates one-click.
2. **Native-first on macOS.** No Docker requirement. Apple Silicon GPU (Metal) is only
   reachable natively; Docker would force CPU-only inference.
3. **Hermes is the brain, Odysseus is the face.** One agent owns agency (tools, approval,
   skills, memory nudges). Odysseus provides UI, documents, email, calendar, model serving.
4. **Any OpenAI-compatible endpoint is a model.** Local (Cookbook/llama.cpp, Ollama,
   LM Studio) and cloud (Anthropic, OpenAI, OpenRouter) are interchangeable at the
   routing layer.
5. **The harness maintains itself.** Upstream updates are canaried, contract-tested, and
   auto-rolled-back; the agent proposes bridge patches when upstream breaks the seam.

## 3. System overview

```
┌─────────────────────────────────────────────────────────────────┐
│  macOS (native)                                                 │
│                                                                 │
│  ┌───────────────┐   MCP/ACP    ┌───────────────┐               │
│  │   Odysseus    │◄────────────►│    Bridge     │               │
│  │  web UI :7860 │              │  (the "3rd")  │               │
│  │  docs, email, │              │  - MCP server │               │
│  │  calendar,    │              │  - gearbox    │               │
│  │  Cookbook     │              │  - updater    │               │
│  └───────┬───────┘              │  - build/test │               │
│          │                      └───────┬───────┘               │
│          │ OpenAI-compatible            │ MCP/CLI               │
│          ▼                              ▼                       │
│  ┌───────────────┐              ┌───────────────┐               │
│  │  Inference    │◄─────────────│    Hermes     │               │
│  │  Cookbook/    │              │  agent runtime│               │
│  │  llama.cpp    │              │  tools, skills│               │
│  │  (Metal),     │              │  approval flow│               │
│  │  Ollama,      │              └───────────────┘               │
│  │  LM Studio*   │                                              │
│  └───────────────┘   * optional, for MLX models                 │
│                                                                 │
│  Cloud models (Anthropic/OpenAI/OpenRouter) via gearbox policy  │
│  GitHub Actions (remote): Windows builds only                   │
└─────────────────────────────────────────────────────────────────┘
```

## 4. Components

### 4.1 Odysseus — workspace UI
- Runs natively via `./start-macos.sh` at `http://127.0.0.1:7860`.
- Provides: chat UI, documents, email, notes/calendar, deep research, gallery.
- **Cookbook** handles local model recommendation, download, and serving
  (llama.cpp with Metal when native). Requires `tmux` (brew).
- Web search: bundled SearXNG requires Docker; native install uses the optional
  `ddgs` (DuckDuckGo) provider instead → fully Docker-free.
- Desktop app: `./build-macos-app.sh` wraps Odysseus as a clickable Mac app. This is
  the harness's "desktop app" — no new shell is written.
- Odysseus's own agent is kept for lightweight in-UI tasks only; heavy agentic work
  routes to Hermes via the bridge.

### 4.2 Hermes — agent brain
- Installed natively (`install.sh`), runs its own venv under `~/.hermes`.
- Provides: 40+ tools, shell with **command approval** (the "asks permission"
  behavior), skills with a self-improvement loop, memory, cron, subagents,
  messaging gateway (Telegram etc. — optional later).
- Exposed to the rest of the system via `mcp_serve.py` (MCP server mode).
- Model provider: pointed at the gearbox endpoint (see §7), never directly at a model.

### 4.3 Bridge — the "3rd in between" (the only code we own)
A small Python service (FastAPI, matching both upstreams' stack) with four jobs:

| Module      | Responsibility |
|-------------|----------------|
| `adapter`   | Registers Hermes as an MCP server inside Odysseus; translates between the two so upstream changes are absorbed here and only here. |
| `gearbox`   | OpenAI-compatible proxy endpoint that routes each request to local or cloud per policy (§7). |
| `lifecycle` | Implements the install **and** update buttons: one-click install/enable/disable of each upstream (with explicit permission prompts), pin-bump, blue-green deploy, contract tests, rollback (§6). |
| `buildkit`  | Build/test tools exposed to Hermes: `build(target)`, `test`, `verify_visual` (§9). |

The bridge also serves a minimal control panel page (status, update buttons, model
routing view, budget meter). Buttons are equally available as chat commands.

### 4.4 Inference layer
- **Default:** Odysseus Cookbook serving GGUF models via llama.cpp + Metal.
- **Optional:** Ollama (`localhost:11434/v1`) and LM Studio (`localhost:1234/v1`).
  LM Studio remains useful specifically for **MLX models**, which Odysseus does not
  serve. All are just endpoints to the gearbox; adding one is a config entry.
- **Cloud:** Anthropic / OpenAI / OpenRouter keys held by the gearbox only.

## 5. Repository layout

```
harness/
├── vendor/
│   ├── hermes-agent/     # git submodule → pinned release tag (e.g. v2026.7.1)
│   └── odysseus/         # git submodule → pinned commit on `main` (not `dev`)
├── bridge/               # our code: adapter, gearbox, updater, buildkit
│   ├── contract_tests/   # the seam tests that gate every update
│   └── panel/            # control panel (static page served by bridge)
├── skills/               # git-versioned Hermes skills (synced to ~/.hermes/skills)
├── policies/
│   ├── routing.yaml      # gearbox rules: privacy globs, escalation, budgets
│   └── approvals.yaml    # pre-approved command patterns for Hermes
├── scripts/              # bootstrap.sh, start.sh, stop.sh, doctor.sh
├── .github/workflows/    # windows-build.yml (later)
└── harness.yaml          # pins, ports, endpoints — single source of truth
```

## 6. Component lifecycle: install, update, rollback

### 6.0 Pluggable upstreams

The bridge is the standalone kernel; Hermes and Odysseus are **optional components**
that can each be installed, enabled, disabled, or removed with one button plus an
explicit permission grant. Install flow:

1. Click "Install Hermes" / "Install Odysseus" on the panel.
2. Panel shows a plan: prerequisites to install (brew: python 3.11, uv, tmux),
   download size, commands to run, directories written. Nothing runs before approval.
3. On approval: clone at pinned tag → create isolated venv → run the upstream's own
   installer (`install.sh` / `start-macos.sh` setup steps) → wire into the bridge →
   health check → component shows "running".

Valid modes (gearbox + panel always available, since they live in the bridge):

| Mode | Experience |
|------|-----------|
| Both (default) | Full: Odysseus UI + Hermes brain |
| Hermes only | Agent via Hermes TUI and bridge panel; no web workspace |
| Odysseus only | Web workspace; Odysseus's native agent as fallback brain |

### 6.1 Updates & rollback (self-healing)

**Trigger:** "Update Hermes" / "Update Odysseus" button, chat command, or weekly cron.

1. **Fetch** — resolve latest upstream release tag (Hermes) / `main` commit (Odysseus).
2. **Stage** — check out the new version in a parallel directory with its own venv
   (blue-green: `vendor/odysseus@new` on port 7861 while 7860 keeps serving).
3. **Contract-test** — run `bridge/contract_tests/`: can Hermes still serve MCP? do the
   Odysseus routes/settings the adapter relies on still exist? does a smoke conversation
   round-trip through the bridge?
4. **Switch or rollback** — tests green → atomically repoint ports and update the pin in
   `harness.yaml` (committed, so every upgrade is a git-revertable event). Tests red →
   discard staging, keep running version, file a report.
5. **Self-heal (M3)** — on red, Hermes is handed the upstream changelog + failing test
   output and asked to propose a bridge patch as a git branch. Human approves the merge;
   the agent never merges its own patch.

**Rules:** never track `dev` branches; one upstream updated at a time; last-known-good
pin always retained.

## 7. Model gearbox

An OpenAI-compatible proxy all agents point at. Routing is declarative (`routing.yaml`):

```yaml
privacy:
  - match: ["~/finance/**", "~/health/**", "*.env", "**/secrets*"]
    route: local-only          # content matching these never leaves the machine
tasks:
  chat:            {prefer: local}
  summarize:       {prefer: local}
  agentic-coding:  {prefer: cloud, fallback: local}
escalation:
  start: local
  escalate_on: [tool_call_failure x2, context > local_max, user_request]
budget:
  cloud_daily_usd: 5.00
  on_exceeded: local-only + notify
```

Rationale: small local models are good at chat/summarization/privacy-sensitive work but
are weak *drivers* of long agentic loops (compile→read error→fix→retry). The gearbox
gives you local-first economics with cloud-grade agency, automatically.

## 8. Unified memory

Problem: Hermes has agent memory; Odysseus has notes/docs/vector memory. Unsynced =
two half-informed brains.

Approach: Odysseus's workspace is the **single source of truth**. The bridge exposes
Odysseus documents/notes to Hermes as MCP tools (read/write/search), and a nightly cron
distills Hermes's session memory into an Odysseus note ("what the agent learned").
Hermes keeps its own working memory but treats the workspace as the durable layer.

## 9. Build, test & visual verification

- `build(target)` — wraps `flutter build macos|ios|apk` (and `xcodebuild`, `swift build`)
  locally. Windows `.exe` triggers `windows-build.yml` on GitHub Actions and returns the
  artifact link. Runs under Hermes's approval flow.
- `test` — `flutter analyze`, `flutter test`, `integration_test` on simulator.
- `verify_visual` (M4) — launch the built app, capture screenshots
  (`screencapture` / simulator), have a vision-capable model check them against the
  intent before declaring success. Closes the gap between "it compiled" and "it works".
- Signing/notarization: one-time cert setup, then scripted; documented in `scripts/`.

## 10. Skills as versioned assets

Hermes auto-creates and improves skills. The harness symlinks/syncs `~/.hermes/skills`
↔ `harness/skills/` under git, so learned skills survive updates and machine moves, and
`git log` becomes the agent's visible learning history. Harness-authored skills
(build-flutter, update-harness, verify-visual) live here too.

## 11. Roadmap

| Milestone | Contents | Exit criterion |
|-----------|----------|----------------|
| **M0 — Skeleton** | Repo + submodules pinned, bootstrap.sh, both apps running natively, Hermes visible in Odysseus via MCP (manual wiring) | Chat in Odysseus reaches Hermes and back |
| **M1 — Bridge core** | Adapter hardened, contract tests, control panel v0, install + update buttons with permission flow and rollback (no self-heal) | One-click install and update of each upstream, safe rollback demonstrated |
| **M2 — Gearbox** | Routing proxy, privacy rules, local→cloud escalation, budget | Same conversation transparently mixes local + cloud per policy |
| **M3 — Self-healing + memory** | Agent-authored bridge patches on failed updates; unified memory sync | A deliberately-broken update produces a working agent patch PR |
| **M4 — Build pipeline** | buildkit skills, GH Actions Windows build, visual verification | Harness builds & visually verifies a Flutter macOS app end-to-end |
| **M5 — Reach (optional)** | Tailscale/webapp access from other devices, Hermes messaging gateway | Use harness from phone |

## 12. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Upstream churn breaks the seam (Hermes: 14k commits, fast-moving) | Pin to releases; contract tests gate every update; adapter is the only coupling point |
| Two agent stacks fight (double memory, double scheduling) | Hermes owns agency; Odysseus agent limited to in-UI tasks; memory unified (§8) |
| Local models too weak for agentic loops | Gearbox escalation (§7) |
| MLX models unsupported by Odysseus | Keep LM Studio as optional endpoint |
| AGPL (Odysseus) | Non-issue for personal use; revisit before any distribution |
| Odysseus native lacks bundled SearXNG | Use `ddgs` provider, or run SearXNG alone in Docker if search quality matters |
| Cloud spend surprises | Gearbox daily budget + notify |

## 13. Open questions

1. ACP vs MCP for the Hermes↔Odysseus seam — pick after inspecting `acp_adapter`
   maturity during M0.
2. Does Odysseus Cookbook's llama.cpp serve well enough on your specific Mac (RAM/model
   sizes), or does Ollama become the default? Decide empirically in M0.
3. Which cloud provider(s) get gearbox keys first?
4. ~~Control panel: separate page vs embedded into Odysseus?~~ Resolved: served by the
   bridge, since Odysseus is now an optional component (§6.0).
