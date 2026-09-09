"""ROUTER — the Hermes TOOLSET and per-SKILL trimming levers, and the browse toggle."""
from __future__ import annotations

import yaml
from fastapi import Request
from fastapi.responses import JSONResponse
from ..core.appctx import app
from ..core.hermescfg import _hermes_cfg_bump, _hermes_config_path, _hermes_has_mcp, _hermes_port, _hermes_set_mcp, _hermes_token
from .misc import _BROWSERMCP, _ody_find_mcp
from .ody import _ody_req


# ── Hermes TOOLSET TRIMMING LEVER ────────────────────────────────────────────
# WHY: the Hermes lane hands the model every enabled toolset's schema PLUS the whole
# skill index, which on a small local model is minutes of prefill before a single
# token comes back. Trimming the toolset list is the lever.
#
# THE MECHANISM, read out of the pin (v2026.8.13), not guessed:
#   • Our lane is the dashboard's JSON-RPC gateway (tui_gateway). It resolves the
#     model's toolsets in `_load_enabled_toolsets()` (tui_gateway/server.py:4267),
#     consumed per session build at server.py:6708 — via
#     `_get_platform_tools(cfg, "cli", include_default_mcp_servers=True)`
#     (server.py:4399). So the key is `platform_toolsets.cli`, NOT some `tools.*`
#     key: `tools.disabled_toolsets` / `enabled_toolsets` / `toolsets.enabled` DO
#     NOT EXIST. (Top-level `toolsets:` exists but is vestigial — only kanban and
#     `hermes dump` read it.)
#   • ⚠️ v2026.8.13 PARAMETERISED that resolver — `_load_enabled_toolsets(platform)`
#     — and the argument is a TRAP for a reader skimming it: it is the SESSION'S
#     SOURCE (`session.create`'s `source` field, resolved by `_resolve_agent_platform`
#     → `_resolve_session_source`, server.py:3685-3699), NOT the
#     `platform_toolsets.<x>` config key. The config read on line 4399 is still
#     HARDCODED `"cli"`. The session source only picks the CLIENT-SURFACE toolsets
#     folded in on top (`_gui_surface_toolsets`, server.py:4246 — see
#     HERMES_GATEWAY_ALWAYS_TOOLSET below). So this lever's key is unchanged.
#   • `_get_platform_tools` (hermes_cli/tools_config.py:2262) has NO memoisation and
#     `load_config()` is mtime+size keyed (hermes_cli/config.py:3105), and
#     `get_tool_definitions`'s own memo key includes the config mtime
#     (model_tools.py:320-336) — so a config edit takes effect on the NEXT CHAT
#     with NO Hermes restart. That is why this endpoint never asks for one.
#   • `agent.disabled_toolsets` (default [], config_defaults.py:228) is subtracted
#     LAST (tools_config.py:2530) — we never write it, but we REPORT it,
#     because a name sitting in there can never be re-enabled from this panel.
#   • `agent.coding_context: "focus"` (default "auto", config_defaults.py:131) makes
#     `coding_selection()` return a toolset list and `_load_enabled_toolsets()`
#     RETURNS EARLY (server.py:4285-4293) — the config list is then never read at
#     all. Only `focus` does this (agent/coding_context.py:517-521), so the default
#     is safe, but we detect it and say so rather than showing dead switches.
#
# WRITES GO THROUGH HERMES'S OWN WRITER, not our yaml round-trip:
#   `PUT /api/tools/toolsets/{name}` (hermes_cli/web_routers/tools.py:123) does
#   load_config → `_get_platform_tools(..., include_default_mcp_servers=False)` →
#   add/discard → `_save_platform_tools` (tools_config.py:2560) → `save_config`
#   (strip_defaults=True, atomic_yaml_write). That helper is the only thing that
#   knows to preserve MCP-server names parked in the same list, to route
#   platform-restricted toolsets (discord → platform_toolsets.discord), and to keep
#   the `known_*_toolsets` bookkeeping coherent. Reimplementing it here would be a
#   SECOND writer of the same key that could drift from upstream at any pin bump.
#   The price is that writing needs Hermes RUNNING — the same precedent the voice
#   MCP rows already set (a switch that cannot work is disabled, not silently
#   ineffective).
HERMES_MINIMAL_TOOLSETS = ("file", "terminal", "clarify")

# ── WHICH ROWS THIS LEVER ACTUALLY GOVERNS ───────────────────────────────────
# `GET /api/tools/toolsets` returns EVERY configurable toolset, but three kinds of
# row live in that one list and only one of them reaches this MOT Deck's chat lane:
#
#  1. ordinary rows — `platform: "cli"`, persisted to `platform_toolsets.cli`,
#     which is exactly what our lane resolves (`_get_platform_tools(cfg, "cli")`,
#     tui_gateway/server.py:4399). THESE are the lever.
#  2. platform-restricted rows — `_TOOLSET_PLATFORM_RESTRICTIONS`
#     (tools_config.py:216-220) pins `discord`/`discord_admin` to the discord
#     platform, so `_toolset_configuration_platform` (tools_config.py:231) makes
#     their row `platform: "discord"` and their PUT writes
#     `platform_toolsets.discord`. `_toolset_allowed_for_platform` (:222) means
#     they can NEVER be enabled for cli — the model in this lane cannot get their
#     tools no matter what the switch says.
#  3. config-only rows — `_CONFIG_ONLY_TOOLSETS` (tools_config.py:165). `stt` is
#     not a model toolset at all: its row's `enabled` is read from `config.stt.
#     enabled` and its PUT writes that key (web_routers/tools.py:97-104, 148-158).
#     It ships ZERO tool schemas, so switching it off saves nothing in the prompt
#     — and switching it off breaks Hermes's speech-to-text.
#
# Presets, the headline count and the Check card are all scoped to (1). Rows of
# kind (2)/(3) still RENDER — hiding a switch Hermes shows would be its own lie —
# but they are labelled for what they are and no preset touches them.
HERMES_LEVER_PLATFORM = "cli"

# Mirrors `_CONFIG_ONLY_TOOLSETS` (hermes_cli/tools_config.py:165). Contract-pinned
# byte-identical, so a pin bump that adds one trips instead of silently letting a
# preset write a config section.
HERMES_CONFIG_ONLY_TOOLSETS = ("stt",)

