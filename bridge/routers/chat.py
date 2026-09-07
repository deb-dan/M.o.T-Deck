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


_DIRECT_REQUEST_META = "mot_direct_request_id"


def _inject_acknowledged(response, expected_count: int) -> bool:
    """Accept only Odysseus's proved bulk-injection receipt."""
    if not 200 <= getattr(response, "status_code", 0) < 300:
        return False
    try:
        body = response.json()
    except Exception:
        return False
    return (isinstance(body, dict) and body.get("ok") is True
            and body.get("count") == expected_count)


async def _persisted_direct_roles(sid: str, request_id: str) -> set[str]:
    """Read back the exact request marker after an ambiguous write response."""
    if not sid or not request_id:
        return set()
    try:
        history = await _ody_req("GET", f"/api/history/{sid}")
        if history.status_code != 200:
            return set()
        rows = history.json().get("history") or []
        return {
            str(row.get("role")) for row in rows if isinstance(row, dict)
            and isinstance(row.get("metadata"), dict)
            and row["metadata"].get(_DIRECT_REQUEST_META) == request_id
            and row.get("role") in {"user", "assistant"}
        }
    except Exception:
        return set()


def _runner_error_sentence(status, model: str = "") -> str:
    """PURE: what the panel (and the transcript) is told when the runner refuses a
    direct-lane turn. A SENTENCE with the cause and the next step in it — never a
    bare code.

    S33/F1, adherence audit rank 2: this lane streamed `"runner 502"` — no cause, no
    fix, on the most-used surface in the app, in the one house whose standing rule is
    that an error names what to DO. The classes below are the ones a local runner
    actually produces; anything else still gets the code AND a place to look, because
    "I do not know why" is allowed and silence is not.
    """
    try:
        code = int(status)
    except (TypeError, ValueError):
        code = 0
    who = f" for {model}" if model else ""
    tail = ("Open MOT Deck → Components to see whether the model runner is up, and "
            "its log for the refusal itself.")
    if code in (502, 503, 504):
        return (f"the model runner answered {code}{who} — it is most likely still "
                f"loading the model, restarting, or has just been stopped. Wait for "
                f"it to finish loading and send the message again. {tail}")
    if code == 400:
        return (f"the model runner refused this request as malformed (400){who} — "
                f"usually the model name on the wire is one it cannot resolve "
                f"(an MLX server is given the model's PATH, not its registry id). "
                f"Re-pick the model in the composer. {tail}")
    if code in (401, 403):
        return (f"the model runner rejected our credentials ({code}) — its api_key "
                f"in motdeck.yaml no longer matches the one it was started with. "
                f"{tail}")
    if code == 404:
        return (f"the model runner has no such model loaded (404){who} — pick a "
                f"model that is actually loaded in the composer, or load it from the "
                f"Models pane. {tail}")
    if code == 413 or code == 422:
        return (f"the model runner refused this turn as too large or unusable "
                f"({code}) — usually a very long history or an attachment it cannot "
                f"read. Start a new session or remove the attachment. {tail}")
    if code == 429:
        return (f"the model runner is at its request limit (429) — it is busy with "
                f"another turn. Send this again in a moment. {tail}")
    return (f"the model runner answered {code or 'an unreadable status'}{who} and "
            f"the turn could not start. {tail}")


