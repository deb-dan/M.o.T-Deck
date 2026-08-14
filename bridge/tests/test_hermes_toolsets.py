"""Unit tests for the Hermes TOOLSET TRIMMING lever (bridge/app.py).

The lever's whole job is to make the Hermes lane's system prompt smaller, so the
tests concentrate on the two things that could silently make it BIGGER or make a
switch lie:

  * hermes_toolsets_valid  — an empty desired set is REFUSED, because upstream
    reads `platform_toolsets.cli: []` as "enable every toolset"
    (tools_config.py:2231 → tui_gateway/server.py:3915 `return None`). Getting
    this wrong would hand the model MORE tools when the user asked for fewer.
  * hermes_toolset_plan    — only CHANGED toolsets are written, so re-applying a
    preset is zero upstream PUTs, and unknown names are reported not written.

Everything under test is PURE (a dict/list in, a dict/list out) — no live Hermes,
no ~/.hermes, no network. _hermes_toolset_config is exercised over a TEMP
HERMES_HOME, and the bridge WIRING is asserted by reading app.py's source so a
renamed endpoint or a stray second yaml writer trips here.

Run: python3 bridge/tests/test_hermes_toolsets.py  (from repo root).
"""
import os
import sys
import tempfile
from pathlib import Path

for _k in [k for k in os.environ if k.lower().endswith("_proxy")]:
    os.environ.pop(_k, None)

_TMP = tempfile.mkdtemp(prefix="harness-hts-home-")
os.environ["HERMES_HOME"] = _TMP

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
import yaml  # noqa: E402
from bridge.app import (  # noqa: E402
    HERMES_MINIMAL_TOOLSETS, HERMES_TOOLSETS_EMPTY_REASON,
    hermes_toolset_names, hermes_toolsets_enabled, hermes_preset_desired,
    hermes_toolsets_valid, hermes_toolset_plan, hermes_toolset_view,
    hermes_skills_summary, _hermes_toolset_config, _hermes_config_path,
)

FAILS = []
CFG = Path(_TMP) / "config.yaml"


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


def row(name, enabled, tools=(), label=None, desc="", platform="cli",
        configured=True):
    return {"name": name, "label": label or name, "description": desc,
            "platform": platform, "platform_label": platform,
            "enabled": enabled, "available": enabled, "configured": configured,
            "tools": list(tools)}


# A stand-in for the real GET /api/tools/toolsets payload (shape read from
# hermes_cli/web_routers/tools.py:96-110 — name/label/description/platform/
# platform_label/enabled/available/configured/tools).
ROWS = [
    row("web", True, ["web_search", "web_extract"], "Web Search & Scraping"),
    row("terminal", True, ["terminal", "process"], "Terminal & Processes"),
    row("file", True, ["read_file", "write_file", "patch", "search_files"], "File Operations"),
    row("skills", True, ["skills_list", "skill_view", "skill_manage"], "Skills"),
    row("clarify", False, ["clarify"], "Clarifying Questions"),
    row("memory", True, ["memory"], "Memory"),
    row("spotify", False, ["spotify_play"], "Spotify"),
]

# ── readers ──────────────────────────────────────────────────────────────────
check("names in payload order",
      hermes_toolset_names(ROWS) == ["web", "terminal", "file", "skills",
                                     "clarify", "memory", "spotify"])
check("enabled subset only",
      hermes_toolsets_enabled(ROWS) == ["web", "terminal", "file", "skills", "memory"])
check("names: junk rows dropped, not raised",
      hermes_toolset_names([None, 1, "x", {}, {"name": ""}, {"name": "  a "}]) == ["a"])
check("names: non-list is empty", hermes_toolset_names(None) == []
      and hermes_toolset_names("web") == [])
check("enabled: missing key is falsy", hermes_toolsets_enabled([{"name": "z"}]) == [])
check("enabled: junk safe", hermes_toolsets_enabled([None, {"name": 5, "enabled": True}]) == [])

# ── presets ──────────────────────────────────────────────────────────────────
check("minimal preset = the floor set", set(hermes_preset_desired(ROWS, "minimal"))
      == {"file", "terminal", "clarify"})
check("minimal preset matches the constant",
      set(hermes_preset_desired(ROWS, "minimal")) == set(HERMES_MINIMAL_TOOLSETS))