# Mirrors `_DEFAULT_OFF_TOOLSETS` (hermes_cli/tools_config.py:156) — the toolsets
# upstream deliberately keeps OFF on a fresh install, subtracted from the composite
# expansion in `_get_platform_tools` (tools_config.py:2336-2344 mixed-config branch,
# 2386-2411 implicit branch).
#
# This exists because "Everything back on" was NOT "back on": it sent every name in
# the catalog, which turned on seven toolsets Hermes had never had on — Video
# Analysis among them. sample's report ("our rows showed video-analysis ON while I
# never enabled it") is exactly that button. The preset now restores HERMES'S OWN
# default set; anything in here stays an explicit, per-row opt-in.
#
# Contract-pinned byte-identical against upstream's set, so a release that adds or
# removes a default-off toolset trips a test rather than drifting quietly — and at
# the v2026.7.30 → v2026.8.13 bump it DID: upstream added `a2a`. Left stale, the
# "Hermes's defaults" preset would have switched a2a ON, which is the same defect
# this constant exists to prevent, one release later.
#
# `a2a` is a BUNDLED PLATFORM PLUGIN (vendor/hermes/plugins/platforms/a2a/), not a
# built-in toolset — it is absent from both `toolsets.py` and CONFIGURABLE_TOOLSETS,
# and reaches the catalog only through `_get_effective_configurable_toolsets`
# (tools_config.py:245-268), which appends whatever plugin toolsets are LOADED.
# Bundled platform plugins are registered as DEFERRED loaders (plugins.py:3855) and
# only import on first use, so the row is normally absent — the staleness was latent,
# not live. The mirror is corrected anyway: "normally absent" is not "cannot appear",
# and a preset must never be able to go past Hermes's own defaults.
HERMES_DEFAULT_OFF_TOOLSETS = ("homeassistant", "spotify", "discord",
                               "discord_admin", "video", "video_gen", "x_search",
                               "a2a")

# `platform_toolsets.cli: []` is a FOOTGUN, not a "no tools" setting: with an empty
# list `has_explicit_config` is False (tools_config.py:2301), the else-branch expands
# nothing, and `_load_enabled_toolsets` turns an empty result into `return None`
# (server.py:4402-4403) — which `get_tool_definitions` reads as ENABLE EVERYTHING.
# Disabling the last toolset would therefore hand the model MORE tools than it had.
HERMES_TOOLSETS_EMPTY_REASON = (
    "at least one toolset must stay on — Hermes reads an empty list as "
    "“all toolsets”, so this would give the model more tools, not fewer")


def hermes_toolset_names(rows) -> list:
    """PURE. Toolset names out of a /api/tools/toolsets payload, order preserved."""
    out = []
    for r in (rows if isinstance(rows, list) else []):
        if isinstance(r, dict):
            n = r.get("name")
            if isinstance(n, str) and n.strip():
                out.append(n.strip())
    return out


def hermes_toolsets_enabled(rows) -> list:
    """PURE. The subset currently reported ENABLED (upstream already accounted for
    _DEFAULT_OFF_TOOLSETS and agent.disabled_toolsets when it built this)."""
    return [r.get("name").strip() for r in (rows if isinstance(rows, list) else [])
            if isinstance(r, dict) and isinstance(r.get("name"), str)
            and r["name"].strip() and r.get("enabled")]


def hermes_toolset_platform(row) -> str:
    """PURE. A row's CONFIGURATION platform — the `platform_toolsets.<x>` key its
    PUT writes (web_routers/tools.py:100, from `_toolset_configuration_platform`).

    Fails OPEN to `cli`: a build that omits the field is far more likely to be an
    ordinary cli row than a platform-restricted one, and treating an unknown row as
    out-of-scope would silently drop it from the preset and the count."""
    if not isinstance(row, dict):
        return HERMES_LEVER_PLATFORM
    p = str(row.get("platform") or "").strip()
    return p or HERMES_LEVER_PLATFORM


def hermes_toolset_is_lever(row) -> bool:
    """PURE. Does this row control the toolsets THIS lane hands the model?

    True only for rows persisted to `platform_toolsets.cli` that are real model
    toolsets. See the HERMES_LEVER_PLATFORM block above for the three row kinds."""
    if not isinstance(row, dict) or not isinstance(row.get("name"), str):
        return False
    name = row["name"].strip()
    if not name or name in set(HERMES_CONFIG_ONLY_TOOLSETS):
        return False
    return hermes_toolset_platform(row) == HERMES_LEVER_PLATFORM


def hermes_lever_names(rows) -> list:
    """PURE. The subset of names this lever governs, in payload order."""
    return [r["name"].strip() for r in (rows if isinstance(rows, list) else [])
            if hermes_toolset_is_lever(r)]


def hermes_lever_enabled(rows) -> list:
    """PURE. Lever rows currently reported ENABLED — the honest "what is on in this
    lane" set. `hermes_toolsets_enabled` (all rows) is kept for the raw report."""
    return [r["name"].strip() for r in (rows if isinstance(rows, list) else [])
            if hermes_toolset_is_lever(r) and r.get("enabled")]


def hermes_preset_desired(rows, preset: str):
    """PURE. Resolve a preset chip to a desired-enabled set over the LEVER rows only
    (never a discord-platform row, never the config-only `stt` switch), INTERSECTED
    with what this Hermes build actually offers (so a renamed/removed toolset
    upstream cannot make a preset write a name the dashboard would 400 on).

    `all` means HERMES'S OWN DEFAULT SET, not every row: `_DEFAULT_OFF_TOOLSETS`
    (tools_config.py:155) is what upstream subtracts when it expands the `hermes-cli`
    composite, so "restore Hermes's full surface" has to subtract it too. Sending
    every name instead is what silently turned Video Analysis on.

    Returns None for an unknown preset — callers must treat that as a 400, never as
    'no change' (silently doing nothing to a tool surface is the wrong failure)."""
    names = hermes_lever_names(rows)
    p = (preset or "").strip().lower()
    if p == "minimal":
        return [n for n in names if n in set(HERMES_MINIMAL_TOOLSETS)]
    if p in ("all", "everything", "default", "defaults"):
        return [n for n in names if n not in set(HERMES_DEFAULT_OFF_TOOLSETS)]
    return None


def hermes_toolset_result(rows, desired, scope=None) -> set:
    """PURE. The LEVER set that would be enabled after applying `desired` within
    `scope` — i.e. what `platform_toolsets.cli` would report next read.

    Rows outside `scope` keep whatever Hermes reports today; rows inside it take
    their membership of `desired`. This is what the empty-list guard has to test:
    the old guard tested `desired` against ALL known names, so an enabled `stt`
    row (config-only, zero schemas) or a discord row was enough to satisfy it while
    every real cli toolset went off — the exact footgun it exists to prevent."""
    lever = set(hermes_lever_names(rows))
    want = {n for n in (desired or []) if isinstance(n, str)}
    sc = lever if scope is None else ({str(s) for s in scope} & lever)
    return (set(hermes_lever_enabled(rows)) - sc) | (want & sc)


def hermes_toolsets_valid(rows, desired, scope=None) -> str:
    """PURE. '' when `desired` is a safe target, else the honest reason string.
    Unknown names are NOT fatal here (they are dropped + reported by the plan)."""
    if not hermes_toolset_names(rows):
        return "Hermes reported no configurable toolsets"
    if not hermes_lever_names(rows):
        return "Hermes reported no toolsets for this chat lane"
    if not hermes_toolset_result(rows, desired, scope):
        return HERMES_TOOLSETS_EMPTY_REASON
    return ""


