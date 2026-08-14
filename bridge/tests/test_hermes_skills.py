"""Unit tests for the PER-SKILL trimming lever (bridge/app.py).

Sibling of test_hermes_toolsets.py, and deliberately the same shape. The `skills`
TOOLSET switch is all-or-nothing; this lever shrinks the same <available_skills>
index one skill at a time, and the things that could make it lie are:

  * a NAME we derived rather than echoed. Upstream disables a skill by NAME, and
    the listing's `name` is `frontmatter.get("name", skill_dir.name)`
    (tools/skills_tool.py:737) while the prompt builder skips on EITHER the
    frontmatter name or the directory name (agent/prompt_builder.py:1654/1676).
    The only safe rule is to post back the listing's own string, so the tests pin
    that the plan never invents, normalises or maps a name.
  * a SCOPE we widened. Upstream's `PUT /api/skills/toggle` takes no platform and
    writes the GLOBAL `skills.disabled` (hermes_cli/skills_config.py:64-72), and
    `skills.platform_disabled.cli` can only ADD — so we read it, never write it,
    and report the rows it hides rather than silently subtracting them.
  * a DEFAULT we invented. `config_defaults.py:1682`'s skills block has no
    `disabled` key, so "Hermes's defaults" is "everything on" AT THIS PIN — which
    is why the constant exists and is contract-pinned rather than hardcoded into
    the preset.
  * a BULK action that reached past what was on screen. `hermes_skill_plan`'s
    scope is what stops "turn off the 12 shown" from touching the hidden 66.

Everything under test is PURE except the two handlers, which are EXECUTED against
a fake dashboard by swapping the one seam that touches the network.

Run: python3 bridge/tests/test_hermes_skills.py   (from repo root).
"""
import os
import sys
import tempfile
from pathlib import Path

for _k in [k for k in os.environ if k.lower().endswith("_proxy")]:
    os.environ.pop(_k, None)

_TMP = tempfile.mkdtemp(prefix="harness-hsk-home-")
os.environ["HERMES_HOME"] = _TMP

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
import yaml  # noqa: E402
from bridge.app import (  # noqa: E402
    HERMES_SKILL_DEFAULT_DISABLED, HERMES_SKILL_TOGGLE_PATH,
    hermes_skill_rows, hermes_skill_names, hermes_skills_on,
    hermes_skill_lane_off, hermes_skill_preset_desired, hermes_skills_valid,
    hermes_skill_plan, hermes_skill_view,
    _hermes_toolset_config, _hermes_config_path,
)

FAILS = []
CFG = Path(_TMP) / "config.yaml"


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


def sk(name, enabled=True, category="general", desc="", prov="bundled"):
    """A stand-in for one /api/skills row (shape read from
    hermes_cli/web_routers/skills.py:394-423)."""
    return {"name": name, "description": desc, "category": category,
            "enabled": enabled, "usage": 0, "provenance": prov}


ROWS = [
    sk("pdf", True, "documents", "Work with PDF files"),
    sk("xlsx", True, "documents", "Spreadsheets"),
    sk("canvas-design", True, "design", "Posters and art"),
    sk("veriff-knowledge", False, "company", "Internal context"),
    sk("mcp-builder", True, "engineering", "Build MCP servers", prov="hub"),
]

# ── hermes_skill_rows: normalisation + totality ───────────────────────────────
r = hermes_skill_rows(ROWS)
check("rows preserve payload order", [x["name"] for x in r] ==
      ["pdf", "xlsx", "canvas-design", "veriff-knowledge", "mcp-builder"])
check("rows carry the fields the panel renders",
      set(r[0]) == {"name", "description", "category", "provenance", "enabled"})
check("enabled mirrors upstream's own bool", r[0]["enabled"] is True
      and r[3]["enabled"] is False)
check("a dict envelope is accepted too",
      hermes_skill_names(hermes_skill_rows({"skills": ROWS})) == hermes_skill_names(r))
check("a missing category degrades to 'uncategorized'",
      hermes_skill_rows([{"name": "x"}])[0]["category"] == "uncategorized")
# FAIL OPEN: only an explicit False is off. A build that stops sending `enabled`
# must not make the whole library look disabled (and then invite a "fix" that
# switches 78 skills on).
check("a row with NO enabled key fails OPEN (reads as on)",
      hermes_skill_rows([{"name": "x"}])[0]["enabled"] is True)
