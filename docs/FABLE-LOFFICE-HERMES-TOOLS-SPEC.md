# FABLE SPEC — LOffice real tools via Hermes (2026-08-27, v1)

**Status:** ruled, awaiting builder · **Owner:** Fable 5 (design), Opus builder (build)
**Supersedes:** nothing — the taught action block (v1.5.2) STAYS as the "Quick" lane.
**Prereq reading for the builder:** this file end-to-end, then `bridge/office.py`,
the toolset lever notes around `bridge/app.py:6459-6580`, and Hermes's MCP catalog
surface (`vendor/hermes` — read, never edit).

## 0. What Debi asked for, and the honest split

"Hermes-like abilities" in the LOffice AI panel. The action block already gives
propose→preview→apply→undo on ANY local model. What it cannot do: multi-step work
(read → compute → write → verify), acting across files, or using a real tool loop.
That is Hermes's job, and Hermes already owns the three hard parts: a tool registry,
approval cards, and the path-guard discipline. We do not rebuild those — we hand
Hermes a small, containment-locked Office toolset and a place in the LOffice panel.

## 1. The one architectural ruling: MCP server on the bridge, not a vendor fork

The office tools are exposed as an **MCP server hosted by the bridge** (new module
`bridge/office_mcp.py`, mounted on the existing :8700 app under `/mcp/office` —
loopback only, same as everything else). Hermes consumes it through its own MCP
catalog, so:
- Hermes's OWN approval cards gate the write tools (we register them as
  approval-required; the "seconds-fast minimal preset" lever keeps working).
- No edit to `vendor/hermes` — compose over APIs, never fork (doctrine).
- The toolset appears in the Capabilities pane like any other, with the existing
  out-of-sync/Adopt reconciliation.

**Registration:** the installer/config-gen step that already writes Hermes's config
adds the office MCP server entry (URL, name `loffice`, enabled default-ON but the
toolset lever can trim it). Idempotent, survives Hermes pin bumps the way the a2a
mirror does.

## 2. The tools (v1 — exactly six, all name-addressed, never path-addressed)

Containment is BY CONSTRUCTION: every tool takes a workbook NAME resolved through
`office.py`'s existing `doc_target`/`valid_name` (realpath under `data/office`,
basename-only, traversal refused). A tool that takes no path cannot escape one.

| tool | args | returns | approval |
|---|---|---|---|
| `office_list` | — | names, sizes, mtimes, open/dirty hints | no |
| `office_read` | name, range? (A1:D20, cap 2000 cells), sheet? | values + formulas-as-text + merges in range | no |
| `office_sheet_stats` | name, sheet? | dims, sheet names, column stats (reuses the Data-menu derivation) | no |
| `office_write_cells` | name, sheet?, ops[] (same `set`/`style` grammar as the action block, same caps: 60 ops / 2000 cells, refuse-over-cap) | per-op report | **yes** |
| `office_sort` / `office_insert_delete` | name + the same args the page's `sortGo`/`rcGo` take | report | **yes** |
| `office_create` | name (never clobbers — ' (n)' steps) | final name | **yes** |

Server-side execution lives in `office.py`-adjacent code (new `office_ops.py`)
implementing the SAME semantics the page has, against the .xlsx via openpyxl:
same merge-refusal on sort, same formulas-not-rewritten rule with the note in the
tool RESULT (the model must see the honesty, not just the user). Shared constants
with the page where practical; where not, contract tests pin both sides to the
same table.

## 3. The write-safety rules (all three are load-bearing)

1. **Pre-write sibling backup:** every approved write tool first copies the target
   to `name.pre-agent.xlsx` (one level, overwritten per agent-write; distinct from
   the daily `.bak`). This is the agent-lane undo: the page's in-memory undo stack
   CANNOT cover a server-side write and must not pretend to.
2. **Open-dirty conflict:** the LOffice page already beacons; it gains a tiny
   heartbeat that registers `{name, dirty}` with the bridge while a file is open.
   `office_write_cells` on a file registered OPEN-AND-DIRTY **refuses** with
   "Debi has unsaved edits in that workbook — ask her to save or close first."
   Open-and-clean is allowed (see rule 3). No heartbeat (page closed/crashed) =
   allowed. Heartbeat is advisory, TTL ~15s, never a lock file.
3. **External-change banner in the page:** LOffice polls the mtime of its open file
   (piggyback on an existing poll — do not add a new timer). On external change:
   clean page → auto-reload with the message "the agent edited this file — reloaded
   (pre-edit copy kept as *name*.pre-agent.xlsx)"; dirty page → a two-button banner:
   **Reload** = discard my in-memory edits and show the agent's version;
   **Keep mine** = keep editing my in-memory version, and my next ⌘S overwrites the
   agent's write on disk (which still survives in nothing — so the banner must say
   that plainly: "saving will overwrite the agent's changes"; the agent's PRE-write
   state is what `.pre-agent.xlsx` holds, not the agent's write itself). The banner
   states which version survives where; a test pins both sentences.

## 4. The panel surface (small, honest)

The LOffice AI panel gains a **lane toggle**: `Quick` (today's direct lane +
action block — default, works on every model) · `Agent` (Hermes). The Agent lane:
- Requires a tool-calling model — reuse the tools-pill detection; if the current
  Hermes model lacks it, the toggle is disabled with the reason in its title
  (grey-not-hide, as everywhere).
- Opens/reuses ONE dedicated Hermes session per LOffice (named `loffice`), with the
  sheet-grounding preamble (reuse `aiPreamble()`; the open sheet name travels).
- Streams via the existing Hermes lane plumbing (SSE map, approval cards render the
  way the Hermes chat lane already renders them — reuse, do not re-implement).
- The approval card for `office_write_cells` should show the op list the same way
  the Quick lane's preview card does — one visual grammar for "the AI wants to
  write cells", two engines behind it.

## 5. Deliberately NOT in v1

- No cross-directory file tools (no read outside data/office — even read-only).
- No formula EVALUATION server-side (openpyxl doesn't compute; the tool result says
  "cached value as of last save by a real engine").
- No autonomous scheduling ("Hands"-style) — separate roadmap item.
- No .docx/.pptx tools until the ONLYOFFICE slice settles what those files are.
- The Quick lane is not deprecated and its tests must not regress.

## 6. Test bar (contract-grade, both sides)

- `office_ops.py` semantics table executed against real workbooks: sort
  merge-refusal, insert shifts merges/leaves formulas, caps asymmetry — asserted
  EQUAL to the page's table (shared fixture or mirrored constants pinned).
- MCP surface: tool list, schema, containment refusals, approval flags — via
  TestClient against the mounted server.
- Conflict rules: dirty-refusal, pre-agent backup existence + content, the banner
  strings.
- Config-gen: the MCP entry lands in Hermes config idempotently; a pin-bump
  reconciliation test in the style of the a2a mirror.
- The page: lane toggle gating, heartbeat registration, external-change banner
  states (executed against stub fetch, per the page's test convention).

## 7. Slicing for the builder

S1 (one builder): `office_ops.py` + MCP server + config-gen + tests.
S2 (same or next builder): panel lane toggle + heartbeat + banner + tests.
Ship each behind the gate; S1 alone is already Debi-testable from Hermes's own chat.
