# Hermes v2026.8.27 (v0.20.6) — ATTEMPTED, PROVEN UNSHIPPABLE, ROLLED BACK

**Date:** 2026-08-28 · **Builder:** Opus · **Bound by** `docs/DOCTRINE-PROACTIVE-BUILD.md`
**Verdict:** the bump is blocked by **two upstream bugs in Hermes v0.20.3+**, not by
our integration. We are back on `v2026.8.13` (app v0.20.1) and everything works.
**Do not retry above `v2026.8.16` until upstream fixes them** (see *The retry plan*).

This file exists so the next sitting costs an hour, not a day. Everything that was
measured is written down, including the large amount that PASSED.

---

## 1. From → to (and back)

| | |
|---|---|
| Was, and is again | tag `v2026.8.13` · app **v0.20.1** · commit `f80f453a` · `mcp 1.28.1` |
| Attempted | tag `v2026.8.27` · app **v0.20.6** · commit `5fc308a7` · `mcp 2.0.0` |
| Range | 3564 commits · 5 releases (0.20.2 – 0.20.6) |

`v2026.8.27` was verified as the genuine newest tag rather than taken from the
audit: `git fetch --tags` then `git tag --sort=-creatordate` gives
`v2026.8.27 (08-27) · v2026.8.19 · v2026.8.18 · v2026.8.16.2 · v2026.8.16 · v2026.8.13`.

⚠️ **`package.json` reads `"version": "1.0.0"` at EVERY tag.** `pyproject.toml`'s
`version` is the only honest app-version source. Do not use package.json.

### Which tag introduced mcp 2.x — this is the important table

| tag | app | `mcp` extra |
|---|---|---|
| v2026.8.13 | 0.20.1 | `mcp==1.28.1` |
| **v2026.8.16** | **0.20.2** | **`mcp==1.28.1`** ← last mcp-1.x tag |
| v2026.8.16.2 | 0.20.3 | `mcp==2.0.0`, `httpx2==2.7.0` |
| v2026.8.18 | 0.20.4 | `mcp==2.0.0` |
| v2026.8.19 | 0.20.5 | `mcp==2.0.0` |
| v2026.8.27 | 0.20.6 | `mcp==2.0.0` |

---

## 2. THE BLOCKER — two camelCase attribute reads upstream forgot to convert

**Root cause, one sentence:** mcp 2.0.0 renamed every model field to snake_case and
kept the camelCase spelling only as a **serialization alias**; pydantic aliases do
**not** apply to attribute access, so `getattr(obj, "camelCaseName")` silently
returns `None` on 2.x instead of raising.

Upstream **knew this** and built the fix helper for it —
`mcp_field(obj, snake, camel, default)` at `tools/mcp_tool.py:488`. Its own docstring
names the exact failure modes we then hit:

> *"That turns a rename into silent wrong behaviour: failed tool calls read as
> successful, tool schemas read as empty, paginated lists stop after page one."*

They applied `mcp_field` in **19 places** in `tools/mcp_tool.py` (plus a private copy
in `tools/computer_use/cua_backend.py`). **They missed these:**

### Bug 1 — read-only MCP tools are misclassified as write-capable
`vendor/hermes/tools/mcp_tool.py:4643`, in `_annotation_read_only_hint()`:
```python
hint = getattr(annotations, "readOnlyHint", None)      # → always None on mcp 2.x
...
return hint is True                                    # → always False
```
mcp 2.0.0's `ToolAnnotations` field is `read_only_hint` (`mcp_types/_types.py:1379`),
with `readOnlyHint` only as a wire alias.

**Effect:** every tool on a `trust: untrusted` MCP server is treated as write-capable
and raises the per-call trust gate — *including tools that correctly declare
`readOnlyHint: true` on the wire.*

