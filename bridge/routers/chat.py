"""ROUTER — POST /api/chat/direct, the direct (runner) chat lane."""
from __future__ import annotations

import asyncio
from fastapi import Request
from fastapi.responses import StreamingResponse
from ..core.analytics import log_turn
from ..core.appctx import app
from ..core.modelid import _live_model_id, wire_model_id
from ..core.procs import _registry_models, cfg
from .ody import _ody_req, flatten_ody_content
from .sampling import IMAGE_MAX_CHARS, _RUNNER, _vision_capable, build_user_content, sampling_merge, turn_metadata
from .sidecars import log_attachment, log_thinking, parse_data_url, user_key


@app.post("/api/chat/direct")
async def chat_direct(req: Request) -> StreamingResponse:
    body = await req.json()
    sid = body.get("session", "")
    user_msg = (body.get("message") or "").strip()
    image = body.get("image") or ""
    image_name = (body.get("image_name") or "")[:200]
    rc = cfg().get("runner", {})
    base = (rc.get("endpoint") or "http://127.0.0.1:6767/v1").rstrip("/")
    key, model = rc.get("api_key", ""), rc.get("model", "")
    # `model` stays our REGISTRY ID (labels/analytics); `wire` is what the runner
    # accepts — identical for llama.cpp (--alias), the model PATH for MLX servers
    # (which would otherwise try to resolve our id on HF → 404 → runner 400).
    _reg = _registry_models()
    wire = wire_model_id(model, _reg)
    # Per-model sampling, engine-translated. Read here (once per turn) rather than
    # cached so an edit in the Models pane lands on the NEXT message with no reload.
    # An unknown model still gets the harness defaults — which is what guarantees an
    # explicit max_tokens on every single turn (see SAMPLING_DEFAULTS).
    sampling = sampling_merge(next((m for m in _reg if m.get("id") == model), None) or {})

    # Build messages: session history (if reachable) + the new user turn.
    messages = []
    if sid:
        try:
            h = await _ody_req("GET", f"/api/history/{sid}")
            if h.status_code == 200:
                for m in (h.json().get("history") or [])[-30:]:
                    # FLATTEN: an AGENT-lane turn that carried an image is stored as
                    # OpenAI content PARTS with the picture inline as base64. Replaying
                    # that verbatim would re-send megabytes into every later direct-lane
                    # prompt — and to a model that may not accept images at all.
                    content = flatten_ody_content(m.get("content"))
                    if m.get("role") in ("user", "assistant") and content:
                        messages.append({"role": m["role"], "content": content})
        except Exception:
            pass  # degrade: direct chat works even with Odysseus down

    # An attached image only rides along when the LIVE model can see it. The live id
    # (not just runner.model) is the same source the composer's VISION chip uses, so
    # the UI's promise and the gate here can't disagree. Probed only when an image is
    # actually attached — no extra work on ordinary turns.
    vision = False
    if image:
        live = None
        try:
            if rc.get("port"):
                live = await asyncio.to_thread(_live_model_id, int(rc["port"]))
        except Exception:
            live = None
        vision = _vision_capable(live or model)
    content, cerr = build_user_content(user_msg, image, vision)
    messages.append({"role": "user", "content": content if not cerr else user_msg})

    async def gen():
        import json as _json, time as _t
        if cerr:   # never call the runner with an attachment it can't use
            yield f'data: {_json.dumps({"type": "proxy_error", "error": cerr})}\n\n'
            yield "data: [DONE]\n\n"
            return
        full, think_open = [], False
        think = []        # thinking sidecar (both reasoning_content + inline <think>)
        t0 = _t.monotonic(); stats = {}   # for best-effort usage analytics
        try:
            async with _RUNNER.stream(
                "POST", f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": wire, "messages": messages,
                      "stream": True, "cache_prompt": True,
                      "stream_options": {"include_usage": True},
                      **sampling},
            ) as r:
                if r.status_code != 200:
                    yield f'data: {{"type":"proxy_error","error":"runner {r.status_code}"}}\n\n'
                    yield "data: [DONE]\n\n"
                    return
                yield f'data: {_json.dumps({"type": "model_info", "model": model})}\n\n'
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload.strip() == "[DONE]":
                        break
                    try:
                        obj = _json.loads(payload)
                    except Exception:
                        continue
                    # final usage frame (stream_options.include_usage) has empty choices
                    if obj.get("usage") or obj.get("timings"):
                        stats["usage"] = obj.get("usage") or stats.get("usage") or {}
                        stats["timings"] = obj.get("timings") or stats.get("timings") or {}
                    _ch = obj.get("choices") or []
                    if not _ch:
                        continue
                    d = _ch[0].get("delta") or {}
                    if "ttft" not in stats and (d.get("reasoning_content") or d.get("content")):
                        stats["ttft"] = _t.monotonic() - t0
                    # thinking arrives either as reasoning_content or inline <think> tags
                    rsn = d.get("reasoning_content")
                    if rsn:
                        think.append(rsn)
                        yield f'data: {_json.dumps({"delta": rsn, "thinking": True})}\n\n'
                        continue
                    chunk = d.get("content") or ""
                    if not chunk:
                        continue
                    while chunk:
                        if think_open:
                            end = chunk.find("</think>")
                            if end == -1:
                                think.append(chunk)
                                yield f'data: {_json.dumps({"delta": chunk, "thinking": True})}\n\n'
                                chunk = ""
                            else:
                                if chunk[:end]:
                                    think.append(chunk[:end])
                                    yield f'data: {_json.dumps({"delta": chunk[:end], "thinking": True})}\n\n'
                                chunk = chunk[end + 8:]
                                think_open = False
                        else:
                            start = chunk.find("<think>")
                            if start == -1:
                                full.append(chunk)
                                yield f'data: {_json.dumps({"delta": chunk})}\n\n'
                                chunk = ""
                            else:
                                if chunk[:start]:
                                    full.append(chunk[:start])
                                    yield f'data: {_json.dumps({"delta": chunk[:start]})}\n\n'
                                chunk = chunk[start + 7:]
                                think_open = True
        except Exception as e:
            yield f'data: {{"type":"proxy_error","error":"{str(e)[:200]}"}}\n\n'
        finally:
            # Persist the exchange into the Odysseus session (best-effort).
            stats["elapsed"] = _t.monotonic() - t0     # per-reply stats stamp
            answer = "".join(full).strip()
            if sid and user_msg:
                persisted = injected = False
                try:
                    # New Odysseus main removed POST /api/session/{sid}/message;
                    # append via the bulk inject_messages endpoint (user before assistant).
                    # TEXT only: the store (and the thinking sidecar's answer-hash
                    # join) stay string-shaped; the attachment is recorded as a marker
                    # so a reopened transcript still shows an image was sent.
                    msgs = [{"role": "user",
                             "content": user_msg + ("\n[image attached]" if image else "")}]
                    if answer:
                        am = {"role": "assistant", "content": answer}
                        # per-reply stats (tok/s · tokens · time) so a reopened
                        # direct-lane transcript stamps the same line the Agent
                        # lane gets from Odysseus's own metrics. Best-effort:
                        # an empty dict is simply not sent.
                        try:
                            meta = turn_metadata(model, stats.get("usage"),
                                                 stats.get("timings"),
                                                 stats.get("elapsed"))
                            if meta:
                                am["metadata"] = meta
                        except Exception:
                            pass
                        msgs.append(am)
                    await _ody_req("POST", f"/api/session/{sid}/inject_messages",
                                   json={"messages": msgs})
                    injected = True
                    if answer:
                        persisted = True
                except Exception:
                    pass
                if injected and image:
                    # Image sidecar: keep the BYTES locally, keyed by (sid, user
                    # text hash), so reopening the session rehydrates the same
                    # thumbnail instead of just the marker line. A malformed or
                    # oversize dataURL is simply not stored — never fails a turn.
                    _mime, _raw = parse_data_url(image, IMAGE_MAX_CHARS)
                    if _raw:
                        log_attachment(sid, user_key(user_msg), image_name,
                                       _mime, _raw)
                if persisted:
                    # Thinking sidecar: Odysseus stores {role,content} only, so keep
                    # this turn's reasoning locally keyed by (sid, answer hash) →
                    # /api/ody/history rehydrates it on reopen. Never raises.
                    log_thinking(sid, answer, "".join(think).strip())
                if persisted:
                    # Best-effort auto-title: the direct lane skips Odysseus's post-turn
                    # tasks (incl. auto-name), so sessions still called "New chat" get a
                    # local title from the first user message. NEVER affects the stream.
                    try:
                        rs = await _ody_req("GET", "/api/sessions")
                        cur = next((s for s in rs.json() if s.get("id") == sid), None) \
                            if rs.status_code == 200 else None
                        if cur and cur.get("name") == "New chat":
                            t = " ".join(user_msg.split())
                            if len(t) > 42:
                                cut = t[:42]
                                if " " in cut:
                                    cut = cut[:cut.rfind(" ")]
                                t = cut
                            if t:
                                await _ody_req("PATCH", f"/api/session/{sid}",
                                               data={"name": t})
                    except Exception:
                        pass
            try:   # best-effort usage analytics (never breaks the turn)
                u = stats.get("usage") or {}; tm = stats.get("timings") or {}
                cached = ((u.get("prompt_tokens_details") or {}).get("cached_tokens")
                          or tm.get("cache_n") or 0)
                itok, otok = u.get("prompt_tokens"), u.get("completion_tokens")
                if itok or otok:
                    log_turn("direct", model, itok, otok, cached,
                             tm.get("predicted_per_second"), stats.get("ttft"))
            except Exception:
                pass
            yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
