"""Hermes toolset-trimming contract — pin-bump gate for the Hermes-tools lever.

The lever (bridge/app.py `/api/hermes/toolsets`, panel Capabilities → Tools →
"Hermes tools") trims the Hermes lane's system prompt by editing which toolsets
the model is handed. Every fact it relies on is upstream-INTERNAL, so this purely
static check greps the vendored source and fails loudly if a pin bump moves any
of them. No network, no build, no running Hermes.

Run: pytest bridge/contract_tests/ (from harness root).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERMES = ROOT / "vendor" / "hermes"


def _read(rel: str) -> str:
    p = HERMES / rel
    assert p.exists(), f"vendored file missing: {rel}"
    return p.read_text(encoding="utf-8", errors="replace")


def test_config_key_is_platform_toolsets_not_a_tools_key():
    """The key is `platform_toolsets.<platform>` — read by _get_platform_tools.

    Pinned because the obvious guesses (`tools.disabled_toolsets`,
    `tools.enabled_toolsets`, `toolsets.enabled`) DO NOT EXIST at this pin; if a
    future tag introduces one, the lever should be reconsidered, not silently
    left writing a key that stopped mattering.
    """
    src = _read("hermes_cli/tools_config.py")
    assert "def _get_platform_tools(" in src
    assert 'config.get("platform_toolsets")' in src, \
        "platform_toolsets is no longer the key _get_platform_tools reads"
    assert 'platform_toolsets.get(platform)' in src


def test_agent_disabled_toolsets_is_subtracted_last():
    """`agent.disabled_toolsets` overrides everything — the panel marks any name
    sitting in it as 'forced off in config' precisely because re-enabling it from
    platform_toolsets can never win."""
    src = _read("hermes_cli/tools_config.py")
    assert 'agent_cfg.get("disabled_toolsets")' in src
    assert "enabled_toolsets -= disabled_set" in src, \
        "agent.disabled_toolsets is no longer a plain subtraction"
    defaults = _read("hermes_cli/config_defaults.py")
    assert '"disabled_toolsets"' in defaults, \
        "agent.disabled_toolsets vanished from DEFAULT_CONFIG"


def test_hermes_lane_resolves_toolsets_for_the_cli_platform():
    """Our lane is the dashboard's TUI gateway, and it resolves the model's
    toolsets for platform "cli" — so `platform_toolsets.cli` is the list the
    Hermes chat lane actually reads. If this platform string changes, every
    switch in the panel would write the wrong key while still reporting success.
    """
    src = _read("tui_gateway/server.py")
    assert "def _load_enabled_toolsets(" in src
    assert re.search(r'_get_platform_tools\(\s*cfg,\s*"cli"', src), \
        'the TUI gateway no longer resolves toolsets for the "cli" platform'
    assert "enabled_toolsets=_load_enabled_toolsets()" in src, \
        "the agent factory no longer consumes _load_enabled_toolsets()"


def test_empty_toolset_list_still_means_ALL_tools():
    """The footgun the bridge refuses (HERMES_TOOLSETS_EMPTY_REASON): an empty
    resolved set makes _load_enabled_toolsets return None, which
    get_tool_definitions reads as 'no restriction' — i.e. every toolset. Turning
    the last switch off would ADD tools. If upstream ever makes empty mean empty,
    this test fails and the guard can be relaxed deliberately."""
    src = _read("tui_gateway/server.py")
    body = src[src.index("def _load_enabled_toolsets("):]
    body = body[:body.index("\ndef ", 10)]
    assert re.search(r"if not enabled:\s*\n\s*return None", body), \
        "the empty-set → None → all-toolsets behaviour changed"


def test_focus_mode_bypasses_the_configured_list():
    """`agent.coding_context: "focus"` makes coding_selection() return a list and
    _load_enabled_toolsets RETURN EARLY, so the panel's switches would be
    cosmetic. The panel detects focus and locks them; pinned so a change in which
    modes short-circuit is caught."""
    server = _read("tui_gateway/server.py")
    assert "from agent.coding_context import coding_selection" in server
    assert re.search(r"if selection is not None:", server), \
        "the TUI gateway no longer short-circuits on coding_selection()"
    cc = _read("agent/coding_context.py")
    assert re.search(r'if self\.config_mode != "focus":\s*\n\s*return None', cc), \
        "toolset_selection is no longer focus-only — it may now override the " \
        "configured toolset list under the DEFAULT coding_context"
    defaults = _read("hermes_cli/config_defaults.py")
    assert '"coding_context"' in defaults


def test_config_is_read_at_use_time_so_no_restart_is_needed():
    """The lever promises "takes effect on the next chat, no restart". That rests
    on three caches all being config-mtime keyed rather than import-time frozen."""
    cfg = _read("hermes_cli/config.py")
    assert "st_mtime_ns" in cfg, "config reads are no longer mtime-invalidated"
    tools = _read("hermes_cli/tools_config.py")
    body = tools[tools.index("def _get_platform_tools("):]
    body = body[:body.index("\ndef ", 10)]
    assert "lru_cache" not in body and "@cache" not in body, \
        "_get_platform_tools grew a cache — a config edit may no longer apply " \
        "to the next chat without restarting Hermes"
    mt = _read("model_tools.py")
    assert "st_mtime_ns" in mt, \
        "get_tool_definitions' memo key no longer includes the config mtime"


def test_dashboard_probe_and_write_routes_exist():
    """The bridge PROBES the catalog and WRITES through Hermes's own routes rather
    than hardcoding toolset names or hand-editing the yaml, so both must exist."""
    src = _read("hermes_cli/web_routers/tools.py")
    assert '@router.get("/api/tools/toolsets")' in src
    assert '@router.put("/api/tools/toolsets/{name}")' in src
    # The read shape the panel renders from.
    for key in ('"name":', '"label":', '"description":', '"enabled":', '"tools":',
                '"platform":'):
        assert key in src, f"GET /api/tools/toolsets no longer returns {key}"
    # The write must still persist via the shared helper (which is what preserves
    # MCP-server names parked in the same list and routes restricted toolsets).
    assert "_save_platform_tools(config, target_platform, enabled)" in src, \
        "PUT /api/tools/toolsets no longer persists via _save_platform_tools"
    assert "_save_platform_tools" in _read("hermes_cli/tools_config.py")


def test_toolset_toggle_body_key_is_enabled():
    """The bridge PUTs {"enabled": bool}; upstream's model must still expect it."""
    models = _read("hermes_cli/web_models.py")
    m = re.search(r"class ToolsetToggle\b.*?(?=\nclass |\Z)", models, re.S)
    assert m, "ToolsetToggle model is gone"
    assert re.search(r"\benabled\s*:", m.group(0)), \
        'ToolsetToggle no longer carries an "enabled" field'


