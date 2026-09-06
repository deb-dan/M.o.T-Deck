# Isolation mode — can every agent tab stand alone on MOT Deck? (2026-08-29)

**Question (Debi):** OpenCode and Unsloth work *inside their own tab* — OpenCode's picker
lists "MOT Deck (local)" models. Hermes, Odysseus, Aider and the two Goose lanes cannot:
their own model-selection surfaces are empty or generic, even though our chat lanes drive
them via hardcoded wiring. Can each work standalone in its tab with our runner surfaced as
a selectable provider — and when a dependency is down, can the tab *say so*, with restart
rebinding the ties automatically?

**Read-only research.** No files outside docs/research/ touched; no processes signaled;
all findings from source, on-disk configs, and existing logs. Repo = the working tree at
`New Harness/MOT Deck`; the snapshot at `~/Library/Application Support/MOT Deck` mirrors it
(same layout, live `data/`).

---

## 0. Verdict table

| App | Standalone today? | Runner in its OWN picker? | First-class feasibility | Rebind-on-restart |
|---|---|---|---|---|
| **OpenCode** | ✅ yes (the target) | ✅ "MOT Deck (local)", all registry models | — (done) | ✅ every Start rewrites the provider |
| **Unsloth** | ✅ yes | n/a — serves its own models | — (done, by architecture) | n/a (no runner dependency) |
| **Odysseus** | ✅ mostly | ✅ "Local runner" endpoint is seeded + visible | **clean** (polish: rename-honouring, full model list) | ✅ seed runs on every Start |
| **Hermes** | ⚠️ works but anonymous | ⚠️ shows as bare `custom` row; canonical rows all 0 models | **possible-with-care** (named `custom_providers` entry) | ✅ config patched on every Start; Hermes reads config at use-time |
| **Goose CLI** | ⚠️ works but generic | ❌ provider = stock "openai"; onboarding/settings generic | **possible-with-care** (declarative custom provider — v1.5.40's named honest limit) | ✅ env+config re-seeded per launch |
| **Goose UI** | ⚠️ works but generic | ❌ same; but its Settings has an "Add custom provider" form | **possible-with-care** (same JSON, or its own form + our pre-set key env) | ✅ env+config re-seeded when goosed spawns |
| **Aider** | ✅ effectively | n/a — aider has no provider picker; model is an argv | **not-worth-it** beyond the pill it already has | ✅ argv/env re-derived per session |

Dependency signaling ("this tab needs X; restart rebinds") is **feasible for all of them**
and mostly a *signal-plumbing* slice, not a per-app integration slice — the supervisor
already computes everything needed (§6).

---

## 1. The target pattern — what OpenCode and Unsloth do differently

### OpenCode (the house gold standard)
- **Wiring:** `scripts/start_component.sh:885-1106`. Every Start rewrites a provider block
  with id `llama.cpp`, display name **"MOT Deck (local)"** (`start_component.sh:980-986`),
  `npm: @ai-sdk/openai-compatible`, baseURL/apiKey from `motdeck.yaml runner:`, and a
  `models` map enumerating **every chat model in our registry** (`data/models.json`,
  lines 938-971) — with the two-identifier rule (slash-free picker key vs. wire `id`;
  gguf = registry id via `--alias`, MLX = path) encoded per model, plus per-model
  `tool_call` and `limit.context`.
- **Written to BOTH** the global `data/opencode/xdg/config/opencode/opencode.json` and the
  project `data/opencode-workspace/opencode.json` (`:1008-1100`), **merge-never-overwrite**
  (only keys we own are replaced, `:1009-1010`).
- **Why isolation works:** OpenCode's *own UI reads its own config* — the picker and
  Settings → Providers render `cfg.provider` (provider.ts:1686, 2017 cited in the script),
  not a live probe. So the runner being down doesn't empty the picker; the models are facts
  written at Start.
- **Self-repair with a stated trade:** it un-disables itself from `disabled_providers`
  (`:1023-1045`, one deliberate documented exception to never-clobber) and appends itself
  to a non-empty `enabled_providers` allowlist (`:1054-1057`).
- **Seeded-not-enforced default model** (`:1059-1086`): set only when absent or when OUR
  stale id dangles; a user's choice inside OpenCode survives.
- **Verification with a verdict sentence:** after Start, GET `/provider` and print one
  `opencode provider check:` line saying whether the config reached it
  (`:1190-1215`, `install_opencode.sh:233-238`).

**The extractable pattern:** (1) write our provider into the app's *own* config surface,
under a stable id and the product name "MOT Deck (local)"; (2) enumerate registry models
with correct wire ids, don't rely on live discovery; (3) merge only owned keys; (4) seed
defaults, never enforce; (5) repair only the one state that makes the lane unrecoverable,
and say so; (6) verify through the app's own API and print a one-line verdict.

### Unsloth
Isolation works for a different, simpler reason: `depends_on: []` — it serves its OWN
models, never our runner (`motdeck.yaml:305`, "standalone — it serves its OWN models"),
in its own fenced home (`UNSLOTH_STUDIO_HOME=data/unsloth-home`, motdeck.yaml unsloth
block). Nothing to surface, nothing to rebind. It's the control case, not a pattern donor.

---

## 2. Hermes

### (1) Our wiring today
`scripts/start_component.sh:1242-1324` (hermes branch): on every Start, patch **only the
managed `model.*` keys** in `~/.hermes/config.yaml` — `default` (wire id, MLX-path rule at
`:1264-1282`), `provider: custom`, `base_url` (runner endpoint), `api_key`,
`context_length` — preserving everything else byte-conscious (`PYPATCH`, `:1284-1324`).
The bridge writes `mcp_servers` entries via `bridge/core/hermescfg.py:_hermes_write_mcp`
(`hermescfg.py:64-103`, atomic, idempotent, generation-bumped so the Swift shell reloads
the stale webview — `:37-50`). Launch: `hermes dashboard --no-open --skip-build` on :9119
with a session token (`start_component.sh:1496-1514`).

### (2) What Hermes's own model UI reads, and why it looks empty
The dashboard Models page calls `GET /api/model/options?include_unconfigured=1`
(`vendor/hermes/web/src/lib/api.ts:517-536`), served by
`hermes_cli/web_server.py:6369-6406` → `hermes_cli/inventory.py`:
- `load_picker_context()` (`inventory.py:80-108`) reads `model.*`, `providers:` (keyed
  v12+ schema) and `custom_providers:` (legacy list) from config.yaml.
- `include_unconfigured=1` **appends every CANONICAL_PROVIDERS row that has no
  credentials** (`inventory.py:139-141, 263-264`) — those are the "providers all 0 models"
  Debi sees. They would populate only if API keys for those clouds were added. They are
  noise for a local-first box, not breakage.
- Our runner *does* appear — but as the anonymous **`custom`** slug row
  (`model_switch.py:185-191`, `_bare_custom_provider_def`), whose model list comes from a
  **live probe of the current custom endpoint on picker open**
  (`inventory.py:311-312`, `probe_current_custom_provider=not refresh`). Runner down ⇒ the
  probe fails ⇒ the one row that is ours is empty too. Nothing on the page says
  "MOT Deck".

### (3) First-class path
Hermes already has the mechanism: a **named custom provider**. Entries in
`custom_providers:` get slug `custom:<name>` (`model_switch.py:1233-1241`), render as
their own picker row, and Hermes itself persists discovered models back into
`custom_providers[].models` (`_save_custom_provider`, `model_switch.py:132-179`) — so the
model list survives the runner being down, exactly like OpenCode's config-resident models.
The slice: extend the Start-time patcher to upsert ONE entry named **"MOT Deck (local)"**
(name, base_url, api_key, and a pre-seeded `models` map from our registry with per-model
`context_length`), and set `model.provider` to reference it rather than bare `custom`.
Same writer discipline as today: managed keys only, atomic write, cfg-gen bump (the shell
then auto-reloads the webview — the reload seam already exists, `hermescfg.py:17-36`).

**Risks / care:**
- **Double-row:** bare `model.provider: custom` + a named entry with the same base_url =
  the runner listed twice; the aggregator dedup (`inventory.py:218-261`) does NOT cover
  this case (both rows are user-defined). The slice must migrate the main slot to the
  named provider in the same write.
- **User-edit clobber:** if the user edits/renames the entry in Hermes's Config page, our
  upsert must match on base_url or a stable `provider_key`
  (dedup keys at `config.py:1551-1569`), never blind-replace — the odyvision rename rule
  (§3 below) is the house precedent.
- **YAML round-trip:** the mcp writer already accepts one-time comment loss
  (`hermescfg.py:70-72`); the model patcher deliberately avoids YAML libs — the
  custom_providers upsert needs the same care (it's a nested list; a text edit is harder;
  budget for it).
- **Session invalidation:** switching the main slot invalidates nothing structurally in
  Hermes (config read at session creation), but the frozen-page problem is real and
  already solved by hermes_config_gen.

### (4) Runner down today
Hermes launches fine without the runner only if `runner.model` is set in motdeck.yaml —
otherwise Start *refuses* (`start_component.sh:1255-1263`, "Start the Runner first").
Mid-session, a turn against a dead base_url surfaces as a provider error in Hermes's own
chat; its dashboard stays healthy on :9119, so the tab looks alive while every turn fails.
No surface says "the runner is the missing piece". Config is read at use-time (new
sessions), so a runner restart on the same endpoint needs **no Hermes restart**; a changed
endpoint/model needs only the Start-time re-patch (which MOT Deck always does).

**Verdict: possible-with-care.** The mechanism exists upstream; the work is a careful
writer + migration + the double-row guard.

---

## 3. Odysseus

### (1) Our wiring today
- `scripts/start_component.sh:469-482`: every Start runs
  `scripts/seed_odysseus_jan.py` (venv active, cwd=vendor/odysseus) with
  `JAN_BASE_URL`/`JAN_API_KEY` from `runner:`.
- `seed_odysseus_jan.py`: upserts ModelEndpoint id `local-jan`, name **"Local runner"**,
  base_url/api_key, `endpoint_kind=local`, `model_refresh_mode=auto`,
  `supports_tools=True`, and pre-seeds `cached_models`/`pinned_models` with the ONE active
  wire model (`:99-121`); sets `default_endpoint_id`/`default_model` in global settings
  (`:123-127`).
- v1.5.33 added the **describer endpoint** — the house precedent for first-class
  registration: `bridge/routers/odyvision.py` registers `/odyvision/v1` as a real, named,
  visible ModelEndpoint ("MOT Deck image describer — …", `odyvision.py:103-123`), matched
  by base_url never by name (rename-honouring, `:154-164`), only OUR stale rows deleted
  (`:167-191`), synchronous ensure at turn time (`ody.py:447-497`).

### (2) Its own model UI — why it reads "generic"
Odysseus's picker is fed by its endpoint rows. Ours IS there ("Local runner"), so this tab
is closest to done. What makes it feel generic/empty:
- The seeded `cached_models` list holds **one** model (the active one at seed time), not
  the registry — with the runner down, `model_refresh_mode=auto` discovery fails and the
  picker falls back to that single cached id (`vendor/odysseus/routes/model_routes.py`,
  `_cached_model_ids` :581), or to nothing on a fresh DB seeded while the runner was down
  (`seed:133-134` prints exactly this case).
- The display name says "Local runner", not "MOT Deck (local)" — brand-invisible.

**If the user adds our runner via its own "Add model endpoint" form:** no conflict.
Odysseus **dedupes by base_url on create** (`routes/model_routes.py:1989-2110`, the
"Dedupe: if an endpoint with the same base_url already exists…" block ~`:2036-2110`) and
updates/reactivates the existing row instead of inserting a duplicate; genuinely new rows
get a random 8-char uuid id (`:2146`), so even a near-miss URL only yields a second row,
never a PK collision with our `local-jan` (seed matches by id, `seed:99-107`).

### (3) First-class path + risks
Mostly polish, per the odyvision precedent:
- Rename the row to "MOT Deck (local)" **only while it still wears a default name**
  (adopt `ODY_VLSHIM_EP_NAMES_ALL`-style migration, `odyvision.py:115-119`). ⚠️ Today's
  seed **violates never-clobber**: `:109-112` resets `ep.name`, `api_key`,
  `is_enabled=True` unconditionally on every Start — a user's rename or deliberate
  disable is silently undone. Fix in the same slice.
- Seed `cached_models`/`pinned_models` with the **full registry chat-model list** (wire
  ids), so the picker is populated even when the runner is down — OpenCode's
  config-resident-models property.
- Session invalidation: Odysseus sessions pin a model id; switching the loaded model
  leaves old sessions pointing at a now-404 wire id — same class as ledger **S1** (stale
  session history), worth one honest sentence in the tab rather than a silent 400.

### (4) Runner down today
Odysseus starts and serves fine (it refuses nothing at Start); chats against the dead
endpoint fail per-turn with its own error toast; auto refresh quietly returns the cache.
Its `depends_on: [runner, searxng]` (`motdeck.yaml:133`) is already the machine-readable
fact the signaling slice needs.

**Verdict: clean.** The registration is done and proven (v1.5.33 closed the pattern);
remaining work is naming, never-clobber repair, and full-list seeding.

---

## 4. Aider (PTY lane)

### (1) Our wiring today
- `bridge/routers/aider.py:59-115`: per-session preconditions — installed, workspace, and
  **the live model probed from the runner** (`_live_model_id`); wire id via
  `wire_model_id`. Runner down/no model ⇒ WebSocket closed `4412` with the reason
  (`:187, :203`; `pty_aider.py:75`).
- `bridge/pty_aider.py:173-202`: launch line `--model openai/<wire>` + lockdown flags;
  env `OPENAI_API_BASE=<runner endpoint>`, `OPENAI_API_KEY`.
- Tab chrome already signals: `bridge/panel/aider.html:227-238` renders a red
  "no model loaded" pill and disables Start when `/api/aider/status.model_ready` is false.

### (2) Its own model surface
Aider has **no provider/model picker to populate** — model choice is the launch argv plus
the in-session `/model` command, which resolves against litellm's public catalog (generic
by construction; our local ids only work in the `openai/<wire>` form the argv already
uses). "Empty/generic" here is aider being aider, not a missing integration.

