# OpenCode / OpenClaw / Omnigent recon — 2026-08-21

Method: full `git clone --depth 1` of each repo read locally + npm registry + raw GitHub.
`api.github.com` was NOT reachable (⚠️ star counts unverified everywhere below; substitutes used).
Clones read at: opencode `e49772a8b4db867f638ffad9f7d188ccbbe05b58` (2026-08-20), omnigent
`269dffacb659fc00b79e84beed107c2e8a09d51e` (2026-08-21).

---

## 1. OpenCode — **github.com/sst/opencode** (ADOPT, as a TAB, with three conditions)

**Disambiguation.** `sst/opencode` is the live repo (clone succeeded, HEAD dated 2026-08-20).
Its own README build badge points at `github.com/anomalyco/opencode` (README.md:14) and brew
installs from `anomalyco/tap/opencode` (README.md:52) — i.e. the project moved under an
`anomalyco` org while `sst/opencode` still serves. npm package is **`opencode-ai`**, not
`opencode` (root package.json:4 marks the monorepo `"private": true`). Do NOT confuse with the
older `opencode-ai/opencode` naming; pin by npm version, which is unambiguous.

**What it is.** A full coding agent with FOUR front ends out of one binary:
`opencode` TUI, `opencode serve` (headless HTTP+OpenAPI, `packages/opencode/src/cli/cmd/serve.ts`),
`opencode web` (server **+ browser UI**, `cli/cmd/web.ts:74` opens `localhost:<port>` on the
server's own port — `packages/app` is the SPA), and a desktop app (`packages/desktop`).
Also ACP (`cmd/acp.ts`), GitHub/GitLab bots, LSP integration, MCP client, subagents (`tool/task.ts`),
plan mode, skills (`tool/skill.ts`), `apply_patch`, permissions.

- **License: MIT** (LICENSE:1, "Copyright (c) 2025 opencode"); npm `"license":"MIT"`.
- **Runtime: a prebuilt native binary.** `opencode-ai@1.18.19` ships
  `optionalDependencies: opencode-darwin-arm64@1.18.19` (registry JSON) — npm just downloads a
  binary; **no Node needed at run time**. Built with Bun (`packageManager: bun@1.3.14`).
  Same pinning shape as our llama.cpp binary. Publisher is GitHub-Actions OIDC (signed).
- **Health: very high.** Commits same-day; `STATS.md` records >10M cumulative downloads by
  2026-01-29 and still climbing ~380k/day. Not bus-factor-1.

**Models — YES, our `:6767` works, first-class and documented.**
`packages/web/src/content/docs/providers.mdx:1351` is a literal **`### llama.cpp`** section:
```json
"provider": { "llama.cpp": { "npm": "@ai-sdk/openai-compatible", "name": "llama-server (local)",
  "options": { "baseURL": "http://127.0.0.1:8080/v1" },
  "models": { "qwen3-coder:a3b": { "limit": { "context": 128000, "output": 65536 } } } } }
```
Provider ID is arbitrary; `options.baseURL` is read at `provider/provider.ts:356`
(`endpoint ?? baseURL`) and a configured `baseURL` **suppresses autoload/ID checks**
(provider.ts:732, :769) — so a custom local provider is not second-guessed. LM Studio and Ollama
sections exist too (providers.mdx:1420, :1613). The model list is declared by us in config, so our
registry ids can be mirrored 1:1.

**⚠️ TOOL-CALLING IS REQUIRED. There is no aider-style text edit path.**
Every mutation is a native tool call — `packages/opencode/src/tool/` holds `edit.ts`, `write.ts`,
`apply_patch.ts`, `shell.ts`, `read.ts`, `task.ts` and a `registry.ts`. A `capabilities.toolcall`
flag exists (`provider/provider.ts:1263`, default **true**) but grep shows it is **only ever
written and asserted in tests** (`test/provider/provider.test.ts:1043`) — it is never consulted to
change the request path, so declaring `tool_call: false` does not buy a fallback. This is the exact
goose disqualifier. Their own Ollama docs concede it: *"If tool calls aren't working, try increasing
`num_ctx`… Start around 16k - 32k"* (providers.mdx:1650). Mitigation, not a fix: `apply_patch`/`edit`
are shallow-argument tools (path + old/new string), far easier for a small model than deep JSON —
but a 4B still has to emit a well-formed call. `packages/codemode/` (private workspace pkg) has the
model write a JS program that calls tools, which is *worse* for a 4B.

**Other facts that matter to us**
- Server default **`--port 4096 --hostname 127.0.0.1`** (`cli/network.ts:8-16`) — loopback by default. ✅
- **No auth by default**: `serve.ts:17` / `web.ts:39` warn `OPENCODE_SERVER_PASSWORD is not set;
  server is unsecured.` Fine on loopback, but a `--cors` flag exists and `--mdns` flips hostname to
  `0.0.0.0` — never pass either.
- **Telemetry: clean.** No posthog/mixpanel/sentry/amplitude anywhere in `packages/opencode/src` or
  `packages/core/src`. Only OpenTelemetry, **opt-in** via `experimental.openTelemetry`
  (`core/src/v1/config/config.ts:173`, consumed `session/llm.ts:344`). Materially better than aider.
- ⚠️ **Auto-update is ON by default** — `cli/upgrade.ts:10`: `if (config.autoupdate === false ||
  Flag.OPENCODE_DISABLE_AUTOUPDATE) return`. Pin discipline **requires** setting both.
- ⚠️ **Runtime npm installs.** Provider packages (e.g. `@ai-sdk/openai-compatible`) are fetched on
  demand into `~/.cache/opencode` via `@npmcli/arborist` (`core/src/npm.ts:83-96`;
  troubleshooting.mdx:269). Floating, unpinned, needs network on first use — hostile to the fat
  offline installer, and a supply-chain surface. It also fetches the models.dev catalog.
- **Permissions map onto our approval doctrine**: `permission` config resolves `allow|ask|deny`
  per tool (permissions.mdx:13-19); `--auto` auto-approves everything except explicit `deny`
  (permissions.mdx:25). **Never pass `--auto`** — same rule as aider's `--yes-always`.

**VERDICT: ADOPT as a second coding lane — as a TAB, not a PTY.**
This is the one item in this report that is strictly more capable than aider and still fits the
doctrine. `opencode web` is exactly our tab shape: one process, loopback, own port, its own SPA —
no xterm.js, no PTY relay, no WebSocket origin gate of ours to write. Integration shape:
`components.opencode` in motdeck.yaml, pin `build.opencode_pin: "1.18.19"` (npm version; resolve the
darwin-arm64 tarball or `npm i -g opencode-ai@<pin>` into `data/opencode/`), start with
`opencode web --port <yaml> --hostname 127.0.0.1`, health = GET on that port.
**Three mandatory conditions:** (1) write `~/.config/opencode/opencode.json` from OUR runner facts
(the llama.cpp provider block above, `baseURL http://127.0.0.1:6767/v1`, model ids from our
registry — the same fan-out we already do for Hermes/Odysseus); (2) `"autoupdate": false` +
`OPENCODE_DISABLE_AUTOUPDATE=1` at spawn, and never touch its in-app upgrade; (3) online-only
install, documented — the arborist provider-fetch cannot ride the fat wheelhouse.
Aider's origin-gate caveat does **not** apply (no bridge WS endpoint), but the port-preflight
ownership rule does. ⚠️ Nothing here is run-verified: no OpenCode binary was executed and no local
model was driven through it. **The one experiment that decides it: point `opencode` at :6767 with a
30B-class coder GGUF and see whether tool calls land.** A 4B almost certainly will not.

---

## 2. OpenClaw — **github.com/openclaw/openclaw** (REJECT — wrong category)

Not a coding agent. It is **a personal AI assistant** by Peter Steinberger (README: "🦞 OpenClaw —
Personal AI Assistant"), MIT, Node ≥22, npm `openclaw`. Architecture: a **Gateway control plane on
`ws://127.0.0.1:18789`** plus ~23 messaging channels (WhatsApp, Telegram, Slack, Discord, Signal,
iMessage, Matrix…), voice wake + talk mode, a Live Canvas, browser control via CDP, cron/webhooks,
skills, macOS/iOS/Android companion apps, Tailscale Serve/Funnel exposure. Agent runtime is
badlogic's `pi-mono`. Config `~/.openclaw/openclaw.json`; workspace `~/.openclaw/workspace`. Very
high activity (PR numbers in the **#93,5xx** range per omnigent's own CI survey,
`designs/ci-external-contributors-proposal.md:146`), OpenAI/Vercel/Convex sponsors, a huge
contributor list — healthy, not bus-factor-1.

**Verdict: REJECT.** It occupies Hermes's territory (messaging gateway, cron, skills, browser,
voice) rather than filling a gap, and it would arrive with 23 channel integrations, a launchd daemon
(`--install-daemon`), a Docker sandbox mode and companion apps. Local-model fitness is ⚠️ unverified
and its own model note pushes *"the strongest latest-generation model available to you"* for
prompt-injection resistance — the opposite of our design point. Idea-quarry only: its
loopback-Gateway + Tailscale Serve/Funnel exposure model is a good reference for our M5 remote item.

---

## 3. omnigent-ai/omnigent — **PARK, watch** (and the headline is *who owns it*)

**It is a Databricks project.** `pyproject.toml:12` `authors = [{ name = "Databricks, Inc." }]`,
keywords include `databricks`; `NOTICE:1` `Copyright (2026) Databricks, Inc.`. **Apache-2.0.**
Version `0.11.0.dev0`, classifier `Development Status :: 3 - Alpha`. Python ≥3.12, installed via
`uv tool install omnigent`. Repo is extremely active (HEAD 2026-08-21, PR **#5141**).

**What it is: a meta-harness — a layer ABOVE Hermes, not a replacement for it.** README:
*"a common orchestration layer over Claude Code, Codex, Cursor, OpenCode, Hermes, Pi, and the agents
you write yourself"* — declarative YAML agents (`docs/AGENT_YAML_SPEC.md`), policies for approval /
spend caps / tool limits, session sync across terminal-browser-phone, a web UI, a macOS desktop app,
and cloud sandboxes (Modal, Daytona, E2B, Databricks…). It drives Hermes as one of several *native
terminal wrappers* via `tmux` (README prerequisites) and OpenClaw over ACP (`docs/openclaw.md:52`;
spawn env pinned at `tests/runtime/test_acp_spawn_env.py:28`). Local models: supported as a
"Gateway" credential — any OpenAI/Anthropic-compatible `base_url` (README.md:329), with Ollama
`http://localhost:11434/v1` as the local example (README.md:345). So our :6767 would work, but only
for the child harnesses that accept a base_url. **No relation to Unsloth.**

**Verdict: PARK.** One paragraph: it is genuinely the same product class as the New MOT Deck itself —
an orchestration layer that owns sessions, policies, approvals and the UI, with Hermes demoted to
one swappable child process — so adopting it means adopting a rival whole-app rather than a
capability we lack (the exact reasoning that rejected mindshub and LibreChat). It also arrives
Databricks-shaped (cloud sandboxes, `docs/databricks.md` is the deepest integration doc,
Modal/Daytona/E2B extras), needs Node 22 + pnpm + tmux + `uv`, and is self-declared **alpha**.
Nothing stops Debi running it *outside* MOT Deck. **Worth watching for one reason:** its policy
engine (`docs/POLICIES.md` — pause-for-approval on risky actions, spend caps, tool allowlists,
scoped to server/agent/chat) is a more general version of our path-guard + approval cards, and its
per-harness adapters are a free survey of how six coding agents actually behave. Idea-quarry, not a
dependency.

---

## 4. Ranked recommendation — "the robust IDE-style lane"

1. **OpenCode as a tab, aider stays as the PTY lane — both, not either.** They fail in opposite
   directions and that is the point. Aider is the only structurally honest option for a small local
   model (no tool-calling required, whole-file edit format); OpenCode is the capable one (LSP,
   subagents, plan mode, MCP, skills, apply_patch, a real web UI) but **requires tool-calling**.
   Keeping aider means the 4B lane never dies; adding OpenCode means the 35B-GGUF lane gets a real
   IDE. Cost: one more component, an online-only install, a config fan-out, an auto-updater to nail
   shut, and ~8 chars of tab-strip budget.
2. **Aider alone** — the conservative option, and defensible if the tool-call experiment fails.
   Choose this if a 30B-class GGUF cannot reliably emit `edit`/`apply_patch` calls through OpenCode;
   a coding lane that silently no-ops on edits is worse than no second lane.
3. **Neither OpenClaw nor Omnigent** for this slot. OpenClaw is a messaging assistant (Hermes's
   category); Omnigent is a meta-harness (our own category).

**The honest trade-off, stated plainly.** Our local reality is 4B→~35B GGUF/MLX. Tool-calling
reliability there is a function of the *model's chat template and quant*, not of the agent — and
neither engine we run advertises it per model. OpenCode does not degrade gracefully: there is no
text path to fall back to (§1), so on a weak model it will look "broken" rather than "worse". That
makes the go/no-go a **measurement, not a design argument**: install the pin, point it at :6767 with
the biggest coder GGUF on disk, ask for a two-file edit, and watch whether `edit` calls land.
Fifteen minutes. Do that before writing a single line of `install_opencode.sh`.

**Open items for a Fable ruling if OpenCode is greenlit:** whether the config fan-out lives in
`start_component.sh` like Hermes's or in a `bridge/opencode.py`; whether its own permission prompts
stay in its UI (simplest, consistent with aider's "aider's confirm IS the approval flow") or get
lifted into our approval cards (much larger — needs its OpenAPI/WS event stream); and whether the
path-guard gap is acceptable (as with aider, the workspace cwd is the only boundary — our
path-guard is a Hermes plugin hook and does not reach here).
