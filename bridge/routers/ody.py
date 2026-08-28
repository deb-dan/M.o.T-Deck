"""ROUTER — the Odysseus lane: session CRUD, per-message actions, the Capabilities pane."""
from __future__ import annotations

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from ..core.appctx import app
from ..core.modelid import _display_model
from ..core.procs import cfg
from .sidecars import _attachment_forget, _attachment_rows, _thinking_forget, _thinking_rows, attach_images, attach_thinking


# ── Rung D: native chat pane — Bridge-side proxy to Odysseus's API ────────────
# The panel (:8700) cannot call Odysseus (:7860) from the browser (CORS default
# allows only portless localhost origins), so the Bridge proxies server-to-server,
# holding an admin login session (cookie `odysseus_session`, 7-day TTL, re-login on 401).

ODY_BASE = "http://127.0.0.1:7860"
_ody = httpx.AsyncClient(base_url=ODY_BASE, timeout=httpx.Timeout(30, read=None))


async def _ody_login() -> bool:
    comp = cfg().get("components", {}).get("odysseus", {})
    r = await _ody.post("/api/auth/login", json={
        "username": comp.get("admin_user", "admin"),
        "password": comp.get("admin_password", "admin123"),
        "remember": True, "totp_code": None})
    return r.status_code == 200 and r.json().get("ok") is True


async def _ody_req(method: str, path: str, **kw) -> httpx.Response:
    r = await _ody.request(method, path, **kw)
    if r.status_code in (401, 403):          # session expired/absent → login once, retry
        if await _ody_login():
            r = await _ody.request(method, path, **kw)
    return r


@app.get("/api/ody/health")
async def ody_health() -> dict:
    try:
        r = await _ody_req("GET", "/api/sessions")
        return {"up": r.status_code == 200}
    except Exception:
        return {"up": False}


@app.post("/api/ody/ensure-session")
async def ody_ensure_session(req: Request) -> JSONResponse:
    """Find (by name) or create the pane's chat session, bound to the default endpoint."""
    body = await req.json()
    name = body.get("name") or "Mission Control"
    try:
        r = await _ody_req("GET", "/api/sessions")
        if r.status_code == 200:
            for s in r.json():
                if s.get("name") == name and not s.get("archived"):
                    # `model` is Odysseus's stored session model = the WIRE id, which
                    # for MLX is a filesystem path — map it back to our registry id
                    # so the chat header/composer show a model NAME, not a path.
                    return JSONResponse({"id": s["id"], "model": _display_model(s.get("model")),
                                         "reused": True})
        r = await _ody_req("POST", "/api/session",
                           data={"name": name, "endpoint_id": "local-jan"})
        if r.status_code == 200:
            j = r.json()
            return JSONResponse({"id": j["id"], "model": _display_model(j.get("model")),
                                 "reused": False})
        return JSONResponse({"error": r.text[:500]}, status_code=502)
    except Exception as e:
        return JSONResponse({"error": f"Odysseus unreachable: {e}"}, status_code=502)


@app.get("/api/ody/sessions")
async def ody_sessions() -> JSONResponse:
    """List the user's chat sessions (newest first) for the pane's session rail."""
    try:
        r = await _ody_req("GET", "/api/sessions")
        if r.status_code != 200:
            return JSONResponse([])
        out = [{
            "id": s.get("id"),
            "name": (s.get("name") or "Untitled"),
            "model": _display_model(s.get("model")),   # wire id (MLX = path) → our id
            "updated_at": s.get("last_message_at") or s.get("updated_at") or s.get("created_at"),
            "message_count": s.get("message_count", 0),
        } for s in r.json() if s.get("id")]
        out.sort(key=lambda x: x["updated_at"] or "", reverse=True)
        return JSONResponse(out)
    except Exception:
        return JSONResponse([])


