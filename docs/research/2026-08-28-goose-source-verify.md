# Source-verify: goose PTY lane (2026-08-28) — roadmap §2.2b

> Executes the 9-item verify-before-build checklist from
> `docs/research/2026-08-21-buzz-goose-recon.md` §3, against the live repo/releases on 2026-08-28.
> Method: `git ls-remote` + shallow clone at the tag + downloaded release asset, all in the session
> scratchpad (nothing installed, nothing changed in the repo). GitHub REST API was rate-limited
> (the house lesson held); everything below was resolved via git/HTML/downloaded artifacts instead.
> Every claim is source-level or empirically executed unless marked otherwise.

## Verdict: **BUILD-READY** (pins at the bottom)

The 2026-08-21 recon's standing conclusions all survived verification, with two upgrades:
the "no browser UI" finding is now confirmed at the real CLI surface, and the "tool-calling
required, no fallback" finding needs a footnote (an experimental **toolshim** exists, but its
interpreter backends are ollama/local-only, so it does not change our plan). One drift item:
**v1.48.0** superseded v1.46.0, and **v2.0 release candidates exist on the tag list** — pin the
sha, ship 1.48.0, and expect a v2 evaluation cycle later.

---

## The 9 checklist items

### 1. Tag → sha; block/goose redirect ✅
- `git ls-remote --tags https://github.com/aaif-goose/goose`:
  **v1.48.0 = `25021517f12cab87c94bed0874fe7d28168dc264`** (latest stable; v1.47.0 = `f9c7aacc…`,
  v1.46.0 = `98c11ce2…`). Newer tags exist but are RCs: `v2-rc.1`, `v2.0.0-rc-04-27-0`.
- `https://github.com/aaif-goose/goose/releases/latest` resolves to **v1.48.0** (not an RC).
- `curl -sI https://github.com/block/goose` → **HTTP 301 → https://github.com/aaif-goose/goose**.
  Redirect, not divergence (the old remote serves the same HEAD).

### 2. LICENSE at source ✅
- Shallow clone at v1.48.0 (`git rev-parse HEAD` = `25021517…`, matches the tag sha).
- `LICENSE` is **Apache License Version 2.0, January 2004** verbatim. **No NOTICE file exists**
  (`ls NOTICE*` empty) — nothing extra to carry.
- Foundation status confirmed at source: `README.md:29` — "goose is part of the Agentic AI
  Foundation (AAIF) at the Linux Foundation"; `GOVERNANCE.md:193` — "Founded by Block and now
  stewarded by AAIF … a Series of LF Projects, LLC." No license drift.

### 3. darwin-arm64 asset ✅
- `goose-aarch64-apple-darwin.tar.gz` (release v1.48.0):
  - **size: 90,382,385 bytes**
  - **sha256: `d502945fca78d8e58c8f56932973f454ad57d0754b272f5d44f696a4722da49a`**
  - contents: exactly two entries — `./` and `./goose`. **No installer script, no phone-home,
    nothing else in the archive.**
  - `file` on the extracted binary: **Mach-O 64-bit executable arm64** (270,423,136 bytes,
    sha256 `e900f1b96662818791ee599c58ea0e44204ca29579dd182ecc238b732ef5d768`).
- The repo's `download_cli.sh` (a separate release asset, which we will NOT use) only curls
  GitHub release URLs — no analytics endpoint. Our installer replicates its job anyway.
- Caveat: sha computed locally from a single download; the API digest field was unavailable
  (rate limit). Cross-check once at install time from a second network if paranoid.

