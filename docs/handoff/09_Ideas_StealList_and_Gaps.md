# 09 — Ideas, Steal-List, and Genuine Gaps (research digest)

## ⟳ STATE UPDATE — 2026-08-07 (supersedes sections below where they conflict)

Fable ranked this list on 2026-07-23; most of the top of it is now built. Live plan: `CLAUDE.md`.

- **Built:** thought-thread telemetry UX (statusline + INSPECT log) · cost/token/speed analytics
  tiles · KV/slot pinning (solved by owning the runner argv) · the **OS-level path-guard fence**
  (shipped as a Hermes `pre_tool_call` plugin that escalates into our approval card, plus a
  `data/logs/guard.log` audit tier and a Logs-pane reader) · artifacts/canvas · per-message actions.
- **Still open from this list:** the **fact-check ✓ badge** (trust surface — Fable-gated) ·
  tiered-memory auto-promotion · session-graph/time-travel · schema-generated settings form ·
  file-based agent mailboxes. All remain parked with their original triggers.
- **Still true and still enforced:** doc 09 §0's correction — the **gearbox is SHELVED** and the
  harness is local-only — plus every 🔴 CONFLICTS tag (no Docker, no WASM, no LanceDB, no React
  rewrite of the panel).
- **Next from the modality side:** voice (`docs/handoff/FABLE-VOICE-TABS-SPEC.md`), not more
  breadth in this list.

---

