# New Harness — working memory (canonical project home)

> For Claude: read this first, then `00_START_HERE.md` (its primer paragraph rehydrates a fresh session). This folder is the **single source of truth** for the harness project as of 2026-07-20. The copies of 00–06 in the old `outputs` folder are frozen; the v1 codebase lives in the `Harness project` folder (working scaffold — see 07).

## Repo

- **GitHub: https://github.com/Debkbas/new-harness (private) — the single source of truth.** `./harness/` is the local clone; `main` pushed 2026-07-20 (`c11f049`: v1 scaffold + v2 doc set in `docs/handoff/`).
- **Sync rule:** the .md files at this folder's root are working copies; any doc change must be copied into `harness/docs/handoff/` and committed. When in doubt, the repo wins.
- **Auth:** push with a GitHub PAT supplied per-session in chat — never store it in any file or remote URL (`git remote` stays tokenless). Debi: revoke the 2026-07-20 token after this session.
- **Migration trap from the sandbox session:** the cowork sandbox cannot unlink files in this folder, so git left stale `*.lock` files (`.git/HEAD.lock`, `.git/objects/maintenance.lock`, submodule `index.lock`s). If git on the Mac refuses to commit, delete those lock files first — they are safe to remove when no git process is running.

## Doctrine

`agent-kit/DELEGATION-DOCTRINE.md` applies to this project in full, with **one amendment (2026-07-20): all UI design / look-and-feel work is Fable 5 only** — builder subagents may implement UI solely from a Fable-authored, decision-free spec. See `08_Interface_Strategy.md` §Governance.

## ⚠️ FABLE-5 CONTINUITY / HANDOFF RULE (critical — Debi 2026-07-20)

If Fable 5's context/token runs out mid-work, the ONLY model that may pick this up is **Opus 4.8 (high reasoning)** — not Sonnet, not any other model. Whoever continues MUST follow this rule so nothing is lost or invented:
- **Do FUNCTION only, never new look-and-feel.** Build/finish features in the EXISTING editorial design system already in `bridge/panel/index.html` (the `:root` vars, serif/mono/cream/gold, restrained, consistent). Apply the established language; do NOT author new colors, layouts, type scales, or "styles inspired by X". That is Fable's job.
- **Leave a marker, don't guess.** Where a real aesthetic decision is needed, ship the working function in the plainest in-system form and add a `<!-- FABLE: style this -->` note (or a CLAUDE.md TODO) for Fable to refine when back. Never block a feature on styling.
- **Aesthetic references Debi likes (for the Fable pass, NOT to copy):** OpenAI chat, Odysseus, Cherry Studio (CherryIn), Jan AI, LM Studio. Fable authors a decision-free spec from these; builders implement.
- Everything else (backend, proxies, wiring, Bridge, scripts) is normal engineering — any model proceeds per the delegation doctrine (read code, one evidenced hypothesis, no trial-and-error).

## Active roadmap (agreed with Debi 2026-07-20, in order)

1. **Chat-pane polish** (in progress): session **duplicate** (DONE below), **attach file**, **in-chat model picker**. NOTE: the model picker is intentionally deferred to land WITH the Models pane (step 2) — it only does something once >1 model exists to pick.
2. **Models pane** (promotes old M2 "gearbox/model browser"): the real gap — the harness has NO model UI today (the sidebar "Models" entry is a stub `alert('Gearbox lands in M2')`). Build list / switch / **download** + runner fan-out. Design (Debi): "best of both worlds" — click a model → an **LM-Studio-style detail page** (HuggingFace model card/README + download options with quant/size + a fit indicator like "Full GPU Offload Possible") PLUS **Jan-hub-style fit pills** ("Fits / May be slow / Won't fit"). **Open design question (Debi undecided, fine either way):** do this as a **Models pane in Mission Control** (default plan — expose Jan's *capability*, don't clone Jan) OR add a dedicated **Jan tab** like the Odysseus/Hermes tabs. Decide when building; leaning Models pane to avoid over-meshing.
3. **jan-browser-mcp** wired into Hermes/Odysseus (+ a "Browse" toggle button in the Chat pane, agent or chat). It's a Chrome extension running a tiny local server (:8181) exposing browser control **as an MCP server** — so we register it as an MCP for Hermes/Odysseus (both speak MCP); the user installs the extension once. Compose, don't fork.
4. **Fable visual pass** on the chat/session rail + panes (references above).
5. **(M5, later) parallel-worktree orchestrator** — maps onto Hermes's existing `delegate_task` tool + worktree-aware terminal backends; one orchestrator dispatching agents across git worktrees, then merging. On-brand, advanced.

## Models pane — confirmed Jan CLI surface + build plan (2026-07-20)