check("minimal is INTERSECTED with what Hermes offers — a floor name this build "
      "lacks is dropped, never written",
      hermes_preset_desired([row("file", True)], "minimal") == ["file"])
check("all preset = every offered name",
      hermes_preset_desired(ROWS, "all") == hermes_toolset_names(ROWS))
check("'everything' is an alias of all",
      hermes_preset_desired(ROWS, "everything") == hermes_toolset_names(ROWS))
check("preset is case/space tolerant",
      hermes_preset_desired(ROWS, " Minimal ") == hermes_preset_desired(ROWS, "minimal"))
for junk in ("", "off", "none", "MIN", "lean", None, "clear"):
    check(f"unknown preset {junk!r} → None (a 400, never a silent no-op)",
          hermes_preset_desired(ROWS, junk) is None)

# ── the empty-set footgun ────────────────────────────────────────────────────
check("empty desired REFUSED", hermes_toolsets_valid(ROWS, []) == HERMES_TOOLSETS_EMPTY_REASON)
check("all-unknown desired REFUSED (it would land as an empty list)",
      hermes_toolsets_valid(ROWS, ["nope", "alsonope"]) == HERMES_TOOLSETS_EMPTY_REASON)
check("None desired REFUSED", hermes_toolsets_valid(ROWS, None) == HERMES_TOOLSETS_EMPTY_REASON)
check("the refusal says WHY (mentions the all-toolsets inversion)",
      "all toolsets" in HERMES_TOOLSETS_EMPTY_REASON)
check("one known name is enough", hermes_toolsets_valid(ROWS, ["file"]) == "")
check("one known + junk is enough", hermes_toolsets_valid(ROWS, ["file", "nope"]) == "")
check("no catalog at all is refused with its own reason",
      hermes_toolsets_valid([], ["file"]) == "Hermes reported no configurable toolsets")
check("minimal preset always passes validation",
      hermes_toolsets_valid(ROWS, hermes_preset_desired(ROWS, "minimal")) == "")
check("all preset always passes validation",
      hermes_toolsets_valid(ROWS, hermes_preset_desired(ROWS, "all")) == "")

# ── plan: minimal writes ─────────────────────────────────────────────────────
p = hermes_toolset_plan(ROWS, ["file", "terminal", "clarify"])
check("plan turns OFF exactly the surplus",
      sorted(n for n, on in p["plan"] if not on) == ["memory", "skills", "web"])
check("plan turns ON exactly what's missing",
      [n for n, on in p["plan"] if on] == ["clarify"])
check("plan leaves already-correct rows alone (file/terminal/spotify)",
      p["unchanged"] == 3)
check("plan never mentions an unchanged row",
      "file" not in [n for n, _ in p["plan"]] and "spotify" not in [n for n, _ in p["plan"]])
check("plan preserves payload order",
      [n for n, _ in p["plan"]] == ["web", "skills", "clarify", "memory"])

p2 = hermes_toolset_plan(ROWS, hermes_toolsets_enabled(ROWS))
check("re-applying the CURRENT state is ZERO writes", p2["plan"] == []
      and p2["unchanged"] == len(ROWS))
p3 = hermes_toolset_plan(ROWS, hermes_preset_desired(ROWS, "all"))
check("'all' from this state only turns the two off rows on",
      sorted(n for n, on in p3["plan"] if on) == ["clarify", "spotify"]
      and [n for n, on in p3["plan"] if not on] == [])
p4 = hermes_toolset_plan(ROWS, ["file", "ghost", "phantom"])
check("unknown names are REPORTED", p4["unknown"] == ["ghost", "phantom"])
check("unknown names are never written",
      set(n for n, _ in p4["plan"]) <= set(hermes_toolset_names(ROWS)))
check("plan totals account for every row",
      len(p4["plan"]) + p4["unchanged"] == len(ROWS))
check("plan on an empty catalog is empty, not an exception",
      hermes_toolset_plan([], ["file"]) == {"plan": [], "unknown": ["file"], "unchanged": 0})
check("plan tolerates non-string desired entries",
      hermes_toolset_plan(ROWS, [None, 3, "file"])["unknown"] == [])
