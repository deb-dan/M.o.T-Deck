"""Unit tests for the path-guard fence.

Two surfaces, both pure:

* the PLUGIN matcher (guards/harness-path-guard/__init__.py) — imported directly
  from the file (never through Hermes) so no hermes venv is needed;
* the BRIDGE audit tier's containment helper (bridge/app.py guard_path_outside),
  extracted by ast so neither fastapi nor websockets is required.

Run directly: python3 bridge/tests/test_path_guard.py
"""
import ast
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "guards" / "harness-path-guard" / "__init__.py"

PASS = 0


def check(name, cond):
    global PASS
    assert cond, name
    PASS += 1
    print(f"  ok  {name}")


def _load_plugin():
    spec = importlib.util.spec_from_file_location("harness_path_guard_under_test", GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _load_plugin()

# ── containment (the /Users/debikEvil prefix trap) ──────────────────────────
check("path inside root", G.path_inside("/Users/debik/proj/a.txt", "/Users/debik/proj"))
check("root itself is inside", G.path_inside("/Users/debik/proj", "/Users/debik/proj"))
check("trailing slash on root tolerated",
      G.path_inside("/Users/debik/proj/a", "/Users/debik/proj/"))
check("sibling prefix is NOT inside (debikEvil trap)",
      not G.path_inside("/Users/debikEvil/x", "/Users/debik"))
check("longer name prefix NOT inside",
      not G.path_inside("/Users/debik/projX/a", "/Users/debik/proj"))
check("parent is not inside child",
      not G.path_inside("/Users/debik", "/Users/debik/proj"))
check("relative target never inside", not G.path_inside("proj/a.txt", "/Users/debik"))
check("empty inputs safe", not G.path_inside("", "/tmp") and not G.path_inside("/tmp", ""))

# ── classify: deny beats allow ──────────────────────────────────────────────
allow = ["/Users/debik/ws", "/Users/debik/.hermes", "/tmp"]
deny = ["/Users/debik/.ssh", "/Users/debik/.hermes/config.yaml"]
check("workspace write → allow",
      G.classify_path("/Users/debik/ws/a.txt", allow, deny)[0] == "allow")
check("~/.hermes write → allow",
      G.classify_path("/Users/debik/.hermes/skills/s.md", allow, deny)[0] == "allow")
check("desktop write → escalate",
      G.classify_path("/Users/debik/Desktop/a.txt", allow, deny)[0] == "escalate")
check("ssh write → deny",
      G.classify_path("/Users/debik/.ssh/authorized_keys", allow, deny)[0] == "deny")
check("deny BEATS allow (config.yaml sits inside ~/.hermes)",
      G.classify_path("/Users/debik/.hermes/config.yaml", allow, deny)[0] == "deny")
check("~/.hermes/config.yaml.bak is NOT the denied file (allow)",
      G.classify_path("/Users/debik/.hermes/config.yaml.bak", allow, deny)[0] == "allow")

# ── root resolution: placeholders, tilde, empty-placeholder drop ─────────────
home = tempfile.mkdtemp()
os.makedirs(os.path.join(home, ".hermes"), exist_ok=True)
cwd = tempfile.mkdtemp()
hroot = tempfile.mkdtemp()
os.makedirs(os.path.join(hroot, "data"), exist_ok=True)
roots = G.resolve_roots(["{HERMES_CWD}", "~/.hermes", "{HARNESS_ROOT}/data", "/tmp",
                         "{TMPDIR}"],
                        cwd=cwd, harness_root=hroot, tmpdir="", home=home)
check("{HERMES_CWD} resolved", os.path.realpath(cwd) in roots)
check("~ expanded against the given home",
      os.path.realpath(os.path.join(home, ".hermes")) in roots)
check("{HARNESS_ROOT} substituted",
      os.path.realpath(os.path.join(hroot, "data")) in roots)
check("empty {TMPDIR} DROPPED (never collapses to /)",
      "/" not in roots and len(roots) == 4)
check("unknown placeholder dropped",
      G.resolve_roots(["{NOPE}/x"], cwd=cwd, harness_root=hroot) == [])
check("relative root dropped",
      G.resolve_roots(["relative/dir"], cwd=cwd, harness_root=hroot) == [])

# realpath: a symlinked workspace resolves to its target
link_parent = tempfile.mkdtemp()
real_ws = os.path.join(link_parent, "real")
os.makedirs(real_ws, exist_ok=True)
link_ws = os.path.join(link_parent, "link")
os.symlink(real_ws, link_ws)
check("symlinked root realpath'd",
      G.resolve_roots([link_ws], cwd=cwd) == [os.path.realpath(real_ws)])
check("symlinked target realpath'd into the root",
      G.path_inside(G.abs_target(os.path.join(link_ws, "a.txt"), cwd=cwd, home=home),
                    os.path.realpath(real_ws)))

# ── abs_target ──────────────────────────────────────────────────────────────
check("relative target joined to cwd",
      G.abs_target("a.txt", cwd=cwd, home=home) == os.path.realpath(os.path.join(cwd, "a.txt")))
check("~ target expanded",
      G.abs_target("~/x.txt", cwd=cwd, home=home) == os.path.realpath(os.path.join(home, "x.txt")))

# ── target extraction / unresolved patches ──────────────────────────────────
check("write_file path extracted",
      G.extract_target("write_file", {"path": " a.txt "}) == ("a.txt", ""))
check("single-file patch path extracted",
      G.extract_target("patch", {"path": "a.py"})[0] == "a.py")
check("V4A multi-file patch → unresolved",
      G.extract_target("patch", {"patch": "*** Update File: a.py"})[0] is None)
check("non-dict args → unresolved", G.extract_target("write_file", None)[0] is None)

# ── evaluate: the directive shapes upstream consumes ────────────────────────
EV = lambda tool, args: G.evaluate(tool, args, allow_roots=allow, deny_roots=deny,
                                   cwd="/Users/debik/ws", home="/Users/debik")
check("non-gated tool → None (fast no-op)", EV("read_file", {"path": "/etc/hosts"}) is None)
check("terminal not gated here", EV("terminal", {"command": "rm -rf /"}) is None)
check("skill_manage NOT gated (out of scope)",
      EV("skill_manage", {"file_path": "x"}) is None)
check("workspace-relative write → None", EV("write_file", {"path": "notes.txt"}) is None)
d = EV("write_file", {"path": "/Users/debik/Desktop/a.txt"})
check("outside write → approve directive",
      d and d["action"] == "approve" and "/Users/debik/Desktop/a.txt" in d["message"])
check("rule_key = per-directory grain",
      d["rule_key"] == "path-guard:/Users/debik/Desktop")
d2 = EV("write_file", {"path": "/Users/debik/.ssh/id_rsa"})
check("deny → block directive with the matched root",
      d2 and d2["action"] == "block" and "/Users/debik/.ssh" in d2["message"])
check("block carries a message (upstream drops message-less blocks)",
      bool(d2.get("message")))
d3 = EV("patch", {"patch": "*** Begin Patch"})
check("unresolved patch → escalate, never None",
      d3 and d3["action"] == "approve" and "cannot verify" in d3["message"])
check("no allow roots at all → everything escalates (fail-closed)",
      (G.evaluate("write_file", {"path": "/Users/debik/ws/a.txt"}, allow_roots=[],
                  deny_roots=[], cwd="/Users/debik/ws") or {}).get("action") == "approve")

# ── fail-closed hook wrapper: an exception escalates, never allows ──────────
_orig = G.load_policy
try:
    G.load_policy = lambda p: (_ for _ in ()).throw(RuntimeError("boom"))
    d4 = G._on_pre_tool_call(tool_name="write_file", args={"path": "a.txt"})
    check("exception inside the hook → approve directive (fail-closed)",
          d4 and d4["action"] == "approve")
    check("non-gated tool short-circuits BEFORE the failing policy read",
          G._on_pre_tool_call(tool_name="read_file", args={"path": "a"}) is None)
finally:
    G.load_policy = _orig

# ── policy parsing ─────────────────────────────────────────────────────────
pol = G.parse_policy_text((ROOT / "guards" / "harness-path-guard" / "policy.yaml").read_text())
check("shipped policy parses with the 5 allow roots", len(pol["allow"]) == 5)
check("shipped policy parses with the 5 deny roots", len(pol["deny"]) == 5)
check("shipped policy allows the workspace placeholder", "{HERMES_CWD}" in pol["allow"])
check("shipped policy denies ~/.ssh", "~/.ssh" in pol["deny"])
check("mini parser matches the yaml parser",
      G._mini_parse((ROOT / "guards" / "harness-path-guard" / "policy.yaml").read_text())
      == pol)
check("garbage policy → empty lists (escalate-all, not allow-all)",
      G.parse_policy_text("not: a policy") == {"allow": [], "deny": []})
check("missing policy file → empty policy",
      G.load_policy("/nonexistent/policy.yaml") == {"allow": [], "deny": []})

# ── bridge audit tier (C): same containment, extracted from app.py ──────────
def _load_bridge_helper():
    src = (ROOT / "bridge" / "app.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "guard_path_outside")
    ns = {"os": os, "_guard_allow_roots": lambda: []}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "guard", "exec"), ns)
    return ns["guard_path_outside"]


OUT = _load_bridge_helper()
check("audit: inside root → not flagged",
      not OUT("/Users/debik/ws/a.txt", roots=["/Users/debik/ws"]))
check("audit: outside root → flagged",
      OUT("/Users/debik/Desktop/a.txt", roots=["/Users/debik/ws"]))
check("audit: debikEvil prefix trap flagged",
      OUT("/Users/debikEvil/a.txt", roots=["/Users/debik"]))
check("audit: no roots → silent (never cry wolf)",
      not OUT("/Users/debik/Desktop/a.txt", roots=[]))
check("audit: relative path → silent (cwd unknown bridge-side)",
      not OUT("notes.txt", roots=["/Users/debik/ws"]))
check("audit: empty path safe", not OUT("", roots=["/Users/debik/ws"]))

print(f"\n{PASS}/{PASS} path-guard checks passed")