check("enabled:0 is not treated as off (only an explicit False is)",
      hermes_skill_rows([{"name": "x", "enabled": 0}])[0]["enabled"] is True)
check("enabled:False is off", hermes_skill_rows([{"name": "x", "enabled": False}])[0]["enabled"] is False)
# Names are ECHOED, never derived: whatever upstream calls a skill is what we
# post back, which is the whole discharge of the frontmatter-vs-directory gotcha.
check("a name with dots/slashes/spaces survives verbatim",
      hermes_skill_names(hermes_skill_rows([sk("anthropic-skills:pdf"), sk("a b.c/d")]))
      == ["anthropic-skills:pdf", "a b.c/d"])
check("a name is stripped but never rewritten",
      hermes_skill_names(hermes_skill_rows([{"name": "  pdf  "}])) == ["pdf"])
for junk in (None, "", 0, [], {}, {"skills": None}, {"skills": "x"},
             [None, 3, "x", {"name": 1}, {"name": ""}, {"name": "   "}, {"nope": 1}]):
    try:
        got = hermes_skill_rows(junk)
        ok = isinstance(got, list)
    except Exception:
        ok = False
    check("hermes_skill_rows total on %r" % (junk,), ok)
check("junk elements are dropped, real ones kept",
      hermes_skill_names(hermes_skill_rows([None, {"name": "keep"}, 7])) == ["keep"])
check("rows are idempotent on their own output",
      hermes_skill_rows(hermes_skill_rows(ROWS)) == hermes_skill_rows(ROWS))

check("hermes_skills_on is upstream's enabled subset",
      hermes_skills_on(ROWS) == ["pdf", "xlsx", "canvas-design", "mcp-builder"])
for junk in (None, "x", 3, [{"nope": 1}]):
    check("hermes_skills_on total on %r" % (junk,),
          isinstance(hermes_skills_on(junk), list))

# ── the platform-hidden set (read-only, one-directional, fail-open) ───────────
LO = hermes_skill_lane_off
check("no cfg ⇒ no claim", LO(ROWS, None) == [] and LO(ROWS, {}) == [])
check("no platform_disabled.cli key ⇒ no claim",
      LO(ROWS, {"skills_platform_disabled_cli": None}) == [])
check("a non-list platform_disabled.cli ⇒ no claim (fail open)",
      LO(ROWS, {"skills_platform_disabled_cli": "pdf"}) == []
      and LO(ROWS, {"skills_platform_disabled_cli": 7}) == [])
check("an empty list ⇒ no claim",
      LO(ROWS, {"skills_platform_disabled_cli": []}) == [])
check("a hidden-but-enabled skill IS reported",
      LO(ROWS, {"skills_platform_disabled_cli": ["pdf"]}) == ["pdf"])
# The reverse direction cannot happen (the platform list only ADDS), so a name
# that is ALREADY globally off must never produce a second, redundant pill.
check("a skill already off globally is NOT reported as lane-hidden",
      LO(ROWS, {"skills_platform_disabled_cli": ["veriff-knowledge"]}) == [])
check("a hidden name that is not installed is ignored",
      LO(ROWS, {"skills_platform_disabled_cli": ["ghost"]}) == [])
check("hidden names are compared after strip",
      LO(ROWS, {"skills_platform_disabled_cli": ["  pdf  "]}) == ["pdf"])

# ── presets: HERMES's defaults, never ours ───────────────────────────────────
check("upstream ships NO default-disabled skills at this pin",
      tuple(HERMES_SKILL_DEFAULT_DISABLED) == ())
check("'defaults' = every installed skill minus upstream's default-off set",
      hermes_skill_preset_desired(ROWS, "defaults") ==
      [n for n in hermes_skill_names(ROWS) if n not in set(HERMES_SKILL_DEFAULT_DISABLED)])
check("'all' is the same chip", hermes_skill_preset_desired(ROWS, "all")
      == hermes_skill_preset_desired(ROWS, "defaults"))
check("'none' is legal and means the empty set",
      hermes_skill_preset_desired(ROWS, "none") == [])
check("preset is case/space insensitive",
      hermes_skill_preset_desired(ROWS, "  DeFaults ") == hermes_skill_preset_desired(ROWS, "defaults"))