# Idempotence: applying a plan then re-planning must be a fixed point.
after = [row(r["name"], (r["name"] in {"file", "terminal", "clarify"}), r["tools"])
         for r in ROWS]
check("plan is a fixed point once applied",
      hermes_toolset_plan(after, ["file", "terminal", "clarify"])["plan"] == [])

# ── view (counts, never invented tokens) ─────────────────────────────────────
v = hermes_toolset_view(ROWS, {"count": 78, "disabled_count": 2})
check("view counts enabled toolsets", v["enabled_count"] == 5 and v["total"] == 7)
check("view sums TOOLS of enabled toolsets only",
      v["tool_count_enabled"] == 2 + 2 + 4 + 3 + 1)
check("view sums all tools too", v["tool_count_total"] == 2 + 2 + 4 + 3 + 1 + 1 + 1)
check("view carries the skill count through", v["skills"]["count"] == 78
      and v["skills"]["disabled_count"] == 2)
check("view has NO token estimate field (schemas are not in the probe, so any "
      "per-toolset token figure would be invented)",
      not [k for k in v if "token" in k]
      and not [k for k in v["toolsets"][0] if "token" in k])
check("view row keeps name/label/description/enabled/tools/tool_count/needs_setup",
      set(v["toolsets"][0]) == {"name", "label", "description", "platform",
                               "enabled", "tools", "tool_count", "needs_setup"})

# ── needs_setup: UPSTREAM's own `configured` bool, mirrored not invented ──────
# Provenance: web_routers/tools.py:107 (the field) ← tools_config._toolset_has_keys
# :2589 (the producer) — the SAME field Hermes's Skills→TOOLSETS page prints its
# amber "Setup needed" caption from (web/src/pages/SkillsPage.tsx:606).
def ns(r):
    return hermes_toolset_view([r])["toolsets"][0]["needs_setup"]


check("configured:False → needs_setup True", ns(row("browser", True, configured=False)) is True)
check("configured:True  → needs_setup False", ns(row("file", True, configured=True)) is False)
# FAIL OPEN: only an EXPLICIT False warns. A build/probe shape that omits the key, or
# returns junk in it, must never invent a scary pill on a working toolset.
_bare = row("file", True)
del _bare["configured"]
check("missing configured → no warning (fail open)", ns(_bare) is False)
check("configured:None → no warning", ns(row("x", True, configured=None)) is False)
check("configured:'' → no warning (only a real False)", ns(row("x", True, configured="")) is False)
check("configured:0 → no warning (0 is not False here — an explicit bool is required)",
      ns(row("x", True, configured=0)) is False)
check("configured:'no' → no warning", ns(row("x", True, configured="no")) is False)
check("needs_setup is independent of our switch (knowing BEFORE enabling is the point)",
      ns(row("browser", False, configured=False)) is True)
check("needs_setup never affects the counts",
      hermes_toolset_view([row("a", True, ["t"], configured=False)])["tool_count_enabled"] == 1)
check("view drops junk rows", len(hermes_toolset_view([None, {}, {"name": 2}])["toolsets"]) == 0)
check("view with no skills payload is zeroed, not missing",
      hermes_toolset_view(ROWS)["skills"] == {"count": 0, "disabled_count": 0})
check("view tolerates non-string tool entries",
      hermes_toolset_view([row("x", True, ["a", None, 3])])["tool_count_enabled"] == 1)
check("view of nothing is total 0", hermes_toolset_view([])["total"] == 0)

# ── skills summary ───────────────────────────────────────────────────────────
check("skills: bare list counted",
      hermes_skills_summary([{"name": "a"}, {"name": "b"}])["count"] == 2)
check("skills: wrapped dict counted",
      hermes_skills_summary({"skills": [{"name": "a"}]})["count"] == 1)
check("skills: disabled counted via enabled:false",
      hermes_skills_summary([{"enabled": False}, {"enabled": True}, {}])
      == {"count": 3, "disabled_count": 1})
for junk in (None, "x", 5, {}, {"skills": "no"}, [1, "a", None]):
    check(f"skills summary totality on {junk!r}",
          hermes_skills_summary(junk)["count"] >= 0)

