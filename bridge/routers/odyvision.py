"""ROUTER — THE ODYSSEUS VISION SHIM: fast image descriptions for uploads made in
ODYSSEUS'S OWN TAB, not just ours (v1.5.33).

── WHAT WAS STILL BROKEN AFTER v1.5.31 ──────────────────────────────────────
v1.5.31 closed the AGENT LANE: an image attached in OUR panel is pre-captioned by
the loaded, registry-verified vision model (`enable_thinking: false`, bounded
prompt, ~6s) and the text is PUT into Odysseus's own vision cache
(UPLOAD_DIR/.vision/<att_id>.txt), so the turn costs nothing extra upstream.

An image the user drops into the ODYSSEUS TAB never touches our panel. It goes
straight to Odysseus's own POST /api/upload on :7860, and at turn time
src/chat_handler.py runs its own path:

    vl_result = analyze_image_with_vl_result(path, owner=owner)   # ← BLOCKING
      → src/document_processor.py:333
      → llm_call(url, model, [... "Describe this image in detail" ...], timeout=120)

with NO token budget and NO thinking control. MEASURED ON THIS MACHINE
(2026-08-29, the loaded Qwen3.6-27B-Fable-Fus-711, our orange/blue-circle/
green-square probe): 65.1s, 849 completion tokens, 2717 characters of reasoning
before a single word of description. v1.5.31 measured 173s for the same call on a
harder image. So the exposure is not "always fails" — it is 65-173s of wait that
sometimes crosses the hard 120s cap and becomes "[VL model unavailable - image not
analyzed]". The identical model with `enable_thinking:false` and our bounded
prompt: 5.7s / 60 tokens, and it named the background colour, both shapes, their
colours and their positions correctly. 11x.

⚠️ AND THE WAIT IS WORSE THAN A WAIT. `analyze_image_with_vl_result` is called
DIRECTLY from an `async def` (chat_handler.py:263 — no asyncio.to_thread, unlike
`model_supports_vision` three lines above it), and so is the GET
/api/upload/{id}/vision route. It is a SYNCHRONOUS httpx call, so for its whole
duration it blocks Odysseus's event loop: the entire app is frozen, not just that
turn. That fact is load-bearing below — see NEVER CALL ODYSSEUS FROM THE SHIM.

── THE SEAM (obligation 8: research first) ──────────────────────────────────
Three candidates were read end to end before any code was written:

  (a) WATCH Odysseus's UPLOAD_DIR and pre-caption new images before the turn asks.
      Rejected as the primary: it only NARROWS the exposure. Detection latency plus
      ~6s of captioning is a race against a user who attaches and sends in the same
      breath, and a lost race falls back to the very 65-173s call this slice exists
      to retire. It also cannot help the other doors into the same function (the
      attachment dropdown's vision editor, gallery captions, document OCR).

  (b) CONFIGURATION — and Odysseus HAS one. Its vision path resolves
      `Settings → Vision → vision_model` through `src/ai_interaction._resolve_model`
      against the ModelEndpoint rows in its own DB (`model@endpoint-name` selects
      one endpoint by name; the endpoint is probed at /v1/models and the model
      matched by id). Registering an OpenAI-compatible endpoint is therefore a
      FIRST-CLASS, SUPPORTED configuration act — and the harness ALREADY does it
      (scripts/seed_odysseus_jan.py upserts the `local-jan` row that points Odysseus
      at our runner). So we register ONE MORE endpoint, served by this file, whose
      only model produces the fast caption. Synchronous at turn time ⇒ NO RACE AT
      ALL, and it covers every door into the VL path, not just chat.

  (c) A reverse proxy in front of :7860 — forbidden by the brief, and unnecessary.

(b) is the seam. (a) is not built at all: with (b) there is no window left to watch.
ZERO vendored bytes are modified; everything here is our own route plus two writes
through Odysseus's own admin API (POST /api/model-endpoints, POST
/api/auth/settings), both never-clobbering and both reversible.

── NEVER CALL ODYSSEUS FROM THE SHIM ────────────────────────────────────────
Because the VL call blocks Odysseus's event loop, a request FROM the shim BACK to
:7860 while one is in flight cannot be served until it finishes: a deadlock that
would turn a 6s caption into Odysseus's own 120s timeout. Everything the shim needs
to know about Odysseus's settings is therefore snapshotted by `ody_vision_shim_ensure`
(which runs OUTSIDE any VL call) into `_SHIM_STATE` and read from memory here.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..core.appctx import app
from ..core.procs import cfg

# ── The shim's identity, on the wire and in Odysseus's UI ────────────────────
# ⚠️ THIS PATH IS NOT A NAMING CHOICE — IT IS THE ONE SHAPE ODYSSEUS CLASSIFIES
# CORRECTLY, AND THE FIRST DRIVE OF THIS SLICE FAILED ON IT. The shim first lived
# at /api/ody/vlshim/v1, next to the rest of the Odysseus lane. Odysseus then
# probed http://127.0.0.1:8700/api/ody/vlshim/v1/TAGS and got a 404, resolution
# failed, and the tab turn answered as if no vision model were configured at all.
# The cause is src/llm_core.py:561 `_is_ollama_native_url`: a LOOPBACK url whose
# path starts with "/api/" — on any port — IS NATIVE OLLAMA to Odysseus, unless
# the path starts with "/v1". And "/v1…" is no escape either: line 578
# `_is_ollama_openai_compat_url` claims every loopback path under /v1 as Ollama's
# OpenAI surface (which is why Odysseus pokes /slots and /api/v1/models at our
# runner). So the base must start with NEITHER "/api" NOR "/v1" — hence
# "/odyvision/v1", outside the bridge's usual /api namespace on purpose.
# Pinned by bridge/contract_tests/test_attach_lanes_contract.py against the
# vendored pin, because a change to either helper upstream silently unwires this.
#
# The TRAILING /v1 matters for the opposite reason: build_models_url only INVENTS
# a /v1 segment for a base with an EMPTY path, so a path-carrying base must
# already end at the OpenAI root. The two derived URLs are then exactly
# <base>/models and <base>/chat/completions — the two routes below.
ODY_VLSHIM_PATH = "/odyvision/v1"
# Visible in Odysseus's model picker and in Settings → Vision. NAMED, not hidden:
# hiding it would depend on an upstream inconsistency (its hidden_models list is
# honoured by the chat resolver but not by the vision one), and a user is better
# served by a row they can read, inspect and delete than by an invisible one.
ODY_VLSHIM_MODEL = "harness-image-describer"
ODY_VLSHIM_EP_NAME = "Harness image describer"
# Our own budget for one caption. UNDER Odysseus's hard 120s on purpose: if the
# runner is wedged we want to answer with an honest marker while it is still
# listening, rather than have it time out and log a failure we could have named.
ODY_VLSHIM_TIMEOUT = 95.0
ODY_VLSHIM_MAX_BYTES = 24 * 1024 * 1024      # decoded image ceiling (~32MB base64)

# What `ody_vision_shim_ensure` last learned about Odysseus, read by the shim
# WITHOUT touching the network (see the deadlock note in the module docstring).
_SHIM_STATE: dict = {"fallbacks": False, "ensured_at": 0.0, "spec": "", "endpoint_id": ""}


# ── PURE HELPERS (ast-extracted by bridge/tests/test_ody_vlshim.py) ──────────
def ody_shim_base(port) -> str:
    """PURE: the base_url Odysseus must be given for this shim."""
    try:
        p = int(port)
    except (TypeError, ValueError):
        p = 8700
    return f"http://127.0.0.1:{p}{ODY_VLSHIM_PATH}"


def ody_shim_spec(model: str, ep_name: str) -> str:
    """PURE: the `vision_model` value — Odysseus's own `model@endpoint` form.

    The @ form is not decoration: _resolve_model filters the endpoint list by
    name BEFORE probing, so resolution is deterministic (no partial-match against
    somebody else's endpoint) and no other endpoint is probed at 5s apiece."""
    m = (model or "").strip()
    n = (ep_name or "").strip()
    if not m:
        return ""
    return f"{m}@{n}" if n else m


def ody_shim_endpoint_pick(rows, base: str) -> dict:
    """PURE: OUR endpoint row out of Odysseus's /api/model-endpoints listing.

    Matched on base_url (trailing slash insensitive) — never on the display name,
    which the user is free to rename. Renaming it is not breakage: ensure() reads
    the name back off the row it finds and re-specs `vision_model` to match."""
    want = (base or "").strip().rstrip("/")
    for r in (rows or []):
        if isinstance(r, dict) and str(r.get("base_url") or "").strip().rstrip("/") == want:
            return r
    return {}


def ody_shim_stale_rows(rows, base: str) -> list:
    """PURE: ids of OUR OWN endpoint rows that point at an address we no longer
    serve — the bridge's port changed, or the path did.

    Recognised by our EXACT display name on a LOOPBACK address — never by path
    (the path itself is one of the things that can change, as it did once during
    this slice's own development), and never by anything a user-made row would
    match by accident. Left behind, a stale row shows up in their endpoint list as
    a permanently offline server: the kind of untidy leftover that reads as
    breakage."""
    want = (base or "").strip().rstrip("/")
    out = []
    for r in (rows or []):
        if not isinstance(r, dict):
            continue
        url = str(r.get("base_url") or "").strip().rstrip("/")
        if not url or url == want:
            continue
        if str(r.get("name") or "").strip() != ODY_VLSHIM_EP_NAME:
            continue
        if "127.0.0.1" not in url and "localhost" not in url:
            continue
        if r.get("id"):
            out.append(str(r["id"]))
    return out


def ody_shim_extract_image(payload) -> tuple:
    """PURE: (base64 payload, mime) of the LAST inline image in an OpenAI-shaped
    request, or ("", "") when there is none.

    Odysseus sends exactly one `image_url` part carrying a data: URL
    (document_processor.py:354-362). We read the LAST one so a multi-image caller
    describes the picture it just added, and we accept only data: URLs — a shim
    that fetched an http:// url from a model request would be an SSRF hole."""
    try:
        msgs = (payload or {}).get("messages") or []
    except AttributeError:
        return ("", "")
    found = ("", "")
    for m in msgs:
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            url = ((part.get("image_url") or {}).get("url")
                   if isinstance(part.get("image_url"), dict) else part.get("image_url"))
            url = str(url or "")
            if not url.startswith("data:"):
                continue
            head, _, b64 = url.partition(",")
            if not b64:
                continue
            mime = head[5:].split(";")[0].strip() or "image/png"
            if not mime.startswith("image/"):
                continue
            found = (b64, mime)
    return found


def ody_shim_failure(reason: str, fallbacks: bool) -> tuple:
    """PURE: how the shim reports "I could not describe this picture" → (kind, text).

    TWO HONEST ANSWERS, and the choice is INFERRED rather than asked (the
    autocorrect standard):
      • the user has configured vision FALLBACKS (Settings → Vision → Fallbacks):
        answer with an HTTP error so Odysseus's own fallback chain gets its turn.
        Swallowing the failure would quietly deprive them of the model they chose.
      • no fallbacks: answer 200 with a marker in UPSTREAM'S OWN IDIOM — a leading
        "[", which is exactly how Odysseus spells its own "[VL model unavailable…]"
        and precisely what chat_handler.py:262 refuses to cache. So it is shown,
        never stored, and the next attempt tries again from scratch.
    Both say what happened. Neither claims a description that did not happen.

    ⚠️ ONE REASON IS TRANSLATED, and deliberately: "no loaded model has vision
    evidence in the registry" is OUR vocabulary (it is what the panel statusline
    says, to a user who is looking at the panel). Somebody who never leaves the
    Odysseus tab has no idea what a registry is — they need the ACTION. Every
    other reason passes through verbatim."""
    why = (reason or "the image could not be described").strip()
    if "vision evidence" in why:
        why = ("no vision-capable model is loaded in Harness — load one from its "
               "Models pane and send this picture again")
    if fallbacks:
        return ("error", why)
    return ("marker", f"[Harness could not describe this image: {why}]")


def ody_shim_no_image_text() -> str:
    """PURE: what the shim says when asked to CHAT (no picture in the request).

    Its model id is visible in Odysseus's picker, so somebody will select it once.
    A silent wrong answer would be the LIE class; this is a sentence that says what
    the thing is and what to do instead."""
    return ("This is the Harness image describer, not a chat model — it only turns "
            "an attached picture into a written description for the model you are "
            "actually chatting with. Pick your own model in the model selector.")


def ody_shim_envelope(model: str, content: str) -> dict:
    """PURE: a minimal, spec-shaped OpenAI chat completion. Odysseus reads
    data['choices'][0]['message']['content'] (llm_core.py:2051) and nothing else,
    but the envelope stays honest for any other OpenAI-compatible reader."""
    return {
        "id": "chatcmpl-harness-vision",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model or ODY_VLSHIM_MODEL,
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": content or ""}}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def ody_shim_sse(model: str, content: str) -> str:
    """PURE: the same answer as a one-chunk SSE stream, for a caller that asked for
    `stream: true`. Odysseus's VL path never streams — this is the graceful-absence
    half, so selecting the describer in the chat picker renders a sentence instead
    of hanging on a stream that never arrives."""
    chunk = {"id": "chatcmpl-harness-vision", "object": "chat.completion.chunk",
             "created": int(time.time()), "model": model or ODY_VLSHIM_MODEL,
             "choices": [{"index": 0, "delta": {"role": "assistant",
                                                "content": content or ""},
                          "finish_reason": None}]}
    done = dict(chunk, choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}])
    return (f"data: {json.dumps(chunk)}\n\n"
            f"data: {json.dumps(done)}\n\n"
            "data: [DONE]\n\n")


