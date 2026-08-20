# aider — pin decision + PTY-tab integration recon (2026-08-20, Opus-5 research)

Brief: Fable approved aider as the harness's coding agent in a PTY tab. This is the pin
decision + the integration shape. **Nothing built.** Evidence = URL or `file:line`.
Sandbox note: outbound `curl` is proxy-blocked (403 on CONNECT) and `api.github.com` was
**not** reachable; everything below came from `web_fetch`/WebSearch on HTML+raw files, or
from the vendored source on disk. Commit SHAs and star/commit counters are therefore
point-in-time reads of rendered pages, tagged ⚠️ where it matters.

---

## 1. Upstream vs fork — VERDICT: pin **upstream `Aider-AI/aider` at a commit on `main`**

### 1.1 Upstream health
| fact | evidence |
|---|---|
| Repo moved `paul-gauthier/aider` → `Aider-AI/aider` | https://github.com/Aider-AI/aider |
| Last **tagged** release `v0.86.0`, **August 2025** — no v0.87+ | WebSearch consensus, incl. https://summary.ecosyste.ms/projects/369932 ⚠️ tag list not read directly |
| `main` is at `0.86.3.dev` | https://raw.githubusercontent.com/Aider-AI/aider/main/aider/\_\_init\_\_.py → `__version__ = "0.86.3.dev"` |
| `main` is **NOT dormant** — its pinned deps are Feb-2026 dated | https://raw.githubusercontent.com/Aider-AI/aider/main/requirements.txt → `certifi==2026.2.25`, `regex==2026.2.28`, `openai==2.28.0`, `litellm==1.82.3` |
| Maintainer absence is a live community topic | https://github.com/Aider-AI/aider/issues/4613 ("Where is Paul?"), https://github.com/Aider-AI/aider/issues/4751 (future direction) |

Read honestly: **~12 months without a tag, but commits and a dependency refresh as recent as
Feb 2026.** Slow, not dead.