**Jan CLI facts (from official docs, jan.ai/docs/desktop/cli — CLI is v0.7.8+, we have 0.8.3):**
- `jan models list` — list installed models (in the shared Jan data folder; desktop + CLI share it).
- `jan models load <id>` — alias for `jan serve <id>`.
- `jan serve <MODEL_ID>` — MODEL_ID can be a local id OR a **HuggingFace repo id** (e.g. `unsloth/Qwen3.5-9B-GGUF`); **if not downloaded, Jan auto-downloads from HF then serves.** → this IS our download path (no separate `jan pull`). Downloading a new model = `jan serve <hf-repo>` (which also makes it active). We already run `jan serve <model> --port 6767 --api-key … --detach` as the runner.
- Since Jan 0.8.0 llama-server runs in **router mode**; `--ctx-size/--n-gpu-layers/--fit` are **ignored** — per-model context comes from `<data-folder>/llamacpp/router.preset.ini` (desktop-authored). (Matches our M1 finding: preset forced 95536.)
- HF model browser (LM-Studio-style detail): use the HuggingFace public API — `GET https://huggingface.co/api/models?search=<q>&filter=gguf&sort=downloads&limit=N` (list) + `GET /api/models/<repo>` (files/siblings → quant/size) + `…/<repo>/raw/main/README.md` (model card). Fit pill = model file size vs the box's 64 GB. The Bridge runs on the Mac (real internet) so it can call HF; the cowork sandbox CANNOT (network locked) → HF/jan shapes must be spiked on the Mac.

**Build plan (slices, each Mac-verified like M0/M1):**
- **Slice 1 — model view + switch.** Bridge: `GET /api/models` (shell `jan models list` → installed; active = `runner.model` in harness.yaml; running state) and `POST /api/models/switch {id}` (write `runner.model`, restart runner, then RE-FAN-OUT to Hermes+Odysseus — their configs bind the model *name*, so a switch must re-patch `~/.hermes/config.yaml` + re-seed Odysseus, i.e. restart those components too). Models pane replaces the sidebar stub `alert('Gearbox lands in M2')`.
- **Slice 2 — HF browser + download.** Search → results → LM-Studio-style detail (card + quant/size + fit pill) → "Download & Load" = `POST /api/models/switch` with an HF repo id (jan serve auto-downloads). Jan-hub-style fit pills alongside.
- **Slice 3 — Fable visual pass** on the pane.
- **Open question (Debi, either OK):** Models *pane* in Mission Control (default) vs a dedicated *Jan tab*. Leaning pane.

