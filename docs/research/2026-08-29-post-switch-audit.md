# Post-switch coherence audit — the full map, 2026-08-29 (v1.5.58 live)

**READ-ONLY.** Every fact below was read off the live system on 2026-08-29 ~17:30:
GETs against the running bridge/runner/LM Studio, config files read in place, both
sqlite DBs copied to scratch before opening. Nothing was written, restarted, or
signalled. Repo: `/Users/debik/Claude Proj Rootz/New Harness/harness`; live snapshot:
`~/Library/Application Support/Harness`.

**The incident state, verified at audit time:**

- `harness.yaml` `runner.model` (the pin) = `Qwen3.6-27B-Fable-Fus-711-UnHeretic-NM-DAU-NEO-MAX-NEO-Q4_K_S` — a model whose **file is deleted and which has left the registry** (18 rows in `data/models.json`, 14 chat models, no 27B).
- The runner (llama.cpp, :6767) is up and serving exactly one model: `Parable-Qwen3-4B-Claude-Fable-5-GGUF-Q4_K_M` (authenticated `/v1/models`, verified).
- `/api/status` runner row: `pin_intent` = the 27B, `live_id` = Parable, `model_file: "unregistered"`, note = "…no longer in your model registry — rescan in Models, or pick another model". **The v1.5.57 truth holds.** The card renders `Online — pinned model missing` from exactly this (`panel/index.html` `cardHTML`, verified in source).
- `/api/deps` = `{"components":{}}` — **empty. Nothing is signalled**, and §3 explains why that is simultaneously "working as built" and the coverage gap that let two stale chips stand.
- One structural fact drives half the table: **llama.cpp ignores the request's `model` field** (measured in v1.5.51/U13/U20 and still true) — so every stale requester below *works* and gets Parable's tokens under the 27B's name. The system does not fail; it **lies quietly**, which is worse.

---

## 1. The verdict table

Four questions per surface: what it **displays** now · what it would **use** on the
next turn · is either **stale**, and which lie class · which **mechanism** should have
updated it and why it didn't.