### (3) First-class path
The only meaningful upgrades are marginal: seed a `.aider.model.settings.yml` in the
workspace with per-model context/edit-format metadata (so `--no-show-model-warnings`
could someday be relaxed), or print a one-line hint of valid `/model openai/<id>` values
at session start. Neither surfaces a picker because none exists.

### (4) Runner down today
- At session start: honest close 4412, message through the terminal (`aider.html:310`).
- Mid-session: aider/litellm print connection errors in the terminal and the session
  survives; the next prompt retries. The env is re-derived on every new session, so a
  runner restart rebinds automatically — even a port change, since `_session_prep` reads
  `cfg()` fresh (`routers/aider.py:73`).

**Verdict: not-worth-it** (beyond the mid-session banner in §6) — the tab already IS
aider standalone, and the pill already names the dependency at start time.

---

## 5. Goose CLI + Goose UI

### (1) Our wiring today
- **CLI lane** (`bridge/pty_goose.py`): env per launch — `GOOSE_PROVIDER=openai`,
  `GOOSE_MODEL=<wire>`, `OPENAI_HOST` (origin, `/v1` stripped — `:229-247`),
  `OPENAI_BASE_PATH=v1/chat/completions`, real `OPENAI_API_KEY` (`:261-307`) — plus
  config keys re-seeded **on every launch** (`routers/goose.py:108-110`,
  "the runner's port or endpoint can change between sessions") into the fenced
  `data/goose/home/.config/goose/config.yaml` (`pty_goose.py:97, 146-147`), via a
  text-edit-never-YAML-round-trip upsert (`:311-319`).
