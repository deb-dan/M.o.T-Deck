# Research: goose Desktop UI — can it be embedded in MOT Deck? (2026-08-29)

> Question reframed mid-task by Debi: the goal is NOT the standalone Desktop app — it is
> goose's UI **inside MOT Deck as its own tab, exactly like Unsloth** (a component serving a
> web UI on a localhost port, shown in a native tab). This doc answers that first, then the
> provider/isolation wiring, then fallbacks.
>
> Method: (a) the actual installed app on this Mac (`/Users/debik/Downloads/Goose.app`,
> v1.48.0 — same version as our PTY-lane pin), inspected bundle + live config/data dirs;
> (b) source clone of `aaif-goose/goose` at tag **v1.48.0** (sha `25021517…`, same pin as
> `docs/research/2026-08-28-goose-source-verify.md`) — every file:line below is from that tag;
> (c) targeted upstream issue/discussion checks. Nothing was installed or modified.

## Verdict in one paragraph

**The goose Desktop renderer is an ordinary Vite/React static web bundle that talks to the
`goosed` backend over a plain browser WebSocket (ACP) — it is technically servable in a
browser/WKWebView.** goosed itself serves **no UI** (only `/acp` WS + `/health`/`/status` +
an MCP-app proxy), and nobody upstream or in the fork network has shipped a browser-served
goose UI (an old experimental `goose web` was removed long before v1.30.0). Embedding is
therefore a **build-it-ourselves shape**: serve the renderer bundle from our bridge, shim
`window.electron`'s ~40 preload IPC methods (about a dozen load-bearing, the rest no-ops),
and supervise our own `goose serve` fenced with `GOOSE_PATH_ROOT`. Apache-2.0 permits all of
it. It is real but it is a **maintained fork-of-behavior** (every goose release can change the
preload contract), so the ladder below puts a supervised-app step before it.

---

## 1. What goose Desktop technically is

Version Debi has = **1.48.0** = current stable (releases/latest as of 08-28; the app matches
our PTY-lane pin exactly).

- **Electron app** (`CFBundleIdentifier: com.electron.goose`, Electron Framework + Squirrel in
  `Contents/Frameworks`, Chromium profile debris in `~/Library/Application Support/Goose/`).
  Debi's copy runs **from `~/Downloads/Goose.app` under macOS App Translocation** (LaunchServices
  shows the translocated path) — it should be moved to /Applications regardless of what we build.
- **Backend it spawns:** the same single **`goose` CLI Mach-O** we ship in the PTY lane —
  bundled at `Contents/Resources/bin/goose` (268,870,288 bytes, arm64). The Electron main
  process runs it as **`goose serve --platform desktop --enable-scheduler --host 127.0.0.1
  --port <free port>`** with a generated `GOOSE_SERVER__SECRET_KEY`
  (`ui/desktop/src/gooseServe.ts:364-372,401`). "goosed" is not a separate binary in 1.48.0 —
  it IS `goose serve`. Also bundled: `jbang/node/npx/uvx` shims for MCP extensions.
- **Renderer ⇄ backend protocol:** ACP (Agent Client Protocol) over **WebSocket** —
  `createWebSocketStream` from `@agentclientprotocol/sdk/experimental/ws-client`
  (`ui/desktop/src/acp/acpConnection.ts:3,138`), URL `ws(s)://127.0.0.1:<port>/acp?…key`.
  Config read/write, provider setup, sessions, recipes, scheduler — all flow over ACP
  (`ui/desktop/src/acp/config.ts`, `providers.ts`, `sessions.ts`, `schedules.ts`).
- **"Use a Local Model" = in-process inference inside goosed, not a separate runner.**
  `crates/goose-local-inference` statically links **llama.cpp via the `llama-cpp-2` Rust
  bindings** (`src/llamacpp/mod.rs:10-14`) — that's why the binary is 268MB — plus an **MLX
  backend** (`src/mlx.rs`). No sidecar server, no Ollama.
- **Where its models land:** the **standard HuggingFace cache** via the `hf-hub` crate
  (`hf_models.rs:2022 download_gguf_to_hf_cache`). Empirically confirmed on this Mac:
  `~/.cache/huggingface/hub/models--bartowski--Llama-3.2-3B-Instruct-GGUF/snapshots/…/
  Llama-3.2-3B-Instruct-Q4_K_M.gguf`. The hf-hub crate honors **`HF_HOME`** /
  **`HF_HUB_CACHE`**. Auxiliary files (mmproj etc.) go to goose's data dir
  (`local_model_registry.rs:157-162` → `Paths::in_data_dir("models")`).
- **Its live config on this Mac** (`~/.config/goose/config.yaml`): `active_provider: local`,
  model `bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M`, `GOOSE_TELEMETRY_ENABLED: false`
  already set, ~18 bundled extensions (developer/skills/scheduler/apps/summon on).
