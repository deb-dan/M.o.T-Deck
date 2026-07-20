# Harness codebase — see ../CLAUDE.md

> This is the v1 scaffold, moved here 2026-07-20. **Project working memory lives one level up: `../CLAUDE.md`** (doc set 00–08 alongside it). The v1 handoff notes that used to live in this file are archived in the original `Harness project` folder and superseded by `../07_Salvage_from_v1.md` (which includes the code-audit findings: stale `app/Config.swift` path, wrong Hermes start invocation, venvs excluded — regenerate via `scripts/bootstrap.sh`).

Quick facts: Bridge :8700 (`scripts/start.sh`), panel at `bridge/panel/index.html`, pins in `harness.yaml`, submodules under `vendor/` (never edit). `data/` (venvs, logs) is gitignored and was deliberately NOT copied — re-run `./scripts/bootstrap.sh`, then reinstall components from the panel. Rebuild the app with `./scripts/build_app.sh` (regenerates `app/Config.swift` with this folder's path).