- **UI lane** (`bridge/gooseui.py`): same wiring into the goosed WE supervise —
  `serve_env` `:400-453` (`GOOSE_PROVIDER=openai`, `GOOSE_MODEL`, `OPENAI_*`), config
  pairs seeded at spawn (`:486-533`), separate home (`data/goose/ui-home`). Notably it
  already pre-sets **`MOT_DECK_RUNNER_API_KEY`** (`CUSTOM_PROVIDER_KEY_ENV`, `:447-460`)
  precisely so a custom provider created in goose's own UI finds its key with no prompt.

### (2) Its own model UI — why generic
Goose's provider surfaces (CLI `/configure`+`/model`; Desktop Settings → Models) list
known providers from a built-in catalog; ours rides the stock **"openai"** provider, so
the settings page shows OpenAI branding and OpenAI's model list — `GOOSE_MODEL`'s value
works but isn't offered. The onboarding screen is suppressed only because
`GOOSE_PROVIDER` is seeded (`gooseui.py:489-492`).

### (3) First-class path — and the recorded blocker
The v1.5.40 commit records the honest limit verbatim: *"custom openai_compatible provider
unbuilt (stock openai seeding proven; **three on-disk custom layouts all 'Unknown
provider'**)"* — i.e. the declarative shape was guessed three times and rejected at the
pin. But `docs/research/2026-08-29-goose-desktop-ui.md:145-154` has since verified the
mechanism at source: the Desktop's own `CustomProviderForm.tsx` (engine
`openai_compatible`, display_name, api_url, headers) **saves a declarative provider as
`custom_providers/*.json` in the config dir** — same mechanism verified 08-28 at
providers.md:481-508. So the first-class path is:
1. Reproduce the JSON goose's own form writes (create one through the UI in a scratch
   home, read the file — that kills the "Unknown provider" guessing) — at pin v1.48.0.
