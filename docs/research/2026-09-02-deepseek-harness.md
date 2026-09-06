# DeepSeek Harness — is it doable like Unsloth/OpenCode? (2026-09-02)

**Question (Debi):** "let's add deepseek harness to our app, but just like Unsloth or Opencode
in our app: https://github.com/deepseek-ai/deepseek-harness — Is this doable? Any issues?"

> ## ⚠️ BUILT 2026-09-03 — READ THIS BOX BEFORE TRUSTING ANY CLAIM BELOW
>
> The lane SHIPPED (ledger S35) and the build measured things this read could only
> infer. Everything below stands as the research it was; these seven claims did **not**
> survive contact and are corrected here so the next reader does not act on them:
>
> 1. **Telemetry does NOT default to `FEEDBACK_ONLY`.** At the shipped pin the composed
>    plugin tree reads `mode: process.env.DSH_TELEMETRY_MODE || 'DISABLED'` — verified in
>    `dsh --dump-config`. Better than the brief said. (We set
>    `DSH_TELEMETRY_DISABLED=1` anyway, so a future default cannot move it.)
> 2. **There is no `pnpm install && pnpm run build` step and no 100MB checkout.** §4 read
>    the MONOREPO. The published npm package is installed with plain `npm install` and
>    serves immediately: MEASURED 455 packages / 283MB / 6m0s, no build.
> 3. **`engines` is NOT enforced.** §4's `engines.node: "^22.19.0 || >=24.0.0"` is in the
>    monorepo root package.json, which npm never sees — the PUBLISHED package declares no
>    `engines` at all, so nothing checks Node but `scripts/ensure_node.sh`.
> 4. **`compat.maxTokensField: max_tokens` is NOT needed** (§3, §7 issue 3 both predicted
>    it would be). Measured on the wire and in both of our engines' source: llama.cpp
>    b10662 and mlx_lm.server accept BOTH cap spellings. Ledger U68 has the table.
>    `supportsDeveloperRole: false` IS set, for a different and measured trigger.
> 5. **`input: [text]` is not a model-entry field** at this pin (the §3 sketch used it).
>    The entry schema is id/name/contextWindow/maxTokens/reasoningEfforts/compat;
>    modalities resolve through the route's `defaultInput`.
> 6. **`providers` must be a MAP, not the array the §3 example implies is optional** — the
>    pre-release array shape fails plugin load with migration directions.
> 7. **§3's "⚠️ UNVERIFIED: a provider-less first boot may nag toward DeepSeek" is now
>    ANSWERED, and it is worse than a nag:** the first boot shows an "Internal Testing
>    Notice" modal (once) and then refuses to accept a message until a WORKSPACE is
>    chosen — through a native `osascript` folder dialog that dsh opens itself. Ledger
>    U67. Nothing points at DeepSeek's cloud, though: that part of §3 was right.
>
> Also worth knowing, because §7's plan sketch assumed otherwise: the pin is upstream's
> own `latest` dist-tag (0.1.1-rc.2), NOT the highest published version — `next` was a
> release ahead on the day. And the "restart to rebind" half of our house pattern does
> **not** apply here: dsh re-reads its settings per operation, which is one place this
> lane is better than OpenCode.

**Read-only research.** No files outside `docs/research/` touched in this repo; nothing
installed, run, or signaled. Method: `git clone --depth 1
https://github.com/deepseek-ai/deepseek-harness.git` to scratchpad, read at HEAD
`49a606bc5b5934603f22a26957a07dc799ab0291` (2026-09-02, "release/dsh-0.1.2-alpha.5"),
plus `npm view @deepseek-ai/dsh`. All citations below are file paths in that clone
unless marked ⚠️ UNVERIFIED (not confirmed in source/docs) or WebSearch (used only to
locate the repo, not for technical claims).

---

## 0. Verdict up front

**Doable like-Unsloth/OpenCode — a real web-UI tab, and a good one.** It is a coding-agent
harness (Claude-Code-shaped), not a DeepSeek-specific chat app, it ships an actual
OpenAI-compatible custom-provider mechanism built for exactly this, it defaults to
loopback with no auth-bypass tricks needed, telemetry is off until the user explicitly
runs `/feedback`, and macOS arm64 is a first-class supported platform (Seatbelt sandbox
backend, not an afterthought). License is MIT, clean.

