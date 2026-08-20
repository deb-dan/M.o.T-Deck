# Unsloth Studio — code recon (2026-08-20)

**Method:** `git clone --depth 1 https://github.com/unslothai/unsloth` → `/tmp/uns/unsloth`, HEAD
`9574476ba6ceab71f870b02b065ac84cb637a1bd` ("Fix Qwen3.8 presence penalty defaults (#9372)", Thu Aug 20 2026).
All `file:line` below are relative to that clone at that commit. Anonymous GitHub REST API was blocked
from the sandbox; `git clone` worked, so **everything here is read from source, nothing from READMEs or
docs sites** unless marked. ⚠️ UNVERIFIED = could not confirm in code.

**Repo shape:** it is ONE monorepo, not a core repo plus a studio repo. `unsloth/` = the training library,
`unsloth_cli/` = the `unsloth` CLI (5,022-line `commands/start.py`), `studio/backend` (37M, FastAPI),
`studio/frontend` (52M, React), `studio/src-tauri` (2.9M, Tauri desktop shell).

**License — dual, and the split matters.** Root `LICENSE` = Apache-2.0 (the training library); root
`COPYING` = **AGPL-3.0**, and `studio/LICENSE.AGPL-3.0` scopes it. Studio source files carry the header
`# SPDX-License-Identifier: AGPL-3.0-only … See /studio/LICENSE.AGPL-3.0`
(`studio/backend/utils/coding_agents.py:1-2`). So **Studio is AGPL-3.0-only** — the same posture as
VoiceStudio/SearXNG, fine at arm's length under our never-edit-vendor doctrine.

---

## 1. `unsloth start` agent wiring — the headline finding

**The pattern is HOME-DIRECTORY RELOCATION, not config patching.** That single sentence is the whole
adoptable idea, and it is strictly better than what we do today (we patch `~/.hermes/config.yaml` in
`start_component.sh` and must re-patch on every model switch).

### 1a. Detection = plain PATH probing, nothing clever

```
CODING_AGENTS: tuple[str, ...] = ("claude", "codex", "openclaw", "opencode", "hermes", "pi")
```
`studio/backend/utils/coding_agents.py:19`. Detection is `shutil.which(agent) is not None`
(`coding_agents.py:22-30`), wrapped so an `OSError` during a PATH probe reads as "not installed" rather
than 500-ing the settings endpoint. `detect_installed_coding_agents()` returns the subset **in
CODING_AGENTS order, not discovery order**, so the first hit is the UI's preferred default
(`coding_agents.py:33-39`). Exposed as `GET`-style handler `get_coding_agents` →
`CodingAgentsResponse(detected=...)` at `studio/backend/routes/settings.py:1202-1203`. That is all —
no config sniffing, no version probing, no registry. Debi's Hermes was detected because `hermes` is on
her PATH.

### 1b. Endpoint injection — how "never touches your agent's config files" is literally true

The UI copy Debi saw is `studio/frontend/src/i18n/locales/en.ts:958`: *"…runs an OpenAI-compatible
server and never touches your agent's config files."* It is honest, and the mechanism is
`_session_config()` (`unsloth_cli/commands/start.py:3942-3973`), a contextmanager yielding **a private
directory that is never the user's own**:

- `--launch` (default), no `--persist` → an **ephemeral temp dir**, wiped when the agent exits
  (`start.py:3958-3966`), rooted under `_agents_config_root() = _studio_auth_root()/"agents"`
  (`start.py:3772-3773`), temp subtree `agents/.tmp` at mode `0o700` (`start.py:3780-3784`).
- `--no-launch` or `--persist` → a **stable Unsloth-owned dir** `agents/<agent>` (mode `0o700`,
  `start.py:3971-3973`), deliberately never wiped because a previously *printed* recipe may still be
  running against it (comment at `start.py:3967-3971`).

Then per agent it writes a **generated config into that private dir** and points the agent's HOME env var
at it. For Hermes (`start.py:4881-4886`):

