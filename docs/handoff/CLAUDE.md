# New Harness — working memory (canonical project home)

> For Claude: read this first, then `00_START_HERE.md` (its primer paragraph rehydrates a fresh session). This folder is the **single source of truth** for the harness project as of 2026-07-20. The copies of 00–06 in the old `outputs` folder are frozen; the v1 codebase lives in the `Harness project` folder (working scaffold — see 07).

## Doctrine

`agent-kit/DELEGATION-DOCTRINE.md` applies to this project in full, with **one amendment (2026-07-20): all UI design / look-and-feel work is Fable 5 only** — builder subagents may implement UI solely from a Fable-authored, decision-free spec. See `08_Interface_Strategy.md` §Governance.

## Doc map

| File | Contents |
|---|---|
| 00–06 | The handoff set (corrected: Jan = Apache-2.0, Odysseus = MIT, Odysseus port = **:7860** not :7000 — AirPlay conflict). |
| 07_Salvage_from_v1.md | v1 review: verdict (v1 = this project's scaffold, not a failed project), keep/reject lists, stall post-mortem. |
| 08_Interface_Strategy.md | Interface direction: reskin webview → deep-link tabs → native panes ladder; Fable-5-only UI rule. |
| mcp*.json, Top-40, LM-Studio guide | Config inventory (05 §5). |

## State (2026-07-20)

- **Code moved: the scaffold now lives at `./harness/`** (git repo + vendor submodules intact; `data/` venvs and `dist/` deliberately left behind — both were broken by the folder's earlier relocation and must be regenerated: `./scripts/bootstrap.sh`, panel installs, `./scripts/build_app.sh`). The old `Harness project` folder is a frozen archive.
- **Mid-M0.** Full code audit done (07 §Code audit): Hermes silent-start root cause FOUND — v1 runs `python mcp_serve.py --port 8721`, but that file is a stdio server with no `--port` flag, and Hermes never got a model config (gearbox was a stub). Fix = M0 tasks 1–2 below, not a mystery anymore. Harness.app needs rebuild (stale hardcoded path in `app/Config.swift`). Odysseus not installed; no runner slot yet.
- All licensing corrected and verified from LICENSE files: Hermes MIT, Odysseus MIT, Jan Apache-2.0; only SearXNG is AGPL.
- Stall cause of v1 identified: silent failures + multi-step manual installs → one-switch provisioning justified as the fix; error surfacing + scripted installs are the load-bearing part, dependency-closure dialog is polish.

## Next actions (in order — from 04 §M0, updated after the code audit)

0. Re-provision in the new location: `cd harness && ./scripts/bootstrap.sh --yes` (recreates bridge venv), reinstall Hermes from the panel, `./scripts/build_app.sh` (regenerates Config.swift → working Harness.app).
1. Fix Hermes start: replace the dead `python mcp_serve.py --port 8721` invocation in `scripts/start_component.sh` with the Hermes daemon per the new topology, and surface start-stderr on the status card (v1 only shows the last line).
2. Write `~/.hermes/config.yaml` directly (`provider: custom`, base_url of whatever runs today; LM Studio :1234/v1 is path of least resistance). Never run the Hermes wizard. Tool-calling model mandatory.
3. Install Odysseus natively from the panel; Bridge writes `.env` (`LLM_HOST`, `SEARXNG_INSTANCE`, `APP_PORT: 7860`).
4. First handshake: Hermes completes a tool-calling task; Odysseus answers a chat; both green.
5. Then the 04 §Prototypes spikes (headless Jan, CLI download, WKWebView embed, native SearXNG) before M1 commitment.

## Standing cautions

- Doc freeze: no fifth planning pass until the M0 handshake is green.
- v1 gotchas (07 §3): zsh `~` in quotes; uvicorn `--log-config /dev/null` crash; `chmod +x` new scripts; drain stdin before prompts; `vendor/hermes` not `vendor/hermes-agent`.
- When any fact is corrected, grep the whole doc set (especially the 00 primer) for the stale value — the primer propagated a wrong license once already.