### 4. Real CLI flag surface — **no web/ui subcommand, confirmed** ✅
Ran the actual binary (env-confined, see item 6). `goose --help` subcommands:
`configure, info, doctor, mcp, acp, serve, session, run, recipe, skills, plugin, schedule,
gateway, update, term, local-models, completion, review, help`. **No `web`, no `ui`.**
- `goose serve --help`: "Start **ACP server over HTTP and WebSocket**". Defaults
  `--host 127.0.0.1 --port 3284`; `--tls`; `--platform cli|desktop`;
  **auth required by default** — refuses without `GOOSE_SERVER__SECRET_KEY` unless
  `--dangerously-unauthenticated`; `--allowed-origin` CORS control. It is a client API,
  not a page — the load-bearing "no first-party browser UI" finding **holds at v1.48.0**.
- `goose session --help`: interactive chat sessions with `--resume/--name/--fork/--history`;
  it can even import Claude Code `.jsonl` sessions. This is the PTY-lane entrypoint.
- New-since-recon subcommand `term` ("Terminal-integrated goose session") exists —
  uninvestigated, not needed for the lane (honest limit).

### 5. Telemetry / auto-update switches ✅
- Telemetry is **PostHog, strictly opt-in**: `crates/goose/src/posthog.rs` —
  `is_telemetry_enabled()` "Returns true **only if the user has explicitly opted in**"
  (posthog.rs:42-52). Kill switches, both verified at source:
  - env: **`GOOSE_TELEMETRY_OFF=1`** (posthog.rs:22-27)
  - config: **`GOOSE_TELEMETRY_ENABLED: false`** (posthog.rs:20)
- **No startup auto-update and no startup update check** in goose-cli (grep across
  `crates/goose-cli/src` found none); `goose update` is a manual subcommand
  (`crates/goose-cli/src/commands/update.rs:294`). The only auto-update machinery is for
  user-installed *plugins* (`crates/goose/src/plugins/mod.rs`) — we install none.
- Contract-test pins: `GOOSE_TELEMETRY_OFF`, `GOOSE_TELEMETRY_ENABLED`, and the absence of
  a CLI self-update-on-start.

### 6. XDG confinement — **empirically proven** ✅
Ran `env -i HOME=<scratch>/fakehome … ./goose --help/--version/run`:
- Config read from `$HOME/.config/goose/config.yaml`; custom providers dir is
  `$HOME/.config/goose/custom_providers/` (`crates/goose/src/config/declarative_providers.rs:21-23`,
  docs `documentation/docs/getting-started/providers.md:482`).
- The only writes landed in **`$HOME/.local/state/goose/logs/cli/<date>/*.log`**.
  Nothing escaped the fake HOME. Confinement into `data/goose/xdg` works exactly like OpenCode's.