2. Seed that file into BOTH homes (`data/goose/home`, `data/goose/ui-home`) at launch,
   display name "MOT Deck (local)", key via `MOT_DECK_RUNNER_API_KEY` (already in env),
   and flip `GOOSE_PROVIDER` to the custom provider's id.
3. Alternatively zero-code: the user can use goose's own Add-custom-provider form today —
   the key env is pre-arranged; only the models list must be typed.

**Risks / care:**
- The declarative-provider schema is upstream-fluid (that's what burned the three
  attempts); pin-locked recon first, contract test after.
- Never-clobber: `custom_providers/*.json` is also where the USER's own creations live —
  seed one file we own by name, never rewrite the directory.
- Session invalidation: goose sessions record provider/model; switching the seeded
  provider mid-history leaves old sessions on the old name — new-sessions-only, same as
  Hermes.
- Model list staleness: like OpenCode, enumerate registry models into the provider file
  at spawn so the picker holds facts, not probes.

### (4) Runner down today
- At session/spawn: `routers/goose.py:94-100` refuses with "no model is loaded — load one
  in MOT Deck…" (WS close 4412); tab pill "no model loaded" + Start disabled
  (`goose.html:361-371`). Goose UI's goosed spawns regardless of the runner (it's the
  page's own Start), but turns fail inside the embed with goose's own provider error.
