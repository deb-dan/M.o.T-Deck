# 04 — Roadmap (M0 → M4)

## ⟳ STATE UPDATE — 2026-08-07 (supersedes sections below where they conflict)

M0–M3 are **complete**. The roadmap below is history. Live plan lives in `CLAUDE.md`.

**Done since this doc was written:**
- **M0** handshake (Hermes + Odysseus green against a real endpoint) · **M1** runner slot,
  dependency-ordered one-switch provisioning, config fan-out, degraded detection ·
  **M2** Models pane (two-pane library + detail), HF browse, per-file download manager with
  pause/resume, aux runner, RAM ledger · **M3** Hermes as a first-class chat lane (streaming,
  approvals, sessions, file cards) plus its dashboard as a native tab.
- **Runner replaced:** Jan → our own llama.cpp (`b10295`) + MLX runner on :6767. MTP speculative
  decoding detected and measured at **~+15%** average.
- **Fat offline installer DONE** — `build_app.sh --fat` bundles CPython + a ~213-wheel arm64
  wheelhouse + the pinned `llama-server`; provisions to green with no terminal and no network.
- **Path-guard fence DONE** (Hermes `write_file`/`patch` gated via the upstream `pre_tool_call`
  plugin hook, escalating into our existing approval card, plus a `data/logs/guard.log` audit tier).
- **Also shipped:** artifacts renderer + editable canvas, Capabilities panel, light theme,
  first-run checklist + walkthrough, analytics tiles, vision/images end-to-end with an attachment
  sidecar, thinking persistence sidecar, per-message actions (copy/edit/fork/delete + tok/s stamps),
  model-picker popover, Logs pane.
- **Dropped / shelved:** the **gearbox** (local↔cloud policy routing) — local-only by choice;
  the Jan-coupled `jan-browser-mcp` (kept browsermcp.io instead); the Odysseus UI reskin-by-CSS.

