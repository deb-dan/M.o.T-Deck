"""CORE — Hermes config generation, its mirrors, and the dashboard's credentials.

⚠️ _hermes_token / _hermes_port moved in here from the chat lane: they are config
reads (motdeck.yaml, data/hermes.token) that BOTH the hermes chat router and the
toolset-lever router need, and that shared need is what made those two routers
mutually dependent.
"""
from __future__ import annotations

import yaml
from .appctx import ROOT
from .events import publish
from .procs import cfg


# ── Hermes config generation ────────────────────────────────────────────────
# Hermes's own dashboard fetches its toolset/skill lists ONCE on mount
# (web/src/pages/SkillsPage.tsx:155-174 — the useEffect is keyed only on the
# profile) and patches its local state optimistically when ITS OWN switches are
# used (:180-186). A write made from THIS panel therefore leaves that page
# showing the state it had when it opened, and the shell's only reload rule was
# "backgrounded longer than staleAfter (600s)" — so within ten minutes of
# switching tabs the user is reading a frozen page and our lever looks broken.
#
# This counter is the signal that closes it: a monotonically increasing
# PROCESS-LIFETIME integer, bumped on every write WE make to Hermes's config
# surface, published on the EXISTING /api/status (the one endpoint the Swift
# shell already fetches — see portOpen in app/main.swift — so no new route and
# no new client). The shell records it when the Hermes webview loads and reloads
# that webview when it has increased since.
#
# PROCESS-LIFETIME is deliberate and sufficient: a bridge restart resets it to 0,
# which the shell reads as a DECREASE and records silently rather than treating
# as a change — so a restart can never cause a spurious reload. The shell also
# treats an absent/unparseable field as "no change", so an older bridge (or a
# bridge that is down) degrades to exactly today's behaviour.
_HERMES_CFG_GEN = 0


def _hermes_cfg_bump() -> int:
    """Record that we just changed Hermes's configuration; returns the new
    generation. Deliberately trivial: it is called immediately after a write that
    has ALREADY succeeded, so it must never be able to fail that write."""
    global _HERMES_CFG_GEN
    _HERMES_CFG_GEN += 1
    # SSE (2026-08-28): pushed as `config`. Same rider as nav's — the Swift shell's 4s
    # hermes_config_gen poll is UNTOUCHED (it reloads a webview, which is a different
    # decision from repainting a card, and it is the only consumer that can act on it).
    publish("config", gen=_HERMES_CFG_GEN)
    return _HERMES_CFG_GEN


def hermes_cfg_gen() -> int:
    """The current generation. 0 = we have written nothing this process."""
    return _HERMES_CFG_GEN


def _hermes_config_path() -> str:
    import os
    return os.path.join(os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes"),
                        "config.yaml")


def _hermes_write_mcp(name: str, entry: "dict | None") -> bool:
    """Add (entry) or remove (entry=None) ONE server in ~/.hermes/config.yaml's
    `mcp_servers`. No CLI (its prompts + live-connect would hang) and no connection
    attempt — Hermes reads the config at use-time, so it applies to NEW chats.
    Returns whether `name` is present afterwards.

    IDEMPOTENT: a no-op toggle doesn't rewrite the file at all, so the one write that
    does happen is the only one that loses comments/ordering (the accepted property of
    the yaml round-trip)."""
    import os
    home = os.path.dirname(_hermes_config_path())
    path = _hermes_config_path()
    if not os.path.exists(path):
        if entry is None:
            return False
        os.makedirs(home, exist_ok=True)
        data = {}
    else:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    servers = data.get("mcp_servers") or {}
    if entry is None:
        if name not in servers:
            return False                      # already absent — don't touch the file
        servers.pop(name, None)
    else:
        if servers.get(name) == entry:
            return True                       # already exact — don't touch the file
        servers[name] = dict(entry)
    data["mcp_servers"] = servers
    # Fable QA hardening: atomic write (temp + os.replace) so a concurrent save from
    # Hermes's own dashboard can never observe a half-written config.
    tmp = path + ".motdeck-tmp"
    with open(tmp, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False)
    os.replace(tmp, path)
    # Reached ONLY on a real write (both no-op branches return above), so an
    # idempotent toggle does not move the generation and cannot cause a reload.
    _hermes_cfg_bump()
    return name in servers


def _hermes_set_mcp(enable: bool) -> bool:
    """Browse toggle: add/remove the browsermcp stdio server (unchanged behaviour —
    now expressed through the shared single-server writer)."""
    return _hermes_write_mcp(
        "browsermcp",
        {"command": "npx", "args": ["@browsermcp/mcp"]} if enable else None)


def _hermes_get_mcp(name: str) -> "dict | None":
    try:
        with open(_hermes_config_path()) as f:
            data = yaml.safe_load(f) or {}
        srv = (data.get("mcp_servers") or {}).get(name)
        return srv if isinstance(srv, dict) else ({} if srv is not None else None)
    except Exception:
        return None


def _hermes_has_mcp(name: str = "browsermcp") -> bool:
    return _hermes_get_mcp(name) is not None


# ⚠️ MOVED HERE from app.py:5052-5073 by the router/core split (2026-08-28).
#    _hermes_token / _hermes_port read motdeck.yaml and data/hermes.token —
#    config access, and both the hermes lane and the toolset lever need them,
#    which is what made those two routers mutually dependent.

def _hermes_token() -> str:
    """Dashboard session token, matching start_component.sh's resolution order:
    motdeck.yaml components.hermes.dashboard_token override → else the
    generate-once file (data/hermes.token) the start script writes."""
    try:
        tok = str((cfg().get("components", {}).get("hermes", {}) or {})
                  .get("dashboard_token") or "").strip()
        if tok:
            return tok
    except Exception:
        pass
    try:
        return (ROOT / "data" / "hermes.token").read_text().strip()
    except Exception:
        return ""


def _hermes_port() -> int:
    try:
        return int(cfg().get("components", {}).get("hermes", {}).get("port") or 9119)
    except Exception:
        return 9119
