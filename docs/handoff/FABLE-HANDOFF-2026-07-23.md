> **DONE — implemented and shipped (marked 2026-08-20).**

# FABLE 5 → OPUS 4.8 EXECUTION HANDOFF (2026-07-23)

**Read order for a fresh session:** `CLAUDE.md` (canonical working memory — state, archaeology, protocols) → THIS file (execution plan) → `09_Ideas_StealList_and_Gaps.md` + `10_Modalities_Voice_and_Vision.md` (new roadmap inputs from Debi). Repo = github.com/Debkbas/new-harness (private); local clone `./harness/`; **sync rule and push flow are in CLAUDE.md — PAT is supplied by Debi per session in chat, never written to any file.**

## 1. Mode & protocol (NON-NEGOTIABLE — see CLAUDE.md §MODEL IDENTITY PROTOCOL)

You are **Opus 4.8 in temporary Opus-first BUILDER mode**. Fable 5 (orchestrator) is out of tokens and has pre-authorized this run via this handoff. Rules:
- Declare your model at session start; repeat "⚠️ Opus-first mode (builder)" at every major decision point.
- Execute the specs below; where a genuinely subtle decision is NOT specified, make the minimal safe choice, tag it **⚠️ PENDING FABLE QA** in CLAUDE.md, and continue — never present it as settled.
- **Oddities log:** maintain a section `## OPUS ODDITIES LOG (for Fable QA)` in CLAUDE.md — anything that felt out of the ordinary (weird upstream behavior, surprising output, flaky test, a spec that didn't match reality), one line each, even if you resolved it. Fable will QA the whole project against this log later.
- UI: FUNCTION only, in the existing editorial system (`:root` vars in bridge/panel/index.html). No new colors/layouts/type scales. `<!-- FABLE: style this -->` markers where aesthetics are needed. **Debi (2026-07-23): the current editorial design STAYS the default forever; OpenHuman-flavored bright theme etc. are OPTIONAL alternates, later, Fable-designed.**
- Ship small; every slice Mac-verified by Debi before the next; CLAUDE.md updated after every ship; commits via the /tmp-clone flow in CLAUDE.md; never edit vendor/; never run Hermes's in-app updater.
- Delegation: you may spawn further Opus subagents for mechanical sub-tasks with decision-free briefs (same report format: verified / shipped-unverified / stopped).

## 2. State snapshot (all detail in CLAUDE.md — trust it over memory)

- **DONE + Mac-verified:** M0/M1/M2 core; SearXNG; Rung D chat pane (sessions/duplicate/direct-lane/transparency contract); Hermes dashboard tab (pin v2026.7.20); Browse toggle (browsermcp stdio → Hermes+Odysseus); Models pane (registry, switch, eject, HF browser w/ sort+format+recency+in-app card); download manager (per-file Get, split-aware, pause/resume/cancel, parallel, progress); llamacpp+mlx+auto adapters (slices 1-3); LM Studio library import; MTP flags; engine label on runner card; fixed sidebar.
- **Shipped, Mac-verify PENDING:** aux runner engine-dispatch fix (Debi has Qwen3-VL-4B set as aux; needs Start test + Odysseus Background-Tasks wiring); MLX model switch end-to-end (mlx venv auto-install on first MLX start); MTP model load; download-manager pause/resume live test.
- **Environment facts:** llama-server binaries at `~/Library/Application Support/Jan/data/llamacpp/backends/*/macos-arm64/build/bin/` (Jan b9743) and `~/.lmstudio/extensions/backends/llama.cpp-mac-arm64-apple-metal-advsimd-2.25.2/` (newer). Registry `data/models.json`. Models: Jan folder (35B IQ4_XS + mmproj), LM Studio `~/.lmstudio/models` (~185GB), harness `data/models/` (downloads). Sandbox CANNOT reach api.github.com or HF directly (github.com git ops + jan.ai/github HTML fetch via web_fetch DO work); the Mac has full internet.

## 3. EXECUTION QUEUE (in order)

### 3.1 Cleanup slice — make the harness Jan-free (Debi: Jan gets fully uninstalled)
a. **Own pinned llama-server binary.** New `scripts/install_llamacpp.sh`: reads `runner.llamacpp_pin` (new harness.yaml key; also add `# pinned llama.cpp release tag (bNNNN)` comment) and downloads `https://github.com/ggml-org/llama.cpp/releases/download/<pin>/llama-<pin>-bin-macos-arm64.zip` to a temp file, unzips into `data/llamacpp/`, expects `build/bin/llama-server` inside (VERIFY the asset name + zip layout FIRST: `git ls-remote --tags https://github.com/ggml-org/llama.cpp.git | tail` for the newest bNNNN tag works from the sandbox; asset naming must be confirmed via web_fetch of the release page HTML or, failing that, the script must fail with a clear message listing what it looked for — tag ⚠️ if unconfirmed). chmod +x; echo the version (`llama-server --version` if supported, else the pin). Set the initial pin to the newest tag you verify.
b. **Binary discovery order** (start_component.sh llamacpp branch + bridge aux_start): explicit `runner.binary` → `data/llamacpp/build/bin/llama-server` (our pin, adjust to real zip layout) → Jan backends glob → LM Studio glob. Keep it one shared ordering.
c. **Migrate Jan models** into harness ownership. New `scripts/migrate_jan_models.sh`: for each `~/Library/Application Support/Jan/data/llamacpp/models/<id>/` with model.gguf: `mv` the folder to `data/models/<id>/` (same volume = instant), then re-run `python3 scripts/seed_registry.py` — BUT seed_registry must be updated FIRST so that (i) it scans `data/models/<id>/` dirs as source "local" entries (model.gguf + optional mmproj.gguf, same shape as jan-import, keep any ctx already in the registry for that id — merge rule: prefer existing entry's ctx when the fresh scan's is null), and (ii) jan-import scan naturally yields nothing once the folder is empty. Preserve the 35B's ctx 95536 (already in registry — verify it survives).
d. **Retire jan:** ONLY after Debi confirms a+b+c green on the Mac: remove the jan adapter branch from start_component.sh, `_jan_bin`/jan branch from bridge api_models, `adapter` comment values, aux jan pkill patterns can stay (harmless). Update harness.yaml comments. Then tell Debi to uninstall Jan desktop + delete `~/Library/Application Support/Jan` (models already migrated). Keep `adapter: lmstudio` reserved-but-unimplemented (fallback idea only).
e. Update CLAUDE.md throughout; Mac-verify sequence for Debi at each step (runner start on migrated path; chat; test_hermes.sh PASS; aux start).

### 3.2 Pin-bump pass (Hermes + Odysseus) — ISOLATED ship, nothing batched
- Hermes: newest tag via `git ls-remote --tags https://github.com/NousResearch/hermes-agent.git`; contract-check OUR surfaces in the new tag's source (dashboard flags --no-open/--skip-build/:9119; HERMES_DESKTOP cron ticker; loopback no-auth; config.yaml keys model.*/mcp_servers) exactly like CLAUDE.md documents for the 7.20 bump; then bump pin + Mac sequence (fetch tags, checkout, reinstall w/ web_dist rebuild, dashboard+chat+test_hermes+cron+browsermcp checks). Rollback documented.
- Odysseus: check upstream pewdiepie-archdaemon/odysseus for commits beyond pin e57f60bd; if bumping, re-read the M0 archaeology first (gotcha #8: reset --hard before checkout; seed script compatibility; chat_routes regressions). Contract-check: /api/chat_stream fields, session endpoints used by the Bridge proxy (list in CLAUDE.md Rung D notes), mcp_routes forms. If upstream is risky, defer with a note — bumping Odysseus is OPTIONAL this pass.

### 3.3 Mac-verify sweep (with Debi) — aux engine-dispatch, MLX switch, MTP load, pause/resume. Record results in CLAUDE.md.

### 3.4 Modalities intake (docs 09 + 10 — Debi wants these on the roadmap)
- Read both docs fully. Fold into CLAUDE.md roadmap: **Voicebox = adopt** (optional, off-by-default managed component; voice loop) — draft the component plan (install/start/stop/health card + where it plugs: Hermes/Odysseus TTS/STT settings) as a PROPOSAL section, ⚠️ PENDING FABLE QA, do not build without Debi's go.
- **ComfyUI = much later/maybe** (headless engine behind a future Fable-designed UI; gated on model-memory scheduling) — roadmap entry only.
- From doc 09: list the 🟢 NEW items into a "Backlog (from 09)" section verbatim-short, each tagged where it fits (M-milestone or Fable-UI queue). No scope expansion without Debi.

### 3.5 Standing queue (do not start without Debi's explicit go)
Browse slice 3 (jan-browser-mcp http :8181 — NOTE: with Jan uninstalled, verify the extension still functions standalone before wiring; it likely does, but tag it); Fable pass-2 UI (LM-Studio two-pane Models layout, top-right Search/Download view, light theme system, onboarding checklist/walkthrough — FUNCTION scaffolds only if Debi asks, from the queue notes; all styling deferred to Fable); file/artifact cards in chat; M5 (gateway/Telegram, Tailscale, parallel-worktree orchestrator via Hermes delegate_task).

## 4. Known traps (beyond CLAUDE.md's list — read that too)
- Panel JS validation: extract `<script>` → `node --check`; CSS brace-count; app.py `ast.parse`; bash -n. ALWAYS before push.
- Paths contain spaces everywhere ("Application Support", "Claude Proj Rootz") — argv arrays in bash, quoted vars, never unquoted expansions.
- WKWebView: no alert/confirm/prompt (silent no-ops) — inline two-step patterns instead.
- The sandbox cannot unlink files in the mounted folders (stale git locks → Debi removes them; scripts lose +x on copy — chmod in the /tmp clone before commit).
- `_script` subprocess timeout is 1800s — keep any script wait loops under it.
- Panel/bridge changes need only a bridge restart + app relaunch; main.swift changes need `./scripts/build_app.sh`.
- Odysseus proxy admin creds come from harness.yaml components.odysseus.admin_user/admin_password.
- Debi's sidebar footer ("HERMES · ODYSSEUS / BRIDGED, NEVER FORKED") is to be HIDDEN in the final app — remove `.side-foot` when convenient (queued, trivial).

## 5. Report format (end of every working session)
Lead "**vX shipped**"-style outcome; per-item verified / shipped-unverified / queued; Mac-verify steps for Debi (shortest path, expected output stated); CLAUDE.md updated + pushed; ODDITIES LOG appended; security line (PAT active → remind Debi of revocation window).