@app.post("/api/ody/session/new")
async def ody_session_new(req: Request) -> JSONResponse:
    """Create a fresh chat session bound to the default (local-jan) endpoint."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    name = (body.get("name") or "New chat").strip() or "New chat"
    try:
        r = await _ody_req("POST", "/api/session", data={"name": name, "endpoint_id": "local-jan"})
        if r.status_code == 200:
            j = r.json()
            return JSONResponse({"id": j["id"], "name": name,
                                 "model": _display_model(j.get("model"))})
        return JSONResponse({"error": r.text[:500]}, status_code=502)
    except Exception as e:
        return JSONResponse({"error": f"Odysseus unreachable: {e}"}, status_code=502)


@app.post("/api/ody/session/{sid}/rename")
async def ody_session_rename(sid: str, req: Request) -> JSONResponse:
    try:
        name = (await req.json()).get("name", "").strip()
    except Exception:
        name = ""
    if not name:
        return JSONResponse({"ok": False, "log": "empty name"}, status_code=400)
    try:
        r = await _ody_req("PATCH", f"/api/session/{sid}", data={"name": name})
        return JSONResponse({"ok": r.status_code == 200, "name": name})
    except Exception:
        return JSONResponse({"ok": False})


@app.post("/api/ody/session/{sid}/duplicate")
async def ody_session_duplicate(sid: str, req: Request) -> JSONResponse:
    """Duplicate a session by copying its messages into a fresh session, then name it
    '<src> (copy)'. New Odysseus main removed POST /api/session/{sid}/fork, so we replicate
    it: read history → create session → inject_messages → rename."""
    try:
        name = (await req.json()).get("name", "").strip()
    except Exception:
        name = ""
    try:
        # (a) fetch the source session's messages
        hr = await _ody_req("GET", f"/api/history/{sid}")
        if hr.status_code != 200:
            return JSONResponse({"error": hr.text[:500]}, status_code=502)
        hist = hr.json().get("history", []) or []
        msgs = [{"role": m.get("role"), "content": m.get("content", "")}
                for m in hist if m.get("role")]
        # (b) create the new session (same params as the "new session" path)
        cr = await _ody_req("POST", "/api/session",
                            data={"name": name or "New chat", "endpoint_id": "local-jan"})
        if cr.status_code != 200:
            return JSONResponse({"error": cr.text[:500]}, status_code=502)
        new_id = cr.json().get("id")
        # (c) copy the messages across
        if new_id and msgs:
            await _ody_req("POST", f"/api/session/{new_id}/inject_messages",
                           json={"messages": msgs})
        # (d) final rename to '<src> (copy)' (panel passes the copy name)
        if new_id and name:
            await _ody_req("PATCH", f"/api/session/{new_id}", data={"name": name})
        return JSONResponse({"id": new_id, "name": name})
    except Exception as e:
        return JSONResponse({"error": f"Odysseus unreachable: {e}"}, status_code=502)


@app.post("/api/ody/session/{sid}/delete")
async def ody_session_delete(sid: str) -> JSONResponse:
    try:
        r = await _ody_req("POST", f"/api/session/{sid}/delete")
        _thinking_forget(sid)   # drop the direct-lane thinking sidecar rows too
        _attachment_forget(sid)  # …and any stored image bytes for that session
        return JSONResponse({"ok": r.status_code == 200})
    except Exception:
        return JSONResponse({"ok": False})


@app.get("/api/ody/history/{sid}")
async def ody_history(sid: str) -> JSONResponse:
    try:
        r = await _ody_req("GET", f"/api/history/{sid}")
        out = r.json() if r.status_code == 200 else {"history": []}
        try:
            # Direct-lane thinking sidecar: Odysseus stores {role,content} only, so
            # re-attach any locally stored reasoning for this session's assistant
            # turns (matched by answer hash, consumed in order). Best-effort — a
            # sidecar miss just means no thinking disclosure, never a broken history.
            if isinstance(out, dict) and isinstance(out.get("history"), list):
                attach_thinking(out["history"], _thinking_rows(sid))
                # Image sidecar: same story for the USER turns — Odysseus keeps
                # only the "[image attached]" marker, so hand the panel back an
                # {id, name} handle it can render as the original thumbnail.
                attach_images(out["history"], _attachment_rows(sid))
        except Exception:
            pass
        return JSONResponse(out)
    except Exception:
        return JSONResponse({"history": []})


# ── Per-message actions (LM-Studio parity) ───────────────────────────────────
# Thin proxies over Odysseus's per-message ops. Both Mission-Control chat lanes
# (direct Chat + Agent) share the Odysseus session store, so delete/edit/fork all
# work for either. The Hermes lane keeps its own store and gets Copy only.
#   • delete → POST /api/session/{sid}/delete-messages {msg_ids}
#   • edit   → POST /api/session/{sid}/edit-message   {msg_id, content}
#              (content-only: upstream stamps metadata.edited and does NOT
#               truncate the tail — matches LM Studio's edit semantics)
#   • fork   → POST /api/session/{sid}/fork {keep_count}
# GOTCHA (recon): fork's keep_count indexes the UNFILTERED in-memory history —
# which is exactly what GET /api/history returns (the unpaged handler), so an
# index computed from that same payload is correct.

def fork_keep_count(history, msg_id):
    """Pure: keep_count that forks a session UP TO AND INCLUDING `msg_id`.

    Returns index+1 of the message whose metadata._db_id matches, or None when
    the id isn't in this history (stale panel state → the caller 404s rather
    than forking the wrong slice). Ids are compared as strings: the db id is an
    int in some rows and a str in others, and it round-trips through JSON/DOM
    datasets as text.
    """
    if msg_id is None or msg_id == "":
        return None
    target = str(msg_id)
    for i, m in enumerate(history or []):
        meta = m.get("metadata") if isinstance(m, dict) else None
        if not isinstance(meta, dict):
            continue
        did = meta.get("_db_id")
        if did is not None and str(did) == target:
            return i + 1
    return None


@app.post("/api/ody/session/{sid}/msg-delete")
async def ody_msg_delete(sid: str, req: Request) -> JSONResponse:
    """Delete ONE message (by its Odysseus db id) from a session."""
    try:
        msg_id = (await req.json()).get("msg_id")
    except Exception:
        msg_id = None
    if msg_id in (None, ""):
        return JSONResponse({"ok": False, "error": "msg_id required"}, status_code=400)
    try:
        r = await _ody_req("POST", f"/api/session/{sid}/delete-messages",
                           json={"msg_ids": [msg_id]})
        if r.status_code != 200:
            return JSONResponse({"ok": False, "error": r.text[:500]}, status_code=502)
        j = r.json() if r.content else {}
        return JSONResponse({"ok": True, "deleted": j.get("deleted", 0)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Odysseus unreachable: {e}"},
                            status_code=502)


@app.post("/api/ody/session/{sid}/msg-edit")
async def ody_msg_edit(sid: str, req: Request) -> JSONResponse:
    """Edit ONE message's text. Content-only — the model is NOT re-run."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    msg_id, content = body.get("msg_id"), body.get("content")
    if msg_id in (None, "") or content is None:
        return JSONResponse({"ok": False, "error": "msg_id and content required"},
                            status_code=400)
    try:
        r = await _ody_req("POST", f"/api/session/{sid}/edit-message",
                           json={"msg_id": msg_id, "content": content})
        if r.status_code != 200:
            return JSONResponse({"ok": False, "error": r.text[:500]}, status_code=502)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Odysseus unreachable: {e}"},
                            status_code=502)