def hermes_toolset_plan(rows, desired, scope=None):
    """PURE. The minimal set of upstream PUTs to reach `desired`.

    Returns {"plan": [(name, enabled), ...], "unknown": [...], "unchanged": n}.
    Only toolsets whose state actually CHANGES are in the plan, so re-applying a
    preset is zero writes and each write is one atomic upstream save.

    `scope` bounds which rows may change. Default = the LEVER rows, so a preset can
    never reach a discord-platform row (whose PUT writes `platform_toolsets.discord`)
    or the config-only `stt` switch (whose PUT writes `config.stt.enabled` and would
    disable Hermes's speech-to-text for zero prompt saving). A single-row toggle
    passes its own name as the scope, so those rows stay flippable ON PURPOSE."""
    want = {n for n in (desired or []) if isinstance(n, str)}
    known = set(hermes_toolset_names(rows))
    now = set(hermes_toolsets_enabled(rows))
    lever = hermes_lever_names(rows)
    names = lever if scope is None else [n for n in hermes_toolset_names(rows)
                                         if n in {str(s) for s in scope}]
    plan, unchanged = [], 0
    for name in names:                            # stable, payload order
        target = name in want
        if target == (name in now):
            unchanged += 1
        else:
            plan.append((name, target))
    return {"plan": plan, "unknown": sorted(want - known), "unchanged": unchanged}


def hermes_toolset_view(rows, skills=None, cfg=None) -> dict:
    """PURE. Panel-shaped view of the probe: per-row tool COUNTS (real, from the
    payload's own resolved tool list) and the aggregate.

    Deliberately NO token estimate: the probe carries tool NAMES, not schemas, so
    any per-toolset token figure would be invented. Counts are the honest proxy.

    Also carries `needs_setup` — see the field comment below for its provenance and
    its one honest weakness (it is upstream's optimistic bool, not upstream's own
    accurate `_toolset_needs_configuration_prompt`, which is not exposed over HTTP)."""
    out, en_tools, all_tools = [], 0, 0
    for r in (rows if isinstance(rows, list) else []):
        if not isinstance(r, dict) or not isinstance(r.get("name"), str):
            continue
        tools = [t for t in (r.get("tools") or []) if isinstance(t, str)]
        on = bool(r.get("enabled"))
        lever = hermes_toolset_is_lever(r)
        # The headline totals are about THIS lane's prompt, so only lever rows count:
        # a discord-platform row's tools can never reach a cli session
        # (`_toolset_allowed_for_platform`, tools_config.py:222) and the config-only
        # `stt` row has no schemas at all. Counting them made the number bigger than
        # anything the model would ever see.
        if lever:
            all_tools += len(tools)
            if on:
                en_tools += len(tools)
        out.append({"name": r["name"].strip(),
                    "label": str(r.get("label") or r["name"]).strip(),
                    "description": str(r.get("description") or "").strip(),
                    "platform": hermes_toolset_platform(r),
                    "platform_label": str(r.get("platform_label")
                                          or hermes_toolset_platform(r)).strip(),
                    "lever": lever,
                    "config_only": r["name"].strip() in set(HERMES_CONFIG_ONLY_TOOLSETS),
                    "default_off": r["name"].strip() in set(HERMES_DEFAULT_OFF_TOOLSETS),
                    "enabled": on, "tools": tools, "tool_count": len(tools),
                    # UPSTREAM's OWN setup signal, mirrored not invented: the row's
                    # `configured` bool (web_routers/tools.py:107, produced by
                    # tools_config._toolset_has_keys:2589) is the same field Hermes's
                    # Skills→TOOLSETS page shows its amber "Setup needed" caption from
                    # (web/src/pages/SkillsPage.tsx:606). Fail OPEN — only an EXPLICIT
                    # False is a warning, so a build that omits the key (or a probe
                    # shape we do not know) can never invent a scary pill.
                    "needs_setup": r.get("configured") is False,
                    # Filled in below from the persisted intent; "" = agrees.
                    "drift": ""})
    off = {d["name"] for d in hermes_toolset_drift(rows, cfg)}
    for t in out:
        if t["name"] in off:
            t["drift"] = "off"
    sk = skills if isinstance(skills, dict) else {}
    return {"toolsets": out,
            "platform": HERMES_LEVER_PLATFORM,
            "enabled_count": sum(1 for r in out if r["enabled"] and r["lever"]),
            "total": sum(1 for r in out if r["lever"]),
            "other_count": sum(1 for r in out if not r["lever"]),
            "tool_count_enabled": en_tools,
            "tool_count_total": all_tools,
            "out_of_sync": sorted(off),
            "skills": {"count": int(sk.get("count") or 0),
                       "disabled_count": int(sk.get("disabled_count") or 0)}}


# ── DO OUR SWITCHES MATCH WHAT HERMES HANDS THE MODEL? ───────────────────────
# The reason this exists: a switch that reports OUR intent rather than Hermes's
# behaviour is exactly the doubt this panel has to kill. Every row above already
# RENDERS Hermes's own `enabled` field (web_routers/tools.py:97, computed by
# `_get_platform_tools`, tools_config.py:2262) — never our last write — so the
# switch itself cannot lie. What was missing is the WHY when the two disagree.

# The gateway folds CLIENT-SURFACE toolsets in on the resolve path our lane takes,
# on top of whatever `platform_toolsets.cli` says — so their tools are in the
# model's schema no matter what this panel does, and the summary reports them
# SEPARATELY rather than quietly under-reporting.
#
# ⚠️ v2026.8.13 replaced the flat `return sorted(enabled | {"project"})` with
# `return sorted(enabled | _gui_surface_toolsets(session_platform))`
# (tui_gateway/server.py:4410; the focus-mode early return folds the same set at
# :4293). `_gui_surface_toolsets` (server.py:4246-4264) is:
#
#     surfaces = {"project"}
#     if platform == "desktop": surfaces.add("desktop_ui")
#
# i.e. `project` is STILL unconditional, and `desktop_ui` is added ONLY for a
# session whose SOURCE is the desktop app. Ours is not: every session.create /
# session.resume this bridge issues sends `source: HERMES_SESSION_SOURCE`
# ("motdeck"), and `_resolve_session_source` (server.py:3685-3695) returns an
# explicit source VERBATIM. So our lane's fold is exactly {"project"} and the
# count below is still complete.
#
# That is worth stating plainly because it is load-bearing and NOT obvious:
# `start_component.sh` launches the dashboard with HERMES_DESKTOP=1 (for the cron
# ticker), and HERMES_DESKTOP=1 is precisely what `_resolve_session_platform`
# (server.py:3659-3682) turns into "desktop" when no source is given. Our explicit
# source is the ONLY thing keeping this lane off the desktop surface — which is the
# right side to be on twice over: those 8 tools (read_terminal, open_preview,
# focus_pane, …) need a GUI renderer our panel does not implement, so inheriting
# them would both break the count and hand the model tools it cannot use.
# Contract-pinned in both directions.
#
# `project` is NOT in CONFIGURABLE_TOOLSETS (tools_config.py:95-122), so it has no
# row and no switch. (toolsets.py:260-264.)
HERMES_GATEWAY_ALWAYS_TOOLSET = "project"
HERMES_GATEWAY_ALWAYS_TOOLS = ("project_list", "project_create", "project_switch")

