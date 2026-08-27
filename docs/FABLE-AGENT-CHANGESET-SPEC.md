# FABLE SPEC — Agent lane v2: one intention, one card (2026-08-27)

**Status:** ruled after deep research (two reports: docs/research/2026-08-27-agent-consent-
incident.md holds the evidence; the commercial-UX and OSS-architecture reports are in the
session transcript and summarized here). **Supersedes** the write-consent half of
FABLE-LOFFICE-HERMES-TOOLS-SPEC.md; the read tools, containment, and panel lane survive.

## 0. What the research settled

- Industry convergence (Copilot Excel, Gemini Docs/Sheets, Cursor/Claude Code, Claude for
  Excel, Univer's agent skills): **stage everything, consent once per intention, apply
  atomically, prove it in the document surface, back it with a checkpoint.** Nobody ships
  one modal per write.
- Hermes (vendored, verified at file:line): the MCP trust gate is per-call with NO memory
  (`request_elicitation_consent` maps "session"/"always" to a bare accept and records
  nothing) and its card CANNOT show tool arguments (message built from tool/server name
  literals only). Its checkpoint system never fires for MCP tools. Fighting this per-call
  gate is the wrong move; restructuring OUR tool surface makes it irrelevant.
- MCP has no transaction primitive; the sanctioned pattern is coarse server-side changeset
  tools. We author the server.

## 1. The ruling — staging tools, human-only apply

The MCP write tools STOP WRITING. New surface (bridge/office_mcp.py + office_ops.py):

- Reads unchanged: `office_list`, `office_read`, `office_sheet_stats` (readOnlyHint: true).
- **`office_stage_changes(file, ops[])`** — validates ops (same grammar + caps as today:
  set/style/sort/insert/delete_rc, plus `create_workbook` and `add_sheet` absorbed from the
  retired office_create), computes BEFORE values for every touched cell from the file, and
  appends to the ONE pending changeset for that workbook (session-scoped, bridge-held,
  TTL ~10 min, replaced not accumulated on a new user request — keyed by Hermes session +
  file). Returns: `{staged: true, changeset_id, op_count, preview: [...before→after...],
  applied: false}` and the sentence "NOT applied — Debi reviews and applies this in
  LOffice." It is annotated `readOnlyHint: true`, and that is HONEST: it never touches a
  workbook; it records a proposal the bridge holds. ⇒ **zero Hermes approval cards, ever,
  on this lane.** The consent moves to a surface that can actually show the change.
- `office_write_cells` / `office_sort` / `office_insert_delete` / `office_create` are
  REMOVED from the catalog (S1 is a day old; tests updated, not appeased).
- **Apply is a human gesture only.** No MCP tool can apply a changeset. The bridge exposes
  `POST /api/office/changeset/{id}/apply` and `/dismiss` for the PANEL.

## 2. The card (LOffice AI panel) — the Quick lane's grammar, exactly

When a turn ends with a pending changeset, the panel renders ONE card (same visual grammar
as Quick's preview card): summary line, the exact op list with before → after, per-op count
caps already enforced, **Apply / Dismiss**. Apply → the bridge applies atomically through
office_ops (all-or-nothing), returns a RECEIPT `{changeset_id, applied_at, cells_written,
verify: re-read of touched ranges}`, and the editor reloads the document (existing
ooExtReload path). Dismiss → bridge drops it.

**The model never gets to say "Done":**
- The panel appends a harness-authored status line under every agent reply that staged
  something: "⏳ staged — nothing is written until you press Apply." Narration never
  stands alone.
- A success badge renders ONLY from a receipt in an actual apply response — never from
  model text.
- After Apply or Dismiss, the bridge injects one system line into the Hermes session
  ("changeset <id> was applied by the user — receipt <hash>" / "…was DISMISSED — it was
  never applied; do not claim otherwise"), so the next turn cannot hallucinate state.
- Tool results that are errors/refusals render as first-class ✗ chips in the panel
  (red, with the tool's own sentence) — this closes the silent-failure gap everywhere,
  not just for writes.

## 3. Checkpoints (the undo that makes one-click consent responsible)

- On every APPLY: the pre-apply workbook is copied to the checkpoint stack
  `data/office/.checkpoints/<stem>/<changeset_id>.xlsx` (keep last 10 per workbook,
  prune oldest). `<stem>.pre-agent.xlsx` remains as the most-recent-apply convenience
  copy (existing name, existing visibility ruling).
- The applied card gains **"Undo this change"** → restores that checkpoint (mtime fence:
  refuse with the honest sentence if the file changed since apply), editor reloads.
- Daily `.bak` stays as the outer ring. Hermes's own checkpointing is NOT extended
  (vendor untouched); the bridge owns spreadsheet snapshots.

## 4. Grounding update (small)

The agent preamble's tool section teaches the new shape: read → compute → stage ONCE with
the complete op list for the whole request → tell the user what was staged and STOP.
Explicitly: "you cannot apply changes; do not claim a change was made unless a system line
confirms it was applied."

## 5. Deliberately not in v2

- No Hermes vendor patches (args-on-card / session grain) — unnecessary once no office
  tool is write-capable; revisit only if a future lane needs Hermes-carded writes.
- No editor-side pending-highlight render (Univer-style visual staging) — phase 3; the
  card's before→after list is the v2 review surface.
- No auto-apply/trusted-session mode until the checkpoint stack has soaked (Cursor's
  lesson: auto-apply is only responsible on top of proven rollback).
- Quick lane unchanged (already changeset-shaped; applies via editor API with editor undo).

## 6. Test bar

office_mcp/office_ops: staging returns before-values and never touches the file (mtime
asserted unchanged); catalog holds exactly 4 tools, all readOnlyHint; apply is atomic +
receipt verifies by re-read; dismiss drops; TTL expiry; checkpoint stack push/prune/restore
+ mtime fence; the session system-line on both outcomes. Panel (test_office_ai.js):
card renders from a staged changeset, Apply posts and renders the receipt badge, Dismiss
posts, the harness status line always accompanies staging turns, ✗ chips on isError
results, no page-side writers added (fence intact). Live proof in the real page with the
27B model: one intention ("add a Purchases row of 200 and update the total") → ONE card →
Apply → sheet shows it → receipt badge → "Undo this change" restores.
