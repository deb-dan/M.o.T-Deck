# MOT Deck

> **NAMING (2026-08-21).** The product is **MOT Deck** — *Mixture of Tools*. Its home
> screen is **MOT Main** (formerly "Mission Control"). The internal codename remains
> `harness` and is NOT being renamed: `harness.yaml`, `HARNESS_*` env vars, API routes,
> nav ids, `~/Library/Application Support/Harness`, `/Applications/Harness.app` and every
> other path/key stay exactly as they are. Older text below says "Harness" for the
> product; read it as MOT Deck.

## ⟳ STATE UPDATE — 2026-09-02 (v1.5.72)

This README describes the early scaffold. Current reality, in order of authority:
**`CLAUDE.md`** (working memory), **`docs/ROADMAP.md`** (what's done / in progress / next),
**`docs/UNFORGET.md`** (the deferred-work ledger — every paused plan, audit finding, and
user-reported issue), **`docs/HARNESS-INTERNALS.md`** (code-derived system reference),
**`docs/USER-GUIDE.md`** / **`docs/USER-EXPLAINERS.md`** (how to use it).

- Nine live components on Mission Control: **Bridge** :8700 (our own code — control panel, panel
  UI, all lifecycle/model/chat plumbing) · **runner** :6767 (llama.cpp for GGUF, Apple MLX for mlx
  models) · optional **aux runner** :6768 · **Hermes** :9119 · **Odysseus** :7860 · **SearXNG**
  :8080 · **VoiceStudio** · **Voicebox** · **ComfyUI** · **Unsloth** · **OpenCode**. Alongside
  these: **Goose** as two coexisting lanes (Goose CLI over a PTY, Goose UI embedding upstream's
  own desktop renderer), and **LOffice** (ONLYOFFICE, one editor for .xlsx/.docx/.pptx with its
  own AI plugin wired into the ribbon). Jan was removed in July 2026; the **gearbox is shelved**
  (local-only) and `bridge/gearbox.py` / `policies/routing.yaml` are historical.
- Local API access: mintable/revocable API keys any app's own Add-Provider form can consume, plus
  a sidebar-only API page (base URL, status, route catalogue, request log).
- **⌥⌘Q "Quit Everything"** stops every component identity-verified, then the bridge, then the
  app; plain **⌘Q "Quit MOT Deck"** leaves the stack running so reopening reuses it instantly.
- Two app builds: `./scripts/build_app.sh` (lean dev app — serves this repo live) and
  `./scripts/build_app.sh --fat` (offline installer + a fat `.dmg` at `dist/` — serves a
  provisioned snapshot at `~/Library/Application Support/Harness`). **Standing ops rule: all
  code ships via `./scripts/ship.sh`** — the fat app will otherwise serve stale code
  (HARNESS-INTERNALS §3).
- `guards/harness-path-guard/` is a Hermes plugin (seeded into `~/.hermes/plugins/` on start) that
  fences the agent's `write_file`/`patch` calls; `bridge/tests/` + `bridge/contract_tests/` are the
  test and pin-bump suites.
- The never-edit-`vendor/` rule below is unchanged and enforced.

---


Personal AI workspace merging [Hermes Agent](https://github.com/NousResearch/hermes-agent)
(agent brain) and [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus)
(web workspace) as pluggable, one-click-updatable components. macOS-native, no Docker.

Full design: `docs/harness-architecture.md`.

## Quick start

```bash
./scripts/bootstrap.sh        # prereqs (asks first), git init, pinned submodules, bridge venv
./scripts/start.sh            # start the bridge → http://127.0.0.1:8700
```

Then open the control panel and click **Install** on Hermes and/or Odysseus.
Each install shows its plan (downloads, commands, directories) and waits for
your approval before touching anything.

## Layout

```
harness.yaml        pins, ports, endpoints — single source of truth
vendor/             pinned submodules (never modified — all glue lives in bridge/)
bridge/             the only code we own: panel, lifecycle, adapter, gearbox
policies/           routing.yaml (model gearbox), approvals.yaml (command patterns)
skills/             git-versioned Hermes skills
scripts/            bootstrap / start / stop / doctor / install_component
data/               (gitignored) venvs, logs, blue-green staging
```

## Component modes

Both installed = full experience (Odysseus UI + Hermes brain).
Hermes only = agent via TUI + panel. Odysseus only = workspace with its native agent.
The bridge (panel + gearbox) always runs.

## Rules

- Never edit anything under `vendor/` — updates would wipe it, and the update
  button depends on pristine submodules.
- Pins change only via the updater (or deliberately in `harness.yaml` + commit).
- One upstream update at a time; contract tests gate every switch.

<!-- unforget-registry:begin -->

### unforget registry

**Global**

| key | value |
|---|---|
| git_posture | committed |
| recall_block | maintained |
| recall_file | CLAUDE.md |
| policy_deferral | aggressive |
| policy_multiaxis | lifespan-wins |
| ratio_flag_threshold | 3 |
| stale_trivial_sessions | 2 |

**Ledgers**

| name | path | role | axis | discipline | parent | death |
|---|---|---|---|---|---|---|
| UNFORGET.md | docs/UNFORGET.md | main | — | standard-10col | — | — |

<!-- unforget-registry:end -->