# The `source` every Hermes session this bridge opens is tagged with. Named rather
# than repeated as a literal because it is not cosmetic: it selects the session's
# PLATFORM (server.py:3685-3699), which decides the client-surface fold above.
HERMES_SESSION_SOURCE = "motdeck"

# Upstream gates the ENTIRE <available_skills> block on these three tool names
# being in the schema — `has_skills_tools` (agent/system_prompt.py:412), else
# `skills_prompt = ""` (:440). Hermes's own banner uses the toolset name for the
# same purpose (`"skills" in _enabled_ts`, hermes_cli/banner.py:1058, which then
# reports `0 skills` and "Skills toolset disabled"). We test the TOOL NAMES, so
# a rename of the toolset key cannot make us claim an index that is not there.
HERMES_SKILL_INDEX_TOOLS = ("skills_list", "skill_view", "skill_manage")


def hermes_toolset_drift(rows, cfg) -> list:
    """PURE. Toolsets we ASKED Hermes for that Hermes does NOT report as enabled.

    INTENT is the PERSISTED one: every write goes through Hermes's own
    `PUT /api/tools/toolsets/{name}` → `_save_platform_tools` (tools_config.py:2560),
    so `platform_toolsets.cli` on disk IS the record of what this panel asked for.
    TRUTH is the probe's `enabled`. A disagreement is real and is worth naming —
    `agent.disabled_toolsets` is subtracted LAST (tools_config.py:2530) and
    `agent.coding_context: "focus"` short-circuits the list entirely
    (tui_gateway/server.py:4285) — both of which silently override a switch.

    ONE DIRECTION ONLY, and that is deliberate: "listed but Hermes says off" is
    unambiguous, while "enabled but not in our list" has legitimate causes we
    cannot distinguish from the payload — a composite name like `hermes-cli`
    sitting in the same list expands to more toolsets (tools_config.py:2315-2344),
    and the config-only toolsets (`_CONFIG_ONLY_TOOLSETS = {"stt"}`,
    tools_config.py:165) are enabled by their own config section and never appear
    in the list at all. Flagging those would be a false alarm, and a false
    "out of sync" pill is worse than none. The other direction is covered
    panel-side by our own in-session intent, which cannot be wrong about itself.

    Fails OPEN in every unknown: no saved list (None = never configured) ⇒ no
    claim; a row this lever does not govern ⇒ skipped, because a platform-restricted
    toolset persists to its own key (`_toolset_configuration_platform`,
    tools_config.py:231) and a config-only row (`stt`) is not in
    `platform_toolsets` at all — its `enabled` comes from `config.stt.enabled`
    (web_routers/tools.py:97-104), so comparing it against the cli list would flag
    every install that has ever saved one."""
    cfg = cfg if isinstance(cfg, dict) else {}
    cli = cfg.get("platform_toolsets_cli")
    if not isinstance(cli, list):
        return []
    want = {str(x).strip() for x in cli if str(x).strip()}
    out = []
    for r in (rows if isinstance(rows, list) else []):
        if not hermes_toolset_is_lever(r):
            continue
        name = r["name"].strip()
        if name not in want:
            continue
        if not r.get("enabled"):
            out.append({"name": name, "intent": True, "reported": False})
    return out


def hermes_tool_summary(rows, skills=None) -> dict:
    """PURE. "What will Hermes actually hand the model?" — computed from the same
    payload Hermes's own Skills→TOOLSETS page renders, so it can be checked in one
    click without cross-referencing two apps.

    The union is de-duplicated because toolsets overlap (`resolve_toolset`,
    toolsets.py:756, composes and dedups the same way), and the gateway's
    client-surface fold is reported SEPARATELY rather than hidden inside the
    number — it is real, it is in the prompt, and no switch here controls it. For
    this lane that fold is exactly `project`; see HERMES_GATEWAY_ALWAYS_TOOLSET
    above for why `desktop_ui` is not in it.

    Counts the LEVER rows only, and that is a correction not a narrowing: this lane
    resolves `_get_platform_tools(cfg, "cli")` (tui_gateway/server.py:4399), so a
    row whose configuration platform is `discord` can never contribute a schema here
    (`_toolset_allowed_for_platform`, tools_config.py:222) and the config-only `stt`
    row ships none at all (tools_config.py:165). Counting them made the card claim
    tools the model would never see.

    HONEST LIMIT carried in the payload as `excludes_mcp`: the listing endpoint
    resolves with `include_default_mcp_servers=False` (web_routers/tools.py:82)
    while the runtime resolve uses True (tui_gateway/server.py:4399), so tools
    coming from connected MCP servers are NOT counted here."""
    en, tools = [], []
    seen = set()
    for r in (rows if isinstance(rows, list) else []):
        if not hermes_toolset_is_lever(r):
            continue
        if not r.get("enabled"):
            continue
        en.append(r["name"].strip())
        for t in (r.get("tools") or []):
            if isinstance(t, str) and t.strip() and t.strip() not in seen:
                seen.add(t.strip())
                tools.append(t.strip())
    extra = [t for t in HERMES_GATEWAY_ALWAYS_TOOLS if t not in seen]
    sk = skills if isinstance(skills, dict) else {}
    return {
        "toolsets": sorted(en),
        "tools": sorted(tools),
        "platform": HERMES_LEVER_PLATFORM,
        "tool_count": len(tools) + len(extra),
        "from_toolsets_count": len(tools),
        "always": {"toolset": HERMES_GATEWAY_ALWAYS_TOOLSET,
                   "tools": list(extra)},
        # Exactly upstream's own predicate, on tool NAMES not a toolset name.
        "skill_index": any(t in seen for t in HERMES_SKILL_INDEX_TOOLS),
        "skill_count": int(sk.get("count") or 0),
        "excludes_mcp": True,
    }


def hermes_skills_summary(payload) -> dict:
    """PURE. Count skills out of the dashboard's /api/skills payload. Accepts a bare
    list or {"skills": [...]} and never raises on a surprise shape — a broken count
    must not blank the group."""
    rows = payload.get("skills") if isinstance(payload, dict) else payload
    rows = rows if isinstance(rows, list) else []
    rows = [r for r in rows if isinstance(r, dict)]
    return {"count": len(rows),
            "disabled_count": sum(1 for r in rows if r.get("enabled") is False)}


