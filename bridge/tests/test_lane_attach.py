#!/usr/bin/env python3
"""IMAGE ATTACH ON EVERY LANE — the bridge half (2026-08-28, Debi's ruling).

THE RULING: "We should ensure all paths have what they can handle depending on the
model." The ⊕ attach button existed on the CHAT lane only, and the audit found the
reason was legacy accident: both other lanes have a real, documented image path.

  chat   /api/chat/direct   → OpenAI content parts to the runner. Vision REQUIRED
                              (build_user_content refuses otherwise) — unchanged.
  agent  /api/ody/chat      → POST /api/upload (multipart) then the `attachments`
                              form field on /api/chat_stream. Odysseus itself
                              decides pixels-vs-description, so no vision gate.
  hermes /api/hermes/chat   → RPC image.attach_bytes on the session, drained by the
                              next prompt.submit. Same story on vision.

What this file pins:
  A. THE PURE FENCES — shape/size refusals in the same vocabulary on all lanes.
  B. THE FLATTENER — Odysseus persists a multimodal user turn as OpenAI content
     PARTS with the picture inline as base64. Two readers (the panel's bubble and
     the DIRECT lane's history replay) need a string. This was ALREADY broken for
     images attached from the Odysseus tab; it is pinned here so it stays fixed.
  C. THE REHYDRATION HANDLE — an Agent-lane image is stored by Odysseus, not by our
     sidecar, so history hands back {ody_id,name} and the panel proxies the bytes.
  D. THE FLOWS, DRIVEN — both lanes against stubs, including the failure paths.
     THE RULE UNDER TEST: an image the user attached and the backend refused must
     FAIL THE TURN with the reason. Answering it as if it had been a plain text
     message is the LIE-TO-USER class and outranks a refusal.

Run: python3 bridge/tests/test_lane_attach.py
"""
import ast
import asyncio
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


# ── A + B + C: the pure helpers, ast-extracted (no fastapi needed) ───────────
def _load(names, consts=()):
    tree = ast.parse(_APP_SOURCE)
    body = [n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name in names]
    missing = set(names) - {n.name for n in body}
    assert not missing, f"missing from the app layer: {sorted(missing)}"
    ns = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) \
                and n.targets[0].id in consts:
            # eval, not literal_eval: both caps are written as arithmetic
            # (12 * 1024 * 1024) so the number stays readable in the source.
            ns[n.targets[0].id] = eval(compile(ast.Expression(n.value),  # noqa: S307
                                               "consts", "eval"), {})
    for c in consts:
        assert c in ns, f"constant {c} vanished from the app layer"
    exec(compile(ast.Module(body=body, type_ignores=[]), "lanes", "exec"), ns)
    return ns


NS = _load(("ody_attach_error", "hermes_attach_error", "flatten_ody_content",
            "flatten_history", "ody_attachment_handles"),
           ("IMAGE_MAX_CHARS", "HERMES_IMAGE_MAX_CHARS"))
ody_attach_error = NS["ody_attach_error"]
hermes_attach_error = NS["hermes_attach_error"]
flatten_ody_content = NS["flatten_ody_content"]
flatten_history = NS["flatten_history"]
ody_attachment_handles = NS["ody_attachment_handles"]

PNG = ("data:image/png;base64,"
       + base64.b64encode(bytes.fromhex(
           "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
           "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
           "00000049454e44ae426082")).decode())

print("\n── A. the pure fences ──")
for fn, lane in ((ody_attach_error, "agent"), (hermes_attach_error, "hermes")):
    check(f"{lane}: no image = no error (the ordinary turn is untouched)",
          fn("") == "" and fn(None) == "")
    check(f"{lane}: a good PNG data URL passes", fn(PNG) == "")
    check(f"{lane}: a non-data-URL is refused by shape",
          "not an image data URL" in fn("https://example.com/cat.png"))
    check(f"{lane}: a non-image data URL is refused",
          "not an image data URL" in fn("data:text/plain;base64,aGk="))
    check(f"{lane}: a non-string is refused rather than crashing",
          "not an image data URL" in fn({"data": "x"}))
    check(f"{lane}: oversize is refused by size, and says SO",
          "too large" in fn("data:image/png;base64," + "A" * (13 * 1024 * 1024)))
# The vision clause belongs to the direct lane ONLY — the other two backends
# describe an image for a text-only model, so refusing there would be a lie.
check("neither non-direct lane refuses on vision (their backends describe instead)",
      "vision" not in ody_attach_error(PNG) and "vision" not in hermes_attach_error(PNG))
check("the direct lane still DOES refuse on vision (unchanged contract)",
      "no vision" in _APP_SOURCE)

print("\n── B. the multimodal-history flattener ──")
check("a plain string passes through byte-identical",
      flatten_ody_content("hello there") == "hello there")
parts = [{"type": "text", "text": "what is this?"},
         {"type": "image_url", "image_url": {"url": PNG}}]
