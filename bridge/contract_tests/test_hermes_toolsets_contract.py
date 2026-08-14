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


def test_toolsets_listing_carries_a_configured_bool():
    """`configured` on each /api/tools/toolsets row is our ONLY per-toolset setup
    signal, and it is upstream's own — the same field its Skills→TOOLSETS page
    prints "Setup needed" from. Our lever rows show a faint
    `needs setup in Hermes` pill off it, so a rename must trip here rather than
    silently make the pill vanish (we fail OPEN, so the failure is invisible).
    """
    src = _read("hermes_cli/web_routers/tools.py")
    i = src.index("/toolsets")
    win = src[i:i + 6000]
    assert '"configured"' in win, "the toolsets row lost its `configured` key"
    assert "_toolset_has_keys(" in win, \
        "`configured` is no longer produced by _toolset_has_keys"
    cfg = _read("hermes_cli/tools_config.py")
    assert "def _toolset_has_keys(" in cfg


def test_configured_is_optimistic_and_that_is_a_known_limit():
    """HONEST LIMIT, pinned so nobody "fixes" our pill by trusting it more.

    `_toolset_has_keys` returns True as soon as ANY provider in the category needs
    no env vars (Local Browser, Edge TTS), so `browser`/`tts` can report
    configured:true while a one-time post_setup install is still missing. The
    accurate predicate `_toolset_needs_configuration_prompt` exists but is NOT
    exposed over HTTP by any web router — if that changes, our pill should switch
    to it.
    """
    cfg = _read("hermes_cli/tools_config.py")
    assert "def _toolset_needs_configuration_prompt(" in cfg, \
        "the accurate needs-setup predicate moved or was renamed"
    # the no-key-provider short circuit that makes `configured` optimistic
    body = cfg[cfg.index("def _toolset_has_keys("):][:2500]
    assert "env_vars" in body
    # and it is still absent from every web router
    routers = ROOT / "vendor" / "hermes" / "hermes_cli" / "web_routers"
    leaked = [p.name for p in routers.glob("*.py")
              if "_toolset_needs_configuration_prompt" in
              p.read_text(encoding="utf-8", errors="replace")]
    assert not leaked, (
        "upstream now exposes _toolset_needs_configuration_prompt over HTTP "
        f"({leaked}) — the pill should use that instead of `configured`")


def test_upstreams_own_ui_uses_the_same_field_for_setup_needed():
    """Provenance: we mirror Hermes's own caption rather than inventing a rule."""
    page = _read("web/src/pages/SkillsPage.tsx")
    assert re.search(r"!\s*ts\.configured", page), \
        "Hermes's TOOLSETS page no longer branches its setup warning on !configured"


def test_toolsets_listing_carries_enabled_and_the_tool_list():
    """THE two fields the reconcile + verify slice stands on.

    `enabled` is what every switch in our Capabilities panel RENDERS — we never
    show our own last write — and `tools` is what the "Hermes will hand the model
    N tools" card counts. A rename of either would turn both surfaces into a
    confident lie (a missing `enabled` reads as off; a missing `tools` reads as
    zero), which is precisely the doubt this slice exists to remove.
    """
    src = _read("hermes_cli/web_routers/tools.py")
    i = src.index("/toolsets")
    win = src[i:i + 6000]
    assert '"enabled": is_enabled' in win, \
        "the toolsets row lost its `enabled` key or stopped computing it"
    assert '"tools": tools' in win, "the toolsets row lost its resolved `tools` list"
    assert "resolve_toolset(name)" in win, \
        "`tools` is no longer the resolved toolset (our count would stop matching)"
    # `enabled` is derived from the platform toolset list — the same key our
    # switches write — not from some separate per-row flag.
    assert "_get_platform_tools(" in win
    assert "enabled_by_platform[target_platform]" in win


def test_available_is_an_alias_of_enabled_not_a_readiness_flag():
    """Recorded so a future reader does not reach for `available` thinking it means
    "ready to use" — at this pin it is literally the same bool."""
    src = _read("hermes_cli/web_routers/tools.py")
    win = src[src.index("/toolsets"):][:6000]
    assert '"available": is_enabled' in win


def test_gateway_always_folds_in_the_project_toolset():
    """Our verify card reports these three tools SEPARATELY because no switch in
    the panel controls them: the lane's resolver adds `project` unconditionally,
    and `project` is not a configurable toolset, so it has no row. If this fold
    disappears (or the toolset's tools change), the card's total would silently
    stop matching what Hermes hands the model.
    """
    src = _read("tui_gateway/server.py")
    assert re.search(r'return sorted\(enabled \| \{"project"\}\)', src), \
        "the gateway no longer folds `project` into every session's toolsets"
    ts = _read("toolsets.py")
    block = ts[ts.index('"project": {'):][:400]
    for tool in ("project_list", "project_create", "project_switch"):
        assert tool in block, f"the project toolset no longer declares {tool}"
    cfg = _read("hermes_cli/tools_config.py")
    head = cfg[cfg.index("CONFIGURABLE_TOOLSETS = ["):]
    head = head[:head.index("\n]")]
    assert '("project"' not in head, \
        "`project` became configurable — it now has a row and must not be " \
        "double-counted as an always-on extra"


