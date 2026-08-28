"""ATTACHMENT contract — pin-bump gate for image attach on the Agent + Hermes lanes.

Debi's ruling (2026-08-28): every lane exposes every affordance its backend and the
current model actually support. The ⊕ now rides all three lanes, and TWO of the three
mechanisms are UPSTREAM-INTERNAL surfaces neither project promises to keep:

  AGENT (Odysseus)
    1. POST /api/upload   — multipart field `files` (+ optional `session_id` form
       field), answering {"files":[{"id",…}]}. The id is the whole point.
    2. POST /api/chat_stream — reads a form field `attachments` holding a JSON list
       of those ids.
    3. Its own vision fork: a text-only main model gets a VL DESCRIPTION rather than
       a refusal. That is why our Agent lane has no vision gate, so if the fork
       disappears the gate has to come back.

  HERMES (tui_gateway)
    4. RPC `image.attach_bytes {session_id, content_base64, filename}` — the
       remote-client path that takes a data URL instead of a host path.
    5. …which queues onto session["attached_images"], drained by the NEXT
       prompt.submit. Our ordering (attach → submit) depends on exactly that.

Purely static: greps the vendored sources. Run: pytest bridge/contract_tests/
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ODY = ROOT / "vendor" / "odysseus"
HERMES = ROOT / "vendor" / "hermes"


def _read(p: Path) -> str:
    return p.read_text(errors="replace")


# ── Odysseus ────────────────────────────────────────────────────────────────
def test_odysseus_upload_route_shape():
    if not ODY.exists():
        return
    src = _read(ODY / "routes" / "upload_routes.py")
    assert 'APIRouter(prefix="/api/upload"' in src, (
        "Odysseus moved its upload router off /api/upload — the Agent lane's ⊕ "
        "uploads there before every attached turn")
    assert "files: List[UploadFile] = File(...)" in src, (
        "POST /api/upload no longer takes a multipart `files` list")
    assert "session_id: Optional[str] = Form(None)" in src, (
        "POST /api/upload no longer accepts the session_id form field we scope "
        "uploads with")
    assert 'return {"files": out}' in src, (
        "POST /api/upload no longer answers {'files': [...]} — the bridge reads the "
        "returned id straight out of that list")
    assert '"id": meta["id"]' in src, (
        "an uploaded file no longer reports an `id`, which is the only handle "
        "/api/chat_stream accepts")


def test_odysseus_chat_stream_reads_attachments():
    if not ODY.exists():
        return
    src = _read(ODY / "routes" / "chat_routes.py")
    assert 'attachments = form_data.get("attachments")' in src, (
        "/api/chat_stream no longer reads an `attachments` form field — the Agent "
        "lane's upload ids would be silently ignored, which is the exact failure "
        "shape (an image attached, a turn answered as if it were text) the lane "
        "refuses to ship")
    assert "att_ids = [str(x) for x in json.loads(attachments)]" in src, (
        "/api/chat_stream no longer parses `attachments` as a JSON list of ids")


def test_odysseus_still_describes_images_for_text_only_models():
    """The Agent lane has NO vision gate, and this is why."""
    if not ODY.exists():
        return
    src = _read(ODY / "src" / "chat_handler.py")
    assert "main_is_vision" in src and "model_supports_vision" in src, (
        "Odysseus no longer forks on the main model's vision capability")
    assert "analyze_image_with_vl_result" in src, (
        "Odysseus no longer describes an attached image with its VL model for a "
        "text-only main model — if that fork is gone, the Agent lane's ⊕ needs the "
        "same vision gate the direct lane has (bridge/routers/odychat.py)")


def test_odysseus_persists_multimodal_turns_as_parts():
    """Why the bridge flattens history (flatten_ody_content)."""
    if not ODY.exists():
        return
    src = _read(ODY / "src" / "document_processor.py")
    assert '"type": "image_url"' in src and "data:image/" in src, (
        "document_processor no longer builds inline image_url parts — re-check "
        "flatten_ody_content, which exists because that LIST reaches our readers")
    helpers = _read(ODY / "routes" / "chat_helpers.py")
    assert 'ChatMessage("user", preprocessed.user_content' in helpers, (
        "the user turn is no longer persisted as preprocess's user_content — the "
        "parts-vs-string shape our flattener normalises may have moved")
    assert '{"attachments": preprocessed.attachment_meta}' in helpers, (
        "a user message no longer carries metadata.attachments — that is the ONLY "
        "way a reopened Agent-lane turn finds its image again "
        "(ody_attachment_handles)")


# ── Hermes ──────────────────────────────────────────────────────────────────
def test_hermes_image_attach_bytes_rpc():
    if not HERMES.exists():
        return
    src = _read(HERMES / "tui_gateway" / "methods_prompt.py")
    assert '@method("image.attach_bytes")' in src, (
        "the Hermes gateway lost image.attach_bytes — the panel has no host PATH to "
        "give image.attach, so the lane's ⊕ has no other door")
    i = src.index('@method("image.attach_bytes")')
    body = src[i:i + 4000]
    assert 'params.get("content_base64")' in body, (
        "image.attach_bytes no longer reads `content_base64`")
    assert 'params.get("filename"' in body, (
        "image.attach_bytes no longer reads `filename` — it is how the gateway "
        "sniffs the extension when the magic bytes are ambiguous")
    assert 'mime_prefix="image/"' in body, (
        "image.attach_bytes stopped accepting a `data:image/...;base64,` prefix — "
        "the panel sends the data URL verbatim")
    assert '"attached": True' in body, (
        "image.attach_bytes no longer answers `attached` — the bridge treats a "
        "missing/false one as a refusal and fails the turn")
    assert "_queue_attached_image(session" in body, (
        "image.attach_bytes no longer queues onto the SESSION — our attach→submit "
        "ordering depends on the next prompt.submit draining it")


def test_hermes_prompt_submit_still_drains_attached_images():
    if not HERMES.exists():
        return
    src = _read(HERMES / "tui_gateway" / "server.py")
    assert 'images = list(session.get("attached_images", []))' in src, (
        "prompt.submit no longer drains session['attached_images'] — an attached "
        "image would be queued and never sent")
    assert "_enrich_with_attached_images" in src and "build_native_content_parts" in src, (
        "Hermes lost one of its two image routes (native parts / vision "
        "description) — the lane's no-vision-gate stance rests on both existing")
