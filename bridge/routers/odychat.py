"""ROUTER — POST /api/ody/chat, the Odysseus streaming relay."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import StreamingResponse
from ..core.analytics import _log_ody_metrics
from ..core.appctx import app
from ..core.chatattachments import decode_chat_file
from .ody import _ody, _ody_login, _ody_req, ody_vision_prepare
from .sampling import IMAGE_MAX_CHARS
from .sidecars import parse_data_url


# ── AGENT-LANE IMAGE ATTACH (2026-08-28, the capability-affordance audit) ────
# The ⊕ used to exist on the Chat lane ONLY, and the reason was legacy accident,
# not capability: Odysseus's own chat surface has taken images since forever, via
# a TWO-STEP shape we now speak here —
#   (1) POST /api/upload  (multipart `files`, optional `session_id`)
#       → {"files":[{"id","name","mime",…}]}          routes/upload_routes.py:257
#   (2) POST /api/chat_stream with form field `attachments` = JSON list of ids
#                                                            routes/chat_routes.py:1299
# Downstream, Odysseus resolves each id and (src/chat_handler.preprocess_message)
# either hands the pixels to a vision main model as OpenAI parts OR describes the
# image with its own VL model for a text-only one. So this lane is LESS gated than
# the direct lane, not more — which is exactly why hiding the button was a lie.
#
# The upload is a HARD gate on the turn: an image the user attached and the backend
# refused must never be silently dropped and the turn answered as if it were a plain
# text message (a LIE-TO-USER outranks a refusal). It fails the turn with the reason.
ODY_ATTACH_UPLOAD = "/api/upload"


def ody_attach_error(image) -> str:
    """PURE: why this attachment cannot ride the Agent lane, or "" when it can.

    Deliberately the SAME vocabulary as the direct lane's build_user_content
    (bridge/routers/sampling.py) MINUS the vision clause — Odysseus itself decides
    pixels-vs-description, so "this model can't see" is not a refusal on this lane.
    """
    if not image:
        return ""
    if not isinstance(image, str) or not image.startswith("data:image/"):
        return "attachment is not an image data URL — attach removed"
    if len(image) > IMAGE_MAX_CHARS:
        return "image too large — attach removed"
    return ""


async def agent_events(body: dict):
    """Produce upstream Agent SSE frames independently of a browser response."""
    image = body.get("image") or ""
    image_name = (body.get("image_name") or "")[:200]
    chat_file, file_error = decode_chat_file(
        body.get("file") or "", body.get("file_name") or "",
        body.get("file_mime") or "")
    fields = {
        "session": body.get("session", ""),
        "message": body.get("message", ""),
        "mode": body.get("mode", "agent"),
        "allow_web_search": "true" if body.get("allow_web_search", True) else "false",
        "allow_bash": "true" if body.get("allow_bash", False) else "false",
    }

    async def gen():
        import json as _json
        tail = ""   # rolling tail of the stream, for best-effort metrics logging
        if image or body.get("file"):
            # Upload FIRST: no part of this turn starts until we know the attachment
            # landed. Every failure ends the turn with its own reason.  Images keep
            # the vision-preparation path; documents ride Odysseus's native upload
            # contract and are processed by its document handler.
            err = "attach one file at a time" if image and body.get("file") else file_error
            is_image = bool(image)
            if is_image:
                err = err or ody_attach_error(image)
                mime, raw = (None, None) if err else parse_data_url(image, IMAGE_MAX_CHARS)
                upload_name = image_name or "image"
                if not err and not raw:
                    err = "that image could not be decoded — attach removed"
            else:
                mime = chat_file.get("mime") if chat_file else None
                raw = chat_file.get("raw") if chat_file else None
                upload_name = chat_file.get("name") if chat_file else "file"
            if not err:
                try:
                    r = await _ody_req(
                        "POST", ODY_ATTACH_UPLOAD,
                        files={"files": (upload_name, raw,
                                         mime or "application/octet-stream")},
                        data={"session_id": fields["session"]})
                    if r.status_code != 200:
                        err = (f"Odysseus refused the attachment ({r.status_code}) — "
                               f"{r.text[:160]}")
                    else:
                        ids = [str(f.get("id")) for f in (r.json().get("files") or [])
                               if f.get("id")]
                        if not ids:
                            err = "Odysseus stored no attachment id — attach removed"
                        else:
                            fields["attachments"] = _json.dumps(ids)
                            # ── VISION PREP (v1.5.32) ───────────────────────
                            # Odysseus would otherwise decide this model cannot
                            # see BY NAME and replace the picture with
                            # "[No vision model configured…]". We pre-caption it
                            # with the loaded, registry-verified vision model and
                            # hand the text to Odysseus's own vision cache, then
                            # auto-wire `vision_model` as the fallback. Both are
                            # best-effort: NOTHING here may fail the turn — the
                            # image already landed, and the user's picture is
                            # never lost because a preparation step went wrong.
                            # ⚠️ ITS OWN try: a raise in here would otherwise be
                            # caught by the UPLOAD handler below and reported as
                            # "attachment upload failed" — blaming the transport
                            # for a preparation step AND failing a turn whose
                            # image already landed.
                            if is_image:
                                try:
                                    vis = await ody_vision_prepare(
                                        ids[0], raw, mime or "", upload_name)
                                except Exception as ve:          # noqa: BLE001
                                    vis = {"source": "none", "model": "",
                                           "note": f"vision prep failed: {str(ve)[:140]}"}
                                # Tell the panel HOW the model got at this image, so a
                                # described answer can never wear the clothes of a
                                # seen one (the LIES-TO-USER rule, requirement 4).
                                yield ("data: " + _json.dumps(
                                    {"type": "vision", "source": vis.get("source"),
                                     "model": vis.get("model"),
                                     "note": vis.get("note")}) + "\n\n")
                except Exception as e:
                    err = f"Odysseus attachment upload failed: {str(e)[:160]}"
            if err:
                yield f'data: {_json.dumps({"type": "proxy_error", "error": err})}\n\n'
                yield "data: [DONE]\n\n"
                return
        try:
            async with _ody.stream("POST", "/api/chat_stream", data=fields,
                                   headers={"X-Tz-Offset": str(body.get("tz_offset", 0))}) as r:
                if r.status_code in (401, 403):
                    await _ody_login()
                    yield 'data: {"type":"retry"}\n\n'
                    async with _ody.stream("POST", "/api/chat_stream", data=fields) as r2:
                        async for chunk in r2.aiter_raw():
                            yield chunk
                            tail = (tail + chunk.decode("utf-8", "ignore"))[-16000:]
                    return
                async for chunk in r.aiter_raw():
                    yield chunk
                    tail = (tail + chunk.decode("utf-8", "ignore"))[-16000:]
        except Exception as e:
            # SERIALIZED, NOT INTERPOLATED — same fix as chat.py's sibling frame
            # (S33/F1): a quote or backslash inside the exception text used to emit
            # an unparseable SSE frame precisely while reporting a failure.
            yield ("data: " + _json.dumps({
                "type": "proxy_error",
                "error": f"the agent lane lost its connection to Odysseus: "
                         f"{str(e)[:200]}"}) + "\n\n")
            yield "data: [DONE]\n\n"
        finally:
            _log_ody_metrics(tail, fields.get("mode", "agent"))

    return gen()


@app.post("/api/ody/chat")
async def ody_chat(req: Request) -> StreamingResponse:
    """Historical Agent SSE endpoint; panel resilience lives at /api/turns."""
    return StreamingResponse(await agent_events(await req.json()),
                             media_type="text/event-stream")