# ── PER-SKILL TRIMMING — THE FINE INSTRUMENT BESIDE THE `skills` SWITCH ───────
# The `skills` TOOLSET switch above is the blunt one: it drops three tool schemas
# and with them the ENTIRE <available_skills> block (upstream gates the block on
# skills_list/skill_view/skill_manage being in the schema, agent/system_prompt.py:412).
# This lever shrinks that block instead of removing it — disable the skills the
# model does not need and the index gets smaller, one line at a time.
#
# WRITES GO THROUGH HERMES'S OWN API, exactly like the toolset lever:
#   `PUT /api/skills/toggle {"name": ..., "enabled": bool}`
#   (hermes_cli/web_routers/skills.py:426-437 → `get_disabled_skills` /
#    `save_disabled_skills`, hermes_cli/skills_config.py:44-72; body model
#    `SkillToggle`, hermes_cli/web_models.py:604-607). Same reasoning recorded for
#   the toolsets: upstream's writer is the only thing that keeps its own key
#   coherent, and a second writer of `skills.disabled` would drift at a pin bump.
#   The price is identical too — writing needs Hermes RUNNING.
#
# THE RECORDED NAME GOTCHA IS DISCHARGED BY NEVER MAPPING A NAME.
#   Memory records "the names stored there are frontmatter names not directory
#   names". Re-read at this pin, the picture is both softer and simpler:
#     • the listing's `name` IS `frontmatter.get("name", skill_dir.name)`
#       (tools/skills_tool.py:737) — frontmatter name, falling back to the dir name;
#     • the prompt builder skips a skill when EITHER matches —
#       `if frontmatter_name in disabled or skill_name in disabled`
#       (agent/prompt_builder.py:1654 snapshot path, :1676 cold path, :1759).
#   So the only safe rule is the one we already follow for toolsets: take every
#   name off upstream's OWN listing and post it back verbatim. We never derive a
#   name from a path, a label or a heuristic, and therefore cannot get this wrong.
#
# SCOPE IS GLOBAL, NOT `cli` — AND THAT IS UPSTREAM'S CHOICE, NOT OURS.
#   `SkillToggle` carries no platform and the handler calls
#   `save_disabled_skills(config, disabled)` with no platform argument, which
#   writes `skills.disabled` (skills_config.py:64-72) — the GLOBAL list. Hermes
#   does have a per-platform list (`skills.platform_disabled.<platform>`,
#   agent/skill_utils.py:448-455) but its dashboard never writes it, and neither
#   do we: a second writer for a key upstream's own UI cannot produce would be the
#   drift this whole approach exists to avoid. The consequence is real and is
#   NAMED in the UI — a skill switched off here is off on every Hermes surface,
#   not just this chat lane. The global list is unioned into every platform's
#   resolution (`global_disabled | platform_disabled`, skill_utils.py:454), so a
#   global write always reaches our lane; it just reaches the others too.
HERMES_SKILL_TOGGLE_PATH = "/api/skills/toggle"

# Upstream's DEFAULT disabled-skill set. `config_defaults.py:1682`'s `skills`
# block has external_dirs / template_vars / inline_shell / inline_shell_timeout /
# guard_agent_created / write_approval and NO `disabled` key at all, so
# `get_disabled_skills` returns an empty set on a fresh install: Hermes ships
# every installed skill ENABLED.
#
# This constant exists so "restore Hermes's defaults" restores UPSTREAM's set
# rather than our idea of one. It is contract-pinned: the day a release ships a
# default `skills.disabled`, the test trips and this chip gets fixed instead of
# quietly switching on skills Hermes deliberately keeps off — which is exactly
# the bug "Everything back on" had on the toolset lever.
HERMES_SKILL_DEFAULT_DISABLED = ()


def hermes_skill_rows(payload) -> list:
    """PURE. Normalise `GET /api/skills` into panel rows.

    Shape read from hermes_cli/web_routers/skills.py:394-423 — the handler returns
    a bare LIST of `_find_all_skills` dicts (name/description/category) annotated
    with `enabled` (:416), `usage` (:417) and `provenance` (:418-422). A dict
    wrapper is accepted too, so a future envelope does not blank the list.

    Total by construction: a surprise element type is dropped, a nameless row is
    dropped, and nothing raises — a broken row must not take the group with it."""
    rows = payload.get("skills") if isinstance(payload, dict) else payload
    out = []
    for r in (rows if isinstance(rows, list) else []):
        if not isinstance(r, dict) or not isinstance(r.get("name"), str):
            continue
        name = r["name"].strip()
        if not name:
            continue
        out.append({
            "name": name,
            "description": str(r.get("description") or "").strip(),
            "category": str(r.get("category") or "").strip() or "uncategorized",
            "provenance": str(r.get("provenance") or "").strip(),
            # Upstream computes this as `name not in disabled` (skills.py:416), so
            # it is Hermes's own answer and is re-read on every load — never our
            # last write. Fail OPEN: only an explicit False is "off", so a build
            # that omits the field can never make the whole library look disabled.
            "enabled": r.get("enabled") is not False,
        })
    return out


def hermes_skill_names(rows) -> list:
    """PURE. Every skill name in the payload, order preserved."""
    return [r["name"] for r in (rows if isinstance(rows, list) else [])
            if isinstance(r, dict) and isinstance(r.get("name"), str) and r["name"]]


def hermes_skills_on(rows) -> list:
    """PURE. The subset Hermes reports ENABLED (i.e. not in `skills.disabled`)."""
    return [r["name"] for r in (rows if isinstance(rows, list) else [])
            if isinstance(r, dict) and isinstance(r.get("name"), str) and r["name"]
            and r.get("enabled") is not False]


def hermes_skill_lane_off(rows, cfg) -> list:
    """PURE. Skills the listing reports ENABLED that this lane will NOT see.

    `GET /api/skills` computes `enabled` from `get_disabled_skills(config)` with NO
    platform (skills.py:406) — the GLOBAL list only. Our lane resolves
    `get_disabled_skill_names(platform)` = global ∪ `platform_disabled[platform]`
    (agent/skill_utils.py:448-455), so a name parked in
    `skills.platform_disabled.cli` is absent from THIS prompt while Hermes's own
    page shows it on. That is exactly the class of silent disagreement the toolset
    lever was built to surface, so it is surfaced here too.

    ONE DIRECTION ONLY, for the same reason as `hermes_toolset_drift`: "the
    listing says on, our lane says off" is unambiguous, while the reverse cannot
    happen at all (the platform list only ADDS). Fails OPEN in every unknown —
    no key, a non-list, a junk cfg ⇒ NO claim, because a scary pill on a healthy
    install is worse than none."""
    cfg = cfg if isinstance(cfg, dict) else {}
    pd = cfg.get("skills_platform_disabled_cli")
    if not isinstance(pd, list):
        return []
    hidden = {str(x).strip() for x in pd if str(x).strip()}
    if not hidden:
        return []
    return [n for n in hermes_skills_on(rows) if n in hidden]


def hermes_skill_preset_desired(rows, preset: str):
    """PURE. Resolve a preset chip to a desired-enabled set over the real catalog.

    `defaults` = HERMES'S OWN default set (every installed skill minus
    HERMES_SKILL_DEFAULT_DISABLED, which is empty at this pin and contract-pinned
    so it stays honest), NOT "everything we can think of".
    `none` = the empty set, which is legal here: unlike `platform_toolsets.cli`
    (where `[]` means ENABLE EVERYTHING — the footgun HERMES_TOOLSETS_EMPTY_REASON
    exists for), a fully-populated `skills.disabled` just means an empty index.

    Returns None for an unknown preset — the caller must 400, never treat it as
    'no change'."""
    names = hermes_skill_names(rows)
    p = (preset or "").strip().lower()
    if p in ("all", "defaults", "default", "everything"):
        return [n for n in names if n not in set(HERMES_SKILL_DEFAULT_DISABLED)]
    if p in ("none", "off"):
        return []
    return None


