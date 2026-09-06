# MOT DECK INTERNALS — how this system actually works

> **IDENTITY (U150, 2026-09-07):** the PRODUCT is **MOT Deck** (*Mixture of Tools*) and
> its home screen is **MOT Main**. The logo remains `M.O.T`; machine-owned names use
> `motdeck`, `local.motdeck.app`, `MOTDeck`, `motdeck.yaml`, and `MOT_DECK_*`.

Canonical technical reference. Every claim below was derived by reading the code in
this repo (paths are repo-relative; `app.py:NNN` = `bridge/app.py` line NNN at the time
of writing — line numbers drift, symbol names don't, so functions are named too).
If this doc and the code disagree, **the code wins** — and this doc is wrong and should
be fixed. Do not add claims here from memory or from chat history.

Companion docs: `CLAUDE.md` (session log / decisions / pending QA), `docs/motdeck-architecture.md`
(original design), `docs/handoff/FABLE-*.md` (per-feature specs).

---

## 1. What this is + doctrine

A personal, local-first AI workspace that **composes two upstream projects without
forking them**, plus one piece of our own code (the Bridge).

| Piece | Where | Role |
|---|---|---|
| Hermes Agent | `vendor/hermes` (submodule, pinned tag) | agent brain: tools, skills, approvals, memory, cron, its own dashboard UI |
| Odysseus | `vendor/odysseus` (submodule, pinned commit) | web workspace: chat/docs/sessions/agent tools/web search |
| SearXNG | `vendor/searxng` (source clone) | private meta-search backend for Odysseus |
| **Bridge** | `bridge/` | **our only code**: control panel + panel UI + all lifecycle/model/chat plumbing |
| Native shell | `app/main.swift` | WKWebView app with tabs: Mission Control / Odysseus / Hermes |

Doctrine (enforced, not aspirational):

- **Never edit `vendor/`.** Read it for recon. Integrate through config files, HTTP APIs,
  and plugin/extension points. Upstream changes arrive only as a **pin bump** in
  `motdeck.yaml`, gated by `bridge/contract_tests/`.
- **Pins, never branches** for Hermes (release tag) and Odysseus (commit sha) —
  `motdeck.yaml` `components.*.pin`. Rollback = check out the old pin + reinstall.
- **No Docker.** Docker on Apple Silicon cannot reach Metal; everything is native.
- **Two builds** (§3): a lean dev app that serves the repo live, and a fat/offline
  installer that serves a provisioned snapshot.
- **Personal use** → AGPL (SearXNG) is not a distribution concern.
- Design/UX decisions are Fable's; builders implement from decision-free specs
  (see `CLAUDE.md` § MODEL IDENTITY PROTOCOL).

---

## 2. Process & port map

All bind loopback only. Ports come from `motdeck.yaml`.

| Process | Port | Started by | Health |
|---|---|---|---|
| Bridge (uvicorn, FastAPI) | **8700** | `scripts/start.sh`, or the app auto-starts it (`app/main.swift` `startBridge`) | `GET /api/status` |
| Runner (main model) | **6767** | `scripts/start_component.sh runner` | `GET :6767/v1/models` + `_live_model_id` (app.py:308) |
| Aux runner (small model) | **6768** | `POST /api/aux/start` (app.py:1741) | port alive |
| Hermes dashboard | **9119** | `start_component.sh hermes` → `hermes dashboard --no-open --skip-build` (start_component.sh:478) | port + `/api/ws` RPC |
| Odysseus | **7860** | `start_component.sh odysseus` | HTTP |
| SearXNG | **8080** | `start_component.sh searxng` | HTTP |
| gearbox (reserved, not built) | 8710 | — | — |

`hermes dashboard` is a **superset** of `hermes serve`: same server, plus Hermes's own
SPA. Loopback bind ⇒ no password for the UI, but `/api` is token-gated (§5).

**Fan-out on start** — the runner endpoint is the single source of truth, and starting a
component re-wires it:

- **hermes**: patches `~/.hermes/config.yaml` `model.{default,provider,base_url,api_key,context_length}`
  from the `runner:` block (start_component.sh:266-357, YAML-quoted); seeds/refreshes the
  path-guard plugin into `~/.hermes/plugins/motdeck-path-guard/` and adds it to
  `plugins.enabled` (start_component.sh:364-443); mints/reads `data/hermes.token` and
  exports `HERMES_DASHBOARD_SESSION_TOKEN` + `HERMES_DESKTOP=1` (cron ticker) at spawn.
- **odysseus**: runs `scripts/seed_odysseus_jan.py` (start_component.sh:224) which upserts
  the `local-jan` model endpoint (display name "Local runner") by **stable id** and sets
  the default model. (The id string `local-jan` is a historical identifier, not a Jan
  dependency — Jan is gone.)
- **runner**: launches the engine for the model's format (§7), always on 6767, so
  components never learn which engine is behind it.

Dependency closure lives in `motdeck.yaml` `depends_on` and is resolved by
`GET /api/components/{name}/start-plan` (app.py:470) → `POST …/start` provisions the whole
chain in a background thread with per-step state (`_provision`, app.py:137).

---

## 3. THE TWO BUILDS + THE SNAPSHOT RULE ⚠️

This has cost entire sessions. Read it twice.

- **Lean / dev app** — `./scripts/build_app.sh` (no flags). `build_app.sh` generates
  `app/Config.swift` with `motdeckRoot` = **this repo** and `fatBuild = false`
  (build_app.sh:33-40). The app starts the bridge **from the repo**, so the bridge and
  panel you edit are the ones running. Use this for iteration.
- **Fat / offline app** — `./scripts/build_app.sh --fat` (implies `--dmg`). Bundles a
  standalone CPython + a ~200-wheel arm64 wheelhouse + the pinned `llama-server` + a
  source **seed** tarball. On first launch `scripts/firstrun_fat.sh` extracts the seed to
  **`~/Library/Application Support/MOT Deck`** and builds all venvs offline
  (main.swift:259-276, firstrun_fat.sh:36-158). From then on the app serves the bridge and
  panel **from that snapshot**, not from the repo.
- **Portable app** — `--portable` uses the same Application Support root, provisioned
  online via `bootstrap.sh`. Packaged builds cannot silently split user state by flavor.

**THE RULE:** a `--fat` rebuild refreshes the bundle's seed but **never** an
already-provisioned snapshot (`firstrun_fat.sh` only extracts when the target dir is
absent, and writes a `.provisioned` marker at :158). After any code change the snapshot
must be refreshed, or the fat app serves stale code:

```
DST="$HOME/Library/Application Support/MOT Deck"
cp -R bridge/panel "$DST/bridge/panel"      # panel only, instant
cp bridge/app.py "$DST/bridge/app.py"       # bridge code
```
Clean alternative: `rm -rf "$DST"` then relaunch (full re-provision, slow).

Verify what is actually being served, **on the Mac**:
`curl -s http://127.0.0.1:8700/ | grep -c '<marker>'`.
Symptom of the trap: repo has the change, app shows old behavior.

The panel route sends `Cache-Control: no-store` (app.py `panel`, app.py:162) — added
because WKWebView heuristically cached `index.html`. If a stale panel persists anyway:
`rm -rf ~/Library/WebKit/local.motdeck.app ~/Library/Caches/local.motdeck.app`
(bundle id `local.motdeck.app`).

---

## 4. `motdeck.yaml` key reference

Single source of truth for pins, ports, endpoints. Read by the bridge (`cfg()`), the
shell scripts, and the build.

| Key | Read by | Meaning |
|---|---|---|
| `version` | `GET /api/version` (app.py:1308) → MC Version tile | local motdeck version |
| `components.<n>.repo` / `.pin` | `bootstrap.sh`, pin bumps | upstream + exact tag/sha |
| `components.<n>.installed` | `/api/status`, panel | install state (committed, survives resets) |
| `components.<n>.port` | bridge health checks, scripts | listen port |
| `components.<n>.depends_on` | start-plan closure (app.py:470) | provisioning order |
| `components.odysseus.admin_user/_password` | `_ody_req` login (app.py:599) | bridge's server-side Odysseus login |
| `components.hermes.dashboard_token` (optional) | `_hermes_token` (app.py) / start_component.sh:459 | override for the dashboard session token |
| `runner.adapter` | start_component.sh runner branch | `auto` (engine per model format) \| `llamacpp` \| `mlx` |
| `runner.llamacpp_pin` | `scripts/install_llamacpp.sh` | llama.cpp release tag (`bNNNN`); the tag **must** have a `macos-arm64` asset |
| `runner.binary` | start_component.sh + `aux_start` | explicit `llama-server` path; empty = auto-discover |
| `runner.mlx_venv` | `install_mlx.sh`, start_component.sh | MLX venv path |
| `runner.port` / `.endpoint` / `.api_key` | everything (fan-out) | canonical model endpoint |
| `runner.model` | start_component.sh, chat lanes, ledger | **registry id** of the active model |
| `runner.ctx_size` | runner launch, Hermes config | ≥64K (Hermes's hard floor) |
| `runner.spec_mtp` | start_component.sh MTP gate | `auto` \| `on` \| `off` (§7) |
| `aux.port/.endpoint/.api_key/.model` | `/api/aux/*` | optional second small model for Odysseus Background Tasks |
| `memory.budget_gb` | `_budget_bytes` (app.py:1408) | model-RAM budget (48 of 64GB); enforced with HTTP 409 |
| `bridge.port` | `start.sh`, main.swift | 8700 |
| `bridge.gearbox_port` | reserved | gearbox is shelved |
| `build.python_version` / `python_tag` | `build_app.sh --fat`, `firstrun_fat.sh` | bundled CPython + wheel ABI tag |
| `build.mlx_lm_pin` / `mlx_vlm_pin` | `install_mlx.sh`, `build_app.sh`, `firstrun_fat.sh` | **single source** — installer and wheelhouse must agree or offline provisioning fails |
| `inference.endpoints` / `cloud` | reference only | gearbox-era; not routed today |
| `paths.*` | scripts | vendor/skills/data roots |

---

## 5. The FOUR chat lanes

The panel has one chat surface with mode chips: **Agent**, **Chat**, **Hermes**, plus a
**Browse** toggle that is not a lane but a capability flip. All three lanes speak the
**same SSE frame protocol** to the panel, so one renderer handles them
(`sendChat`, panel index.html).

Shared frame vocabulary (panel-side): `{delta}` token, `{delta, thinking:true}`,
`{type:"model_info"}`, `{type:"tool_start"|"tool_output"}`, `{type:"approval"}`,
`{type:"file_card"}`, `{type:"guard_flag"}`, `{type:"hermes_status"}`,
`{type:"hermes_session"}`, `{type:"proxy_error"}`, terminated by `data: [DONE]`.

### 5.1 Agent lane (Odysseus)

- Path: panel → `POST /api/ody/chat` (app.py:1332) → Odysseus `POST /api/chat_stream`,
  raw SSE **passed through unchanged**.
- Auth: the bridge logs into Odysseus server-side as admin and re-logs on 401
  (`_ody_req`, app.py:599); the panel never talks to :7860 directly (CORS + cookies).
- Tools: web_search / web_fetch / deep research / doc editor live in Odysseus. Telemetry
  arrives as structured SSE events → the panel's single `.statusline` (`▸ searching the
  web…` → `✓ web_search — N steps`) plus a collapsible `INSPECT` log of structured frames.
- Persistence + thinking + auto-title: **Odysseus's own** store and post-turn tasks.
  Reopening a session shows what Odysseus stored; tool-heavy turns may put the substance
  in a canvas document (upstream behavior).
- Stop: `POST /api/ody/stop/{sid}` (app.py:3503).
- Analytics: the bridge keeps a 16KB rolling tail of the passthrough and extracts the last
  `{"type":"metrics"}` frame in `finally` → `log_turn` (app.py:1070).

### 5.2 Chat lane (direct to the runner)

- Path: panel → `POST /api/chat/direct` (app.py:2334) → runner `POST /v1/chat/completions`
  (`_RUNNER` httpx client). **Bypasses Odysseus entirely** — root cause it exists: Odysseus
  fires auxiliary LLM calls (titles, memory extraction, search-query generation) at the same
  single-slot runner and chat turns queue behind them, losing the prompt cache.
- Model id on the wire: `wire_model_id` (app.py:206) — registry id for llama.cpp
  (launched with `--alias`), the model **path** for MLX (§7).
- History: last 30 `{role,content}` messages read from `GET /api/history/{sid}` on Odysseus
  (degrades silently if Odysseus is down — the lane still works).
- Thinking: both shapes handled in one loop — `delta.reasoning_content`, and inline
  `<think>…</think>` split out of `delta.content`. Streamed as `{delta, thinking:true}`.
- **Thinking persistence (sidecar)**: Odysseus stores `{role,content}` only, so the turn's
  reasoning is written to **`data/thinking.db`** keyed by `(sid, answer_hash(answer))`
  where `answer_hash` = sha1 of the first 2048 chars (`answer_hash` app.py:1137,
  `log_thinking` app.py:1166). On reopen, `GET /api/ody/history/{sid}` joins them back in
  **order-consuming** fashion (`attach_thinking`, app.py:1213) and the panel renders a
  collapsed `thinking · restored` disclosure (`addRehydratedThinking`).
- Persistence: one batched `POST /api/session/{sid}/inject_messages` (user then assistant)
  — upstream removed the older `/message` and `/fork` endpoints at pin 25c9e73.
- Auto-title: the lane skips Odysseus's post-turn tasks, so the bridge derives a ≤42-char
  word-boundary title from the first user message when the session is still "New chat".
- **Images (vision)**: optional body key `image` (a `data:image/…` dataURL). `build_user_content`
  (app.py, pure, tested by `bridge/tests/test_vision_content.py`) returns either the plain
  string (no image) or OpenAI parts `[{type:text},{type:image_url}]`. Refusals (non-image
  dataURL / >12MB / model has no vision) stream **one** `proxy_error` frame and never call
  the runner. Vision capability = registry flag for the **live** model id
  (`_vision_capable` + `_live_model_id`). Persistence stores text plus a
  `\n[image attached]` marker, keeping the store string-shaped so the answer-hash sidecar
  join is unaffected. The composer shows a `VISION` pill and an `⊕` attach button only when
  the live model is vision-capable and the lane is Chat.
- No tools, no approvals, no file cards in this lane.
- Analytics: `stream_options.include_usage` + `timings` → `log_turn`. `cached_tokens` /
  `cache_n` availability is llama-server-build-dependent (the Cache-hit tile hides itself
  when absent).

### 5.3 Hermes lane (dashboard JSON-RPC gateway)

- Path: panel → `POST /api/hermes/chat` (app.py:2935) → **one shared WebSocket** to
  `ws://127.0.0.1:9119/api/ws?token=…`, multiplexed by `session_id`, re-emitted as SSE.
- Auth: `HERMES_DASHBOARD_SESSION_TOKEN` is set at spawn (start_component.sh:459-478) and
  read back by `_hermes_token`, so the bridge knows the token deterministically.
- RPC methods used: `session.create`, `prompt.submit`, `session.interrupt`,
  `session.active_list`, `session.resume`, plus session list/rename/delete.
  Events consumed: `message.delta`, `message.complete` (status `complete|error|interrupted`),
  `tool.start`, `tool.complete`, `approval.request`.
- The event→frame mapping is a **pure** function `hermes_event_to_frames` (app.py:2676),
  unit-tested (`bridge/tests/test_hermes_sse_map.py`) and pin-gated
  (`bridge/contract_tests/test_hermes_ws_contract.py`). ⚠ This protocol is
  upstream-internal with no stability promise — the contract test is the tripwire.
- Turn lifecycle guards in the relay: 60s first-event timeout; 20s mid-turn silence →
  a `hermes_status` note plus a best-effort `session.active_list` probe that ends the turn
  if Hermes reports the session idle/gone; 600s hard guard. Both the note and the probe are
  **suppressed while an approval card is pending**.
- Stop: `POST /api/hermes/stop` (app.py:3087) nudges the relay then calls
  `session.interrupt`; interrupting with an approval pending auto-denies it upstream.
- **Approvals**: `approval.request` → SSE `{type:"approval", request:{command, description,
  choices}}` → an inline card in the assistant message with one chip per declared choice
  (Once / This session / Always / Deny). Answer: `POST /api/hermes/approve` (app.py:3115)
  → `approval.respond {session_id, choice}`. There is **no request id on the wire** —
  approvals are keyed by session and resolved FIFO-oldest. Missing/malformed `choices`
  degrade to `["once","deny"]` (never invent a persistence scope). Turn end with open cards
  stamps them `· expired`.
  **Finding that matters:** Hermes's *default* `approvals.mode` is **`smart`**, not manual —
  a guardian LLM can auto-approve before the card path. Set `manual` in Hermes Config →
  Security for every dangerous command to card.
  `bridge/contract_tests/` pins both the approval payload shape and the default mode.
- **File cards**: `tool.complete` for `write_file`/`patch` with a successful dict result →
  SSE `{type:"file_card", path, tool}` → a card with Open / Show-in-Folder via `/api/open`.
  Only absolute `/Users|~` paths render; cards do not survive a reload (transcript
  hydration can't reconstruct them); `skill_manage` and writes inside `execute_code` are
  invisible at `tool.complete`.
- **Restored thinking**: Hermes's own store keeps reasoning, so
  `GET /api/hermes/history/{sid}` maps `reasoning|reasoning_content|reasoning_details|
  codex_reasoning_items` back into the transcript and **keeps reasoning-only assistant
  turns** (mirroring upstream's own projection) — otherwise extended-thinking turns vanish
  on reopen. Tested in `bridge/tests/test_hermes_sessions.py`.
- **Known limit:** don't drive the same Hermes session from the panel and the Hermes
  dashboard at once — `prompt.submit`/`session.resume` rebind the session's transport to the
  caller, silently muting the other surface. A dashboard banner "session ended (code 1005)"
  is a **browser-side** WebKit teardown of a backgrounded tab plus an upstream client bug,
  not a bridge fault; ⌘R the Hermes tab.

### 5.4 Browse toggle (not a lane)

`GET/POST /api/browse/status|toggle` (app.py:3569/3580) registers the stdio **Browser MCP**
(`npx @browsermcp/mcp`) into **both** components in one flip: Odysseus via
`POST /api/mcp/servers`, Hermes via a YAML round-trip that writes `mcp_servers.browsermcp`
into `~/.hermes/config.yaml` (`_hermes_set_mcp`, app.py:3528 — atomic tmp+`os.replace`).
The `hermes mcp add` CLI is deliberately **not** used (interactive prompts + live connect
would hang a subprocess). Requires the Chrome extension + a connected tab. Hermes picks the
config up on new chats. (The Jan-coupled "jan-browser-mcp" was dropped — it needs Jan's
own bridge on 17389.)

---

## 6. Session stores (three distinct stores)

1. **Odysseus DB** — sessions for the Agent *and* Chat lanes (both write into the same
   session). Bridge proxy: `/api/ody/sessions`, `/api/ody/session/new|{sid}/rename|
   {sid}/duplicate|{sid}/delete`, `/api/ody/history/{sid}` (app.py:642-741). Duplicate is
   implemented as create + `inject_messages` + rename (upstream removed `/fork`).
2. **Hermes's own store** — reachable only through the gateway:
   `/api/hermes/sessions|session/new|session/resume|{sid}/rename|{sid}/delete|history/{sid}`
   (app.py:3254-3372).
3. **`data/thinking.db`** — the bridge's local sidecar for direct-lane reasoning (§5.2).
   Not a session store proper, but it is a third place turn data lives.

The **rail follows the active lane**: `setMode()` synchronously re-renders the rail before
any async load, and a shared `sessionsReqSeq` request token drops late/superseded loads, so
Odysseus rows can never appear under the Hermes chip. `selectSession` /
`selectHermesSession` are lane-guarded.

**Hermes stored-vs-live sid** — the crucial distinction: `session.resume` returns a **new
live `session_id`** plus a durable `session_key` (the *stored* id). The panel keeps both
(`hermesSid` live, `hermesStoredSid` durable, persisted in `localStorage['motdeck-hermes-sid'
| 'motdeck-hermes-stored']`). The rail lists stored ids; prompts go to the live id; the
guard audit records the stored id so an audit row can jump back to the exact conversation.

Panel `localStorage` keys: `motdeck-chat-sid`, `motdeck-hermes-sid`, `motdeck-hermes-stored`,
`motdeck-theme`, `motdeck-chat-rail`, `motdeck-sessions-rail`, `motdeck-sessions-width`,
`motdeck-artifact-split`, `motdeck-canvas-split`, `motdeck-caps-section`,
`motdeck-setup-done`, `motdeck-tour-done`.

---

## 7. Models

### Registry — `data/models.json`

Written by `scripts/seed_registry.py` (scans `data/models/` for app-owned models and
`~/.lmstudio/models` for read-only imports) and by the download manager
(`_gguf_registry_entry` / `_mlx_registry_entry`, app.py ~1975-2013). Entry fields:

`id` (internal key everywhere: ledger, labels, selects), `name`, `path` (file for gguf,
DIR for mlx), `size_bytes`, `format` (`gguf|mlx`), `vision` (bool), `mmproj` (gguf
projector), `ctx` (preserved across re-seeds), `source` (`download|local|lmstudio-import`),
**`repo`** (the HuggingFace source repo — persisted specifically because MTP models ship as
`<org>/…-MTP-GGUF` while the per-file id carries no marker; without it MTP detection was
blind, see below).

`merge()` in seed_registry replaces the re-scanned sets (so models deleted in LM Studio drop
out) while preserving `source: download` entries and known `ctx`. `POST /api/models/rescan`
(app.py:1493) re-runs it.

### Download manager

`POST /api/dl/start {repo, filename}` (app.py:2160) + pause/resume/cancel + `GET /api/dl`.
Per-file GGUF (split `-NNNNN-of-MMMMM` expanded, lone `mmproj` auto-fetched) and whole-repo
MLX mode (empty filename → all safetensors/config/tokenizer). HTTP-Range resume via `.part`
files, parallel tasks, EMA rate. Destination is hard-pinned to `ROOT/data/models/<id>/`.

### Engines / adapters

`runner.adapter: auto` picks the engine **per model format** in
`scripts/start_component.sh`'s runner branch: `gguf → llama-server`,
`mlx → mlx_lm.server`, `mlx + vision → mlx_vlm.server`. Always port 6767. Binary discovery
order: `runner.binary` → our pin `data/llamacpp/build/bin/llama-server` → LM Studio
backends glob. llama-server always gets `--alias <registry id>` (so `/v1/models` reports our
id) and, when the binary supports them, `--repeat-penalty 1.1 --repeat-last-n 256`
(start_component.sh:104) — added after a real repetition-loop degeneration.

### MTP (speculative decoding)

Gate in start_component.sh:114-168. Detection matches the registry **id OR the source
repo** (that gap was why MTP loaded but never accelerated). `runner.spec_mtp` overrides:
`auto|on|off`. Flags: `--jinja --spec-type draft-mtp --spec-draft-n-max 2 …`. **Self-healing
retry:** if a spec launch fails, the script warns, strips `SPEC_ARGS`, kills the listener and
relaunches clean — so broadening detection can never strand the runner. Never add spec flags
without MTP evidence (they break loading on non-MTP models). Pinned by
`bridge/tests/test_mtp_detect.py`. Measured effect: ~+15% avg, decaying with generation
length.

### RAM ledger

`_model_size` / `_budget_bytes` / `_loaded_models_bytes(exclude_slot)` /
`_within_budget` (app.py:1395-1435). Footprint is **approximated by weight-file size**;
`memory.budget_gb: 48` of 64GB leaves headroom for KV-cache and the OS. Enforced with
**HTTP 409** on `POST /api/models/switch` and `POST /api/aux/start`. `GET /api/models`
returns `ledger:{used_bytes,budget_bytes}`; the Models pane stamps `· RAM x / y GB`.

### Live model, switching, ejecting

`_live_model_id(port)` (app.py:308) probes `GET :port/v1/models` — the **single source of
truth** for "what is loaded" (a set `runner.model` with a live port is not enough). `/api/status`
`running` and the Models pane's `live` pill both key off it. `POST /api/models/switch` runs
`_do_switch` in a background thread with a busy lock, checks each step's exit code, and
**rolls `motdeck.yaml` back** on load failure; `/api/models/switch-status` polls;
`/api/models/eject` clears `runner.model` (Stop = pause, Eject = forget — deliberate
asymmetry). `POST /api/models/delete` only ever deletes under `data/models`
(`_deletable_target`, app.py:1622, plus a second containment check).

### `wire_model_id` — why MLX uses the path

`wire_model_id` / `display_model_id` (app.py:206/222). `mlx_lm.server` treats the request's
`model` field as **a model to load** (`ModelProvider.load` → HF resolve), and mlx-lm/mlx-vlm
have **no `--alias` flag**, so sending our registry id caused a 404 on huggingface.co → runner
400. Fix: for `format: mlx` the wire id is the registry **`path`**, byte-identical to the
`--model` argv, so the already-loaded model resolves with no reload. gguf is unchanged
(the `--alias` makes id == wire). Applied at every wire site: direct lane, Hermes config
fan-out, `seed_odysseus_jan.py` (+ `MOT_DECK_WIRE_MODEL` override). The registry id stays the
internal key; four endpoints map back for display. Also: never trust an MLX server's
`/v1/models` ids — `mlx_lm.server` enumerates the whole shared HuggingFace cache.

---

## 8. Path-guard fence

Fences Hermes's `write_file` / `patch` tool calls.

- **Mechanism:** Hermes's first-class `pre_tool_call` plugin hook
  (`vendor/hermes/hermes_cli/plugins.py`, in `VALID_HOOKS`); directive vocabulary
  `{"action":"block"|"approve","message","rule_key"}`. `approve` escalates the call into the
  **same** approval gate as dangerous shell commands (`tools/approval.py`,
  `plugin_rule:<key>` allowlist namespace) — so it renders in our existing approval card
  with zero panel work. `block` is a hard veto.
- **Delivery:** the plugin lives in the repo at `guards/motdeck-path-guard/`
  (`plugin.yaml`, `__init__.py` with a pure matcher, `policy.yaml`, `README.md`) and is
  **seeded** to `~/.hermes/plugins/motdeck-path-guard/` on every Hermes start
  (copy-if-changed, `{MOT_DECK_ROOT}` substituted, `__pycache__` cleared) plus added to
  `plugins.enabled` via a YAML round-trip + atomic write (start_component.sh:364-443).
  User plugins are opt-in: a missing `plugins.enabled` key loads nothing.
- **Policy semantics** (`guards/motdeck-path-guard/policy.yaml`, re-read on every gated
  call): `deny` is checked **first and always wins** (`~/.ssh`, `~/.aws`, `~/.gnupg`,
  `~/Library/Keychains`, `~/.hermes/config.yaml`); then `allow` proceeds
  (`{HERMES_CWD}`, `~/.hermes`, `{MOT_DECK_ROOT}/data`, `/tmp`, `{TMPDIR}`); anything else
  **escalates** to the approval card. Containment uses `os.path.commonpath` on realpaths —
  never string prefixes (the `/Users/debikEvil` trap). Fail-**closed** on unresolved V4A
  patches, an unreadable policy, or any exception. `rule_key` grain = the target's
  containing directory.
- **Approval card:** a plugin-escalated approval sets `command` to a synthetic label
  (`<write_file> (plugin approval rule)`) and puts the path in `description`, so the bridge
  forwards `description` into the card.
- **Audit tier (independent of the fence):** the bridge reads the same policy and, beside
  each out-of-allowlist `file_card`, emits an SSE `guard_flag` frame (faint
  `⚠ wrote outside workspace: <path>` on the statusline, deduped per turn), one
  `[guard]` warning line (`_guard_flag`, app.py:2635), and a durable JSON line in
  **`data/logs/guard.log`** (`_guard_audit`, app.py:2644 — `{ts, path, tool, sid,
  stored_sid}`). Note the audit tier resolves `{HERMES_CWD}` as the **bridge's** cwd: a
  differently-launched Hermes would over-flag, never under-flag.
- **Logs pane:** `GET /api/logs/{name}` accepts `bridge|hermes|odysseus|searxng|runner|guard`
  (app.py:370); the `guard` source renders as an editorial list (time · tool · file rows with
  Reveal and a jump-to-chat via the stored sid) rather than raw JSON. Every source also has
  Copy / Export (`POST /api/logs/{name}/export` → `~/Downloads/motdeck-logs/`) / Clear
  (truncate-not-delete, so a component holding the fd keeps appending).
- **Honest limits:** gates `write_file`/`patch` **only**. Arbitrary writes from
  terminal/`execute_code` still ride upstream's dangerous-pattern gating (full shell coverage
  would need the deferred `sandbox-exec` option). Reads/exfiltration are out of scope.
- Tests: `bridge/tests/test_path_guard.py` (matcher + bridge helper) and a
  `test_path_guard_hook_contract` in the contract suite (hook name, directive keys, resolver
  + gate seams, user-plugin dir, `plugins.enabled`, `discover_plugins` on the model_tools
  path, write_file/patch registrations).

---

## 9. Capabilities panel

`#view-caps`, sub-tab chips **General / Tools / Skills / Models** (show/hide over one
snapshot fetch; last section in `localStorage['motdeck-caps-section']`).

Backend: `GET /api/ody/caps` (app.py:829) aggregates Odysseus's two stores plus search
availability, partial-safe with an `errors{}` map; writes go through the pure
`caps_map_write(group, key, value)` (app.py:775) → `POST /api/ody/caps/set`:

| Group | → Odysseus | Notes |
|---|---|---|
| `feature` | `POST /api/auth/features` | 8 booleans in `features.json` |
| `setting` | `POST /api/auth/settings` | restricted to `CAPS_SETTING_KEYS` (search backend/safesearch/count, agent limits) |
| `mcp_server` | `PATCH /api/mcp/servers/{id}` | **form** `is_enabled` |
| `mcp_tools` | `PATCH /api/mcp/servers/{id}/tools` | full replace list of disabled tools |
| `builtin_tools` | `POST /api/tools` | full replace list of disabled built-in tool ids |
| `skill_builtin` | `DELETE /api/skills/builtin/{key}` | reset a text override only — built-in skills have **no** on/off here |

Any `*_api_key` write is refused outright (secrets never pass through the panel). Add/remove
MCP servers: `POST /api/ody/mcp/add` → `POST /api/mcp/servers` (form) and
`POST /api/ody/mcp/{id}/remove` → `DELETE`. Model pickers (Background/Utility) write the
`task_*`/`utility_*` endpoint+model settings. `GET /api/ody/mcp/{id}/tools` lists per-server
tools. Built-in tool **categories** are a panel-authored map (`/api/tools` is flat).
Unit-tested: `bridge/tests/test_caps_map.py`.

---

## 10. Artifacts + Canvas

- **Detection:** `artifactKind()` (pure, unit-tested) + fenced-block classification. HTML /
  SVG / React always get an `⧉ Open <Kind>` button; js/code when ≥8 lines or ≥300 chars;
  plus markdown, mermaid, CSV, JSON. Buttons attach at stream `[DONE]` (one clean finalize
  re-render — an explicit design decision, not a bug).
- **Rendering sandbox:** every scripted artifact goes into an `iframe srcdoc` with
  `sandbox="allow-scripts"` and **no `allow-same-origin`** → unique opaque origin, plus a
  strict CSP with `connect-src 'none'`. Scripted frames need `'unsafe-eval'` (Babel /
  Tailwind JIT / mermaid) — contained by the opaque origin.
- **Nav-escape fix:** a `srcdoc` document resolves relative URLs against the **parent's**
  base, so an artifact's `<a href="/">` navigated the frame to the panel. Fix:
  `<base href="about:srcdoc">` injected as the first `<head>` element of every artifact doc
  (`ART_BASE`), first-base-wins making ours authoritative; `base-uri` dropped from the CSP
  (it would block our own base); plus a capture-phase `ART_NAV_GUARD` click listener that
  preventDefaults any non-fragment anchor.
- **Offline assets:** `scripts/fetch_vendor_assets.sh` downloads pinned libs into
  `bridge/panel/assets/vendor/` (gitignored), mounted at `/assets`
  (`app.mount`, app.py:33): babel-standalone 7.26.4, react/react-dom 18.3.1 UMD, Prism
  1.29.0, markdown-it 14.1.0, DOMPurify 3.2.4, Tailwind Play 3.4.16, mermaid 11.4.1,
  CodeMirror 5.65.18. `rewriteVendorCdns()` rewrites `cdn.tailwindcss.com` script srcs to
  the self-hosted copy using an **absolute** `location.origin` URL (so the dead `<base>`
  doesn't break asset loads). `build_app.sh` runs the fetch for `--portable`/`--fat` and
  bundles the vendor dir into the seed.
- **Viewer:** split pane (drag divider, persisted) + expand overlay; cleared when leaving
  Chat. Markdown goes markdown-it → DOMPurify → Prism; CSV → a host-side sortable table
  (RFC-4180-ish parser, numeric-aware, 2000-row display cap); JSON → a `<details>` tree.
- **Canvas (editable artifacts):** homegrown, **not** Sandpack (CodeMirror 5 UMD
  self-hosts as a single file; Sandpack deferred to a future multi-file/npm need).
  ✎ Edit → editor/preview stack with a persisted split, 600ms-debounced re-render through
  the same renderer, Copy / Revert / Save. `POST /api/artifact/save` (app.py:3465) is
  hardened: basename-only, extension whitelist, 5MB cap, server-built path under
  `~/Downloads/motdeck-artifacts/`, never-clobber ` (n)` suffix; tested in
  `bridge/tests/test_artifact_save.py`.
- **`POST /api/open`** (app.py:3385) is the only escape hatch: `{url}` http(s) only, or
  `{path, action:"open"|"reveal"}` whose realpath must exist and start with `$HOME` —
  `file://` is never accepted in the url field; rejections are logged.

---

## 11. Bridge endpoint index

Derived from the `@app.*` decorators in `bridge/app.py`.

**Panel / status / logs**
- `GET /` — the panel (sends `Cache-Control: no-store`)
- `GET /api/status` — components, provisioning overlay, runner/live model, degraded flags
- `GET /api/version` — local motdeck version
- `GET /api/analytics` — tokens today, turns, avg tok/s, cache-hit %
- `GET /api/logs/{name}` · `POST /api/logs/{name}/clear` · `POST /api/logs/{name}/export`

**Component lifecycle**
- `GET /api/components/{name}/plan` · `POST …/install`
- `GET /api/components/{name}/start-plan` · `POST …/start` · `POST …/stop`
- `POST /api/components/{name}/update` (501 stub)

**Odysseus proxy**
- `GET /api/ody/health` · `POST /api/ody/ensure-session`
- `GET /api/ody/sessions` · `POST /api/ody/session/new`
- `POST /api/ody/session/{sid}/rename|duplicate|delete` · `GET /api/ody/history/{sid}`
- `POST /api/ody/chat` (agent lane) · `POST /api/ody/stop/{sid}`
- `GET /api/ody/caps` · `POST /api/ody/caps/set`
- `GET /api/ody/mcp/{id}/tools` · `POST /api/ody/mcp/add` · `POST /api/ody/mcp/{id}/remove`

**Models / runner**
- `GET /api/models` · `POST /api/models/rescan`
- `POST /api/models/switch` · `GET /api/models/switch-status` · `POST /api/models/switch-cancel`
- `POST /api/models/eject` · `POST /api/models/delete`
- `POST /api/aux/set|start|stop`
- `GET /api/models/hf` · `GET /api/models/hf/files` · `GET /api/models/hf/card`
- `POST /api/dl/start` · `POST /api/dl/{id}/pause|resume|cancel` · `GET /api/dl`

**Chat lanes**
- `POST /api/chat/direct` (Chat lane; optional `image`)
- `POST /api/hermes/chat` · `POST /api/hermes/stop` · `POST /api/hermes/approve`
- `GET /api/hermes/sessions` · `POST /api/hermes/session/new|resume`
- `POST /api/hermes/session/{sid}/rename|delete` · `GET /api/hermes/history/{sid}`

**Misc**
- `POST /api/open` (browser url / open-or-reveal a file under `$HOME`)
- `POST /api/artifact/save`
- `GET /api/browse/status` · `POST /api/browse/toggle`
- `/assets/*` — StaticFiles mount for the self-hosted vendor libs

---

## 12. Ops rules & gotchas

Learned the hard way; each one cost real time.

1. **Every `lsof -ti tcp:` kill MUST carry `-sTCP:LISTEN`.** Without it the pattern matches
   **client** sockets, and the bridge holds httpx keep-alives to :7860/:6767 — a port-clear
   once SIGTERMed the bridge itself. Helpers: `_port_kill_cmd` / `_kill_port_listener` /
   `_port_listener_pids` (app.py:496, tested in `bridge/tests/test_port_kill.py`);
   inline occurrences in start_component.sh all carry the flag.
2. **Stop verifies the port, not just the pid.** Stale pid files made Stop a silent no-op;
   `stop()` (app.py:516) now treats the pid kill as advisory and always checks the port
   (≤1.5s grace) before killing the listener.
3. **Never kill the bridge by name or by a bare port match.** `ship.sh` uses the bridge
   pidfile first, re-verifies the full command/path identity, and refuses to touch a
   stranger listening on :8700.
4. **Relaunching the installed app:** ask the stable bundle id to quit, then reopen that
   same identity: `osascript -e 'tell application id "local.motdeck.app" to quit'` followed
   by `open -b local.motdeck.app`. The installed filename may be `MOT Deck.app` or
   user-renamed; `ship.sh` validates and selects the actual bundle before changing anything.
5. **Stale panel:** `rm -rf ~/Library/WebKit/local.motdeck.app ~/Library/Caches/local.motdeck.app`
   (bundle id `local.motdeck.app`).
6. **The snapshot rule** (§3) — the fat app serves the snapshot, not the repo.
7. **Submodule hygiene:** `git -C vendor/<name> reset --hard` before any pin checkout
   (Odysseus rewrites its own scripts at runtime); remove stale
   `.git/modules/vendor/*/index.lock` if git refuses (safe when no git process runs); mode
   noise can be silenced with `core.fileMode false`.
8. **Never `git reset --hard` over unverified work**, and always `git fetch` first —
   resetting to a stale local ref silently reverted pushed fixes once.
9. **zsh:** `~` does not expand inside quotes — use `cd ~/"Some Folder"`. Multi-line pastes
   have answered interactive prompts by accident; prefer single commands or `--yes`.
10. `uvicorn` must not get `--log-config /dev/null` (crashes). New scripts need `chmod +x`.
11. **Never click Hermes's in-app "Update now"** — Hermes is a pinned submodule; updates go
    through the pin-bump + contract-test flow only.
12. Shell-script trap seen twice: `"$VAR…"` with a glued ellipsis crashes under `nounset` —
    write `"${VAR}…"`.

---

## 13. Installation footprint & security posture

Audited by reading `scripts/*`, `app/main.swift`, `bridge/app.py`, `guards/` (2026-08-07).
Motivation: apps that scatter files into system or Homebrew prefixes.

### Everything MOT Deck writes

| Path | Written by (file:line) | When |
|---|---|---|
| `<repo>/vendor/*`, `<repo>/data/`, `<repo>/.git` | `bootstrap.sh:56-98` | bootstrap |
| `<repo>/data/*-venv/` (bridge, hermes, odysseus, searxng, mlx) | `bootstrap.sh:86-91`, `install_component.sh`, `install_mlx.sh` | install |
| `<repo>/data/llamacpp/build/bin/llama-server` | `install_llamacpp.sh:34-75` | runner install |
| `<repo>/data/models/<id>/…` (weights, `.part` files) | `app.py:2059-2225` (`_run_download`), `migrate_jan_models.sh:33-40` | downloads / migration |
| `<repo>/data/models.json` | `seed_registry.py:244-257`, `app.py:1937-1968` (atomic) | seed / delete |
| `<repo>/data/{runner,aux,hermes,odysseus,searxng}.pid` | `start_component.sh:147-479`, `app.py:49-1597` | start/stop |
| `<repo>/data/logs/*.log` (incl. `guard.log`) | `start.sh:14`, `start_component.sh`, `app.py:2654-2667` | runtime |
| `<repo>/data/hermes.token` (chmod 600) | `start_component.sh:466-467` | hermes start |
| `<repo>/data/analytics.db`, `<repo>/data/thinking.db` | `app.py:1055`, `app.py:1150` | runtime |
| `<repo>/motdeck.yaml` (in-place line rewrite) | `app.py:1371-1384`, `install_component.sh:72-78` | switch / install |
| `<repo>/bridge/panel/assets/vendor/*` | `fetch_vendor_assets.sh:93-105` | asset fetch |
| `<repo>/dist/*`, `<repo>/app/Config.swift` (generated) | `build_app.sh:29-245` | build |
| `~/Library/Application Support/MOT Deck/**` | `main.swift:259-276`, `firstrun_fat.sh:36-158` | **fat** first run |
| `~/Library/Application Support/MOT Deck/**` | `main.swift`, `firstrun*.sh` | **portable + fat** first run |
| `~/.hermes/config.yaml` | `start_component.sh:266-357`, `app.py:3528-3554` (atomic) | hermes start / MCP toggle |
| `~/.hermes/plugins/motdeck-path-guard/*` | `start_component.sh:364-443` | hermes start |
| `~/Downloads/motdeck-artifacts/<name>` | `app.py:3489-3498` (sanitizer at 3437-3461) | Canvas Save |
| `~/Downloads/motdeck-logs/<name>-<ts>.log` | `app.py:401-418` | log export |
| `/tmp`, `$TMPDIR` | `install_llamacpp.sh:79-84` (version probe, removed after) | install |
| `~/.local/bin` (uv) | `firstrun.sh:31-32` — astral.sh installer's own default | first run, only if `uv` is missing |
| `vendor/hermes/{node_modules,hermes_cli/web_dist}` | `install_component.sh:44-51`, `build_app.sh:123-130` | hermes install (upstream-gitignored build output) |
| `vendor/searxng/`, Odysseus's own sqlite DB inside `vendor/odysseus` | `install_searxng.sh:13-18`, `seed_odysseus_jan.py:99-127` | install / seed |

Recursive deletes exist in exactly two places and both are double-fenced under
`ROOT/data/models`: model delete (`app.py:1666-1694`, `_deletable_target` + a second
containment check) and download cleanup (`app.py:2027-2043`).

### We do NOT (each verified against the code)

- **No `sudo`** anywhere in our scripts, Swift, or Python (zero occurrences).
- **No writes to `/usr/local` or `/opt/homebrew`** by our code.
- **No `/etc` writes.**
- **No writes to system `/Library`** — every `/Library/` path in the tree is under
  `$HOME/Library` (`main.swift:130`, `seed_registry.py:18-21`, `migrate_jan_models.sh:16`).
- **No shell-rc modification** — nothing touches `~/.zshrc`, `~/.bash_profile`, `~/.profile`.
  `firstrun.sh:32` exports `PATH` **in-process only**.
- **No launchd/LaunchAgent/daemon installation** — the only `.plist` is the app bundle's own
  `Info.plist` (`build_app.sh:45,72`); no `launchctl` anywhere.
- **No `chown`**; the only `chmod`s target files inside the repo's `data/` or the built app.
- **No self-install into `/Applications`** — the app runs from wherever the user puts it.

### Honestly flagged

1. `bootstrap.sh:49` runs **`brew install`** for missing prerequisites (git/tmux/uv/python@3.12),
   gated by an interactive confirmation (or `--yes`). We never write into the Homebrew prefix
   ourselves, but this is the one path by which our script chain causes files to land there.
2. `firstrun.sh:31` uses **`curl -LsSf https://astral.sh/uv/install.sh | sh`** — the vendor's
   documented method, but a classic curl-pipe-to-shell with **no checksum verification**. We
   pass no `UV_INSTALL_DIR`/`CARGO_HOME`, so **we do not control where uv lands**; we merely
   assume `~/.local/bin` when extending our own subprocess `PATH`.
3. **One provisioned root** for both packaged build flavors:
   `~/Library/Application Support/MOT Deck`. A second root is an identity-migration defect.
4. `~/.hermes/config.yaml` is written by our own scripts/bridge while the guard's deny-list
   forbids the **agent** from writing it (`policy.yaml:24`). Intentional (MOT Deck manages
   Hermes's config; the agent must not), but it reads like a contradiction at first glance.
5. YAML round-trip writes to `~/.hermes/config.yaml` (`yaml.safe_dump`) **drop comments and
   key ordering** on the writes that add `mcp_servers` / `plugins.enabled`. Accepted property.
6. The app is **ad-hoc codesigned** (`build_app.sh:235-237`), not notarized — a fresh Mac may
   need a right-click-open / xattr clear.
7. Odysseus's default admin credentials live in `motdeck.yaml` in plaintext
   (`admin/admin123`) because the bridge logs in server-side. Loopback-only, personal use.
8. Secrets posture: cloud keys belong in `.env`, never in `motdeck.yaml`; the Capabilities
   writer refuses any `*_api_key` (app.py:788-790); Hermes redacts credentials in approval
   commands upstream before they reach our card.

---

## 14. Test & contract suite index

Run with the proxy env cleared (`unset ALL_PROXY all_proxy HTTP_PROXY http_proxy HTTPS_PROXY https_proxy`)
— otherwise the loopback-probing tests fail spuriously. Python tests are standalone
(`python3 bridge/tests/<file>.py`) and extract functions from `bridge/app.py` **by `ast`**, so
they need neither fastapi nor websockets. JS tests run with `node`.

| File | Pins |
|---|---|
| `bridge/tests/test_vision_content.py` | `build_user_content`: image parts vs plain string, oversize/malformed/non-vision refusals |
| `bridge/tests/test_thinking_sidecar.py` | `answer_hash`, sqlite sidecar store, order-consuming `attach_thinking` |
| `bridge/tests/test_hermes_sse_map.py` | `hermes_event_to_frames` — every gateway event → panel frame, incl. `description`/`guard_flag` notes |
| `bridge/tests/test_hermes_sessions.py` | session normalize + `hermes_messages_to_panel` (reasoning keys, reasoning-only turns kept, list flattening, precedence) |
| `bridge/tests/test_path_guard.py` | the guard's pure matcher (deny>allow>escalate, commonpath containment) + the bridge audit helper |
| `bridge/tests/test_mtp_detect.py` | registry `repo` persistence + the conservative MTP decision table |
| `bridge/tests/test_load_switch.py` | load/switch state machine, `wire_model_id`/`display_model_id`, live-id reconcile |
| `bridge/tests/test_port_kill.py` | listener-scoped port-kill command construction |
| `bridge/tests/test_model_delete.py` | `_deletable_target` containment guard |
| `bridge/tests/test_caps_map.py` | `caps_map_write` routing + secret/unknown-group refusals |
| `bridge/tests/test_audio_registry.py` | voice download→registry builder, the conservative `audio_format_for` Rescan classifier, `merge` audio semantics, and **the invariant against the real `api_models()`: audio never reaches `installed`** |
| `bridge/tests/test_audio_rows.js` | Audio-tab row/label helpers extracted from the panel (role-scoped default, engine label, escaping) |
| `bridge/tests/test_artifact_save.py` | artifact-save filename sanitizer (basename, ext whitelist, never-clobber) |
| `bridge/tests/test_artifact_kind_v2.js` · `test_fence_classify.js` | `artifactKind()` + fenced-block/"worthy" rules |
| `bridge/tests/test_csv_parse.js` | CSV parse/delimiter sniff/numeric sort |
| `bridge/tests/test_react_prep.js` | React source prep + pane clamp math |
| `bridge/tests/test_rewrite_cdns.js` | Tailwind CDN rewrite + nav-guard anchor rule |
| `bridge/tests/test_canvas_logic.js` | canvas split clamp, kind→CodeMirror mode, default filename |
| `bridge/contract_tests/test_hermes_ws_contract.py` | **pin-bump gate**: Hermes RPC method/event names, approval payload shape, `approvals.mode` default, path-guard hook seams, file_card signal |
| `bridge/contract_tests/test_seam.py` | structural seams (M0) |

Panel validation (no browser in the sandbox): extract each `<script>` block and
`node --check` it **separately**, `python3 -c "import ast; ast.parse(...)"` for `app.py`, and
a brace-balance count over the `<style>` blocks with scripts stripped.
