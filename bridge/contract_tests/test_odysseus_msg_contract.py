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
    if not ODY.exists():
        return
    src = _read(SESS)
    assert '@router.get("/history/{sid}")' in src, (
        "the unpaged GET /api/history/{sid} handler is gone — the paged variant "
        "OMITS metadata._db_id, so the panel's actions would go dark")
    assert '{"history": [msg.to_dict() for msg in session.history]}' in src, (
        "GET /history no longer returns msg.to_dict() over the full in-memory "
        "history (unfiltered + metadata-carrying)")
    m = _read(MODELS)
    assert 'result["metadata"] = self.metadata' in m, (
        "ChatMessage.to_dict no longer emits `metadata` — _db_id and the "
        "server-written metrics would vanish from history")


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
    assert 'ChatMessage(m["role"], m["content"], metadata=m.get("metadata"))' in src, (
        "inject_messages no longer forwards a per-message `metadata` — the direct "
        "lane's per-reply stats stamp (turn_metadata) would be dropped silently")