**Next (in order):** voice components as first-class tabs — `docs/handoff/FABLE-VOICE-TABS-SPEC.md`
(VoiceStudio + Voicebox) · a **2nd-Mac `.dmg` first-run test** (the single biggest unverified
surface) · then **M5 remote access** (Tailscale + Hermes's messaging gateway).
---


*Part of the Harness handoff set. Index: [00_START_HERE.md](00_START_HERE.md). Architecture referenced throughout: [02_Architecture.md](02_Architecture.md).*

Ordering principle (personal-first): **every milestone ends with something you personally use that week.** No milestone exists to serve a hypothetical future user. Shipping-related work is deferred indefinitely; the only future-proofing is the four hygiene rules in [03_Licensing.md](03_Licensing.md).

---

## M0 — Finish the handshake (you are HERE, mid-M0)

Goal: the existing harness runs Hermes and Odysseus against a real model endpoint, end to end. **Do not pivot to M1 before this runs** — M1's runner interface should be extracted from a working system, not designed in the abstract.

Tasks (the four known remainders, with the new research folded in):
1. **Fix Hermes start-error reporting** in the Bridge/Mission Control so failures surface in the status card instead of dying silently.
2. **Connect Hermes by writing `~/.hermes/config.yaml` DIRECTLY — do not run the setup wizard.** (Updated 2026-07-20 for the one-switch requirement, [02_Architecture.md](02_Architecture.md) §One-switch provisioning: verified that `config.yaml` fully bypasses the interactive wizard — which can't even skip its Nous Portal step, per upstream issue #41046.) The Bridge writes `model: { provider: custom, base_url: ... }` with the base URL of whatever's running today (LM Studio `http://localhost:1234/v1` is the path of least resistance right now; Jan desktop `http://localhost:1337/v1` also works and is in Hermes's official compatibility table), then validates with `hermes config check`. This *is* the Hermes "connect step" of the provisioning pipeline — building it now means M1 reuses it verbatim. **Use a tool-calling-capable model** (LM Studio ≥0.3.6 handles the wire format; see Decisions §1).
3. **Install Odysseus from the panel.** Native Python route only — no Docker (locked decision, §Decisions). (Python 3.11+): venv → `pip install -r requirements.txt` → `python setup.py` → `python -m uvicorn app:app --host 127.0.0.1 --port 7860`. Bridge writes its `.env` (`LLM_HOST`, `SEARXNG_INSTANCE`, `APP_PORT`); finish provider setup in Odysseus's in-app Settings UI.
4. **First handshake:** Hermes completes a trivial multi-step task through the endpoint; Odysseus answers a chat query; both visible as green cards. Optional stretch: one DeepResearch query if SearXNG is already reachable.

Exit criterion: you did all of the above **without opening a terminal** (except where the harness legitimately shells out for you).

## M1 — The runner slot + one-switch provisioning

Goal: Jan becomes a Bridge-managed headless component; the runner becomes anonymous behind an adapter; and the Bridge's install machinery grows into the full **one-switch provisioning pipeline** — Debi's declared #1 requirement ([02_Architecture.md](02_Architecture.md) §One-switch provisioning): flipping a component ON auto-installs AND auto-connects it, dependencies included.

1. **Write down the runner interface in the Bridge** exactly as specified in [02_Architecture.md](02_Architecture.md) §Runner slot: inference endpoint, `GET /v1/models`, an acquisition mechanism, headless lifecycle + health.
2. **Jan adapter:** Bridge manages `jan serve --detach` (CLI auto-installed by desktop Jan to `/usr/local/bin/jan`); canonical endpoint `http://127.0.0.1:6767/v1`; health = `GET /v1/models`; acquisition = `jan serve <org>/<repo-GGUF>` (auto-downloads HF repo IDs), progress parsed from CLI output. Remember: CLI and desktop share a data folder, and per-model settings come from the desktop-generated `router.preset.ini` — so configure models once in desktop Jan, serve headless thereafter.
3. **Status card for the runner** (which runner, which model loaded, endpoint, health), and Bridge config fan-out so Hermes `config.yaml` and Odysseus `.env` receive the canonical endpoint URL — flip once, everything follows.
4. **Verify Hermes and Odysseus run against Jan's endpoint** (tool-calling check for Hermes especially — this is the likeliest friction point; if Jan's tool-call formatting misbehaves for your model, that's a candidate upstream issue/PR, or fall back per §5).
5. **LM Studio fallback adapter,** thin: endpoint :1234, `lms` CLI for lifecycle and `lms get` for acquisition. Switching runners must be a one-line config change.
6. **Component manifests + provisioning pipeline** (the one-switch requirement, spec in [02_Architecture.md](02_Architecture.md) §One-switch provisioning): write the five manifests (searxng, jan-runner, model-primary, odysseus, hermes) with pins; teach the Bridge dependency-closure resolution (flip Odysseus → plan includes SearXNG + runner + model); implement the state machine (`off → planned → installing → configuring → starting → verifying → ON`, plus `degraded`/`needs-repair`) with live progress on the status cards; make every step check-then-act (idempotent) and add the **Repair** verb (re-enter at the failed step). The Jan manifest includes the one-time desktop-launch step for CLI install, labeled in the plan dialog.

Exit criteria (both):
- **Runner swap:** kill Jan, flip config to LM Studio, restart components from Mission Control, everything still works — then flip back.
- **One-switch (the paramount one):** from a clean slate, flip Odysseus ON in Mission Control → one approval dialog → SearXNG, Jan, the primary model, and Odysseus all install, connect, and go green — **without you touching a terminal or any config file.**

## M2 — The unified surface

Goal: the experiences that motivated the whole project.

1. **Native model browser** (the flagship): HF API for discovery (search, GGUF/MLX quants, size), hardware-fit computation against 64GB, your editorial styling, download via the active runner's adapter. Runner-agnostic by construction. De-risk first — see Prototypes below.
2. **Odysseus webview tab** in Mission Control (WKWebView → `http://127.0.0.1:7860`). Chrome it with your styling around the frame; don't rebuild its UI.
3. **Cross-component ⌘K verbs:** "download model…" (→ browser), "deep research…" (→ Odysseus tab, query pre-filled), "assign to Hermes…" (→ Hermes task), "switch model/runner…", "update component…" (existing pin/rollback).
4. **Shared SearXNG as a first-class component** (Decisions §2): Bridge-managed **native from-source** instance on :8080 (no Docker — install recipe in [02_Architecture.md](02_Architecture.md) §SearXNG); Odysseus's `SEARXNG_INSTANCE` and the MCP search server both point at it.

Exit criterion: a full week where you never open LM Studio's or Jan's own UI except to change a model setting.

## M3 — Hermes deepening

Goal: the async agent becomes a genuine coworker surfaced through your shell.

1. **Activity feed integration:** Hermes task starts/steps/completions flow into Mission Control's feed.
2. **Task dispatch from ⌘K** ("assign to Hermes…"), with status card showing current task and last result.
3. **Hermes consumes harness capabilities as tools:** DeepResearch (via Odysseus's API) and the runner endpoint; possibly the shared SearXNG directly.
4. **Adopt the SKILL.md convention harness-wide** (Decisions §3): one canonical skills directory; Hermes reads it natively; LM Studio's community skills plugin (`~/.lmstudio/skills`) gets a symlink; Hermes being MIT means you can lift its loader conventions into your own code freely.

Exit criterion: you assign Hermes a task at night from ⌘K; in the morning the activity feed tells you what it did, and a skill it wrote is available everywhere.

## M4 — Optional give-back & review

- Upstream PRs to Jan for polish gaps you actually hit (logged along the way). Influence without maintenance debt.
- **Fork tripwire review** ([03_Licensing.md](03_Licensing.md)): fork only if a named need is blocked upstream. Expected outcome: still no.
- Revisit "ship it?" — if yes, the hygiene rules mean it's packaging + a lawyer-hour, not a rewrite.

---

## De-risking prototypes (cheap spikes BEFORE committing milestone effort)

| Spike | Question it answers | Effort |
|---|---|---|
| `jan serve --detach` by hand; curl `/v1/models` + a chat completion | Does headless Jan behave as documented on your machine/version? | 30 min |
| `jan serve unsloth/SomeModel-GGUF` for an uncached model | Is CLI-driven download + progress-parsing viable for the browser? | 30 min |
| Hermes `config.yaml` → Jan :6767, one tool-calling task | The likeliest M1 friction (tool-call wire format through Jan) | 1 hr |
| Raw HF API query for GGUF models + sizes | Is the model-browser data source good enough without scraping? | 1 hr |
| WKWebView on :7860 | Does Odysseus's UI embed cleanly (auth, websockets, popups)? | 30 min |
| Native SearXNG: clone → venv → `pip install -e .` → `settings.yml` (port 8080, `limiter: false`, `json` in formats) → `python -m searx.webapp`; curl `/search?q=test&format=json` | Does the no-Docker SearXNG path build and serve cleanly on macOS/arm64? | 1 hr |
| MLX model in Jan vs. LM Studio, same prompt, tokens/sec | How real are Jan's MLX regressions for YOUR models? | 1 hr |

If a spike fails, adjust the milestone before building (e.g., MLX bad in Jan → run Jan for GGUF + keep LM Studio loaded for MLX until upstream catches up; the runner slot makes this a config stance, not a crisis).

## Decisions (updated 2026-07-19 — four now LOCKED)

1. **Default models — policy LOCKED, exact picks open.** **Tool calling is mandatory for the primary model.** Hermes cannot work without it (its whole loop is tool calls) and MCP tools break too — so any model without reliable tool calling is **disqualified as primary**, however good its prose. Standardize two named roles in Bridge config (`primary`, `fast`), never hardcoded IDs: (a) `primary` — a ~30B-class tool-calling model run at 64K+ context (leading candidates: Qwen3-32B ~128K native, or the Qwen3.5/3.6 MoE equivalent; 64GB RAM leaves ample KV headroom — see [05_Reference_and_Learnings.md](05_Reference_and_Learnings.md)); (b) `fast` — a small tool-capable model for Hermes's high-frequency loops and background summarization. Still to do: benchmark and name the exact model IDs.
2. **Shared SearXNG: LOCKED yes — and native.** One Bridge-managed from-source instance on :8080 (no Docker; recipe in [02_Architecture.md](02_Architecture.md) §SearXNG); Odysseus (`SEARXNG_INSTANCE`) and the MCP search server both point at it.
3. **Single skills directory: yes (recommendation, still open).** `~/harness/skills` (or inside your harness root) as canon; symlink into `~/.lmstudio/skills`; configure/symlink Hermes to the same. One skill corpus, three consumers. Keep it in git.
4. **Canonical runner endpoint: LOCKED — headless Jan :6767** (`jan serve --detach`, Bridge-managed, survives desktop-app quits). Desktop Jan (:1337) stays a manual convenience for settings/chat, never the harness endpoint.
5. **Docker: LOCKED — none, anywhere.** Debi doesn't want Docker on the machine. Odysseus runs native Python; SearXNG runs native from source. The earlier "container acceptable for SearXNG" fallback is withdrawn; the emergency fallback is a public SearXNG instance, temporarily.
6. **Where daily chat lives:** defer. Jan's UI is fine through M1; revisit at M2 when the Odysseus tab exists; a native Mission Control chat pane is a possible M3+ luxury, not a commitment.

---

*Reference facts and sources: [05_Reference_and_Learnings.md](05_Reference_and_Learnings.md).*
