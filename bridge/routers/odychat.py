"""ROUTER — POST /api/ody/chat, the Odysseus streaming relay."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import StreamingResponse
from ..core.analytics import _log_ody_metrics
from ..core.appctx import app
from .ody import _ody, _ody_login


@app.post("/api/ody/chat")
async def ody_chat(req: Request) -> StreamingResponse:
    """Stream a chat turn: re-emit Odysseus's SSE (delta / tool events / [DONE]) to the panel."""
    body = await req.json()
    fields = {
        "session": body.get("session", ""),
        "message": body.get("message", ""),
        "mode": body.get("mode", "agent"),
        "allow_web_search": "true" if body.get("allow_web_search", True) else "false",
        "allow_bash": "true" if body.get("allow_bash", False) else "false",
    }

    async def gen():
        tail = ""   # rolling tail of the stream, for best-effort metrics logging
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
