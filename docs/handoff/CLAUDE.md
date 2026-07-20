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

## State (2026-07-20)

- **Code moved: the scaffold now lives at `./harness/`** (git repo + vendor submodules intact; `data/` venvs and `dist/` were regenerated on the Mac via `./scripts/bootstrap.sh`). The old `Harness project` folder is a frozen archive.
- **M0 Hermes half DONE (verified 2026-07-20).** Bridge online :8700; Hermes green via `hermes serve` :9119; `scripts/test_hermes.sh` returned `PASS` — Hermes executed a shell tool call through Jan (`Qwen3_6-35B-A3B-…-IQ4_XS` @ :1337). Latest repo commit family: `d786fb8` (+ Jan-side context fix, no code).
- **Remaining M0:** install Odysseus natively from the panel (:7860), first chat round-trip, both cards green. Then the 04 §Prototypes spikes before M1.
- All licensing verified from LICENSE files: Hermes MIT, Odysseus MIT, Jan Apache-2.0; only SearXNG is AGPL.

## Next actions (in order)

1. **Install Odysseus** from the panel (native Python, :7860). Bridge writes `.env` (`LLM_HOST` → Jan :1337, `SEARXNG_INSTANCE`, `APP_PORT: 7860`). Expect its Start/health to be simpler than Hermes — a normal web server on a real port, no daemon ambiguity.
2. **First full handshake:** Odysseus answers a chat through Jan; Hermes already proven. Both cards green = M0 complete.
3. Then the 04 §Prototypes spikes (headless Jan, CLI download, WKWebView embed, native SearXNG) before M1 commitment.

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

## Git sync rule (important — cost us a full cycle)

Always sync the Mac clone with: `git fetch origin && git reset --hard origin/main`. Plain `git reset --hard origin/main` without a fetch resets to a **stale** local ref and silently reverts pushed fixes (this happened once and looked like "nothing changed"). Remote is truth; commits are pushed from the assistant's side per session.

## Standing cautions

- Doc freeze: no fifth planning pass until the full M0 handshake (Hermes + Odysseus both green) is done.
- v1 gotchas (07 §3): zsh `~` in quotes; uvicorn `--log-config /dev/null` crash; `chmod +x` new scripts (the sandbox copy loses execute bits); drain stdin before prompts; `vendor/hermes` not `vendor/hermes-agent`.
- When any fact is corrected, grep the whole doc set (especially the 00 primer) for the stale value.