**Reproduced live** (real 27B turn through the panel's Hermes lane):
```
tool_start  mcp__loffice__office_list
approval    "MCP tool 'office_list' on UNTRUSTED server 'loffice' wants to run.
             This tool is write-capable (no readOnlyHint=true annotation)…"
tool_output is_error=true  "The user did not approve running write-capable MCP tool…"
```
That is the **entire v2 LOffice consent design inverted**. `docs/FABLE-AGENT-CHANGESET-SPEC.md`
ruled, after the 2026-08-27 consent incident, that this lane raises **zero** approval
cards and that consent lives on the panel's changeset card. Under v0.20.6 the model
cannot read a spreadsheet without Debi answering a card per call — the precise failure
the ruling exists to prevent.

Proof in isolation, run in the real venv:
```
$ hermes-venv/bin/python -c '...'
parsed from wire camelCase: read_only_hint=True
getattr readOnlyHint   -> None
getattr read_only_hint -> True
>>> Hermes _annotation_read_only_hint(tool) = False
```

### Bug 2 — the MCP schema cache is written with EMPTY tool schemas
`vendor/hermes/tools/mcp_tool.py:7374`, in the cache writer:
```python
schema_obj = getattr(mcp_tool, "inputSchema", None)    # → None on mcp 2.x
... "inputSchema": schema_obj if isinstance(schema_obj, dict) else {},
... "annotations": {"readOnlyHint": _annotation_read_only_hint(mcp_tool)},   # ← Bug 1 again
```
mcp 2.0.0's field is `Tool.input_schema`. Note the same file reads it **correctly**
at `:6871` and `:2105` via `mcp_field` — only the cache writer was missed.

**Effect:** the cache is *poisoned*. Every cache-registered ("lazy") start hands the
model tools **with no argument schema at all** and `readOnlyHint: false`.

**Reproduced on disk** — this is what `~/.hermes/cache/mcp_schema_cache.json` held
after one v0.20.6 run (evidence kept, see §6):
```
office_list          | annotations = {'readOnlyHint': False} | schema keys = []
office_read          | annotations = {'readOnlyHint': False} | schema keys = []
office_sheet_stats   | annotations = {'readOnlyHint': False} | schema keys = []
office_stage_changes | annotations = {'readOnlyHint': False} | schema keys = []
```
`office_stage_changes` with an empty schema means the model is never told that `name`,
`sheet` and `ops` exist. That is a silent, total break of the Agent lane — and it is
**not** limited to our server; it hits every MCP server Hermes hosts on its next
cache refresh. `config_fingerprint` does not change, so the poisoned entry is
*re-used*, not re-derived.

A third, unexercised miss: `:2284` `getattr(params, "requestedSchema", None)`
(elicitation).

### Also still broken on upstream `main`
`origin/main` @ `6dcebea7` (also 0.20.6) has the identical
`getattr(annotations, "readOnlyHint", None)` at `:4643`. **No upstream fix exists yet.**

### Why there is no fix on our side
- Our server already sends camelCase on the wire **correctly** — the handshake test
  proves the SDK parses it (`read_only_hint=True`). The bug is purely Python attribute
  access inside Hermes.
- We cannot make the SDK object expose a `readOnlyHint` attribute: `MCPModel` sets no
  `extra`, so pydantic **drops** unknown keys (measured — sending both spellings gives
  `model_extra: None`).
- Editing `vendor/hermes` is out (compose over APIs, never fork).
- Flipping `mcp_servers.loffice.trust` from `untrusted` to `full` would silence Bug 1,
  but it disarms a documented fence to hide an upstream bug — exactly the
  "shipped unattended because someone also had to remember a config key" failure
  `bridge/office_mcp.py`'s own docstring warns against. And it does nothing for Bug 2.

---

## 3. WHAT PASSED AT v0.20.6 — do not re-derive this

### The mcp 2.x transport question is ANSWERED: our hand-written server needs no change
This was the mission's headline risk and it is a **non-issue**, measured three ways:

- **mcp 2.0.0 keeps two eras.** `mcp_types/version.py` splits
  `HANDSHAKE_PROTOCOL_VERSIONS` (…`2025-11-25`) from `MODERN_PROTOCOL_VERSIONS`
  (`2026-07-28` — the stateless per-request envelope + `server/discover` probe).
- **Hermes deliberately stays on the handshake era.** `tools/mcp_tool.py:261-267` and
  `:3616-3624`: it connects with `ClientSession.initialize()` and seeds
  `mcp-protocol-version: LATEST_HANDSHAKE_VERSION`, with a comment explaining that
  advertising `2026-07-28` would route onto the envelope ladder and be rejected. It
  never calls `mcp.client._probe.negotiate_auto`, so `server/discover` is never sent
  to us. (Even if it were: our `-32601 method not found` is on that module's fallback
  **denylist** — anything that is not positive modern evidence falls back to
  `initialize`.)
- **All three transport rules `bridge/office_mcp.py` is written against still hold**
  in the 2.0.0 client: `202` for a notification (`streamable_http.py:329`),
  `application/json` accepted for a request (`:382` — the `JSON` constant was inlined
  to the literal, which is the only contract-test string that moved), `405` tolerated
  on the GET stream (`:631`).

**Wire evidence** from the bridge log during the v0.20.6 handshake test — the whole
protocol, exactly as designed:
```
POST /mcp/office 200   (initialize, application/json)
POST /mcp/office 202   (notifications/initialized, empty body)
GET  /mcp/office 405   (no server stream — client stops asking)
POST /mcp/office 200   (tools/list)
DELETE /mcp/office 204 (session termination — 2.x cleans up; we honour it)
```
And `POST /api/mcp/servers/loffice/test` under mcp 2.0.0 returned **all four tools
with correct schemas** (`schema_chars` 499 / 1043 / 934 / 4894).

**NO new bridge dependency was added. The no-FastMCP ruling stands, unchanged.**

### The path-guard fence and the approval cards survive v0.20.6
Despite three refactors moving the seam, a real turn asking `write_file` for
`~/Desktop` raised:
```
approval  "<write_file> (plugin approval rule)"
          "path-guard: write outside workspace: /Users/debik/Desktop/motdeck-gate-probe.txt"
```
and the file was never created. `approvals.mode: manual` also survived.

### A real Hermes-lane chat turn streams end-to-end at v0.20.6
`hermes_session` → thinking deltas → `hermes_status`/`hermes_ping` → answer deltas →
`[DONE]`. The SSE frame vocabulary is unchanged.

### The contract gate went 139 → 142 green
Five asserts tripped; **all five were upstream refactor-MOVES, none a regression.**
Every mirror was written to be *stronger*, and to pass at **both** tags — so all of it
is **KEPT at the rolled-back pin** and arms itself when the pin next moves. Details in §4.

---

## 4. Every tripped contract test and its resolution

| # | Test | What moved upstream | Resolution |
|---|---|---|---|
| 1 | `test_hermes_skills_contract.py::test_the_global_list_is_unioned_into_every_platform` | new `ESSENTIAL_SKILLS` frozenset wraps the union as `(global \| platform) - ESSENTIAL_SKILLS` (`agent/skill_utils.py:443,475-483`) | mirror widened to match the **union** rather than the whole `return` line. Still fails if `\|` becomes `&` or the platform list starts *replacing* the global one. |
| 2 | *(new)* `…::test_essential_skills_cannot_be_disabled_from_either_side` | — | **new test** pinning the newly-found fact, plus a real fix on our side (below). Dormant at v0.20.1, arms at v0.20.3+. |
| 3 | `test_hermes_ws_contract.py::test_clarify_protocol_contract` | the `session.interrupt` body hoisted into shared `server._interrupt_session_turn()` (`server.py:1112-1157`) so the WS orphan reaper applies the same contract; handler calls it on both branches (`methods_session.py:3338`, `:3345`) | mirror now accepts **either** shape and, in both, requires `_clear_pending(sid)` **and** the deny-all `resolve_gateway_approval` — the second half was never pinned before. |
| 4 | `test_hermes_ws_contract.py::test_path_guard_hook_contract` (a) | the pre_tool_call escalation body hoisted into `_resolve_block_from_details()` (`plugins.py:6603`), shared with the new `_dispatch_pre_tool_call_hooks()` | mirror follows the hop and now also pins **fail-closed** (`BLOCKED: plugin approval gate failed`) and block-on-deny, which the old single literal never checked. |
| 5 | `test_hermes_ws_contract.py::test_path_guard_hook_contract` (b) | `model_tools.py:1384-1401` calls `_dispatch_pre_tool_call_hooks` instead of `resolve_pre_tool_block` | mirror accepts either name and additionally pins `skip_pre_tool_call_hook` (the single-fire opt-out — without it the guard could card twice for one write). |
| 6 | `test_office_mcp_contract.py::test_the_client_hermes_ships_accepts_a_json_reply_and_a_bare_202` | mcp 2.0.0 inlined `startswith(JSON)` → `startswith("application/json")` | mirror accepts both spellings; passes on mcp 1.x and 2.x. |
| 7 | *(new)* `…::test_hermes_stays_on_the_handshake_era_so_our_hand_written_server_is_reachable` | — | **new test** recording the whole §3 answer. Upstream half dormant on mcp 1.x; our half (`negotiate()` must never echo `2026-07-28`) runs at every pin. |
| 8 | *(new)* `test_hermes_ws_contract.py::test_the_new_modify_directive_can_rewrite_args_the_guard_already_judged` | — | **new negative** for a hazard found while bumping (below). Runs at every pin. |

The **all-clear** side of the office contract also held at v0.20.6 unchanged (line
numbers moved, strings did not): `mcp_servers` key, `"url" in self._config` ⇒ HTTP,
`transport: sse` opt-in, `_TRUST_UNTRUSTED`/`_TRUST_FULL`, default-`full`,
`_annotation_read_only_hint`, `return hint is True`, `_trust_gate_check`,
gate-before-transport, and **no** per-tool `approval`/`approvals`/`require_approval`/
`tool_approval` config knob appeared. That is why the static gate went green while the
*behaviour* was broken — see the honest limit in §7.

### Fix landed on our side (kept; harmless at v0.20.1)
`ESSENTIAL_SKILLS` is subtracted **symmetrically** — `save_disabled_skills` drops it on
the way in and `get_disabled_skills` on the way out (`hermes_cli/skills_config.py:55-74`).
So at v0.20.3+ a request to disable `hermes-agent` answers **200 and persists nothing**,
and the panel switch snapped straight back with no explanation. Fixed:
- `bridge/app.py` — `POST /api/hermes/skills` now reports `pinned_on` (names that
  refused to go OFF; `stuck` only ever covered "wanted ON, still OFF" and its message
  says "still off"), drops those names from `changed`, and sets the note accordingly.
- `bridge/panel/index.html` — prints *"Hermes keeps these on and ignores a request to
  switch them off: …"*.

Inert while `ESSENTIAL_SKILLS` does not exist, so it ships safely at v0.20.1.

### New hazard found while bumping (pinned, not reachable today)
v0.20.6 adds a **third** `pre_tool_call` directive: `{"action":"modify","args":{…}}`,
merged into the tool's args before dispatch (`plugins.py:6485-6495`) and returned from
the **same** hook pass as a block/approve. So: our path-guard judges the original
`file_path`, Debi approves *that* path on the card, and a `modify` directive from any
other enabled pre_tool_call plugin can then replace it with a path nothing re-checked.
**Not reachable today** — no bundled Hermes plugin emits `modify`, and `plugins.enabled`
is opt-in with `motdeck-path-guard` the only name `start_component.sh` adds. The new
test fails loudly if a bundled plugin ever gains one; the fix then is for the guard to
re-judge `modified_args`.

---

## 5. The retry plan

**Precondition (either one):**
1. Upstream converts `tools/mcp_tool.py:4643` and `:7374` to `mcp_field(...)` — watch
   for it in a tag above v0.20.6, or file it upstream. Two one-line changes:
   `mcp_field(annotations, "read_only_hint", "readOnlyHint")` and
   `mcp_field(mcp_tool, "input_schema", "inputSchema")`. (Also `:2284`
   `requestedSchema` → `requested_schema`.)
2. …or accept a fork of those two lines, which the compose-over-APIs rule currently
   forbids. Raise it with Debi before doing this, do not decide it in a build sitting.

**The safe partial, available right now:** `v2026.8.16` (app **v0.20.2**) is the last
`mcp==1.28.1` tag, so it carries none of this. It is a one-release bump and the audit
found no security driver in the range, so it is *optional* — but it is the ceiling
until the precondition is met.

**When you do retry:**
1. Everything in §3 is already measured — do not re-derive the transport story.
2. All eight contract mirrors in §4 already pass at v0.20.3+; expect the gate to be
   green immediately, and **do not trust that**. The gate was green while the lane was
   broken.
3. **Walk journey C2 first** (a real model turn calling `office_list`), before
   anything else. Zero approval frames is the pass condition. It is the cheapest
   possible detector for Bug 1.
4. Then check `~/.hermes/cache/mcp_schema_cache.json` for the loffice entry: every
   tool must have `readOnlyHint: true` and a non-empty `inputSchema`. That is the
   detector for Bug 2. **Purge the entry before re-testing** — `config_fingerprint`
   does not change, so a poisoned entry survives a restart.
5. Add both of those as executable tests before shipping (see the honest limit in §7).

---

## 6. Rollback artifacts left on disk

Kept in `docs/handoff/rollback-hermes-2026-08-28/`:

| file | what it is |
|---|---|
| `OLD-SHA.txt` | `f80f453ae0679347e38abc917c7f94f717bf96c5` / `v2026.8.13` |
| `discarded-package-lock.diff` | the dirty `vendor/hermes/package-lock.json` diff (27 added lines), **deliberately discarded** on this bump. Nothing else in `vendor/hermes` was locally modified — verified before touching anything. **See the sidebar below: this file's origin is now known.** |
| `hermes-venv-freeze-OLD.txt` | 113-line `pip freeze` of the snapshot Hermes venv at v0.20.1 |
| `motdeck.yaml.repo.bak`, `motdeck.yaml.snapshot.bak` | both manifests before the bump |
| `POISONED-mcp_schema_cache.json` | **the evidence for Bug 2** — the real cache file as v0.20.6 wrote it |

### 🔎 Side finding: the "dirty package-lock" mystery is SOLVED
Every builder since 2026-08-23 reported `vendor/hermes/package-lock.json` as dirty and
"pre-existing, not mine". **They were all right, and it is not a stray edit at all:
`scripts/install_component.sh`'s own `npm install --workspace web` step regenerates it
on every hermes install.** `package-lock.json` is not gitignored the way `node_modules/`
and `web_dist/` are, so the build leaks into `git status`.

Measured: discarded it, ran the installer, and `git diff package-lock.json` came back
**byte-identical** to the diff saved above (27 added lines). So discarding it before a
pin bump is always safe, and it always comes back. A comment recording this now sits
next to the npm step in `scripts/install_component.sh` so nobody chases it a fourth
time. (It is dirty again right now, for exactly this reason — the state is otherwise
identical to pre-bump.)

Also on disk (safe to delete once you are happy):
- `~/Library/Application Support/MOT Deck/vendor/hermes.v2026.8.13.bak/` (426 MB) —
  the pre-bump vendored tree; this is what the rollback was performed FROM.
- `~/Library/Application Support/MOT Deck/data/hermes-venv.rolledforward/` (438 MB) —
  the v0.20.6 venv (mcp 2.0.0), moved aside. **Keep this one until the retry** — it
  saves a full reinstall when you next test v0.20.3+.
- `~/Library/Application Support/MOT Deck/motdeck.yaml.bak-hermes-20260828{,-post}`

Rollback commands actually used (for the record):
```bash
git -C vendor/hermes checkout v2026.8.13
./scripts/install_component.sh hermes --yes                      # repo venv + web_dist
rsync -a --delete "$DST/vendor/hermes.v2026.8.13.bak/" "$DST/vendor/hermes/"
mv "$DST/data/hermes-venv" "$DST/data/hermes-venv.rolledforward"
mv "$DST/data/hermes-venv.v2026.8.13.bak" "$DST/data/hermes-venv"   # path-exact ⇒ shebangs work
# purge the poisoned cache entry — it survives a restart otherwise
python3 - <<'EOF'
import json, pathlib
p = pathlib.Path.home() / ".hermes/cache/mcp_schema_cache.json"
d = json.loads(p.read_text()); d.pop("loffice", None); p.write_text(json.dumps(d, indent=1))
EOF
./scripts/ship.sh --restart hermes
```

---

## 7. Honest limits

- **The static contract gate did not catch either blocker, and could not have.** All
  the pinned upstream strings still existed at v0.20.6 — the *values those reads
  return* changed. This is the strongest argument yet that the file:line mirror suite
  needs live journey tests beside it for anything with a behavioural outcome. **The
  two live detectors in §5 steps 3-4 are NOT yet executable tests** — they are
  procedure. Turning them into a `bridge/tests/` journey test (assert zero approval
  frames on an `office_list` turn; assert the cache entry is healthy) is the single
  most valuable follow-up from this sitting, and it was out of scope here because the
  version that fails them is no longer installed.
- **The `pinned_on` fix is pinned but not journey-walked.** It needs a v0.20.3+ Hermes
  running to exercise, and we rolled back. The contract test asserts the reporting
  exists and the upstream symmetry that makes it necessary; the panel sentence has not
  been seen by a human eye in the UI.
- **Bug 2's blast radius beyond our server is inferred, not measured.** The mechanism
  is server-agnostic (the cache writer is shared), and `browsermcp`'s cached entries
  still carry schemas because they were written under mcp 1.x. We did not force a
  refresh of another server's cache to watch it happen.
- **Not walked at v0.20.6, because the lane was already blocked:** journey (d), a
  staged changeset through the Agent path. It *was* walked at the restored pin (below).
- **`~/.hermes/config.yaml` is at `_config_version: 33`** while v0.20.1's
  `DEFAULT_CONFIG` says 34 (and v0.20.6 says 39). This is **pre-existing** and
  unchanged by the attempt — no migration ran, which is why the rollback is clean —
  but someone should decide whether that drift matters. Migrations 34→39 are what a
  successful retry would apply; they are listed in `hermes_cli/config_migrations.py`
  and include a "one-time personality reset" and several default raises.
- **Concurrent activity in the tree.** `bridge/tests/test_theme_packs.js` appeared
  mid-session (04:05) and is not this sitting's work. The sweep count moved 67 → 68
  for that reason.
- **A staged changeset with a 600 s TTL was left in the store** by journey (d)
  (`76dc8370643e89b0`, `Monthly budget.xlsx` H1 = `QA-PROBE`, `applied: false`). It
  expires on its own; nothing was applied and the workbook's mtime is untouched.
- The three probe SSE captures and the mcp 2.0.0 / mcp-types wheels read during
  reconnaissance are in this session's scratchpad, not the repo.

---

## 8. Post-rollback verification — every journey re-walked at v2026.8.13

Because a rollback that has not been verified is not a rollback.

| journey | evidence |
|---|---|
| (a) dashboard + version | `/api/health` → `{"ok":true,"version":"0.20.1"}`, new PID, `/` → 200. Bridge `/api/status` → `pin v2026.8.13 · running true · health ok` |
| (b) real chat turn through the panel's Hermes lane | full SSE: `hermes_session` → thinking → deltas → `[DONE]` |
| (c) loffice MCP handshake + a real `office_list` model turn | handshake lists all four tools; a real 27B turn: `tool_start mcp__loffice__office_list` → `tool_output` (no `is_error`) → the model listed the 8 real workbooks. **Approval frames: 0** ✅ |
| (d) staged changeset through the Agent path | `office_stage_changes` in one call → changeset `76dc8370643e89b0`, `preview: H1 "" → "QA-PROBE"`, `cells_changed: 1`, `applied: false`, **workbook mtime unchanged** (Aug 27 15:37 vs staged 04:18). **Approval frames: 0** ✅ |
| (e) approval machinery alive for a write-capable non-office tool | `write_file` → `~/Desktop` raised `path-guard: write outside workspace`; file never created ✅ |
| the gate | `./scripts/verify.sh` → **142 passed, 4 skipped** · `bridge/tests` sweep → **68/68** |
| config | `approvals.mode: manual` intact · MCP schema cache healthy (`readOnlyHint: true` + real schemas on all four) |
