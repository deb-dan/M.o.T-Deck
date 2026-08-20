# HermesOffice recon — is it the genoffice replacement?

Date: 2026-08-20 · Method: `git clone --depth 1 https://github.com/criptogus/HermesOffice` → /tmp/ho
(clone succeeded; all file:line below are from that checkout at `c549db5` unless marked ⚠️).

## 1. What it IS

**A thin fork of the very repo we rejected.** `README.md` (GitHub page) — *"Fork de
genspark-ai/genoffice (Apache-2.0). Este é um thin fork: o código de engines e apps segue o
upstream, com uma camada própria de identidade e integração com o Hermes Agent"*. `NOTICE:19-27`
repeats it: *"HermesOffice is a fork of GenOffice … Copyright 2026 Mainfunc, Inc."*

Not a fork of ONLYOFFICE/LibreOffice/Collabora. It is **five/six Electron apps in one npm workspace**
(`package.json:12-15` workspaces `apps/*`, `packages/*`; `apps/{docs,sheets,slides,pdf,markdown,shell}`):
docs = own `.docx` byte-preserving engine, sheets = Univer core + **a Rust xlsx sidecar**
(`apps/sheets/package.json:13` `cargo build --release --manifest-path native/xlsx-engine/Cargo.toml`),
slides = own pptx engine, pdf = pdf.js + pdf-lib, shell = tabbed host + auto-update.

**Name collision is real and is with OUR Hermes.** The "Hermes" here IS Nous Research's Hermes Agent
(`hermes/README.md:3` "the **Hermes Agent** (Nous Research)") — the same upstream we vendor. So the
product name is not a coincidence; it is a fork rebranded *around* our agent. In our UI it would
still need a distinct label (e.g. "Office"), because our tab strip already has a tab named Hermes.

## 2. License

**Apache-2.0** (`LICENSE:2-4`, 169 lines, verbatim Apache 2.0) — clean, plus `LICENSE-UNICODE.txt`
for a generated table. ⚠️ **One carve-out:** `ee/LICENSE:1-16` — everything under `ee/` is a
proprietary "GenOffice Enterprise License" (dev/testing only; production use needs an agreement
with Mainfunc, Inc.). Today `ee/` is empty except its README/LICENSE (`ee/README.md:5-7`), so the
shipped code is Apache-2.0 — but the boundary exists and upstream can fill it at any time.
⚠️ `NOTICE:17-40` still contains **unresolved merge-conflict markers** (`<<<<<<< HEAD` /
`>>>>>>> upstream/main`) in a legally-load-bearing file. That is the quality tell of this fork.

## 3. Architecture

**It is a desktop application, not a server.** There is no port to point a webview at, no
`/health` it serves, no node/python daemon of its own. Build: Node ≥22.12 + npm ≥10
(`package.json:8-10`), `npm install` → `npm run dist:mac` → a `.dmg`. **npm, not bun**; plus a
**Rust toolchain (`cargo` on PATH)** for the sheets sidecar, and Vite dev servers on 5173-5177 in
dev mode only (`package.json:31`). It runs fully local — documents never leave the machine on the
core path.

Two paths that *do* leave the machine, both opt-in: `packages/hermes-cloud` (embedded Google-Drive
OAuth, `drive.file` scope, `src/auth.ts:6-18`; watches open docs and uploads on change,
`src/cloud-sync.ts:20-27`) and `packages/hermes-share` (`src/index.ts:1-9`, pipes a document out
through `hermes send` to whatever messaging platforms the Hermes gateway has configured).
No telemetry SDK anywhere — grepping posthog/mixpanel/sentry/telemetry across `apps/` + `packages/`
returns only `apps/sheets/src/renderer/edit-journal.ts` (a local edit journal). The one attribution
header, `gensparkAttributionHeaders` (`packages/ai-provider/src/providers.ts:24-28`), attaches
`X-Agent-Type` **only when the base URL starts with `https://www.genspark.ai`**.

## 4. THE decisive question — bring-your-own endpoint? **YES. It passes the test genoffice failed.**

- `packages/ai-provider/src/providers.ts:15` — `export const HERMES_LLM_BASE_URL = 'http://127.0.0.1:8642/v1'`
- `providers.ts:31-39` — provider `hermes`, `needsBaseUrl: true`, `defaultBaseUrl: HERMES_LLM_BASE_URL`,
  key placeholder "Hermes gateway API_SERVER_KEY". `providers.ts:121` — `return { provider: 'hermes', … }`
  is the **default**; all four editors hard-force it (`apps/docs/src/main/docs-main.ts:2588`,
  `apps/sheets/src/main/sheets-main.ts:2122`, `apps/pdf/src/main/ai-ipc.ts:41`,
  `apps/slides/src/main/ai-ipc.ts:63` — all `settings.provider = 'hermes'`).
