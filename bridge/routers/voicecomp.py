"""ROUTER — the voice COMPONENTS and their in-process MCP registration."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from ..core.appctx import app
from ..core.hermescfg import _hermes_has_mcp, _hermes_write_mcp
from ..core.procs import _port_alive, cfg
from .misc import _ody_find_mcp, _ody_mcp_list
from .ody import _ody_req


# ── Voice components: register their in-process MCP servers ──────────────────
# Both optional voice components mount an MCP server IN-PROCESS on their own port
# (streamable HTTP at <base>/mcp), so wiring them into the agents is EXACTLY the
# browse-toggle mechanism — Odysseus via its live admin API, Hermes via the yaml
# round-trip of ~/.hermes/config.yaml. The helpers above were generalised for this
# rather than copy-pasted twice.
#
# The `tools` lists are DISPLAY ONLY (each host discovers the real list itself over
# MCP). VoiceStudio's are read from vendor backend/mcp_server.py — RE-VERIFIED at the
# 2026-08-28 v0.4.2 → v0.5.0 bump: all seven tool names still defined, and the mount is
# byte-for-byte the same shape (`streamable_http_path = "/"` + `app.mount("/mcp", …)`),
# so the registered `<base>/mcp` url is unchanged. The only MCP-side difference is the
# FastMCP server's own display name ("OmniVoice Studio" → "VoiceStudio"), which nothing
# of ours keys off. A live `initialize` handshake against POST <base>/mcp/ returns
# protocolVersion 2025-06-18 + tools capability. Voicebox's list still comes from the
# Phase-0 recon notes. ⚠️ PENDING FABLE QA.
VOICE_MCP = {
    "voicestudio": {
        "label": "VoiceStudio",
        "path": "/mcp",
        "tools": ["generate_speech", "clone_voice", "transcribe", "list_voices",
                  "list_personalities", "list_languages", "check_health"],
        # mount_mcp() sets streamable_http_path="/" and mounts the sub-app at "/mcp",
        # so the endpoint is exactly <base>/mcp (upstream's own comment says so).
        # Upstream resolves a per-agent voice binding from an X-OmniVoice-Client-Id
        # REQUEST HEADER; neither host lets us attach custom headers to an http MCP
        # entry, so our calls fall back to the GLOBAL default voice. Graceful, but
        # VoiceStudio's Settings → MCP per-agent binding will not apply to us.
        "note": "per-agent voice binding (X-OmniVoice-Client-Id) can't be sent — "
                "generate_speech uses VoiceStudio's global default voice",
    },
    "voicebox": {
        "label": "Voicebox",
        "path": "/mcp",
        "tools": ["voicebox.speak", "voicebox.transcribe",
                  "voicebox.list_captures", "voicebox.list_profiles"],
        "note": "no auth of any kind — keep it on 127.0.0.1 (never expose via M5)",
    },
}


def voice_mcp_spec(name: str, port) -> "dict | None":
    """PURE: (component name, port) → the registration payloads for BOTH hosts, or
    None for an unknown component / unusable port. Kept pure so the wire shapes are
    unit-testable without a live Odysseus or a ~/.hermes on disk.

      odysseus_form — mcp_routes.add_server is FORM-encoded and takes
                      name/transport/command/args/env/url; http transport needs `url`.
      hermes_entry  — Hermes's url-only shape (mcp_config.cmd_mcp_add:
                      `server_config["url"] = url`) = streamable HTTP.
    """
    meta = VOICE_MCP.get(name)
    if not meta:
        return None
    try:
        p = int(port)
    except (TypeError, ValueError):
        return None
    if p <= 0 or p > 65535:
        return None
    url = f"http://127.0.0.1:{p}{meta['path']}"
    return {
        "name": name,
        "label": meta["label"],
        "url": url,
        "tools": list(meta["tools"]),
        "note": meta["note"],
        "odysseus_form": {"name": name, "transport": "http", "url": url,
                          "args": "[]", "env": "{}"},
        "hermes_entry": {"url": url},
    }


def _voice_comp(name: str) -> dict:
    return (cfg().get("components", {}) or {}).get(name) or {}


@app.get("/api/voice/status")
async def voice_status() -> JSONResponse:
    """Per-host registration state for every voice component. Mirrors browse_status's
    honesty contract: `odysseus` and `hermes` are reported SEPARATELY so the panel can
    show a partial registration instead of a single lying switch. `odysseus_known` is
    False when Odysseus couldn't be asked at all (down ≠ not registered)."""
    try:
        ody = await _ody_mcp_list()
    except Exception:
        ody = None
    out = {"ok": True, "components": {}}
    for name in VOICE_MCP:
        comp = _voice_comp(name)
        port = comp.get("port")
        spec = voice_mcp_spec(name, port)
        srv = None
        if ody is not None:
            srv = next((s for s in ody if s.get("name") == name), None)
        try:
            running = bool(await _port_alive(int(port))) if port else False
        except (TypeError, ValueError):
            running = False
        hermes = _hermes_has_mcp(name)
        out["components"][name] = {
            "label": VOICE_MCP[name]["label"],
            "url": (spec or {}).get("url"),
            "tools": VOICE_MCP[name]["tools"],
            "note": VOICE_MCP[name]["note"],
            "port": port,
            "installed": bool(comp.get("installed")),
            "running": running,
            "odysseus": bool(srv),
            "odysseus_known": ody is not None,
            "hermes": hermes,
            "connected": (srv or {}).get("status") == "connected",
            "on": bool(srv) or hermes,
        }
    return JSONResponse(out)