check("content PARTS become their text (the picture is NOT stringified)",
      flatten_ody_content(parts) == "what is this?")
check("…and the base64 never leaks into the text",
      "base64" not in flatten_ody_content(parts))
check("two text parts join with a blank line",
      flatten_ody_content([{"type": "text", "text": "a"},
                           {"type": "text", "text": "b"}]) == "a\n\nb")
check("an image-only turn flattens to empty, not to junk",
      flatten_ody_content([{"type": "image_url", "image_url": {"url": PNG}}]) == "")
check("None → '' (never the string 'None')", flatten_ody_content(None) == "")
check("a surprise shape degrades instead of raising",
      isinstance(flatten_ody_content(42), str))
rows = [{"role": "user", "content": parts}, {"role": "assistant", "content": "hi"}]
flatten_history(rows)
check("flatten_history rewrites in place and leaves strings alone",
      rows[0]["content"] == "what is this?" and rows[1]["content"] == "hi")
check("flatten_history survives junk rows", flatten_history([None, 3, {}]) is not None)

print("\n── C. the Agent-lane rehydration handle ──")
hist = [{"role": "user", "content": "look",
         "metadata": {"attachments": [{"id": "up_1", "name": "shot.png",
                                       "mime": "image/png"}]}}]
ody_attachment_handles(hist)
check("an Odysseus image upload becomes an {ody_id,name} handle",
      hist[0]["attachment"] == {"ody_id": "up_1", "name": "shot.png"})
check("…and it is NOT the sidecar's {id} shape (different bytes source)",
      "id" not in hist[0]["attachment"])
h2 = [{"role": "user", "content": "x", "attachment": {"id": 7, "name": "a"},
       "metadata": {"attachments": [{"id": "up_2", "name": "b.png",
                                     "mime": "image/png"}]}}]
ody_attachment_handles(h2)
check("a handle the local sidecar already set is never overwritten",
      h2[0]["attachment"]["id"] == 7)
h3 = [{"role": "user", "content": "x",
       "metadata": {"attachments": [{"id": "u", "name": "notes.txt",
                                     "mime": "text/plain"}]}}]
ody_attachment_handles(h3)
check("a NON-image attachment gets no thumbnail handle", "attachment" not in h3[0])
h4 = [{"role": "assistant", "content": "x",
       "metadata": {"attachments": [{"id": "u", "name": "a.png",
                                     "mime": "image/png"}]}}]
ody_attachment_handles(h4)
check("only USER rows get a handle", "attachment" not in h4[0])
h5 = [{"role": "user", "content": "x",
       "metadata": {"attachments": [{"id": "u1", "name": "a.png", "mime": "image/png"},
                                    {"id": "u2", "name": "b.png", "mime": "image/png"}]}}]
ody_attachment_handles(h5)
check("only the FIRST image per row (the composer stages one)",
      h5[0]["attachment"]["ody_id"] == "u1")
check("malformed metadata is skipped, never raised",
      ody_attachment_handles([{"role": "user", "metadata": "nope"},
                              {"role": "user", "metadata": {"attachments": 5}},
                              None]) is not None)