def hermes_skills_valid(rows, desired, scope=None) -> str:
    """PURE. '' when `desired` is a safe target, else the honest reason.

    Deliberately has NO empty-set refusal (see hermes_skill_preset_desired): with
    skills, "none enabled" is a legitimate, reversible state that makes the index
    empty. The only refusal is an empty CATALOG — writing names against a listing
    we never got would be writing blind."""
    if not hermes_skill_names(rows):
        return "Hermes reported no skills"
    return ""


def hermes_skill_plan(rows, desired, scope=None):
    """PURE. The minimal set of upstream PUTs to reach `desired`.

    Returns {"plan": [(name, enabled), ...], "unknown": [...], "unchanged": n}.
    Only skills whose state actually CHANGES are written, so re-applying a preset
    costs zero upstream calls and a bulk action over a filtered list only touches
    the rows that were not already in the wanted state.

    `scope` bounds which rows may change (a single switch passes its own name; a
    bulk action passes the names it displayed). Default = the whole catalog."""
    def _seq(x):
        return x if isinstance(x, (list, tuple, set, frozenset)) else []
    want = {n for n in _seq(desired) if isinstance(n, str)}
    known = hermes_skill_names(rows)
    kset = set(known)
    now = set(hermes_skills_on(rows))
    names = known if scope is None else [n for n in known
                                         if n in {str(s) for s in _seq(scope)}]
    plan, unchanged = [], 0
    for name in names:                                # stable, payload order
        target = name in want
        if target == (name in now):
            unchanged += 1
        else:
            plan.append((name, target))
    return {"plan": plan, "unknown": sorted(want - kset), "unchanged": unchanged}


def hermes_skill_view(rows, cfg=None) -> dict:
    """PURE. Panel-shaped view: the rows plus the two counts that matter.

    `in_prompt` is deliberately NOT just `enabled`: it also subtracts the
    lane-hidden set, so the headline number is what THIS lane's index will carry
    rather than what Hermes's global page shows. When there is no
    `platform_disabled.cli` (the normal install) the two are identical."""
    # `hermes_skill_rows` is idempotent on its own output, so normalise
    # unconditionally rather than sniffing the shape — one code path, and a
    # hand-built or already-normalised row is handled identically.
    rr = hermes_skill_rows(rows)
    off = set(hermes_skill_lane_off(rr, cfg))
    out = []
    for r in rr:
        out.append({**r, "lane_off": r["name"] in off})
    cats = []
    for r in out:
        if r["category"] not in cats:
            cats.append(r["category"])
    return {"skills": out,
            "total": len(out),
            "enabled_count": sum(1 for r in out if r["enabled"]),
            "in_prompt": sum(1 for r in out if r["enabled"] and not r["lane_off"]),
            "lane_off": sorted(off),
            "categories": cats,
            # Named so the panel never has to guess which key it is editing, and
            # so the "this is global, not just this lane" sentence has a source.
            "scope": "global"}


def _hermes_toolset_config() -> dict:
    """Raw truth off disk for the three keys that decide the lane's tool surface.
    Readable with Hermes STOPPED, so the panel can still say what is configured."""
    try:
        with open(_hermes_config_path()) as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    pts = data.get("platform_toolsets")
    cli = (pts or {}).get("cli") if isinstance(pts, dict) else None
    agent = data.get("agent") if isinstance(data.get("agent"), dict) else {}
    dis = agent.get("disabled_toolsets")
    sk = data.get("skills") if isinstance(data.get("skills"), dict) else {}
    skd = sk.get("disabled")
    spd = sk.get("platform_disabled")
    spc = (spd or {}).get(HERMES_LEVER_PLATFORM) if isinstance(spd, dict) else None
    return {
        # None = never saved → Hermes falls back to the hermes-cli composite.
        "platform_toolsets_cli": ([str(x) for x in cli] if isinstance(cli, list) else None),
        "disabled_toolsets": ([str(x) for x in dis] if isinstance(dis, list) else []),
        "coding_context": str(agent.get("coding_context") or "auto").strip().lower(),
        # The GLOBAL disabled-skill list — the key Hermes's own dashboard writes
        # (skills_config.py:68). Readable with Hermes stopped, so the panel can
        # still say what is configured. `[]`/absent are the same thing here (unlike
        # platform_toolsets.cli, where the distinction is load-bearing).
        "skills_disabled": ([str(x) for x in skd] if isinstance(skd, list) else []),
        # Read-ONLY, never written by us: upstream's dashboard cannot produce it,
        # so writing it would make us a second, divergent writer. It can only ADD
        # to the disabled set (skill_utils.py:454), so it is the one thing that can
        # make our lane's index smaller than Hermes's own page claims — surfaced
        # per-row rather than silently subtracted.
        "skills_platform_disabled_cli": ([str(x) for x in spc]
                                         if isinstance(spc, list) else None),
    }


async def _hermes_dash(method: str, path: str, **kw):
    """One REST call to Hermes's own dashboard on loopback (token-gated, same header
    as the session-rename call). Raises on transport failure; callers decide."""
    import httpx
    tok = _hermes_token()
    if not tok:
        raise RuntimeError("no Hermes dashboard token")
    async with httpx.AsyncClient(timeout=15.0) as c:
        return await c.request(method, f"http://127.0.0.1:{_hermes_port()}{path}",
                               headers={"X-Hermes-Session-Token": tok}, **kw)


async def _hermes_toolset_rows() -> list:
    r = await _hermes_dash("GET", "/api/tools/toolsets")
    if r.status_code >= 400:
        raise RuntimeError(f"toolsets probe {r.status_code}")
    rows = r.json()
    return rows if isinstance(rows, list) else []


@app.get("/api/hermes/toolsets")
async def hermes_toolsets_get() -> JSONResponse:
    """The lever's read side. The CATALOG is always PROBED from the running Hermes
    (GET /api/tools/toolsets) rather than hardcoded, so a pin bump that adds or
    renames a toolset cannot leave a stale table in our source; when Hermes is down
    we report `running:false` + the raw config and invent nothing."""
    cfgv = _hermes_toolset_config()
    base = {"config": cfgv,
            # focus mode makes _load_enabled_toolsets return BEFORE reading the
            # config list — the switches below would be cosmetic. Say so.
            "focus_override": cfgv["coding_context"] == "focus",
            "restart_required": False}
    try:
        rows = await _hermes_toolset_rows()
    except Exception as e:
        return JSONResponse({**base, "running": False, "source": "config",
                             **hermes_toolset_view([]), "error": str(e)[:200]})
    skills = {}
    try:                                  # best-effort: a skill count is a nicety
        rs = await _hermes_dash("GET", "/api/skills")
        if rs.status_code < 400:
            skills = hermes_skills_summary(rs.json())
    except Exception:
        skills = {}
    return JSONResponse({**base, "running": True, "source": "probe",
                         **hermes_toolset_view(rows, skills, cfgv)})