- Headless note: set **`GOOSE_DISABLE_KEYRING: true`** in the seeded config
  (`crates/goose/src/config/base.rs:101`, used throughout upstream's own tests) so the PTY lane
  never triggers a macOS Keychain prompt; secrets then come from env/config.

### 7. Docker — settled: **optional, not a runtime dependency** ✅
All runtime hits are either (a) an opt-in flag to run *extensions* inside a user-specified
container — `crates/goose-cli/src/cli.rs:136` ("Docker container ID to run extensions inside"),
executed at `crates/goose/src/agents/extension_manager.rs:1564,1639` only when configured — or
(b) regex *patterns* in the security scanner (`crates/goose/src/security/patterns.rs:246`,
`security/egress_inspector.rs`) that inspect shell commands, and (c) docs/Dockerfile for building.
The original rejection's "Docker-ish" note was indeed an over-read. The empirical run (item 9)
touched no Docker.

### 8. Tool-calling requirement — confirmed, with a new footnote ✅
- Requirement stands: docs `documentation/docs/getting-started/providers.md:53` — "**o1-mini and
  o1-preview are not supported because goose uses tool calling**"; provider model filtering drops
  models without `tool_call` capability (`crates/goose-provider-types/src/base.rs:584`).
- **NEW since the recon: a "toolshim"** (`crates/goose/src/providers/toolshim.rs`) emulates tool
  calls for non-tool models by piping text through an interpreter model. BUT its backends are
  **only `ollama` or `local`** (goose's own bundled llama.cpp local-inference)
  (toolshim.rs:66-81: `parse_toolshim_backend` accepts `ollama|local|llama.cpp`), enabled via
  `GOOSE_TOOLSHIM=true` + `GOOSE_TOOLSHIM_OLLAMA_MODEL`/`GOOSE_TOOLSHIM_MODEL`
  (`crates/goose/src/model_config.rs:245,261`), and upstream marks it experimental
  (`documentation/docs/experimental/index.md:24`). It cannot point at our :6767 OpenAI-compat
  runner, so it does not change slice 1: **keep the `tools` pill + warn-don't-refuse plan**;
  pill gate copy can cite providers.md:53 and base.rs:584. Toolshim is a possible future opt-in,
  not a dependency.

### 9. Model-id parsing — **no `/` split; MLX path ids are safe** ✅
- `GOOSE_MODEL` is read **verbatim** from env or config and passed whole into the request:
  `crates/goose-cli/src/session/builder.rs:382`, `crates/goose-cli/src/commands/configure.rs:953`.
  Provider and model are separate keys (`GOOSE_PROVIDER` + `GOOSE_MODEL`) — there is no
  `provider/model` composite string anywhere on this path.
- Repo-wide grep for `/`-splitting in provider code found only Google model-listing, Azure
  Foundry deployment names, and URL-path helpers — none touch the OpenAI provider's model id.
- Empirically: `GOOSE_MODEL: test-model` went out on the wire unmodified (item: empirical run).
  Still key the registry entry slash-free on our side, as doctrine says — but goose itself will
  not shred an MLX absolute-path id.

---

## The :6767 config — verified shape (and an empirical smoke run)

The recon's guessed env shape was right, now confirmed as ConfigKeys with defaults
(`crates/goose-providers/src/openai.rs:647-666`): `OPENAI_API_KEY` (secret), `OPENAI_BASE_URL`,
`OPENAI_HOST` (default `https://api.openai.com`), **`OPENAI_BASE_PATH` (default already
`v1/chat/completions`)**, `OPENAI_CUSTOM_HEADERS`, `OPENAI_TIMEOUT` (default 600).

**Executed end-to-end** with the confined home and this seeded `config.yaml`:

```yaml
GOOSE_PROVIDER: openai
GOOSE_MODEL: test-model
GOOSE_DISABLE_KEYRING: true
GOOSE_TELEMETRY_ENABLED: false
OPENAI_HOST: http://127.0.0.1:6767
OPENAI_BASE_PATH: v1/chat/completions
```

`OPENAI_API_KEY=dummy goose run -t "say hi"` → banner rendered, session `20260828_1` created,
request hit **`http://127.0.0.1:6767/v1/chat/completions`** and came back
`401 Unauthorized: Invalid API Key` from the live runner. So: fully headless (no TTY tricks, no
desktop, no telemetry prompt, no keychain prompt), config honored, correct URL composed.
**Build-slice note:** our runner at :6767 evidently validates the bearer key — seed the runner's
real key into the goose env/config (or confirm the runner's permissive mode) rather than assuming
"any key works", which the old recon assumed. This is a harness-side detail, not a goose problem.

Alternative config route (if we ever want goose to list multiple runner models): a **declarative
custom provider** JSON in `~/.config/goose/custom_providers/<name>.json` with
`engine: "openai"`, `base_url` (full path incl. `/v1/chat/completions`), `api_key_env`, and a
`models: [{name, context_limit}]` list (providers.md:481-508). Nice-to-have, not needed for slice 1.

## goosed / sessions, for the PTY embed

- PTY lane runs **`goose session`** (alias `s`) in xterm.js over the generalized `pty_lane.py` —
  resume/fork/name flags exist for daily-use journeys; sessions persist under the confined XDG
  state dir; `session list/export/import` cover recovery.
- `goose serve` (goosed) stays out of scope: ACP-over-HTTP/WS for *clients*, secret-key-gated by
  default, loopback default `127.0.0.1:3284`. Shape 2 from the recon remains "only if PTY proves
  unpleasant".

## Drift since 2026-08-21 (recon → today)

| Item | 08-21 recon said | Verified 08-28 |
|---|---|---|
| Version | v1.46.0 ⚠️ | **v1.48.0** stable (releases/latest); v1.47.0 in between; **v2.0 RC tags exist** — sha-pin insulates us |
| Org/license | aaif-goose, Apache-2.0 ⚠️ | Confirmed at source; block/goose 301s; no NOTICE |
| darwin-arm64 asset | exists ⚠️ | Confirmed + size/sha recorded; single-binary archive |
| No browser UI | "verify hardest" ⚠️ | **Confirmed** — no web/ui subcommand; serve is ACP API |
| Tool calling required | yes, no fallback ⚠️ | Required, but experimental **toolshim** exists (ollama/local backends only — unusable for :6767, plan unchanged) |
| Docker | probably optional ⚠️ | **Optional, proven at source** |
| `:7681` ttyd sighting | red herring | Nothing in source serves a terminal page; stands |
| New surface | — | `term`, `plugin`, `gateway`, `local-models` subcommands; `goose-local-inference` crate (bundled llama.cpp) — all ignorable for slice 1 |

## BUILD-READY pin sheet (for slice 1)

```
build.goose_pin:
  repo:    https://github.com/aaif-goose/goose        # block/goose 301s here
  tag:     v1.48.0
  sha:     25021517f12cab87c94bed0874fe7d28168dc264   # pin the sha, never the tag
  asset:   goose-aarch64-apple-darwin.tar.gz
  size:    90382385
  sha256:  d502945fca78d8e58c8f56932973f454ad57d0754b272f5d44f696a4722da49a
  contains: ./goose (Mach-O arm64; binary sha256 e900f1b96662818791ee599c58ea0e44204ca29579dd182ecc238b732ef5d768)
```
Seed config (XDG-confined into `data/goose/xdg/.config/goose/config.yaml`): the six-line YAML
above, plus the runner's REAL api key in env. Contract-test pins: `GOOSE_TELEMETRY_OFF` env +
`GOOSE_TELEMETRY_ENABLED` config key exist; no CLI self-update at startup (`update` is a
subcommand); `OPENAI_HOST`/`OPENAI_BASE_PATH` ConfigKeys exist with the defaults above;
`GOOSE_DISABLE_KEYRING` honored; tool-calling requirement (providers.md:53 / base.rs:584).
Installer: download → sha-verify **before** extract → `data/goose/` → **call
`scripts/flip_installed.py`** → exec bit via `git update-index --chmod=+x`. Tab title "Goose".

## HONEST LIMITS

- No interactive `goose session` was run against a real tool-calling model (no key to the live
  runner from this recon sandbox); headless `goose run` + full config/wire path was executed
  instead. The build slice must walk the interactive journey per the doctrine.
- `goose serve`'s ~103 endpoints were not enumerated (out of scope for the PTY lane).
- `term` subcommand and the plugin/gateway systems: unexamined.
- Asset sha from one download on one network; API `digest` field unavailable (rate limit).
- The 401 from :6767 proves the seam but also that key handling needs a harness-side decision.
- v2.0 RCs were not evaluated; this sheet is a 1.48.0 pin.

## Reproduce this recon

```
git ls-remote --tags https://github.com/aaif-goose/goose | grep v1.48.0
curl -sLO https://github.com/aaif-goose/goose/releases/download/v1.48.0/goose-aarch64-apple-darwin.tar.gz
shasum -a 256 goose-aarch64-apple-darwin.tar.gz   # d502945f…da49a
tar -tzf goose-aarch64-apple-darwin.tar.gz         # ./ and ./goose only
git clone --depth 1 --branch v1.48.0 https://github.com/aaif-goose/goose
```