- Mid-session: the child gets connection errors; the PTY stays up. New launch rebinds
  (env + config re-derived every time).

**Verdict (both lanes): possible-with-care.** All plumbing exists; the one unknown is the
exact declarative JSON, which is a read-a-file-goose-wrote recon, not a design problem.

---

## 6. Dependency signaling + rebind-on-restart — the design sketch

### What exists (the seams)
1. **The supervisor already knows.** `GET /api/status`
   (`bridge/routers/components.py:23-95`) computes per-component
   `running/degraded/health/misses` (debounced via `core/health._health_track`) and for
   the runner the three-state truth: `port_up` vs `loaded` vs `degraded` (`:60-90`).
   `motdeck.yaml depends_on` is the dependency graph (hermes→runner,
   odysseus→runner+searxng; opencode/unsloth deliberately `[]`).
2. **A push channel exists**: `core/events.publish` SSE (used by nav_gen and
   hermes_config_gen riders, `hermescfg.py:46-49`).
3. **The Swift shell already polls /api/status** (main.swift:1472, 2089-2102, 2413-2414)
   and has both an overlay precedent (DropOverlay above a webview, main.swift:2196-2209)
   and an honest-HTML mechanism (`showUnreachable`).
4. **Lane tabs already self-signal at start**: aider.html/goose.html render the
   `model_ready` pill from their `/api/*/status` and disable Start — but the status poll
   is not sustained through a live session, so a mid-session runner death is only visible
   as raw errors inside the terminal.
5. **Rebind already happens at every (re)start**, per app: Hermes config re-patch
   (start_component.sh:1246), Odysseus re-seed (`:481`), OpenCode provider rewrite
   (`:920`), goose env+config per spawn (`routers/goose.py:108-110`), aider argv/env per
   session, gooseui seed at goosed spawn. **"Restart rebinds" is therefore already true
   everywhere** — the missing halves are (a) telling the user *which* restart, in the
   tab, and (b) rebinding *running* components when the RUNNER (not the component)
   restarts.

### The sketch
- **Bridge:** add a derived `needs` list per component in `/api/status` — unmet
  dependencies computed from `depends_on` + live state (e.g.
  `needs: [{"component":"runner","state":"down","fix":"start_runner"}]`), plus the same
  for the two goose lanes and aider (their dependency is `runner.loaded`, already probed
  in their status endpoints). Publish a `deps` SSE event when a `needs` set changes —
  same rider pattern as `config`/`nav`.
