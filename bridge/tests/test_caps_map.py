"""Unit tests for the PURE caps-write mapping (Capabilities panel Phase 1).

caps_map_write(group, key, value) → (method, path, json_body) or ("__error__", msg, None).
Guarantees: feature vs setting routing, unknown groups rejected, Phase-2/3 groups
rejected in Phase 1, secret (*_api_key) keys never forwarded, and `setting` writes
confined to the Phase-1 allowlist.
Run: python3 bridge/tests/test_caps_map.py  (from repo root).
"""
import os
import sys
from pathlib import Path

# Sandbox hygiene: importing bridge.app builds an httpx client at import time.
for _k in [k for k in os.environ if k.lower().endswith("_proxy")]:
    os.environ.pop(_k, None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from bridge.app import caps_map_write as m, CAPS_SETTING_KEYS  # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


# ── feature routing ──────────────────────────────────────────────────────────
check("feature → POST /api/auth/features",
      m("feature", "web_search", True) == ("POST", "/api/auth/features", {"web_search": True}, "json"))
check("feature value coerced to bool (truthy)",
      m("feature", "memory", 1) == ("POST", "/api/auth/features", {"memory": True}, "json"))
check("feature value coerced to bool (falsy)",
      m("feature", "gallery", 0) == ("POST", "/api/auth/features", {"gallery": False}, "json"))

# ── setting routing (allowlist) ──────────────────────────────────────────────
check("setting search_provider allowed",
      m("setting", "search_provider", "searxng") == ("POST", "/api/auth/settings", {"search_provider": "searxng"}, "json"))
check("setting agent_max_rounds passes value through (Odysseus clamps)",
      m("setting", "agent_max_rounds", 500) == ("POST", "/api/auth/settings", {"agent_max_rounds": 500}, "json"))
check("setting search_result_count allowed",
      m("setting", "search_result_count", 8) == ("POST", "/api/auth/settings", {"search_result_count": 8}, "json"))
check("all six Phase-1 setting keys route",
      all(m("setting", k, 1)[0] == "POST" for k in CAPS_SETTING_KEYS))

# ── Phase-2 groups: MCP servers, MCP per-tool, built-in tools ────────────────
check("mcp_server enable → PATCH form is_enabled=true",
      m("mcp_server", "srv123", True) == ("PATCH", "/api/mcp/servers/srv123", {"is_enabled": "true"}, "form"))
check("mcp_server disable → PATCH form is_enabled=false",
      m("mcp_server", "srv123", False) == ("PATCH", "/api/mcp/servers/srv123", {"is_enabled": "false"}, "form"))
check("mcp_tools → PATCH JSON {disabled:[...]}",
      m("mcp_tools", "srv123", ["a", "b"]) == ("PATCH", "/api/mcp/servers/srv123/tools", {"disabled": ["a", "b"]}, "json"))
check("mcp_tools empty list allowed (re-enable all)",
      m("mcp_tools", "srv123", []) == ("PATCH", "/api/mcp/servers/srv123/tools", {"disabled": []}, "json"))
check("mcp_tools non-list rejected", m("mcp_tools", "srv123", "nope")[0] == "__error__")
check("builtin_tools → POST /api/tools {disabled:[...]}",
      m("builtin_tools", "all", ["bash", "python"]) == ("POST", "/api/tools", {"disabled": ["bash", "python"]}, "json"))
check("builtin_tools empty list allowed (enable all)",
      m("builtin_tools", "all", []) == ("POST", "/api/tools", {"disabled": []}, "json"))
check("builtin_tools non-list rejected", m("builtin_tools", "all", "nope")[0] == "__error__")

# ── skill_builtin: reset-only (DELETE the override); no true on/off ───────────
check("skill_builtin reset (falsy) → DELETE /api/skills/builtin/{name}, no body",
      m("skill_builtin", "manage_memory", False) == ("DELETE", "/api/skills/builtin/manage_memory", None, "none"))
check("skill_builtin reset with 0 also routes to DELETE",
      m("skill_builtin", "web_search", 0) == ("DELETE", "/api/skills/builtin/web_search", None, "none"))
check("skill_builtin truthy (enable) rejected — no on/off, needs override text",
      m("skill_builtin", "manage_memory", True)[0] == "__error__")
check("skill_builtin empty key rejected", m("skill_builtin", "", False)[0] == "__error__")
check("skill_builtin *_api_key name still blocked",
      m("skill_builtin", "some_api_key", False)[0] == "__error__")

# ── setting NOT on the allowlist is rejected ─────────────────────────────────
check("arbitrary setting rejected", m("setting", "reminder_ntfy_topic", "x")[0] == "__error__")
check("task_endpoint_id (Phase 3) rejected as setting", m("setting", "task_endpoint_id", "e")[0] == "__error__")

# ── secret keys never forwarded ──────────────────────────────────────────────
check("brave_api_key blocked (setting)", m("setting", "brave_api_key", "sk")[0] == "__error__")
check("api_key substring blocked", m("setting", "google_pse_api_key", "sk")[0] == "__error__")
check("api_key blocked even as feature", m("feature", "some_api_key", True)[0] == "__error__")

# ── unknown / Phase-3 groups rejected ────────────────────────────────────────
check("unknown group rejected", m("bogus", "x", 1)[0] == "__error__")
check("model-picker group (Phase 3) still rejected", m("model", "task_model", "x")[0] == "__error__")

# ── malformed input ──────────────────────────────────────────────────────────
check("empty key rejected", m("feature", "", True)[0] == "__error__")
check("non-string key rejected", m("feature", None, True)[0] == "__error__")

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1)
print("all caps-map tests passed")
