# AI Harness

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