- **Auto-update:** electron-updater against `github: aaif-goose/goose`
  (`Resources/app-update.yml`), set up after window creation (`main.ts:2539-2550`);
  **`GOOSE_DISABLE_AUTO_DOWNLOAD=1`** disables auto-download (`utils/autoUpdater.ts:390-393`).
  Frontend telemetry is a disabled stub (`utils/analytics.ts:4-16`); backend PostHog stays
  opt-in as verified 08-28.

## 2. PRIMARY: can the UI be served over HTTP for a MOT Deck tab?

### 2a. Is the renderer a web app? — YES, with one bounded Electron seam

- The packaged renderer inside `app.asar` is a **plain Vite static build**
  (`/.vite/renderer/main_window/index.html` + `assets/*.js|css` — verified by listing Debi's
  installed asar). Entry `ui/desktop/src/renderer.tsx` is stock React DOM + react-intl;
  in dev mode Forge serves this same bundle from a Vite HTTP dev server into Electron.
  Nothing about the bundle itself is Electron-specific.
- The transport is a **standard browser WebSocket** (ACP SDK ws-client) — works from any page.
- **The seam:** `contextBridge.exposeInMainWorld('electron', …)` + `('appConfig', …)`
  (`preload.ts:366-367`). **54 renderer files** call `window.electron.*`; the API is ~40
  methods (`preload.ts:101-160+`). Usage census (grep, calls not files):
  getSetting 20 / setSetting 18 / on 16 / off 16 / logInfo 13 / openExternal 9 / platform 7 /
  createChatWindow 6 / showMessageBox 5 / listFiles 5 / **getAcpUrl 5** / …long tail of 1-2s.
  `window.appConfig.get` ×11 (injected via `additionalArguments`, `main.ts:1313`).
- **The single connection-critical call is `window.electron.getAcpUrl()`**
  (`acpConnection.ts:131-138`) — no fallback: without it the renderer throws
  "ACP URL is not available". Everything else degrades or shims:
  - trivially shimmable: getAcpUrl (return our ws URL+key), getSetting/setSetting
    (localStorage), on/off (no-op event bus), logInfo/getConfig/platform, openExternal
    (window.open), showMessageBox (confirm()).
  - degradable no-ops: menu-bar/dock icon, wakelock, spellcheck, notifications-settings.
  - genuinely lossy in a browser: `createChatWindow` (multi-window → force same-tab),
    native file pickers (`selectFileOrDirectory`, `selectRecipeFile`), direct-FS helpers
    (`listFiles`, `writeFile`, `readGoosehints` — used by recipe/goosehints editors),
    drag-in `getPathForFile`. These degrade features, not the chat core.
- **Crucially, "Use a Local Model" survives an embed**: all local-model management flows over
  ACP (`acp/local-inference.ts:31-102` — `localInferenceModelsList/Download/Settings/
  HuggingfaceSearch_unstable`), i.e. it lives in goosed, not in Electron. Onboarding,
  providers, sessions, recipes, scheduler likewise (all `client.goose.*` over ACP).
- Server-side CORS/origin is solvable by flag: `goose serve --allowed-origin <our origin>`
  feeds `AcpOriginPolicy::exact` (`crates/goose/src/acp/transport/mod.rs:225-247`); default
  policy already admits loopback origins.

**What the embed slice would actually be** (Unsloth-shape): supervise `goose serve
--platform desktop --enable-scheduler --allowed-origin http://127.0.0.1:<bridge>` with
`GOOSE_PATH_ROOT` fenced (see §5); serve the renderer bundle (extracted from the sha-pinned
asar, or built with `pnpm` from the pinned tag — both Apache-clean) behind our bridge; inject
one `<script>` before the bundle defining `window.electron`/`window.appConfig` shims
(~200-400 lines); MOT Deck tab points at the page. Estimated: days, not hours — and a
**standing maintenance tax**: the preload contract and `_unstable` ACP methods can change
every goose release, so the shim needs a contract test against each version bump.

### 2b. Does goosed serve the UI itself in any mode/flag? — NO

The full router is `/acp` (WS) + `/health` + `/status` + an MCP-app proxy
(`/mcp-app-guest`, `/mcp-app-proxy` — sandboxed HTML for MCP "apps", not the goose UI)
(`crates/goose/src/acp/transport/mod.rs:242-247`, `acp/mcp_app_proxy.rs:364-387`).
No static-file serving of the renderer anywhere in the crates. The CLI docs confirm: no
`web`/`ui` subcommand (also verified on the real binary 08-28).

### 2c/Q4. Forks, PRs, issues — honest negative