# ── D. the flows, driven against stubs ──────────────────────────────────────
def test_flows():
    try:
        from fastapi.testclient import TestClient
    except Exception as e:                                       # noqa: BLE001
        print(f"  (skipped the driven flows — no TestClient: {e})")
        return
    import warnings
    warnings.filterwarnings("ignore")
    from bridge import app as A                                  # noqa: F401
    from bridge.routers import hermes as H
    from bridge.routers import odychat as OC

    client = TestClient(A.app)

    # ---- the Agent lane -----------------------------------------------------
    calls = {}

    class _Resp:
        def __init__(self, code=200, payload=None, text=""):
            self.status_code, self._p, self.text = code, payload, text

        def json(self):
            return self._p

    class _Stream:
        def __init__(self, code=200, body=b'data: {"delta":"ok"}\n\n'):
            self.status_code, self._b = code, body

        async def aiter_raw(self):
            yield self._b

    class _FakeOdy:
        def stream(self, method, path, **kw):
            calls["stream"] = dict(kw.get("data") or {})
            outer = _Stream()

            class _CM:
                async def __aenter__(self_inner):
                    return outer

                async def __aexit__(self_inner, *a):
                    return False
            return _CM()

    async def _fake_req(method, path, **kw):
        calls.setdefault("req", []).append((method, path, kw))
        if path == "/api/upload":
            if calls.get("upload_fails"):
                return _Resp(500, None, "disk on fire")
            return _Resp(200, {"files": [{"id": "up_9", "name": "shot.png"}]})
        return _Resp(200, {})

    OC._ody = _FakeOdy()
    OC._ody_req = _fake_req
    OC._log_ody_metrics = lambda *a, **k: None

    r = client.post("/api/ody/chat", json={"session": "s1", "message": "hi"})
    check("agent lane, NO image: the turn streams and sends no `attachments` field",
          r.status_code == 200 and "attachments" not in calls["stream"])

    calls.clear()
    r = client.post("/api/ody/chat", json={"session": "s1", "message": "what is this",
                                           "image": PNG, "image_name": "shot.png"})
    up = [c for c in calls.get("req", []) if c[1] == "/api/upload"]
    check("agent lane: the image is UPLOADED to Odysseus first", len(up) == 1)
    check("…as multipart `files` with the decoded bytes and its real mime",
          up[0][2]["files"]["files"][0] == "shot.png"
          and isinstance(up[0][2]["files"]["files"][1], bytes)
          and up[0][2]["files"]["files"][2] == "image/png")
    check("…scoped to the session (Odysseus's own gallery promotion needs it)",
          up[0][2]["data"]["session_id"] == "s1")
    check("…and chat_stream then carries the returned id in `attachments` JSON",
          json.loads(calls["stream"]["attachments"]) == ["up_9"])
    check("…while the message text itself is untouched",
          calls["stream"]["message"] == "what is this")

    calls.clear()
    calls["upload_fails"] = True
    r = client.post("/api/ody/chat", json={"session": "s1", "message": "m",
                                           "image": PNG})
    check("agent lane, upload REFUSED: the turn fails with the reason…",
          "proxy_error" in r.text and "refused the attachment" in r.text)
    check("…and NO chat turn is sent behind the user's back (the anti-lie rule)",
          "stream" not in calls)
    check("…and the stream is still closed properly ([DONE])", "[DONE]" in r.text)

    calls.clear()
    r = client.post("/api/ody/chat", json={"session": "s1", "message": "m",
                                           "image": "data:text/plain;base64,aGk="})
    check("agent lane, a non-image attachment is refused before any network call",
          "proxy_error" in r.text and not calls.get("req") and "stream" not in calls)

    # ---- the Hermes lane ----------------------------------------------------
    hcalls = []

    class _FakeWS:
        def __init__(self):
            self.q = None
            self.fail_attach = False

        async def rpc(self, method, params, timeout=30.0):
            hcalls.append((method, dict(params)))
            if method == "session.create":
                return {"session_id": "gw1", "stored_session_id": "st1"}
            if method == "image.attach_bytes":
                if self.fail_attach:
                    raise RuntimeError("unsupported image extension: .tif")
                return {"attached": True, "path": "/tmp/x.png", "count": 1}
            if method == "prompt.submit":
                self.q.put_nowait({"type": "message.complete",
                                   "payload": {"status": "complete"}})
                return {"status": "streaming"}
            return {}

        def open_queue(self, sid):
            self.q = asyncio.Queue()
            return self.q

        def close_queue(self, sid):
            pass

    fake = _FakeWS()
    H._HERMES = fake

    hcalls.clear()
    r = client.post("/api/hermes/chat", json={"session_id": "", "message": "hello"})
    check("hermes lane, NO image: no image.attach_bytes is sent",
          r.status_code == 200
          and not [c for c in hcalls if c[0] == "image.attach_bytes"])

    hcalls.clear()
    r = client.post("/api/hermes/chat", json={"session_id": "gw1", "message": "what is this",
                                              "image": PNG, "image_name": "shot.png"})
    names = [c[0] for c in hcalls]
    check("hermes lane: image.attach_bytes is sent…", "image.attach_bytes" in names)
    check("…BEFORE prompt.submit (the gateway drains attached_images at submit)",
          names.index("image.attach_bytes") < names.index("prompt.submit"))
    att = [c[1] for c in hcalls if c[0] == "image.attach_bytes"][0]
    check("…on the SAME session that is about to be prompted",
          att["session_id"] == "gw1")
    check("…carrying the panel's data URL verbatim (upstream strips the prefix)",
          att["content_base64"] == PNG)
    check("…and the filename, so the gateway can sniff the extension",
          att["filename"] == "shot.png")

    hcalls.clear()
    fake.fail_attach = True
    r = client.post("/api/hermes/chat", json={"session_id": "gw1", "message": "m",
                                              "image": PNG})
    check("hermes lane, attach REFUSED: the turn fails with Hermes's own reason",
          "proxy_error" in r.text and "unsupported image extension" in r.text)
    check("…and prompt.submit is NEVER reached (no answer without the image)",
          "prompt.submit" not in [c[0] for c in hcalls])
    fake.fail_attach = False

    hcalls.clear()
    r = client.post("/api/hermes/chat", json={"session_id": "gw1", "message": "m",
                                              "image": "data:image/png;base64,"
                                                       + "A" * (13 * 1024 * 1024)})
    check("hermes lane, oversize is refused before any session work",
          "too large" in r.text and not hcalls)


test_flows()

print()
if FAILS:
    print(f"{len(FAILS)} FAILED:")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("all lane-attach checks passed")
