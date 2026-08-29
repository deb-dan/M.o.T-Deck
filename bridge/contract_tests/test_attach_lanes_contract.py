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


def test_odysseus_vision_cache_is_the_precaption_seam():
    """v1.5.32 — the PRIMARY Agent-lane vision path is a pre-caption written into
    Odysseus's own vision cache. Four upstream facts carry it, and every one of
    them is an internal detail upstream never promised."""
    if not ODY.exists():
        return
    up = _read(ODY / "routes" / "upload_routes.py")
    assert '@router.put("/{file_id}/vision")' in up, (
        "PUT /api/upload/{id}/vision is gone — that is where the bridge stores the "
        "description it produced with OUR runner (bridge/routers/ody.py "
        "ody_vision_prepare); without it the Agent lane goes blind again")
    assert "_vision_cache_path(file_id)" in up, (
        "the vision text is no longer written to the per-upload cache file the chat "
        "send reads")
    ch = _read(ODY / "src" / "chat_handler.py")
    assert 'os.path.join(UPLOAD_DIR, ".vision", att_id + ".txt")' in ch, (
        "chat_handler no longer reads UPLOAD_DIR/.vision/<id>.txt before calling its "
        "own VL model — that short-circuit is the whole reason the pre-caption works")
    assert 'not cached_desc.startswith("[")' in ch, (
        "the '[' rule is gone: Odysseus DISCARDS a cached description that starts "
        "with '[' (its own error markers). ody_vision_provenance is written never to "
        "start with one — if the rule changed, re-check that comment")
    dp = _read(ODY / "src" / "document_processor.py")
    assert "timeout=120" in dp, (
        "Odysseus's VL call is no longer hard-capped at 120s. THAT CAP IS WHY WE "
        "PRE-CAPTION: driven 2026-08-28, the loaded 27B thinking model needed 173s "
        "for the same image and the turn died with '[VL model unavailable]'. If the "
        "cap is now configurable, the simple vision_model wire may finally suffice")
    assert 'settings.get("vision_model", "")' in dp, (
        "`vision_model` is no longer the setting that names Odysseus's VL model — "
        "the bridge's evidence-gated auto-wire writes exactly that key")


def test_odysseus_folds_our_caption_in_verbatim_so_the_trust_fence_survives():
    """U47 / S33-F2 — THE VENDOR SEAM, PINNED.

    The trust fence around transcribed image text cannot live in Odysseus's code
    (zero vendored bytes), so it lives INSIDE the caption string we write into its
    vision cache (bridge/routers/ody.py::ody_vision_provenance). That only works
    while upstream folds the cached text into the prompt WHOLE — no truncation, no
    first-line-only, no re-summarisation. Both branches are pinned:

      • text-only main model: `enhanced_message = f"…[Image: {name}]\n{vl_desc}"`
      • NAME-RECOGNISED vision model: the cached text is folded in under
        "[User-corrected caption / OCR for this image — treat as authoritative]".
        That authority stamp is upstream's and we cannot remove it — which is
        exactly why our own string carries the sentence that answers it. If upstream
        ever stops interpolating the cached text verbatim, the fence is gone and the
        U47 row must reopen.
    """
    if not ODY.exists():
        return
    ch = _read(ODY / "src" / "chat_handler.py")
    assert '"\n{vl_desc}"' in ch or "{vl_desc}" in ch, (
        "chat_handler no longer interpolates the cached/VL description into the "
        "prompt verbatim — the U47 trust fence travels INSIDE that string, so a "
        "truncating or reformatting upstream silently strips it")
    assert "treat as authoritative]" in ch and "{_vtext}" in ch, (
        "the 'User-corrected caption … treat as authoritative' fold is gone or "
        "reshaped. Our fence sentence is written to answer that exact stamp "
        "(ody.py's ODY_VISION_TRUST); re-read it if upstream changed the wording")
    # And OUR half of the seam, in the same test, so the pair cannot drift apart.
    ours = _read(ROOT / "bridge" / "routers" / "ody.py")
    assert "ODY_VISION_FENCE" in ours and "ODY_VISION_TRUST" in ours, (
        "the trust fence constants are gone from ody.py — U47's closure depends on "
        "them being part of the cached caption itself")
    assert "authoritative" in ours, (
        "ody.py's trust sentence no longer mentions the upstream authority stamp it "
        "exists to answer")