- **A first-party `goose web` existed and was removed**: block/goose issue #6391 ("goose web —
  tools hang on OSX", 2025-era) references it; by v1.30.0 the command file no longer exists in
  the tree (checked `git ls-tree` at v1.30.0/v1.40.0/v1.44.0 — no `commands/web.rs`, no `ui/web`).
- **Upstream direction** (Discussion #7697 "Goose Client/Server", roadmap #6973, ACP #7309,
  issue #6642 "goosed to ACP-over-HTTP"): first-party UIs are desktop + mobile (+ TUI
  prototype, `ui/text`); **community UIs are explicitly encouraged via the published TS SDK**
  — `@aaif/goose-sdk` lives in-tree at `ui/sdk` ("ACP SDK for Goose AI agent"). Nobody in
  that thread proposes serving the desktop renderer in a browser.
- **No fork/PR found that makes the desktop UI browser-served.** Searches for goose web-UI /
  browser / serve turned up only the removed `goose web`, MCP-app rendering inside Desktop
  (issue #3562), and the ACP/SDK roadmap. If we build the embed, we are first — which cuts
  both ways (nothing to steal, nothing proven).
- Sources: [#7697](https://github.com/aaif-goose/goose/discussions/7697),
  [#6973](https://github.com/aaif-goose/goose/discussions/6973),
  [#7309](https://github.com/aaif-goose/goose/discussions/7309),
  [#6642](https://github.com/aaif-goose/goose/issues/6642),
  [#6391](https://github.com/block/goose/issues/6391),
  [#3562](https://github.com/aaif-goose/goose/issues/3562),
  [ui/sdk](https://github.com/aaif-goose/goose/tree/main/ui/sdk),
  [CLI commands doc](https://goose-docs.ai/docs/guides/goose-cli-commands).

## 3. Pointing ANY goose UI shape at OUR stack (:6767, our models)

- **Custom provider — exists in the Desktop settings UI.**
  `ui/desktop/src/components/settings/providers/modal/subcomponents/forms/CustomProviderForm.tsx`
  offers engine **`openai_compatible`** (default, :230-267) with `display_name`, `api_url`,
  API key, and **custom HTTP headers** (:154, :489-491). Saved as a declarative provider
  (config-dir `custom_providers/*.json`, same mechanism verified 08-28 at providers.md:481-508).
  So: **Settings → Models → Add custom provider → OpenAI-compatible →
  `http://127.0.0.1:6767/v1/chat/completions` + our runner's real API key.** Alternative
  (what the PTY lane already does): the stock `openai` provider with `OPENAI_HOST:
  http://127.0.0.1:6767` + `OPENAI_BASE_PATH: v1/chat/completions` in config.yaml — both keys
  surface in the Desktop's provider settings UI (`utils/configUtils.ts:25-26`). Model ids pass
  verbatim; tool-calling requirement unchanged (our `tools`-verdict pill logic applies).
- **The LOCAL-model page cannot see our GGUF dir.** There is **no `GOOSE_LOCAL_MODEL_DIR`** or
  equivalent (repo-wide grep). Local inference resolves models ONLY through the HF-cache
  layout (`models--owner--repo/snapshots/…`) via hf-hub, storage enum
  `LocalModelStorage::HuggingFaceCache` (`hf_models.rs:2007-2019`). Our harness models are
  flat dirs (`data/models/<name>/<file>.gguf` per `data/models.json`) — wrong layout, invisible
  to goose. Sharing **`HF_HOME`** would dedupe only models that both sides pulled from HF in
  cache layout — ours aren't. **Conclusion: don't fight it. Local-inference mode duplicates
  weights by design; the no-duplicates answer is the custom/openai provider against :6767**
  (the 3.2GB Llama it already downloaded can be deleted from its Models page, or left).
- **In the embedded shape** this is even cleaner: we seed the fenced config.yaml exactly like
  the PTY lane (same six lines + real key) before first launch — onboarding never even asks.

## 4. License — Apache-2.0 covers the embed

- One `LICENSE` (Apache-2.0 verbatim) at repo root; **no NOTICE file**; **no separate license
  in `ui/desktop`** — and `ui/desktop/package.json:160` explicitly says `"license":
  "Apache-2.0"`. No proprietary bits in the desktop tree.
- That permits: running the app against our runner (obviously), **building the renderer from
  source, extracting it from the asar, serving it, modifying it, shimming it, and shipping it
  inside MOT Deck** — with the standard §4 conditions (keep the license text, state changes).
  Our vendored-component pattern (pin + sha + provenance stamp) already satisfies this.
- **Trademark is the only fence**: goose is a Series of LF Projects, LLC; LF trademark policy
  applies (`GOVERNANCE.md:193` → lfprojects.org/policies). Presenting the tab as "Goose"
  running goose's own unmodified UI is nominative use — fine. Don't rebrand goose's UI as
  MOT's own work, and note the renderer assets include **Block lockup PNGs**
  (`block-lockup_black/white`) — leave the UI's self-identification as-is.

## 5. Isolation when WE launch anything goose

- **Best tool, better than HOME/XDG: `GOOSE_PATH_ROOT`** (absolute path required) redirects
  config/data/state/agents wholesale — `crates/goose-local-inference/src/paths.rs:40-46`
  (and the same Paths type is used across the crates). Point it at `data/goose/home` and
  nothing lands in `~/.config/goose` / `~/.local/{share,state}/goose`.
- **The Desktop app cooperates**: Electron main reads `GOOSE_PATH_ROOT` from its own env and
  passes it to the goosed child (`main.ts:989,1216`); the child env spreads `process.env`
  with `HOME` preserved (`gooseServe.ts:290-306`) — so launching
  `Goose.app/Contents/MacOS/Goose` directly with `HOME`/`GOOSE_PATH_ROOT` set fences it
  (NB: `open -a` does NOT pass env; exec the binary). Electron's own `userData`
  (`~/Library/Application Support/Goose` — settings.json, window state, Chromium profile)
  follows `HOME` via `os.homedir()`, so the HOME fence catches that too. Remaining leaks
  outside any fence: the HF model cache (unless `HF_HOME` is also set) and macOS keychain
  (seed `GOOSE_DISABLE_KEYRING: true` as in the PTY lane). Add
  `GOOSE_DISABLE_AUTO_DOWNLOAD=1` so a supervised app never self-updates.
- Our PTY lane's existing fence (HOME + all four XDG_* into `data/goose/home`, env applied
  before argv parse) already covers the embedded-goosed shape with zero changes — goosed is
  the same binary the lane runs.

## 6. Recommendation ladder (reordered per Debi's clarification)

**(i) BUILD: embed as an Unsloth-like component tab — feasible, first-of-its-kind, budget it
as a real slice.** Serve the pinned renderer bundle from the bridge + a `window.electron`
shim (~40 methods, ~12 load-bearing, listed in §2a) + our supervised
`goose serve --platform desktop --enable-scheduler --allowed-origin <bridge origin>` under
`GOOSE_PATH_ROOT=data/goose/home`, config pre-seeded at :6767 so onboarding never offers
duplicate downloads. What breaks/degrades: multi-window → same-tab, native file pickers and
goosehints/recipe FS editing, drag-in file paths, notifications. Risks to price in: the
preload contract and `_unstable` ACP methods drift per release (pin hard, contract-test the
shim), and WKWebView + WS + `--tls`'s self-signed cert needs the non-TLS loopback mode we
already control. Recommend a 1-day spike first: extract bundle, static-serve, shim only
`getAcpUrl`+`getSetting`+`on/off`+`getConfig`, see how far the chat core gets — that spike
answers 80% of the residual risk before committing the full slice.

**(ii) BRIDGE (interim while (i) is spiked/built): supervised standalone Desktop from a MOT
Deck button** — exec the app binary (not `open -a`) with `GOOSE_PATH_ROOT`, `HOME` fence,
`GOOSE_DISABLE_AUTO_DOWNLOAD=1`, seeded :6767 config. Two sentences as ordered: it is an app
handoff, not an embed, and it inherits our isolation + provider wiring wholesale. Prereq for
any shape: move `Goose.app` out of `~/Downloads` (App Translocation) into /Applications.

**(iii) Config-only fallback**: keep Debi's hand-installed Desktop but add the custom
provider at :6767 (§3) and delete/ignore the duplicate local Llama — no MOT work at all.

**PTY lane: keep it** regardless of (i)-(iii). It is the scriptable/recoverable surface
(resume/fork/import, contract-fenced, telemetry-killed), it shares the same binary+fence the
embed needs anyway, and if (i) ships and proves pleasant for daily use, retiring the PTY tab
becomes a UI decision, not an architecture one — record it as a ledger row then, not now.

## HONEST LIMITS

- The renderer was **not actually served in a browser** during this research — the "shimmable"
  verdict is source-level (bundle layout, transport, preload census), not an executed spike.
  The 1-day spike in (i) is the empirical test.
- ACP method names carry `_unstable` suffixes throughout — upstream reserves the right to
  break them; version-pinning renderer+binary as a matched pair is mandatory.
- Fork-network search was keyword-based (web ui / browser / serve) via web search + issue
  reads, not an exhaustive crawl of all forks; GitHub code-search API was auth-gated.
- `hf-hub` env behavior (`HF_HOME`/`HF_HUB_CACHE`) is from crate docs + the empirically
  observed default path, not a re-read of the crate source.
- Whether WKWebView's WebSocket + the shim survive goose's CSP (`utils/csp.ts` buildCSP is
  applied by Electron main, so a self-served page sets its own) — spike territory.