**Written:** 2026-07-21 (by Claude Opus 4.8, at Debi's request). **Status:** reference only — no code changed, no docs resynced, nothing on any milestone. This captures a research pass over other "agent OS / harness" projects + a Gemini analysis, **cross-checked against this project's own plans (00–08 + `harness/CLAUDE.md` + `policies/routing.yaml`)** so a fresh chat can tell *new* ideas from things already decided/planned/shelved.

**How to read this:** every idea is tagged:
- 🟢 **NEW** — not in the current plan; worth considering.
- 🟡 **ALREADY PLANNED** — in the roadmap/decisions; listed only so nobody re-proposes it as if new.
- 🔴 **CONFLICTS / SHELVED** — contradicts a locked decision, or was deliberately parked.

> **Scope caveat (read first).** This project is deliberately *narrow*: a native shell supervising **Jan** (runner) + **Odysseus** (research) + **Hermes** (agent) + **SearXNG**, composed over APIs, never forked. Many "encompassing multi-agent OS" ideas from the research are broader than that scope. Breadth is not automatically good here — focus is a feature. Ideas below are raw material, not a mandate to expand scope.

> **Design governance (from `08_Interface_Strategy.md`).** All UI look-and-feel decisions belong to the orchestrator (Fable 5), not to builder subagents. The UI references and UX ideas below are **inputs for that design work**, not design decisions.

---

## 0. Correction to earlier advice (important)

In an earlier chat, Claude recommended "build the gearbox next — it's the keystone stub." **That was wrong.** Per `07_Salvage_from_v1.md` #5, the gearbox (local↔cloud routing, privacy globs, escalation, daily budget) is **deliberately shelved** because the harness is local-only today; it revives *only if cloud API keys ever enter*. The draft policy in `policies/routing.yaml` is labeled "(M2)" but the current plan supersedes that label — treat the gearbox as parked. Do not build it without a decision to add cloud.

---

## 1. UI / design references Debi likes (inputs for Fable's design work)

Debi's stated taste (2026-07-20, `08`): likes **Jan** and **Cherry Studio** interfaces; Odysseus "functions good, UI not liked / arrangement weird." New data point (2026-07-21): **also likes OpenFang's UI** and the **komputermechanic Hermes dashboard screenshots**.

| Reference | URL | What specifically to look at |
|---|---|---|
| **OpenFang dashboard** | repo https://github.com/RightNow-AI/openfang · homepage openfang.sh · UI source in `crates/openfang-api/static/` (vanilla JS + Alpine.js + Chart.js, no build step) + Tauri shell `crates/openfang-desktop` | Clean **light/warm** theme (cream canvas, orange accent), **left nav grouped into sections** (Agents / Automation / Extensions / Monitor / System), agent **cards with category tags** + live "RUNNING / Inferencing…" status, top-right "+ New Agent" / "Stop All", `Ctrl+K` palette, "2 agents running" pill. This is a strong reference for *information architecture* + *card/status language*. |
| **komputermechanic Hermes "Mission Control"** | http://komputermechanic.com/tutorials/hermes-dashboard | **Glassmorphism** premium look; 5-screen IA (Overview / Agents / Tasks-Kanban / Schedule / Content Library); per-agent activity, sparklines, cron calendar. Screenshots are the taste anchor. |
| **Nous Hermes official dashboard** | https://hermes-agent.nousresearch.com/docs/user-guide/features/web-dashboard | React 19 + Tailwind + shadcn/ui. Panels: Status, Sessions (FTS5 search), Config (schema-generated form), Analytics (cost/token), Logs, Cron, Skills Hub, MCP catalog. Reference for *panel density done tastefully*. |
| **Jan / Cherry Studio** | jan.ai · cherry-ai.com | Debi's baseline "calm chat" taste. Cherry patterns to mine (per `06`): assistants-as-presets, unified capability-tagged provider list, MCP onboarding, KB-per-assistant, multi-model compare. |

**Open design tension to resolve deliberately:** the current Mission Control aesthetic is **dark editorial** (cream/gold on near-black — see `bridge/panel/index.html`). OpenFang is **light/warm**. Debi likes both. Whoever owns design should decide light vs dark (or a toggle — OpenFang ships a sun/moon switch) rather than drift. *Not a decision to make here.*

---

## 2. Steal-list from researched projects

Each entry: **what · why · how it works · where to find the full detail · status vs this project.**

### OpenFang — https://github.com/RightNow-AI/openfang (Rust, ~18k★, Apache/MIT, pre-1.0)
- **"Hands" — packageable scheduled autonomous workflows.** 🟢 NEW
  - *Why:* your plan has manual ⌘K dispatch (M3) and no cron/scheduler at all (see §4). "Hands" is the clean abstraction for "agent that wakes on a schedule and delivers a result" — the "left it running overnight" use-case.
  - *How:* each Hand = a folder with `HAND.toml` (tools, settings, dashboard metrics) + a multi-phase system prompt + a `SKILL.md` domain doc + guardrails/approval gates; lifecycle verbs activate/pause/status; a marketplace ("FangHub"). Look at OpenFang's `agents/<name>/agent.toml` + the `crates/openfang-kernel` scheduler.
  - *Fit:* aligns with your existing SKILL.md convention (M3) and per-component manifest style. A "Hand" ≈ a scheduled Hermes skill with a manifest.
- **Declarative agent TOML with capability allowlists.** 🟡 partially — your component manifests (M1) already do capability/pin declaration; the *per-agent* `[capabilities]` (allowlisted tools/network/memory scopes) + `[[fallback_models]]` is a refinement worth copying if you ever define multiple named agents.
- **Single-binary → `init` → instant local dashboard onboarding.** 🟡 your one-switch provisioning is the equivalent; nothing to add.
- **Note:** OpenFang has **no model downloader** — this is the exact gap Debi hit when he "couldn't download models in OpenFang." Your project *solves* it via Jan + the planned M2 HF browser. Do not treat OpenFang as a runtime to fork; it's an idea mine only.

### Hollow-agentOS — https://github.com/ninjahawk/hollow-agentOS (Python, wiki: ninjahawk.github.io/hollow-wiki)
- **Codebase fact-check verification (→ a "Verified ✓ / Unverified ⚠" badge).** 🟢 NEW
  - *Why:* your `verify` gates prove *component connectivity* only (`02` manifests). There is **no** answer/claim verification. Local models emit confident, well-formatted hallucinations; a fact-check layer is the antidote and a genuine differentiator.
  - *How (Hollow's 5-layer completion gate):* mechanical placeholder/AST checks → semantic accomplishment eval → peer feedback → **codebase fact-check that opens the files an artifact claims to touch and confirms the claim** → promote to ✓ only if it passes. For this harness: when Hermes says "done," have the Bridge read the referenced files / run a linter before the activity feed shows ✓.
  - *Note:* v1's `verify_visual` (screenshot-check a built app) was **deprioritised** in `07` — the fact-check idea is textual/code verification, lighter and different.
- **Mechanical state-gated capabilities + OS-level path validation before shell exec.** 🟢 NEW (the path-guard part)
  - *Why:* your only execution boundary today is "process spawn + HTTP/CLI, no linking" (`02` rule 1). Hermes runs shell with approval, but there's no mechanical path fence.
  - *How:* before any file-write/shell command reaches the OS, validate the path is inside an allowed workspace dir; deny otherwise. Don't trust the model to self-restrain. (Hollow ties tool-locks to a computed risk/"suffering" state — the transferable core is the *mechanical* gate.)
- **`invoke_claude`-style escalation** — 🔴 this is essentially the shelved gearbox (local→stronger-model handoff). Same status: parked until cloud enters.

### Rivet agentos — https://github.com/rivet-dev/agentos (deepwiki.com/rivet-dev/agentos)
- **Durable, replayable transcripts → time-travel / session-graph.** 🟢 NEW
  - *Why:* not in the plan (no session graph, no time-travel — confirmed gap). For a harness whose value is "trust what ran while I slept," being able to scrub/replay/branch an agent run is compelling.
  - *How:* store each conversation as a structured graph (not a flat list) with step snapshots; allow rewind + regenerate-from-here. Rivet backs this with actor durable state; you'd back it with SQLite. **Heavy** — a later luxury, not near-term.
- **In-process WASM sandbox.** 🔴 CONFLICTS. Gemini also flagged this correctly: WASM can't run npm/pip/git/headless-Chromium that real agent tools need. And your no-Docker decision rules out the container alternative. Stick with host subprocess + path-guard (Hollow, above).
- **ACP (Agent Communication Protocol) for federating agent CLIs.** 🟡 your Hermes↔Odysseus seam already picks MCP-vs-ACP as an open question (`02` §13.1); ACP is on your radar.

### AIPass — https://github.com/AIOSAI/AIPass (Python)
- **Trinity tiered memory (hot JSON → auto-spill to ChromaDB).** 🟡/🟢 mixed
  - *Status:* you already **have ChromaDB** (bundled with Odysseus, :8100) and MCP `memory`/`sqlite` servers; a *unified/tiered* memory architecture is only a **shelved sketch** (`07` #7, "workspace as durable layer + nightly distillation"). So the *concept* isn't new, but a concrete **tiered auto-promotion** design is unbuilt. If you ever revive unified memory, AIPass's "no DB until it grows, then transparent promotion to vectors" is the cleanest pattern to copy.
- **File-based agent mailboxes** (every inter-agent message is an inspectable file). 🟢 NEW small idea — trivially debuggable; fits your "legible, file-on-disk" ethos.

### Hermes (Nous) — https://github.com/NousResearch/hermes-agent
- **Cost/token/cache-hit analytics (7/30/90-day).** 🟢 NEW
  - *Why:* not planned (the only cost concept is the shelved gearbox budget). Even fully local, "tokens/sec, tokens today, cache-hit %" is genuinely useful and cheap to add to your metric tiles.
  - *How:* the runner already streams usage; log per-session token counts to SQLite, render in the metrics strip. (Cloud $ only matters if the gearbox ever ships.)
- **Schema-generated config form (150+ typed fields from a schema).** 🟢 NEW small idea — if Mission Control ever grows a settings screen, generate it from a schema instead of hand-building; big maintenance win. (Low priority for a personal tool with few settings.)
- **MCP catalog with pre-enable review + connectivity test.** 🟡 you already have MCP fan-out planned + starter configs (`mcp-*.json`); the "test before enable" UX is a nice refinement.

### agent-os (buildermethods) — https://github.com/buildermethods/agent-os
- **Standards as selectively-injected, context-frugal artifacts** + "shape-spec" planning mode. 🟢 NEW-ish — relevant only to how Hermes skills/standards are written; aligns with your SKILL.md corpus (M3). Low urgency.

---

## 3. Genuine gaps worth considering (all cross-checked as NOT in the plan)

Ranked by value-for-effort for *this* project. None are on a milestone; all are optional.

1. **KV-cache / slot pinning at the runner** 🟢 — *the highest-value technical one.*
   - *Why:* your docs decided context sizing (64K+, RAM governs KV budget, `05` §6) but **not KV-cache pinning**. On local models, prompt *ingestion* is the slow part; a tool-call loop that re-ingests 10k tokens every turn stalls 30–60s. Pinning the system prompt + tool schemas in a persistent llama.cpp slot so only new tokens are ingested is the single biggest local-agent latency win.
   - *How:* llama.cpp `llama-server` supports prompt caching + slot reuse (`--slots`, `cache_prompt`, slot save/restore). Point the runner adapter to keep a stable slot per session.
   - **⚠ Jan-specific caveat (from your `05` §1):** since Jan v0.8.0 llama-server runs in "router mode" and **CLI tuning flags are currently ignored**; per-model settings come from the desktop-generated `router.preset.ini`. So slot control may be limited *through Jan*. Worth a spike: does headless Jan expose/honour slot persistence? If not, this is an argument for the "bare `llama-server` runner" adapter your plan already contemplates as a later option.

2. **Fact-check verification badge** 🟢 — Hollow steal §2. Reads referenced files / runs a linter before the feed shows ✓. Antidote to local-model hallucination; genuine differentiator; moderate effort.

3. **Cost/token/speed analytics tiles** 🟢 — Hermes steal §2. Cheap, useful even fully-local. Fits existing metric strip.

4. **Thought-thread telemetry UX** 🟢 (design input for Fable) — Gemini's best UX idea. Main view shows human-readable states (`🔍 Searching… → 🛠️ Writing src/App.tsx → ✅ Verified`); a collapsible "Inspect" slides out raw JSON tool traces. Nearest planned thing is the M3 activity feed — this would *elevate* it. The failure it prevents: user can't tell "working" from "hung in a loop."

5. **OS-level path-guard before shell/file writes** 🟢 — Hollow steal §2. Mechanical fence, not model trust. Modest effort, real safety.

6. **Cron / scheduler ("Hands")** 🟢 — OpenFang steal §2. Enables unattended overnight runs. Bigger lift; only if the overnight use-case matters to you.

7. **Session-graph / time-travel replay** 🟢 — Rivet steal §2. High value for trust, but heavy (storage + UI). A "someday" luxury.

8. **Tiered memory auto-promotion** 🟢 — AIPass steal §2. Only if the shelved unified-memory sketch (`07` #7) is revived.

---

## 4. Already covered — do NOT re-propose as new

For a fresh chat: these appear in the research as "great ideas" but are **already in this project's plan or decisions.** Restating them wastes effort.

| Idea | Status here | Where |
|---|---|---|
| Hardware-fit / VRAM rating in a model browser | 🟡 PLANNED (M2 flagship) | `04` M2.1, `02` §Mission Control |
| Runner-agnostic model browser + HF discovery | 🟡 PLANNED (M2) | `04` M2.1 |
| Model download by HF repo id | 🟡 DECIDED (Jan `jan serve <repo>`) | `02` §Runner slot |
| Local/cloud routing, escalation, privacy globs, $ budget (gearbox) | 🔴 SHELVED (local-only) | `07` #5, `routing.yaml` |
| Hermes↔Odysseus MCP wiring (adapter) | 🟡 SHELVED→M3 candidate | `07` #6 |
| Blue-green updater + contract tests + rollback | 🟡 PLANNED (M1) | `07` #4, `02` §6.1 |
| MCP host + one server-list fanned out to hosts | 🟡 PLANNED (+ starter configs exist) | `05` §2 |
| Component connectivity `verify` gates | 🟡 DECIDED | `02` manifests |
| Activity feed (Hermes task steps) | 🟡 PLANNED (M3) | `04` M3.1 |
| One-window native shell + webview for Odysseus | 🟡 DECIDED | `02` §Mission Control |
| ⌘K cross-component verbs | 🟡 PLANNED (M2/M3) | `04` M2.3 |
| No Docker; 127.0.0.1-only; plan-and-approve installs | 🔴 LOCKED | `04` Decisions §5, `02` |

---

## 5. From the Gemini analysis — take vs discard

**Take (valuable, and consistent with the plan or a genuine gap):**
- **KV-cache/slot pinning** — see §3.1. The one genuinely important thing Gemini surfaced that the plan lacks. (Gemini didn't know the Jan router-mode caveat — see the ⚠ above.)
- **Thought-thread UX** — see §3.4.
- **Hardware-fit VRAM safety rating** — valid, but **already planned** (M2). Gemini independently confirming its importance is a useful signal.
- **Path-validation before shell** (their "Hollow-style mechanical fail-safes") — see §3.5. The *subprocess* tier of their "tiered sandbox" is the right one.

**Discard (garbage / misaligned — with reasons, so it doesn't get re-suggested):**
- **Docker/Podman container sandbox tier** 🔴 — violates the LOCKED no-Docker decision (`04` §5). Only the host-subprocess + path-guard tier survives.
- **WASM sandbox** 🔴 — can't run npm/pip/git/headless-Chromium that agent tools need (Gemini itself half-admits this). Skip.
- **LanceDB vector DB** 🔴 redundant — Odysseus already bundles **ChromaDB** (:8100). Don't add a second vector store.
- **Electron / Vite+React scaffold, `api.ts`, `ModelContext`/`AgentContext`** 🔴 — wrong stack. This project is **Python Bridge (FastAPI) + native Swift shell + an HTML panel**, not a React SPA. Gemini's file paths/scaffolding don't apply.
- **"Build a new inference engine"** — moot; you compose Jan. (Gemini actually agrees on compose-over-fork.)
- **Gemini's 4-phase roadmap** — ignore; your `04_Roadmap.md` M0–M4 is more specific and grounded in the real codebase.
- **GGUF metadata parsing for prompt templates** — low value here: Jan already handles chat templates via `router.preset.ini`. Only relevant if you add a bare-`llama-server` runner later.
- **Port auto-discovery of Ollama/LM Studio** — largely covered by the dual-mode runner's `auto` health-probe (`02` §Dual-mode).

**What Gemini got right at the high level** (matches Claude's earlier synthesis and your architecture): compose-over-fork; "runtime is a plugin, UI is the product"; two-mode UI (Talk vs Mission Control). None of that is new to you — it *is* your architecture.

---

## 6. Source index (for a fresh chat)

**Research briefs live in Claude Code memory** for the *Base Harness* working dir: `harness-project.md`, `harness-research-sources.md` (at `~/.claude/projects/-Users-debik-Claude-Proj-Rootz-Base-Harness/memory/`). If a new chat runs from a different dir, rely on this doc + the URLs below.

- OpenFang — https://github.com/RightNow-AI/openfang · openfang.sh
- Hollow-agentOS — https://github.com/ninjahawk/hollow-agentOS · ninjahawk.github.io/hollow-wiki
- Rivet agentos — https://github.com/rivet-dev/agentos · deepwiki.com/rivet-dev/agentos
- AIPass — https://github.com/AIOSAI/AIPass
- agent-os (buildermethods) — https://github.com/buildermethods/agent-os
- Hermes (Nous) — https://github.com/NousResearch/hermes-agent · https://hermes-agent.nousresearch.com/docs/user-guide/features/web-dashboard
- komputermechanic Hermes dashboard tutorial — http://komputermechanic.com/tutorials/hermes-dashboard
- Komputer Mechanic YouTube series (agent-OS / mission-control builds): sWB-lvWj3f8, t6W_Zpohb7g, Iup815Xz_ZU, oCj3_YVxDaI, erMROJqU5t4
- llama.cpp server (KV-cache/slots) — https://github.com/ggml-org/llama.cpp/tree/master/tools/server
- Reddit "left agent OS running overnight" (r/ClaudeAI 1t29fq6) — **was unreachable** during research; paste the text if you want it analysed.

*Not verified by running anything: the code read was a review-grade read, not an execution. OpenFang/Hollow metrics are self-reported. Treat perf numbers as unconfirmed.*
