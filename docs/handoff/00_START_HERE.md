# 00 — START HERE: The Harness Project Handoff

## ⟳ STATE UPDATE — 2026-08-07 (supersedes sections below where they conflict)

The primer below has been rewritten in place (staleness in a rehydration primer actively
misleads). Everything else in this file — "Current status", "Immediate next steps", "Open
decisions" — is **2026-07-19/20 history**. Where it disagrees with the living references, they win.

- **Living references, in order:** `CLAUDE.md` (canonical working memory), `docs/HARNESS-INTERNALS.md`
  (code-derived system reference), `docs/USER-GUIDE.md`. Docs 00–10 are planning archaeology.
- **Done since:** M0 (handshake) · M1 (runner slot, one-switch dependency provisioning, fan-out) ·
  M2 (Models pane, HF browse, download manager, aux runner) · M3 (Hermes as a first-class lane).
  Plus: native 3-tab app, four chat lanes, artifacts/canvas, Capabilities panel, path-guard fence,
  fat offline installer + .dmg, vision/images end-to-end, per-message actions.
- **Biggest deltas from the 2026-07 plan:** **Jan is gone** (removed July 2026 — we run our own
  llama.cpp + MLX runner on :6767); the **gearbox / cloud routing is shelved** (local-only);
  Odysseus is MIT and pinned at `25c9e73`; Hermes pinned at `v2026.7.30`.
- **Ship rule:** all code ships via `./scripts/ship.sh` (the fat app serves a provisioned snapshot,
  not the repo — see HARNESS-INTERNALS §3).
- **Next:** voice components as tabs (`docs/handoff/FABLE-VOICE-TABS-SPEC.md` — VoiceStudio +
  Voicebox), a 2nd-Mac .dmg first-run test, then M5 remote access.

---

**Owner:** Debi. **Written:** 2026-07-19. **Purpose:** This document set is a complete, zero-context-loss handoff for your personal local-AI project. Point any fresh chat at this file (or paste the primer below) and the assistant will be fully rehydrated.

---

## The copy-paste context primer

Paste this paragraph verbatim into a new chat to bootstrap an assistant:

> I'm working on **New Harness**, a personal local-first AI workspace on my Mac (Apple Silicon, 64GB RAM). My own code is the **Bridge** (FastAPI on :8700 — component lifecycle, model registry/downloads/switching, the chat lanes, and the panel UI in a dark editorial style: serif headlines, mono small-caps labels, cream-and-gold on near-black) plus a native Swift/WKWebView shell with tabs (Mission Control / Odysseus / Hermes). It composes upstream projects over their APIs and never forks them: **Hermes Agent** (pinned tag `v2026.7.30`, its own dashboard on :9119) as the agent brain, **Odysseus** (pinned commit `25c9e73`, :7860) as the web workspace, **SearXNG** (:8080) as private search, and **our own model runner** on :6767 — llama.cpp (pinned `llama-server`) for GGUF and Apple MLX (mlx-lm / mlx-vlm) for MLX models — plus an optional aux runner on :6768. **Jan AI was removed entirely in July 2026** (LM Studio survives only as a read-only model-import source). No Docker anywhere; everything binds loopback. The living references, in order: **`CLAUDE.md`** (canonical working memory — decisions, dated session log, pending Fable QA), **`docs/HARNESS-INTERNALS.md`** (code-derived system reference: ports, the fat-app snapshot rule, `harness.yaml` keys, the four chat lanes, models/registry, path-guard, endpoint index, ops gotchas), and **`docs/USER-GUIDE.md`**. Docs 00–10 under `docs/handoff/` are historical planning material — accurate as history, superseded wherever they conflict with the two references above. Standing ops rule: **all code ships via `./scripts/ship.sh`**. Fable 5 orchestrates; builders implement decision-free specs and tag judgment calls ⚠️ PENDING FABLE QA.

<details><summary>Original 2026-07-19 primer (historical — Jan-era, superseded)</summary>