for bad in ("lean", "", None, "minimal", "  "):
    check("unknown preset %r returns None (caller must 400)" % (bad,),
          hermes_skill_preset_desired(ROWS, bad) is None)
check("a preset never names a skill the catalog does not have",
      set(hermes_skill_preset_desired(ROWS, "defaults")) <= set(hermes_skill_names(ROWS)))

# ── validity: NO empty-set refusal here, and that is the point ────────────────
# platform_toolsets.cli:[] means "enable everything" upstream, which is why the
# toolset lever refuses an empty target. skills.disabled has no such inversion:
# a full disabled list just empties the index, reversibly.
check("an empty desired set is ALLOWED for skills", hermes_skills_valid(ROWS, []) == "")
check("turning the last skill off is allowed",
      hermes_skills_valid([sk("only")], [], ["only"]) == "")
check("an EMPTY catalog is refused (writing blind)",
      hermes_skills_valid([], ["pdf"]) == "Hermes reported no skills")
for junk in (None, "x", 3):
    check("hermes_skills_valid total on rows=%r" % (junk,),
          isinstance(hermes_skills_valid(junk, []), str))

# ── the plan: minimal diff, scoped, never inventing ──────────────────────────
P = hermes_skill_plan
p = P(ROWS, hermes_skill_preset_desired(ROWS, "defaults"))
check("restoring defaults writes ONLY the one that was off",
      p["plan"] == [("veriff-knowledge", True)] and p["unchanged"] == 4)
check("re-applying defaults after that is zero writes",
      P([sk(n) for n in hermes_skill_names(ROWS)],
        hermes_skill_preset_desired(ROWS, "defaults"))["plan"] == [])
p = P(ROWS, [])
check("'none' turns off exactly the four that are on",
      [n for n, on in p["plan"]] == ["pdf", "xlsx", "canvas-design", "mcp-builder"]
      and all(on is False for _, on in p["plan"]))
check("the plan keeps payload order", [n for n, _ in p["plan"]] ==
      [n for n in hermes_skill_names(ROWS) if n in set(hermes_skills_on(ROWS))])
# THE BULK GUARD: a filtered "turn off the shown" must not reach the hidden rows.
p = P(ROWS, [], scope=["pdf", "xlsx"])
check("a scoped bulk-off touches ONLY the scoped rows",
      p["plan"] == [("pdf", False), ("xlsx", False)])
check("a scoped write leaves the rest of the catalog alone",
      "canvas-design" not in [n for n, _ in p["plan"]]
      and "mcp-builder" not in [n for n, _ in p["plan"]])
check("a scope naming an unknown skill changes nothing",
      P(ROWS, ["ghost"], scope=["ghost"])["plan"] == [])
check("an empty scope is a no-op, not a catalog-wide write",
      P(ROWS, [], scope=[])["plan"] == [])
check("unknown names are reported, never planned",
      P(ROWS, ["pdf", "ghost"])["unknown"] == ["ghost"]
      and "ghost" not in [n for n, _ in P(ROWS, ["pdf", "ghost"])["plan"]])
check("a plan over an empty catalog is empty",
      P([], ["pdf"])["plan"] == [] and P([], ["pdf"])["unknown"] == ["pdf"])
check("plan is a fixed point: applying it twice plans nothing the second time",
      P([sk(n, (n in {"pdf"})) for n in hermes_skill_names(ROWS)], ["pdf"])["plan"] == [])
for junk in (None, "x", 3, [1, 2]):
    try:
        ok = isinstance(P(junk, junk)["plan"], list)
    except Exception:
        ok = False
    check("hermes_skill_plan total on %r" % (junk,), ok)
check("non-string desired entries are ignored, not stringified",
      P(ROWS, [None, 7, "pdf"])["unknown"] == [])

# ── the view ─────────────────────────────────────────────────────────────────
v = hermes_skill_view(ROWS, {"skills_platform_disabled_cli": ["xlsx"]})
check("view totals", v["total"] == 5 and v["enabled_count"] == 4)
check("in_prompt subtracts the lane-hidden row", v["in_prompt"] == 3)
check("view marks the hidden row per-row",
      [s["name"] for s in v["skills"] if s["lane_off"]] == ["xlsx"])
check("view reports the hidden set", v["lane_off"] == ["xlsx"])
check("view names its scope as global (upstream writes skills.disabled)",
      v["scope"] == "global")