```python
with _session_config("hermes", launch, persist = persist) as home:
    # HERMES_HOME relocates hermes' whole home dir (config.yaml, sessions, state)
    # like CODEX_HOME, so the user's ~/.hermes is left untouched for the session.
    write_hermes_config(base, entry, home / "config.yaml")
    env = {_HERMES_ENV_KEY: key, "HERMES_HOME": str(home)}
    _run(base, entry, env, command, launch = launch, install_hint = install_hint)
```

`_HERMES_ENV_KEY = "UNSLOTH_API_KEY"` (`start.py:51`). The env dict is applied to the child process only
(`_run`, `start.py:3709-3760`); with `--no-launch` it is *printed* as an env+command recipe instead of
executed (`start.py:3735-3746`). Same shape for codex (`CODEX_HOME`), openclaw, opencode
(`OPENCODE_CONFIG` + `OPENCODE_CONFIG_CONTENT` inline JSON, `start.py:4820-4826`) and pi
(`~/.pi/agent/models.json`, HOME-relocated — `start.py:4285-4289`).

### 1c. `write_hermes_config` — they knew our Hermes gotchas, in code

`start.py:4210-4270`. Worth reading in full before we build anything Hermes-adjacent; four facts they
encoded that our own memory only half-records:

1. **A bare `provider: custom` ignores the api key** — Hermes only reads the key for a *named* custom
   provider, so they register `providers.unsloth` and set `model.provider = "custom:unsloth"`
   (`start.py:4235-4239`, `:4262-4266`), with `key_env: UNSLOTH_API_KEY` rather than an inline secret.
2. **Hermes auto-detects context from `GET /v1/models`, and OpenAI's schema has no context field**, so it
   can fall back to a 256k default that overflows a small local model. They pin the real window into
   top-level `model.context_length` (documented as the highest-priority override) and set
   `compression.threshold = 0.9` because Hermes defaults to compacting at 50% (`start.py:4240-4249`).
3. **The 64,000-token floor is confirmed at their pin too** — `_HERMES_MIN_CONTEXT = 65536`
   (`start.py:79`). Below it Hermes *refuses to initialize*, so for a small model they **claim the floor**
   and shrink the threshold to `round(0.9 * window / 65536, 4)` so compaction still fires at 90% of the
   REAL window, plus an `auxiliary.compression.context_length` override so the same floor check does not
   reject the compression model mid-session (`start.py:4250-4261`). This is a genuinely clever trick we
   do not have.
4. **Parse failures fail SAFE**: unparseable YAML, or valid YAML that is not a mapping, produces a warning
   and an early `return` — they never clobber a user-managed file (`start.py:4214-4232`). They also
   only write when the serialized text actually differs (`start.py:4267-4270`) — the same
   "skip-when-unchanged" property we adopted for `_hermes_write_mcp`.

They pin the Hermes installer by commit: `_HERMES_INSTALL_COMMIT = "f1af945f6c576eccb126fa955edc9be258b33020"`
with `--skip-setup` hints for posix/windows (`start.py:62-73`).

### 1d. Flags Debi saw, in code

`--serve/--no-serve` auto-starts a Studio server for `--model` and keeps it after the agent exits
(`start.py:205-211`); `--launch/--no-launch` (`:304-308`) prints env+command instead of running — this is
their remote-shell/WSL story; `--persist/--no-persist` (`:322-337`, help text explicitly names
"codex/openclaw/hermes/pi have their whole home relocated"); `--as-subagent` keeps the agent's own model
and adds Unsloth as a *local subagent* (`:338-343`) — Hermes explicitly rejects it,
`_reject_as_subagent("hermes", ctx.args)` at `start.py:4857`; `--yolo` is one normalized switch accepting
all three vendor spellings and routed per agent via `_YOLO_COMMAND_FLAGS` (`start.py:295-355`), where
hermes maps to `["--yolo"]` (`:350`). `UNSLOTH_STUDIO_URL` defaults to `http://127.0.0.1:8888`
(`start.py:1281`, `:2133`); `UNSLOTH_API_KEY` is the `--api-key` envvar (`start.py:295-303`) and is
**minted automatically per local server and cached** (`_agent_api_key`, `start.py:1427-1445`).

### 1e. What this means for us