# ── THE SHIM ROUTES ──────────────────────────────────────────────────────────
@app.get(ODY_VLSHIM_PATH + "/models")
async def ody_vlshim_models() -> JSONResponse:
    """The OpenAI model list Odysseus probes when it resolves `vision_model`.

    ONE id, always present — deliberately NOT gated on a vision model being loaded
    right now. The endpoint is a stable address; what is behind it is resolved per
    request, so a model switch (or a runner that is down at probe time) can never
    unwire the configuration and strand the user back on the 120s path."""
    return JSONResponse({"object": "list", "data": [
        {"id": ODY_VLSHIM_MODEL, "object": "model", "created": 0,
         "owned_by": "harness"}]})


@app.post(ODY_VLSHIM_PATH + "/chat/completions")
async def ody_vlshim_chat(req: Request):
    """Describe the attached picture — fast, honestly labelled, never blocking.

    ⚠️ NOT ONE NETWORK CALL TO ODYSSEUS HAPPENS IN HERE. Odysseus's event loop is
    blocked for the whole duration of the call it is making TO US (see the module
    docstring), so asking it anything now would deadlock until its own timeout."""
    from .ody import _ody_vision_describe, ody_vision_provenance
    try:
        body = await req.json()
    except Exception:                                        # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    stream = bool(body.get("stream"))
    model = str(body.get("model") or ODY_VLSHIM_MODEL)

    def _answer(text: str, status: int = 200):
        if status != 200:
            return JSONResponse({"error": {"message": text, "type": "harness_vision"}},
                                status_code=status)
        if stream:
            return StreamingResponse(_one(ody_shim_sse(model, text)),
                                     media_type="text/event-stream")
        return JSONResponse(ody_shim_envelope(model, text))

    async def _one(s: str):
        yield s

    b64, mime = ody_shim_extract_image(body)
    if not b64:
        return _answer(ody_shim_no_image_text())
    fallbacks = bool(_SHIM_STATE.get("fallbacks"))
    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception:                                        # noqa: BLE001
        raw = b""
    if not raw or len(raw) > ODY_VLSHIM_MAX_BYTES:
        kind, text = ody_shim_failure(
            "the image was empty or larger than 24 MB" if raw else
            "the image data could not be decoded", fallbacks)
        return _answer(text, 200 if kind == "marker" else 502)
    t0 = time.time()
    try:
        desc, mid, err = await _ody_vision_describe(raw, mime, timeout=ODY_VLSHIM_TIMEOUT)
    except Exception as e:                                   # noqa: BLE001
        desc, mid, err = ("", "", f"the vision pass raised: {str(e)[:140]}")
    if not desc:
        kind, text = ody_shim_failure(err or "the vision pass returned nothing", fallbacks)
        print(f"[ody-vlshim] no description ({err or 'empty'}) after "
              f"{time.time() - t0:.1f}s → {kind}", flush=True)
        return _answer(text, 200 if kind == "marker" else 502)
    print(f"[ody-vlshim] described an image with {mid} in {time.time() - t0:.1f}s",
          flush=True)
    # The SAME provenance text the Agent lane stores — one rule, one function: it
    # never starts with "[" (upstream discards those), it names the model that read
    # the pixels, and it says it IS a description so the answering model can never
    # present it as sight. The file name is not on the wire here (Odysseus sends
    # only the data URL), and ody_vision_provenance degrades to "the attached
    # image" rather than inventing one.
    return _answer(ody_vision_provenance("", mid, desc))