def test_odysseus_name_keyword_vision_test_still_exists():
    """We MIRROR Odysseus's name test (ody_name_looks_vision) so we only step in
    where it misses. If upstream starts reading real capability, stop mirroring."""
    if not ODY.exists():
        return
    src = _read(ODY / "src" / "chat_helpers.py")
    assert "_VISION_MODEL_KEYWORDS" in src and "def is_vision_model" in src, (
        "Odysseus no longer classifies vision BY NAME — re-read "
        "ody_name_looks_vision in bridge/routers/ody.py, which exists only to "
        "predict that keyword match")
    for kw in ('"gemma-3"', '"llama-4"', '"phi-4"'):
        assert kw in src, (
            f"the vision keyword {kw} left Odysseus's list — our mirrored copy "
            "(ODY_NAME_VISION_KEYWORDS) is now wrong in the direction that makes us "
            "SKIP a model Odysseus can no longer see with")
    assert r"(?<![a-z])vl(?![a-z])|vlm" in src, (
        "the standalone-'vl' regex changed — ODY_NAME_VISION_RE mirrors it verbatim")


def test_odysseus_settings_still_carries_the_vision_keys():
    """The fallback path (A) writes ONE key through Odysseus's own settings API."""
    if not ODY.exists():
        return
    src = _read(ODY / "src" / "settings.py")
    assert '"vision_model"' in src and '"vision_enabled"' in src, (
        "vision_model / vision_enabled left Odysseus's settings — the bridge's "
        "auto-wire writes the first and refuses to caption when the second is off")


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


# ── The VISION SHIM (v1.5.33) ───────────────────────────────────────────────
# An image uploaded in ODYSSEUS'S OWN TAB never touches our panel, so the v1.5.32
# pre-caption cannot reach it. Instead the bridge registers an OpenAI-compatible
# endpoint of its own (bridge/routers/odyvision.py) and points Odysseus's
# `vision_model` at it, so ODYSSEUS'S OWN VL call becomes the fast one: measured
# 2026-08-29 on the loaded Qwen3.6-27B — 65.1s/849 tokens through the stock path,
# 4.2s through the shim, same model, same picture. Five upstream mechanics carry
# that, and each is an internal detail upstream never promised.
def test_odysseus_resolves_vision_model_through_its_endpoint_rows():
    """`vision_model` → (url, model, headers) via the ModelEndpoint table, with the
    `model@endpoint` form selecting one endpoint BY NAME. Both halves are ours."""
    if not ODY.exists():
        return
    ai = _read(ODY / "src" / "ai_interaction.py")
    assert "def _resolve_model(" in ai, (
        "_resolve_model is gone — it is what turns our `vision_model` string into a "
        "call to the shim (bridge/routers/odyvision.py)")
    assert 'model_name, target_endpoint_name = spec.rsplit("@", 1)' in ai, (
        "the `model@endpoint` spec form is gone — ody_shim_spec() writes exactly "
        "that so resolution is deterministic and no other endpoint is probed")
    assert "ModelEndpoint.name.ilike(f\"%{target_endpoint_name}%\")" in ai, (
        "the endpoint half of the spec no longer matches by display NAME — "
        "ody_vision_shim_ensure re-reads the row's name and re-specs vision_model "
        "to whatever the user renamed it to, which only works while this holds")
    mr = _read(ODY / "routes" / "model_routes.py")
    assert '@router.post("/model-endpoints")' in mr, (
        "POST /api/model-endpoints is gone — that is how the bridge registers the "
        "image-describer endpoint (admin session, form fields)")
    assert '@router.delete("/model-endpoints/{ep_id}")' in mr, (
        "DELETE /api/model-endpoints/{id} is gone — ody_shim_stale_rows cleans up "
        "our OWN leftover row after a bridge port/path change with it")