# ── config reader over a REAL temp HERMES_HOME ───────────────────────────────
check("config path honours HERMES_HOME", _hermes_config_path().startswith(_TMP))
c0 = _hermes_toolset_config()
check("no config file → cli list is None (Hermes uses its default composite), "
      "NOT an empty list (which would mean something entirely different)",
      c0["platform_toolsets_cli"] is None)
check("no config file → no disabled_toolsets, coding_context defaults to auto",
      c0["disabled_toolsets"] == [] and c0["coding_context"] == "auto")

CFG.write_text(yaml.safe_dump({
    "model": {"default": "x"},
    "platform_toolsets": {"cli": ["file", "terminal", 12306]},
    "agent": {"disabled_toolsets": ["memory"], "coding_context": "FOCUS"},
}, sort_keys=False))
c1 = _hermes_toolset_config()
check("reads platform_toolsets.cli", c1["platform_toolsets_cli"] == ["file", "terminal", "12306"])
check("numeric yaml toolset names are stringified (a bare `12306:` parses as int)",
      all(isinstance(x, str) for x in c1["platform_toolsets_cli"]))
check("reads agent.disabled_toolsets", c1["disabled_toolsets"] == ["memory"])
check("coding_context lowercased", c1["coding_context"] == "focus")

CFG.write_text("platform_toolsets:\n  cli: notalist\nagent: 5\n")
c2 = _hermes_toolset_config()
check("a non-list cli value degrades to None, never to []",
      c2["platform_toolsets_cli"] is None)
check("a non-dict agent block degrades safely",
      c2["disabled_toolsets"] == [] and c2["coding_context"] == "auto")
CFG.write_text("this: is: not: yaml: [\n")
c3 = _hermes_toolset_config()
check("an unparseable config degrades instead of 500ing the panel",
      c3["platform_toolsets_cli"] is None and c3["coding_context"] == "auto")
CFG.write_text(yaml.safe_dump({"platform_toolsets": {"cli": []}}))
check("an EXPLICIT empty list is reported as [] (distinct from None) so the panel "
      "can tell 'saved as empty' from 'never saved'",
      _hermes_toolset_config()["platform_toolsets_cli"] == [])

# ── bridge WIRING (read out of app.py's source) ──────────────────────────────
SRC = (ROOT / "bridge" / "app.py").read_text()
check("GET endpoint exists", '@app.get("/api/hermes/toolsets")' in SRC)
check("POST endpoint exists", '@app.post("/api/hermes/toolsets")' in SRC)
check("the catalog is PROBED from Hermes, not hardcoded",
      '"/api/tools/toolsets"' in SRC and "_hermes_toolset_rows" in SRC)
check("writes go through upstream's own per-toolset PUT",
      '"PUT", f"/api/tools/toolsets/{name}"' in SRC)
check("the dashboard call carries the session token header",
      '"X-Hermes-Session-Token": tok' in SRC)
check("the loopback probe stays on 127.0.0.1",
      'f"http://127.0.0.1:{_hermes_port()}{path}"' in SRC)
check("NO second writer: the lever never writes platform_toolsets itself "
      "(that key appears in app.py only as a READ)",
      SRC.count("platform_toolsets") == SRC.count('.get("platform_toolsets")')
      + SRC.count("platform_toolsets_cli") + SRC.count("platform_toolsets.cli")
      + SRC.count("platform_toolsets.discord"))
check("the empty-set guard is actually called before any write",
      SRC.index("hermes_toolsets_valid(rows, desired)")
      < SRC.index('"PUT", f"/api/tools/toolsets/{name}"'))
check("a POST with Hermes down is a 409 naming the fix, not a silent success",
      "is not reachable — " in SRC and "status_code=409" in SRC)
check("restart_required is reported (and is False — the config is read at "
      "use-time, so a new chat suffices)", '"restart_required": False' in SRC)
check("the response re-probes and reports STUCK names rather than our intent",
      '"stuck": stuck' in SRC and "agent.disabled_toolsets" in SRC)
check("focus mode is detected and surfaced",
      '"focus_override"' in SRC and 'cfgv["coding_context"] == "focus"' in SRC)
check("a write is logged for post-hoc diagnosis", "[hermes-tools]" in SRC)

# ── panel WIRING ─────────────────────────────────────────────────────────────
PANEL = (ROOT / "bridge" / "panel" / "index.html").read_text()
check("panel renders the group", "function renderHermesTools(" in PANEL)
check("group lands in the Tools sub-tab",
      "setSec('caps-sec-tools', renderHermesTools()" in PANEL)