Our harness patches `~/.hermes/config.yaml` in place and re-patches on every `start_component.sh hermes`.
Unsloth's approach would let us launch a Hermes bound to our runner **without owning the user's Hermes
config at all** — set `HERMES_HOME` to a harness-owned dir, generate `config.yaml` there. Costs: the
harness Hermes would then have its OWN sessions/state separate from a user's standalone Hermes (arguably
correct, and `--persist`-style stability is one flag away), and our path-guard plugin seeding
(`~/.hermes/plugins/`) would need to follow the relocated home. This is a real design item, not a
one-liner.

---

## 2. UI design system

**Stack** (`studio/frontend/package.json`): React 19.2.4 + TS 5.9.3 + **Vite 8** (`:74-76,120,127`);
package name is literally `unsloth-theme` (`:2`). **Tailwind v4** (`:43,89`) with **no `tailwind.config.js`**
— config lives in CSS via `@theme inline` (`src/index.css:750`). **shadcn 4.2.0** with
`components.json` style `radix-maia`, baseColor neutral, cssVariables true, and
`iconLibrary: "hugeicons"` (`studio/frontend/components.json:3-13`); 61 primitives under
`src/components/ui/`. Icons = **Hugeicons** (`package.json:32-33`), lucide present as secondary (`:65`).
State = **zustand 5** with `persist` (`:98`); router = **TanStack Router 1.169.2** pinned in `overrides`
(`:44,101-103`); desktop shell = **Tauri v2** (`:47-54`). Chat runtime is `@assistant-ui/react 0.12.28`,
markdown via `streamdown`, animation via `motion` (Framer successor).

**Tokens.** Colors are **oklch CSS custom properties** on `:root` (light, `src/index.css:183-238`) and
`.dark` (`:354-399`), re-exported to Tailwind in `@theme inline` (`:750+`, e.g.
`--color-background: var(--background)` at `:849`). One radius knob `--radius: 1.1rem` (`:215`, `:388`)
with a **px-offset** scale `--radius-sm … --radius-4xl` = `calc(var(--radius) ± Npx)` (`:850-856`).
Spacing stays Tailwind default `0.25rem` and its `@theme` re-export is **deliberately commented out**
(`:874`) so layout geometry never moves. Motion tokens `--duration-micro|fast|normal` = 100/150/200ms
(`~:600`). Theme applied **pre-paint by an external classic script** `public/theme-boot.js:11-26`
reading `localStorage["theme"]` + `localStorage["palette"]` — external rather than inline because the
backend CSP is `script-src 'self'` (`theme-boot.js:4-7`). *(Our panel already does the pre-paint trick
inline; theirs is the CSP-safe variant.)* Beyond light/dark there are **3 palettes** via
`html[data-palette]`: standard / `classic` / `minimal` (`src/index.css:444-450`, blocks `:460,:516,:534,:584`).

**Fonts.** Three loading paths: self-hosted npm variable fonts (`@import "@fontsource-variable/…"` for
figtree, space-grotesk, inter — `src/index.css:9-11`); local `@font-face` for **Hellix** 400/500/600 and
Fira Code variable (`:138-169`, OTFs in `public/Hellix font official/OTF/`); and **user-imported fonts at
runtime** registered via the `FontFace` API from `data:` URLs, max 3 fonts / ~2.2MB each / 4.4MB total to
stay inside the localStorage quota (`appearance-custom-store.ts:699-733`, `:181-191`). Default stacks
(`appearance-custom-store.ts:529-533`): sans `Inter Variable`, heading `Hellix, Space Grotesk Variable`,
mono `JetBrains Mono`. ⚠️ UNVERIFIED: no `@font-face` or CDN for JetBrains Mono was found — it looks like
a name-only reference relying on a locally installed font.

**The 15px UI font size — the detail worth stealing.** It is **not** applied as root font-size. It becomes
a ratio `--ui-font-scale = size / 16` set inline on `<html>` plus a `data-ui-font-size` attribute
(`appearance-custom-store.ts:826-843`), range `{min:12, max:20, default:15}` (`:245`), default
`--ui-font-scale: 0.9375` baked into `:root` (`src/index.css:310`). The code carries an explicit comment
that rem-based layout geometry must NOT move with the preference, and clears the stale inline root
font-size older builds set (`:843`). Every type token multiplies by it: `--text-xs…--text-4xl`
(`src/index.css:755-762`) plus a bespoke pixel-named ramp `--text-ui-8 … --text-ui-50` with half-steps
like `--text-ui-13p5` (`:764-786`). Components use `text-ui-13` rather than `text-sm` throughout. Icons
derive from the same scale with a `min()` damping so they grow *slower* than text (`:320-335`).