- The transport is **plain OpenAI-compatible**: `stream.ts:869-873`
  `streamOpenAiCompatible(config.baseUrl || HERMES_LLM_BASE_URL, …)` → `stream.ts:729`
  `POST ${baseUrl}/chat/completions`. A `custom` provider also exists (`providers.ts:92-99`,
  `needsBaseUrl: true`; `stream.ts:932` *"A custom provider requires a Base URL"*).
- Therefore pointing it at **our runner `http://127.0.0.1:6767/v1`** works by construction, and
  pointing it at our Hermes needs only the gateway's api_server platform enabled on **:8642**
  (`docs/hermes-integration.md:29-45`) — which our harness does **not** run today (we run
  `hermes dashboard` :9119 and keep the messaging gateway off by design).

⚠️ **But the config surface is a JSON file, not UI.** `baseUrl` appears in exactly one renderer
line (`apps/docs/src/renderer/App.tsx:296`, a defaults object) and there is **no Base-URL input
field and no i18n string for one** anywhere under `apps/*/src/renderer`. The value lives in
`ai-settings.json` in Electron userData (`apps/docs/src/main/docs-main.ts:2479`,
`apps/pdf/src/main/ai-ipc.ts:23`, +2). So BYO-endpoint is real at the code level and a hand-edit at
the user level. It also health-gates every stream on `GET <base minus /v1>/health`
(`packages/ai-provider/src/hermes-health.ts:26-56`) — a URL **our runner does not serve** — so
aiming it straight at :6767 must use the `custom` provider, not `hermes`. ⚠️ untested.

## 5. Health

**3 stars, 0 forks, 0 watchers, 27 commits, 0 releases** (github.com/criptogus/HermesOffice, fetched
2026-08-20). Single author — `git log --format=%an | sort -u` → `CriptoGus` only; HEAD `c549db5`
dated 2026-08-13 ("Merge pull request #53 … readme-overhaul"). **Bus factor 1.** No prebuilt
binaries — README: *"Releases assinados do fork serão publicados aqui (em construção)"*, build from
source. The README also concedes the whole point of the fork is *"Integração em desenvolvimento"*.
`package.json:12` carries the rebrand script's collateral damage: `repository.url` points at the
non-existent `github.com/genspark-ai/hermesoffice.git`. Upstream genoffice (Mainfunc/Genspark) is
the real engineering; this fork is ~a week of sed-rebrand + one provider case + a launcher + skills.

## 6. Component fit

Poor, structurally. Our optional-component shape is *install → start a loopback HTTP server → a
WKWebView tab + a `/health` card*. HermesOffice has **no server to start and no page to load** — it
is a separate `.app` with its own window, its own tab strip and its own auto-update. There is no
install/start/stop for us to own; the honest integration is "Debi installs a normal Mac app".
Cost if we tried anyway: Node ≥22 + a full Rust toolchain, an Electron monorepo build
(⚠️ **disk estimated 3-6 GB** node_modules + Electron binaries + cargo target — not measured), and
a second Electron runtime resident beside our Swift shell. It also **spawns `hermes gateway start`**
when :8642 is dead (`apps/shell/src/main/hermes-launcher.ts:66`, consent-gated per its own comment
at :4-8) — i.e. it would start a Hermes surface our harness deliberately keeps off, against the
same `~/.hermes` config we patch. No 0.0.0.0 binds found (nothing listens at all); the only outbound
paths are the opt-in Drive sync and `hermes send` share, both off by default.

## 7. Verdict — **REJECT as a harness tab component; note it as a standalone app Debi may install herself.**

It genuinely fixes the one thing that killed genoffice — the AI is an OpenAI-compatible base URL
defaulting to a *local* Hermes gateway, with a `custom` provider for any endpoint, so our :6767
runner is reachable by construction. But that fix does not make it composable *with us*: it is an
Electron desktop suite with no server surface, so there is nothing to put in a tab, nothing to
health-probe, and nothing for install/start/stop to own — adopting it would mean the harness
"installing" a second desktop app, building a Rust sidecar and an Electron bundle, and letting that
app start a Hermes gateway we keep switched off. Against that cost the maturity is 3 stars, one
author, 27 commits, no releases, an unresolved merge conflict in NOTICE and a broken repository URL
— a week-old thin fork whose real engineering belongs to an upstream we already rejected on other
grounds. Recommendation: **do not build a component**; if Debi wants byte-preserving `.docx`/`.xlsx`
editing with a local agent, she installs it as an ordinary Mac app, points its `ai-settings.json`
wherever she likes, and we revisit only if it grows releases and a second maintainer. If we ever do
want office editing *inside* the harness, upstream `genspark-ai/genoffice` plus our own provider
patch is the same amount of work on a healthier base — and it would still be an Electron app, not
a tab.