@app.post("/api/voice/toggle")
async def voice_toggle(req: Request) -> JSONResponse:
    """Register/remove a voice component's MCP server in BOTH Odysseus (live API) and
    Hermes (config.yaml → new Hermes chats). One control → both components, exactly
    like the Browse toggle.

    Idempotent: enabling an already-registered server is a no-op on both hosts (a
    stale URL — e.g. the port changed in harness.yaml — is re-registered); disabling
    an absent one likewise. Turning ON is REFUSED when the component isn't installed
    or isn't listening, because registering a dead URL only buys connection errors in
    every subsequent turn. Turning OFF is always allowed (it is the cleanup path)."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    name = str(body.get("name") or "").strip()
    on = bool(body.get("on"))
    if name not in VOICE_MCP:
        return JSONResponse({"ok": False, "error": f"unknown voice component '{name}'"},
                            status_code=400)
    comp = _voice_comp(name)
    spec = voice_mcp_spec(name, comp.get("port"))
    if spec is None:
        return JSONResponse({"ok": False,
                             "error": f"components.{name}.port is missing or invalid in harness.yaml"},
                            status_code=400)
    if on:
        if not comp.get("installed"):
            return JSONResponse({"ok": False, "error":
                                 f"{spec['label']} isn't installed yet — install it in MOT Main first"},
                                status_code=409)
        if not await _port_alive(int(comp["port"])):
            return JSONResponse({"ok": False, "error":
                                 f"{spec['label']} isn't running — start it in MOT Main first "
                                 f"(nothing is listening on :{comp['port']})"},
                                status_code=409)
    log, ody_on, hermes_on = [], None, None   # None = the host couldn't be reached
    try:
        existing = await _ody_find_mcp(name)
        if on:
            if existing and (existing.get("url") or "") != spec["url"]:
                r = await _ody_req("DELETE", f"/api/mcp/servers/{existing['id']}")
                log.append(f"odysseus-stale-del:{r.status_code}")
                existing = None
            if existing:
                log.append("odysseus:already")
                ody_on = True
            else:
                r = await _ody_req("POST", "/api/mcp/servers", data=spec["odysseus_form"])
                log.append(f"odysseus:{r.status_code}")
                ody_on = r.status_code == 200
        else:
            if existing:
                r = await _ody_req("DELETE", f"/api/mcp/servers/{existing['id']}")
                log.append(f"odysseus-del:{r.status_code}")
                ody_on = r.status_code != 200      # still registered iff the delete failed
            else:
                log.append("odysseus:absent")
                ody_on = False
    except Exception as e:
        log.append(f"odysseus-err:{str(e)[:120]}")
    try:
        hermes_on = _hermes_write_mcp(name, spec["hermes_entry"] if on else None)
        log.append("hermes:ok")
    except Exception as e:
        log.append(f"hermes-err:{str(e)[:120]}")
        hermes_on = _hermes_has_mcp(name)
    line = " · ".join(log)
    print(f"[voice] {name} mcp {'on' if on else 'off'} → {line}", flush=True)
    # ok = at least one host reached the requested state; `partial` says the other
    # didn't, and the panel renders both per-host pills so nothing is hidden.
    reached = [(ody_on is on), (hermes_on is on)]
    return JSONResponse({"ok": any(reached), "on": on, "partial": not all(reached),
                         "odysseus": bool(ody_on), "hermes": bool(hermes_on),
                         "log": line})
