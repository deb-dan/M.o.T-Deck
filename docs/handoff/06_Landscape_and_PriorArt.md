# 06 — Landscape & Prior Art (research pass, 2026-07-19)

## ⟳ STATE UPDATE — 2026-08-07 (supersedes sections below where they conflict)

The build-vs-adopt verdict below ("keep building the hybrid") was correct and is now settled by
evidence — MOT Deck does things no surveyed app does. Living references: `CLAUDE.md`,
`docs/MOT-DECK-INTERNALS.md`.

- **Keep Odysseus / keep Hermes** both held. Both have since been pin-bumped in place under
  contract tests (Odysseus `25c9e73`, Hermes `v2026.7.30`) with no fork and no vendor edit.
- **Jan is no longer in the comparison** — it was removed from MOT Deck in July 2026 and
  replaced by our own llama.cpp + MLX runner. Any "Jan as runner" reasoning below is historical.
- **Cherry Studio / LM-Studio-style chat surface:** the deferred layer got built ourselves — the
  panel now has a four-lane chat, a model-picker popover, artifacts + editable canvas, per-message
  actions, and image attachments. The reference apps remain taste input only.
- Prior-art scanning is **paused** — the project is past the survey phase and into maintenance +
  new modalities (voice next). Revisit only if a concrete capability is blocked.
---


*Part of the MOT Deck handoff set. Index: [00_START_HERE.md](00_START_HERE.md). Architecture: [02_Architecture.md](02_Architecture.md). Licensing: [03_Licensing.md](03_Licensing.md). Roadmap: [04_Roadmap.md](04_Roadmap.md).*

This pass answers four questions you asked: (1) can the runner tap desktop Jan as well as headless Jan (answered in [02_Architecture.md](02_Architecture.md) §Dual-mode runner — designed and written in); (2) is anything better than Odysseus; (3) is anything better than Hermes; (4) what is "CherryIN"/Cherry Studio, what does the prior-art field look like, and does it change the build-vs-adopt decision. Everything below was researched fresh in July 2026, with sources inline.

---

## ⚠️ Correction to the earlier docs: Odysseus is MIT, not AGPL