def test_odysseus_url_classification_still_traps_api_and_v1_paths():
    """⚠️ THE TRAP THAT BROKE THE FIRST DRIVE OF THIS SLICE, PINNED.

    Odysseus decides a LOOPBACK endpoint's protocol from its PATH: anything under
    "/api/…" is native Ollama (so it probes /api/tags and never /models), and
    anything under "/v1…" is Ollama's OpenAI-compat surface (so it also pokes
    /slots). The shim therefore lives at /odyvision/v1 — outside the bridge's usual
    /api namespace — and that choice is only correct while these two hold."""
    if not ODY.exists():
        return
    src = _read(ODY / "src" / "llm_core.py")
    assert 'path.startswith("/api/")' in src and "def _is_ollama_native_url" in src, (
        "_is_ollama_native_url changed. If '/api/…' is no longer read as Ollama, the "
        "shim may move back under /api/ody/; if the rule got BROADER, re-check that "
        "/odyvision/v1 is still classified as a plain OpenAI endpoint")
    assert 'if path.startswith("/v1"):\n        return False' in src, (
        "the /v1 escape hatch in _is_ollama_native_url is gone")
    assert "def _is_ollama_openai_compat_url" in src and 'path.startswith("/v1/")' in src, (
        "_is_ollama_openai_compat_url changed — it is why the shim's base does NOT "
        "start with /v1 either")


def test_odysseus_derives_our_two_shim_urls_from_the_base():
    """The shim serves exactly <base>/models and <base>/chat/completions because
    that is what Odysseus builds from a path-carrying base."""
    if not ODY.exists():
        return
    src = _read(ODY / "src" / "endpoint_resolver.py")
    assert 'return _append_endpoint_path(base, "/chat/completions")' in src, (
        "build_chat_url no longer appends /chat/completions to a generic base")
    assert 'return _append_endpoint_path(base, "/models")' in src, (
        "build_models_url no longer appends /models to a path-carrying base — the "
        "shim's GET route would then be at the wrong address")
    assert "if not parsed.path and uses_v1_models_by_default:" in src, (
        "the 'only invent /v1 for an EMPTY path' rule changed — the shim's base "
        "ends in /v1 precisely because of it")


def test_odysseus_vl_call_still_blocks_its_event_loop():
    """WHY THE SHIM NEVER CALLS ODYSSEUS BACK. The VL call is synchronous and is
    made straight from an async handler — no asyncio.to_thread — so Odysseus's
    whole event loop is frozen while it waits for us. A request from the shim back
    to :7860 mid-call would deadlock until its own 120s timeout, which is why
    everything the shim needs is snapshotted by ody_vision_shim_ensure instead."""
    if not ODY.exists():
        return
    src = _read(ODY / "src" / "chat_handler.py")
    assert "vl_result = analyze_image_with_vl_result(file_info[\"path\"], owner=owner)" in src, (
        "the VL call moved. If it is now on a thread (asyncio.to_thread) the "
        "deadlock hazard is gone and routers/odyvision.py may read Odysseus's "
        "settings live instead of from _SHIM_STATE")


def test_odysseus_vl_failure_text_is_still_its_own_bracket_marker():
    """Our shim answers a failure the same way upstream does — a leading '[' — so
    Odysseus shows it and (chat_handler's rule) never caches it."""
    if not ODY.exists():
        return
    src = _read(ODY / "src" / "document_processor.py")
    assert '"[VL model unavailable - image not analyzed]"' in src, (
        "upstream's own VL failure marker changed — ody_shim_failure() deliberately "
        "speaks the same idiom")
    assert '"[No vision model configured — set one in Settings → Vision]"' in src, (
        "the unconfigured-vision marker changed — that literal string is what the "
        "tab journey produced before this slice, and what it must never produce "
        "again while a vision-capable model is loaded")
    assert "resolve_vision_fallback_candidates" in src, (
        "the vision FALLBACK chain is gone — ody_shim_failure returns an HTTP error "
        "instead of a 200 marker precisely so a user's configured fallback still "
        "gets its turn")
