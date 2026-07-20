# 02 — Architecture

*Part of the Harness handoff set. Index: [00_START_HERE.md](00_START_HERE.md). Why this shape: [01_Vision_and_Decision.md](01_Vision_and_Decision.md). Licenses per layer: [03_Licensing.md](03_Licensing.md).*

---

## The composed architecture

```
┌───────────────────────────────────────────────────────────────────┐
│  MISSION CONTROL  (Swift, native, YOURS)                          │
│  one window · ⌘K palette · status cards · activity feed           │
│  unified model catalog/browser · plan-and-approve installs        │
│  Odysseus embedded as a webview tab                               │
└───────────────▲───────────────────────────────────────────────────┘
                │ local HTTP (Bridge API)
┌───────────────┴───────────────────────────────────────────────────┐
│  BRIDGE  (local orchestration server, YOURS)                      │
│  component lifecycle (spawn/stop/health) · git pin & rollback     │
│  of upstream repos · venv/dep management · config fan-out         │
│  permission broker · runner-slot adapter layer                    │
└──┬───────────────┬───────────────┬───────────────┬────────────────┘
   │ OpenAI-wire   │ HTTP :7860    │ daemon/CLI    │ HTTP :8080
   │ + CLI         │               │ + config.yaml │
┌──▼──────────┐ ┌──▼──────────┐ ┌──▼──────────┐ ┌──▼──────────┐
│ RUNNER SLOT │ │ ODYSSEUS    │ │ HERMES      │ │ SEARXNG     │
│ (swappable) │ │ workspace + │ │ async agent │ │ shared meta │
│ Jan today   │ │ DeepResearch│ │ daemon      │ │ -search     │
│ LM Studio   │ │ (MIT)       │ │ (MIT)       │ │ (AGPL)      │
│ fallback;   │ │ FastAPI+    │ │ SKILL.md    │ │ serves both │
│ llama.cpp/  │ │ ChromaDB    │ │ memory      │ │ Odysseus &  │
│ mlx later   │ │ :8100, ntfy │ │             │ │ MCP search  │
│             │ │ :8091       │ │             │ │             │
└──────┬──────┘ └──────┬──────┘ └──────┬──────┘ └─────────────┘
       │               │               │
       └───────────────┴───────────────┘
         Odysseus & Hermes consume the runner's
         OpenAI-compatible endpoint as their LLM
```

Two layers of yours (Mission Control, Bridge) orchestrate four managed components. Everything crosses boundaries via HTTP, CLI invocation, or process spawning — never code linking. That single rule is what keeps your licensing freedom intact ([03_Licensing.md](03_Licensing.md)).

## Port map (canonical assignments — locked 2026-07-19)

