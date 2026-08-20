# Repo triage — 2026-08-20

**Brief:** Fable asked for adversarial triage of a list of repos Debi collected. Adopt/reject decisions ride on this.
House constraints applied throughout: Apple Silicon, **no Docker**, pin+vendor doctrine, components = port + health + tab,
local models via OpenAI-compatible runner on `:6767` (llama.cpp / MLX), daily model is a **4B** (27–30B available via LM Studio),
Hermes = resident agent, Odysseus = chat workspace.

**No code was changed. This is a report.**

---

## VERDICTS TABLE

| Item | What it really is | License | Mac + local-model fit | Overlap with harness | Verdict |
|---|---|---|---|---|---|
| **aider** | Terminal REPL coding agent (+ experimental Streamlit browser UI). No server API. | Apache-2.0 | **Best of the lot: needs NO tool-calling** — edits via text edit formats. `OPENAI_API_BASE` + `openai/<model>` is documented. | Complements Hermes (repo map + edit-loop discipline Hermes lacks) | **ADOPT (primary)** — but pin it: upstream has had **no release since 2025-08-09**; living fork is `cecli`. |
| **goose** | General-purpose agent (desktop app + CLI + ACP/REST server), not a coding agent | Apache-2.0 | First-class local config (`OPENAI_HOST`/`OPENAI_BASE_PATH`), but vendor says **"works best with Claude 4"** and tool-calling is load-bearing | Duplicates Hermes almost exactly | **REJECT** — a second Hermes with worse local-model odds. |
| **OpenCode** (`anomalyco/opencode`, formerly `sst/`) | TUI + CLI + desktop + `opencode serve` headless HTTP | MIT | Local first-class (`@ai-sdk/openai-compatible` + `baseURL`); **tool-calling required**, docs admit few models are good at both code + tools | Best *embeddable* contract of any candidate | **RECON-FURTHER** — best tab-integration story (OpenAPI 3.1 + SSE + permission endpoints), but 6,496 open issues and 4B won't drive it. |
| **Crush** | Charm's TUI + `crush serve` | **FSL-1.1-MIT — source-available, NOT OSI open source** | **Best local engineering anywhere**: native `llamacpp` *and* `omlx` (MLX) provider types + model auto-discovery + separate large/small model slots | Coding agent, complements Hermes | **RECON-FURTHER** — licence is a doctrine decision, not a detail. |
| **OpenHands** | Agent platform (SDK + CLI + Docker GUI) | MIT (+ source-available `enterprise/`) | Docker *is* escapable (`RUNTIME=process`) but that means **zero isolation**; docs demand "a powerful model", name **35B / 64GB / ≥22k ctx**, smallest community-working model **14B** | Heavy duplicate of Hermes | **REJECT** — self-disqualifies on the 4B and on no-sandbox-without-Docker. |
| **Qwen Code** | Fork of gemini-cli that *added* OpenAI-compat; CLI + `qwen serve` daemon | Apache-2.0 (dual © Google/Qwen) | Cleanest env-var path of all: `OPENAI_BASE_URL` + `OPENAI_MODEL`, keyless local servers documented | Coding agent | **RECON-FURTHER** — the viable no-Docker runner-up to aider. |
| **gemini-cli** | Google's Gemini CLI | Apache-2.0 | **NO.** Gemini/Vertex auth only. The merged `GOOGLE_GEMINI_BASE_URL` speaks the *Gemini* wire protocol, not OpenAI — needs a translation proxy. | — | **REJECT** — Google closed the OpenAI-compat request as p2, pointing at Qwen Code. |
| **browser-use** | Python lib driving Chromium from an LLM loop | MIT | Local supported (`ChatOpenAI(base_url=…)`, Ollama provider) but **forces strict JSON-schema output per step** — worst possible ask for a 4B | **Already a Hermes backend** (`_PROVIDER_REGISTRY`) | **REJECT as new component / ADOPT as config** — it's a flag flip in Hermes, not a project. |
| **browser-use/web-ui** | Separate Gradio front-end (:7788) | MIT | Playwright hard dep | — | **REJECT** — changelog frozen since 2025-01; 324 open issues. |
| **firecrawl** | Self-hostable web-data API (scrape/crawl/map/extract) | **AGPL-3.0** (server); MCP server is MIT | Self-host = **API + workers + Playwright + Redis + RabbitMQ + Postgres**, Docker-first | **Already a Hermes backend**; overlaps SearXNG + `web_fetch` | **REJECT self-host / RECON-FURTHER the MCP** — 6 services on a 48GB-budgeted box is the wrong trade. |
| **affaan-m/ECC** | **Not an engine.** A prompt/skills/hooks config bundle for other harnesses (has a `.hermes/` dir) | MIT | N/A — no inference layer of its own | Parallel take on Hermes skills + our `guards/` | **REJECT as dependency** — read for ideas only; installing a third party's hooks into the agent tool path is what path-guard exists to prevent. |
| **langchain** | A *library* for building LLM apps. Not an app. | MIT | Trivially yes; irrelevant | Competes with code we already wrote (bridge, lanes, fan-out) | **REJECT** — nothing to adopt under compose-don't-build. |
| **nexu-io/open-design** | AI **design-artifact generator** (Next.js + local daemon + SQLite) that drives *coding-agent CLIs* as its engine. Not a Figma clone. | Apache-2.0 | Local endpoint supported (BYOK proxy incl. LM Studio/Ollama); no Docker required | New capability (artifact/deck/prototype generation) | **RECON-FURTHER** — real code, but aggressive growth marketing and unverifiable stars; sandbox before trusting. |
| **genspark-ai/genoffice** | AI **desktop office suite** (5 Electron apps, OOXML round-trip) | Apache-2.0 (`ee/` carve-out) | **AI is cloud-gated** — routes model calls through Genspark's service, no BYOK/base-URL | — | **REJECT as component** — Electron desktop, no port, no local endpoint. Its Apache-2.0 **engine packages** (`docx-engine`, `pptx-engine`) are the only stealable part. |
| **LibreChat** | ⚠️ *Not* "Libre Office" — a multi-provider chat **web app** | MIT | Custom OpenAI-compat endpoints are first-class (`librechat.yaml`); npm install works without Docker but **MongoDB is mandatory** | ~80% duplicate of Odysseus | **REJECT as component / ADOPT as feature quarry** — mine its agents/artifacts/RAG/fork feature set. |
| **unsloth** | ⚠️ **Debi was right.** Not just a CUDA library any more — **Unsloth Studio** is an open-source no-code **web UI on :8888** doing train + run + export for text/vision/TTS/embedding **with Mac MLX training** | **Dual: Apache-2.0 core, AGPL-3.0 Studio UI** | Mac training + MLX/GGUF inference documented; ships an **OpenAI-compatible API** and an explicit **Hermes Agent integration** | Huge — it is a rival whole-stack (chat, web search, code exec, model hub, API) | **RECON-FURTHER (highest value on the list)** — adopt narrowly as a **Tune/train surface**, never as a chat replacement. |
| **mlx-tune** (ex-`unsloth-mlx`) | Community MLX reimplementation of Unsloth's API — SFT/DPO/GRPO/vision/TTS/STT/OCR/embedding on Apple Silicon | Apache-2.0 | Native MLX, pip-installable, no Docker, 8GB+ | The library-level answer to the same wish | **ADOPT as the library** if a Tune tab gets built — solo maintainer, so pin hard. |