**Contrast slider**: 0–100, 50 neutral, step 5 (`appearance-custom-controls.tsx:864-883`); maps
`|value-50|` onto a 0–40% mix and remixes exactly **three** tokens — `--border`, `--sidebar-border`,
`--muted-foreground` — via `color-mix(in oklab, …)` (`appearance-custom-store.ts:853-867`,
`src/index.css:613-621`). Also worth stealing: custom accent colors are auto-corrected to clear a **2.5:1
floor** against both plain and 20%-wash surfaces by binary-walking 255 mix steps
(`appearance-custom-store.ts:600-688`).

**Sidebar/topbar customization — the data model.** Two independent features in one persisted object.
`SidebarNavItemPref = { id, pinned }` where **array order IS render order** and `pinned` decides
top-level vs the "More" flyout (`appearance-custom-store.ts:106-110`, `:89`). Defaults:
`SIDEBAR_NAV_ITEM_IDS = ["hub","projects","images","video","audio","train","recipes","export","api"]`
(`:90-102`) with `SIDEBAR_NAV_DEFAULT_PINNED` leaving audio/recipes/export/api unpinned (`:113-124`).
Profile menu is `SidebarMenuItemPref = { id, visible }` over 8 ids, with Settings/Help/Log out/Shutdown
**permanently pinned and not listed** (`:54-87`). Reordering uses **`motion/react`'s `Reorder.Group`/
`Reorder.Item` with `useDragControls` and a dedicated drag handle** (`dragListener={false}`) — no dnd-kit,
no react-beautiful-dnd (`sidebar-nav-customizer.tsx:18,60-87`). **The "More" rule:** unpinned rows collapse
into a flyout **only if there are 2+** — a single unpinned row is dropped entirely rather than getting a
menu of one, enforced identically in the sidebar and mirrored in the settings preview
(`src/components/app-sidebar.tsx:1822-1828`, `sidebar-nav-customizer.tsx:117,138`). One `navRows` record
is the single source of truth so pinned rows and flyout entries cannot drift (`app-sidebar.tsx:1664-1665`).

**Persistence — two tiers.** (1) localStorage via zustand `persist`, key
**`unsloth_appearance_customization`**, `version: 7`, with a wrapper that swallows quota/private-browsing
throws, sanitized on *every* rehydrate not just version bumps (`appearance-custom-store.ts:501-503,15-37,516-522`).
(2) Backend sync `GET/PUT /api/settings/personalization` (`src/features/settings/api/personalization.ts:36,50`),
debounced push + remote hydrate (`use-personalization-sync.ts:95,239,300,375,410`), stored server-side as a
**DB row** under app-setting key `"personalization"` (`studio/backend/routes/settings.py:2374-2403`,
`utils/personalization_settings.py:6,11-19`). The backend duplicates the frontend defaults and warns they
MUST match, because a missing id 422s the whole PUT (`routes/settings.py:2200-2214`); incoming lists are
capped at `4 * len(defaults)` (`:2216,:2226`). Sidebar *width* (`sidebar_width`, default 280 / 260–480)
and *pin* state (`sidebar_pinned`, cross-tab synced via the `storage` event) are **separate localStorage
keys outside the personalization payload** (`use-sidebar-width.ts:7-14`, `use-sidebar-pin.ts:6,27-33`).
Best idea in the file: `migrateShippedSidebarNavDefault` compares a stored layout against an **archive of
every previously shipped default layout** and only adopts a new default if the user's layout exactly
matches one they never touched (`appearance-custom-store.ts:406-426`, `:130-179`).

---

## 3. Chat performance — verdict