check("group ALSO renders when Odysseus is unreachable (it writes Hermes, not "
      "Odysseus)", "innerHTML = renderHermesTools() + renderVoiceMcp()" in PANEL)
check("snapshot is loaded by initCaps", "await loadHermesTools();" in PANEL)
check("both preset chips exist",
      "hermesToolsPreset('minimal'" in PANEL and "hermesToolsPreset('all'" in PANEL)
check("per-toolset switch is wired", "toggleHermesToolset('" in PANEL)
check("switches are DISABLED when they cannot work (Hermes down / focus mode)",
      "hermesToolsetLocked(" in PANEL and "${lock ? 'disabled' : ''}" in PANEL)
check("the note tells the user when it applies",
      "next chat" in PANEL and "no restart" in PANEL)
check("zero new CSS: the group uses only existing caps classes",
      all(cls in PANEL for cls in ["caps-group", "cap-h", "cap-card", "cap-row",
                                   "cap-sw", "cap-pill", "cap-count", "cap-btn"]))

# ── the POST handler, run for real against a FAKE dashboard ──────────────────
# The plan→PUT loop, the re-probe, the stuck detection and every refusal path are
# EXECUTED here (not grepped) by swapping the one seam that touches the network.
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
    """Stands in for Hermes's dashboard: holds the enabled set, applies PUTs the way
    upstream does, and can pin a toolset 'forced off' (agent.disabled_toolsets)."""

    def __init__(self, enabled, forced_off=(), fail=(), down=False):
        self.enabled = set(enabled)
        self.forced_off = set(forced_off)
        self.fail = set(fail)
        self.down = down
        self.puts = []

    async def __call__(self, method, path, **kw):
        if self.down:
            raise RuntimeError("connection refused")
        if method == "GET" and path == "/api/tools/toolsets":
            return FakeResp(200, [
                row(r["name"], r["name"] in self.enabled and r["name"] not in self.forced_off,
                    r["tools"], r["label"]) for r in ROWS])
        if method == "GET" and path == "/api/skills":
            return FakeResp(200, [{"name": "s%d" % i} for i in range(78)])
        if method == "PUT" and path.startswith("/api/tools/toolsets/"):
            name = path.rsplit("/", 1)[1]
            self.puts.append((name, bool(kw.get("json", {}).get("enabled"))))
            if name in self.fail:
                return FakeResp(500)
            (self.enabled.add if kw["json"]["enabled"] else self.enabled.discard)(name)
            return FakeResp(200, {"ok": True})
        return FakeResp(404)


def post(body, dash):
    A._hermes_dash = dash
    r = asyncio.run(A.hermes_toolsets_set(FakeReq(body)))
    return r.status_code, json.loads(r.body)


def get(dash):
    A._hermes_dash = dash
    r = asyncio.run(A.hermes_toolsets_get())
    return r.status_code, json.loads(r.body)


_real_dash = A._hermes_dash
CFG.write_text("model:\n  default: x\n")     # a clean config for the handler tests

d = FakeDash(["web", "terminal", "file", "skills", "memory"])
code, j = post({"preset": "minimal"}, d)
check("POST minimal → 200", code == 200 and j["ok"] is True)
check("POST minimal wrote exactly the diff (3 off, 1 on)", len(d.puts) == 4)
check("POST minimal left the enabled set at the floor",
      d.enabled == {"file", "terminal", "clarify"})
check("POST minimal reports the new state", sorted(j["enabled"]) == ["clarify", "file", "terminal"])
check("POST minimal reports the tool count that now rides in the prompt",
      j["tool_count_enabled"] == 4 + 2 + 1)
check("POST minimal promises no restart", j["restart_required"] is False
      and "next Hermes chat" in j["note"])
check("POST minimal nothing stuck", j["stuck"] == [] and j["failed"] == [])

before = list(d.puts)
code, j = post({"preset": "minimal"}, d)
check("re-applying minimal is 200 with ZERO extra writes",
      code == 200 and d.puts == before and j["changed"] == [])

code, j = post({"preset": "all"}, d)
check("POST all turns everything on", code == 200
      and d.enabled == set(hermes_toolset_names(ROWS)))