---

## 1. Coding agents

### The real question
Debi's framing was "something like Claude Code… apparently not the same as Hermes." That instinct is correct and worth naming precisely:
**Hermes has the tools but not the discipline.** Vendored Hermes ships a `coding` toolset and 35 toolsets total
(`vendor/hermes/toolsets.py`), with terminal + file + 13 browser tools. What it does *not* have is what makes Claude
Code/aider feel different on a codebase:

1. a **repo map** — a tree-sitter symbol graph, ranked and pruned to a token budget, so the model gets an orientation
   it could never discover by grepping;
2. a **structured edit format** with a verifier — search/replace or unified-diff blocks that either apply or fail loudly;
3. an **edit→lint→test→fix loop** — errors fed back automatically;
4. **commit-per-change** so every step is revertible.

That is the gap worth filling, and it is the axis on which to judge these seven.

### The local-model axis, which eliminates most of them
Six of the seven are **agentic tool-loop** agents: the model must emit valid JSON tool calls, multi-turn, over a large
fixed prefill of tool schemas. That is the single hardest thing to ask of a 4B, and the vendors say so themselves:

- **goose**: *"relies heavily on tool calling capabilities and currently works best with Claude 4 models."* Its Ollama
  tool-shim mitigation is experimental, Ollama-only, and carries open bugs (#8269, #8275).
- **OpenCode**: of the many models available, *"there are only a few of them that are good at **both** generating code
  and tool calling"* — and every model on its recommended list is frontier.
- **OpenHands**: *"it requires a powerful model to work."* Documented floor: Qwen3.6-35B-A3B, **64GB unified memory**,
  context **≥22,000** because *"the default (4096) is way too small — not even the system prompt will fit."*
  Smallest community-reported working model: **14B**.

**aider is the exception, and it is a structural exception, not a preference.** Its core edit loop sends no tools schema
at all — the model reads a repo map and prose, and writes an edit format back as text. Nothing has to be valid JSON.
Combined with `--edit-format whole` (the lowest bar of any option here) it is the only one of the seven with a real
chance on a 4B. ⚠️ *That "no tool-calling requirement" is inferred from the edit-format architecture; aider's docs never
state it as a negative requirement.*

### Recommendation: **aider, as a PTY tab, pinned**

Integration shape — deliberately the cheapest one available:

- **Not** a `components:` entry. aider is a CLI with no health endpoint and no server API; a port+health component
  would be fiction.
- Hermes's dashboard **already embeds a PTY** (`/api/pty`). The honest shape is a **new tab running `aider` in a PTY**,
  or simply a ⌘K action that opens one — the same class of surface the harness already ships.
- Config is three lines and needs no new machinery:
  `OPENAI_API_BASE=http://127.0.0.1:6767/v1`, `OPENAI_API_KEY=harness-local`, `aider --model openai/<registry-id>`.
  Note this must use the **wire model id** rule the harness already encodes (`wire_model_id()` in `bridge/app.py`):
  gguf → registry id, mlx → the registry *path*.
- aider auto-commits. On this repo, with its uncommitted-work discipline, that wants an explicit `--no-auto-commits`
  decision before anyone runs it in the harness tree.

**The catch, and it is real:** upstream aider's last GitHub release is **v0.86.0, 2025-08-09** — roughly twelve months
cold, with ~1,600 open issues and a maintainer described as AFK. The community fork `aider-ce` was created for exactly
that reason and has since been renamed **`cecli`** (`dwash96/cecli`), with releases into July 2026. Under pin+vendor
doctrine a frozen upstream is *cheap*, not disqualifying — we pin anyway. But the choice between "pin stale Apache-2.0
upstream" and "pin an active fork" is a Fable call, not a builder's.

### Runners-up, honestly ranked

- **Qwen Code** — if aider's staleness is a dealbreaker, this is the pick. Apache-2.0, `npm -g`, no Docker, and the
  cleanest local config on the list (`OPENAI_BASE_URL`/`OPENAI_MODEL`, with a documented keyless-local-server example).
  `qwen serve` gives a loopback HTTP+SSE daemon with sane auth (bearer token required for non-loopback binds).
  Costs: Node ≥22, a **94 MB / 948-file** npm install, tool-calling required, and it is tuned for *Qwen* output quirks.
- **Crush** — technically the best-engineered for this exact machine: native `llamacpp` **and `omlx` (MLX)** provider
  types, model auto-discovery off `/v1/models`, explicit per-model `--context-window`, a separate **small-model slot**
  for housekeeping, and `permissions deny` that *hides* a tool from the agent. Two blockers: the **FSL-1.1-MIT licence
  is source-available, not open source** (fine for personal internal use, materially different if the harness is ever
  open-sourced or shipped — GitHub reports it as `NOASSERTION`, so scanners will flag it), and its config is **trusted
  code** (`crushrc` is Bash; `$(...)` in `crush.json` executes at load). Also: metrics on by default
  (`CRUSH_DISABLE_METRICS=1`) and a provider catalog that auto-updates from Charm's servers
  (`CRUSH_DISABLE_PROVIDER_AUTO_UPDATE=1`) — both want disabling in a local-first harness.
- **OpenCode** — the only candidate that hands you a **documented versioned HTTP contract** for building a native
  panel: `opencode serve`, OpenAPI 3.1 at `/doc`, SSE at `/event`, `POST /session/:id/permissions/:permissionID`,
  `OPENCODE_SERVER_PASSWORD`. If the harness ever wants a coding lane rendered in its *own* editorial UI with approval
  cards (exactly the Hermes-lane pattern already built), this is the substrate. Against it: **6,496 open issues** and
  a 4B cannot drive it.

⚠️ **Naming, for the record:** `opencode-ai/opencode` is the dead Go ancestor. Charm hired its original author, then
renamed *its* lineage **Crush**; the OpenCode name went with a TypeScript rewrite now at **`anomalyco/opencode`**
(`sst/opencode` redirects there). Crush's `LICENSE.md` still carries the original author's MIT notice, corroborating
the lineage.

- **gemini-cli — out.** Auth is Gemini API key / Vertex / Sign-in-with-Google. Issue #23385 ("Support OpenAI-compatible
  API endpoints") was **closed as p2/possible-duplicate**, and it name-checks Qwen Code as the fork that already
  shipped it. The merged PR #25357 added `GOOGLE_GEMINI_BASE_URL` and explicitly permits `localhost` over HTTP — but it
  passes that URL to `@google/genai` as `httpOptions.baseUrl`, so it sends **Gemini `generateContent`** requests. Our
  runner speaks OpenAI `/v1/chat/completions`. Making it work needs a bidirectional translating proxy as a fourth moving
  part, permanently chasing an internal Google protocol. That is the definition of a hack.

- **OpenHands — out, and the no-Docker question deserves a straight answer.** Docker is *not* truly required:
  `RUNTIME=process` (legacy alias `local`) runs the agent server as a normal process, and `openhands web` is listed with
  dependencies **"None"** (only `openhands serve`, the full React GUI, is Docker-gated). But the docs are blunt about
  what that costs: *"This mode provides **no sandbox isolation**. The agent can read/write files your user account can
  access and execute commands on your host system."* Two tells that it is second-class: the CLI command reference
  exposes **no sandbox flag at all** (you steer a core env var from outside the documented surface), and there is an open
  issue (#13203) proposing a QEMU/HVF microVM backend precisely because Docker-or-nothing is a live complaint. Combined
  with the 35B/64GB/22k-context floor, this is the wrong tool for this box.

---

## 2. Browser control — and the finding that reframes it

**The single most important fact here was in our own `vendor/` the whole time.**

`vendor/hermes/toolsets.py:205-215` defines a `browser` toolset with **13 `browser_*` tools** — `browser_navigate`,
`browser_snapshot`, `browser_click`, `browser_type`, `browser_scroll`, `browser_back`, `browser_press`,
`browser_get_images`, `browser_vision`, `browser_console`, `browser_cdp`, `browser_dialog`, `browser_exec` — plus
`web_search`. It drives a **real Chromium via Playwright + CDP** (`vendor/hermes/tools/browser_tool.py`, ~5300 lines;
CDP endpoint resolution at `:452-514`, configurable via `BROWSER_CDP_URL` or `browser.cdp_url`). It is **not** in the
default-off set, so it is on by Hermes default.

And `browser_tool.py:688-692` reads:

```python
_PROVIDER_REGISTRY = {"browserbase", "browser-use", "firecrawl"}
```

**browser-use and firecrawl are already pluggable backends in the Hermes we vendor.** Setting
`browser.backend = "browser-use"` collapses the model's surface to a single `browser_exec` tool
(`vendor/hermes/tools/browser_use_cli.py`). So items 2 and 3 on Debi's list are **configuration questions inside a
component we already ship**, not integration projects. That is a much better answer than "adopt a new component," and
nobody would have found it from the READMEs.

Two corollaries worth stating plainly:

- **Playwright is not a pinned Hermes dependency.** It is absent from `vendor/hermes/pyproject.toml` and probed
  lazily (`_chromium_installed()` at `:1218`, with install nudges at `:435`, `:1229`, `:2741`; `hermes doctor` checks
  for it). So Hermes's browser toolset is *present but probably inert on this machine* until
  `npx playwright install --with-deps chromium` has been run. **This is the cheapest unclaimed capability on the list
  and should be verified before anything else here is considered.**
- **browsermcp may be largely redundant.** `bridge/app.py:5006-5011` registers `@browsermcp/mcp` as an MCP — and the
  comment at `:5008-5009` says Hermes-side registration was a follow-up slice that was never done. So today
  browsermcp serves **Odysseus** while Hermes has its own richer native path. Those are two different browser stacks
  for two different lanes, which is fine, but it should be a decision rather than an accident.

### Debi's broader ask: "add chrome / some web browser that ties to the LM side"

Three honest options, cheapest first:

1. **Turn on what we have (recommended).** Install Playwright's Chromium once; Hermes's 13-tool browser toolset comes
   alive with snapshots, clicks, typing, console access, raw CDP and a vision path. Cost: one `npx` command and a
   Chromium download. Risk: none new — the toolset already exists and is already governed by the approval + path-guard
   machinery. This is a config change, not a build.
2. **Keep/extend browsermcp for Odysseus.** Already working, already toggleable from the panel. Nothing to do.
3. **An embedded in-app browser pane the agent drives (the ambitious one).** Genuinely feasible and architecturally
   close: the shell is already a five-tab `WKWebView` host with split view, ghost panes, drag-to-pane and a download
   delegate. The problem is that **WKWebView is not CDP-controllable** — Hermes drives Chromium over the DevTools
   protocol, and WebKit does not speak it. So the honest shape is *not* "let the agent drive our WKWebView"; it is
   **launch a headless-but-visible Chromium with `--remote-debugging-port`, point `BROWSER_CDP_URL` at it, and show
   it in a window/pane** — the agent and the human then share one real browser. That is a real slice (process
   lifecycle, port, window management) and wants a Fable spec. ⚠️ Whether a CDP-driven Chromium window can be hosted
   *inside* the harness window on macOS, versus sitting beside it, is unverified.

**browser-use itself: REJECT as a component.** Its default forces
`response_format: {type: "json_schema", strict: true}` on every step over a large DOM-state prompt. The very existence
of its escape hatches — `dont_force_structured_output`, `add_schema_to_system_prompt`,
`remove_min_items_from_schema` — is upstream conceding that non-frontier backends can't satisfy strict schema mode.
All its published benchmarks are frontier models; there is **no official small-local-model benchmark**. If it is ever
wanted, it arrives as a Hermes `browser.backend` value, not a tab. Its `web-ui` sibling (Gradio, :7788) is stale —
324 open issues and a README changelog frozen at 2025-01-26.

---

## 3. firecrawl

**What it adds over what we have:** genuinely a lot — `map` (URL discovery), `crawl`, schema/LLM `extract`, `parse`
(PDF/docx/xlsx → markdown), `monitor` (scheduled re-checks with change detection + webhooks), and research endpoints.
Odysseus's `web_search` + `web_fetch` + SearXNG cover *search and fetch one page*; firecrawl covers *acquire a
structured corpus*.

**What it costs to self-host:** `SELF_HOST.md` is explicit — *"Compose runs the Firecrawl API and workers, Playwright,
Redis, RabbitMQ, NuQ PostgreSQL, and FoundationDB services…"*, API published on `:3002`. Docker Compose is the
documented baseline; the alternatives are Kubernetes and Helm. A bare-metal path exists only as a *contributor*
"Running Locally" guide. Two sharp edges stated outright: the default API is **unauthenticated**
(`USE_DB_AUTHENTICATION=false`), and the root Compose file **defines no persistent volumes**.

**Licence:** **AGPL-3.0**, and verified as the full unmodified text (35,064-byte `LICENSE`, no exception preamble).
Personal use is unaffected and the network clause only bites on *modified* versions — the same posture already accepted
for SearXNG and VoiceStudio. The SDKs and the **MCP server are MIT**, separate repos.

**Verdict: REJECT self-hosting.** Six services on a machine with a 48GB model-RAM budget is the wrong trade for a
capability we mostly have. **The cheap integration is the MCP** — `firecrawl-mcp-server` (MIT) takes
**`FIRECRAWL_API_URL`** to point at a self-hosted instance, with `FIRECRAWL_API_KEY` optional in that mode. And before
even that: they operate a **keyless hosted MCP endpoint** (`https://mcp.firecrawl.dev/v2/mcp`) where scrape/search/parse
work rate-limited with no key — zero infrastructure, and it plugs into the MCP wiring both Hermes and Odysseus already
have. ⚠️ That is a *cloud* dependency, which cuts against the local-first grain; flagging it as an option, not a
recommendation.

And again: **`firecrawl` is already in Hermes's `_PROVIDER_REGISTRY`**, so there may be a config path that needs no MCP
at all. Worth reading `browser_tool.py`'s firecrawl branch before building anything.

---

## 4. affaan-m/ECC — answering Debi's three questions directly

**What it actually is:** not an engine. ECC self-describes as *"The agent harness performance optimization system.
Skills, instincts, memory, security, and research-first development for Claude Code, Codex, Opencode, Cursor and
beyond."* Installed as a Claude Code plugin marketplace. Its repo tree is per-harness dotfolders — `.claude`, `.codex`,
`.cursor`, `.gemini`, **`.hermes`**, `.opencode`, `.qwen`, `.zed`, … — plus `agents/`, `commands/`, `skills`, `hooks/`,
`contexts/`. MIT. Primary language JavaScript; effectively **markdown + shell + JS configuration, with no service to
run**.

- **"Is this better than Hermes?"** — Not comparable. Hermes is an agent runtime (model loop, tools, approvals,
  sessions, WS gateway). ECC has **no inference layer at all**; it configures whatever harness you already run. It
  cannot replace Hermes because it does not do what Hermes does.
- **"Could it be our engine but more robust?"** — No. There is no engine in it.
- **"Is this a combination of Hermes and Odysseus?"** — No. It is a *prompt-and-skills layer* — the same category as
  Hermes's own skills, our `guards/harness-path-guard`, and this `CLAUDE.md` working-memory discipline. It is a
  competing take on the layer we already have, not a combination of the two components.

**Maturity:** genuinely, intensely active — created 2026-01-18, ~2,428 commits, last push the day before this report.
But by its own admission *"a single maintainer ships weekly across 7 harnesses"*, with ~144 open issues and ~100 open
PRs. It is open-core commercial (MIT repo funding a $19/seat/mo hosted GitHub App). The README carries a prominent
**malware warning about unofficial mirrors** — i.e. it has been targeted for supply-chain impersonation.

⚠️ **Anomaly flagged rather than laundered:** the GitHub API reports **~241,000 stars / ~36,500 forks** for a 7-month-old
markdown-and-config bundle. That would make it one of the most-starred repos in existence. I report the API figure
because it is the authoritative source, but I did not audit it, and the README leans on a custom
`api.ecc.tools/badge/stars` endpoint rather than GitHub's own shield. Treat the number as unverified.

**Verdict: REJECT as a dependency; read for ideas.** Installing a third party's `hooks/` into the agent's tool path is
precisely the surface `guards/harness-path-guard` and the approval-card work exist to control. Its cross-harness skill
*packaging* ideas may be worth reading.

---

## 5. langchain — answering "is it the same as ECC?"

No, and it is not the same category as anything else on this list.

**LangChain is a library** — a set of Python (and JS) abstractions over chat models, tools, embeddings and vector
stores, so that application code can swap providers. MIT, org-backed by a commercial company (LangSmith), ~137k stars,
very active. **There is no app**: no UI, no process to run, no port, nothing to install and open. Its ecosystem splits
into **LangGraph** (a separate repo — the low-level agent orchestration framework), **Deep Agents** (a higher-level
package: planning, subagents, filesystem), and **LangSmith** (the paid observability/eval product).

Why it is not comparable to Hermes/Odysseus: those are *finished applications* with their own runtimes, UIs, session
stores and tool implementations. LangChain is the raw material you would use to *build* such a thing.

**Use for this harness: none, and adopting it would be actively costly.** The compose-don't-build doctrine says: take
finished components and wire them over HTTP/MCP. LangChain is the opposite move — it would mean rewriting the bridge's
lanes, fan-out and relay against someone else's abstraction layer, for **zero end-user capability gain**. The one place
it legitimately shows up is indirectly: LibreChat's RAG API is a LangChain/FastAPI service. That is fine — it is
somebody else's implementation detail, which is exactly where a framework belongs.

---

## 6. nexu-io/open-design

**Not a Figma clone.** It is a local-first **AI design-artifact generator**: a Next.js web app plus a local Express
daemon that drives *coding-agent CLIs* (Claude Code, Codex, Cursor Agent, OpenCode, Qwen…) as its rendering engine,
producing prototypes, landing pages, dashboards, slide decks, images and video as real files with HTML/PDF/PPTX/MP4
export. No canvas editor, no layers — a prompt→artifact pipeline positioned as an "open-source Claude Design
alternative."

- **Licence: Apache-2.0**, read from the actual `LICENSE` ("Copyright 2026 Open Design contributors"). ⚠️ At least one
  aggregator summary claims MIT — that is wrong.
- **Runtime:** Node ~24 + pnpm 10.33, Next.js 16, Express daemon with SSE, **better-sqlite3** (`.od/app.sqlite`,
  relocatable via `OD_DATA_DIR`). **Docker offered but not required.** Also ships a signed desktop app.
- **Local models: yes** — a BYOK proxy (`POST /api/proxy/{openai,ollama,...}/stream`) with presets for LM Studio,
  vLLM, Ollama and any OpenAI-compatible endpoint.
- **The hidden dependency is the real story:** it expects at least one **coding-agent CLI on your PATH** — that is its
  actual engine. And the CLI-plus-local-model combination is visibly flaky: issue #4932 reports *"OpenCode + Ollama
  completes successfully but generated files are never written."*
- **Health:** real, active code (open-sourced ~2026-04-28, issue numbers in the #4900s) wrapped in **aggressive growth
  marketing** — a keyword-stuffed repo description, a paid "Open Design Cloud" upsell with utm-tagged links, and
  feature counts that differ wildly between README versions (19 vs 31 vs "259+ Skills"). ⚠️ Aggregator star counts
  disagree by 4× (21k / 84k / 89.5k); I could not verify a real number.

**Integration shape if adopted:** it fits the component pattern on paper (daemon, port, SQLite, no Docker) — but note
it would be a component whose engine is *a coding agent CLI*, i.e. it only becomes useful **after** item 1 is settled.

**Verdict: RECON-FURTHER, sandbox-first.** The capability is genuinely new to the harness and the licence/runtime are
compatible; the marketing posture and the unverifiable numbers mean nobody should adopt this on README trust.

---

## 7. genspark-ai/genoffice

**What it actually is:** a real AI-native **desktop office suite** — five Electron apps (Docs/.docx, Sheets/.xlsx,
Slides/.pptx, PDF, plus a tabbed shell) over shared pure-TypeScript engine packages, with byte-preserving OOXML
round-trips and an embedded AI panel doing block-granular editing. **Not** a headless document-generation library.
Open-sourced 2026-08-03 by Genspark/Mainfunc; Apache-2.0 with an `ee/` enterprise carve-out and a trademark clause
(forks must rebrand). Professionally engineered — SECURITY.md with renderer sandboxing, third-party notice generation.

**The deal-breaker, verbatim from the README:** *"The apps sign in to a Genspark account and route model calls through
the Genspark service side; no model API key is stored locally."* There is a `packages/ai-provider` abstraction but **no
documented BYOK or base-URL override**, and server-side AI actions burn **Genspark cloud credits**. So: free, offline,
ad-free *editing* — cloud-gated *intelligence*. Some secondary articles overstate BYOK; the repo is the authority.
Sheets additionally needs a **Rust toolchain** for its xlsx sidecar.

**Verdict: REJECT as a component.** Electron desktop app — no port, no health endpoint, nothing to embed as a tab, and
its AI cannot point at `:6767`. **What is worth stealing:** the Apache-2.0 TypeScript **engine packages**
(`docx-engine`, `pptx-engine`/`pptx-render`, `file-parse`, `agent-core`) have zero Electron dependency and are
importable as libraries — a credible route to local docx/pptx read-write if the harness ever wants document output.
⚠️ Whether `ai-provider` has an *undocumented* base-URL override is unverified (would need to read source).

---

## 8. danny-avila/LibreChat

⚠️ **Naming flag, front and centre: Debi labelled this "Libre Office." It is LibreChat — a multi-provider AI chat web
app with no relationship whatsoever to LibreOffice.** Worth correcting explicitly, because the two would be triaged
completely differently.

**What it is:** the reference open-source ChatGPT-style self-hosted web app. MIT. Node 24 + npm works **without
Docker** (`npm run reinstall && npm run backend`, serves on **:3080**), but **MongoDB is mandatory**. Optional add-ons:
Meilisearch (message search), a separate RAG API service (LangChain/FastAPI + pgvector), and a Code Interpreter that is
a **paid LibreChat API service**. Custom OpenAI-compatible endpoints are first-class — `librechat.yaml`
`endpoints.custom[]` with `baseURL`/`apiKey`/`models`, and the docs ship an Ollama example; pointing it at `:6767` with
a dummy key would just work. Health is strong, and it has just picked up corporate backing (**joining ClickHouse to
power an "Agentic Data Stack"** — worth watching for roadmap drift).

**The honest overlap answer: ~80% duplicate of Odysseus.** Chat over multiple endpoints, sessions, tools, MCP, web
search, artifacts, file upload — Odysseus already does all of that, and the harness has built a great deal of bespoke
machinery *on top of* Odysseus (the direct lane, the session rail, per-message actions, the attachment sidecar, the
artifact renderer, the capabilities panel). Running a second chat app would fork the user's attention and double the
surface for zero new capability in the common case.

**Is there ANY feature worth it?** Yes — as a **specification quarry**, not a component. The ones Odysseus does not
appear to cover:

- **Agents / Subagents / Agent Plugins / Skills** + an Agents API — no-code custom assistants with their own tools and
  files. (The harness's analogue is the Hermes lane; a *user-defined agent* surface is genuinely absent.)
- **Sandboxed Code Interpreter** (Python/JS/Go/Rust). Note: paid hosted service, not self-hostable — so this is an
  idea, not a component.
- **User Memory** — persistent cross-conversation context. (The harness's unified-memory milestone is still open.)
- **Model Arena / side-by-side comparison.**
- **Resumable streams** — auto-reconnect after an interrupted response. Directly relevant: the harness has fought
  turn-lifecycle and WS-1005 teardown bugs repeatedly, and "the stream survives a reconnect" is a real design idea.
- **Enterprise auth** (OAuth2/SAML/LDAP/2FA, roles, admin panel) — irrelevant for a single-user personal harness, and
  worth naming as irrelevant so it doesn't inflate the comparison.
- Conversation **forking** and **import from ChatGPT** — the harness already has fork; import does not exist.
- No "assistants marketplace" in the app-store sense; the analogue is shared/permissioned Agents.

**Verdict: REJECT as a component (MongoDB + duplicate), ADOPT as a feature quarry.** The two highest-value ideas to
lift are **resumable streams** and a **user-facing agent-definition surface**.

---

## 9. Unsloth — Debi was right, and this is the headline finding

### The correction I expected to write, and didn't

The brief asked me to verify whether Unsloth is "an APP or a fine-tuning LIBRARY (+ notebooks)", and whether it runs on
Apple Silicon at all given the Triton/CUDA dependency. The expected answer was "library, CUDA-only, Debi saw the
notebooks." **That answer is now out of date.**

**Unsloth Studio** is *"an open-source, no-code web UI for training, running and exporting open models in one unified
local interface."* Per Unsloth's own docs:

- **Runs a web UI on port 8888** (`unsloth studio -p 8888`), loopback by default, password on first launch, JWT
  auth. Install: `curl -fsSL https://unsloth.ai/install.sh | sh` into `~/.unsloth/studio` — plus a native desktop app.
- **Mac: *"Training, MLX and GGUF inference all work inside of Unsloth."*** It runs GGUF, MLX **and diffusion
  image/video** models on Mac.
- **Text + diffusion vision + TTS audio + embedding** models, train and run.
- Ships an **OpenAI-compatible *and* Anthropic-compatible API** on the same port (`/v1/chat/completions`,
  `/v1/responses`, `/v1/messages`, `/v1/models`) with `sk-unsloth-…` bearer keys and a live API monitor.
- **Data Recipes** — auto-builds datasets from PDF/CSV/JSON/DOCX/TXT (powered by NVIDIA NeMo Data Designer).
- Exports to **GGUF / 16-bit safetensors** for llama.cpp, Ollama, LM Studio.
- **Licence: dual — Apache-2.0 core, AGPL-3.0 for the Studio UI.** Same posture the harness already accepted for
  SearXNG and VoiceStudio, and the same doctrine applies (arm's-length HTTP, never edit vendor, never modify-and-serve).

So Debi's claim — *"unsloth is doing everything I'm trying to do — text/audio/image in one app for local AI"* — is
substantially **accurate**. What she saw was not the notebooks.

### And it documents a first-class Hermes Agent integration

This is the part nobody would have guessed. Unsloth ships `/docs/integrations/hermes-agent.md`, an `unsloth start hermes`
command, and this warning, verbatim:

> Use `--disable-tools` when driving Hermes (or any external agent with its own tools). By default Unsloth Studio runs
> its own server-side tools, **which swallows the agent's tool calls, so Hermes answers but never runs its tools.**
> `--disable-tools` switches to passthrough, so Hermes's own tools are used.

That is a precise description of a failure mode this harness would have hit blind — and it is the exact seam
(`platform_toolsets`, the toolset lever, the approval cards) that has consumed several sessions. Unsloth also documents
the Hermes config path we already write to (`~/.hermes/config.yaml` + `.env`) and the "Custom OpenAI-compatible
endpoint" wizard flow.

### The honest caveats — and there are five

1. **Mac training is new and the docs contradict themselves.** `studio.md` says *"MacOS: Training, MLX and GGUF
   inference all work."* `install.md` says *"Mac: Like CPU - Chat + Data Recipes works for now. **MLX** training now
   works!"* And the **Unsloth Core** requirements page still says *"Apple/Silicon/MLX is in the works."* Three pages,
   three positions. Read that as: **MLX training landed recently and is beta.** ⚠️ Unverified on this machine.
2. **It is a rival whole-stack, not a feature.** Studio brings its own chat, its own web search, its own code
   execution, its own model hub, its own agent launcher, and its own **llama.cpp build** (`~/.unsloth/llama.cpp`,
   needs `brew install cmake openssl git`) alongside our pinned `b10427`. Adopting it wholesale would mean adopting a
   competitor to the harness's entire reason for existing.
3. **Security posture cuts against ours.** Server-side tools (web search, **Python and terminal execution**) *"run as
   your user and are on by default"* on loopback — *"Anyone who can reach the server with the API key can run code on
   this machine."* That is a strictly weaker stance than the harness's path-guard + approval-card discipline, and it
   would sit on the same box.
4. **RAM-ledger blindness.** It uses `~/.cache/huggingface` (which our registry already scans as `audio-hf-cache`) and
   loads its own resident models. A model loaded in Studio is **invisible to `memory.budget_gb: 48`** — the same class
   of gap already recorded for the voice components, but worse, because training peaks are large and sustained.
5. **Duplicate models on disk.** Shared HF cache helps, but Studio's own downloads and exports are another multi-GB
   claimant on a disk that has already hit full once in this project's history.

### Verdict and integration shape

**RECON-FURTHER — highest-value item on the list, adopted narrowly.**

The wrong move is a "Tune tab" that is really a second harness. The right move, if Debi wants this, is a **component in
the VoiceStudio pattern**: `components.unsloth` in `harness.yaml` (repo/pin/port 8888/installed:false/enabled:false),
`installed:false` by default, its own tab, health-checked on `:8888`, **started only when training** — and explicitly
**not** wired as a chat provider or an agent endpoint. Our runner stays `:6767`. Its AGPL UI is reached over HTTP,
never modified.

Two things must be settled *before* any build, and both are Fable calls:
- **Does a resident training process get a ledger claim?** The existing verdict ("the ledger counts persistent runner
  slots; voice engines are transient subprocesses") does not cover a multi-hour training run that pins tens of GB.
  This is the strongest argument yet for the deferred ledger work.
- **Do we accept a second llama.cpp + a second tool-executing server on the box?** That is a doctrine question, not an
  engineering one.

### The Apple-Silicon-native alternative, as requested

Two paths, and the first is nearly free:

**(a) `mlx_lm.lora` — already installed.** Confirmed present in the provisioned venv:
`data/mlx-venv/bin/mlx_lm.lora`, plus `mlx_lm.fuse`, `mlx_lm.convert`, `mlx_lm.dwq`, `mlx_lm.awq`, `mlx_lm.gptq`,
`mlx_lm.evaluate`, `mlx_lm.perplexity`. Pinned `mlx-lm==0.31.3` (`harness.yaml:202`), with `transformers 5.14.1` and
`torch 2.13.0` already in that venv. **There is zero fine-tuning surface in the harness today** — a repo-wide grep for
`lora|finetune|fine_tune|train` outside `vendor/`/`data/` returns nothing but prose and one HF dataset split. So the
capability is sitting in the venv, unexposed.

- **What it can tune:** LoRA/QLoRA and full fine-tune of any mlx-lm-supported text model, plus `fuse` to merge
  adapters and `convert` for quantisation.
- **Data shape:** JSONL — the standard mlx-lm `train.jsonl`/`valid.jsonl` with `text`, `prompt`/`completion`, or
  `messages` (chat) formats. ⚠️ The exact accepted key set at 0.31.3 should be read out of `mlx_lm/tuner/datasets.py`
  before writing a UI against it.
- **RAM on 64GB:** community reporting puts QLoRA at ~8B on 16GB, ~14B on 32GB, and **~32B on 64GB** — i.e. this
  machine can LoRA a 30B-class model, and comfortably tune the 4B daily driver. A 9B LoRA on an M4 Max/64GB is reported
  at ~2 hours for 600 iterations. ⚠️ All secondary sources; unmeasured here. And note the collision with
  `memory.budget_gb: 48` — a 32B QLoRA run and a loaded runner will not coexist.
- **Integration shape:** the smallest honest slice is **not a tab** — it is a `scripts/tune.sh` + a bridge endpoint
  that shells `mlx_lm.lora` with a log tail, in exactly the shape `install_mlx.sh` / `start_component.sh` already use,
  surfaced as a **Models → Tune** sub-tab beside the existing Chat/Audio sub-tabs. No new component, no new port, no
  new dependency, no AGPL. Then `mlx_lm.fuse` → an entry in our own registry → loadable by the runner immediately.

**(b) `mlx-tune` (`ARahim3/mlx-tune`, formerly `unsloth-mlx`) — the library-level answer.** Apache-2.0, `pip install
mlx-tune`, Apple Silicon only, macOS 13+, Python 3.9+, 8GB minimum. It deliberately mirrors **Unsloth's API**
(`FastLanguageModel`, `SFTTrainer`) on top of MLX, so scripts are portable to CUDA+Unsloth later. Coverage is startlingly
broad for a community project: SFT/DPO/ORPO/GRPO/KTO/SimPO, **vision** (via mlx-vlm — Gemma 4, Qwen3.5, Pixtral),
**TTS** (Orpheus, OuteTTS, Spark, Sesame/CSM, Qwen3-TTS), **STT** (Whisper, Moonshine, Canary, Voxtral, **Parakeet
TDT**), embeddings, OCR, MoE (39+ architectures), and continual pretraining. Several of those model families are ones
the harness *already ships* (mlx-audio TTS, Parakeet STT, mlx-vlm) — so this is the natural route to "fine-tune my own
voice/vision model" without leaving MLX.

⚠️ Real caveats: **solo maintainer, explicitly unofficial**, and it declares a dependency graph that already conflicts
with itself in one documented case (DeepSeek-OCR needs `transformers<5.0` while `mlx-lm>=0.31` needs `>=5.0` — their
own README ships a `--no-deps` workaround). It also documents a genuine limitation inherited from mlx-lm: **GGUF export
from a 4-bit base does not work** ([mlx-lm#353](https://github.com/ml-explore/mlx-lm/issues/353)) — train from fp16 if a
GGUF is the goal. Pin hard; do not float.

**Recommended sequencing:** `mlx_lm.lora` behind a Models → Tune sub-tab is the cheap, doctrine-clean first slice and
uses only what we already pin. `mlx-tune` is the second slice if Debi wants TTS/vision/preference tuning. **Unsloth
Studio is the third and largest** — and it is worth doing only if the ledger question is answered and the "second
whole-stack on the box" question is accepted.

---

## THREE MOST SURPRISING FINDINGS

1. **Hermes already has a 13-tool native browser stack driving real Chromium over Playwright+CDP — and
   `browser-use` and `firecrawl` are already registered backends in it** (`vendor/hermes/tools/browser_tool.py:688-692`
   `_PROVIDER_REGISTRY = {"browserbase", "browser-use", "firecrawl"}`). Two of the "should we adopt this?" items are
   config flags in code we already vendor. Playwright is not a pinned dep, so this capability is very likely **installed
   but inert** on Debi's Mac — one `npx playwright install chromium` from being live.
2. **Debi was right about Unsloth, and the docs are out ahead of everyone's mental model.** Unsloth Studio is an
   AGPL-licensed no-code web UI on `:8888` doing train + run + export for text/vision/TTS/embedding **with Mac MLX
   training**, an OpenAI- *and* Anthropic-compatible API — **and a documented first-class Hermes Agent integration**
   including the exact `--disable-tools` gotcha (Studio's server-side tools otherwise *swallow Hermes's tool calls*)
   that this harness would have hit blind.
3. **Every agentic coding agent on the list disqualifies itself on the 4B, in the vendors' own words** — goose
   ("works best with Claude 4"), OpenCode ("only a few are good at both code and tool calling"), OpenHands ("requires a
   powerful model", 35B/64GB/22k-context, community floor 14B). **aider survives for a structural reason, not a
   quality one: its edit loop sends no tools schema at all.** Meanwhile aider's upstream has had no release in ~12
   months — so the best local-model fit is also the most abandoned, and the active fork was renamed (`aider-ce` →
   `cecli`) mid-story.

## THREE BIGGEST UNCERTAINTY FLAGS

1. **No credible published benchmark exists for *any* of these coding agents against a 4B or 30B local model.** The
   llama.cpp/OpenCode/Crush literature documents *configuration*, never *quality*. Every expectation in §1 is either a
   vendor statement about model class or my own architectural inference — labelled as such, but it means the real answer
   to "will this be usable on the 4B?" can only come from Debi trying aider on this repo for an afternoon. That is the
   single cheapest decisive experiment on this list.
2. **Unsloth's Mac training claim is self-contradictory across three of its own doc pages** (`studio.md`: training
   works; `install.md`: "like CPU… MLX training now works!"; Core requirements: "Apple/Silicon/MLX is in the works").
   Nothing here was run on Debi's Mac. Also unverified: whether Studio's llama.cpp build conflicts with our pinned
   `b10427`, and how its resident models interact with `memory.budget_gb: 48`. **Do not plan a Tune tab on Unsloth
   until someone installs it and watches Activity Monitor.**
3. **Star counts and last-commit dates across this whole report are unreliable.** The GitHub API returned empty for
   several repos and served what look like cached `pushed_at` values (two unrelated repos with identical timestamps).
   Specific anomalies: **ECC at ~241k stars** for a 7-month-old config bundle (reported from the API, not audited);
   **open-design** star counts spanning 21k–89.5k across aggregators; **Crush's `/v1` server mode reported as
   unauthenticated** by a single secondary source (verify before binding anywhere but loopback); and the completeness
   of a **bare-metal no-Docker firecrawl** path, which lives in a contributor guide I did not read.

---

### Cited sources

Coding agents: [aider](https://github.com/Aider-AI/aider) · [aider OpenAI-compat](https://raw.githubusercontent.com/Aider-AI/aider/main/aider/website/docs/llms/openai-compat.md) · [aider repo map](https://raw.githubusercontent.com/Aider-AI/aider/main/aider/website/docs/repomap.md) · [aider v0.86.0](https://github.com/Aider-AI/aider/releases/tag/v0.86.0) · [cecli fork](https://github.com/dwash96/aider-ce) · [goose providers](https://goose-docs.ai/docs/getting-started/providers/) · [goose Ollama tool shim](https://goose-docs.ai/docs/experimental/ollama/) · [OpenCode server](https://opencode.ai/docs/server/) · [OpenCode models](https://opencode.ai/docs/models/) · [OpenCode name dispute](https://biggo.com/news/202507070115_OpenCode_Name_Dispute) · [Crush README](https://raw.githubusercontent.com/charmbracelet/crush/main/README.md) · [Crush LICENSE (FSL-1.1-MIT)](https://raw.githubusercontent.com/charmbracelet/crush/main/LICENSE.md) · [OpenHands process sandbox](https://docs.openhands.dev/openhands/usage/sandboxes/process) · [OpenHands local LLMs](https://docs.openhands.dev/openhands/usage/llms/local-llms) · [OpenHands #13203](https://github.com/OpenHands/OpenHands/issues/13203) · [Qwen Code auth docs](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/) · [gemini-cli #23385](https://github.com/google-gemini/gemini-cli/issues/23385) · [gemini-cli PR #25357](https://github.com/google-gemini/gemini-cli/pull/25357)

Browser/scrape: [browser-use](https://github.com/browser-use/browser-use) · [browser_use ChatOpenAI source](https://raw.githubusercontent.com/browser-use/browser-use/main/browser_use/llm/openai/chat.py) · [browser-use/web-ui](https://github.com/browser-use/web-ui) · [firecrawl SELF_HOST.md](https://github.com/firecrawl/firecrawl/blob/main/SELF_HOST.md) · [firecrawl-mcp-server](https://github.com/firecrawl/firecrawl-mcp-server)

Others: [affaan-m/ECC](https://github.com/affaan-m/ECC) · [langchain](https://github.com/langchain-ai/langchain) · [nexu-io/open-design](https://github.com/nexu-io/open-design) · [open-design #4932](https://github.com/nexu-io/open-design/issues/4932) · [genspark-ai/genoffice](https://github.com/genspark-ai/genoffice) · [LibreChat custom endpoints](https://www.librechat.ai/docs/quick_start/custom_endpoints) · [LibreChat npm install](https://www.librechat.ai/docs/local/npm) · [LibreChat features](https://www.librechat.ai/docs/features)

Unsloth/MLX: [Unsloth Studio](https://unsloth.ai/docs/new/studio.md) · [Unsloth Studio install](https://unsloth.ai/docs/new/studio/install.md) · [Unsloth requirements](https://unsloth.ai/docs/get-started/fine-tuning-for-beginners/unsloth-requirements) · [Unsloth API endpoint](https://unsloth.ai/docs/basics/api.md) · [Unsloth × Hermes Agent](https://unsloth.ai/docs/integrations/hermes-agent.md) · [mlx-tune](https://github.com/ARahim3/mlx-tune) · [mlx-lm #353 (GGUF export)](https://github.com/ml-explore/mlx-lm/issues/353)

Local repo facts: `vendor/hermes/toolsets.py:205-215` · `vendor/hermes/tools/browser_tool.py:452-514,688-692` · `vendor/hermes/tools/browser_use_cli.py:21,117` · `bridge/app.py:5006-5011,5113-5117` · `harness.yaml:66-71,78-84,104-132,140-144,181-182,202-229` · `data/mlx-venv/bin/mlx_lm.lora`