# ── REGISTRATION: teach Odysseus about the shim, without clobbering anything ──
async def ody_vision_shim_ensure(settings=None) -> dict:
    """Make sure Odysseus has the shim endpoint and (if we may) points its vision
    at it. Idempotent, best-effort, never raises into a caller.

    → {"ok", "spec", "endpoint_id", "created", "reason"}"""
    from .ody import _ody_req, _ody_settings
    out = {"ok": False, "spec": "", "endpoint_id": "", "created": False, "reason": ""}
    base = ody_shim_base(cfg().get("bridge", {}).get("port") or 8700)
    try:
        s = settings if isinstance(settings, dict) else await _ody_settings()
        # Snapshot what the shim will need to know while Odysseus's loop is blocked.
        fb = s.get("vision_model_fallbacks")
        _SHIM_STATE["fallbacks"] = bool(fb) if isinstance(fb, (list, tuple, str)) else False
        r = await _ody_req("GET", "/api/model-endpoints")
        rows = r.json() if r.status_code == 200 else []
        if isinstance(rows, dict):
            rows = rows.get("endpoints") or rows.get("items") or []
        row = ody_shim_endpoint_pick(rows, base)
        for _stale in ody_shim_stale_rows(rows, base):
            # Best-effort and never fatal: a leftover of OURS at an address we no
            # longer serve would sit in the user's endpoint list as a dead server,
            # and (because vision_model selects by NAME) would be probed first.
            try:
                d = await _ody_req("DELETE", f"/api/model-endpoints/{_stale}")
                print(f"[ody-vlshim] removed our stale endpoint {_stale} "
                      f"({d.status_code})", flush=True)
            except Exception:                                # noqa: BLE001
                pass
        if not row:
            # Odysseus dedupes on base_url itself, so a concurrent create is safe.
            c = await _ody_req("POST", "/api/model-endpoints", data={
                "name": ODY_VLSHIM_EP_NAME, "base_url": base, "api_key": "",
                "model_type": "llm", "endpoint_kind": "local",
                "skip_probe": "false", "shared": "true"})
            if c.status_code != 200:
                out["reason"] = f"Odysseus refused the endpoint ({c.status_code})"
                return out
            r = await _ody_req("GET", "/api/model-endpoints")
            row = ody_shim_endpoint_pick(r.json() if r.status_code == 200 else [], base)
            out["created"] = bool(row)
            if row:
                print(f"[ody-vlshim] registered the image-describer endpoint at {base} "
                      f"— Odysseus's own vision calls now take ~6s instead of 65-173s",
                      flush=True)
        if not row:
            out["reason"] = "the endpoint is not in Odysseus's list after creating it"
            return out
        if row.get("is_enabled") is False:
            # The user disabled it. That is a decision, not a fault: leave it alone
            # and say so — never re-enable something a human switched off.
            out["reason"] = "the endpoint is disabled in Odysseus — left alone"
            out["endpoint_id"] = str(row.get("id") or "")
            return out
        out.update(ok=True, endpoint_id=str(row.get("id") or ""),
                   spec=ody_shim_spec(ODY_VLSHIM_MODEL, str(row.get("name") or "")))
        _SHIM_STATE.update(spec=out["spec"], endpoint_id=out["endpoint_id"],
                           ensured_at=time.time())
    except Exception as e:                                   # noqa: BLE001
        out["reason"] = f"shim registration unavailable: {str(e)[:160]}"
    return out


async def _shim_boot() -> None:
    """Wire the shim WITHOUT waiting for anyone to open our panel.

    The whole point of this slice is the user who never leaves the Odysseus tab, so
    the wiring cannot depend on an Agent-lane attach. Odysseus may still be starting
    (or stopped, or never installed): retry gently, do nothing at all once wired,
    and never log twice for the same state."""
    from .ody import ody_vision_autowire
    tries = 0
    while True:
        try:
            res = await ody_vision_autowire()
            if res.get("wired") or "already" in (res.get("reason") or "") \
                    or "hand" in (res.get("reason") or ""):
                await asyncio.sleep(600)
                tries = 0
                continue
        except Exception:                                    # noqa: BLE001
            pass
        tries += 1
        await asyncio.sleep(30 if tries < 10 else 600)


async def _ody_vlshim_startup() -> None:
    asyncio.get_running_loop().create_task(_shim_boot())


# Starlette's own startup list rather than @app.on_event("startup"): the decorator is
# deprecated in this FastAPI and would add a DeprecationWarning to a gate that has
# none, and the app object is created bare in core/appctx.py (no lifespan to join).
app.router.on_startup.append(_ody_vlshim_startup)