**SPIKE DONE (2026-07-20) — confirmed output shapes:**
- `jan models list` → **JSON array**, fields per model: `id`, `name` (pretty), `size_bytes`, `engine` ("llamacpp"), `embedding` (bool), `capabilities` ([]), `model_path`, `mmproj_path`. (jan 0.8.3.)
- runner `GET :6767/v1/models` → `{data:[{id, status.value:"loaded", architecture.input_modalities:["text","image"], meta.n_ctx, meta.size, …}]}`. **Current model IS vision-capable** (text+image, mmproj present) → image attach viable later.
- HF `GET /api/models?search=…&filter=gguf&sort=downloads&limit=N` → array of `{id (repo), name/modelId, downloads, likes, tags[], pipeline_tag, createdAt}`. (Works from the Mac Bridge; sandbox network is locked so HF/jan can't be tested in cowork — Mac-verify.)

**Concurrent-download answer (Debi asked):** `jan serve <hf-repo>` = download+load+serve ONE active model (no separate `jan pull`). So you can't parallel-download 2-5 that way (port + 64 GB + single-active). Plan: slice-2 download = serial "Download & Load" (switch runner to it). A **parallel download queue** (Bridge fetches GGUFs straight into `~/…/Jan/data/llamacpp/models/<id>/` with progress, no load) is an explicit later enhancement (Debi agreed).

**Slice 2 CODE DONE (Mac-verify pending, 2026-07-21):** HF browser in the Models pane. Bridge `GET /api/models/hf?q=` (HuggingFace search, filter=gguf, sort=downloads) + `GET /api/models/hf/files?repo=` (tree/main → .gguf files + sizes, for fit pills). Panel: "Download a model" search box → results (repo · downloads · likes · pipeline) → per-result **Files & fit** (expand → gguf list with fit pills: Fits <55% / May be slow <90% / Won't fit, vs 64 GB), **Download & Load** (two-step confirm — WKWebView has no `confirm()`; reuses `switchModel(repo)` → jan serve auto-downloads+loads), **Model card ↗** (opens HF via /api/open). `<!-- FABLE: style this -->` — LM-Studio/Jan/Cherry are the reference feel. **Known caveats:** (1) large first-download can exceed the runner's ~90s readiness wait in start_component.sh → status may show a timeout while jan keeps fetching in the background (fix later: longer wait during download, or the parallel download-queue). (2) `jan serve <repo>` lets Jan pick the quant; per-file quant selection is a later refinement.

**Slice 2b CODE DONE (Mac-verify pending, 2026-07-21):** per Debi feedback — (1) **in-app model card**: `GET /api/models/hf/card?repo=` fetches the README (front-matter stripped, 20k cap), rendered in-pane with a light safe markdown renderer (`mdCard`: images dropped, links → openExt); "Model card" button toggles it inline (no more browser bounce), "HF ↗" kept as secondary. (2) **Sort** dropdown: Most downloaded / Most recent (lastModified) / Best match (relevance). (3) **Format** dropdown: GGUF / MLX — `hf_search` passes `filter` + `sort`+`direction`; `hf_files` now handles MLX repos (.safetensors → one summed-size model + fit pill) as well as GGUF (per-file pills). JS validated with `node --check`.

**Slice 1 CODE DONE (Mac-verify pending, 2026-07-20):** Bridge `GET /api/models` (`jan models list` JSON → installed; active = `runner.model`; runner_up), `POST /api/models/switch {id}` (writes runner.model via line-scan, background thread restarts runner + re-fans-out to Hermes/Odysseus IF running — their configs bind the model name), `GET /api/models/switch-status` (poll). Panel: sidebar "Models" stub replaced → `#view-models` pane lists installed models, marks the live one, Switch button (disabled on active), progress via switch-status poll. `id` may be a local id OR an HF repo id (slice 2 uses that for download). Panel-only + bridge → bridge restart, no app rebuild. `<!-- FABLE: style this -->` marker left on the pane.

## Research findings feeding the roadmap (2026-07-20, web-verified)

- **Jan model management IS exposeable.** Jan is OpenAI-compatible; the **`jan` CLI (v0.7.8+)** can start the server, **list models, and manage config**; GUI-downloaded models are auto-available to the CLI. Jan's model hub shows fit pills + quant tiers. Caveat to spike before building step 2: whether headless `jan serve` on :6767 exposes download/hub endpoints, or whether **download must go via the `jan` CLI / Jan's management API** (either works, changes plumbing only).
- **jan-browser-mcp** = Chrome extension + tiny local server (:8181), browser automation (click/type/navigate/screenshot/a11y-tree/extract) exposed as MCP. Fits our MCP-native components directly.
- **cate** (github.com/0-AI-UG/cate, MIT): Electron infinite-canvas IDE (editor/terminal/browser/agent panels, git-worktree sidebar, per-chat model memory). Different app class (Electron/React) → **inspiration only**, not a dependency. Borrow: in-app browser panels, worktree UI, per-chat model memory (pairs with the per-session model picker).
- **Odysseus endpoints discovered** (for the proxy, all under `/api`): sessions `GET /api/sessions`, create `POST /api/session`, rename `PATCH /api/session/{id}` (form `name`), delete `POST /api/session/{id}/delete`, **fork/duplicate `POST /api/session/{id}/fork`** (json `{keep_count}` → returns `{id,name,kept}`), history `GET /api/history/{id}`, **models `GET /api/models`** (per-user, cached), per-session model switch via `PATCH /api/session/{id}` (form `model`+`endpoint_id`).

## Doc map

| File | Contents |
|---|---|
| 00–06 | The handoff set (corrected: Jan = Apache-2.0, Odysseus = MIT, Odysseus port = **:7860** not :7000 — AirPlay conflict). |
| 07_Salvage_from_v1.md | v1 review: verdict (v1 = this project's scaffold, not a failed project), keep/reject lists, stall post-mortem. |
| 08_Interface_Strategy.md | Interface direction: reskin webview → deep-link tabs → native panes ladder; Fable-5-only UI rule. |
| mcp*.json, Top-40, LM-Studio guide | Config inventory (05 §5). |

## State (2026-07-20, later — M1 core done)

- **M1 runner slot + fan-out DONE (verified).** The Bridge manages headless **Jan on :6767** as a "Runner" component (panel card, start/stop/health). `jan serve <model> --port 6767 --api-key <key> --ctx-size <ctx> --detach`; stop-by-port. Both components repointed to the runner and verified with **desktop Jan OFF**: Hermes `test_hermes.sh` = PASS, Odysseus chat replies (~74 tok/s). Harness is now self-contained — no desktop app needed. Repo tip `1cf7f3e`.
- **Single source of truth for the model endpoint:** the `runner:` block in harness.yaml (endpoint + api_key + model + ctx_size). Hermes start patches `~/.hermes/config.yaml` model.{default,provider,base_url,api_key,context_length}; Odysseus start runs `seed_odysseus_jan.py` (upserts the `local-jan` endpoint by stable id + sets default model). `inference.hermes_llm` removed.
- **One-switch pipeline slice 1 DONE (verified 2026-07-20):** dependency-aware start. `depends_on: [runner]` on hermes/odysseus; Bridge resolves the closure (`start-plan` endpoint), and POST start brings up the whole chain in order (skipping running, stop+report on first failure). Panel shows a single plan→approve dialog when a dep must come up (verified: stopping all then Start Odysseus → dialog lists runner+odysseus → Approve → both green). Repo tip `8562b81`.
- **One-switch pipeline slice 2 DONE (verified 2026-07-20):** live per-step progress. POST start runs the closure in a background thread, publishing per-component state (pending/starting/on/failed/blocked) into `PROV`; `/status` exposes it; the panel animates cards live (Starting…/Failed with colored dots), logs transitions to the feed, adaptive-polls (1.5s provisioning / 6s idle), and a failed step shows Retry + View-log. Verified: stop all → Start Odysseus → runner "starting…"→"online"→odysseus "starting…"→"online" live. Repo tip `ed2748a`.
- **One-switch pipeline slice 3 DONE (verified 2026-07-20):** degraded-state detection. An "expected up" marker (`data/<name>.expected`) is written on successful start, cleared on explicit Stop; `/status` reports `degraded = expected-up AND health failing`. Panel shows red "Degraded" with Restart/Stop + a `health` feed note. Verified: kill runner by port → card flips to Degraded → Restart → starting…→online. State machine now distinguishes Stopped (intentional) from Degraded (crashed).
- **M1 one-switch pipeline: essentially COMPLETE** (slices 1–3: dependency-aware start + single approval, live per-step progress, degraded detection + recovery). Optional future refinements, not blocking: install-time closure (flip an *uninstalled* component → install deps too), cross-dependency health cascade (mark Odysseus/Hermes degraded when the runner they depend on dies — currently only the runner's own health is tracked), and the model-download node (folds into M2's model browser).
- **New M1 failure archaeology:** seed matched the endpoint by `base_url`, but with a fixed id — when the URL changed (:1337→:6767) it tried to INSERT a duplicate id → PK collision → silent rollback → Odysseus stuck on the dead :1337 (Error 503). FIX: match by stable id, update in place (`1cf7f3e`).

## State (2026-07-20)

- **Code moved: the scaffold now lives at `./harness/`** (git repo + vendor submodules intact; `data/` venvs and `dist/` were regenerated on the Mac via `./scripts/bootstrap.sh`). The old `Harness project` folder is a frozen archive.
- **M0 COMPLETE (verified 2026-07-20).** Both components green under the Bridge (:8700), each proven end-to-end:
  - **Hermes** green via `hermes serve` :9119; `scripts/test_hermes.sh` = `PASS` (real shell tool call through Jan).
  - **Odysseus** green :7860; real chat reply from `Qwen3_6-35B-A3B-…-IQ4_XS` @ Jan :1337, ~60 tok/s. One-button install AND connect from the panel (admin/admin123; Jan endpoint auto-seeded as default model via `scripts/seed_odysseus_jan.py`).
  - Latest repo tip: `4c0ffba`. Odysseus pin bumped to `e57f60bd` (old `168f5930` had a chat NameError).
- All licensing verified from LICENSE files: Hermes MIT, Odysseus MIT, Jan Apache-2.0; only SearXNG is AGPL.

## M2 interface — slice 1 DONE (verified 2026-07-20)

- **Native tabbed Harness.app is the one window.** `app/main.swift` rebuilt: standard titled window + a segmented tab strip (Mission Control :8700 / Odysseus :7860), two persistent WKWebViews, Odysseus lazy-loaded on first select. Each tab is a **top-level** load — sidesteps Odysseus's `X-Frame-Options: DENY` / `frame-ancestors none` (middleware.py:108), which make iframing impossible. Built with swiftc 6.3 via `./scripts/build_app.sh`; verified: login (admin/admin123, the app's WKWebView has its own cookie store), chat replies ~75 tok/s. Repo tip `943e8ec`.
- **Web/internet note:** the local model has NO internet (Chat mode = training-data answers). Odysseus's web comes from `web_search`/`web_fetch` agent tools + Deep Research, active only in **Agent mode** (the Agent|Chat toggle by the input). Backend: `search_provider: searxng` (:8080, NOT installed yet) with automatic **duckduckgo fallback** (`ddgs`, installed) — so Agent mode already works via DDG; native SearXNG is the better shared backend (planned).

## M2 slice 2a DONE (verified 2026-07-20)
- Dark tab bar (`window.appearance = .darkAqua` + near-black strip in `app/main.swift`). Sidebar Components entries clickable → scroll-to-card + gold highlight (`jumpToCard`, cards get `id=card-<name>`). Repo tip `85d2ca6`.
- **macOS gotcha (recorded):** `open dist/Harness.app` re-focuses a running instance instead of relaunching the new build — must `pkill -x Harness` first. This masked the change once.

## M2 slice 2b DONE + design findings (2026-07-20)
- Injected a "Harness skin" `WKUserScript` into the Odysseus web view (`app/main.swift`) overriding `--font-family` (unset → Fira Code mono everywhere) to a sans stack; code blocks keep explicit Fira Code. Colors left to Odysseus's Theme editor. Repo tip `bd61553`.
- **"Premium vs ordinary" diagnosis (Debi's observation; keep for Rung D native panes).** What makes Mission Control / Jan / LM Studio / Cherry feel premium and Odysseus feel ordinary, in 4 levers: (1) **typographic hierarchy** — big serif display title + small mono small-caps labels + body; Odysseus is typographically flat (uniform size/weight). (2) **colour restraint** — one accent (gold) used sparingly on neutral; Odysseus paints coral everywhere (biggest "cheap" tell). (3) **whitespace** — generous breathing room vs Odysseus's dense, border-on-everything layout. (4) **serif+sans pairing** — the editorial signature. **Decision: do NOT chase pixel-parity via fragile injected CSS (tripwire).** True parity = Rung D native panes over Odysseus's API in our aesthetic — a deliberate future milestone.

## SearXNG DONE (verified 2026-07-20) — full architecture diagram now live

- **Native SearXNG installed, managed, and verified serving Odysseus.** `scripts/install_searxng.sh` (source clone, venv, real-pip `--use-pep517` install — uv pip rejects that flag; localhost settings.yml, JSON API on, limiter off). Managed component card (:8080) with start/stop; `odysseus depends_on [runner, searxng]` so one-switch provisions the full 3-node chain. Stop endpoint now falls back to kill-by-port when no pid file (`e514f9d`).
- **Verification method (use this, not log-noise heuristics):** `grep -i searxng data/logs/odysseus.log` → `SearXNG JSON API returned N results for: <query>` = private search confirmed. Startup noise in searxng.log (wikidata 403, ahmia/torch, X-Forwarded-For botdetection line) is non-fatal.
- **Operating note:** Odysseus falls back to DDG if SearXNG is down at search time (one old `Connection refused` explained by pre-install search). Dependency order guarantees searxng-before-odysseus for panel starts.
- **The harness now matches the full architecture diagram:** Bridge + Runner (headless Jan) + Hermes + Odysseus + SearXNG, one native window, all local, all private. Repo tip `e514f9d`.

## M3 Hermes-as-coworker — slice 1 DONE (verified 2026-07-20)

- **VERIFIED on the Mac, both surfaces.** Reinstall built the web UI clean (489 pkgs, `✓ built` → hermes_cli/web_dist/); `hermes dashboard` up on :9119; browser at http://127.0.0.1:9119 shows Hermes's full unstripped dashboard (chat replied via the runner Jan :6767 — "Got it — testing works", ready line 18.2k/65.5k ctx, cwd New Harness/harness, 31 tools · 73 skills); native Harness.app now has **three tabs (Mission Control / Odysseus / Hermes)** with the Hermes tab live; `test_hermes.sh` still `PASS`. Repo tip `0792822` (+ this doc update).
- **Operating note:** the dashboard's left panel shows **Gateway Status: Stopped** — that's the *messaging* gateway (Telegram/Discord), intentionally not running; NOT an error. It's the M5 remote-access surface, off by design for now.
- **Direction (Debi, 2026-07-20):** don't strip anything from Hermes; the harness's power is "use it as a harness, OR use Hermes from it, OR use Odysseus from it." Hermes must be **interactive with full visibility by default** (see everything as it happens — thinking, tools, approvals), NOT fire-and-watch-only. Fire-and-watch (`hermes -z`) stays as an *option*, added later. Follow how Hermes itself works.
- **The key code finding:** `hermes serve` and `hermes dashboard` boot the **same server** (`web_server.start_server`, default :9119) — `dashboard` is a **superset**: serve's JSON-RPC/WebSocket/PTY API **plus** Hermes's own web UI (embedded chat, live tool feed, approvals, sessions, config). So we don't run two servers; we run the superset and get both surfaces on one port. `hermes -z` is a separate one-shot invocation, untouched (test_hermes.sh still uses it).
- **Therefore slice 1 = Hermes's own dashboard as a third native tab** (Mission Control / Odysseus / **Hermes**) — its real, unstripped interface, so nothing is hidden. Auth: a **loopback bind (127.0.0.1) requires NO password** (`should_require_auth`: host==loopback → False) — unlike Odysseus. Web UI: a Vite/React SPA that **must be built once** — output goes to `vendor/hermes/hermes_cli/web_dist/` (both `node_modules/` and `web_dist/` are gitignored by upstream → building never dirties the submodule / blocks pin-bumps). Build cmd (must run at the hermes **root**, not web/, because `web` is a workspace with a `file:` dep on `apps/shared` = `@hermes/shared`): `npm install --workspace web && npm run build --workspace web`. **VERIFIED building clean in sandbox** (Node 22 / npm 10; 491 pkgs; `✓ built`; web_dist/index.html present).
- **Changes made this session (committed + Mac-verified):**
  - `install_component.sh` hermes branch: after pip install, builds the web UI (npm guarded by `command -v npm`; warns if npm absent).
  - `start_component.sh` hermes: launch switched `hermes serve` → `hermes dashboard --no-open --skip-build --host 127.0.0.1 --port 9119`. Pre-launch cleanup hardened (`hermes dashboard --stop` + `pkill -f "hermes (dashboard|serve)"` + `lsof` port-kill). Config patch (runner endpoint) unchanged. If web_dist is missing, dashboard degrades to headless (API only) — never blocks startup.
  - `bridge/app.py` install-plan text refreshed (was stale: "hermes-agent", ":8721", "gearbox").
  - `app/main.swift`: **third tab "Hermes"** → :9119, lazy-loaded top-level WKWebView, NO skin injection (Hermes's UI is already polished), uiDelegate for external links. Brace/paren balanced. **Requires `./scripts/build_app.sh` rebuild.**
- **Mac-verify sequence (Debi, next):** sync → **reinstall Hermes** (to build web_dist: panel Reinstall, or `./scripts/install_component.sh hermes --yes`) → Start Hermes → open **http://127.0.0.1:9119** in a browser → confirm the dashboard loads AND a chat message routes to the runner (Jan :6767) via the patched `~/.hermes/config.yaml` → confirm `test_hermes.sh` still PASS → THEN `./scripts/build_app.sh` + relaunch to get the Hermes tab. (Browser-first per Debi: the tab shows exactly what :9119 shows — no app-specific logic.)
- **Deferred (deliberate):** a *native* Mission Control Hermes pane in our editorial aesthetic (like the Odysseus Chat pane) is the HARD path — Hermes has no clean SSE chat API; its live surface is PTY (`/api/pty`) + a websocket tool-feed (`/api/ws`). Worth it later for aesthetic unity (Rung D premium), but the dashboard tab delivers the full interactive experience now without it.
- **Messaging gateway = relevant, later (Debi flagged it IS relevant).** Hermes's `gateway/` (Telegram/Discord/etc.) is the natural engine for "reach the harness from my phone" → folds into **M5 (remote access: Tailscale + messaging gateway)**. Recorded so it isn't lost.

## M3 slice 1b — "nothing stripped" audit + cron (2026-07-20)

Debi asked (seeing Config toggles do nothing + a theme setting): is anything stripped/removed/non-functioning? **Full code audit of vendored Hermes (Opus subagent, file:line evidence) → nothing is stripped.** `[all]` extras installed; `hermes dashboard` is the complete unstripped SPA (banner: 31 tools · 73 skills). Findings:
- **Config saves DO work** — `PUT /api/config` → `save_config` writes `~/.hermes/config.yaml` (web_server.py:5704; no headless/loopback/CSRF gate). "No response" = Hermes's own **live-apply semantics**: config is read via `load_config()` at use-time, so it applies to **new chats / next read**, never the in-flight turn. Model changes have their own reload path (`/api/model/set`).
- **Most Config sections don't touch the web chat by design.** Web-affecting: model/providers, agent, memory, mcp/toolsets, context. **CLI/TUI-only:** `display.*` (incl. skin), `terminal.*`, voice beeps. **Gateway/messaging-only:** the whole `gateway` block + every platform. Voice/TTS/STT need keys. So Display/Terminal/Voice/Discord toggles legitimately do nothing to the web view.
- **Theme = TWO separate systems.** `display.skin` ("CLI visual theme") themes the **terminal only** — never the web. The web theme is the **bottom-left palette switcher ("HERMES TEAL")**: 8 presets (default/Teal, Midnight, Ember, Mono, Cyberpunk, Rosé, Nous Blue, Teal-Large) in `web/src/themes/presets.ts`, stored in localStorage `hermes-dashboard-theme` + mirrored to `~/.hermes/dashboard-themes/*.yaml`. Already fully working. (Future Fable task: author a custom editorial theme matching Mission Control's cream/gold — clean path via this system.)
- **Gateway/Channels/Pairing/Webhooks/Cron look dead only because the gateway daemon isn't running.** The gateway is a **separate long-lived process** (`hermes gateway run`; also start/stop/status/restart/install). The dashboard's buttons just shell out (`/api/gateway/{start,stop,restart}` spawn `hermes gateway …`) and read its **pidfile** for status. Platforms (telegram, discord, slack, matrix, mattermost, whatsapp, signal, email, teams, +more in plugins/platforms/) each need env-var credentials. **Clean fit as a future Bridge component:** start=`hermes gateway run`, stop=`hermes gateway stop`, health=pidfile. Debi (2026-07-20): don't set messaging up yet — just confirm nothing's missing (it isn't); wire Telegram first when we do.
- **Cron:** Hermes has **no standalone cron daemon** — the ticker lives in the gateway. Debi wants cron working "both" ways → **enabled `HERMES_DESKTOP=1` on the dashboard launch** (start_component.sh) so the dashboard runs its OWN cron ticker (web_server.py:132 `_start_desktop_cron_ticker`, 60s interval). **VERIFIED firing 2026-07-20** ("Custom reminder" job → a session tagged `cron` in Sessions). **Delivery with no messaging channel:** the fired job is delivered as a **new chat session** (the per-platform send path's fallback) — so look in Sessions, not for a push. **Side effects of the flag:** exposes desktop-only `read_terminal`/`close_terminal` tools (inert outside Electron) + minor desktop prompt framing. **No double-fire risk** (earlier note was WRONG): the provider's `cron.scheduler.tick` takes a `cron/.tick.lock` file lock, so the dashboard ticker + a future gateway on the same HERMES_HOME never both fire — whichever grabs the lock wins (web_server.py:141-144 docstring).
- **Submodule mode-flip hygiene (2026-07-20):** an earlier sandbox/bootstrap copy stripped execute bits on ~60 tracked files in `vendor/hermes` (`old mode 100755 → 100644`, ZERO content change) — dirtying the submodule and threatening a future pin-bump (same class as the Odysseus gotcha #8). NOT caused by any chat. Fix on the Mac (sandbox can't unlink mount lockfiles): `rm -f .git/modules/vendor/hermes/index.lock` then `git -C vendor/hermes checkout -- .` (restores modes; discards nothing else). Or ignore mode noise entirely: `git -C vendor/hermes config core.fileMode false`.
- **Inventory — genuinely working now (loopback dashboard):** web chat (→ runner), Config read/save, Sessions, Skills, Models, Keys/Env, MCP config, Theme/Font switcher, **Cron (now, via the flag)**. **Present but inert pending runtime/credentials (NOT missing):** Gateway + Channels/Pairing/Webhooks (need the daemon + platform tokens), Voice/TTS/STT (keys), Memory (provider config). All are installed and in the UI; they light up when their backing process/credential exists.

## Rung D slice 1 DONE (verified 2026-07-20) — native Chat pane

- **Mission Control now has a native Chat pane** (sidebar + ⌘K "Open chat"): our editorial UI over Odysseus's API. Bridge-side proxy `/api/ody/*` (CORS default blocks browser-direct from :8700; Bridge logs in as admin via creds in harness.yaml, cookie + re-login on 401). Session find-or-create "Mission Control" bound to `local-jan`; SSE (`data:` lines over chunked POST, `[DONE]` terminator) re-streamed to the panel. Repo tip `951bc94`.
- **Transparency contract (the pattern for ALL future panes):** thinking streams OPEN live in italic serif, auto-collapses when the answer starts, expandable after — and simply absent for non-thinking models; tool lines show `running… → done`; web sources render as concise pills (truncated title + host) behind an expandable chip; links open in the default browser via Bridge `/api/open` (macOS `open`; webview target=_blank is unreliable — WKUIDelegate handler also added for Odysseus-tab links); minimal safe markdown (bold/code) rendered on completion; fixed-height column layout — messages scroll internally, input pinned.
- **Fan-out consequence:** if Odysseus admin password changes, update `components.odysseus.admin_password` in harness.yaml (the proxy logs in with it).

## Rung D slice 2 — Chat pane session management (code done, Mac-verify pending, 2026-07-20)

- **Chat pane now has a session rail** (list / switch / new / rename / delete), left of the chat column. Backed by new Bridge proxy endpoints over Odysseus's session API: `GET /api/ody/sessions` (list → id/name/model/updated_at/message_count, newest first), `POST /api/ody/session/new` (create, bound to `local-jan`), `POST /api/ody/session/{sid}/rename` (→ Odysseus `PATCH /api/session/{sid}` form `name`), `POST /api/ody/session/{sid}/delete` (→ Odysseus `POST /api/session/{sid}/delete`). History via existing `GET /api/ody/history/{sid}`.
- **Panel behavior:** on open, loads the list and restores the last session (`localStorage['harness-chat-sid']`) or the newest; "＋ New" creates+selects; switching loads that session's history; the rail refreshes after each turn so Odysseus's auto-title + recency reorder show up.
- **Inline rename/delete — deliberately NO `prompt()`/`confirm()`:** WKWebView shows neither unless the app implements the WKUIDelegate JS-panel methods (it doesn't), so those would silently no-op in the native tab. Rename swaps the name for an inline `<input>` (Enter save / Esc cancel / blur cancel); delete is a two-step arm (✕ → ✓? for 3s → confirm). Works identically in browser and app. (Existing `alert()` calls elsewhere in the panel DO silently fail in-app — future cleanup or add the WKUIDelegate panels.)
- **Panel-only change** (bridge/app.py + panel/index.html) — no Swift, so **no app rebuild**: sync → restart bridge (or relaunch app, which auto-starts it) → refresh the panel. Not yet Mac-verified.
- **Aesthetic references (Debi, 2026-07-20) for the FABLE visual pass:** likes the chat/session feel of **OpenAI's chat, Odysseus, CherryIn (Cherry Studio), Jan AI**. Per doctrine, look-and-feel = Fable-5 only; this slice ships the *function* in the existing editorial style (restrained, consistent) — a dedicated Fable-authored pass should restyle the rail + chat to that reference feel (decision-free spec → builder implements).

## Next actions (in order)

1. **Rung D next slices:** session management in the Chat pane (list/switch/new), Deep Research pane (launch/progress/report in our aesthetic), search-backend chooser (maps to Odysseus `search_provider`/fallback chain).
2. Then M3 Hermes-as-coworker (⌘K dispatch, feed integration, shared skills), then robustness polish (health cascade, install-time closure) — Debi's chosen order.
2. **Rung D native panes (future):** native Mission Control screens over Odysseus's API in the editorial aesthetic — the real "premium" path (see design findings above).
   - **Debi request (2026-07-20):** when the unified interface lands, expose a **search-backend chooser** (SearXNG vs others). Maps directly onto Odysseus's existing `search_provider` + `search_fallback_chain` settings (src/settings.py) — a UI setting + fan-out, not new engineering.
   - **Backlog:** investigate Jan desktop's native web-search (MCP or built-in tool?) for possible later incorporation.
2. **Web/search:** install the native SearXNG component (04 §Prototypes spike + shared-search) so Deep Research + Agent web_search use it instead of the DDG fallback.
3. Optional M1 polish: cross-dependency health cascade, install-time closure.

## Post-M0 spike results (2026-07-20)

**Headless Jan runner (`jan serve`) — PROVEN, M1-ready.** CLI 0.8.3 at `~/.local/bin/jan`. `jan serve <model> --port 6767 --api-key <KEY> --detach` serves standalone with desktop Jan QUIT (no desktop dependency), ~78 tok/s on the Qwen 35B. M1 runner-adapter facts, all verified:
- **Auth:** headless :6767 REQUIRES a key (unlike desktop :1337 which was keyless). `--api-key <KEY>` sets it; clients send `Authorization: Bearer <KEY>`. `LLAMA_API_KEY` env (set by Jan) is overridden by the flag. → M1: Bridge launches with a known key and fans it out to Hermes (`model.api_key`) and Odysseus (`model_endpoints.api_key`).
- **Stop by PORT, not PID:** `jan serve --detach` prints a supervisor PID, but the child llama-server router holds :6767 and SURVIVES `kill <pid>` → orphan blocks the next bind (cost us a confusing 401 from the stale server). → M1 stop = `lsof -ti tcp:6767 | xargs kill -9`.
- **Context:** the desktop-authored `router.preset.ini` wins over `--ctx-size` (loaded at 95536 despite `--ctx-size 65536`). ≥64K satisfied here; M1 must ensure the preset/flag yields ≥64K for any model.
- **Health probe:** `GET /v1/models` returns 200 with rich metadata WITHOUT a key; only chat needs the key.
- Metal shader compile warning appears in serve.log but is non-fatal (model loads + serves).
- Remaining spikes (not yet run): native SearXNG on macOS/arm64, WKWebView embed of :7860, HF API model query, `jan serve <hf-repo>` CLI download.

## Operating preconditions (as of M1 core — desktop Jan NO LONGER required)

- Start order: `./scripts/start.sh` (bridge) → panel **Start on Runner** (launches headless Jan :6767; loads model ~60–90s) → then Start Hermes and Odysseus (they repoint to :6767 on start). Or scripts: `start_component.sh runner|hermes|odysseus`.
- **Desktop Jan should be QUIT** when using the runner (avoids double-loading the 35B on 64GB). The `jan` CLI (installed by desktop Jan's first launch, at `~/.local/bin/jan`) is all the runner needs.
- Stop the runner by PORT (panel Stop does this): `lsof -ti tcp:6767 | xargs kill -9`. Killing the printed PID alone leaves an orphan holding :6767.
- Odysseus login: admin / admin123 — **change after first login**. Runner ctx must stay ≥64K (Hermes floor); the desktop-authored preset currently forces 95536.

## Operating preconditions (Hermes)

- Jan desktop must be running with **Settings → Local API Server ON** (:1337) and the model **loaded at ≥64K context** (set Context Size to 65536 in Jan's model settings, reload). M1 removes this manual step when the runner slot manages the endpoint.
- To (re)apply Hermes config + start: `./scripts/start_component.sh hermes`; to prove tool-calling: `./scripts/test_hermes.sh`.

## Verified learnings — failure archaeology (M0 Hermes, 2026-07-20)

Recorded so no one re-fights these. Format: symptom → root cause → evidence → status.

1. **Hermes "start" died silently (empty log).** → v1 ran `python mcp_serve.py --port 8721`, but that file is a stdio MCP server with no `--port`; and `gateway.run` (tried next) is the *messaging* daemon that idles/gets reaped with no platforms. Hermes is **invoke-on-demand**, not a daemon. → Verified in vendored code + Opus investigation. → FIXED: the one legitimate persistent, port-health-checkable surface is `hermes serve` (:9119, always headless); that's what `start_component.sh` launches. The actual tool-calling proof is `hermes -z` (`scripts/test_hermes.sh`).
2. **Config wrote `default: #`.** → awk read the `#` from the trailing comment on the `model:` line in harness.yaml. → FIXED: strip `#.*` + whitespace; empty → auto-pick first model from `/v1/models`.
3. **"HTTP 400: model name is missing".** → consequence of #2 (model was `#`). → FIXED with #2.
4. **"Context length exceeded (43 tokens). Cannot compress further."** → NOT a Hermes config problem. `model.context_length` is honored internally and passes Hermes's hard **64,000-token minimum gate** (`agent/model_metadata.py:185`, `agent_init.py:1842`), but it is **never sent to the server**. The real limit is the context window the **model is loaded at in Jan** (llama.cpp `n_ctx`). Jan's default was too small for Hermes's system-prompt + 70+ tool schemas → Jan rejected the request → Hermes compressed to ~43 tokens, couldn't shrink further, bailed (`agent/conversation_loop.py:3624`). → FIXED **Jan-side**: set the model's Context Size to ≥65536 and reload. Keep `model.context_length: 65536` in `~/.hermes/config.yaml` (needed to pass the gate + match the real window).

**Process lesson (Debi, 2026-07-20):** stop trial-and-error patching. "Cannot compress further" against a llama.cpp backend = server-side window rejection — diagnosable from the source on first sight. Standard now: read the code, form ONE evidenced hypothesis, then act. Both Opus subagent investigations produced the correct fix in a single pass — delegate subtle debugging early.

## Verified learnings — failure archaeology (M0 Odysseus, 2026-07-20)

5. **Odysseus chat 500'd: `NameError: _explicit_web_intent`.** → upstream bug in pin `168f5930` (used before assignment in `routes/chat_routes.py`); every chat failed. Jan itself confirmed fine via direct curl. → FIXED by pin-bump to `e57f60bd` (assigns it at line 882); verified deps/schema/setup unchanged first. Lesson: a generic "Internal Server Error" → read the component's own log (`data/logs/odysseus.log`) for the traceback; isolate server-vs-client with a direct curl to the endpoint.
6. **Odysseus "connect" seed created 0 rows silently.** → seed run by absolute path put the *script* dir on `sys.path`, not cwd, so `import core` failed; `|| true` swallowed it. → FIXED: `sys.path.insert(0, os.getcwd())` in `seed_odysseus_jan.py`. Lesson: never `|| true` a step whose failure matters — surface it.
7. **Odysseus pid never written → panel Stop said "no pid file".** → `( cd X && nohup … & echo $! > ../../data/pid )` backgrounds the `cd`, so `echo` ran from the wrong cwd and `../../data` pointed outside the project. → FIXED: `cd` applied to whole subshell + ABSOLUTE pid/log paths + stale-port kill before launch.
8. **Pin-bump blocked by dirty submodule.** → Odysseus rewrote its own `scripts/odysseus-backup`/`-memory` at runtime, so `git checkout <newpin>` aborted. → FIX before any Odysseus pin-bump: `git -C vendor/odysseus reset --hard` (upstream files, safe to discard), then `./scripts/bootstrap.sh --yes`.

**Git sync (reaffirmed):** stale `.git/modules/vendor/*/index.lock` from the sandbox blocks bootstrap → `rm -f` them (safe, nothing running). Always `git fetch origin && git reset --hard origin/main` to sync; `installed:true` now committed so resets don't revert install state.

## Git sync rule (important — cost us a full cycle)

Always sync the Mac clone with: `git fetch origin && git reset --hard origin/main`. Plain `git reset --hard origin/main` without a fetch resets to a **stale** local ref and silently reverts pushed fixes (this happened once and looked like "nothing changed"). Remote is truth; commits are pushed from the assistant's side per session.

## Standing cautions

- Doc freeze: no fifth planning pass until the full M0 handshake (Hermes + Odysseus both green) is done.
- v1 gotchas (07 §3): zsh `~` in quotes; uvicorn `--log-config /dev/null` crash; `chmod +x` new scripts (the sandbox copy loses execute bits); drain stdin before prompts; `vendor/hermes` not `vendor/hermes-agent`.
- When any fact is corrected, grep the whole doc set (especially the 00 primer) for the stale value.
