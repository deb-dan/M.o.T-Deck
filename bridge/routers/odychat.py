"""ROUTER — POST /api/ody/chat, the Odysseus streaming relay."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import StreamingResponse
from ..core.analytics import _log_ody_metrics
from ..core.appctx import app
from .ody import _ody, _ody_login, _ody_req
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


@app.post("/api/ody/chat")
async def ody_chat(req: Request) -> StreamingResponse:
    """Stream a chat turn: re-emit Odysseus's SSE (delta / tool events / [DONE]) to the panel."""
    body = await req.json()
    image = body.get("image") or ""
    image_name = (body.get("image_name") or "")[:200]
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
        if image:
            # Upload FIRST: no part of this turn starts until we know the attachment
            # landed. Every failure ends the turn with its own reason.
            err = ody_attach_error(image)
            mime, raw = (None, None) if err else parse_data_url(image, IMAGE_MAX_CHARS)
            if not err and not raw:
                err = "that image could not be decoded — attach removed"
            if not err:
                try:
                    r = await _ody_req(
                        "POST", ODY_ATTACH_UPLOAD,
                        files={"files": (image_name or "image", raw,
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
            yield f'data: {{"type":"proxy_error","error":"{str(e)[:200]}"}}\n\n'
            yield "data: [DONE]\n\n"
        finally:
            _log_ody_metrics(tail, fields.get("mode", "agent"))

    return StreamingResponse(gen(), media_type="text/event-stream")