@app.get("/api/hermes/toolsets/summary")
async def hermes_toolsets_summary() -> JSONResponse:
    """The VERIFY affordance: read LIVE from Hermes and answer the one question the
    switches cannot answer on their own — "what will Hermes hand the model?".

    Deliberately a FRESH probe rather than the panel's snapshot: the whole point is
    that sample does not have to trust our cached view (or open Hermes's own Skills →
    TOOLSETS page) to check. 409 when Hermes is down — a summary computed off a
    stale config would be exactly the kind of confident-but-wrong number this slice
    exists to remove."""
    try:
        rows = await _hermes_toolset_rows()
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Hermes is not reachable — "
                             f"start it first ({str(e)[:120]})"}, status_code=409)
    skills = {}
    try:
        rs = await _hermes_dash("GET", "/api/skills")
        if rs.status_code < 400:
            skills = hermes_skills_summary(rs.json())
    except Exception:
        skills = {}
    # In `agent.coding_context: "focus"` the lane's resolver RETURNS ITS OWN toolset
    # list before the config list is read (tui_gateway/server.py:4285-4293), so this
    # listing's enabled set is not what the model gets. Say so on the card rather
    # than print a confident number that does not apply — the exact failure mode
    # this whole affordance exists to remove.
    cfgv = _hermes_toolset_config()
    return JSONResponse({"ok": True, "focus_override": cfgv["coding_context"] == "focus",
                         **hermes_tool_summary(rows, skills)})