### 1.2 The fork — `cecli-dev/cecli` is the canonical one, and it is a real aider fork
⚠️ **NAME COLLISION IS REAL** — at least seven repos answer to "cecli"/"aider-ce":
`chemtov/cecli`, `dwash96/cecli`, `gopar/cecli`, `coconsultant/cecli`, `sannysanoff/aider-ce`,
`ErichBSchulz/aider-ce`. The canonical one is **`cecli-dev/cecli`** (it owns the `cecli.dev`
domain via a `CNAME` file in-repo, and `cecli.dev/install.sh` is the README's install path).

| fact | evidence (https://github.com/cecli-dev/cecli) |
|---|---|
| Genuine fork of aider, not a name collision | page meta: `repository_is_fork: true`, `repository_parent_nwo: Aider-AI/aider`, `repository_network_root_nwo: Aider-AI/aider` |
| 15,626 commits, 394 stars, 49 forks, 15 open issues, 8 open PRs | rendered repo page |
| **Apache-2.0 survives in the fork** | https://raw.githubusercontent.com/cecli-dev/cecli/main/LICENSE.txt — full Apache 2.0 text, verbatim |
| Tagged releases through **v0.100.12 (11 Jul)** ⚠️ year not shown in the render, almost certainly 2026 | https://github.com/cecli-dev/cecli/releases |
| Ships as PyPI `cecli-dev`, command `cecli` | README install section |

### 1.3 Why upstream wins anyway
cecli has **diverged, not tracked**. Its own README calls it "yet another cli agent" and its
roadmap is checked-off for: **Agent Mode with local tool-calling** (`agent-mode.md`, "allowed
local tools", "tool call limits", "dynamic tool discovery tool"), **MCP**, **subagents +
a `Delegate` tool**, **hooks with `pre_tool`/`post_tool`**, a **textual TUI**, and a **new
hashline SEARCH/REPLACE edit format**.

That is precisely the property we rejected `goose`, `gemini-cli` and `OpenHands` over. Fable's
stated reason for aider was that it is *"the only one structurally honest with small local
models"* — because it needs **no tool-calling** (§2.1). cecli's headline features re-introduce
tool-calling and a 35B-class agent loop. ⚠️ **UNVERIFIED** whether cecli's classic
`whole`/`diff` coders still work untouched with a 4B — plausible (they are inherited), but the
project's centre of gravity has moved away from that use case.

**VERDICT — pin `Aider-AI/aider` at a specific commit on `main`.**
- NOT the `v0.86.0` tag: it is ~1 year old and predates the Feb-2026 dependency refresh
  (openai 2.x / litellm 1.82) that a current OpenAI-compatible endpoint wants.
- An untagged commit pin is **native to this repo's doctrine** — `odysseus` is already pinned
  to a bare commit on a non-default branch (`harness.yaml`, odysseus pin `25c9e73` on `dev`).
- ⚠️ **The exact SHA could not be resolved from the sandbox.** Resolve at build time and record
  it in `harness.yaml` with the date, exactly as the odysseus pin does:
  `git ls-remote https://github.com/Aider-AI/aider.git refs/heads/main`
- **Plan B, documented not adopted:** if upstream `main` goes >6 months without a commit, move
  to `cecli-dev/cecli` at a release tag (Apache-2.0 verified, so the licence stays clean) and
  accept the tool-calling-flavoured agent mode as *optional*, keeping `--edit-format whole`.

---

## 2. Local-model fitness at that pin

### 2.1 No tool-calling required — CONFIRMED
Every edit format is a **plain-text convention inside the assistant's normal message content**:
`whole`, `diff` (SEARCH/REPLACE), `diff-fenced`, `udiff`, `udiff-simple`, `patch` (V4A),
`editor-diff`, `editor-whole`, `editor-diff-fenced`
(https://aider.chat/docs/more/edit-formats.html). The only function-calling coder in the tree,
`single_wholefile_func_coder`, is **commented out of** `aider/coders/__init__.py`
(https://github.com/Aider-AI/aider/blob/main/aider/coders/__init__.py) — i.e. not selectable.

**For a 4B: use `--edit-format whole`.** Upstream's own guidance
(https://aider.chat/docs/troubleshooting/edit-errors.html): *"Run aider with `--edit-format
whole`…"*, and, said plainly, *"Most local models are just barely capable of working with
aider, so editing errors are probably unavoidable"* / *"Local models which have been quantized
are more likely to have editing problems."* Cost: the model re-emits the whole file on each
edit (https://aider.chat/docs/more/edit-formats.html) — with `max_tokens` now sent explicitly
(sampling v1) that is a real interaction, not a truncation trap. `whole` is also the
ModelSettings default (https://aider.chat/docs/config/adv-model-settings.html).

### 2.2 Wiring to our runner on :6767
`export OPENAI_API_BASE=http://127.0.0.1:6767/v1` + `OPENAI_API_KEY=…`, then
`aider --model openai/<model-name>` (https://aider.chat/docs/llms/openai-compat.html).
Flag equivalents exist: `--openai-api-base` / `--openai-api-key`.

⚠️ **A dummy key is MANDATORY even though our runner is keyless.** Upstream states it for the
LM Studio lane: *"Even though LM Studio doesn't require an API Key out of the box the
… API_KEY must have a dummy value like `dummy-api-key` set or the client request will fail
trying to send an empty `Bearer` token"* (https://aider.chat/docs/llms/lm-studio.html). ⚠️
UNVERIFIED as an explicit statement for the generic `openai/` lane, but it is the same client
and the same empty-Bearer failure. Use `OPENAI_API_KEY=harness-local`.

⚠️ **Use `wire_model_id()`, do not reinvent it.** `bridge/app.py` already encodes the rule the
harness learned the hard way: gguf → the registry id (llama-server is launched with `--alias`),
**MLX → the registry PATH** (mlx_lm.server resolves the request's `model` field as a model to
LOAD; a registry id 404s on huggingface.co → 400). So the argv is
`--model openai/<wire_model_id(entry)>`.

### 2.3 Context window / unknown-model warnings
`--max-chat-history-tokens` is **not** the context window — it is the history-summarisation
threshold. Context length for a model litellm doesn't know goes in
`.aider.model.metadata.json` (`max_input_tokens` / `max_output_tokens`, keyed by the fully
qualified `provider/model` name), searched home → git root → cwd, or `--model-metadata-file`
(https://aider.chat/docs/config/adv-model-settings.html). Upstream downplays it: *"Aider never
enforces token limits, it only reports token limit errors from the API provider"*
(https://aider.chat/docs/llms/warnings.html) — so the honest v1 move is
`--no-show-model-warnings` and let the runner be the authority (it already is: our `Load`
group owns `--ctx-size`). Behavioural settings (e.g. pinning `edit_format` per model) go in
`.aider.model.settings.yml`.

### 2.4 Lockdown flags for a harness default
| flag | env var | why |
|---|---|---|
| `--analytics-disable` | `AIDER_ANALYTICS_DISABLE` | **permanent** opt-out. `--no-analytics` is session-only. Default behaviour enables analytics *"for a random subset of users"* (https://aider.chat/docs/more/analytics.html) |
| `--no-check-update` | `AIDER_CHECK_UPDATE=false` | no phone-home on launch |
| `--no-show-release-notes` | `AIDER_SHOW_RELEASE_NOTES=false` | no prompt on version change |
| `--no-auto-commits` | `AIDER_AUTO_COMMITS=false` | edits stay uncommitted; the user commits |
| `--no-dirty-commits` | `AIDER_DIRTY_COMMITS=false` | never commit the user's pre-existing WIP |
| `--no-gitignore` | `AIDER_GITIGNORE=false` | don't rewrite the user's `.gitignore` |
| `--edit-format whole` | `AIDER_EDIT_FORMAT` | §2.1 |
| `--no-show-model-warnings` | `AIDER_SHOW_MODEL_WARNINGS=false` | §2.3 |
| `--disable-playwright` | `AIDER_DISABLE_PLAYWRIGHT` | **load-bearing for a PTY tab — see §4** |
| `--weak-model` / `--editor-model` | `AIDER_WEAK_MODEL` / `AIDER_EDITOR_MODEL` | point at the same local model, or the aux runner (:6768) |

⚠️ **Do NOT set `--yes-always`** and **do NOT set `--no-git`** — see guardrails, §3.4.
Config precedence is `.aider.conf.yml` home → git root → cwd, **last wins**
(https://aider.chat/docs/config/aider_conf.html), so a harness-written per-workspace file
beats a user's home config — decide deliberately which layer we own.

---

## 3. PTY tab shape

### 3.1 What Hermes already proves (read from `vendor/hermes`)
- Client: **xterm.js**, self-hosted — `@xterm/xterm 6.0.0` + `addon-fit 0.11.0` /
  `addon-unicode11 0.9.0` / `addon-web-links 0.12.0` / `addon-webgl 0.19.0`
  (`vendor/hermes/web/package.json`), mounted in
  `web/src/components/HermesConsoleModal.tsx:3-7`.
- Server: `hermes_cli/pty_bridge.py` — **`ptyprocess`, deliberately not stdlib**, with the
  reasoning in its own docstring: *"Zero Node dependency on the server side… pure-Python
  wrapper around the OS calls"*, and byte-oriented I/O because *"streaming ANSI is inherently
  byte-oriented and UTF-8 boundaries may land mid-read"* (`pty_bridge.py:1-27`). POSIX-only
  (`fcntl`/`termios`), so macOS is fine.
- Endpoint: `@app.websocket("/api/pty")`, `hermes_cli/web_server.py:16071`.
- **Wire protocol is beautifully small and worth copying verbatim:** raw bytes both ways, no
  JSON framing; the ONLY control message is an in-band resize escape
  `\x1b[RESIZE:<cols>;<rows>]` (`web_server.py:14848`, `_RESIZE_RE`), consumed server-side and
  never written to the PTY (`web_server.py:16233-16236`, comment: *"Resize escape is consumed
  locally, never written to the PTY."*).
- Dimension clamping against broken probes (WSL2 reports `columns=131072`) —
  `pty_bridge.py:_clamp_dimension`, `_MAX_COLS = 2000`.

### 3.2 Smallest honest architecture for us
The bridge can host this with **zero new Python dependencies**: `websockets>=12` is already in
`bridge/requirements.txt` (uvicorn's WS server support), and macOS gives us stdlib
`pty` + `fcntl` + `termios` + `struct`. (Hermes chose `ptyprocess`; we could too, but that is
one more wheel in the fat wheelhouse for a wrapper that is ~60 lines.)

```
Swift tab "Coding"  ──▶  http://127.0.0.1:8700/pty/aider      (static page, bridge/panel)
                             │  xterm.js from bridge/panel/assets/vendor/  (fetch_vendor_assets.sh)
                             ▼
                         ws://127.0.0.1:8700/api/pty/aider     (FastAPI @app.websocket)
                             │  bytes ⇄ bytes;  \x1b[RESIZE:c;r]  consumed server-side
                             ▼
   pty.openpty() + Popen(argv, stdin/stdout/stderr=slave, start_new_session=True, cwd=<workspace>)
   env: OPENAI_API_BASE=http://127.0.0.1:6767/v1   OPENAI_API_KEY=harness-local
        TERM=xterm-256color   (COLUMNS/LINES unset — TIOCSWINSZ owns the size)
   argv: data/aider-venv/bin/aider --model openai/<wire_model_id> --edit-format whole
         --analytics-disable --no-check-update --no-auto-commits --no-dirty-commits
         --no-gitignore --no-show-model-warnings --disable-playwright
```
- **Assets:** xterm.js + fit addon go through `scripts/fetch_vendor_assets.sh` into
  `bridge/panel/assets/vendor/`, exactly like `codemirror.min.js` / `mermaid.min.js` today, and
  ride the fat seed for free (`build_app.sh` already bundles that dir).
- **One session at a time**, 409 on a second connect — the `VoiceBusy` precedent. A second PTY
  is a second claimant on one workspace directory.

### 3.3 Risks
1. **⚠️ SECURITY, the big one: WebSockets are NOT subject to CORS.** Without an `Origin` check,
   any web page the user visits in any browser can open `ws://127.0.0.1:8700/api/pty/aider`
   and get a process on their Mac. Loopback binding is **not** sufficient. Hermes gates this
   explicitly (`_ws_host_origin_reason`, `web_server.py:16096-16100`, close code 4403) — copy
   the gate, not just the port.
2. **Process lifecycle.** `start_new_session=True` gives a process group, so on disconnect we
   can SIGHUP → SIGTERM → SIGKILL the **group**, and aider's children (`/run` subprocesses,
   linters) die with it. Without it, an orphan holds the workspace. Plus an idle reaper.
3. **Reconnect.** Hermes needed `pty-reconnect.ts` *and* `pty-resume-sanitizer.ts` — the latter
   exists because *"An unterminated CSI must never reach xterm: it would leave the parser…"*
   (`web/src/lib/pty-resume-sanitizer.test.ts:118`). **v1 must NOT replay a buffer**; a dropped
   socket ends the session, said plainly in the UI. Inheriting that bug class is not worth it.
4. **Resize fidelity.** FitAddon + rAF-debounce (Hermes: `HermesConsoleModal.tsx:384-386`), and
   clamp like `_clamp_dimension`. aider's `prompt_toolkit` redraw is size-sensitive.
5. **WKWebView key handling.** ⌘V/paste and key capture inside xterm.js are known-solvable but
   not free — Hermes carries `web/src/lib/chatImagePaste.ts` for exactly this.
6. **ANSI/TTY fidelity.** aider uses `rich` + `prompt_toolkit`; both need a real TTY (we give
   one) and a sane `TERM`. ⚠️ Unverified in a WKWebView: mouse reporting and bracketed paste.

### 3.4 Guardrails — say this part out loud
- **The harness path-guard fence does NOT cover aider.** `guards/harness-path-guard` is a
  *Hermes plugin* on Hermes's `pre_tool_call` hook. aider is a separate process outside it.
- **Run only in a chosen workspace dir** (`cwd=`), never `$HOME`, never the harness repo by
  default. A workspace picker is slice 2; slice 1 hardcodes one configured path.
- **Keep git ON.** `--no-auto-commits` (don't commit for the user) but **not** `--no-git` —
  git is the *only* undo aider has (`/undo`, `/diff`). Disabling it removes the safety net
  while keeping all of the write power. This asymmetry is deliberate.
- **Never `--yes-always`.** aider's per-edit confirmation prompt *is* the approval flow, and it
  renders natively in the PTY. That is the whole reason a PTY tab is honest here.
- `--disable-playwright` is a guardrail, not a nicety: without it aider can print *"Install
  playwright?"* and **block on stdin inside our tab** (`aider/scrape.py`).

---

## 4. Install shape
- **Vendored pinned clone**, matching hermes/odysseus/searxng: `vendor/aider` at the chosen
  commit, installed editable into **`data/aider-venv`**. This also makes
  `bridge/contract_tests/` possible (they read vendored source).
- **Python:** upstream `pyproject.toml` says `requires-python = ">=3.10,<3.15"`. Our bundled
  standalone CPython is **3.12.11** (`harness.yaml` `build.python_version`) — in range.
- **uv resolved by explicit path** (the standing Finder-minimal-PATH rule), falling back to
  `python -m pip`; never `bin/pip`.
- **Size ⚠️ ESTIMATE ~350–450 MB**: `litellm`, `tokenizers`, `tree-sitter-language-pack 0.13.0`,
  `scipy`, `numpy`, `pillow`, `fastapi`+`starlette`, `rich`, `prompt_toolkit`. No torch —
  torch/llama-index/scikit-learn are the **optional `help` extra** only. Not measured.
- **Offline-wheelhouse red flags** (from `requirements.txt` + `requirements/`):
  - `tree-sitter-language-pack` + ~4 `tree-sitter-*` grammars — binary wheels, per-platform AND
    per-CPython; must resolve `macosx arm64 cp312`. Probably fine; must be verified.
  - `scipy` / `numpy` — version-gated on `python_version` inside the requirements file; large.
  - `sounddevice` + `soundfile` + `pydub` + `audioop-lts` — **core deps**, binding PortAudio /
    libsndfile through `cffi`. Only used by voice-to-code, but they are not optional.
  - `pypandoc` — wants a `pandoc` **binary** at runtime for the `/web` fallback.
  - `mixpanel` **and** `posthog` are **core** deps → §2.4's `--analytics-disable` is not
    paranoia, it is the mitigation.
  - **playwright is NOT core** (`optional-dependencies`, `requirements-playwright.in`); without
    it `/web` degrades to httpx+BeautifulSoup rather than failing.
- **Contract test** (`bridge/contract_tests/test_aider_contract.py`), same shape as
  `test_llama_tts_contract.py`: skip cleanly in-sandbox; on the Mac run `aider --help` and pin
  `--edit-format`, `--analytics-disable`, `--no-auto-commits`, `--disable-playwright`,
  `--no-show-model-warnings`, `--model`. A pin bump that renames one of these then trips loudly
  instead of silently launching an aider that phones home.

---

## 5. Build plan

### Slice 1 — the tab exists and talks to our runner
1. `harness.yaml`: `components.aider` (repo, commit pin + date, `installed:false`,
   `enabled:false`) + `aider.workspace` (one path) + `aider.edit_format: whole`.
2. `scripts/install_component.sh` aider branch → `vendor/aider` shallow clone at the pin →
   `data/aider-venv` (bundled CPython, explicit-path uv, `python -m pip install -e`).
3. `scripts/fetch_vendor_assets.sh` += xterm.js 6.0.0 + addon-fit → `bridge/panel/assets/vendor/`.
4. Bridge: `GET /pty/aider` (static page) + `WS /api/pty/aider` — stdlib pty, byte passthrough,
   the `\x1b[RESIZE:c;r]` control escape, **Origin gate + loopback + one-session lock**,
   process-group teardown, log to `data/logs/aider.log`.
5. argv/env built by a **pure** `aider_argv(entry, workspace, cfg)` — a unit-testable decision
   table (wire id per engine, the lockdown flags, edit format): the `tts_argv`/`stt_argv` pattern.
6. Swift: a sixth tab pointing at `:8700/pty/aider`; plain WKWebView, lazy-load, the existing
   "Not reachable yet" placeholder + ⌘R retry, no skin injection.
7. Tests: `test_aider_argv.py` (argv/env totality, both engines, every lockdown flag present,
   `--yes-always` and `--no-git` asserted **absent**), `test_pty_bridge.py` (resize clamp,
   escape consumed-not-written, teardown kills the group, second connect → 409, Origin gate),
   plus the contract test above.
   **Verify:** open the tab → aider banner → `/add <file>` → ask for a one-line change → aider
   prints the whole-file edit and asks to apply → `y` → the file changes on disk and
   `git diff` shows it, with **no** commit made.

### Slice 2 — polish
- **Model handoff:** the tab reads the live model from `/api/status` (`runner.pin` →
  `display_model_id`, running-gated — the exact rule the v2.1 lane-label fix established) and
  restarts aider on a model change, with a visible "restart to apply" affordance rather than a
  silently stale process.
- **Workspace picker:** a small chooser (recent dirs, persisted), a refusal to start in `$HOME`
  or the harness root, and the chosen path shown in the tab header — because the workspace
  **is** the security boundary and must never be implicit.
- `.aider.conf.yml` / `.aider.model.settings.yml` written per workspace so our defaults are
  visible and editable rather than buried in argv (and so `/help` reports the truth).
- Optional: the aux runner (:6768) as `--weak-model`, so commit-message/summary calls stop
  competing with the main slot — the same collision the direct chat lane was built to dodge.

---

**Sources:** [Aider-AI/aider](https://github.com/Aider-AI/aider) ·
[aider `__init__.py`](https://raw.githubusercontent.com/Aider-AI/aider/main/aider/__init__.py) ·
[aider requirements.txt](https://raw.githubusercontent.com/Aider-AI/aider/main/requirements.txt) ·
[issue #4613](https://github.com/Aider-AI/aider/issues/4613) ·
[issue #4751](https://github.com/Aider-AI/aider/issues/4751) ·
[cecli-dev/cecli](https://github.com/cecli-dev/cecli) ·
[cecli LICENSE.txt](https://raw.githubusercontent.com/cecli-dev/cecli/main/LICENSE.txt) ·
[cecli releases](https://github.com/cecli-dev/cecli/releases) ·
[edit formats](https://aider.chat/docs/more/edit-formats.html) ·
[edit errors](https://aider.chat/docs/troubleshooting/edit-errors.html) ·
[openai-compat](https://aider.chat/docs/llms/openai-compat.html) ·
[LM Studio](https://aider.chat/docs/llms/lm-studio.html) ·
[Ollama](https://aider.chat/docs/llms/ollama.html) ·
[warnings](https://aider.chat/docs/llms/warnings.html) ·
[options](https://aider.chat/docs/config/options.html) ·
[analytics](https://aider.chat/docs/more/analytics.html) ·
[aider_conf.yml](https://aider.chat/docs/config/aider_conf.html) ·
[adv-model-settings](https://aider.chat/docs/config/adv-model-settings.html) ·
[ecosyste.ms summary](https://summary.ecosyste.ms/projects/369932)
