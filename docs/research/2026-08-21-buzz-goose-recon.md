# Recon: Buzz + Goose (2026-08-21)

> ⚠️ **INSTRUMENT LIMIT — read this first.** The session VM was dead: **no bash, no git clone, no web_fetch.**
> Every fact below comes from **WebSearch result summaries only** — no file was read at source level, no
> `--help` was run, no LICENSE file was opened, no tag/sha was resolved. Nothing here is contract-grade.
> Facts marked ⚠️ need source-level verification before ANY build slice. Verdicts are deliberately conservative.

---

## 1. Buzz — disambiguation (there are two, and they are unrelated)

**Both repos exist.** The user's link resolves to the Block one.

| | **block/buzz** (the link given) | **chidiwilliams/buzz** (the famous one) |
|---|---|---|
| What | "A hive mind communication platform" — self-hosted team chat/workspace where humans and AI agents share channels, threads, canvases, git patches, workflows, voice huddles | Desktop GUI around Whisper — offline audio transcription + translation |
| License | **Apache-2.0** ⚠️ | **MIT** ⚠️ (App Store "Pro" tier is a separate paid build) |
| Stack | Rust relay (single binary: WebSocket relay + REST API + **web UI** in one process); **Tauri + React** desktop; `buzz-cli` (JSON-in/JSON-out, built for LLM tool calls); mobile | Python/Qt desktop app; supports whisper, whisper.cpp, faster-whisper, HF whisper models, OpenAI API |
| Substrate | **Nostr** — every message/reaction/workflow step/review/git event is a signed Nostr event in one log, same shape whether author is human or agent | n/a |
| Origin | Block (block.xyz), hosted option at buzz.xyz; spans 5 repos, block/buzz is the OSS relay+desktop+mobile+CLI | Independent |

### 1a. block/buzz — verdict: **REJECT as a component (doctrine), WATCH the idea**
The blocker is infrastructure, not licence or intent:
- The relay **requires Postgres + Redis + an S3-compatible object store + a persistent git volume** ⚠️ — four
  services. Upstream's own path is `deploy/compose` (**Docker Compose v2.24.4+ required** ⚠️).
- That is a direct collision with our **no-Docker, no-heavy-infra, one-process-per-component** doctrine. Running
  it "natively" means we own a Postgres + Redis + MinIO install on Debi's Mac. Idle footprint quoted ~1.5–2 GB RAM ⚠️.
- Dev build needs **Rust 1.88+, Node 24+, pnpm 10+, just** (or Hermit) ⚠️ — heavier than any component we pin today.
- It also isn't a capability we lack; it is a *collaboration surface* — the same product-class objection that
  parked mindshub and omnigent. A single-user local deck has nobody to Buzz with.

**What IS worth keeping:** the relay serves its **web UI from the same process**, so IF someone ever runs a Buzz
relay elsewhere (a VPS), pointing a tab at it is trivial — it is a URL, not a component. And a community gist
already documents a **Hermes Agent + Buzz** gateway integration ⚠️ — i.e. our existing Hermes could *join* a Buzz
without us hosting anything. That is the only shape I would build, and only on demand.

### 1b. chidiwilliams/buzz — verdict: **REJECT as a component, RECOMMEND as an ordinary Mac app**
It is a native desktop GUI (no server, no web UI) → nothing to put in a tab. Same ruling shape as HermesOffice:
if Debi wants it, she installs the .dmg. **And we already own this capability better**: our voice lane runs
mlx-whisper + parakeet (`stt-mlx`, `stt-mlx-audio`) natively with a live VAD segmenter and dictation. Buzz would
duplicate it with a Qt app we cannot theme, tab, or ledger.

---

## 2. Goose — it moved, and the earlier rejection is now half-wrong

**Home org changed: `block/goose` → `aaif-goose/goose`.** ⚠️ Block **donated goose to the Agentic AI Foundation
(AAIF) at the Linux Foundation** (announced ~2026-04-07), alongside Anthropic's MCP and OpenAI's AGENTS.md.
`block.github.io/goose` URLs are being migrated to `goose-docs.ai` ⚠️. The old org still 302s in practice ⚠️.