async def direct_events(body: dict):
    """Produce the legacy direct SSE frames without binding them to a response.

    ``routers.turns`` owns this iterator in the durable API.  Keeping the old
    endpoint as a thin subscriber preserves callers that still expect its original
    SSE shape.
    """
    # Direct Chat has no document-ingestion contract. Reject the alternate API entry
    # explicitly; silently dropping a caller-supplied file would be worse than refusal.
    if body.get("file"):
        async def _file_refusal():
            import json as _json
            yield ("data: " + _json.dumps({
                "type": "proxy_error",
                "error": "files work in Agent or Hermes; direct Chat accepts images only",
            }) + "\n\n")
            yield "data: [DONE]\n\n"
        return _file_refusal()

    sid = body.get("session", "")
    request_id = str(body.get("request_id") or "")[:200]
    user_msg = (body.get("message") or "").strip()
    image = body.get("image") or ""
    image_name = (body.get("image_name") or "")[:200]
    rc = cfg().get("runner", {})
    base = (rc.get("endpoint") or "http://127.0.0.1:6767/v1").rstrip("/")
    key = rc.get("api_key", "")
    # ══ U18 CLOSED HERE. THE LINE THIS REPLACES WAS `model = rc.get("model", "")` ══
    #
    # That read motdeck.yaml's PIN — INTENT, not reality — and the post-switch coherence
    # audit measured what it cost: on 2026-08-29 the pin named a 27B whose file had been
    # deleted while the runner served Parable-Qwen3-4B. The composer chip above the box
    # said Parable (it reads live); this lane wired the 27B, llama.cpp silently
    # substituted the model it actually had, and the turn WORKED — while `model_info`,
    # the per-turn metadata stamped into the transcript and every `log_turn("direct", …)`
    # analytics row named a model that was not loaded. One screen, disagreeing with
    # itself, with the wrong half written into the record.
    #
    # PRECEDENCE, matching the hermes arm (v1.5.56) and aider's `_live_model_id` lane:
    # what the runner IS SERVING outranks motdeck.yaml; the pin is the fallback for the
    # one case a probe cannot answer — the runner is down, where naming the model we
    # intend to load is the most honest thing available and the turn is going to fail
    # with a connection error anyway.
    #
    # ⚠️ AND IT IS NOT COSMETIC. While both ids name gguf models the wrong wire value is
    # merely mislabelled; the moment a dangling pin names an MLX model, the wire id stops
    # being harmless — mlx_lm.server treats the request's `model` as A MODEL TO LOAD and
    # answers 400 for one it cannot resolve. Live-first removes that whole class.
    live = None
    try:
        if rc.get("port"):
            live = await asyncio.to_thread(_live_model_id, int(rc["port"]))
    except Exception:
        live = None
    model = live or rc.get("model", "")
    # `model` stays our REGISTRY ID (labels/analytics); `wire` is what the runner
    # accepts — identical for llama.cpp (--alias), the model PATH for MLX servers
    # (which would otherwise try to resolve our id on HF → 404 → runner 400).
    _reg = _registry_models()
    wire = wire_model_id(model, _reg)
    # Per-model sampling, engine-translated. Read here (once per turn) rather than
    # cached so an edit in the Models pane lands on the NEXT message with no reload.
    # An unknown model still gets MOT Deck defaults — which is what guarantees an
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
    # the UI's promise and the gate here can't disagree.
    # (The live probe now happens ONCE at the top of the turn — `model` IS the live id
    # whenever the runner answered — so this gate reads the same fact it always did
    # without a second probe.)
    vision = bool(image) and _vision_capable(model)
    content, cerr = build_user_content(user_msg, image, vision)
    messages.append({"role": "user", "content": content if not cerr else user_msg})

    async def gen():
        import json as _json, time as _t
        # A direct turn's prompt belongs to the session before the runner sees it.
        # This is deliberately after history construction above, so it cannot echo
        # itself into the model prompt, and before any network wait, so a reload or
        # lane detach never silently loses an attempted message.
        user_persisted = False
        image_logged = False
        user_record = {"role": "user", "content": user_msg +
                       ("\n[image attached]" if image else "")}
        if request_id:
            user_record["metadata"] = {_DIRECT_REQUEST_META: request_id}
        if sid and user_msg:
            try:
                stored = await _ody_req("POST", f"/api/session/{sid}/inject_messages", json={
                    "messages": [user_record],
                })
                user_persisted = _inject_acknowledged(stored, 1)
                if not user_persisted and request_id:
                    user_persisted = "user" in await _persisted_direct_roles(sid, request_id)
                if image:
                    _mime, _raw = parse_data_url(image, IMAGE_MAX_CHARS)
                    if _raw and user_persisted:
                        log_attachment(sid, user_key(user_msg), image_name, _mime, _raw)
                        image_logged = True
            except Exception:
                # Odysseus absence remains a graceful direct-lane degradation.  The
                # durable journal still records the attempted prompt; the final path
                # below makes one more best-effort transcript write.
                if request_id:
                    user_persisted = "user" in await _persisted_direct_roles(sid, request_id)
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
                    # ⚠️ NOT A BARE CODE (S33/F1, adherence audit rank 2). This line
                    # used to stream `"runner {code}"` — the exact dead-end the house
                    # error doctrine bans, on the most-used lane in the app: no cause,
                    # no next step, and nothing a model or a human could act on. The
                    # sentence names the actor (OUR runner, not the app), the code,
                    # what it usually means, and the one place to look.
                    yield ("data: " + _json.dumps({
                        "type": "proxy_error",
                        "error": _runner_error_sentence(r.status_code, model)}) + "\n\n")
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
            # ⚠️ SERIALIZED, NOT INTERPOLATED (S33/F1, adherence audit rank 7). This
            # was an f-string JSON literal with raw str(e) inside it, so an exception
            # message carrying a quote or a backslash — a path, a JSON snippet, a
            # Windows-shaped name — emitted an SSE frame the panel could not parse,
            # at the worst possible moment (during an error). Its siblings above
            # already do it this way.
            yield ("data: " + _json.dumps({
                "type": "proxy_error",
                "error": f"the direct lane failed mid-stream: {str(e)[:200]}"}) + "\n\n")
        finally:
            # Persist the exchange into the Odysseus session (best-effort).
            stats["elapsed"] = _t.monotonic() - t0     # per-reply stats stamp
            answer = "".join(full).strip()
            if sid and user_msg:
                persisted = injected = False
                assistant_persisted = False
                try:
                    if request_id and not user_persisted:
                        user_persisted = "user" in await _persisted_direct_roles(
                            sid, request_id)
                    # New Odysseus main removed POST /api/session/{sid}/message;
                    # append via the bulk inject_messages endpoint (user before assistant).
                    # TEXT only: the store (and the thinking sidecar's answer-hash
                    # join) stay string-shaped; the attachment is recorded as a marker
                    # so a reopened transcript still shows an image was sent.
                    msgs = [] if user_persisted else [user_record]
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
                        if request_id:
                            am.setdefault("metadata", {})[_DIRECT_REQUEST_META] = request_id
                        msgs.append(am)
                    if msgs:
                        stored = await _ody_req(
                            "POST", f"/api/session/{sid}/inject_messages",
                            json={"messages": msgs})
                        acknowledged = _inject_acknowledged(stored, len(msgs))
                        if acknowledged:
                            user_persisted = True
                            assistant_persisted = bool(answer)
                        elif request_id:
                            roles = await _persisted_direct_roles(sid, request_id)
                            user_persisted = "user" in roles
                            assistant_persisted = "assistant" in roles
                    injected = user_persisted
                    persisted = assistant_persisted
                except Exception:
                    if request_id:
                        roles = await _persisted_direct_roles(sid, request_id)
                        user_persisted = "user" in roles
                        assistant_persisted = "assistant" in roles
                        injected, persisted = user_persisted, assistant_persisted
                if injected and image and not image_logged:
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
                if not user_persisted or (answer and not assistant_persisted):
                    missing = "prompt and reply" if not user_persisted else "reply"
                    yield ("data: " + _json.dumps({
                        "type": "proxy_error",
                        "error": (f"the {missing} could not be confirmed in this session's "
                                  "history; the reply above may be partial, so copy it before "
                                  "leaving this session")}) + "\n\n")
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

    return gen()


@app.post("/api/chat/direct")
async def chat_direct(req: Request) -> StreamingResponse:
    # Compatibility callers such as LOffice Quick AI legitimately have no Odysseus
    # session. Keep the historical endpoint and request contract exact; the panel uses
    # /api/turns when it has a session and needs disconnect resilience.
    return StreamingResponse(await direct_events(await req.json()),
                             media_type="text/event-stream")