*(Plain-language reminder: a port is an apartment number at your machine's internal address `127.0.0.1`; an endpoint is the full URL other programs call, e.g. `http://127.0.0.1:6767/v1`. See the basics section in [01_Vision_and_Decision.md](01_Vision_and_Decision.md).)*

| Port | Component | Notes |
|---|---|---|
| :6767 | Jan headless (`jan serve`) | `/v1` prefix; **DECIDED: the Bridge-managed canonical runner endpoint (primary).** |
| :1337 | Jan desktop API server | Settings → Local API Server → Start Server; **optional dual-mode "desktop tap"** the adapter can point at when headless is down or when Debi wants the desktop GUI (see §Runner slot → Dual-mode). Health-probed, not Bridge-managed. |
| :1234 | LM Studio server | Fallback runner. |
| :7860 | Odysseus (FastAPI: UI + API, single app) | `APP_PORT`/`APP_BIND` to override; binds 127.0.0.1 by default. Native Python — no Docker (decided). **Changed from :7000 (2026-07-20): macOS AirPlay Receiver squats :7000 — conflict caught in harness v1 (`harness.yaml` used 7860 for this reason).** |
| :8080 | SearXNG (shared) | One instance for Odysseus AND MCP search. Native from-source install — no Docker (decided). |
| :8091 | ntfy (Odysseus notifications) | Bundled with Odysseus. |
| :8100 | ChromaDB (Odysseus vector store) | Bundled with Odysseus. |
| (yours) | Bridge API | Whatever you've already assigned; keep it stable — Mission Control and future scripts depend on it. |

All components bind 127.0.0.1. Nothing listens on the network — which is also what keeps AGPL's network clause dormant ([03_Licensing.md](03_Licensing.md)).

## One-switch provisioning — the paramount requirement (declared 2026-07-20)

You declared this your #1 critical requirement, so it now sits above everything else in this document: **flipping a component's switch in Mission Control must AUTOMATICALLY install it AND connect it** — no terminal, no setup wizard, no manual config file. Verdict first, honestly: **yes, this is achievable for all four components plus SearXNG**, because every one of them has a scriptable install (git clone + venv + pip, or brew cask) and file-based config the Bridge can write directly (Hermes `~/.hermes/config.yaml`, Odysseus `.env`, SearXNG `settings.yml`). "Flip switch → installed + connected" concretely means: **toggle → dependency-ordered provisioning pipeline → config fan-out → health-verified green card.** The Bridge already does the first half (plan-and-approve installs — you installed Hermes this way); this section specifies the second half and makes the whole thing a first-class contract.

**The honest caveats (design around these, don't pretend they're absent):**

1. **The switch can't be *instant*.** First-run model weights are multi-GB downloads; SearXNG's pip install compiles wheels. The switch means "start the pipeline now, show live progress on the card, go green when verified" — never a frozen toggle. Progress UX is part of the requirement, not decoration.
2. **Jan needs one desktop-app first-launch** (verified 2026-07-20, see Research verification below): the `jan` CLI is installed *by the desktop app on its first launch* — there is no standalone CLI package. Scriptable workaround: `brew install --cask jan --no-quarantine`, then `open -a Jan`, wait for `/usr/local/bin/jan` (or `~/.local/bin/jan`) to appear, then quit the app. One window flashes once, ever; the plan dialog must say so. (Possible optimization to spike: the CLI binary may be symlinkable straight out of `Jan.app`'s bundle — unverified.)
3. **macOS Gatekeeper** on downloaded apps: `--no-quarantine` on the brew cask handles it (legitimate here — you approved the install in the plan dialog); without it, first launch needs a manual right-click-Open once.
4. **Models must exist before Hermes/Odysseus can go green** — a connected agent pointing at an endpoint with no loaded model is not "connected." Model acquisition is therefore a node in the dependency graph, not an afterthought.
5. **Upstream drift**: install steps and config schemas change. Mitigated by the existing pin/rollback machinery — the manifest pins a version, and "update" is an explicit re-run of the pipeline against a new pin, never a silent drift.
6. **API keys: none needed.** All five components run keyless against localhost (Hermes with `provider: custom` needs no key; Jan's `--api-key` is optional). If a future component demands one, the plan dialog must surface it as a labeled manual input — that's the one thing the Bridge can't conjure.

### The component manifest

Each managed component gets one declarative manifest the Bridge executes. Format: `name`, `source` (repo/package + pin), `install` (ordered steps), `config` (template the fan-out writer renders from central config), `depends_on`, `start`, `health` (liveness probe), `verify` (the deeper "actually connected" proof). The manifests for the five components, with real values:

```yaml
# ─── searxng.yaml ───
name: searxng
source: { type: git, repo: https://github.com/searxng/searxng, pin: <tag> }
install:
  - venv: create
  - pip: [pyyaml, msgspec, typing-extensions, pybind11]
  - pip: ["--use-pep517", "--no-build-isolation", "-e", "."]
config:
  path: <harness>/searxng/settings.yml
  template: { server.port: 8080, server.secret_key: "{{ random }}",
              limiter: false, search.formats: [html, json] }
depends_on: []
start: SEARXNG_SETTINGS_PATH=<path> python -m searx.webapp
health: GET http://127.0.0.1:8080/  →  200
verify: GET /search?q=test&format=json  →  200 with results array

# ─── jan-runner.yaml ───
name: jan-runner
source: { type: brew-cask, package: jan, pin: <cask version> }
install:
  - brew install --cask jan --no-quarantine
  - open -a Jan            # one-time: desktop app installs the CLI (labeled in plan dialog)
  - wait_for: path /usr/local/bin/jan OR ~/.local/bin/jan (timeout 120s)
  - osascript quit Jan     # window flashed once; done forever
config: {}                 # the runner receives nothing; it IS the endpoint
depends_on: [model-primary]          # weights before green
start: jan serve {{ models.primary }} --detach --port 6767
health: GET http://127.0.0.1:6767/v1/models  →  200
verify: POST /v1/chat/completions, 5-token reply streams back

# ─── model-primary.yaml ─── (an asset, not a process — see states below)
name: model-primary
source: { type: hf-repo, id: "{{ models.primary }}" }     # exact ID still open, see 04 §Decisions
install:
  - jan serve {{ models.primary }}   # side-effect: auto-downloads HF repo ID; progress parsed from CLI output
depends_on: [jan-runner.installed]   # needs the CLI present, not the server running
health: jan models list contains {{ models.primary }}

# ─── odysseus.yaml ───
name: odysseus
source: { type: git, repo: https://github.com/pewdiepie-archdaemon/odysseus, pin: <tag> }
install:
  - venv: create (python 3.11+)
  - pip: ["-r", "requirements.txt"]
  - run: python setup.py
config:
  path: <clone>/.env
  template: { LLM_HOST: "{{ runner.resolved_endpoint }}",       # http://127.0.0.1:6767/v1
              SEARXNG_INSTANCE: "http://127.0.0.1:8080",
              APP_PORT: 7860, APP_BIND: 127.0.0.1 }
depends_on: [jan-runner, searxng]
start: python -m uvicorn app:app --host 127.0.0.1 --port 7860
health: GET http://127.0.0.1:7860/  →  200
verify: one chat round-trip through the API; stretch: one DeepResearch
        query that provably hits the shared SearXNG

# ─── hermes.yaml ───
name: hermes
source: { type: git, repo: https://github.com/NousResearch/hermes-agent, pin: <tag> }
install:
  - venv: create
  - pip: install (as the harness already does today)
config:
  path: ~/.hermes/config.yaml        # written DIRECTLY — the setup wizard is never run (verified below)
  template:
    model: { provider: custom,
             base_url: "{{ runner.resolved_endpoint }}",
             model: "{{ models.primary }}" }
depends_on: [jan-runner]             # model loaded ⇒ transitively model-primary
start: hermes daemon (as today)
health: daemon process alive + hermes config check exits 0
verify: dispatch one trivial smoke task that must complete ≥1 tool call
        through the endpoint (tool-calling is the harness-wide mandate —
        a Hermes that can't tool-call is NOT connected)
```

### The dependency graph, and what one flip does

```
searxng ──────────────┐
jan-runner ── model-primary ──► odysseus
        └───────────────────► hermes
```

- SearXNG before Odysseus (DeepResearch is the point of Odysseus).
- Runner before Hermes and Odysseus connect (their configs embed `runner.resolved_endpoint`).
- Model weights before the runner's *verify* — and hence before any agent goes green.

**Flipping ONE switch resolves the whole subtree.** Toggle Odysseus ON from a clean slate and the Bridge computes the closure, then shows a single plan-and-approve dialog: *"Enabling Odysseus will also: install SearXNG (native, :8080), install Jan + CLI (one desktop window will open once), download the primary model (~XX GB), start the runner on :6767, then install and connect Odysseus. Approve?"* One approval, then the pipeline runs dependency-ordered with live per-node progress. Already-green dependencies are skipped (idempotency below). The dialog is the only human step — that's the requirement met.

### Component states (what the status card shows)

```
off → planned (approval dialog) → installing → installed
    → configuring → starting → verifying → ON (green)
                                     any step ✗ → needs-repair
                              runtime health-loss → degraded
```

| State | Card shows |
|---|---|
| `off` | Grey card, toggle off. |
| `planned` | The approve dialog is up; card pulses "awaiting approval". |
| `installing` | Live step + progress ("cloning… / pip 34% / downloading model 12.4 of 19 GB"). |
| `installed` | Momentary; bits on disk, nothing configured yet. |
| `configuring` | "writing config.yaml…" — the fan-out writers rendering templates. |
| `starting` | Process spawned, waiting on first health 200. |
| `verifying` | Health passed; running the deeper `verify` probe (the tool-call task, the search round-trip). |
| `ON` | Green. Version pin, endpoint, last-verified timestamp. |
| `degraded` | Was green, health now failing; adapter retry/fallback running (cf. dual-mode runner). Amber. |
| `needs-repair` | Pipeline failed; card names the exact failed step + stderr tail, offers **Repair**. Red. |

`model-primary` is an *asset*, not a process: its states collapse to `off → downloading → present`, and it has no health loop — only an existence check.

### Idempotency & repair (the rules)

1. **Every step is check-then-act.** Clone exists at pin? skip. Venv healthy? skip. Config file content-identical to rendered template? skip. Health already green? skip the whole node. Re-flipping a green switch is a no-op that just re-verifies.
2. **Partial failure keeps completed steps.** Failure at step N leaves 1..N−1 done; **Repair** re-enters the pipeline *at N*, not from scratch. (Full re-provision stays available behind an explicit "Reinstall" verb.)
3. **Config is regenerated, never patched.** The fan-out writer owns the managed files wholesale (or owns a clearly-marked managed block, if you ever need manual sections — rule 2 of the API boundaries).
4. **OFF means stop, not uninstall.** Flipping off stops the process and greys the card; bits and config stay. "Uninstall" is a separate deliberate verb.
5. **Version changes re-run the pipeline** against the new pin, with rollback = re-run against the old pin. Provisioning and pin/rollback are the same machinery, on purpose.

### Research verification (2026-07-20, sources cited)

**(a) Can Hermes be fully configured by writing `~/.hermes/config.yaml`, bypassing the wizard? — YES.** The [configuration docs](https://hermes-agent.nousresearch.com/docs/user-guide/configuration/) confirm `config.yaml` is the single source of truth and that setting `model.base_url` makes Hermes "ignore the provider and call that endpoint directly"; `provider: custom` + `base_url` is the documented path for OpenAI-compatible local endpoints, with `api_key` optional (falls back to `OPENAI_API_KEY`; local endpoints accept none). Non-interactive validation exists: `hermes config check` / `hermes config migrate`. Corroborating: [issue #41046](https://github.com/NousResearch/hermes-agent/issues/41046) complains the `hermes setup` wizard *can't* skip the Nous Portal flow — and the acknowledged workaround is exactly ours: don't run `hermes setup` at all; write `config.yaml` directly. So the Bridge never invokes the wizard, ever.

**(b) Can Jan be installed AND run headless purely via CLI/brew, never opening the desktop app? — NO, with a cheap workaround.** The [Jan CLI docs](https://www.jan.ai/docs/desktop/cli) state plainly: "Jan CLI is installed automatically when you launch the Jan desktop app for the first time" (to `/usr/local/bin/jan` or `~/.local/bin/jan`); the [brew cask](https://formulae.brew.sh/cask/jan) installs the desktop app bundle, not a CLI. There is no standalone CLI package. Additionally, per-model inference settings come from `router.preset.ini` *generated by the desktop app* — CLI tuning flags are currently ignored in router mode. Workaround (fully scriptable, one-time): brew-cask install → `open -a Jan` → wait for the CLI binary → quit. The plan dialog labels it: "a Jan window will open once during install." After that, headless-only forever.

## Component responsibilities

### Mission Control (Swift, yours)
- The **only window**. Dark editorial UI: serif headlines, mono small-caps labels, cream-and-gold on near-black.
- Status cards per component (running/stopped/error, version/pin, health), metric tiles (components running, disk free), activity feed, ⌘K command palette with cross-component verbs, plan-and-approve install dialogs.
- **M2 flagship: the native model browser.** Queries the HF API directly for discovery (search, sizes, quants, hardware-fit computation against your 64GB), renders in your aesthetic, and triggers downloads *through the Bridge's runner adapter* — so it works identically whichever runner is active. This beats LM Studio's browser on both axes you care about: aesthetics and runner-agnosticism.
- **Odysseus tab**: `http://127.0.0.1:7860` in a WKWebView. Don't rebuild its UI; chrome it.

### Bridge (local server, yours)
- Lifecycle: clone/update managed repos with **git pin/rollback** (already built), create venvs, install deps, spawn/stop/monitor processes, aggregate health.
- Config fan-out: single source of truth for ports, endpoints, model defaults, and the shared-SearXNG URL; writes each component's native config format (Odysseus `.env`, Hermes `config.yaml`, MCP `mcp.json`).
- Permission broker for install/update actions (surfaced as Mission Control's plan-and-approve dialogs).
- **Runner adapter layer** — the interface below.

### Runner slot (swappable; Jan today)
The one interface that permanently dissolves "Jan vs. LM Studio":

**Runner-slot interface contract (what any runner must provide):**
1. **Inference:** an OpenAI-compatible endpoint (`POST /v1/chat/completions`, streaming, tool calling).
2. **Catalog:** a model-list API (`GET /v1/models`).
3. **Acquisition:** a *mechanism* the Bridge can drive to download a model by HF repo ID. Note: this is deliberately "mechanism," not "HTTP API" — see the Jan findings below.
4. **Lifecycle:** a way for the Bridge to start/stop it headlessly and health-check it.

**Adapter: Jan (primary).** Verified findings (2026):
- Jan ships a real CLI since v0.7.8, auto-installed by the desktop app to `/usr/local/bin/jan` or `~/.local/bin/jan`. `jan serve [MODEL_ID]` exposes a model at `localhost:6767/v1`, with `--port`, `--api-key`, and `--detach` for background daemon use. Also `jan launch`, `jan models`, `jan threads`. ([jan.ai/docs/desktop/cli](https://www.jan.ai/docs/desktop/cli))
- The desktop app's own API server is a settings toggle, default `127.0.0.1:1337/v1`, OpenAI-compatible plus an Anthropic-compatible `/v1/messages`. ([jan.ai/docs/desktop/api-server](https://www.jan.ai/docs/desktop/api-server), [api-preference](https://www.jan.ai/docs/desktop/api-preference))
- **There is no HTTP download endpoint** — the old Cortex `/v1/models/pull` died when Jan moved off Cortex to direct llama.cpp integration in v0.6 ([janhq/jan#4941](https://github.com/janhq/jan/issues/4941)). But `jan serve <org>/<repo-GGUF>` **auto-downloads any HuggingFace repo ID** — so the Bridge's Jan adapter implements "acquisition" as a CLI invocation, with progress parsed from CLI output. Clean and sufficient.
- Fallback acquisition: drop files into the data folder — `<Jan data>/llamacpp/models/<org>/<repo>/model.gguf` + `model.yml` (MLX under `mlx/models/<model_id>/`); data folder at `~/Library/Application Support/Jan/data` on macOS ([jan.ai/docs/desktop/data-folder](https://www.jan.ai/docs/desktop/data-folder)). Whether a bare GGUF without `model.yml` is picked up is unverified — prefer the CLI route.
- CLI and desktop share one data folder; since v0.8.0 llama-server runs in "router mode" with per-model settings in `<data>/llamacpp/router.preset.ini` generated by the desktop app. Practical consequence: **configure model settings once in desktop Jan; headless serving inherits them.**
- **DECIDED (2026-07-19): the Bridge manages `jan serve --detach` on :6767 as the canonical endpoint — with an OPTIONAL desktop tap (:1337) selectable via `runner.mode` (headless | desktop | auto).** In plain terms: Jan can run two ways — as a windowed desktop app (whose optional API server lives on :1337) or as an invisible background server with no window (`jan serve`, :6767). Headless is primary; the dual-mode adapter (see below) can borrow the desktop endpoint when it's already open or when Debi overrides. Either way the engine stays silent-by-default and the only window Debi *must* see is Mission Control. "Headless" literally means "no head" = no UI.

**Dual-mode Jan: headless primary + optional desktop tap (designed 2026-07-19).**

You wanted the *option* for the runner to tap the running desktop Jan (:1337) instead of always spawning headless (:6767). This is a clean fit because both speak the identical OpenAI wire protocol — so it lives entirely *inside* the Jan adapter and nothing above the adapter ever notices. The abstraction from boundary rule #4 ("the runner is anonymous above the adapter") is preserved exactly: Odysseus, Hermes, Mission Control, and MCP hosts all still receive one opaque endpoint URL from Bridge config; only the adapter knows whether that URL is :6767 or :1337 today.

*Why tap the desktop endpoint sometimes:*
- The desktop app is already open, so the model is already loaded in RAM — spawning a second headless server would double the memory footprint for the same weights.
- Per-model settings, MLX tuning, and the `router.preset.ini` are authored in the desktop GUI; tapping :1337 uses those live rather than relying on headless inheriting them.
- You want to *watch* a conversation happen in Jan's own chat window while the harness drives it — useful for debugging tool-call formatting.

*How the Bridge picks (one small resolution function, evaluated at endpoint-resolve time and on health-loss):*
1. **`runner.mode` config toggle** with three values: `headless` (always :6767, spawn if needed — the default), `desktop` (always :1337, never spawn — user override for "use what's on my screen"), and `auto`.
2. In **`auto`**: **prefer headless.** If a Bridge-managed `jan serve` is already healthy, use it. Else health-probe the desktop endpoint (`GET :1337/v1/models`, ~300ms timeout); if the desktop app is up, tap it and skip spawning. Else spawn headless (`jan serve --detach`) and use :6767. This means "if the desktop app is open, borrow it; otherwise run the silent one" — no double-loading, no manual toggling.
3. **Health fallback (both non-auto modes benefit):** if the active endpoint fails a health check mid-session, the adapter re-runs resolution once (headless death → try desktop; desktop quit → spawn headless) before surfacing an error to the status card. The runner status card shows which of the two is live (`Jan · headless :6767` vs `Jan · desktop :1337`).

*Acquisition note:* model download stays a **headless-only capability** — `jan serve <hf-repo>` via CLI, unaffected by which endpoint is currently serving inference. If mode is `desktop`, downloads still shell out to the CLI (which writes into the shared data folder the desktop app reads). One data folder, so a model pulled either way is visible to both.

*Tiny config example (Bridge central config):*
```toml
[runner]
adapter = "jan"
mode    = "auto"        # headless | desktop | auto
[runner.jan]
headless_endpoint = "http://127.0.0.1:6767/v1"
desktop_endpoint  = "http://127.0.0.1:1337/v1"
health_timeout_ms = 300
prefer            = "headless"   # tiebreak in auto mode
# components receive runner.resolved_endpoint, never these raw fields
```
The fan-out writers still emit one URL (`runner.resolved_endpoint`) into Hermes's `config.yaml` and Odysseus's `.env`; flipping `mode` re-resolves and re-fans-out, so switching between headless and desktop is a one-line change with everything downstream following — the same property the runner slot gives you for Jan-vs-LM-Studio, now one level finer.

**Adapter: LM Studio (fallback).** OpenAI endpoint on :1234; `lms` CLI for headless load/serve and `lms get` for downloads; mature MCP host. Keep the adapter thin; you only need it when Jan regresses (its MLX backend is young — e.g., issue #7804-era regressions).

**Adapter: bare llama.cpp / mlx (later, optional).** `llama-server` already satisfies (1),(2); acquisition via `huggingface-cli`. Only worth building if you want to shed the Jan dependency for specific models.

### Odysseus (managed component, MIT)
- Synchronous workspace + **DeepResearch** via SearXNG, using an adapted Tongyi DeepResearch pipeline (Apache-2.0 origin).
- Verified run details: plain Python (3.11+): `pip install -r requirements.txt; python setup.py; python -m uvicorn app:app --host 127.0.0.1 --port 7860`. (Upstream also offers docker compose — **not used here**; see decision below.) Single FastAPI app serves UI and API on :7860. ([odysseus docs/setup.md](https://github.com/pewdiepie-archdaemon/odysseus/blob/main/docs/setup.md))
- **`SEARXNG_INSTANCE` env var** points it at an external SearXNG (default `http://localhost:8080`) — this is what makes the shared-SearXNG plan officially supported, not a hack. Model endpoint via `LLM_HOST` / `LLM_HOSTS` (discovery list), plus `RESEARCH_LLM_ENDPOINT`, `EMBEDDING_URL`/`EMBEDDING_MODEL`; most provider config is done in its in-app Settings UI. ([.env.example](https://github.com/pewdiepie-archdaemon/odysseus/blob/main/.env.example))
- **DECIDED (2026-07-19): native Python via the Bridge's existing venv machinery — no Docker.** Debi has ruled Docker out harness-wide. Bridge writes its `.env` from central config. UI embedded as a Mission Control webview tab. Note: Odysseus's docker-compose bundle would have brought its own SearXNG/ntfy/ChromaDB containers; running native means the Bridge (not compose) is responsible for the sidecars — SearXNG is covered below; ntfy/ChromaDB install natively via pip/binary and are already 127.0.0.1-only.

### Hermes (managed component, MIT)
- NousResearch's async, self-directed coding-agent daemon: reads codebases, edits files, runs commands, plans multi-step tasks, writes reusable SKILL.md skills it remembers.
- Verified config details: `hermes model` is the interactive provider wizard; "Custom endpoint" supports any OpenAI-compatible base URL. `~/.hermes/config.yaml` is the single source of truth (`model: { provider: custom, base_url: http://localhost:6767/v1, ... }`); the old `OPENAI_BASE_URL`/`LLM_MODEL` env vars were removed. LM Studio is a named provider; **Jan at :1337/v1 is explicitly in its compatibility table**. ([hermes-agent providers doc](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/integrations/providers.md))
- **Tool calling is required — now a locked harness-wide rule:** the primary model MUST support tool calling (Hermes and every MCP tool depend on it); non-tool-calling models are disqualified as primary. Wire-format notes: vLLM needs `--enable-auto-tool-choice --tool-call-parser hermes`, llama-server needs `--jinja`, LM Studio 0.3.6+ — otherwise tool calls come back as raw text. ([04_Roadmap.md](04_Roadmap.md) §Decisions.)
- Being MIT, Hermes is the one component whose *patterns and code* you may freely lift into your own layers — notably the SKILL.md conventions.

### SearXNG (shared infrastructure, AGPL)
- One instance on :8080 serving both Odysseus DeepResearch and an MCP web-search server for chat clients. Bridge-managed like everything else. Why shared: one process to supervise instead of two, one config, less RAM, and both consumers see identical search behavior.
- **DECIDED (2026-07-19): native from-source install — no Docker.** SearXNG is a plain Python app; Docker is merely its most-advertised packaging. The native path fits the Bridge's existing git+venv machinery exactly:
  1. `git clone https://github.com/searxng/searxng` (Bridge pin/rollback as usual);
  2. venv + `pip install --use-pep517 --no-build-isolation -e .` (plus `pyyaml`, `msgspec`, `typing-extensions`, `pybind11` first);
  3. write a `settings.yml`: set `server.secret_key`, `server.port: 8080`, **`limiter: false`** (localhost-only, and it avoids the Valkey/Redis dependency), and add **`json` to `search.formats`** — required so Odysseus/MCP can consume results via the JSON API, not just HTML;
  4. run `SEARXNG_SETTINGS_PATH=<path> python -m searx.webapp` as a Bridge-supervised process. ([docs.searxng.org — step-by-step installation](https://docs.searxng.org/admin/installation-searxng.html))
- **Honest cost of going Docker-free here: moderate, not painful.** Caveats, plainly: (a) SearXNG is not on PyPI — you install from a source clone, which the Bridge already does for every component; (b) the official step-by-step guide is Linux/uWSGI-flavored (system user, uwsgi service) — skip all of that; `python -m searx.webapp` is the built-in single-process server, documented as a "check" mode but entirely adequate for one local user; (c) updates = git pull + reinstall = the Bridge's normal pin/rollback flow; (d) a de-risking spike is listed in [04_Roadmap.md](04_Roadmap.md) to confirm the pip install builds cleanly on macOS/arm64.
- Fallback if native ever proves fiddly: temporarily point `SEARXNG_INSTANCE` and the MCP server at a public SearXNG instance (privacy tradeoff: queries leave the machine; public instances also often disable the JSON format). Docker stays off the table.

## Data & API boundaries (the rules)

1. **Your code never imports their code.** HTTP, CLI, process spawn only.
2. **The Bridge owns config; components receive it.** One central config → fan-out writers for `.env` / `config.yaml` / `mcp.json`. Never hand-edit a component's config that the Bridge manages (or teach the Bridge to preserve manual sections).
3. **Upstream repos are read-only clones under pin/rollback.** Local patches, if ever needed, live as git-managed diffs the Bridge can reapply after updates.
4. **The runner is anonymous above the adapter.** Mission Control and every managed component see only "the endpoint" (URL from Bridge config). Nothing outside the adapter may know it's Jan.
5. **Skills are shared, state is not.** One SKILL.md corpus can serve LM Studio's skills plugin and Hermes ([05_Reference_and_Learnings.md](05_Reference_and_Learnings.md)); but each component keeps its own runtime state (threads, vectors, memory) in its own data dir.

---

*Next: [03_Licensing.md](03_Licensing.md) for why these boundaries also solve the license question; [04_Roadmap.md](04_Roadmap.md) for build order.*