**Top 3 issues**, in order of how much they'd cost us:
1. **No pinned native binary — it's an online, npm/pnpm, build-from-source install**, closer
   to Hermes/Odysseus's footprint than to OpenCode's single-binary-per-platform pin. Cold
   install pulls a large pnpm workspace (100MB source, no `node_modules`) and needs a build
   step (`pnpm run build`) before `pnpm dsh web` will serve anything.
2. **Developer preview, compatibility-breaking-changes disclaimer in the README itself.**
   Fourteen npm versions to date, all `0.0.x`/`0.1.x`-`alpha`/`rc` — this is pre-1.0, moving
   fast, and the safety doc says plainly it has not had a security audit.
3. **Custom-provider config quirks that need the same "OpenCode-style" care we already
   learned**: request-shape mismatches (`developer` role, `max_completion_tokens`) against
   non-OpenAI gateways are common enough that the docs dedicate a troubleshooting section to
   them, and our runner will need the `compat` overrides spelled out below.

None of these are "not sensibly" issues — they're all things our existing seeding pattern
(OpenCode's provider-block rewrite) already knows how to handle, applied to a new target.

---

## 1. What it actually is

**Not** a DeepSeek-specific chatbot or an eval harness. It is **a general-purpose coding
agent harness** — the same product category as Hermes, OpenCode, or Claude Code itself.
README: *"DeepSeek Harness (`dsh`) is an open-source agent harness developed by DeepSeek
AI. It is built on an everything-is-a-plugin architecture and powered by
[Cordis](https://github.com/cordiverse/cordis)"* (`README.md:5-7`). It's a pnpm monorepo:
`apps/{cli,web}` are the two front ends; `packages/` holds ~50 plugin packages — `llm`
(model adapters, including `llm-pi-ai` and `llm-deepseek`), `credentials`, `sandbox`
(cross-platform process confinement), `mcp`, `lsp`, `subagent`, `plan`, `skill`,
`workflow`, `acp`, `e2b` (cloud sandbox). Multiple "profiles" boot different surfaces from
one install: `web`, `headless`, `acp`, `sdk`, `sdk-minimal` (`packages/boot/app-boot`).
It can also run headless as an ACP agent (editor integration) or via an SDK — those modes
aren't relevant to us, but they confirm the "harness," not "chat app," framing.

---

## 2. Web UI — yes, exactly the OpenCode/Unsloth shape

`dsh web` starts a **Web UI on `http://127.0.0.1:3080`** by default and opens the default
browser for a local launch (`README.md:23-27`, `apps/cli/reference/README.md:80`). The
port is overridable: `dsh --profile web --port 8080` or `dsh web --host <h> --port <p>
--no-open` (`apps/cli/README.md:26`, `apps/cli/reference/README.md:27,70`). Two details
that matter for embedding it as a tab, both good news:
- **Loopback-only by policy, not just by default**: *"The CLI intentionally does not
  support `--host 0.0.0.0` and exits with a usage error"* (`apps/cli/reference/README.md:80`)
  — stronger than OpenCode, which merely defaults to loopback and warns you not to pass
  `--mdns`.
- An SSH session suppresses the auto-browser-open (prints the URL instead) — irrelevant to
  us but shows the same "well-behaved local server" design as OpenCode's `serve`/`web`.

This is a **web-UI tab candidate**, not a PTY lane — same shape as OpenCode's `opencode
web`, not Goose CLI/Aider's terminal shape. No scope-fork decision needed on that axis;
the app itself already draws the line the way our house pattern wants.

---

## 3. Talking to our runner (127.0.0.1:6767/v1)

**Yes, and it's a first-class, documented mechanism** — closer to OpenCode's
config-resident-provider pattern than to Hermes's probe-based one.

- **Where it lives:** `$DSH_HOME/settings.yaml` (default `$DSH_HOME` = `~/.dsh`), under the
  `llm-pi-ai` plugin's `providers` map, plus `$DSH_HOME/.credentials.yaml` for the actual
  key (`docs/user/guide/providers.md:13,36-48`). Settings are read fresh per-request —
  *"Model changes take effect on the next request without restarting the server"*
  (`docs/user/guide/providers.md:5`) — the same live-reread property OpenCode and Hermes
  have, better than the "restart to rebind" cases in our isolation-mode brief.
- **Format, minimal example**, from the docs verbatim shape (`providers.md:38-48`):
  ```yaml
  llm-pi-ai:
    providers:
      mot-deck:
        apiKeyEnv: MOT_DECK_RUNNER_API_KEY  # or apiKey inline via the UI's key field
        api: openai-completions
        baseURL: http://127.0.0.1:6767/v1
        models:
          - id: <registry-wire-id>
            input: [text]        # add image if the model is VLM-capable
  ```
- **The provider ID is permanent** once created — renaming means "add a new provider,
  delete the old one" (`providers.md:27`), the same rename-honouring discipline our
  isolation-mode doc already codifies for Odysseus/Hermes (match by base_url/stable id,
  never blind-replace).
- **Model discovery**: the UI's "Fetch available models" button does a live `GET /models`
  against the base URL (`providers.md:29,128`) — so a populated `models:` list in
  settings.yaml (like OpenCode's config-resident catalog) survives the runner being down;
  the live-fetch button is optional convenience, not the only path.
- **Request-shape overrides exist and are documented**, not guessed
  (`providers.md:82-116`): `compat.supportsDeveloperRole: false` and
  `compat.maxTokensField: max_tokens` are the two most common fixes for a non-OpenAI
  gateway; a per-model `compat` block overrides the per-route default. Worth setting both
  defensively when we seed the entry, exactly as OpenCode's start script encodes per-model
  `tool_call` facts rather than relying on live probing.
- **No forced DeepSeek account.** "Configure DeepSeek" (the one-API-key-field DeepSeek
  card) is presented as ONE option among "Add provider" (catalog clouds) and "Add a custom
  provider" (us) — nothing in the docs or the settings schema makes the DeepSeek card
  mandatory to reach a usable state (`providers.md:7-29`). ⚠️ UNVERIFIED: whether a
  completely provider-less first boot shows an onboarding nag pointed at DeepSeek — not
  confirmed either way in the docs read here.
- **Does it phone home otherwise?** See §6 — telemetry exists but is off until the user
  explicitly records feedback; DeepSeek-specific requests (the DeepSeek card, if used) do
  carry the anonymous per-install id, but that's opt-in by using that card at all.

---

## 4. Install shape

| Dimension | Finding | Evidence |
|---|---|---|
| Language/runtime | TypeScript/Node, pnpm monorepo. `engines.node: "^22.19.0 \|\| >=24.0.0"` | `package.json:8-10` |
| Binary vs source | **No prebuilt native binary equivalent to OpenCode's.** `npx @deepseek-ai/dsh web` fetches the npm package and its deps at run time; running from a checkout needs `pnpm install && pnpm run build` before `pnpm dsh web` serves anything | `README.md:19-41` |
| Install size | Repo checkout (source only, no `node_modules`) is **100MB**; the published `@deepseek-ai/dsh` npm tarball itself is small (`dist.unpackedSize` ≈ 120KB) but pulls its own dependency tree via npm at install time — this is the Hermes/Odysseus dependency-footprint class, not the OpenCode single-binary class | `du -sh` on clone; `npm view @deepseek-ai/dsh dist.unpackedSize` |
| Pin cleanly? | Yes — npm publishes real, distinct versions (14 to date: `0.0.1-rc.1` … `0.1.2-alpha.5`), so pin-by-npm-version works exactly like our OpenCode discipline | `npm view @deepseek-ai/dsh versions` |
| macOS arm64 | **First-class**, not an afterthought. The `dsh-sandbox-local` package's own runner-selection table lists Linux (bwrap/Landlock), **macOS (Seatbelt / `sandbox-exec`)**, and Windows (ACL) as three maintained platform backends, each reporting `full`/`partial` enforcement honestly | `packages/sandbox/sandbox-local/README.md` |
| Port | `:3080` default, CLI-overridable, loopback-enforced (see §2) | as cited above |
| Daemons | None found beyond the web server process itself; no background service, no launchd-style installer script encountered in this read | (absence, not a search of every file — read `apps/cli`, `packages/boot`, README/docs only) |

**Net:** this is a from-source (or npm-fetched) TypeScript app, not a pinned single
binary. Fits the shape of our Hermes/Odysseus installs (`install_*.sh` running
npm/pip against a pinned version, own fenced home dir) rather than OpenCode's
"download one Mach-O and go" shape — a real but known cost class, not a blocker.

---

## 5. License

**MIT**, root `LICENSE` file, copyright DeepSeek 2026 (`LICENSE:1-3`). Clean — the same
Apache/MIT-friendly bucket as OpenCode. `THIRD_PARTY_NOTICES.md` was checked for
copyleft leakage: the only GPL-family entries found are **dev-only tooling**
(`eslint-plugin-sonarjs`, LGPL-3.0-only) explicitly noted as *"run only as development
tooling; their code is not linked into or distributed with any DeepSeek Harness
artifact"* — no runtime copyleft dependency (`THIRD_PARTY_NOTICES.md`, grep for
AGPL/GPL). One native addon, `@deepseek-ai/node-addon-landlock-run` (the Linux Landlock
sandbox helper, irrelevant on macOS), is **BSD-3-Clause**
(`native/landlock-run/package.json:6`).

---

## 6. Red flags — checked specifically, per Debi's ask

- **`pkill`/`killall` in scripts** (the thing that burned us before): **none found.**
  `grep -rln "pkill\|killall" scripts apps packages` returned zero hits.
- **Telemetry**: real, but off-by-default and disclosed at length, not hidden. Two feeds
  exist (`packages/session/session-telemetry*`), gated by `DSH_TELEMETRY_MODE`, defaulting
  to `FEEDBACK_ONLY` — the Agent Note states plainly: *"Fresh profiles and projects make
  no telemetry network request until the user records `/feedback`"*
  (`.agents/notes/implemented/feature/2026-08-10-telemetry-default-off.md`). An anonymous
  per-install UUID (`$DSH_HOME/.anonymous-user-id`, random via `crypto.randomUUID()`,
  never derived from hostname/network/git — `packages/identity/*/README.md`) tags
  telemetry, feedback acknowledgements, and DeepSeek-provider requests specifically, so
  those three correlate per-install; it is not sent unless one of those three features
  fires. A hard opt-out env var (`DSH_TELEMETRY_DISABLED`) exists as an authoritative
  pre-load kill switch. Nothing here contacts a server on ordinary chat/tool-call turns
  through a custom provider like ours.
- **Writes outside its own folder**: not found in this read. Config lives under
  `$DSH_HOME` (default `~/.dsh`), overridable via env — same fenced-home shape as our
  Hermes/Goose installs.
- **Hard cloud dependency**: none found for basic operation. The DeepSeek-cloud card is
  optional, sitting alongside "Add provider" (other clouds) and "Add a custom provider"
  (us) with no evidence in the docs that one of the three is mandatory to reach a usable
  chat state (§3).
- **Safety posture, stated by the project itself**: *"DeepSeek Harness is experimental
  developer-preview software. It has not undergone a security audit and must not be
  treated as secure or production-ready"* and it *"can execute model-generated code and
  commands, load third-party plugins, and access the network, processes, credentials, and
  files made available to it"* (`SAFETY.md:7,9`) — the same class of disclaimer Hermes and
  aider carry, worth the same respect (least-privilege install, our existing sandbox/
  approval doctrine still applies at our layer regardless of dsh's own Seatbelt backend).

---

## 7. Verdict for Debi, plain words

**Doable like-Unsloth/OpenCode — install it as an embedded web-UI tab.** It clears every
bar that made OpenCode work as a tab (own web UI on its own loopback port, own config
surface it reads live, a documented custom-OpenAI-compatible-provider mechanism built for
exactly our situation, MIT license, no `pkill`/`killall`, macOS arm64 first-class) and is
meaningfully more forthcoming about its telemetry and safety posture than most of what
we've integrated so far.

**Top 3 issues, restated for the build:**
1. It's an **online, from-source/npm install** (Hermes/Odysseus weight class), not a
   pinned single binary (OpenCode weight class) — budget the same class of install script
   and pin discipline as `install_hermes.sh`/`install_opencode.sh`, not a five-line fetch.
2. **Pre-1.0, developer preview, breaking changes expected** — the settings.yaml schema
   for `llm-pi-ai.providers` (and the `compat` override vocabulary) is exactly the kind of
   thing that has burned us with Goose's declarative-provider JSON; pin the npm version and
   contract-test the schema the same way.
3. **Request-shape compat flags will likely be needed** for our runner specifically
   (`supportsDeveloperRole: false`, `maxTokensField: max_tokens` are the documented common
   fixes for non-OpenAI gateways) — budget for the same "fifteen-minute experiment before
   writing the install script" that closed the OpenCode tool-calling question.

**Isolation-seeding plan sketch** (following the OpenCode pattern from
`docs/research/2026-08-29-isolation-mode.md` §1 — write into the app's OWN config surface,
merge-never-overwrite, enumerate registry models as facts, verify through its own API):
1. `scripts/install_deepseek_harness.sh` — pin `@deepseek-ai/dsh@<version>` via pnpm/npm
   into `data/deepseek-harness/`, `pnpm run build` once at install time (not per-Start).
2. New `scripts/seed_dsh_config.py`, same shape as `seed_opencode_config.py`: on every
   Start, write/merge ONE named provider entry under `llm-pi-ai.providers.mot-deck` in
   `$DSH_HOME/settings.yaml` (fenced home, e.g. `data/deepseek-harness/home`) —
   `baseURL: http://127.0.0.1:6767/v1`, `apiKeyEnv` pointing at our runner key env,
   `models:` enumerated from `MR.offerable(registry)` (the same registry walk
   `seed_opencode_config.py` already does), with `compat.supportsDeveloperRole: false` and
   `compat.maxTokensField: max_tokens` set defensively per model. Match/update by
   provider-id stability, never blind-replace (the provider ID is permanent per §3, so our
   own id `mot-deck` is the stable key across seeds).
3. `motdeck.yaml` component block, `depends_on: []` (same reasoning as OpenCode — usable
   against any provider it has configured; start the runner yourself for the local lane),
   `port: 3080` (or a harness-chosen port passed via `--port` at spawn, matching the
   OpenCode `--port` override precedent since upstream's doc default is a fixed 3080 not an
   ephemeral one — confirm at pin time whether `--port` is required the way OpenCode's is).
4. `start_component.sh` arm: run the seed script, then launch `dsh web --host 127.0.0.1
   --port <yaml> --no-open`, health-poll the port, add a tab in `app/main.swift`'s registry
   pointed at that port — the same four-step shape as OpenCode.
5. `bridge/routers/components.py`: register the new component for `/api/status`, same
   `depends_on`/health pattern as OpenCode.
6. Nail the auto-update question shut if one exists (⚠️ UNVERIFIED whether `dsh` has an
   OpenCode-style in-app auto-updater; not found in this read, but check before shipping,
   same discipline as OpenCode's `autoupdate: false` + env var double-lock).

**Effort size:** comparable to the OpenCode integration — one new install script, one new
seed script (near-identical structure to `seed_opencode_config.py`), one `motdeck.yaml`
block, one `start_component.sh` arm, one Swift tab registration, one bridge router
registration. Estimate **6-7 files touched, 1 new component**, plus the fifteen-minute
compat-flag experiment against our actual runner before locking the seed script's
`compat` defaults.

---
*Method note: all citations are file:line in the clone at
`49a606bc5b5934603f22a26957a07dc799ab0291`. No process was started, stopped, or signaled;
nothing outside `docs/research/` in this repo was written; the clone lives only in the
scratchpad and was not copied into the repo or the snapshot.*