| Fact | Value | Confidence |
|---|---|---|
| License | **Apache-2.0** | ⚠️ search-summary only |
| Language | **Rust** | ⚠️ |
| Latest release | **v1.46.0** (≈2026-08-12) | ⚠️ — resolve the sha at build time, never pin a floating tag |
| macOS arm64 asset | `goose-aarch64-apple-darwin.tar.{gz,bz2}` on the releases page | ⚠️ — **exactly the OpenCode shape** (prebuilt darwin-arm64 archive) |
| Surfaces | **CLI** + **Desktop app** + **`goose serve`** (a.k.a. `goosed`) | ⚠️ |
| `goose serve` | Rust/**axum** server exposing the **Agent Client Protocol over HTTP + WebSocket**; described as REST+SSE with ~103 endpoints; flags `--host --port --tls`; **loopback-only when `--host` is 127.0.0.1** | ⚠️ |
| **Web UI?** | **NO first-party browser UI found.** `goose serve` is an *API for clients* — Desktop spawns `goosed` as a child and talks HTTP/WS to it; mobile + Slack bots connect the same way | ⚠️ — this is the load-bearing finding, verify hardest |
| MCP | first-class ("extensions"), 15+ providers | ⚠️ |
| **Tool calling** | **REQUIRED** — upstream wording: "goose can be powered by any language model that **has tool calling capabilities**." No text/diff fallback surfaced. Block even fine-tuned a small model specifically to make tool-calling work | ⚠️ — confirms the original rejection's *technical* premise |

### 2a. The `localhost:7681` sighting is a red herring — do not build on it
One write-up shows a goose session in a browser at `:7681`. **7681 is ttyd's default port.** That is almost
certainly a third party wrapping the goose **CLI** in ttyd, not a goose web UI. ⚠️ Verify — but plan as if there
is no browser UI, because the primary sources describe `goose serve` as a client API, not a page.

### 2b. Connecting to our runner (:6767) — this part is clean
llama.cpp/mlx are OpenAI-compatible, and goose's documented pattern is to select the **`openai` provider** and
repoint it:
```
GOOSE_PROVIDER=openai
OPENAI_HOST=http://127.0.0.1:6767
OPENAI_BASE_PATH=v1/chat/completions      # note: PATH, not a bare /v1  ⚠️
OPENAI_API_KEY=<anything; local runner ignores it>
```
Persistable in `config.yaml` (name / engine / base_url / models) ⚠️. Same seam we already solved for OpenCode —
**and the same MLX trap applies**: our MLX wire id is an absolute *path*, so any `provider/model` string-split on
goose's side would shred it. Key by the slash-free registry id, put the wire id in the model's own `id` field.
⚠️ Verify how goose parses model ids before writing a config.

### 2c. The user's ruling, answered
> *"If the only issue was that smaller models without tool calls won't work, let's add it — and ensure we show it won't work."*

The tool-calling issue is **real and confirmed** — but it is now a *labelled constraint*, exactly like OpenCode:
we ship `bridge/modeltools.py`, the green **`tools` pill**, and the start-plan warning. So the gate exists.
**The tool-calling objection no longer blocks adoption. The integration SHAPE does.**

### 2d. Verdict — **RECON-more-when-VM-returns, leaning ADOPT as a PTY lane (not a tab component)**

Three candidate shapes, ranked:

1. **PTY lane, like aider** (recommended). `goose` CLI in an xterm.js terminal over our existing
   `bridge/pty_aider.py` machinery (origin-gated WS, `\x1b[RESIZE:c;r]`, killpg teardown). We already own every
   piece; the second lane costs a generalised `pty_lane.py` + a page + a tab. Prebuilt darwin-arm64 archive means
   **no Rust toolchain, no build step** — installer shape identical to OpenCode's (download, sha-verify, extract).
2. **`goose serve` as a component + our own thin UI.** Honest but expensive: ~103 endpoints of a *bespoke* API
   (ACP-flavoured) that we would be re-implementing a client for, with a pin-bump contract surface to match. Only
   worth it if the PTY lane proves unpleasant.
3. **Desktop app.** Reject/launch-external — nothing to tab, and it spawns its own `goosed`.

**Blocking unknowns before slice 1:** (a) is there truly no served UI; (b) does the CLI need a TTY / does it
behave in a PTY without a desktop; (c) telemetry & auto-update defaults (OpenCode needed `autoupdate:false` +
`OPENCODE_DISABLE_AUTOUPDATE`; assume goose has an equivalent until proven otherwise); (d) does it write to
`~/.config/goose` and can it be XDG-confined into `data/goose/xdg` the way OpenCode was; (e) whether it shells
out to Docker for anything (the old "Docker-ish" note — the Docker material found this round was all *Docker
Model Runner as a provider*, i.e. optional, **not** a runtime dependency ⚠️ — the original rejection may have
over-read this).

---

## 3. Follow-up checklist for the build slice(s) — run these the moment the VM is back

**Verify-before-build (all of §2's ⚠️ rows, at source):**
1. `git ls-remote --tags https://github.com/aaif-goose/goose` → resolve v1.46.x (or newer) to a **sha**; confirm
   `block/goose` redirects rather than diverges.
2. Read `LICENSE` in the checkout (confirm Apache-2.0 verbatim, check for a NOTICE).
3. Download `goose-aarch64-apple-darwin.tar.gz`, record size + sha256, confirm it is a Mach-O arm64 binary and
   that the archive carries no installer script that phones home.
4. `goose --help`, `goose serve --help`, `goose configure --help` → capture the real flag surface. **Specifically
   confirm/refute: any `web`/`ui` subcommand, any static-asset serving in `goose serve`.**
5. `grep -rn` the source for `update`/`telemetry`/`analytics`/`posthog`/`sentry` → find the disable switches;
   pin them in a contract test like we did for `--analytics-disable` (aider) and `OPENCODE_DISABLE_AUTOUPDATE`.
6. `grep -rn` for `xdg`/`dirs::config_dir`/`~/.config/goose` → prove XDG confinement works into `data/goose/`.
7. `grep -rn` for `docker` in the runtime crates (not docs) → settle the Docker question with evidence.
8. Find where tool-calling is required (the provider/agent loop) → get a **file:line** for the pill's gate copy,
   and confirm there is no text-edit fallback we could opt into.
9. Confirm the model-id parsing path (does it split on `/`?) before writing any provider config for MLX.

**Then, slice 1 (PTY lane) — mirrors the aider slice exactly:**
- `build.goose_pin` in motdeck.yaml (sha, not tag); `scripts/install_goose.sh` (download + sha-verify **before**
  extract → `data/goose/`; **must call `scripts/flip_installed.py`** — the standalone-installer trap that bit
  opencode and searxng); log in `_LOG_NAMES` + `LOG_SOURCES`; **exec bit staged via `git update-index --chmod=+x`**
  (test_script_hygiene now enforces this).
- Generalise `bridge/pty_aider.py` → shared PTY lane (origin gate mandatory, 4403/4409, killpg, RESIZE).
- Seed the provider config into an XDG-confined home; runner id keyed slash-free; `tools:false` live model →
  **warn, don't refuse** (start-plan wording already exists for opencode — reuse it verbatim).
- Nav registry entry + Swift tab (strip budget: check width — we are at ~808/830pt, so the title must be short:
  **"Goose"** is fine).
- Contract test pinning: the disable-telemetry/auto-update flags still exist upstream; the config path; the
  tool-calling requirement.

**Buzz:** no slice. If Debi wants it, the answer is a URL to someone else's relay, or `brew`/dmg for the
transcription app. Revisit block/buzz only if it ever ships a single-binary embedded-storage mode.