@app.post("/api/hermes/toolsets")
async def hermes_toolsets_set(req: Request) -> JSONResponse:
    """The lever's write side. Body is ONE of:
        {"preset": "minimal"|"all"}   — the chips
        {"enabled": ["file", ...]}    — an explicit desired-enabled set
        {"name": "web", "on": false}  — one row's switch

    Every change is an upstream `PUT /api/tools/toolsets/{name}` (see the block
    comment above) and only CHANGED toolsets are written, so re-applying a preset
    costs zero writes. Takes effect on the NEXT Hermes chat — no restart
    (`restart_required` is reported so the panel never has to assume)."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    # Shape first, so a malformed body is always the specific 400 and never gets
    # masked by a 409 just because Hermes happens to be stopped.
    if not (body.get("preset") is not None
            or isinstance(body.get("enabled"), list)
            or (isinstance(body.get("name"), str) and body["name"].strip())):
        return JSONResponse({"ok": False, "error": "preset, enabled or name required"},
                            status_code=400)
    try:
        rows = await _hermes_toolset_rows()
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Hermes is not reachable — "
                             f"start it first ({str(e)[:120]})"}, status_code=409)

    # `scope` = which rows this request may change. None = the LEVER rows (every
    # preset), so a preset can never write `platform_toolsets.discord` or flip
    # `config.stt.enabled`. A single-row switch scopes to its own name, so those
    # rows stay flippable when the user aims at them deliberately.
    scope = None
    if body.get("preset") is not None:
        desired = hermes_preset_desired(rows, str(body.get("preset")))
        if desired is None:
            return JSONResponse({"ok": False, "error": "unknown preset"},
                                status_code=400)
    elif isinstance(body.get("enabled"), list):
        desired = [str(x) for x in body["enabled"]]
    elif isinstance(body.get("name"), str) and body["name"].strip():
        nm = body["name"].strip()
        scope = [nm]
        desired = [nm] if body.get("on") else []
    else:                                     # unreachable — the shape gate above
        return JSONResponse({"ok": False, "error": "preset, enabled or name required"},
                            status_code=400)

    bad = hermes_toolsets_valid(rows, desired, scope)
    if bad:
        return JSONResponse({"ok": False, "error": bad}, status_code=400)

    p = hermes_toolset_plan(rows, desired, scope)
    changed, failed = [], []
    for name, on in p["plan"]:
        try:
            r = await _hermes_dash("PUT", f"/api/tools/toolsets/{name}",
                                   json={"enabled": bool(on)})
            if r.status_code >= 400:
                failed.append(f"{name}:{r.status_code}")
            else:
                changed.append(name)
                # Per SUCCESSFUL write, so a partially-failed request still signals
                # the part that landed. The shell only compares > and records, so a
                # multi-write request costs exactly one reload, not one per name.
                _hermes_cfg_bump()
        except Exception as e:
            failed.append(f"{name}:{str(e)[:60]}")

    # Re-probe and report the TRUTH rather than our intent. A name that refuses to
    # turn on is almost always sitting in agent.disabled_toolsets, which upstream
    # subtracts last (tools_config.py:2530) — so name that cause instead of leaving
    # the user staring at a switch that snaps back.
    stuck = []
    try:
        after = await _hermes_toolset_rows()
        now = set(hermes_toolsets_enabled(after))
        stuck = sorted({n for n in desired if n in set(hermes_toolset_names(after))
                        and n not in now})
    except Exception:
        after = rows
    view = hermes_toolset_view(after)
    print(f"[hermes-tools] {len(changed)} changed, {len(p['plan'])} planned, "
          f"{view['enabled_count']}/{view['total']} toolsets on "
          f"({view['tool_count_enabled']} tools) failed={failed} stuck={stuck}",
          flush=True)
    return JSONResponse({
        "ok": not failed, "changed": changed, "failed": failed,
        "unknown": p["unknown"], "stuck": stuck,
        # The LANE's set, so this list and `enabled_count` can never disagree.
        "enabled": sorted(hermes_lever_enabled(after)),
        "platform": HERMES_LEVER_PLATFORM,
        "enabled_count": view["enabled_count"], "total": view["total"],
        "tool_count_enabled": view["tool_count_enabled"],
        "restart_required": False,
        "note": ("takes effect on the next Hermes chat" if not failed else
                 "some toolsets could not be written — " + " · ".join(failed)),
    }, status_code=200 if not failed else 502)


async def _hermes_skill_rows() -> list:
    r = await _hermes_dash("GET", "/api/skills")
    if r.status_code >= 400:
        raise RuntimeError(f"skills probe {r.status_code}")
    return hermes_skill_rows(r.json())


@app.get("/api/hermes/skills")
async def hermes_skills_get() -> JSONResponse:
    """The per-skill lever's read side. The catalog is always PROBED from the
    running Hermes (`GET /api/skills`) — never a table in our source — so a skill
    installed, renamed or removed upstream cannot leave a stale row here.

    With Hermes stopped we report `running:false` and the raw configured list off
    disk, and invent nothing."""
    cfgv = _hermes_toolset_config()
    base = {"config": {"skills_disabled": cfgv["skills_disabled"],
                       "skills_platform_disabled_cli":
                           cfgv["skills_platform_disabled_cli"]},
            "scope": "global"}
    try:
        rows = await _hermes_skill_rows()
    except Exception as e:
        return JSONResponse({**base, "running": False, "source": "config",
                             **hermes_skill_view([], cfgv), "error": str(e)[:200]})
    return JSONResponse({**base, "running": True, "source": "probe",
                         **hermes_skill_view(rows, cfgv)})


@app.post("/api/hermes/skills")
async def hermes_skills_set(req: Request) -> JSONResponse:
    """The per-skill lever's write side. Body is ONE of:
        {"preset": "defaults"|"none"}      — the chips
        {"name": "pdf", "on": false}       — one row's switch
        {"names": [...], "on": false}      — a bulk action over the rows shown
        {"enabled": [...]}                 — an explicit desired-enabled set

    Every change is an upstream `PUT /api/skills/toggle` (see the block comment
    above `hermes_skill_rows`) and only CHANGED skills are written, so re-applying
    a preset costs zero writes. Takes effect on the NEXT Hermes chat — the skill
    index is rebuilt per prompt from a cache keyed on the disabled set
    (agent/prompt_builder.py:1618-1625), so no restart is needed.

    ⚠️ The writes are SEQUENTIAL because upstream offers no bulk route (there is
    exactly one `/api/skills/toggle` at this pin) and each one is its own atomic
    save — so a bulk action over many rows takes visibly longer than one click,
    and a mid-way failure leaves the earlier writes landed and names the rest."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    # Shape first, so a malformed body is always the specific 400 and is never
    # masked by a 409 just because Hermes happens to be stopped.
    if not (body.get("preset") is not None
            or isinstance(body.get("enabled"), list)
            or isinstance(body.get("names"), list)
            or (isinstance(body.get("name"), str) and body["name"].strip())):
        return JSONResponse({"ok": False,
                             "error": "preset, enabled, names or name required"},
                            status_code=400)
    try:
        rows = await _hermes_skill_rows()
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Hermes is not reachable — "
                             f"start it first ({str(e)[:120]})"}, status_code=409)

    scope = None
    if body.get("preset") is not None:
        desired = hermes_skill_preset_desired(rows, str(body.get("preset")))
        if desired is None:
            return JSONResponse({"ok": False, "error": "unknown preset"},
                                status_code=400)
    elif isinstance(body.get("enabled"), list):
        desired = [str(x) for x in body["enabled"]]
    elif isinstance(body.get("names"), list):
        # A bulk action may only move the rows it named — never the rest of the
        # catalog. Turning off "the 12 shown" must not turn off the other 66.
        scope = [str(x) for x in body["names"]]
        desired = list(scope) if body.get("on") else []
    else:
        nm = body["name"].strip()
        scope = [nm]
        desired = [nm] if body.get("on") else []

    bad = hermes_skills_valid(rows, desired, scope)
    if bad:
        return JSONResponse({"ok": False, "error": bad}, status_code=400)

    p = hermes_skill_plan(rows, desired, scope)
    changed, failed = [], []
    for name, on in p["plan"]:
        try:
            r = await _hermes_dash("PUT", HERMES_SKILL_TOGGLE_PATH,
                                   json={"name": name, "enabled": bool(on)})
            if r.status_code >= 400:
                failed.append(f"{name}:{r.status_code}")
            else:
                changed.append(name)
                _hermes_cfg_bump()          # same rule as the toolset lever above
        except Exception as e:
            failed.append(f"{name}:{str(e)[:60]}")

    # Re-probe and report the TRUTH rather than our intent — the same rule the
    # toolset lever follows. A name that refuses to move is worth naming.
    cfgv = _hermes_toolset_config()
    try:
        after = await _hermes_skill_rows()
    except Exception:
        after = rows
    now = set(hermes_skills_on(after))
    known = set(hermes_skill_names(after))
    stuck = sorted({n for n in desired if n in known and n not in now})
    # ⚠️ THE OTHER DIRECTION, ADDED AT THE v0.20.6 PIN BUMP (2026-08-28).
    # Upstream grew `agent/skill_utils.ESSENTIAL_SKILLS` (today exactly
    # {"hermes-agent"}) and subtracts it in BOTH directions —
    # `save_disabled_skills` drops it on the way IN and `get_disabled_skills`
    # drops it on the way OUT (hermes_cli/skills_config.py:55-74). So a request
    # to disable an essential skill is accepted with a 200, persists nothing,
    # and the row is enabled again on the next read. Before this, the write
    # answered `ok:true changed:[hermes-agent] "takes effect on the next Hermes
    # chat"` and sample's switch snapped back with no sentence explaining why —
    # a small lie the re-probe already had the facts to contradict. `stuck`
    # cannot carry it (its message is "still off"), so it gets its own field.
    pinned_on = sorted({n for n, on in p["plan"]
                        if not on and n in known and n in now})
    view = hermes_skill_view(after, cfgv)
    print(f"[hermes-skills] {len(changed)} changed, {len(p['plan'])} planned, "
          f"{view['in_prompt']}/{view['total']} skills in the prompt "
          f"failed={failed} stuck={stuck} pinned_on={pinned_on}", flush=True)
    # A name upstream refused to move did NOT change, whatever the 200 said.
    changed = [n for n in changed if n not in set(pinned_on)]
    note = "takes effect on the next Hermes chat"
    if failed:
        note = "some skills could not be written — " + " · ".join(failed)
    elif pinned_on:
        note = ("Hermes will not let these be switched off — " +
                " · ".join(pinned_on))
    return JSONResponse({
        "ok": not failed, "changed": changed, "failed": failed,
        "unknown": p["unknown"], "stuck": stuck, "pinned_on": pinned_on,
        "enabled_count": view["enabled_count"], "in_prompt": view["in_prompt"],
        "total": view["total"], "scope": "global", "restart_required": False,
        "note": note,
    }, status_code=200 if not failed else 502)


@app.get("/api/browse/status")
async def browse_status() -> JSONResponse:
    try:
        s = await _ody_find_mcp("browsermcp")
    except Exception:
        s = None
    hermes = _hermes_has_mcp()
    return JSONResponse({"on": bool(s) or hermes, "odysseus": bool(s),
                         "hermes": hermes, "connected": (s or {}).get("status") == "connected"})


@app.post("/api/browse/toggle")
async def browse_toggle(req: Request) -> JSONResponse:
    """Register/remove the stdio Browser MCP in BOTH Odysseus (live API) and Hermes
    (config.yaml, applies to new Hermes chats). One control → both components."""
    on = bool((await req.json()).get("on"))
    log = []
    try:
        existing = await _ody_find_mcp("browsermcp")
        if on and not existing:
            r = await _ody_req("POST", "/api/mcp/servers", data=_BROWSERMCP)
            log.append(f"odysseus:{r.status_code}")
        elif not on and existing:
            r = await _ody_req("DELETE", f"/api/mcp/servers/{existing['id']}")
            log.append(f"odysseus-del:{r.status_code}")
    except Exception as e:
        log.append(f"odysseus-err:{str(e)[:120]}")
    try:
        _hermes_set_mcp(on)
        log.append("hermes:ok")
    except Exception as e:
        log.append(f"hermes-err:{str(e)[:120]}")
    return JSONResponse({"ok": True, "on": on, "log": " · ".join(log)})