@app.post("/api/ody/session/{sid}/fork-from")
async def ody_fork_from(sid: str, req: Request) -> JSONResponse:
    """Fork a new session containing everything up to (and incl.) `msg_id`."""
    try:
        msg_id = (await req.json()).get("msg_id")
    except Exception:
        msg_id = None
    if msg_id in (None, ""):
        return JSONResponse({"ok": False, "error": "msg_id required"}, status_code=400)
    try:
        hr = await _ody_req("GET", f"/api/history/{sid}")
        if hr.status_code != 200:
            return JSONResponse({"ok": False, "error": hr.text[:500]}, status_code=502)
        keep = fork_keep_count(hr.json().get("history") or [], msg_id)
        if keep is None:
            return JSONResponse({"ok": False, "error": "message not found in session"},
                                status_code=404)
        r = await _ody_req("POST", f"/api/session/{sid}/fork", json={"keep_count": keep})
        if r.status_code != 200:
            return JSONResponse({"ok": False, "error": r.text[:500]}, status_code=502)
        j = r.json() if r.content else {}
        return JSONResponse({"ok": True, "id": j.get("id"), "name": j.get("name"),
                             "kept": j.get("kept", keep)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Odysseus unreachable: {e}"},
                            status_code=502)


# ── Capabilities panel (Phase 1): aggregate Odysseus settings + route writes ──────
# One snapshot for the panel to render; one router for writes. Mirrors the _ody_req
# proxy style. Odysseus is the source of truth (shared with the Odysseus tab).

# The Phase-1 subset of app-settings the panel is allowed to see/edit. Kept explicit
# so we never leak the whole settings bag (which can hold *_api_key secrets).
CAPS_SETTING_KEYS = (
    "search_provider", "search_fallback_chain", "search_safesearch",
    "search_result_count", "agent_max_rounds", "agent_max_tool_calls",
    # Phase 3 — model pickers (Background-tasks + Utility). Empty string = "same
    # as chat" (Odysseus DEFAULT_SETTINGS defaults all four to "").
    "task_endpoint_id", "task_model", "utility_endpoint_id", "utility_model",
)


def caps_map_write(group: str, key: str, value):
    """PURE mapping: (group, key, value) → (method, path, body, encoding) for a caps
    write, or ("__error__", message, None, None) to reject. `encoding` is "json" or
    "form" (Odysseus's MCP toggle is form-encoded, everything else is JSON). Routes:
      feature       → POST /api/auth/features         (bool)          [Phase 1]
      setting       → POST /api/auth/settings         (allowlist)     [Phase 1]
      mcp_server    → PATCH /api/mcp/servers/{id}      form is_enabled [Phase 2]
      mcp_tools     → PATCH /api/mcp/servers/{id}/tools {disabled:[]} [Phase 2]
      builtin_tools → POST  /api/tools                 {disabled:[]}   [Phase 2]
    Secrets (`*_api_key`) are never forwarded; `setting` writes are confined to the
    Phase-1 allowlist so the panel can't reach arbitrary settings keys."""
    if not isinstance(key, str) or not key:
        return ("__error__", "missing key", None, None)
    if key.endswith("_api_key") or "api_key" in key:
        return ("__error__", "refusing to write a secret key", None, None)
    if group == "feature":
        return ("POST", "/api/auth/features", {key: bool(value)}, "json")
    if group == "setting":
        if key not in CAPS_SETTING_KEYS:
            return ("__error__", f"setting '{key}' not writable in Phase 1", None, None)
        return ("POST", "/api/auth/settings", {key: value}, "json")
    if group == "mcp_server":
        # key = server id; value = desired enabled state. Odysseus expects a form
        # field is_enabled="true"/"false" (see mcp_routes.toggle_server).
        return ("PATCH", f"/api/mcp/servers/{key}",
                {"is_enabled": "true" if value else "false"}, "form")
    if group == "mcp_tools":
        # key = server id; value = the FULL list of disabled tool names (replace).
        if not isinstance(value, list):
            return ("__error__", "mcp_tools value must be a list of tool names", None, None)
        return ("PATCH", f"/api/mcp/servers/{key}/tools", {"disabled": value}, "json")
    if group == "builtin_tools":
        # key is a placeholder (write is global); value = FULL list of disabled
        # built-in tool ids (replace). Writes settings["disabled_tools"].
        if not isinstance(value, list):
            return ("__error__", "builtin_tools value must be a list of tool ids", None, None)
        return ("POST", "/api/tools", {"disabled": value}, "json")
    if group == "skill_builtin":
        # key = built-in skill (TOOL_SECTIONS) name. IMPORTANT: Odysseus's
        # /api/skills/builtin is a TEXT-OVERRIDE store (PUT {text}) + a reset
        # (DELETE) — it is NOT an on/off switch. The real enable/disable of a
        # built-in tool lives in group 'builtin_tools' (→ POST /api/tools). So the
        # only boolean-safe write here is RESET (DELETE the override → shipped
        # default); enabling an override would need override TEXT the panel never
        # collects. Accept only a falsy value = "reset this override".
        # ⚠️ PENDING FABLE QA: built-in skills have no true on/off by design here.
        if value:
            return ("__error__",
                    "built-in skills have no on/off — send value:false to reset the "
                    "override; enable/disable is the Tools section", None, None)
        return ("DELETE", f"/api/skills/builtin/{key}", None, "none")
    return ("__error__", f"group '{group}' not supported", None, None)


@app.get("/api/ody/caps")
async def ody_caps() -> JSONResponse:
    """Aggregate the Phase-1 capabilities snapshot. Each sub-fetch is isolated so a
    partial failure still returns the rest. Phase 2/3 keys (mcp_servers,
    model_endpoints) are omitted for now."""
    out = {"features": {}, "settings": {}, "search_providers": [],
           "mcp_servers": [], "builtin_tools": [],
           "skills_builtin": [], "skills_user": [],
           "model_endpoints": [], "models": [], "errors": {}}
    try:
        r = await _ody_req("GET", "/api/auth/features")
        if r.status_code == 200 and isinstance(r.json(), dict):
            out["features"] = r.json()
        else:
            out["errors"]["features"] = r.text[:200]
    except Exception as e:
        out["errors"]["features"] = str(e)
    try:
        r = await _ody_req("GET", "/api/auth/settings")
        if r.status_code == 200 and isinstance(r.json(), dict):
            full = r.json()
            # only surface the Phase-1 subset — never leak the whole bag / secrets
            out["settings"] = {k: full.get(k) for k in CAPS_SETTING_KEYS if k in full}
        else:
            out["errors"]["settings"] = r.text[:200]
    except Exception as e:
        out["errors"]["settings"] = str(e)
    try:
        r = await _ody_req("GET", "/api/search/providers")
        if r.status_code == 200 and isinstance(r.json(), list):
            out["search_providers"] = r.json()
        else:
            out["errors"]["search_providers"] = r.text[:200]
    except Exception as e:
        out["errors"]["search_providers"] = str(e)
    # Phase 2 — connected tools (MCP servers) + built-in agent tools.
    try:
        r = await _ody_req("GET", "/api/mcp/servers")
        if r.status_code == 200 and isinstance(r.json(), list):
            out["mcp_servers"] = r.json()
        else:
            out["errors"]["mcp_servers"] = r.text[:200]
    except Exception as e:
        out["errors"]["mcp_servers"] = str(e)
    try:
        r = await _ody_req("GET", "/api/tools")
        doc = r.json() if r.status_code == 200 else None
        # Odysseus returns {"tools": [{"id","enabled"}]} (flat — no server-side
        # categories; the panel groups them for display).
        if isinstance(doc, dict) and isinstance(doc.get("tools"), list):
            out["builtin_tools"] = doc["tools"]
        else:
            out["errors"]["builtin_tools"] = r.text[:200]
    except Exception as e:
        out["errors"]["builtin_tools"] = str(e)
    # Skills — built-in tool-instruction blocks (name/description/is_overridden;
    # text-override + reset only) and the user's learned SKILL.md skills (read-only
    # here — full CRUD lives in the Odysseus tab).
    try:
        r = await _ody_req("GET", "/api/skills/builtin")
        doc = r.json() if r.status_code == 200 else None
        if isinstance(doc, dict) and isinstance(doc.get("builtin"), list):
            out["skills_builtin"] = doc["builtin"]
        else:
            out["errors"]["skills_builtin"] = r.text[:200]
    except Exception as e:
        out["errors"]["skills_builtin"] = str(e)
    try:
        r = await _ody_req("GET", "/api/skills")
        doc = r.json() if r.status_code == 200 else None
        # Odysseus returns {"skills": [...], "count": N}; be tolerant of a bare list.
        if isinstance(doc, dict) and isinstance(doc.get("skills"), list):
            out["skills_user"] = doc["skills"]
        elif isinstance(doc, list):
            out["skills_user"] = doc
        else:
            out["errors"]["skills_user"] = (r.text[:200] if r is not None else "no response")
    except Exception as e:
        out["errors"]["skills_user"] = str(e)
    # Phase 3 — model endpoints + models (for the Background-tasks / Utility pickers).
    # /api/model-endpoints (admin-only, reachable via our admin cookie) returns a
    # list of {id, name, models:[...], is_enabled, ...} — this is the primary
    # source for the pickers (endpoint id/name + its model ids). We also carry the
    # /api/models {items:[{endpoint_id, models, models_extra, ...}]} view for
    # completeness / cross-check. ⚠️ PENDING FABLE QA: shapes read from
    # vendor/odysseus/routes/model_routes.py @25c9e73.
    try:
        r = await _ody_req("GET", "/api/model-endpoints")
        if r.status_code == 200 and isinstance(r.json(), list):
            out["model_endpoints"] = r.json()
        else:
            out["errors"]["model_endpoints"] = r.text[:200]
    except Exception as e:
        out["errors"]["model_endpoints"] = str(e)
    try:
        r = await _ody_req("GET", "/api/models")
        doc = r.json() if r.status_code == 200 else None
        # /api/models returns {"hosts":[], "items":[...]}; be tolerant of a bare list.
        if isinstance(doc, dict) and isinstance(doc.get("items"), list):
            out["models"] = doc["items"]
        elif isinstance(doc, list):
            out["models"] = doc
        else:
            out["errors"]["models"] = (r.text[:200] if r is not None else "no response")
    except Exception as e:
        out["errors"]["models"] = str(e)
    return JSONResponse(out)


@app.get("/api/ody/mcp/{server_id}/tools")
async def ody_mcp_tools(server_id: str) -> JSONResponse:
    """Per-server MCP tool list with is_disabled state (fetched on-demand when a
    server row is expanded — kept out of the /caps snapshot so opening Capabilities
    doesn't fan out to every server's tools). ⚠️ PENDING FABLE QA."""
    try:
        r = await _ody_req("GET", f"/api/mcp/servers/{server_id}/tools")
        if r.status_code == 200 and isinstance(r.json(), list):
            return JSONResponse({"ok": True, "tools": r.json()})
        return JSONResponse({"ok": False, "error": r.text[:300]}, status_code=502)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Odysseus unreachable: {e}"}, status_code=502)


@app.post("/api/ody/mcp/add")
async def ody_mcp_add(req: Request) -> JSONResponse:
    """Register a new MCP server in Odysseus. Forwards to Odysseus's admin-only
    form endpoint (POST /api/mcp/servers). The panel sends JSON; we translate to the
    form fields Odysseus expects (name, transport, command, args JSON, env JSON, url).
    Adding a stdio server runs an arbitrary binary on the host — same trust surface as
    the Odysseus tab's own MCP page. ⚠️ PENDING FABLE QA: form field names mirror
    mcp_routes.add_server (@25c9e73)."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    name = (body.get("name") or "").strip()
    transport = (body.get("transport") or "stdio").strip()
    command = (body.get("command") or "").strip()
    url = (body.get("url") or "").strip()
    # args/env may arrive as a JSON string OR as a list/dict — normalise to a JSON string.
    def _as_json_str(v, default):
        if v is None or v == "":
            return default
        if isinstance(v, str):
            return v
        try:
            return json.dumps(v)
        except Exception:
            return default
    args = _as_json_str(body.get("args"), "[]")
    env = _as_json_str(body.get("env"), "{}")
    if not name:
        return JSONResponse({"ok": False, "error": "name is required"}, status_code=400)
    if transport == "stdio" and not command:
        return JSONResponse({"ok": False, "error": "command is required for stdio transport"}, status_code=400)
    if transport in ("sse", "http") and not url:
        return JSONResponse({"ok": False, "error": f"url is required for {transport} transport"}, status_code=400)
    form = {"name": name, "transport": transport, "args": args, "env": env}
    if command:
        form["command"] = command
    if url:
        form["url"] = url
    try:
        r = await _ody_req("POST", "/api/mcp/servers", data=form)
        if r.status_code == 200:
            return JSONResponse({"ok": True, "server": r.json()})
        return JSONResponse({"ok": False, "error": r.text[:300]}, status_code=502)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Odysseus unreachable: {e}"}, status_code=502)


@app.post("/api/ody/mcp/{server_id}/remove")
async def ody_mcp_remove(server_id: str) -> JSONResponse:
    """Delete an MCP server from Odysseus (DELETE /api/mcp/servers/{id})."""
    try:
        r = await _ody_req("DELETE", f"/api/mcp/servers/{server_id}")
        if r.status_code == 200:
            return JSONResponse({"ok": True})
        return JSONResponse({"ok": False, "error": r.text[:300]}, status_code=502)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Odysseus unreachable: {e}"}, status_code=502)


@app.post("/api/ody/caps/set")
async def ody_caps_set(req: Request) -> JSONResponse:
    """Route a single capability write to the right Odysseus endpoint. Odysseus
    validates/clamps server-side (e.g. agent_max_rounds 1-200)."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    group = body.get("group")
    key = body.get("key")
    value = body.get("value")
    method, path, jbody, enc = caps_map_write(group, key, value)
    if method == "__error__":
        return JSONResponse({"ok": False, "error": path}, status_code=400)
    try:
        if enc == "form":
            r = await _ody_req(method, path, data=jbody)
        elif enc == "none":            # DELETE with no body (e.g. reset a skill override)
            r = await _ody_req(method, path)
        else:
            r = await _ody_req(method, path, json=jbody)
        if r.status_code == 200:
            # echo the value Odysseus actually stored (it may clamp/coerce)
            stored = value
            try:
                doc = r.json()
                if isinstance(doc, dict) and key in doc:
                    stored = doc[key]
            except Exception:
                pass
            return JSONResponse({"ok": True, "group": group, "key": key, "value": stored})
        return JSONResponse({"ok": False, "error": r.text[:300]}, status_code=502)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Odysseus unreachable: {e}"}, status_code=502)