**It is mostly engine + config, and there IS something to adopt.** On a Mac with a GGUF model, chat is
served by a bundled **`llama-server` subprocess proxied over HTTP** (`studio/backend/routes/inference.py:14664`,
backend class in `core/inference/llama_cpp.py`, binary resolved by `utils/llama_cpp_update.py:104`) — the
same engine class we run. Their launch argv (`core/inference/llama_cpp.py:17497-17708`) turns on things
our runner does not: **`--flash-attn on` forced** with a capability gate that fails open (`:17506-17517`);
**`--parallel <n>`** continuous-batching slots (`:17501-17505`); **`--slot-save-path`** for a persistent
slot KV cache in a 0700 dir (`:17644-17658`); `--no-context-shift` (`:17520-17521`); `--jinja` (`:17706`);
`-ngl -1 --fit off` when the model fits, else `--fit on` (`:17629-17636`); `--metrics` when supported.
**Speculative decoding is first-class and defaults to `"auto"`** with drafter sidecar selection
(`llama_cpp.py:5481-5484`, `:4173`, `utils/models/drafters/preference.py:21-48`) — ⚠️ UNVERIFIED whether a
4B Q4 actually gets a drafter, so I would not attribute Debi's 89 tok/s to it. `--threads` is deliberately
NOT emitted (`:17693-17703`). Model stays resident; idle auto-unload is **off by default**
(`llama_keepwarm.py:4-8`), and a background thread warms the ML stack during FastAPI lifespan so torch
import overlaps serving (`utils/torch_warmup.py:4-13`). **Verdict:** the 64ms first token is a hot
slot-KV cache + resident model + a snappy streaming UI; the 89 tok/s on a 4B Q4 is the same order as our
own chat lane (our 2026-08-06 measurement was 90.8 tok/s on a *35B*, so 89 on a 4B is unremarkable — this
matches Fable's prior). **The adoptable delta is a handful of launch flags — `--flash-attn`,
`--slot-save-path`, `--parallel` — not an engine swap.** Two of those (`--flash-attn`, and `--ctx-size`/
`--n-gpu-layers`) our Load group already exposes as of v2; `--slot-save-path` is the one genuinely new
idea.

**One caution:** their llama.cpp is downloaded from **`unslothai/llama.cpp` (a fork) at tag `latest`** —
`DEFAULT_LLAMA_TAG = os.environ.get("UNSLOTH_LLAMA_TAG", "latest")`
(`studio/install_llama_prebuilt.py:250,254`). The only literal pin is a macOS-pre-26 fallback
`_PINNED_MACOS_FALLBACK_TAG = "b9415"` (`:322-323`, used at `:1202-1207,1233-1235`). **Their builds are
not reproducible across time.** Ours (b10427) are. Do not adopt their acquisition path.

---

## 4. Mac / Apple-Silicon training — verdict

**Real, but MLX-only and feature-limited — and the contradiction Debi noticed is because the *library* and
the *Studio* answer differently.** The core `unsloth/` torch library is CUDA/ROCm/XPU-only and says so:
`raise NotImplementedError("Unsloth currently only works on NVIDIA, AMD and Intel GPUs.")`
(`unsloth/device_type.py:87`); there is no `torch.backends.mps` training path, and MLX is short-circuited
*before* torch is imported (`device_type.py:60-65`). Studio, however, dispatches to a **separate MLX
trainer**: `if cls is UnslothTrainer and should_use_mlx_training_backend(): return create_mlx_trainer_adapter(...)`
(`studio/backend/core/training/trainer.py:284-285`), gated by `is_apple_silicon_training_platform()`
(`core/training/training.py:154-168`), with a self-contained loop `_run_mlx_training`
(`core/training/worker.py:2585`) importing `unsloth_zoo.mlx.loader.FastMLXModel` and `unsloth_zoo.mlx.trainer`
(`worker.py:2611-2620`). **⚠️ Those modules live in the external `unsloth-zoo` package, not this repo —
the actual training internals are UNVERIFIED here.** Supported = **LoRA/QLoRA only** (`worker.py:2670-2671`);
explicitly refused on Mac with `NotImplementedError`/HTTP 4xx: **LoftQ, DoRA, embedding-model training, and
Continued Pretraining** (`worker.py:2643-2655`, `routes/training.py:868-888`). The two `scripts/install_*_mlx.sh`
are **inference-only** (they install `mlx-vlm` and print `mlx_vlm.chat` usage), not training. Net: if
Debi wants Mac fine-tuning, LoRA/QLoRA is genuinely on the table — which also means our doctrine-pure
alternative (a Models → Tune tab over the already-installed `mlx_lm.lora`/`mlx_lm.fuse`) targets exactly
the same capability envelope without the AGPL dependency.

---

## 5. Component fit (VoiceStudio pattern)

| Dimension | Finding | Evidence |
|---|---|---|
| Port / bind | **8888**, bound **127.0.0.1** by default; auto-increments if busy | `studio/backend/run.py:2205-2206`, `:2229` |
| Health | **`GET /api/health`**; unauth callers get a reduced payload, `version`/`device_type` need a bearer | `studio/backend/main.py:1644-1650` |
| Server | FastAPI single app | `studio/backend/main.py:795` |
| OpenAI surface | **same app, same port**, prefix **`/v1`** (`/v1/chat/completions`, `/v1/models`, `/v1/completions`, plus Anthropic-shaped `/v1/messages`, `/v1/responses`) | `main.py:1369`, `routes/inference.py:13932,17917,18063,148` |
| Auth | **API key REQUIRED**, `Authorization: Bearer` against a SQLite `api_keys` table; **no loopback bypass found** | `routes/inference.py:13935`, `auth/authentication.py:28,156`, `auth/storage.py:321` |
| Install | `install.sh` (5,400+ lines) driving **uv/pip** against hard-pinned `studio/backend/requirements/*.txt` (e.g. `transformers==5.5.0`, `trl==0.23.1`, `peft==0.18.1`, diffusers pinned to a git commit), **plus prebuilt native downloads** (llama.cpp, whisper.cpp, sd.cpp, **and Node itself**), **plus an npm frontend build** in the CLI path. The Tauri `.dmg` bundles its frontend and skips Node/npm entirely. | `requirements/extras-no-deps.txt:8-27`, `diffusers-pin.txt:17`, `install.sh:2213,5407`, `studio/node_prebuilt_pins.json` |
| License | **AGPL-3.0-only** for Studio; Apache-2.0 for the training library | `COPYING`, `studio/LICENSE.AGPL-3.0`, `coding_agents.py:1-2` |
| `--disable-tools` gotcha | **CONFIRMED and worse than reported.** CLI policy is a **process global that OUTRANKS the request**: "A policy of `False` (--disable-tools) vetoes even an explicit `enable_tools: true` ask." A client sending its own `tools:` array gets them server-side-vetoed, `/v1/messages` included. Note the asymmetry: `unsloth studio run` installs a tools-ON default, while `unsloth studio`, the desktop app and Colab leave it **unset (= off)**. | `state/tool_policy.py:11-22,38-41`, `run.py:2143-2158,2867-2876`, `routes/inference.py:2804-2812,2852-2856` |
| Engine conflict | **Yes, real.** It downloads its own `llama-server` from a *fork* at tag `latest` (`install_llama_prebuilt.py:250,254`) and ships an in-app updater that re-pulls latest on demand (`utils/llama_cpp_update.py:11-17`). That is a second, floating, unpinnable llama.cpp beside our pinned b10427 — it would not overwrite ours (separate install root), but it breaks our pin+bump+contract-test discipline for anything served through it. | as cited |
| RAM ledger | **Blind.** Model stays resident with idle auto-unload OFF by default (`llama_keepwarm.py:4-8`); resident weights live in *its* process, invisible to `memory.budget_gb`. Same class as the VoiceStudio/Voicebox blindness we already accepted, but larger — a training run or a resident 8B would silently blow the budget our spawn_guard enforces. | `llama_keepwarm.py:4-8` |

**Install-footprint reality check:** pinned `transformers`, `trl`, `peft`, `diffusers`, torch, plus prebuilt
llama.cpp + whisper.cpp + sd.cpp + a private Node. This is a **multi-GB venv in the VoiceStudio weight
class or heavier**, and it brings a second Node runtime we do not currently own.

---

## 6. mindsdb/mindshub

Cloned `https://github.com/mindsdb/mindshub` → **MIT** (`LICENSE`, "Copyright (c) 2019 MindsDB, Inc.").
**Zero references to it anywhere in the Unsloth repo** (`grep -rn 'mindshub|mindsdb|MindsDB'` → no hits),
so the two are unrelated; the earlier naming note stands. It self-describes as *"MindsHub Cowork … the
unified workspace where you delegate entire projects"* and is a **platform superproject** pinning
submodules `frontend`, `backend/core_api`, `backend/core_agent`, `backend/data-vault` (README.md
"Build from source"). It is an Electron desktop app + web console, `docker-compose.yml` with `api`/`web`/
`cowork-data` services, `make setup|dev|build|dist-mac`. **It is the same product class as the harness**,
but cloud-leaning and freemium (a hosted `console.mindshub.ai`, a "Pro adds all frontier models" pricing
tier, a Model Router across Claude/GPT/Gemini) — the opposite of our local-first axis. Two things are
notable: (a) it **runs Hermes as one of two swappable open agent harnesses** ("Anton (default) and Hermes,
swappable from a dropdown") — independent evidence that Hermes-as-a-pluggable-brain is a recognised
pattern, not just ours; (b) its credential story is a **scoped vault where "agents never see raw keys"**,
which is a cleaner shape than our `.env`. **Verdict: IGNORE as a dependency** (Docker-first, cloud console,
duplicates the harness itself), **recon-only for the vault idea.**

---

## Ranked verdict

### ADOPT
1. **HOME-relocation for agent wiring** (`HERMES_HOME` + a generated `config.yaml` in a harness-owned dir)
   instead of patching `~/.hermes/config.yaml`. Highest-value single idea in this recon; retires a whole
   class of "we own the user's config" problems. Needs a Fable design pass for path-guard plugin seeding
   and session-store location.
2. **The four `write_hermes_config` facts** (`start.py:4210-4270`) regardless of whether we adopt #1 — the
   named-custom-provider key rule, the 256k-fallback pin, the sub-64k floor-claim + scaled-threshold trick,
   and fail-safe-on-unparseable. Two of these are things our current fan-out gets wrong or does not do.
3. **`--slot-save-path`** (persistent slot KV cache) as a llama-server Load-group flag — the one real
   perf idea here that we do not already expose after Model Settings v2.
4. **`--ui-font-scale` as a ratio, not root font-size** — exactly the right way to build the deep-theme
   font-size control, with their own comment explaining why the naive version is wrong.

### IMITATE (pattern, not code — AGPL)
5. **Sidebar customization data model**: `{id, pinned}` array where order IS order; the "More flyout only
   if 2+ unpinned" rule; a single nav-row record so pinned and flyout entries cannot drift; the
   shipped-defaults archive so a new default only lands on untouched layouts.
6. **Two-tier persistence** (localStorage for instant paint + a server settings row for durability), with
   the backend-defaults-must-match warning as a cautionary tale, not a feature.
7. **Contrast slider remixing only 3 tokens via `color-mix`**, and the 2.5:1 auto-correction floor for
   user-chosen accents — both directly relevant to the deep-theme spec.
8. **PATH-probe agent detection** (`shutil.which`, ordered by a declared tuple, OSError → "not installed").
   Trivial, but it is the honest way to build a harness "detected agents" surface if we ever want one.

### IGNORE
9. **Studio as a harness component.** AGPL is survivable, but it brings a *floating-tag forked llama.cpp*,
   a second Node runtime, a multi-GB pinned-torch venv, mandatory bearer auth on loopback, a
   `--disable-tools` global that outranks per-request tool asks, and models resident outside our RAM
   ledger. It duplicates chat + models + serving — the three things the harness already owns. Our
   doctrine-pure `Models → Tune` slice over the already-installed `mlx_lm.lora`/`mlx_lm.fuse` reaches the
   same LoRA/QLoRA envelope with none of that.
10. **Their llama.cpp acquisition path** (fork @ `latest` + in-app updater) — actively incompatible with
    our pin+bump+contract-test discipline.
11. **mindsdb/mindshub** as a dependency.
