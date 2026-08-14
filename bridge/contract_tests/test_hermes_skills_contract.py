"""Per-skill trimming contract — pin-bump gate for the Hermes per-skill lever.

The lever (bridge/app.py `/api/hermes/skills`, panel Capabilities → Tools →
"Hermes tools" → the per-skill list under the `skills` row) shrinks the Hermes
lane's <available_skills> index by disabling individual skills. Every fact it
relies on is upstream-INTERNAL, so this purely static check greps the vendored
source and fails loudly if a pin bump moves any of them. No network, no build,
no running Hermes.

Run: pytest bridge/contract_tests/   (from harness root).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
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
    assert "return global_disabled | _normalize_string_set(platform_disabled)" in src, \
        "the per-platform list no longer ADDS to the global one — our lane-hidden " \
        "pill's one-directional reasoning depends on this union"


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