The 03/05 docs recorded Odysseus as AGPL-3.0. **Verified today against the LICENSE file on `main`: Odysseus is MIT** ("Copyright (c) 2025 Odysseus Contributors") — [raw LICENSE](https://raw.githubusercontent.com/pewdiepie-archdaemon/odysseus/main/LICENSE). The repo also appears renamed to `odysseus-dev/odysseus` (old URL redirects).

Practical consequences, all in your favor:
- You may now **lift Odysseus patterns AND code** (with attribution), same as Hermes. The "ideas not code" restriction is lifted.
- The AGPL components in MOT Deck shrink to **SearXNG alone** (further correction 2026-07-20: Jan is Apache-2.0 too, verified root LICENSE + README — this line originally also listed Jan's app). You only ever talk to it over APIs anyway, so nothing about the architecture changes; the hygiene rules just got cheaper again.
- A dated correction note has been added to [03_Licensing.md](03_Licensing.md); the boundary rules stay as-is (they're good engineering regardless of license).

Also worth knowing: Odysseus turned out to be a phenomenon. It launched publicly May 31, 2026 (yes, it's PewDiePie's project) and passed **77,000 GitHub stars and 10,000 forks within about three weeks** ([XDA review](https://www.xda-developers.com/tried-pewdiepie-open-source-ai-workspace-odysseus-weirdly-great/), [Medium coverage](https://medium.com/@creativeaininja/pewdiepies-odysseus-blew-past-50-000-github-stars-in-days-a53bedb8285e)). Upstream scope is broader than our docs described: chat, autonomous agents, DeepResearch, email/calendar/notes, image generation, and a "Cookbook" recommending models for your hardware from 270+ options ([launch coverage](https://letsdatascience.com/news/pewdiepie-releases-open-source-odysseus-ai-workspace-ccad3aef)). Maintenance risk has inverted: three months ago the question was "will this niche repo survive"; now it's one of the most-watched local-AI projects alive.

---

## 1. Is there something better than Odysseus? (research workspace / DeepResearch slot)

What Odysseus is in MOT Deck: a **synchronous, user-driven research workspace** — chat + DeepResearch over your shared SearXNG, native Python, FastAPI on :7860, embedded as a webview tab. The candidates below were checked for: local-model support, SearXNG support, license, Docker posture, maintenance health, and fit for that exact slot.

| Project | License | Local LLM | SearXNG | No-Docker viable | Health (2026-07) | Fit for the slot |
|---|---|---|---|---|---|---|
| **Odysseus** (incumbent) | **MIT** (verified) | Yes — `LLM_HOST`, any OpenAI endpoint | **Native** (`SEARXNG_INSTANCE`) | Yes — plain Python/uvicorn | 77k+ stars, explosive activity | **The slot was designed around it** |
| **Perplexica** (rebranded **Vane**, 3/2026) | MIT | Yes (Ollama etc.) | **Built around it** | Awkward — Node/Next.js, Docker-first packaging | ~33k stars, active, v1.12.x | Answer engine, not a workspace |
| **local-deep-research** (LearningCircuit) | MIT | Yes — llama.cpp/Ollama/any endpoint | Yes (instance URL) | **Yes — on PyPI**, plain pip install | ~7.2k stars, fast-growing | Research *engine* with utilitarian UI; strongest **augment** |
| **GPT Researcher** | Apache-2.0 (LICENSE; pyproject inconsistently says MIT; bundles AGPL PyMuPDF — [issue #1063](https://github.com/assafelovic/gpt-researcher/issues/1063)) | Yes (documented Ollama path) | Yes (`RETRIEVER=searx`) | Yes — Python lib | Mature, steady | Report-generator library, no workspace UI |
| **SurfSense** | Open source (repo: MODSetter/SurfSense) | Yes (Ollama, 150+ models) | Partial (Tavily/Linkup-first; connectors are the moat) | No — Docker-compose-shaped, Postgres etc. | Popular, team-oriented | NotebookLM-for-teams, wrong shape |
| **Khoj** | AGPL-3.0 | Yes | No (own search) | Middling | Established | Personal second-brain, not DeepResearch |
| **Morphic** | Apache-2.0 | Yes | Yes | Node/Next.js | Active | Answer engine, same caveat as Perplexica |
| **Onyx (ex-Danswer)** | MIT core + enterprise dirs | Yes | No | No — heavy compose stack | Enterprise-focused | Team RAG platform, wrong shape entirely |

Sources: [Perplexica/Vane guide (2026)](https://joshuaopolko.com/perplexica-self-hosted-guide/), [OSSAlt Perplexica self-host guide](https://ossalt.com/guides/how-to-self-host-perplexica-open-source-perplexity-2026), [local-deep-research repo](https://github.com/LearningCircuit/local-deep-research) and [SearXNG setup doc](https://github.com/LearningCircuit/local-deep-research/blob/main/docs/SearXNG-Setup.md), [GPT Researcher Ollama docs](https://docs.gptr.dev/docs/gpt-researcher/llms/running-with-ollama), [SurfSense repo](https://github.com/MODSetter/SurfSense), [2026 NotebookLM-alternative comparison](https://rohitraj.tech/hi/notes/open-notebook-vs-khoj-vs-surfsense-notebooklm-2026).

**Verdict: keep Odysseus. Nothing beats it *for this slot*, and the case got stronger since the last pass.**
- It is the only candidate that is simultaneously: a full workspace UI (not just an answer box), SearXNG-native, plain-Python no-Docker, MIT, and already wired into your Bridge plan.
- Its momentum problem solved itself — 77k stars and a flood of contributors means bugs you'd have had to patch will likely get fixed upstream.
- **Augment option (logged as an open question, not a task):** `local-deep-research` is the one genuinely interesting complement — MIT, pip-installable (fits the Bridge's venv machinery perfectly), points at any OpenAI endpoint + your SearXNG, and benchmarks its pipeline seriously (~95% SimpleQA claims with mid-size local models). If Odysseus's DeepResearch ever disappoints on rigor, bolt LDR in as a second engine — e.g., exposed as an MCP tool or a Hermes skill — rather than replacing the workspace. Zero urgency today.
- Perplexica/Vane is excellent but answers questions; it doesn't hold a research *session*. If you ever want a lightweight "Perplexity box" in Mission Control, it's the obvious pick — but it duplicates what Odysseus DeepResearch + SearXNG already give you, in a Node/Docker-flavored package you'd resent supervising.

## 2. Is there something better than Hermes? (async coding-agent slot)

What Hermes is in MOT Deck: an **async, autonomous, headless-daemon coding agent** — MIT, points at any OpenAI-compatible endpoint via `~/.hermes/config.yaml`, edits files, runs commands, writes SKILL.md skills. Candidates checked for: daemon-vs-IDE shape, local-endpoint support, tool-calling requirements, skills/memory, license, health.

| Project | License | Shape | Local endpoint | Skills/memory | Health (2026-07) | Fit |
|---|---|---|---|---|---|---|
| **Hermes** (incumbent) | MIT | **Async daemon** (+ new Hermes Desktop front-end) | Yes — any OpenAI endpoint; Jan/LM Studio in compat table | **SKILL.md native** | **~214k stars, ~40k forks**, near-weekly releases, v0.18.0 July 1 | **The slot was designed around it** |
| **OpenCode** (sst/Anomaly) | MIT | **Client/server**: TUI is a client to a local agent server | Yes — any OpenAI-compatible endpoint via `opencode.jsonc`; 75+ providers | Agents/commands config; no SKILL.md-style self-written skills | ~160k stars, most-starred OSS coding agent | **Strongest structural alternative** — server mode could be Bridge-driven |
| **Goose** (Block → Agentic AI Foundation / Linux Foundation) | Apache-2.0 | CLI + desktop; headless/scriptable; MCP-native | Yes — Ollama/Ramalama/etc. | **Recipes** (reusable YAML workflows) + scheduler | ~50k stars, v1.38, foundation-governed | Best *automation* agent; less "async coder" |
| **OpenHands** (ex-OpenDevin) | MIT (core) | Headless CLI (`--headless`, always-approve) + SDK; Docker default but **LocalRuntime runs on host** | Yes — recommends Qwen3.6-35B-A3B locally via LM Studio/Ollama | Microagents/repo memory | Very active; strong SDK paper | Capable but heavy; Docker-culture even if avoidable |
| **Aider** | Apache-2.0 | Sync CLI pair-programmer, no daemon | Yes | Conventions files, no skills | **Maintenance mode** — v0.86.2 (Feb 2026) after long gap; slowdown acknowledged in [issue #4751](https://github.com/Aider-AI/aider/issues/4751) | Great tool, wrong shape, fading |
| **Cline / Roo Code / Kilo Code / Continue** | Apache-2.0 (all) | **IDE-bound** (VS Code extensions; Continue has a young CLI) | Yes | Rules files | All active | **Don't fit a headless daemon model** — excluded |
| **SWE-agent / mini-swe-agent** | MIT | Batch research motdeck | Yes | No | Academic cadence | Benchmark motdeck, not a coworker |
| **Tabby** | Apache-2.0 | Completion/chat server | Is one | No | Active | Not an agent at all |

Sources: [Hermes ecosystem report (214k stars, release cadence)](https://the-agent-report.com/2026/06/hermes-agent-ecosystem-2026-pillar/), [Hermes Desktop launch](https://www.marktechpost.com/2026/06/03/nous-research-releases-hermes-desktop-a-native-cross-platform-front-end-for-hermes-agent-v0-15-2-with-streaming-tool-output/), [Nous $1.5B funding talks (TechCrunch, 2026-07-13)](https://techcrunch.com/2026/07/13/hermes-agent-maker-nous-research-in-talks-for-new-funding-at-1-5b-valuation/), [OpenCode developer guide](https://www.developersdigest.tech/blog/opencode-developer-guide-2026), [opencode env.dev profile](https://env.dev/ai/opencode), [Goose docs](https://block-goose.mintlify.app/), [Goose post-Linux-Foundation review](https://pickuma.com/for-dev/goose-cli-review-block-open-source-agent/), [OpenHands local-LLM docs](https://docs.openhands.dev/openhands/usage/llms/local-llms), [OpenHands CLI repo](https://github.com/OpenHands/OpenHands-CLI), [Aider releases](https://github.com/Aider-AI/aider/releases).

**Verdict: keep Hermes, without hesitation.**
- It is the *only* candidate purpose-built as an async self-directed daemon with SKILL.md skills — which is exactly the M3 plan — and it's MIT, so it remains your pattern-and-code donor.
- Its trajectory removes the risk argument: 214k stars, brutal release cadence, a desktop front-end, and a company raising at $1.5B behind it. (Watch item: monetization pressure at Nous could eventually tier features — the MIT license on what's shipped protects you.)
- **Fallback/augment, logged as an open question:** OpenCode's client/server split is architecturally the best match to your Bridge (a supervised local server the Swift app could even talk to directly), and it's MIT. If Hermes ever turns hostile to the daemon use-case, OpenCode is the swap. Goose is the second-best swap and its Apache-2.0 **recipes** format is worth reading when you design your skills convention — a recipe (goal + required extensions + structured inputs + sub-recipes) is a more formal cousin of SKILL.md.
- The IDE-bound family (Cline/Roo/Kilo/Continue) is confirmed out of scope for this slot: they assume an open editor and a human in the loop. Note that tool-calling remains mandatory across every serious candidate — your locked model policy holds for all of them.

## 3. Prior-art "does-everything" motdeck apps — and Cherry Studio

### The field at a glance

The question behind this table: **who already combines multi-provider + local models + MCP + agents + knowledge, on a desktop?**

| App | License | Local models | MCP | Agents | Knowledge/RAG | Platform | Notes |
|---|---|---|---|---|---|---|---|
| **Cherry Studio** | **AGPL-3.0** (community) + paid commercial exemption; earlier user-segmented regime — see deep dive | Via Ollama/LM Studio (doesn't run models itself) | **Yes**, incl. pre-wired servers | Assistants (300+ presets) + newer "autonomous agents"; **Deep Research still on roadmap** | **Yes** — built-in KB (PDF/DOCX/URL/sitemap) | Win/Mac/Linux, **Electron** | 46.9k★. The closest single-app cousin of your vision's *surface* |
| **Jan** | Apache-2.0 (corrected 2026-07-20) | **Runs them** (llama.cpp/MLX) | Yes (v0.7.3+) | Assistants-lite | No real KB | Tauri/Rust desktop | Your runner. Also a decent chat surface |
| **Open WebUI** | Custom "Open WebUI License" (BSD-3 until v0.6.5; branding-protection clause since 4/2025 — [license doc](https://docs.openwebui.com/license/), [HN discussion](https://news.ycombinator.com/item?id=43901575)) | Yes (Ollama-native) | Yes (via pipes/tools) | Tools/functions | Yes | **Web server**, not desktop | Huge but license-controversial and server-shaped |
| **AnythingLLM** | MIT | Yes (desktop bundles a runner; or Ollama/LM Studio) | **Yes** ([docs](https://docs.anythingllm.com/mcp-compatibility/overview)) | No-code Agent Builder | **Yes** — workspaces-as-RAG | Desktop (no Docker needed) + server | ~54k★. The most complete *open* all-in-one desktop |
| **LibreChat** | MIT | Endpoint-level | **Yes** (early, deep) | Agents + code interpreter | Yes | **Web server** | Multi-user oriented |
| **Msty** | Proprietary (free tier) | Yes (bundles Ollama) | Partial | No | Yes (Knowledge Stacks) | Desktop | Closed; polished |
| **Witsy** | Open source ([Kochava-Studios/witsy](https://github.com/Kochava-Studios/witsy)) | Yes | **Yes — "universal MCP client"** | Light | Light | Desktop | Small but MCP-forward |
| **Chatbox** | Open core (verify current terms) | Yes (BYOK + local) | Yes (Agent Mode) | Agent mode | KB integration | Desktop + mobile + web | Consumer-leaning |
| **LobeChat** | Custom/verify (moved off plain permissive) | Yes | Yes | Assistants market | Yes | Web + desktop wrapper | Cloud-first gravity |
| **BoltAI / Enconvo** | Proprietary, paid | Yes (endpoints) | Partial/plugins | Light | Light | macOS native | Closest to your *aesthetic native macOS* lane, closed |
| **Odysseus** | MIT | Via endpoints | (n/a — own tools) | **Yes** | Notes/own stack | Self-hosted web | Already yours |
| **Your MOT Deck** | Yours | **Manages the runner itself** | Planned via fan-out | Hermes + Odysseus | Odysseus + future KB | **Native Swift** | The only one that *supervises other programs* |

(Comparison sources beyond those linked: [ClickHouse survey of MCP-capable chat UIs](https://clickhouse.com/blog/llm-chat-mcp-support), [AnythingLLM vs Open WebUI vs LibreChat 2026](https://runaihome.com/blog/anythingllm-vs-open-webui-vs-librechat-2026/), [Mac local-AI platform comparison](https://modelpiper.com/blog/local-ai-platforms-compared-mac).)

Direct answers to your two sub-questions:
- **Open-source ones that "do everything" and run local:** Cherry Studio (AGPL) and AnythingLLM (MIT) are the real ones on desktop; Open WebUI and LibreChat do it as web servers. None of them manage a *headless runner's lifecycle*, install/supervise sibling apps, or do anything like git pin/rollback — they are all *consumers* of endpoints, not orchestrators of components.
- **Closed-source ones that do everything and allow local:** LM Studio (runner+chat+MCP), Msty, BoltAI, Enconvo. Same limitation, plus you can't learn from their code.

### Cherry Studio, deep dive

**What it is.** "CherryIN" is not a separate product — it's Cherry Studio's built-in commercial API gateway. **Cherry Studio** ([CherryHQ/cherry-studio](https://github.com/CherryHQ/cherry-studio), 46.9k★/4.5k forks) is an Electron desktop client for Windows/Mac/Linux: multi-provider chat (300+ models, 50+ providers), 300+ assistant presets + custom assistants, multi-model *simultaneous* conversations, a local knowledge base (PDF/DOCX/PPTX/XLSX/URL/sitemap sources with configurable embedders), MCP server support with pre-wired servers, mini-programs, translation, drawing panel, WebDAV backup ([README](https://github.com/CherryHQ/cherry-studio/blob/main/README.md), [docs](https://docs.cherryai.com.cn/docs/en-us)). Local models are supported **via Ollama and LM Studio** — it never runs a model itself. **CherryIN** launched with v1.6.4 as their aggregated cloud-model storefront (Claude/GPT/Gemini/etc. at discounted rates) — i.e., their monetization is *cloud* access, which tells you where the product's gravity points ([CherryIN docs](https://docs.cherryai.com.cn/docs/en-us/pre-basic/providers/cherryin-1), [launch coverage](https://www.aibase.com/news/www.aibase.com/news/21883)).

**The license situation, verified.** The LICENSE file on `main` today is **plain, unmodified AGPL-3.0** ([raw LICENSE](https://raw.githubusercontent.com/CherryHQ/cherry-studio/main/LICENSE)), and the README states: Community Edition governed by standard AGPL-3.0; **commercial use permitted subject to AGPL compliance**; a paid commercial license granting exemption from AGPL is available (bd@cherry-ai.com). The "notable license situation" you half-remembered is real but historical: Cherry Studio previously used a **user-segmented dual license** — AGPL-3.0 only for individuals and orgs of ≤10 people, mandatory commercial license above that — and their docs site still describes that regime ([license FAQ](https://docs.cherry-ai.com/contact-us/questions/cherrystudio-xu-ke-xie-yi)). For you personally it's moot either way (personal use, no distribution → zero obligations, same posture as Jan). For *pattern-lifting* it matters: **AGPL means ideas only, never code** — same rule you already apply to Jan.

**What to learn / incorporate (ideas, not code):**
1. **Assistants-as-presets.** Their single best idea: an "assistant" is a cheap bundle of system prompt + model choice + params + enabled tools/KB, switchable per-chat, with a large browsable library. This costs almost nothing to implement above your runner endpoint and maps perfectly onto ⌘K ("new chat as *researcher*…"). If Mission Control ever grows a chat pane, this is its data model. It's also the right shape for your Bridge config: named roles (`primary`, `fast`) generalize naturally to named *assistants*.
2. **Provider abstraction with capability tags.** Their model registry treats every provider uniformly and tags models by capability (vision/tools/embedding). Your runner-slot contract is the same instinct applied one level deeper — but their UX (one unified searchable model list regardless of origin) is exactly what your M2 native model browser should feel like.
3. **MCP handling UX.** Ship a curated starter set of MCP servers pre-wired, check for `npx`/`uv` at add-time, per-assistant tool enablement, and a marketplace on the roadmap. Your Bridge's planned "one MCP list fanned out to all hosts" is stronger architecture; steal their *onboarding* (pre-wired defaults + dependency checks in the install dialog).
4. **Knowledge base attached to assistants.** KB-per-assistant with a configurable embedding model is a clean pattern. Don't build this now — Odysseus covers research memory — but if you ever add a motdeck KB, copy this shape rather than a global monolithic index.
5. **Multi-model simultaneous chat** (one prompt fanned to N models side-by-side) is a genuinely useful evaluation tool and trivial to build against `/v1/models` + parallel requests — a candidate ⌘K verb ("compare models…") for M2/M3.
6. **A warning, not a lesson:** Cherry Studio is what happens when a chat client absorbs features for three years — 40+ sidebar surfaces, Electron heft, cloud-gateway monetization. Your one-window, few-verbs editorial discipline is the *opposite* bet. Keep it.

## 4. Build vs. adopt — the honest reassessment

The discovery question: Cherry Studio (or Jan, or AnythingLLM) is "~80% of the vision" — so should you still build?

**No, it isn't 80%. It's ~80% of one layer — the chat surface — which is the layer you explicitly deferred.** Line up your vision against the field:

| Vision element | Cherry Studio | AnythingLLM | Jan | Your MOT Deck |
|---|---|---|---|---|
| Multi-provider chat + assistants | ✅ best-in-class | ✅ | ✅ | deferred on purpose |
| Knowledge base | ✅ | ✅ | ❌ | via Odysseus |
| MCP host | ✅ | ✅ | ✅ | fan-out planned |
| **Runs the model engine itself** | ❌ | partial | ✅ | via runner slot |
| **Installs/supervises sibling components** (runner, Odysseus, Hermes, SearXNG) | ❌ | ❌ | ❌ | ✅ the Bridge |
| **Async coding agent as managed daemon** | ❌ | ❌ | ❌ | ✅ Hermes |
| **DeepResearch over your own SearXNG** | roadmap | ❌ | ❌ | ✅ Odysseus |
| Git pin/rollback of upstreams, config fan-out, health | ❌ | ❌ | ❌ | ✅ built |
| Native Swift, one window, your aesthetic | ❌ Electron | ❌ Electron | Tauri | ✅ |

**Verdict: (c), the hybrid — which is what you're already building.** Keep the composed MOT Deck: the Bridge is not duplicated by *anything* in this survey — every app in the table is an endpoint **consumer**; your product is the endpoint **orchestrator** plus the shell you love. Adopting Cherry Studio as the shell would mean: Electron (you chose Jan partly for *not* being Electron), AGPL (your shell code would live inside an AGPL app — the exact trap the compose decision avoids), zero component supervision (you'd still need the Bridge, now without a home), and abandoning the part of the project you've said brings you joy. That trade loses on your three stated values — one tool, personal-first, compose-not-fork — simultaneously.

What the discovery *should* change:
1. **Kill any ambition to hand-build the commodity layer.** Chat panes, KB ingestion, assistant libraries are commoditized — three open-source teams ship them full-time. Your "where does daily chat live" open decision gets a sharper answer: **an existing client pointed at your endpoint, never a from-scratch build.** Jan's UI already fills this; Cherry Studio is worth installing *as a user* the way desktop Jan is — a manual convenience client aimed at `:6767` (or :1337), zero Bridge involvement, adopted or deleted freely.
2. **Mine Cherry Studio for the five patterns above** when you reach M2 (model browser, ⌘K verbs) and any future chat pane.
3. **Add a cheap tripwire, mirroring the Jan fork tripwire:** if you ever find yourself speccing a Mission Control feature that is really "rebuild a chat client feature" (threads, message editing, KB ingestion, prompt library), stop and check whether pointing an existing client at the endpoint covers it. The MOT Deck's identity is supervision + orchestration + the editorial shell — guard that boundary from both directions.

And to not be a yes-man about it: **the one scenario where adopting wins** is if your joy in the Swift shell fades and the project degrades into a chore. On pure capability-per-hour, "Jan + Cherry Studio + hand-run Hermes/Odysseus" gets maybe 70% of the outcome for 5% of the remaining effort. The other 30% — one window, silent supervised daemons, pin/rollback, no Docker, everything green at a glance — is precisely the itch that started this. As long as opening Mission Control still makes you happy, the math favors building. If it stops, this doc is your permission slip to collapse to the 70% and lose nothing important.

## 5. Comparison visual (spec for rendering)

One 2-axis scatter map, editorial-dark styling if rendered in your aesthetic:

- **X-axis: Capability breadth** — "single-purpose → all-in-one → orchestrates other programs" (left to right).
- **Y-axis: Local-first depth** — "cloud client with BYOK → runs local models → manages the local stack (runner lifecycle, search, daemons)" (bottom to top).
- Points (x, y on a 0–10 scale): LibreChat (6, 3) · LobeChat (6, 2.5) · Chatbox (5, 3.5) · Open WebUI (6.5, 5.5) · Cherry Studio (7.5, 4.5) · Witsy (4, 4.5) · Msty (5.5, 6) · BoltAI (4.5, 4) · AnythingLLM (7, 6.5) · LM Studio (4, 7.5) · Jan (5, 8) · Odysseus (7, 7.5) · **The MOT Deck (target) (9, 9.5)** — annotate: "only occupant of the top-right: supervises Jan + Odysseus + Hermes + SearXNG behind one native window."
- Optional shape/color encoding: circle = open source, diamond = proprietary; gold ring = MCP host.

---

*Cross-references: dual-mode runner design now lives in [02_Architecture.md](02_Architecture.md) §Runner slot; new open questions and recommendations are indexed in [00_START_HERE.md](00_START_HERE.md); the Odysseus license correction is noted in [03_Licensing.md](03_Licensing.md).*