def test_dashboard_api_is_token_gated_with_the_header_we_send():
    """The probe/write reuse the lane's existing X-Hermes-Session-Token header."""
    src = _read("hermes_cli/web_server.py")
    assert "X-Hermes-Session-Token" in src, \
        "the dashboard session-token header was renamed"


def test_skills_index_rides_on_the_skills_toolset():
    """The panel calls `skills` the biggest lever because disabling it drops the
    ENTIRE <available_skills> block, not just three tool schemas."""
    src = _read("agent/system_prompt.py")
    assert re.search(
        r"has_skills_tools\s*=\s*any\(.*skills_list.*skill_view.*skill_manage",
        src, re.S), "the skills-index gate no longer keys off the skills tools"
    assert re.search(r"else:\s*\n\s*skills_prompt = \"\"", src), \
        "the skill index is no longer suppressed when the skills tools are absent"
    ts = _read("toolsets.py")
    m = re.search(r'"skills":\s*\{.*?\}', ts, re.S)
    assert m and "skills_list" in m.group(0), \
        "the `skills` toolset no longer contains skills_list"


def test_minimal_preset_names_are_real_configurable_toolsets():
    """The floor set the "Minimal preset" chip writes must be togglable at this
    pin — a name outside CONFIGURABLE_TOOLSETS would 400 on the upstream PUT."""
    import sys
    sys.path.insert(0, str(ROOT))
    from bridge.app import HERMES_MINIMAL_TOOLSETS

    src = _read("hermes_cli/tools_config.py")
    block = src[src.index("CONFIGURABLE_TOOLSETS = ["):]
    block = block[:block.index("\n]")]
    names = set(re.findall(r'^\s*\("([a-z0-9_]+)"', block, re.M))
    assert names, "could not parse CONFIGURABLE_TOOLSETS"
    missing = [n for n in HERMES_MINIMAL_TOOLSETS if n not in names]
    assert not missing, \
        f"minimal-preset toolsets are no longer configurable upstream: {missing}"
    # And none of them is default-off, so 'minimal' is reachable from a fresh install.
    off = re.search(r"_DEFAULT_OFF_TOOLSETS\s*=\s*\{([^}]*)\}", src)
    assert off, "_DEFAULT_OFF_TOOLSETS is gone"
    off_names = set(re.findall(r'"([a-z0-9_]+)"', off.group(1)))
    assert not (set(HERMES_MINIMAL_TOOLSETS) & off_names), \
        "a minimal-preset toolset became default-off upstream"