def test_skill_index_gate_is_the_three_skill_tool_names():
    """Our card says "skill index: PRESENT/ABSENT" from exactly upstream's own
    predicate, computed over TOOL names so a toolset rename cannot fool it."""
    src = _read("agent/system_prompt.py")
    assert re.search(
        r"has_skills_tools\s*=\s*any\(\s*name in agent\.valid_tool_names\s+for name in "
        r"\['skills_list', 'skill_view', 'skill_manage'\]\)", src), \
        "the <available_skills> gate is no longer those three tool names"
    assert 'skills_prompt = ""' in src, \
        "an ungated skills prompt would make our ABSENT verdict wrong"


def test_the_banner_reports_zero_skills_when_the_toolset_is_off():
    """Provenance for the two-layer sentence on the skills row: Hermes's OWN banner
    already reports 0 skills with the toolset off, while the library on disk is
    untouched. Our wording mirrors that rather than inventing a distinction."""
    src = _read("hermes_cli/banner.py")
    assert '_skills_enabled = (not _enabled_ts) or ("skills" in _enabled_ts)' in src
    assert "Skills toolset disabled" in src
    assert 'summary_parts = [f"{len(tools)} tools", f"{total_skills} skills"]' in src, \
        "the banner's tools/skills summary line moved — the numbers our verify " \
        "card is meant to match are computed there"


def test_the_listing_excludes_default_mcp_servers():
    """The honest limit our card prints: the listing resolves WITHOUT default MCP
    servers while the runtime resolve includes them, so MCP tools are not in our
    count."""
    src = _read("hermes_cli/web_routers/tools.py")
    win = src[src.index("/toolsets"):][:6000]
    assert "include_default_mcp_servers=False" in win
    gw = _read("tui_gateway/server.py")
    assert re.search(r'_get_platform_tools\(cfg, "cli", include_default_mcp_servers=True\)', gw)


# ── PLATFORM: which rows the lever governs ───────────────────────────────────
# Debi's live report ("our page and Hermes's page disagree in both directions")
# put the platform question at the centre, so every fact the scope now depends on
# is pinned here. The finding these pins encode: our panel and Hermes's own
# Skills → TOOLSETS page read the SAME field of the SAME endpoint, and that field
# is computed PER ROW for that row's own configuration platform.

def test_listing_computes_enabled_for_each_rows_own_platform():
    """`GET /api/tools/toolsets` does not serve one platform — it resolves the
    enabled set for EACH row's own configuration platform and reports it as
    `platform` on the row.

    This is the fact that refutes "the listing serves a different platform than we
    write": the same helper decides the row's platform for both the READ and the
    PUT, so an ordinary toolset's `enabled` is its `platform_toolsets.cli` state,
    which is exactly what our lane resolves.
    """
    src = _read("hermes_cli/web_routers/tools.py")
    assert "_toolset_configuration_platform(name)" in src
    assert "enabled_by_platform = {" in src, \
        "the listing no longer resolves per-platform enabled sets"
    assert re.search(
        r"enabled_by_platform\[target_platform\]", src), \
        "the row's enabled is no longer taken from its own platform's set"
    assert '"platform": target_platform' in src, \
        "rows no longer carry the platform their PUT writes"
    assert '"platform_label"' in src


def test_the_put_writes_the_same_platform_the_listing_reported():
    """The write target is `_toolset_configuration_platform(name)` — the identical
    call the listing used. Read and write can therefore not disagree about which
    `platform_toolsets.<x>` key a row belongs to."""
    src = _read("hermes_cli/web_routers/tools.py")
    put = src.split('@router.put("/api/tools/toolsets/{name}")')[1].split("@router.")[0]
    assert "target_platform = _toolset_configuration_platform(name)" in put
    assert "_save_platform_tools(config, target_platform, enabled)" in put


def test_configuration_platform_is_cli_except_for_restricted_toolsets():
    """`_toolset_configuration_platform` defaults to "cli" and only diverges for a
    toolset pinned to another platform by `_TOOLSET_PLATFORM_RESTRICTIONS`.

    Those rows are the ones our lever must NOT count or preset: their PUT writes
    `platform_toolsets.discord`, and `_toolset_allowed_for_platform` means a cli
    session can never be given their tools.
    """
    src = _read("hermes_cli/tools_config.py")
    assert 'def _toolset_configuration_platform(ts_key: str, default: str = "cli")' in src, \
        "the configuration-platform default is no longer cli"
    assert "def _toolset_allowed_for_platform(" in src
    assert "_TOOLSET_PLATFORM_RESTRICTIONS" in src
    m = re.search(r"_TOOLSET_PLATFORM_RESTRICTIONS:\s*Dict\[str,\s*Set\[str\]\]\s*=\s*\{(.*?)\n\}",
                  src, re.S)
    assert m, "the platform-restriction map moved or changed shape"
    assert '"discord"' in m.group(1) and '"discord_admin"' in m.group(1)