| Surface | Displays now | Uses on next turn | Stale? / lie class | Mechanism that should have updated it — and why it didn't |
|---|---|---|---|---|
| **Runner card + `/api/status`** | `Online — pinned model missing`; meta `serving Parable…`; drift sentence names both ids | serves Parable | **Honest** (the v1.5.57 slice, verified live and in `cardHTML`) | n/a — this is the truth source. ⚠️ but the card's own advice ("pick another model") is un-followable for the model already served — see §4 fix 3 |
| **`harness.yaml` pin itself** | `runner.model:` 27B | every pin-reader inherits it (chat lane, ody seeder, opencode/voicestudio arms) | **STALE — the root artifact.** Class: *stale-intent record* | The old `_do_switch` rollback wrote it (pre-U16 fix, reverted the pin onto the deleted 27B after a FALSE failure); the new arm would not repeat it, but **nothing ever repairs it** — deliberately not silently (v1.5.57 ruling), and the offered manual path is broken (§4 fix 3) |
| **Models view rows + fit chips** | 14 rows (registry, no ghost), Parable row `live`, fits: 7 fits / 2 tight / 3 over / 1 unknown (`Laguna-XS-2.1-APEX-I-Compact` = "No estimate", U23's silent survivor) | switch route loads what you click | **Honest** | reads the registry + `live_id` — refreshed by rescan, which ran |
| **Panel Chat lane (composer chip)** | chip shows **Parable** (`modelLiveId \|\| modelActiveId` — live wins, `loadChatModels`) | ⚠️ **the wire sends the PIN**: `routers/chat.py:25` `model = rc.get("model")` = 27B → substitution → Parable answers, but `model_info`, per-turn metadata and analytics all say **27B** | **STALE USE under an honest chip** — chip and turn label disagree on the same screen. Class: *display-reads-config-not-live*, inverted (use-reads-config) | This is a named U18 echo (`modelid.py`/chat lane read the pin). Never fixed because U18 is `@status:open`. Bonus hazard: if the pin ever dangles onto an **MLX** id while a gguf serves (or vice versa), the wire id stops being harmless — MLX servers treat `model` as a load instruction |
| **Panel Agent lane** | header/chip shows the Odysseus **session's** stored model — the panel's own "Mission Control" session is bound to `Qwen3_6-35B-A3B-…IQ4_XS`, a model deleted **weeks** ago | Odysseus sends the session model → substitution → Parable answers | **STALE**, doubly (session-pinned ghost older than this incident). Class: *seed-once-never-refresh* (session records) | Nothing updates a stored session's model except the user's picker. Odysseus's own requested→actual label is the only truth on screen |
| **Panel Hermes lane** | Hermes's state | `~/.hermes/config.yaml` `model.default` | **Honest** — see Hermes row | — |
| **Odysseus** (seeded `local-jan` endpoint + composer chip + a turn) | chip = `default_model` = **27B**; picker offers **16** models incl. the deleted 27B (`pinned_models` still the pre-deletion registry; `cached_models` collapsed to `[Parable]` by its own probe); 8 of the last sessions stored on the 27B | new chat: requests 27B → substitution → **Parable answers labeled 27B** (its own requested→actual label is the one honest pixel) | **STALE ×3** (default, pinned list, session records). Class: *seed-once-never-refresh* + *display-reads-config-not-live* | The switch route **did** restart Odysseus (`_do_switch` re-wires it when running) and the seeder **did** run — but: (a) `seed_odysseus_jan._wire_model()` reads **the harness.yaml PIN, not the live model** (`_active_model_id()` regexes `runner: model:` — the "loaded-model-first" wording in v1.5.51 was true only while pin==loaded); (b) at that moment the 27B was still registered, so `settings_plan` judged `default_model` *visible* → honoured; (c) after the file deletion + rescan, **no Odysseus restart has happened since**, and even one today would seed the stale pin again, and would keep the 27B in `pinned_models` because the dangling pin is passed as `active` and force-inserted (`registry_wire_models` inserts `a` unconditionally). The `HARNESS_WIRE_MODEL` env override exists in the seeder **and has zero callers** |
| **Hermes** (main slot, v1.5.56) | its picker/config: `model.default = Parable`, provider `custom:mot-deck-(local)`, catalog pruned to the 14-model registry (`data/hermes-provider.json`: `changed:false`, 14 models, no 27B) | Parable (config read at use-time; process restarted 17:17, config patched 17:01) | **Honest — the one third-party app that is coherent** | v1.5.56 verified in source: the hermes arm curls `/v1/models` **with the auth header** and *"the runner's answer OUTRANKS harness.yaml"* (`start_component.sh`, LIVE_MODEL block) — the only seeder that prefers live over pin. This is the template every other seeder should copy |
| **Goose UI** | chip shows **27B** — both stores agree with Debi: `ui-home/goose/config/config.yaml` `providers.{openai,custom_mot_deck__local}.model: Qwen3.6-27B…`, and `sessions.db` `provider_inventory_models` holds exactly one row = the 27B | the **live goosed** (pid 87744, respawned post-switch) carries `GOOSE_MODEL=Parable…` + `GOOSE_PROVIDER=custom_mot_deck__local` in env — env beats config (F6), so a fresh session resolves Parable; a turn that does send 27B is substituted to Parable anyway. **Answer: always Parable's tokens; label: 27B** | **STALE DISPLAY.** Class: *display-reads-config-not-live* + *seeded-not-enforced honours a ghost* | The provider FILE was re-seeded correctly (14 models, no 27B, both lanes — `gooseprov` ran at respawn). But `providers.<slug>.model` is a key **goose wrote** when 27B was picked/live, and our seeder deliberately never touches it (v1.5.54's never-clobber F6 fix). Correct rule, missing complement: nothing marks or refreshes a *dangling* choice, and goose has no requested→actual label. Nothing signals it either — no `/api/status` row → no `/api/deps` derivation possible (S28b) |
| **Goose CLI lane** | `home/.config/goose/config.yaml`: `active_provider: custom_mot_deck__local`, **no model key at all**; provider file re-seeded (14, no 27B) | spawn env sets `GOOSE_MODEL` = live wire at next session | **Honest** (PTY lanes rebind on next session by construction) | — |
| **OpenCode** | default `model: llama.cpp/Parable…` in `opencode/opencode.json` — chip honest | Parable | **Catalog stale**: the provider block still lists **16** models incl. the ghost 27B (file written 2026-08-28 01:49, the last opencode Start; process running since then). Picking the ghost = substitution, and OpenCode has no requested→actual label | *seed-once-never-refresh*: the provider block is only rewritten by `start_component.sh opencode`, which has not run since the registry changed. (Its default-model block also reads the pin — U18 echo `:962` — it just happens not to matter while `cur` is valid) |
| **Generate / Compose engine chips** | ComfyUI checkpoints / music engines | their own engines | **Unaffected — verified**: `grep -c '6767\|runner' panel/comfy.html panel/compose.html` → 0 and 0. Neither page references the runner | n/a |
| **LOffice AI (note only)** | ribbon dropdown = whatever the last document-open seeded | `ooai.runner_state` probes the **live** served id and `oo.html` **overwrites** the plugin's localStorage on every open (`aiPrepare`, unconditional `setItem`) | **Coherent after next open** (live-read). Two notes: (a) a document left open across the switch keeps the old seed until reopened; (b) the seed rewrites the whole storage blob incl. `customProviders:{}` — an enforce that would clobber a provider the user added inside the plugin's own settings. Nobody has done that, but it is the never-clobber rule every other lane obeys, skipped here | by design (seed-on-open) |
| **Aider lane** | spawn-time live model | `routers/aider.py:92` `_live_model_id` — live-first ✓ | honest at spawn; a mid-session switch leaves the PTY on the old wire until respawn (S28c's lane-poll case) | — |
| **The deps banner `/api/deps`** | `{"components":{}}` — silent | — | **The coverage gap, quantified**: with the runner up+loaded, `needs_derive` can only flag `swapped`/`moved`, and `bindings` is built for **exactly one component** (`_hermes_binding`). Hermes is coherent → empty map. **Who SHOULD be showing `swapped` right now and isn't:** Odysseus (bound 27B ≠ live Parable), Goose UI (bound 27B ≠ live). OpenCode's default is fine (catalog ghost is a different class). And the harness's **own Chat lane** is the worst offender by its own standard — bound to the pin, no binding reader, no banner | Hermes-only by v1.5.55's honest limit (ledger S24/S28). The irony: the one app covered is the one app that self-heals (live-first seeder), so the signal as shipped can only ever fire between a swap and the next Hermes Start |

**Bottom line:** every turn in the building is answered by Parable. The surfaces that
*say so*: runner card, Models view, panel composer chip, Hermes everywhere, OpenCode's
default, Aider, LOffice-on-next-open. The surfaces that claim otherwise: **Odysseus's
chip/default/picker, Goose UI's chip, the panel Chat lane's own turn labels and
analytics, OpenCode's picker ghost** — and the banner built to catch exactly this
reports all-healthy.

---

## 2. Root-cause classes

1. **Seed-once-never-refresh (the never-clobber shadow).** The isolation slices
   (v1.5.49–56) made every third-party picker config-resident and made the seeders
   honour user values — correct, U11/U12-closing behavior. But "update only what is
   provably ours and stale" defines *stale* as "differs from what we last wrote", never
   as **"dangles against reality"**. A user-picked (or once-live-seeded) model that has
   since been deleted is honoured forever: Odysseus `default_model`, goose
   `providers.<slug>.model`, Odysseus session records, OpenCode's catalog. The seeders
   run only at component Start, and two of the four never re-ran after the registry
   changed.

2. **Display-reads-config-not-live.** Chips render a config/db value while the runner
   serves something else, and llama.cpp's silent substitution guarantees the turn
   *works*, so the lie never trips an error: Odysseus chip, Goose UI chip, and —
   inverted — our own Chat lane, which displays live but **wires and logs the pin**
   (U18's named echoes: `routers/chat.py:25`, `modelid.py:92/:192`,
   `start_component.sh` opencode `:962` / voicestudio `:615`).

3. **Swapped-signal coverage gap.** `/api/deps` derives `swapped` from `bindings`, and
   `bindings` has one reader (Hermes). Odysseus and goose have **cheap read-only
   binding sources this audit used directly** — no admin API, no live process needed:
   `vendor/odysseus/data/settings.json` `default_model` and
   `data/goose/ui-home/goose/config/config.yaml` `providers.<active_provider>.model`,
   plus `opencode/opencode.json` `model`. The S24 note ("Odysseus's binding lives behind
   its admin API") is **stale** — the settings file is on disk and world-readable.

4. **NEW — pin-first seeding under a live-first doctrine.** v1.5.56 established "the
   runner's answer outranks harness.yaml" and implemented it in exactly one arm
   (hermes). `seed_odysseus_jan._wire_model()` still reads the pin, so the Odysseus
   seed inherits any pin drift and *re-injects the dangling id* into `pinned_models`
   (as `active`) on every future Start — the stale pin doesn't just persist, it
   **propagates**. The seeder's own `HARNESS_WIRE_MODEL` override is the ready seam;
   it has no callers.

5. **NEW — the intent record has no repair affordance.** The pin is a legitimate
   intent record, and v1.5.57 rightly refused to silently rewrite it. But the only
   offered path ("pick another model") cannot target the model actually served —
   its row is `live` and `modelAction()` returns only **Eject** (plus Aux). The state
   `pin_intent ≠ live_id` is therefore **stable**: nothing in the UI can end it except
   ejecting Parable and reloading it, or hand-editing yaml. Debi hit this wall.

---

## 3. Why `/api/deps` is empty right now (the precise trace)

`deps()` → `status()` → runner `{running:1, port_up:1, loaded:1}` → the down/model-gone/
no-model arms all pass → `swapped` needs `bindings[name]`, and `bindings` gets exactly
one candidate: `_hermes_binding()` reads `~/.hermes/config.yaml` → `model.default =
Parable…` == `wire_model_id(live)` → no need → `{}`. Odysseus and Goose UI never enter
the comparison because nothing reads their bindings (and Goose additionally has no
status row for `needs_derive` to key on — S28b). So "nothing signalled either" is the
system behaving exactly as its honest limit says — and the limit is the bug.

---

## 4. The fix plan — slice ladder

**Slice 1 (S28 core): auto-rebind on switch — a runner switch re-seeds every dependent
through the seams that now exist.**
Trigger point, named: `bridge/routers/models.py::_do_switch`, immediately after
`_record_load_launch(new_id)` (line ~651) — the exact spot that already conditionally
re-runs `start_component.sh hermes` / `odysseus`. Generalize that block into a
dependents fan-out; every seam is v1.5.5x, idempotent, never-clobber:

- **Hermes** — already correct: `start_component.sh hermes` → live-first MODEL +
  `seed_hermes_provider.py` (which since v1.5.56 owns *both* `custom_providers` and the
  `model:` main slot — the S28 ledger note saying the main slot is "still a text patch"
  is stale; only the restart-vs-live-patch question remains).
- **Odysseus** — `seed_odysseus_jan.py`, called with **`HARNESS_WIRE_MODEL=<new wire>`**
  (the unused seam) so the seed stops inheriting the pin. For a *live* rebind without a
  restart, the admin-API upsert shape already exists in
  `bridge/routers/odyvision.py::ody_vision_shim_ensure` (match by base_url, never name).
  Also fix `_wire_model()` itself to prefer the live probe over the pin (the hermes-arm
  rule, one function), and stop force-inserting an `active` id that is neither
  registered nor served.
- **Goose (both lanes)** — `gooseprov.seed_provider()` + `gooseui.seed_config()`
  (`routers/gooseui.py:264`) already run at spawn; the rebind action is a goosed
  respawn (`/api/gooseui/start` seam exists). For the chip: a *dangling* honoured
  `providers.<slug>.model` (names a model neither in the registry nor served) is the
  one case "seeded, never enforced" should treat as repairable — same rule
  `settings_plan` already uses for OpenCode/Odysseus defaults ("replace only when the
  configured choice DANGLES").
- **OpenCode** — re-run the config half of the opencode arm (or extract its PYOC block
  into a callable script) so the provider catalog tracks the registry without a full
  component restart; its default-model rule already self-repairs dangling ids at Start.
- **Our own Chat lane** — close the U18 echo: `routers/chat.py` should wire
  `live → wire_model_id(live)` with the pin as runner-down fallback (the hermes-arm
  rule again). This also fixes per-turn metadata + analytics attribution.

**Slice 2: `swapped` coverage for all apps in `/api/deps`.**
Add three cheap binding readers beside `_hermes_binding` — all file reads this audit
performed read-only, none need the app running or an API:
`_ody_binding` (`vendor/odysseus/data/settings.json` → `default_model` +
`default_endpoint_id`, compare only when the endpoint is `local-jan`),
`_goose_binding` (embed-lane `config.yaml` → `providers[active_provider].model`; needs
the S28b status-row or per-lane action mapping so the need carries a real action),
`_opencode_binding` (`opencode.json` → `model` when prefixed `llama.cpp/`). The
sentence + `restart` action grammar already exists in `needs_message`. This makes the
banner say, today: *"Odysseus is still wired to 'Qwen3.6-27B…' — the Runner is now
serving 'Parable…'. Restart Odysseus to rebind."* — the exact sentence this incident
was missing.

**Slice 3: pin-align-to-served (the affordance Debi hit).**
Smallest honest fix: when `pin_intent ≠ live_id`, the runner card's drift sentence
gains one button — **"Pin the served model"** → `_set_runner_model(live_id)` (the
setter already exists in `routers/models.py`; no reload needed, the model is already
up; publish a `model` event so the panel re-reads). Belt-and-braces: in the Models
view, a `live` row whose id ≠ `active` shows "Pin" beside Eject (`modelAction()` gains
the one state it is missing). This ends the stable drift state without ever writing
the pin silently.

**Slice 4: the Goose UI chat-delete verdict — NOT a shim casualty, and not lost.**
Read off the vendored v1.48.0 bundle (`data/goose/ui/assets/App-DERRs_Zf.js` +
`index-YGtEK3wY.js`):
- Delete **exists**: the **Sessions page** renders per-session card actions — open-in-new-window / rename / duplicate / **Delete session** (red trash icon) — revealed on **hover** (`opacity-0 group-hover:opacity-100`).
- The click opens a **React confirmation dialog** (in-page state `Ie → ee(e), D(!0)`, confirm handler `Re`), not a native Electron dialog.
- The deletion itself goes over the **ACP websocket** (`session_delete` in the protocol table, `index-YGtEK3wY.js`) to the goosed **we supervise**, then `SESSION_DELETED` events update the lists.
- **Zero electron methods in the path.** Nothing in the v1.5.40 DEGRADED set (native pickers, FS access, save dialog, multi-window) is touched; `showMessageBox` is shimmed to `confirm()` anyway and isn't used here.
- What Debi likely saw: the **sidebar's recent-sessions list has no per-item delete at all upstream** (its component renders name/date only and merely *listens* for `SESSION_DELETED`), and on the Sessions page the icons are invisible until the card is hovered. So the verdict is **discoverability, not capability**: chat deletion should work today in the embedded tab via Sessions → hover a card → trash → confirm. One caveat honestly held: this is a code-walk verdict; the one-minute live click on `/gooseui/` was out of scope for a read-only audit and should be the slice's first step. If the hover-reveal misbehaves in WKWebView, the fix is a CSS nudge in our injected page (always-visible action row), not a shim method.

**Slice 5 (rounding out): the fresh-eyes list from §5** — chiefly the dangling-choice
rule (5.2) and the registry duplicate (5.4).

---

## 5. Anything else fundamentally incoherent (fresh eyes)

1. **The panel Chat lane disagrees with itself on one screen** — composer chip says
   Parable (live), the turn's `model_info` frame, sidecar metadata and
   `log_turn("direct", model, …)` analytics all say 27B (pin). Debi's usage/analytics
   for every direct-chat turn since the rollback are attributed to a model that wasn't
   loaded. Same-class hazard: `voicestudio` arm exports `TRANSLATE_MODEL=<pin>` (:615).

2. **"Honoured" has no dangling check anywhere but OpenCode/Odysseus defaults.** The
   settings_plan/OpenCode rule — *seed when unset, replace when the choice dangles,
   honour otherwise* — is the correct three-state rule, and it exists in exactly two
   places. Goose's provider model and Hermes's `model.default` honour unconditionally
   (Hermes gets away with it via the live-first Start arm; goose doesn't). One shared
   definition of "dangles" (not in registry AND not served) applied across all four
   seeders would have prevented both stale chips in this incident.

3. **`/api/status` naming hazard:** the runner row's `pin` field carries the **live id**
   (component "pin" semantics reused), while `pin_intent` carries the actual yaml pin.
   Any future consumer that reads `runner.pin` expecting the pin gets the live model —
   `deps()` itself does `live = runner.pin` (correct value, misleading spelling). Rename
   or alias (`served_id`) before someone believes the label.

4. **Registry duplicate:** `data/models.json` carries `parakeet-tdt-0.6b-v3` **twice**
   (identical audio rows). Harmless today; every `next((m for m if id==...))` consumer
   silently takes the first, and a future divergence between the two rows would be
   invisible. The rescan/seed path should de-dupe by id.

5. **Odysseus session records are un-healable ghosts:** sessions store `model` +
   `endpoint_url` at creation and nothing ever revisits them (`Mission Control` is on a
   35B deleted weeks ago; 6 more sessions on the 27B). Reopening any of them silently
   substitutes. U13's load-on-select/hint destination is the real fix; until then the
   requested→actual label is the only defence, and only Odysseus has one (U20: Hermes
   has none; goose and OpenCode have none either).

6. **The isolation slices did not break anything they touched** — the never-clobber
   walks held everywhere this audit looked (goose provider files correct in both lanes,
   hermes catalog pruned with the marker rules, `local-jan` endpoint intact, opencode
   merge preserved user keys). What they *did* do is make the substitution lie-class
   systemic: four pickers now confidently offer 14–16 config-resident models while the
   runner serves one, three of the four without any requested→actual honesty
   (U13/U14/U20 name this; this incident is what it looks like in the wild).

7. **The banner's own cadence gate** (`depsPoll` only while a banner-capable tab shows)
   is fine, but worth restating for slice 2: coverage without a status row (goose lanes)
   needs S28b's per-lane action mapping or the derived need will render with a dead
   button — the exact defect S20 documents for the log allowlist.

---

## 6. Verification commands (all read-only)

```
curl -s 127.0.0.1:8700/api/status | python3 -m json.tool | grep -A3 pin_intent
curl -s 127.0.0.1:8700/api/deps                        # {} = signal silent
curl -s -H 'Authorization: Bearer harness-local' 127.0.0.1:6767/v1/models
python3 -c "import json;print(json.load(open('$HOME/Library/Application Support/Harness/vendor/odysseus/data/settings.json'))['default_model'])"
grep -A2 '^model:' ~/.hermes/config.yaml
grep -B1 -A2 'custom_mot_deck__local:' "$HOME/Library/Application Support/Harness/data/goose/ui-home/goose/config/config.yaml"
python3 -c "import json;print(json.load(open('$HOME/Library/Application Support/Harness/data/opencode/xdg/config/opencode/opencode.json'))['model'])"
ps eww $(cat "$HOME/Library/Application Support/Harness/data/goose-ui.pid") | tr ' ' '\n' | grep GOOSE_MODEL
```

**Nothing was changed by this audit — no restart or refresh is required.** If Debi
wants the stale bindings healed *today*, before any slice ships, the manual sequence
is (in MOT Deck, or via the API): fix the pin first (edit `harness.yaml
runner.model` to the Parable id — the one write the card currently can't make), then
Restart Odysseus and reopen any LOffice documents; Hermes needs nothing; Goose UI's
chip clears when a model is picked once inside its own picker (or on the slice-1
dangling-choice repair). This audit ran none of those.