> I'm building a personal local-AI harness on my Mac (Apple Silicon, 64GB RAM). The product is my own code: a "Bridge" (local orchestration API — component lifecycle, git pin/rollback of upstream repos, health, config) plus a native Swift "Mission Control" app (dark editorial UI: serif headlines, mono small-caps labels, cream-and-gold on near-black; status cards, metric tiles, activity feed, working ⌘K palette, plan-and-approve install dialogs). It orchestrates third-party components over their APIs, never by forking them: **Jan AI** as the swappable model runner (headless via `jan serve` on :6767 or desktop API on :1337; LM Studio on :1234 as fallback), **Odysseus** (MIT Python workspace with SearXNG-backed DeepResearch, FastAPI on :7860, run as native Python — no Docker) embedded as a webview tab, **Hermes** (NousResearch's MIT async coding-agent daemon, configured via ~/.hermes/config.yaml to point at the runner endpoint), and one shared **SearXNG** instance on :8080 (native from-source install — the whole harness is Docker-free by decision). Locked decisions (2026-07-19): NO Docker anywhere; headless `jan serve --detach` on :6767 is the canonical runner endpoint (desktop Jan :1337 stays a manual convenience); one shared SearXNG serves both Odysseus and MCP search; tool calling is MANDATORY for the primary model (a ~30B tool-capable daily driver at 64K+ context plus a small fast model — non-tool-calling models are disqualified as primary). The decided strategy: unified PRODUCT, composed ARCHITECTURE — do NOT fork Jan (its gaps I cared about — HF browser, MLX, MCP, non-Electron — already exist upstream; and composing over APIs keeps my code independent and the runner swappable; note 2026-07-20: Jan relicensed to Apache-2.0, so the old AGPL-trap argument is retired — merge debt and gaps-closed carry the no-fork decision on their own). This is a PERSONAL tool for now — no shipping pressure, so AGPL imposes zero obligations today; I only keep cheap hygiene (my code in separate repos, arm's-length API boundaries, no AGPL code copied into my repos) so a future ship isn't a rewrite. Roadmap: M0 finish the current Hermes+Odysseus handshake in the harness; M1 define the runner-slot interface in the Bridge and add headless Jan as a managed component; M2 build a native editorial-styled model browser (HF API for discovery, runner CLI/API for downloads) plus the Odysseus webview tab and cross-component ⌘K verbs; M3 deepen Hermes (activity feed, task dispatch, shared SKILL.md skills convention); M4 optional upstream PRs, and revisit forking only if a concrete need is blocked upstream. My #1 CRITICAL requirement (declared 2026-07-20): flipping a component's switch in Mission Control must AUTOMATICALLY install AND connect it — toggle → dependency-ordered provisioning pipeline (one approval dialog covers the whole dependency subtree) → config fan-out → health-verified green card; spec with manifests, state machine (off → planned → installing → configuring → starting → verifying → ON, plus degraded/needs-repair), and verified caveats (Hermes config.yaml written directly, no wizard; Jan needs one scripted desktop-app first-launch to install its CLI) lives in 02_Architecture.md §One-switch provisioning. The full handoff docs (00_START_HERE.md through 06_Landscape_and_PriorArt.md) contain the architecture contract, licensing analysis, roadmap tasks, and reference facts — read them if available.

</details>

---

## Document index

| File | What it contains |
|---|---|
| **00_START_HERE.md** (this file) | Index, context primer, current status, immediate next steps, open decisions. |
| **[01_Vision_and_Decision.md](01_Vision_and_Decision.md)** | Why one tool; why compose instead of fork Jan; the personal-first decision and what it changes; what success looks like. |
| **[02_Architecture.md](02_Architecture.md)** | The composed architecture with ASCII diagram, component responsibilities, the runner-slot interface contract, port map, API boundaries, and fresh research findings (Jan CLI, Odysseus env vars, Hermes config). |
| **[03_Licensing.md](03_Licensing.md)** | Per-component license table, the AGPL reasoning, why personal use = zero obligations today, the cheap hygiene rules that keep future shipping open, and the fork tripwire. |
| **[04_Roadmap.md](04_Roadmap.md)** | M0→M4 with concrete tasks tied to the harness's current mid-M0 state, de-risking prototypes, and the decision list with recommendations. |
| **[05_Reference_and_Learnings.md](05_Reference_and_Learnings.md)** | Tool landscape facts (LM Studio, Jan, Hermes, Odysseus), MCP config learnings, skills/SKILL.md landscape, SearXNG options, model/hardware notes, existing config-file inventory, consolidated sources. |
| **[06_Landscape_and_PriorArt.md](06_Landscape_and_PriorArt.md)** | Fresh 2026 research: Odysseus alternatives (verdict: keep), Hermes alternatives (verdict: keep), prior-art "does-everything" desktop apps table, a deep Cherry Studio subsection (what to learn), and the build-vs-adopt verdict (keep building the hybrid). Also carries the Odysseus-is-MIT correction and the dual-mode runner cross-link. |

---

## Current status (as of 2026-07-20, FOURTH pass — the one-switch requirement)

- **Correction (2026-07-20, verified against root LICENSE + README in a fresh clone): Jan is Apache-2.0, not AGPLv3.** The earlier "AGPL app / MIT SDK" split is retired. Consequence: the "license trap" argument against forking Jan (01 §Why NOT fork, 03 §core reasoning) no longer applies — the no-fork decision stands unchanged on its two other legs (gaps closed upstream; merge debt forever). The only AGPL component left in the harness is SearXNG. Fixed across 01/02/03/05/06.
- **Correction (2026-07-20): the primer above previously still called Odysseus AGPL** despite the third-pass MIT correction — the paste-verbatim primer was propagating the stale fact. Fixed. Lesson: when a fact is corrected, grep the whole doc set (especially the primer) for the old value.

- **Debi declared his #1 CRITICAL requirement:** flipping a component's switch in Mission Control must AUTOMATICALLY install it AND connect it — no terminal, no wizard, no hand-edited config. **Verdict: achievable for all five managed pieces** (Jan runner, Odysseus, Hermes, SearXNG, models), as: toggle → dependency-ordered provisioning pipeline → config fan-out → health-verified green card. Full spec now in [02_Architecture.md](02_Architecture.md) §"One-switch provisioning — the paramount requirement": component manifests (with real YAML for all five), dependency graph + closure resolution (one flip provisions its whole subtree behind ONE approval dialog), the state machine (`off → planned → installing → configuring → starting → verifying → ON`, plus `degraded`/`needs-repair` + Repair verb), per-component connect steps and verify probes, idempotency rules.
- **Two risky assumptions verified 2026-07-20:** (a) Hermes IS fully configurable by writing `~/.hermes/config.yaml` directly (`provider: custom` + `base_url`; validate with `hermes config check`) — the interactive wizard is never needed and is now banned from the pipeline. (b) Jan can NOT be installed purely via CLI — the `jan` CLI is installed by the desktop app's first launch; scriptable workaround: brew cask → `open -a Jan` → wait for the binary → quit (one window flashes once, labeled in the plan dialog).
- **Honest caveats accepted into the design:** the switch is a pipeline with live progress, not instant (model weights are GBs); models must exist before agents go green (a node in the dependency graph); Gatekeeper handled via `--no-quarantine`; upstream drift handled by pins; no API keys needed anywhere today.
- **Roadmap updated:** M0 task 2 now writes Hermes config directly (no wizard); M1 gains the manifests + pipeline work and a second exit criterion — *"from a clean slate, flip Odysseus ON → everything installs, connects, goes green without touching a terminal."*
- **Debi decided (2026-07-20): the primary-model download rides INSIDE the runner's switch** — fully automatic, size shown in the approval dialog ("~XX GB"), live progress on the card. Not a separate action.

## Current status (as of 2026-07-19, THIRD pass — landscape researched, dual-mode runner designed, build-vs-adopt reaffirmed; **Debi accepted all third-pass recommendations** — see "Accepted 2026-07-19" below)

- **New this pass ([06_Landscape_and_PriorArt.md](06_Landscape_and_PriorArt.md)):** Researched the field. **Keep Odysseus** (nothing beats it for the research slot; it's also now MIT and at 77k+ stars). **Keep Hermes** (only true async SKILL.md daemon; 214k stars, relentless releases). Investigated **Cherry Studio** (the "CherryIN" Debi saw — 46.9k★ Electron all-in-one, AGPL-3.0 + paid commercial exemption): it's ~80% of the *chat-surface layer only*, the layer we deliberately deferred, and it orchestrates nothing. **Build-vs-adopt verdict: keep building the hybrid** — no surveyed app supervises a runner + Odysseus + Hermes + SearXNG; that Bridge role plus the native editorial shell is the whole product. Mine Cherry Studio for 5 UX patterns (assistants-as-presets, provider abstraction, MCP onboarding, KB-per-assistant, multi-model compare).
- **Dual-mode runner DESIGNED (Task 1, now in [02_Architecture.md](02_Architecture.md) §Runner slot):** the Jan adapter can point at headless (:6767, primary) OR desktop (:1337) via `runner.mode = headless | desktop | auto`; `auto` prefers headless, borrows the desktop app if it's already open (no double model-load), health-fallback between them. Anonymous-above-the-adapter rule preserved.
- **Correction:** Odysseus is **MIT, not AGPL** (verified LICENSE). Noted in [03_Licensing.md](03_Licensing.md) and [06](06_Landscape_and_PriorArt.md).

## Current status (as of 2026-07-19, second pass — basics clarified, four decisions locked)

- **Strategy: DECIDED.** Personal tool first; possibly ship later but not today. No Jan fork — you agreed after seeing the research. Unified product, composed architecture: your Harness (Bridge + Swift Mission Control) is the product; Jan is a swappable runner; Odysseus and Hermes are managed components surfaced through your shell.
- **New this pass:** a plain-language "How the pieces fit" section now opens [01_Vision_and_Decision.md](01_Vision_and_Decision.md) — read it first if the architecture ever feels abstract. Four previously-open decisions are now LOCKED (see below): no Docker anywhere, headless Jan :6767 as canonical runner, one shared native SearXNG on :8080, tool-calling mandatory for the primary model.
- **Build state: mid-M0.** The Bridge and Mission Control exist and work (status cards, ⌘K palette, install dialogs, git pin/rollback). Remaining M0 work: fix Hermes start-error reporting; run the Hermes setup wizard pointed at a model endpoint; install Odysseus from the panel; wire the two together for a first handshake.
- **Research state: complete for planning purposes.** Everything needed to execute M0–M2 is verified and written down in these docs, including the newest findings: Jan's headless CLI (`jan serve`, port 6767, auto-downloads HF repo IDs), Jan's lack of an HTTP download endpoint (drive downloads via CLI instead), Odysseus's `SEARXNG_INSTANCE` env var (external SearXNG supported), and Hermes's `~/.hermes/config.yaml` custom-endpoint support with tool-calling requirements.

## Immediate next steps (do these, in order)

1. **Finish M0** — get the first Hermes ↔ Odysseus ↔ model-endpoint handshake running through the existing harness. Don't pivot to M1 before this runs. Details in [04_Roadmap.md](04_Roadmap.md) §M0.
2. **Point Hermes at a real endpoint by writing `~/.hermes/config.yaml` directly** (`model: { provider: custom, base_url: http://localhost:1337/v1 }` for Jan or `:1234/v1` for LM Studio; validate with `hermes config check`). Do NOT run the setup wizard — verified unnecessary, and it can't skip its Nous Portal step. Use a tool-calling-capable model. Details in [02_Architecture.md](02_Architecture.md) §Hermes and §One-switch provisioning.
3. **Pick the two default models** (the only decision still gating anything) — policy is locked (tool-calling ~30B + small fast model); benchmark and name the exact IDs. See [04_Roadmap.md](04_Roadmap.md) §Decisions.
4. **Start M1** — write the runner-slot interface in the Bridge and register headless Jan (`jan serve --detach`) as a managed component with a status card.

## Decisions — LOCKED 2026-07-19 (details in 04_Roadmap.md §Decisions)

1. **No Docker, anywhere.** Debi doesn't want Docker. Odysseus runs as native Python (venv, uvicorn); SearXNG runs native from source (recipe in [02_Architecture.md](02_Architecture.md) §SearXNG). The old "container acceptable for SearXNG" fallback is withdrawn.
2. **Canonical runner endpoint: headless Jan on :6767** (`jan serve --detach`, Bridge-managed, invisible). Desktop Jan (:1337) stays installed as a manual convenience for model settings and occasional chat — it is NOT the harness's endpoint.
3. **Shared SearXNG: yes.** One Bridge-managed native instance on :8080; both Odysseus (`SEARXNG_INSTANCE`) and any MCP web-search server point at it.
4. **Tool calling is MANDATORY for the primary model.** Hermes and MCP tools break without it. Default pair: a ~30B-class tool-calling daily driver at 64K+ context + a small fast model for light/background tasks. Non-tool-calling models are disqualified as primary, no matter how good their prose.

## Accepted 2026-07-19 (Debi agreed with Fable's third-pass recommendations)

These move from "recommended" to **decided**; escape hatches retained where noted.

1. **Dual-mode runner — accepted.** Jan adapter supports `runner.mode = headless | desktop | auto`; headless :6767 primary, desktop :1337 tappable, `auto` prefers headless and borrows the desktop app if already open. Details in [02_Architecture.md](02_Architecture.md) §Runner slot.
2. **Keep Odysseus** as the research workspace (MIT; native Python). Hold MIT `local-deep-research` in reserve as an *augment* only — never a replacement. [06](06_Landscape_and_PriorArt.md) §1.
3. **Keep Hermes** as the async coding daemon (MIT). **OpenCode** (MIT, client/server) is the logged escape hatch if Nous turns hostile; Goose second. IDE-bound agents excluded. [06](06_Landscape_and_PriorArt.md) §2.
4. **Keep building the composed hybrid** — do NOT adopt Cherry Studio / Jan / AnythingLLM as the shell. The Bridge's orchestration + the native editorial shell is the product. [06](06_Landscape_and_PriorArt.md) §4.
5. **Mine Cherry Studio for patterns (ideas only — AGPL) at M2:** assistants-as-presets, unified capability-tagged provider list, MCP onboarding (pre-wired defaults + `npx`/`uv` checks), KB-per-assistant, multi-model compare. Also install it *as a user* for UX reference. [06](06_Landscape_and_PriorArt.md) §3.
6. **Adopt the build-vs-adopt tripwire.** If a Mission Control feature is really "rebuild a commodity chat-client feature" (threads, message editing, KB ingestion, prompt library), stop and check whether an existing client on the endpoint covers it. Guard the identity = supervision + orchestration + editorial shell.
7. **Skills convention — accepted:** one canonical SKILL.md corpus (e.g. `~/harness/skills`) shared across LM Studio (`~/.lmstudio/skills`) and Hermes; borrow structure from Goose's Apache-2.0 **recipes**.
8. **Daily-chat principle — accepted:** never build a chat client from scratch; point an *existing* one (Jan, or Cherry Studio as a manual convenience) at the endpoint. A native Mission Control pane is a luxury only if it earns its keep against ⌘K.

## Still genuinely open (need a real-world step; fine to defer)

1. **Exact model IDs** for the `primary` and `fast` roles — *policy* is locked (tool-calling ~30B @64K+ ctx + small fast model); the specific picks (e.g., Qwen3-32B vs. a Qwen3.5/3.6 MoE) await a quick benchmark on your machine.
2. **Which existing client is the daily-chat home** (Jan vs. Cherry Studio as convenience) — the *principle* is decided (#8 above); the specific pick can wait until after M1.
3. **Native SearXNG proving run** on macOS/arm64 (~1 hr spike) — confirm the no-Docker from-source path works on your machine before the Bridge wires it in. See [04_Roadmap.md](04_Roadmap.md).

---

*Everything below the fold of this project lives in the five sibling documents. If you're an assistant reading this: read 01 and 02 next; 03–05 as needed.*