code, j = post({"name": "skills", "on": False}, d)
check("single toggle off works", code == 200 and "skills" not in d.enabled)
check("single toggle wrote exactly one PUT", d.puts[-1] == ("skills", False))
code, j = post({"name": "skills", "on": True}, d)
check("single toggle back on works", code == 200 and "skills" in d.enabled)

# the footgun: the LAST toolset can never be switched off
d2 = FakeDash(["file"])
code, j = post({"name": "file", "on": False}, d2)
check("turning the LAST toolset off is REFUSED with 400", code == 400)
check("the refusal explains the all-toolsets inversion",
      j["error"] == HERMES_TOOLSETS_EMPTY_REASON)
check("nothing was written on the refusal", d2.puts == [] and d2.enabled == {"file"})
code, j = post({"enabled": []}, d2)
check("an explicit empty list is REFUSED too", code == 400 and d2.puts == [])
code, j = post({"enabled": ["ghost"]}, d2)
check("an all-unknown list is REFUSED (it would land as empty)", code == 400)

# unknown names are dropped + reported, never written
d3 = FakeDash(["web"])
code, j = post({"enabled": ["file", "ghost"]}, d3)
check("unknown names are reported", code == 200 and j["unknown"] == ["ghost"])
check("unknown names are never PUT", all(n != "ghost" for n, _ in d3.puts))

# a name forced off in agent.disabled_toolsets must be reported as STUCK
d4 = FakeDash(["file"], forced_off=["web"])
code, j = post({"enabled": ["file", "web"]}, d4)
check("a forced-off toolset is reported STUCK rather than claimed as enabled",
      j["stuck"] == ["web"] and "web" not in j["enabled"])
check("a stuck toolset does not make the call a failure (the write DID land; "
      "upstream simply subtracts it later)", code == 200 and j["ok"] is True)

# an upstream write failure is surfaced, not swallowed
d5 = FakeDash(["web", "terminal", "file", "skills", "memory"], fail=["memory"])
code, j = post({"preset": "minimal"}, d5)
check("a failed PUT → 502", code == 502 and j["ok"] is False)
check("the failing toolset is named", any(x.startswith("memory:") for x in j["failed"]))
check("the OTHER writes still landed (each PUT is its own atomic save)",
      "web" in j["changed"] and "memory" not in j["changed"])
check("the note carries the failure", "could not be written" in j["note"])

# unknown preset / bad shape / Hermes down
check("unknown preset → 400", post({"preset": "lean"}, FakeDash(["file"]))[0] == 400)
for bad_body in ({}, {"name": "   "}, {"enabled": "web"}, {"on": True}):
    code, j = post(bad_body, FakeDash(["file"], down=True))
    check(f"malformed body {bad_body} → 400 even with Hermes DOWN (the shape gate "
          f"runs before the probe)", code == 400)
check("a real request with Hermes down → 409 naming the fix",
      post({"preset": "minimal"}, FakeDash([], down=True))[0] == 409)

# GET against the fake dashboard
code, j = get(FakeDash(["file", "skills"]))
check("GET probes the live catalog", code == 200 and j["running"] is True
      and j["source"] == "probe" and j["total"] == len(ROWS))
check("GET reports the enabled count", j["enabled_count"] == 2)
check("GET carries the skill count for the skills row", j["skills"]["count"] == 78)
check("GET never claims a restart is needed", j["restart_required"] is False)
CFG.write_text(yaml.safe_dump({"agent": {"coding_context": "focus"}}))
code, j = get(FakeDash(["file"]))
check("GET flags focus mode, where the switches would be cosmetic",
      j["focus_override"] is True)
CFG.write_text(yaml.safe_dump({"agent": {"coding_context": "auto"}}))
check("GET does not flag the default posture", get(FakeDash(["file"]))[1]["focus_override"] is False)
code, j = get(FakeDash([], down=True))
check("GET with Hermes down is a 200 with running:false (the panel renders a note, "
      "not an error state)", code == 200 and j["running"] is False and j["error"])
A._hermes_dash = _real_dash

print()
print(("FAILED: " + ", ".join(FAILS)) if FAILS else "all checks passed")
sys.exit(1 if FAILS else 0)
