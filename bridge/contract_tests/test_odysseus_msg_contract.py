"""Odysseus per-message API contract — pin-bump gate for the message-actions slice.

The panel's Copy/Edit/Delete/Fork chips and the per-reply stats stamp ride four
upstream seams that Odysseus does NOT promise to keep:

  1. POST /api/session/{sid}/delete-messages  {msg_ids: [...]}
  2. POST /api/session/{sid}/edit-message     {msg_id, content}
  3. POST /api/session/{sid}/fork             {keep_count} → {id, name, kept}
  4. GET  /api/history/{sid} — the UNPAGED session_routes handler, returning
     msg.to_dict() (which carries `metadata`, incl. the `_db_id` the actions key
     off and the server-written metrics the stamp renders)
  5. POST /api/session/{sid}/inject_messages accepting a PER-MESSAGE `metadata`
     (how the direct lane persists its own stats)

Purely static: greps the vendored source. Run: pytest bridge/contract_tests/
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# ⚠️ THE APP LAYER IS NO LONGER ONE FILE (router/core split, 2026-08-28).
# bridge/app.py is a FACADE over bridge/core/*.py + bridge/routers/*.py, so the
# source-text assertions below read bridge/appsrc.py's assembled view of the whole
# app layer instead of one file. Read bridge/appsrc.py's header for why the
# assertions are source-text in the first place and why order is part of it.
import sys as _sys                                          # noqa: E402
_sys.path.insert(0, str(ROOT))                              # noqa: E402
from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402
ODY = ROOT / "vendor" / "odysseus"
HIST = ODY / "routes" / "history" / "history_routes.py"
SESS = ODY / "routes" / "session_routes.py"
MODELS = ODY / "core" / "models.py"


def _read(p: Path) -> str:
    return p.read_text(errors="replace")


def test_per_message_routes_still_exist():
    if not ODY.exists():
        return  # submodule not checked out — nothing to gate
    src = _read(HIST)
    for route in ('@router.post("/api/session/{session_id}/delete-messages")',
                  '@router.post("/api/session/{session_id}/edit-message")',
                  '@router.post("/api/session/{session_id}/fork")'):
        assert route in src, (
            f"Odysseus no longer mounts {route} — the panel's per-message "
            "actions (bridge /api/ody/session/*/msg-delete|msg-edit|fork-from) "
            "need rewiring")


def test_delete_messages_payload_shape():
    if not ODY.exists():
        return
    src = _read(HIST)
    assert 'body.get("msg_ids", [])' in src, (
        "delete-messages no longer reads {msg_ids: [...]} — the bridge sends "
        "exactly that key")
    # deletion is BY DB ID (our msg ids), not by positional index
    assert "DbChatMessage.id == mid" in src, (
        "delete-messages no longer matches messages by db id")
    assert "'_db_id'" in src or '"_db_id"' in src, (
        "delete-messages no longer prunes in-memory history by _db_id")


def test_edit_message_payload_shape():
    if not ODY.exists():
        return
    src = _read(HIST)
    assert 'body.get("msg_id")' in src and 'body.get("content")' in src, (
        "edit-message no longer reads {msg_id, content}")
    assert "meta['edited'] = True" in src or 'meta["edited"] = True' in src, (
        "edit-message no longer stamps metadata.edited — the panel renders that "
        "as its 'edited' mark")
    # content-only by design: the panel's tooltip promises no model re-run, so a
    # future upstream that ALSO truncates/resends would change the semantics.
    assert "truncate" not in src.split('/edit-message")')[1].split("@router")[0], (
        "edit-message now touches truncation — its content-only semantics "
        "(matching LM Studio) no longer hold")


def test_fork_keep_count_semantics():
    if not ODY.exists():
        return
    src = _read(HIST)
    body = src.split('/fork")')[1].split("@router")[0]
    assert 'body.get("keep_count", 0)' in body, (
        "fork no longer reads {keep_count} — fork_keep_count() computes exactly this")
    assert "source.history[:keep_count]" in body, (
        "fork's keep_count is no longer a PREFIX slice of the UNFILTERED in-memory "
        "history — fork_keep_count()'s index+1 arithmetic depends on it")
    assert '"id": new_id' in body and '"kept"' in body, (
        "fork no longer returns {id, kept} — the panel selects the new session by id")


def test_unpaged_history_returns_metadata():
    """The UNPAGED GET /api/history/{sid} must still carry per-message `metadata`.

    ⚠️ Rewritten at the 2026-08-28 bump (dev@25c9e735 → dev@c9dd68d). Until c9dd68d
    there were TWO handlers for this path: a duplicate in routes/session_routes.py
    (`/history/{sid}`, returning `msg.to_dict()` unfiltered) and the canonical one in
    routes/history/history_routes.py. session_routes was mounted FIRST, so the
    duplicate is the one that actually served us. Upstream deleted the duplicate, so
    the canonical handler now serves the seam — which is what this test's own previous
    docstring said to pin at the bump, so that is what it pins now:

      · the canonical `GET /api/history/{session_id}` exists,
      · `limit is None` takes the in-memory session_manager branch (NOT the paged,
        100-row-capped DB branch — see test_bridge_never_pages_history), and
      · that branch still emits `metadata` per entry, so `_db_id` survives.

    KNOWN behaviour delta accepted at this bump (both benign for us):
      · the canonical branch DROPS messages with `metadata.hidden` (compaction
        summaries) — the deleted duplicate returned them, and Odysseus's own UI
        hides them anyway;
      · it collapses multimodal content to text via `_history_display_content`,
        which is already what bridge/app.py assumes (it re-attaches images from its
        OWN attachment sidecar, see `attach_images`).
    """
    if not ODY.exists():
        return
    h = _read(HIST)
    assert '@router.get("/api/history/{session_id}")' in h, (
        "the canonical GET /api/history/{session_id} handler is gone — the panel's "
        "whole transcript load rides it")
    # The unpaged branch must be the in-memory one, and must forward metadata.
    body = h.split('@router.get("/api/history/{session_id}")')[1].split("@router")[0]
    assert "if limit is not None:" in body, (
        "the unpaged/paged split on `limit` is gone — the bridge deliberately never "
        "sends limit/offset because the paged branch caps at 100 rows")
    unpaged = body.split("if limit is not None:")[1].split("session_manager.get_session")[1]
    assert 'entry["metadata"]' in unpaged, (
        "the unpaged branch no longer emits per-message `metadata` — _db_id and the "
        "server-written metrics would vanish and the panel's Copy/Edit/Delete/Fork "
        "chips would go dark")
    # The old duplicate must not silently come back and shadow the canonical handler.
    assert '@router.get("/history/{sid}")' not in _read(SESS), (
        "routes/session_routes.py mounts a SECOND /history/{sid} handler again. It is "
        "included BEFORE history_routes in app.py, so it would shadow the canonical "
        "one — re-verify which shape actually serves us before trusting this suite")
    m = _read(MODELS)
    assert 'result["metadata"] = self.metadata' in m, (
        "ChatMessage.to_dict no longer emits `metadata` — _db_id and the "
        "server-written metrics would vanish from history")


def test_bridge_never_pages_history():
    """OUR CLIENT must never send limit/offset to GET /api/history/{sid}.

    Two independent reasons, both load-bearing, and the second one is NEW:

      1. (original) The unpaged handler is the one that emits full `metadata`,
         including the `_db_id` every per-message action keys off. A paged
         variant historically omitted it — pass a page param and the panel's
         Copy/Edit/Delete/Fork chips go dark.
      2. (2026-08-14 update sweep, upstream #5929 `fix(history): defer full
         transcript hydration to model sends`) On Odysseus **dev** the canonical
         handler gained optional `limit`/`offset`, and **the paged branch is
         CAPPED AT 100 ROWS**. So the never-page rule is now also the only thing
         standing between us and a SILENTLY TRUNCATED transcript — a failure that
         looks like data loss, not like an error.

    This asserts the invariant on the side we control (bridge/app.py), which
    holds at the CURRENT pin (where the params may not exist yet) and at any
    future one. ⚠️ At the Odysseus bump, ADD the upstream half: pin that
    `limit is None` takes the metadata-preserving in-memory branch in
    routes/history/history_routes.py — that is the actual upstream invariant.
    """
    src = _APP_SOURCE
    calls = [ln.strip() for ln in src.splitlines()
             if "/api/history/" in ln and "_ody_req" in ln]
    assert calls, (
        "no GET /api/history/{sid} call found in bridge/app.py — this test can "
        "no longer see the seam it guards; re-point it at the new call site")
    for ln in calls:
        for bad in ("limit", "offset", "params", "?"):
            assert bad not in ln, (
                f"bridge/app.py pages GET /api/history: {ln!r}\n"
                "Odysseus's paged branch CAPS AT 100 ROWS and drops "
                "metadata._db_id — transcripts would silently truncate and the "
                "per-message actions would go dark. Never pass limit/offset.")


def test_db_id_is_stamped_on_persisted_messages():
    if not ODY.exists():
        return
    sm = _read(ODY / "core" / "session_manager.py")
    assert "_db_id" in sm, (
        "session_manager no longer stamps metadata._db_id on messages — every "
        "per-message action keys off that id")


def test_inject_messages_accepts_per_message_metadata():
    if not ODY.exists():
        return
    src = _read(SESS)
    assert '@router.post("/session/{sid}/inject_messages")' in src, (
        "inject_messages is gone — the direct lane persists through it")
    assert 'metadata=' in src and 'm.get("metadata")' in src, (
        "inject_messages no longer forwards a per-message `metadata` — the direct "
        "lane's per-reply stats stamp (turn_metadata) would be dropped silently")
    if "sanitize_client_message_metadata" in src:
        # Newer Odysseus correctly strips only server-owned tool-approval authority.
        # Prove the sanitizer leaves every stats key MOT Deck writes; accepting the
        # new function name without executing its predicate would make this gate lie.
        import runpy
        sanitizer = runpy.run_path(
            str(ODY / "src" / "tool_approval_scopes.py")
        )["sanitize_client_message_metadata"]
        metadata = {
            "model": "served-model",
            "tokens_per_second": 42.5,
            "response_time": 1.25,
            "input_tokens": 8,
            "output_tokens": 21,
        }
        assert sanitizer(metadata) == metadata, (
            "Odysseus's client-metadata sanitizer now removes Direct-turn stats")