check("view lists categories in first-seen order",
      v["categories"] == ["documents", "design", "company", "engineering"])
v0 = hermes_skill_view(ROWS, None)
check("with no platform key in_prompt == enabled_count",
      v0["in_prompt"] == v0["enabled_count"] == 4 and v0["lane_off"] == [])
check("view of an empty catalog is all zeroes, not an error",
      hermes_skill_view([], None)["total"] == 0)
for junk in (None, "x", 3, [{"nope": 1}]):
    try:
        ok = hermes_skill_view(junk, junk)["total"] == 0
    except Exception:
        ok = False
    check("hermes_skill_view total on %r" % (junk,), ok)

# ── _hermes_toolset_config: the two skills keys, over a REAL temp HERMES_HOME ─
check("HERMES_HOME points at the temp dir", str(_hermes_config_path()) == str(CFG))
if CFG.exists():
    CFG.unlink()
c0 = _hermes_toolset_config()
check("no config file → no disabled skills, no platform key",
      c0["skills_disabled"] == [] and c0["skills_platform_disabled_cli"] is None)
CFG.write_text(yaml.safe_dump({
    "skills": {"disabled": ["pdf", 12306],
               "platform_disabled": {"cli": ["xlsx"], "telegram": ["pdf"]}}}))
c1 = _hermes_toolset_config()
check("reads skills.disabled", c1["skills_disabled"] == ["pdf", "12306"])
check("numeric yaml names are stringified, not dropped",
      all(isinstance(x, str) for x in c1["skills_disabled"]))
check("reads ONLY the cli platform list", c1["skills_platform_disabled_cli"] == ["xlsx"])
CFG.write_text(yaml.safe_dump({"skills": {"disabled": "just-one"}}))
check("a scalar skills.disabled is not exploded into characters",
      _hermes_toolset_config()["skills_disabled"] == [])
CFG.write_text(yaml.safe_dump({"skills": "nope"}))
check("a non-dict skills block degrades to empty",
      _hermes_toolset_config()["skills_disabled"] == []
      and _hermes_toolset_config()["skills_platform_disabled_cli"] is None)
CFG.write_text("skills: [oops\n  - broken")
check("an unparseable config degrades rather than raising",
      _hermes_toolset_config()["skills_disabled"] == [])
CFG.write_text(yaml.safe_dump({"skills": {"platform_disabled": {"cli": []}}}))
check("an explicitly EMPTY cli list is distinguished from absent",
      _hermes_toolset_config()["skills_platform_disabled_cli"] == [])
CFG.write_text(yaml.safe_dump({"model": {"default": "x"}}))
check("the toolset keys still work alongside the new ones",
      "platform_toolsets_cli" in _hermes_toolset_config()
      and "coding_context" in _hermes_toolset_config())

# ── the handlers, EXECUTED against a fake dashboard ──────────────────────────
import asyncio  # noqa: E402
import json     # noqa: E402
import bridge.app as A  # noqa: E402


class FakeResp:
    def __init__(self, code, payload=None):
        self.status_code = code
        self._p = payload

    def json(self):
        return self._p


class FakeReq:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


class FakeDash:
    """Stands in for Hermes's dashboard: holds the disabled set the way
    `save_disabled_skills` does and applies PUTs the way skills.py:426-437 does."""

    def __init__(self, disabled=(), fail=(), sticky=(), down=False):
        self.disabled = set(disabled)
        self.fail = set(fail)          # PUTs that 500
        self.sticky = set(sticky)      # names that refuse to come back on
        self.down = down
        self.puts = []

    async def __call__(self, method, path, **kw):
        if self.down:
            raise RuntimeError("connection refused")
        if method == "GET" and path == "/api/skills":
            return FakeResp(200, [
                sk(r["name"], r["name"] not in self.disabled
                   and r["name"] not in self.sticky, r["category"], r["description"])
                for r in ROWS])
        if method == "PUT" and path == HERMES_SKILL_TOGGLE_PATH:
            body = kw.get("json", {})
            name, on = body.get("name"), bool(body.get("enabled"))
            self.puts.append((name, on))
            if name in self.fail:
                return FakeResp(500)
            (self.disabled.discard if on else self.disabled.add)(name)
            return FakeResp(200, {"ok": True, "name": name, "enabled": on})
        return FakeResp(404)