- **Tab chrome (vendor webviews — hermes, odysseus, opencode, gooseui):** the Swift shell
  overlays a slim banner on the affected tab only: *"This tab needs the Runner — it's
  down. Restart the Runner; this tab rebinds automatically."* One overlay view, driven by
  the poll it already runs; no injection into vendor pages (Odysseus X-Frame policy noted
  at the pin bump, motdeck.yaml:129 — untouched).
- **Lane pages (aider/goose):** keep their status poll alive during a session at a slow
  cadence; when `model_ready` flips false mid-session, show the existing red pill plus
  one sentence above the terminal — the terminal already carries the raw error.
- **Rebind on RUNNER restart, components left running:** a post-start hook on the runner
  in the bridge re-runs the *API-level* fan-outs that don't need a component restart:
  - Hermes: re-run the config patch (config is read at use-time — new chats pick it up;
    the cfg-gen bump reloads the webview). No process restart.
  - Odysseus: the odyvision `ensure()` already re-runs synchronously at turn time
    (`ody.py:447`); extend the same ensure-style upsert to the `local-jan` row via
    Odysseus's admin API (the v1.5.33 route, not the DB script — the DB script needs the
    venv and offline DB access).
  - OpenCode: rewrite the config; whether the running server hot-reloads it is
    UNVERIFIED at the pin — if not, the banner says "Restart OpenCode to pick up the new
    model list" (honest, cheap).
  - Goose/Aider: nothing to do — next session rebinds by construction; the banner's job
    is only to say so.

---

## 7. Risk register (cross-app)

- **Never-clobber:** the one live violation found is `seed_odysseus_jan.py:109-117`
  (name/api_key/is_enabled reset every Start). OpenCode's `disabled_providers` repair is
  a *documented deliberate* exception (`start_component.sh:1033-1036`). Every new seeding
  must follow odyvision's rules: match by base_url/stable id, migrate only default names,
  delete only our own stale rows.
- **Double-seeding / double rows:** Hermes bare-`custom` + named entry (must migrate, not
  add); Odysseus user-added duplicate is defused upstream (base_url dedupe); goose: own
  one `custom_providers/<ours>.json` file by name.
- **Session invalidation on model switch:** ledger **S1** is the incident of record;
  every picker-facing model list we seed makes it easier to select a model the runner
  hasn't loaded — the honest shape is per-model "loaded/not loaded" hints where the app
  supports them, or a one-sentence tab note, never silent 400s.
- **Upstream schema drift:** goose declarative providers (already burned once), Hermes
  `custom_providers` vs keyed `providers:` (v12 migration in flight upstream,
  `config.py:1534-1543`) — contract tests per seeded shape, as always.
- **Snapshot rsync:** any new state under `vendor/odysseus/data/` stays inside the
  existing exclude rule (motdeck.yaml:124-128) — seeding via API keeps us out of that
  minefield entirely.

## 8. Slice ladder (proposal)

1. **S-ISO-1 — Signal first (all tabs, zero vendor writes):** `needs` in /api/status +
   SSE `deps` event + shell banner overlay + sustained lane-page polls. Smallest slice,
   biggest confusion-killer; makes every later slice observable.
2. **S-ISO-2 — Odysseus polish (clean):** rename-honouring seed, "MOT Deck (local)"
   default-name migration, full-registry cached/pinned models, never-clobber fix.
   API-level ensure so a runner restart rebinds without an Odysseus restart.
3. **S-ISO-3 — Hermes named provider (care):** `custom_providers` upsert
   "MOT Deck (local)" + main-slot migration + double-row guard + contract pins on the
   picker payload (`/api/model/options` row present with our models, runner down or up).
4. **S-ISO-4 — Goose declarative provider (care):** pin-locked recon of the JSON goose's
   own CustomProviderForm writes (closes v1.5.40's honest limit), seed both homes, flip
   `GOOSE_PROVIDER`, registry-enumerated model list, contract test the file shape.
5. **S-ISO-5 — Runner-restart fan-out:** the post-start hook re-running the API-level
   rebinds (Hermes patch, Odysseus ensure, OpenCode rewrite + verified-or-honest reload
   note).
6. **(skip)** Aider first-class provider — no picker exists to populate; S-ISO-1 already
   gives it the mid-session banner.

---
*Method note: all citations are file:line in this repo (vendor pins as checked out today,
Hermes v2026.8.13, Odysseus dev@c9dd68d, goose v1.48.0, OpenCode 1.18.23). No process was
started, stopped or signaled; no config, DB or vendor file was written.*
