"""Per-skill trimming contract — pin-bump gate for the Hermes per-skill lever.

The lever (bridge/app.py `/api/hermes/skills`, panel Capabilities → Tools →
"Hermes tools" → the per-skill list under the `skills` row) shrinks the Hermes
lane's <available_skills> index by disabling individual skills. Every fact it
relies on is upstream-INTERNAL, so this purely static check greps the vendored
source and fails loudly if a pin bump moves any of them. No network, no build,
no running Hermes.

Run: pytest bridge/contract_tests/   (from motdeck root).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# ⚠️ THE APP LAYER IS NO LONGER ONE FILE (router/core split, 2026-08-28).
# bridge/app.py is a FACADE over bridge/core/*.py + bridge/routers/*.py, so the
# source-text assertions below read bridge/appsrc.py's assembled view of the whole
# app layer instead of one file. Read bridge/appsrc.py's header for why the
# assertions are source-text in the first place and why order is part of it.
import sys as _sys                                          # noqa: E402
_sys.path.insert(0, str(ROOT))                              # noqa: E402
from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402
HERMES = ROOT / "vendor" / "hermes"


def _read(rel: str) -> str:
    p = HERMES / rel
    assert p.exists(), f"vendored file missing: {rel}"
    return p.read_text(encoding="utf-8", errors="replace")


def test_upstream_exposes_a_per_skill_toggle_route():
    """`PUT /api/skills/toggle` is the ONLY writer we use.

    The alternative — writing `skills.disabled` ourselves through the atomic yaml
    helper — was rejected for the reason recorded for the toolset lever: a second
    writer of the same key drifts from upstream's own bookkeeping at any pin bump.
    If this route disappears, the lever must be re-thought, not silently swapped
    for a private writer.
    """
    src = _read("hermes_cli/web_routers/skills.py")
    assert '@router.put("/api/skills/toggle")' in src, \
        "the per-skill toggle route moved or vanished"
    assert "async def toggle_skill(body: SkillToggle" in src
    assert "save_disabled_skills(config, disabled)" in src, \
        "the toggle no longer persists through save_disabled_skills"


def test_toggle_body_is_name_plus_enabled():
    """The exact body the bridge sends: {"name": ..., "enabled": bool}."""
    models = _read("hermes_cli/web_models.py")
    m = re.search(r"class SkillToggle\(BaseModel\):(.*?)\n\n", models, re.S)
    assert m, "SkillToggle model not found"
    body = m.group(1)
    assert re.search(r"\bname:\s*str", body), "SkillToggle.name is gone"
    assert re.search(r"\benabled:\s*bool", body), "SkillToggle.enabled is gone"
    # If a `platform` field ever appears, our GLOBAL-scope UI copy becomes wrong
    # and the lever should start writing platform_disabled.cli instead.
    assert not re.search(r"\bplatform:\s*", body), \
        "SkillToggle grew a platform field — the lever's 'this is global' copy " \
        "is now wrong and it should scope writes to the cli platform"


def test_the_dashboard_toggle_writes_the_GLOBAL_disabled_list():
    """`save_disabled_skills(config, disabled)` with no platform writes
    `skills.disabled` — the global list.

    This is why our UI says a skill switched off here is off on EVERY Hermes
    surface. If upstream ever routes the dashboard toggle through a platform,
    that sentence becomes a lie and must change with it.
    """
    src = _read("hermes_cli/skills_config.py")
    assert "def save_disabled_skills(config: dict, disabled: Set[str], platform" in src
    assert re.search(r'if platform is None:\s*\n\s*config\["skills"\]\["disabled"\]\s*=',
                     src), "the global branch of save_disabled_skills changed shape"


def test_the_global_list_is_unioned_into_every_platform():
    """A globally-disabled skill stays disabled on every platform — which is what
    makes a global write always reach OUR (cli) lane.

    The per-platform list only ADDS, which is also why our lane-hidden pill is
    one-directional (the listing can over-report, never under-report).
    """
    src = _read("agent/skill_utils.py")
    assert "def get_disabled_skill_names(" in src
    assert 'global_disabled = _normalize_string_set(skills_cfg.get("disabled"))' in src
    assert 'skills_cfg.get("platform_disabled") or {}' in src, \
        "skills.platform_disabled is no longer the per-platform key"
    # ⚠️ WIDENED AT THE v0.20.6 BUMP (2026-08-28), and the reason is recorded here
    # rather than only in a report: v0.20.6 wraps the union in
    # `(global | platform) - ESSENTIAL_SKILLS`. The UNION is what this test guards
    # and it is intact; the subtraction is a NEW upstream fact, pinned by
    # test_essential_skills_cannot_be_disabled_from_either_side below. Matching the
    # union alone (not the whole `return` line) is what lets this assertion survive
    # that wrapper while still failing if the `|` ever becomes a `&` or the
    # platform list ever REPLACES the global one.
    assert "global_disabled | _normalize_string_set(platform_disabled)" in src, \
        "the per-platform list no longer ADDS to the global one — our lane-hidden " \
        "pill's one-directional reasoning depends on this union"


def test_essential_skills_cannot_be_disabled_from_either_side():
    """UPSTREAM GAINS A SET OF SKILLS NO SURFACE MAY SWITCH OFF, and our lever is one
    of those surfaces.

    ⚠️ THIS TEST IS DORMANT AT THE PIN WE SHIP (v2026.8.13 / v0.20.1) AND ARMS BY
    ITSELF. It was written on 2026-08-28 against v2026.8.27 (v0.20.6), where
    `ESSENTIAL_SKILLS` first appears; that bump was rolled back for unrelated
    reasons (see docs/handoff/HERMES-v0.20.6-BLOCKED-2026-08-28.md), so the
    constant is absent again and this returns early. It is KEPT, rather than
    deleted with the bump, because the finding is real and the next builder to
    move this pin should not have to rediscover it. The `pinned_on` reporting in
    bridge/app.py is inert while the constant is absent, which is why leaving it
    in place is free.

    `agent/skill_utils.ESSENTIAL_SKILLS` (exactly {"hermes-agent"} at this pin) is
    subtracted SYMMETRICALLY: `save_disabled_skills` drops it on the way IN and
    `get_disabled_skills` drops it on the way OUT (hermes_cli/skills_config.py:55-74).

    THE SYMMETRY IS THE WHOLE POINT, because it is what keeps our panel honest:
      · because the WRITER drops it, `PUT /api/skills/toggle {"enabled": false}`
        answers 200 and persists nothing;
      · because the READER drops it too, `GET /api/skills` reports that skill
        ENABLED again — so the listing and the model's actual prompt AGREE, and
        `hermes_skill_lane_off`'s one-directional claim stays true.
    If the subtraction ever goes ASYMMETRIC (dropped on write but honoured on read,
    or the reverse), the listing and the lane disagree and the pill starts lying.

    Our side: POST /api/hermes/skills re-probes and reports `pinned_on` for a name
    that refused to go off, and the panel prints a sentence for it. Without that,
    sample's switch snapped back with no explanation and it looked like our bug.
    """
    utils = _read("agent/skill_utils.py")
    if "ESSENTIAL_SKILLS" not in utils:
        # Nothing is force-enabled at this pin, so every skill the toggle writes
        # really lands and `pinned_on` is always empty. Nothing to check.
        return
    assert "- ESSENTIAL_SKILLS" in utils, \
        "get_disabled_skill_names no longer subtracts the essential set"
    cfg = _read("hermes_cli/skills_config.py")
    # THE READER — every branch of it.
    assert cfg.count("- ESSENTIAL_SKILLS") >= 3, (
        "get_disabled_skills stopped subtracting the essential set on one of its "
        "branches — the listing and our lane can now disagree")
    # THE WRITER. This is the half that makes the 200 a no-op.
    writer = cfg.split("def save_disabled_skills", 1)[1].split("\ndef ", 1)[0]
    assert "disabled = set(disabled) - ESSENTIAL_SKILLS" in writer, (
        "save_disabled_skills no longer drops essential skills on the way in — "
        "either the toggle now really disables them (drop `pinned_on`) or the "
        "config and the resolver have gone asymmetric (a lie in the panel)")
    # Our own reporting must still be there.
    app = _APP_SOURCE
    assert '"pinned_on": pinned_on' in app, (
        "the skills lever stopped reporting the names Hermes refuses to switch "
        "off — a request to disable one answers 200 and does nothing")


def test_upstream_ships_no_default_disabled_skills():
    """HERMES_SKILL_DEFAULT_DISABLED is () because DEFAULT_CONFIG's `skills`
    block has no `disabled` key at all — a fresh install enables every skill.

    The moment upstream ships a default disabled list, "Hermes's defaults" must
    stop meaning "everything on" or it becomes the same defect the toolset
    preset had (silently switching on things Hermes deliberately keeps off).
    """
    src = _read("hermes_cli/config_defaults.py")
    i = src.index('"skills": {')
    depth, j = 0, i + len('"skills": ')
    for k in range(j, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                break
    block = src[i:k + 1]
    assert '"external_dirs"' in block, "not the skills defaults block"
    assert '"disabled"' not in block, \
        "DEFAULT_CONFIG now ships skills.disabled — update " \
        "HERMES_SKILL_DEFAULT_DISABLED in bridge/app.py so the defaults chip " \
        "restores UPSTREAM's set, not 'everything'"


def test_the_listing_reports_enabled_per_skill():
    """`GET /api/skills` is the read side: the full catalog with upstream's own
    `enabled` bool. Our rows render that field and never our last write."""
    src = _read("hermes_cli/web_routers/skills.py")
    assert '@router.get("/api/skills")' in src
    assert "skills = _find_all_skills(skip_disabled=True)" in src, \
        "the listing no longer returns the FULL catalog — disabled skills would " \
        "vanish from our list instead of showing as switched off"
    assert 's["enabled"] = s["name"] not in disabled' in src, \
        "the listing's `enabled` field changed shape"
    assert "disabled = get_disabled_skills(config)" in src, \
        "the listing now resolves a platform — our lane-hidden pill assumes it " \
        "reads the GLOBAL list only and would start double-reporting"


def test_the_listing_name_is_the_name_the_prompt_builder_disables_on():
    """THE RECORDED GOTCHA, pinned from both ends.

    Memory records "the names stored there are frontmatter names, not directory
    names". At this pin the listing's `name` is
    `frontmatter.get("name", skill_dir.name)` and the prompt builder skips a
    skill when EITHER its frontmatter name OR its directory name is in the
    disabled set — so echoing the listing's own string back is correct by
    construction, and the lever never maps a name.

    If either half changes, the echo may stop matching and the lever would start
    writing names that disable nothing.
    """
    tool = _read("tools/skills_tool.py")
    assert re.search(r'name\s*=\s*frontmatter\.get\("name",\s*skill_dir\.name\)', tool), \
        "the listing's skill name is no longer frontmatter-name-or-directory-name"
    pb = _read("agent/prompt_builder.py")
    assert len(re.findall(
        r"if\s+(?:entry\[\"frontmatter_name\"\]|frontmatter_name)\s+in\s+disabled"
        r"\s+or\s+skill_name\s+in\s+disabled", pb)) >= 2, \
        "the prompt builder no longer accepts BOTH the frontmatter name and the " \
        "directory name in skills.disabled"


def test_the_skill_index_is_rebuilt_from_the_disabled_set_with_no_restart():
    """The panel promises "takes effect on the next chat, no restart".

    That holds because the skills prompt cache key INCLUDES the disabled set, so
    a config write invalidates it rather than being masked by a warm cache.
    """
    pb = _read("agent/prompt_builder.py")
    assert "disabled = get_disabled_skill_names(_platform_hint or None)" in pb
    assert re.search(r"tuple\(sorted\(disabled\)\)", pb), \
        "the disabled set is no longer part of the skills-prompt cache key — a " \
        "toggle could be masked by a warm cache and the panel's no-restart " \
        "promise would become false"


def test_there_is_still_no_bulk_toggle_route():
    """Our bulk actions are N sequential PUTs because upstream offers exactly one
    toggle route. If a bulk route appears, the bulk path should use it (a 78-row
    action is 78 atomic config saves today)."""
    src = _read("hermes_cli/web_routers/skills.py")
    assert len(re.findall(r'@router\.(put|post)\("/api/skills/toggle', src)) == 1
    assert "/api/skills/toggle-many" not in src and "/api/skills/bulk" not in src, \
        "upstream gained a bulk skill route — the lever's sequential PUT loop " \
        "should switch to it"


def test_the_skills_toolset_still_gates_the_whole_index():
    """The coarse lever this one refines: with the three skill TOOLS absent from
    the schema, upstream drops the entire <available_skills> block — which is why
    the per-skill list says it is moot while that switch is off."""
    src = _read("agent/system_prompt.py")
    assert "has_skills_tools" in src
    for t in ("skills_list", "skill_view", "skill_manage"):
        assert t in src, f"{t} is no longer part of the skill-index gate"
    assert 'skills_prompt = ""' in src