def post(body, dash):
    A._hermes_dash = dash
    r = asyncio.run(A.hermes_skills_set(FakeReq(body)))
    return r.status_code, json.loads(r.body)


def get(dash):
    A._hermes_dash = dash
    r = asyncio.run(A.hermes_skills_get())
    return r.status_code, json.loads(r.body)


_real_dash = A._hermes_dash
CFG.write_text("model:\n  default: x\n")     # a clean config for the handler tests

d = FakeDash(disabled=["veriff-knowledge"])
code, j = get(d)
check("GET reports running + the probe as the source",
      code == 200 and j["running"] is True and j["source"] == "probe")
check("GET carries every installed skill", j["total"] == 5)
check("GET's enabled count is HERMES's answer, not our last write",
      j["enabled_count"] == 4)
check("GET names the write scope so the panel need not guess", j["scope"] == "global")

code, j = post({"name": "pdf", "on": False}, d)
check("single toggle off → 200 with exactly ONE upstream PUT",
      code == 200 and d.puts == [("pdf", False)])
check("the PUT body is upstream's own {name, enabled} shape",
      d.puts[-1] == ("pdf", False) and "pdf" in d.disabled)
check("the response reports the re-read truth, not the ask",
      j["enabled_count"] == 3 and j["total"] == 5)
check("no restart is promised or required",
      j["restart_required"] is False and "next Hermes chat" in j["note"])

before = list(d.puts)
code, j = post({"name": "pdf", "on": False}, d)
check("re-toggling to the SAME state is 200 with zero writes",
      code == 200 and d.puts == before and j["changed"] == [])

code, j = post({"preset": "defaults"}, d)
check("'Hermes's defaults' restores every installed skill", code == 200
      and d.disabled == set())
check("the defaults chip wrote only the two that were off",
      sorted(j["changed"]) == ["pdf", "veriff-knowledge"])

# THE BULK GUARD, end to end: a filtered off must not touch the hidden rows.
d2 = FakeDash()
code, j = post({"names": ["pdf", "xlsx"], "on": False}, d2)
check("bulk off writes exactly the named rows",
      code == 200 and sorted(n for n, _ in d2.puts) == ["pdf", "xlsx"])
check("bulk off leaves every unnamed skill enabled",
      d2.disabled == {"pdf", "xlsx"})
check("bulk ON is symmetric",
      post({"names": ["pdf"], "on": True}, d2)[0] == 200 and "pdf" not in d2.disabled)
check("a bulk list naming an unknown skill writes nothing for it",
      post({"names": ["ghost"], "on": False}, d2)[1]["changed"] == [])

# an explicit desired set is unscoped and may turn things off
d3 = FakeDash()
code, j = post({"enabled": ["pdf"]}, d3)
check("an explicit enabled list turns the rest off",
      code == 200 and d3.disabled == {"xlsx", "canvas-design",
                                      "veriff-knowledge", "mcp-builder"})
check("turning EVERY skill off is allowed (no empty-set footgun here)",
      post({"enabled": []}, FakeDash())[0] == 200)

# a skill that refuses to move is reported, not claimed
d4 = FakeDash(sticky=["xlsx"])
code, j = post({"enabled": hermes_skill_names(ROWS)}, d4)
check("a skill that stays off is reported STUCK", j["stuck"] == ["xlsx"])
check("a stuck skill does not make the call a failure (the write DID land)",
      code == 200 and j["ok"] is True)

# an upstream write failure is surfaced, not swallowed
d5 = FakeDash(fail=["xlsx"])
code, j = post({"enabled": []}, d5)
check("a failed PUT → 502", code == 502 and j["ok"] is False)
check("the failing skill is named", any(x.startswith("xlsx:") for x in j["failed"]))
check("the other writes still landed (each PUT is its own atomic save)",
      "pdf" in j["changed"] and "xlsx" not in j["changed"])
check("the note carries the failure", "could not be written" in j["note"])

check("unknown preset → 400", post({"preset": "minimal"}, FakeDash())[0] == 400)
for bad_body in ({}, {"name": "   "}, {"enabled": "pdf"}, {"on": True}, {"names": "pdf"}):
    code, j = post(bad_body, FakeDash(down=True))
    check("malformed body %r → 400 BEFORE the probe (never masked by a 409)"
          % (bad_body,), code == 400)
code, j = post({"name": "pdf", "on": False}, FakeDash(down=True))
check("Hermes down on a write → 409 naming the fix",
      code == 409 and "start it first" in j["error"])
