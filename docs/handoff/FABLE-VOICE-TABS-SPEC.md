> **DONE — implemented and shipped (marked 2026-08-20).**

# FABLE SPEC — Voice components as first-class tabs (VoiceStudio + Voicebox)

Fable 5, 2026-08-07. For Opus 5 (or Opus 4.8) builder sessions. Identity protocol
applies: builders declare themselves, tag judgment calls ⚠️ PENDING FABLE QA, and
never present subtle decisions as settled. Ship rule: `./scripts/ship.sh` only.

## Goal

Two new components, each wired exactly like Odysseus/Hermes are today:

- **VoiceStudio** — https://github.com/debpalash/VoiceStudio
- **Voicebox** — https://github.com/jamiepine/voicebox (MIT, FastAPI + MLX sibling
  stack; earlier recon notes: REST on :17493, ships an MCP server, v0.5.x)

Each gets: a pinned vendored submodule, install/start/stop lifecycle under the
Bridge with a Mission Control card, health checks, a **native tab** in the app
(like Odysseus/Hermes), and — where the component ships an MCP server — idempotent
registration into Hermes (`~/.hermes/config.yaml` `mcp_servers` yaml round-trip)
and Odysseus (`POST /api/mcp/servers`), reusing the EXISTING browsermcp helper
pattern in bridge/app.py.

## Phase 0 — RECON FIRST (mandatory, before any code)

Today's lesson applies: no building on assumptions. For EACH repo, an Explore-style
read-only recon with file:line evidence:

1. License (must be permissive; AGPL = flag to Debi before proceeding).
2. Install story: python version, package manager, deps (torch? mlx? node build
   step?), disk size estimate. We are macOS-native, NO Docker.
3. Serve story: exact command to run headless, port (default + how to override),
   bind address (loopback-only required), auth (token/none), web UI path.
4. Does it have a web UI suitable for a tab? X-Frame-Options? (We load tabs
   top-level, so frame headers don't matter — pattern proven with Odysseus.)
5. Model management: what models it downloads, where, sizes → RAM/disk ledger
   impact (our `memory.budget_gb` accounting should count its resident models —
   at minimum document; wiring into the ledger is a Fable follow-up).
6. MCP server: transport (stdio/http/sse), exact command/url → registration form.
7. Latest release tag → the PIN. Never track main.
8. Anything that phones home / telemetry → list for disabling.

Recon output goes into CLAUDE.md as a dated block. If the two repos conflict with
anything in this spec, THE RECON WINS — update the spec notes and tag it.

## Phase 1 — component wiring (one component at a time; VoiceStudio first per Debi)

Mechanical, mirrors existing components (read start_component.sh's odysseus branch
+ install_component.sh first):

1. `harness.yaml`: `components.voicestudio` / `components.voicebox` blocks —
   repo, pin, port (from recon; avoid collisions with 8700/7860/9119/8080/6767/6768),
   `installed: false`, `depends_on: []` (add `runner` ONLY if recon shows it can use
   an OpenAI-compatible LLM endpoint — then wire it to :6767 like the others).
2. `scripts/install_component.sh` branch: shallow submodule at the pin →
   `data/<name>-venv` (uv/pip, wheels; `--yes` flag; loud failures).
3. `scripts/start_component.sh` branch: launch headless on its port, loopback
   bind, pid file + log under data/, port-kill ONLY with `-sTCP:LISTEN` (standing
   rule), TRIES generous for first model load.
4. Bridge: add to the components list (card appears in Mission Control with
   Install/Start/Stop/log, start-plan dependency closure picks it up free).
5. Contract tests: pin whatever internal surface we depend on (serve command
   flags, MCP config shape) so pin-bumps trip loudly.

## Phase 2 — native tab (app/main.swift)

Mirror the Hermes tab addition exactly: new segment in the NSSegmentedControl,
lazy-loaded top-level WKWebView pointing at the component's local URL, uiDelegate +
navigationDelegate set (failed-load placeholder + ⌘R retry), underPageBackground
dark, included in tabChanged + currentWebView. DropOverlay stays Mission-Control-
only. Tab order: Mission Control · Odysseus · Hermes · VoiceStudio · Voicebox.
⚠️ Shell recompile ships via ship.sh (it detects main.swift changed).

## Phase 3 — MCP + integration (per recon)

- Register the component's MCP server into BOTH Hermes and Odysseus using the
  existing browse-toggle helper pattern (idempotent add/remove; Hermes picks up
  on new chats). A Capabilities toggle like the Browse chip is the UI surface —
  reuse that grammar, no new design.
- If the component can use a local LLM endpoint, point it at the runner (:6767)
  the same way Odysseus is seeded — never at a cloud default.

## Explicitly Fable-gated (do NOT build without a Fable-authored spec)

- Any chat-composer voice UX (dictation hotkey, TTS toggle on replies).
- Ledger enforcement for voice models (budget math changes).
- Any new visual surface beyond the stock tab + component card.

## Definition of done (per component)

Install from panel → card green → tab loads its UI → one real round-trip
(VoiceStudio: whatever its core demo flow is per recon; Voicebox: one STT or TTS
call) → MCP tools visible in Hermes dashboard banner → all tests + contract suite
green → CLAUDE.md updated → committed via the normal flow. Ship = `./scripts/ship.sh`.
