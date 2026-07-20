# New Harness — working memory (canonical project home)

> For Claude: read this first, then `00_START_HERE.md` (its primer paragraph rehydrates a fresh session). This folder is the **single source of truth** for the harness project as of 2026-07-20. The copies of 00–06 in the old `outputs` folder are frozen; the v1 codebase lives in the `Harness project` folder (working scaffold — see 07).

## Repo

- **GitHub: https://github.com/Debkbas/new-harness (private) — the single source of truth.** `./harness/` is the local clone; `main` pushed 2026-07-20 (`c11f049`: v1 scaffold + v2 doc set in `docs/handoff/`).
- **Sync rule:** the .md files at this folder's root are working copies; any doc change must be copied into `harness/docs/handoff/` and committed. When in doubt, the repo wins.
- **Auth:** push with a GitHub PAT supplied per-session in chat — never store it in any file or remote URL (`git remote` stays tokenless). Debi: revoke the 2026-07-20 token after this session.
- **Migration trap from the sandbox session:** the cowork sandbox cannot unlink files in this folder, so git left stale `*.lock` files (`.git/HEAD.lock`, `.git/objects/maintenance.lock`, submodule `index.lock`s). If git on the Mac refuses to commit, delete those lock files first — they are safe to remove when no git process is running.

## Doctrine

`agent-kit/DELEGATION-DOCTRINE.md` applies to this project in full, with **one amendment (2026-07-20): all UI design / look-and-feel work is Fable 5 only** — builder subagents may implement UI solely from a Fable-authored, decision-free spec. See `08_Interface_Strategy.md` §Governance.

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
- **Remaining M1 slices:** the Retry-on-failed button + idempotent closure already cover most of "Repair"; still to add — a persistent `needs-repair`/`degraded` state (runtime health-loss detection after a component was green), and install-time closure (flip an *uninstalled* component → install its deps too behind one approval). Model download is a future node (M2 model browser makes the model dynamic).
- **New M1 failure archaeology:** seed matched the endpoint by `base_url`, but with a fixed id — when the URL changed (:1337→:6767) it tried to INSERT a duplicate id → PK collision → silent rollback → Odysseus stuck on the dead :1337 (Error 503). FIX: match by stable id, update in place (`1cf7f3e`).

## State (2026-07-20)

- **Code moved: the scaffold now lives at `./harness/`** (git repo + vendor submodules intact; `data/` venvs and `dist/` were regenerated on the Mac via `./scripts/bootstrap.sh`). The old `Harness project` folder is a frozen archive.
- **M0 COMPLETE (verified 2026-07-20).** Both components green under the Bridge (:8700), each proven end-to-end:
  - **Hermes** green via `hermes serve` :9119; `scripts/test_hermes.sh` = `PASS` (real shell tool call through Jan).
  - **Odysseus** green :7860; real chat reply from `Qwen3_6-35B-A3B-…-IQ4_XS` @ Jan :1337, ~60 tok/s. One-button install AND connect from the panel (admin/admin123; Jan endpoint auto-seeded as default model via `scripts/seed_odysseus_jan.py`).
  - Latest repo tip: `4c0ffba`. Odysseus pin bumped to `e57f60bd` (old `168f5930` had a chat NameError).
- All licensing verified from LICENSE files: Hermes MIT, Odysseus MIT, Jan Apache-2.0; only SearXNG is AGPL.

## Next actions (in order)

1. **Post-M0 spikes (04 §Prototypes)** before committing to M1: headless Jan (`jan serve` :6767), CLI model download, WKWebView embed of :7860, native SearXNG on macOS/arm64.
2. **M1** — runner slot (make Jan a managed headless component behind the adapter) + the one-switch provisioning pipeline (dependency closure, config fan-out, Repair verb). Odysseus/Hermes connect steps built in M0 (`seed_odysseus_jan.py`, Hermes config patch) are the seeds of this.
3. **M2 interface (08)** — reskin/deep-link the Odysseus webview into a Mission Control tab (Fable-only UI work).

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