def test_config_only_toolsets_are_not_platform_toolsets_at_all():
    """`stt` is in `_CONFIG_ONLY_TOOLSETS`: its row's `enabled` comes from
    `config.stt.enabled` and its PUT writes that section, NOT platform_toolsets.

    It ships zero tool schemas, so a preset that switched it off saved nothing in
    the prompt and silently disabled Hermes's speech-to-text. Our mirror of this
    set is asserted byte-identical below.
    """
    from bridge.app import HERMES_CONFIG_ONLY_TOOLSETS
    src = _read("hermes_cli/tools_config.py")
    m = re.search(r"_CONFIG_ONLY_TOOLSETS\s*=\s*\{([^}]*)\}", src)
    assert m, "_CONFIG_ONLY_TOOLSETS moved or changed shape"
    upstream = {s.strip().strip('"\'') for s in m.group(1).split(",") if s.strip()}
    assert upstream == set(HERMES_CONFIG_ONLY_TOOLSETS), (
        f"our HERMES_CONFIG_ONLY_TOOLSETS mirror is stale: upstream={upstream}")
    routes = _read("hermes_cli/web_routers/tools.py")
    assert "_CONFIG_ONLY_TOOLSETS" in routes
    assert 'section["enabled"] = bool(body.enabled)' in routes, \
        "the config-only PUT no longer writes its own config section"


def test_default_off_toolsets_mirror_is_current():
    """`_DEFAULT_OFF_TOOLSETS` is what upstream subtracts when it expands the
    platform composite — i.e. the toolsets Hermes ships OFF.

    Our "Hermes's defaults" preset subtracts the same set. Before this pin, the
    preset sent every catalog name, which is what turned Video Analysis on for a
    user who never asked for it. A release that adds or removes a default-off
    toolset must trip here rather than drift.
    """
    from bridge.app import HERMES_DEFAULT_OFF_TOOLSETS
    src = _read("hermes_cli/tools_config.py")
    m = re.search(r"_DEFAULT_OFF_TOOLSETS\s*=\s*\{([^}]*)\}", src)
    assert m, "_DEFAULT_OFF_TOOLSETS moved or changed shape"
    upstream = {s.strip().strip('"\'') for s in m.group(1).split(",") if s.strip()}
    assert upstream == set(HERMES_DEFAULT_OFF_TOOLSETS), (
        f"our HERMES_DEFAULT_OFF_TOOLSETS mirror is stale: upstream={upstream}")
    assert "video" in upstream, "Video Analysis is no longer default-off upstream"
    assert "enabled_toolsets -= default_off" in src, \
        "the default-off set is no longer subtracted from the composite expansion"


def test_upstream_skills_page_reads_the_same_endpoint_and_field():
    """Hermes's own Skills → TOOLSETS page renders `ts.enabled` from
    `GET /api/tools/toolsets` — the identical field our switches render.

    So the two surfaces cannot structurally disagree; a disagreement can only be
    staleness. Which is the next pin.
    """
    api = _read("web/src/lib/api.ts")
    assert re.search(r"getToolsets:\s*\(profile\?: string\)\s*=>", api)
    assert '`/api/tools/toolsets${profileQuery(profile)}`' in api
    page = _read("web/src/pages/SkillsPage.tsx")
    assert "api.getToolsets(" in page
    assert "ts.enabled" in page and "t.common.active" in page, \
        "the active/inactive badge no longer comes from the row's enabled field"


def test_upstream_skills_page_does_not_live_refresh():
    """The page fetches its toolset list ONCE per mount (a useEffect keyed only on
    the selected profile) and otherwise only after its own Configure drawer writes.

    This is the whole reason a cross-check between the two apps disagrees in both
    directions: our panel re-reads Hermes on every refresh and after every write;
    Hermes's page keeps whatever it fetched when the tab was opened. Our group
    header now says so and tells the user to reload that tab. If upstream ever adds
    polling or an invalidation, this pin trips and that sentence can be dropped.
    """
    page = _read("web/src/pages/SkillsPage.tsx")
    body = page.split("api.getToolsets(selectedProfile")[1].split("const handleToggleSkill")[0]
    assert "}, [selectedProfile]);" in body, \
        "the toolsets fetch effect's dependency list changed — re-check staleness"
    assert "setInterval" not in page and "useSWR" not in page and "refetchInterval" not in page, \
        "the Skills page appears to poll now; the panel's stale-tab warning may be obsolete"