code, j = get(FakeDash(down=True))
check("Hermes down on a read → running:false, source:config, no invention",
      code == 200 and j["running"] is False and j["source"] == "config"
      and j["total"] == 0 and j["skills"] == [])
A._hermes_dash = _real_dash

# ── WIRING (read out of the source, so a rename trips here) ──────────────────
SRC = (ROOT / "bridge" / "app.py").read_text()
check("the write goes through Hermes's own toggle route",
      'HERMES_SKILL_TOGGLE_PATH = "/api/skills/toggle"' in SRC
      and "_hermes_dash(\"PUT\", HERMES_SKILL_TOGGLE_PATH" in SRC)
check("the PUT body is upstream's {name, enabled}",
      'json={"name": name, "enabled": bool(on)}' in SRC)
# THE SECOND-WRITER RULE: we must never write skills.disabled ourselves. The
# whole reason the toolset lever goes through upstream's PUT applies here.
_CODE = "\n".join(l for l in SRC.splitlines() if not l.lstrip().startswith("#"))
check("the bridge never writes skills.disabled itself (upstream's PUT is the "
      "ONLY writer — a second one would drift at a pin bump)",
      '"skills_disabled"' in _CODE
      and 'data["skills"]' not in _CODE
      and 'setdefault("skills"' not in _CODE
      and "save_disabled_skills(" not in _CODE
      and '"skills"]["disabled"]' not in _CODE)
check("platform_disabled.cli is read but never written",
      '"skills_platform_disabled_cli"' in _CODE
      and 'platform_disabled"] =' not in _CODE
      and '"platform_disabled":' not in _CODE)
check("the skills lever adds no new yaml writer",
      "_set_yaml_scalar" not in _CODE.split("def hermes_skill_rows")[1]
      .split("@app.get(\"/api/browse/status\")")[0])
check("both endpoints exist under /api/hermes/skills",
      '@app.get("/api/hermes/skills")' in SRC
      and '@app.post("/api/hermes/skills")' in SRC)
check("the write re-probes and reports the truth",
      SRC.index("for name, on in p[\"plan\"]") < SRC.index("after = await _hermes_skill_rows()"))
check("the shape gate runs BEFORE the probe",
      SRC.index("preset, enabled, names or name required")
      < SRC.index("rows = await _hermes_skill_rows()\n    except Exception as e:\n"
                  "        return JSONResponse({\"ok\": False, \"error\": f\"Hermes is not reachable"))
check("the toolset lever's endpoints are untouched",
      '@app.get("/api/hermes/toolsets")' in SRC
      and '@app.post("/api/hermes/toolsets")' in SRC
      and '/api/hermes/toolsets/summary' in SRC)

PANEL = (ROOT / "bridge" / "panel" / "index.html").read_text()
check("the panel posts to the skills endpoint",
      "fetch('/api/hermes/skills'" in PANEL)
check("the sub-list hangs off the skills toolset row",
      "isSk ? renderHermesSkills(t)" in PANEL)
check("a bulk-off sends the SHOWN names explicitly (never a bare preset)",
      "{names: shown, on: false}" in PANEL)
check("the bulk-off only collects rows that are currently on",
      ".filter(s => s.enabled).map(s => s.name)" in PANEL)
check("a write re-READS rather than patching the panel's copy",
      "await loadHermesSkills();" in PANEL and "hermesSkillsSnap.skills[" not in PANEL)
check("the group NAMES the global scope",
      "off on <b>every</b> Hermes surface" in PANEL)
check("the staleness warning is carried, like the toolset group's",
      "loads its list once when it opens and never refreshes" in PANEL)
# The shell now reloads the Hermes webview on a tab switch when the bridge's
# `hermes_config_gen` has moved (app/main.swift syncHermesGen), so the copy promises
# that — but ONLY for the tab switch. Split view never switches tabs, so ⌘R stays the
# instruction there and the sentence must not overclaim.
check("...and the promise of an automatic reload is scoped to the tab switch",
      PANEL.count("switching to the Hermes tab reloads it for you") == 2)
check("...with the split-view exception named on both groups",
      PANEL.count("already open beside this one in split view") == 1
      and PANEL.count("already open <i>beside</i> this one in split view") == 1)

print()
print(("FAILED: " + "; ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
