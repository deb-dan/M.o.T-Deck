"""THE FACADE'S OWN GATE — what the router/core split promised, asserted forever.

bridge/app.py was 10,072 lines. On 2026-08-28 it became a ~250-line facade over
bridge/core/*.py + bridge/routers/*.py. The split's whole claim was ZERO behaviour
change, and the four ways that claim can quietly stop being true are pinned here.
Nothing in this file tests a lane's logic — every lane already has its own suite. This
tests the SEAM, which no other suite is looking at.

  1. THE FACADE IS TOTAL, NOT A LIST. 50+ suites, the contract gate, satellite modules
     and scripts/ reach into bridge.app for internals. app.py answers for them through a
     module-class proxy, so the surface is automatic; a re-export list would have been
     one forgotten line away from an AttributeError in a suite nobody ran that day.
     Asserted the only way that means anything: EVERY top-level name of EVERY lane must
     be reachable through bridge.app.

  2. A WRITE THROUGH THE FACADE MUST LAND WHERE THE CODE READS IT. This is the half a
     re-export cannot do and the half that is easy to break. Seven symbols are
     monkeypatched by the suite (`A.ROOT = tmpdir`, `A._script = fake`, …) and the patch
     has to change what the code under test CALLS. `from ..core.procs import _script`
     binds a name in each importing lane, so a write has to reach all of them. If this
     ever regresses, the affected tests do not error — they run against the REAL
     _script and the REAL ROOT, i.e. they run MOT Deck for real against the user's
     tree while reporting a pass. That is the worst failure shape in this file.

  3. THE DEPENDENCY DIRECTION HOLDS. core never imports a router; nothing imports
     app.py; the router graph stays acyclic. Each of those, violated, is a real import
     error at boot rather than a subtle bug — but they are violated by ADDING ONE
     IMPORT LINE while fixing something else, which is exactly when nobody is thinking
     about layering.

  4. THE MODULES STAY SMALL. The point of the exercise was that no file in the app
     layer is a monolith again. A ceiling only works if something enforces it.

Run: python bridge/tests/test_app_facade.py   (from repo root)
"""
import ast
import os
import re
import sys
import typing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Importing bridge.app builds httpx clients; the proxy cannot be tested without it, and
# this suite is about the proxy. Strip proxy env vars first, like the other suites that
# import it do.
for _k in [k for k in os.environ if k.lower().endswith("_proxy")]:
    os.environ.pop(_k, None)

import bridge.app as A                                            # noqa: E402
import bridge.appsrc as appsrc                                    # noqa: E402

FAILS = []
PASS = 0


def check(name, cond):
    global PASS
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL {name}")


LANES = [f for f in appsrc.FILES if f != "app.py"]
SRC = {f: (ROOT / "bridge" / f).read_text() for f in appsrc.FILES}


def top_level_names(src):
    out = set()
    for n in ast.parse(src).body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.Assign):
            out |= {t.id for t in n.targets if isinstance(t, ast.Name)}
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            out.add(n.target.id)
        elif isinstance(n, ast.Try):                    # the defensive satellite imports
            for s in ast.walk(n):
                if isinstance(s, ast.Assign):
                    out |= {t.id for t in s.targets if isinstance(t, ast.Name)}
                elif isinstance(s, (ast.Import, ast.ImportFrom)):
                    out |= {(a.asname or a.name.split(".")[0]) for a in s.names}
    return out


# ── 1. the facade is total ───────────────────────────────────────────────────
print("\n── 1. every lane symbol is reachable through bridge.app ──")
unreachable = []
for f in LANES:
    for nm in sorted(top_level_names(SRC[f])):
        if nm.startswith("__"):
            continue
        if not hasattr(A, nm):
            unreachable.append(f"{f}:{nm}")
check("no lane symbol is unreachable through bridge.app "
      f"({sum(len(top_level_names(SRC[f])) for f in LANES)} names checked)",
      not unreachable)
if unreachable:
    print("       unreachable:", unreachable[:20])

check("the FastAPI instance is a real attribute of bridge.app (uvicorn loads "
      "bridge.app:app by that name, and the proxy must not be what answers for it)",
      "app" in vars(A))
check("…and it is the same object the lanes decorated",
      A.app is sys.modules["bridge.core.appctx"].app)
check("a name no lane defines still raises AttributeError rather than returning None",
      not hasattr(A, "definitely_not_a_symbol_in_this_motdeck"))

# ── 2. writes land where the code reads them ─────────────────────────────────
print("\n── 2. a monkeypatch through the facade reaches every reader ──")
# The seven the suite actually patches, enumerated so a REMOVED one is noticed too.
# (owner is not asserted — it may legitimately move; reachability and propagation are.)
PATCHED = ["ROOT", "_script", "_set_runner_model", "_proc_cmdline",
           "_port_listener_pids", "_hermes_dash", "aider_spawn_spec"]
# ⚠️ LANES ONLY — AND THAT BOUNDARY IS THE PRE-SPLIT BEHAVIOUR, NOT A SHORTCUT.
# bridge/voice.py has a ROOT of its own, and `A.ROOT = tmpdir` never touched it when
# app.py was one file either: the satellites are separate modules that resolve their
# own paths (office_mcp.configure(ROOT) is the explicit hand-off, and it exists exactly
# because "two ideas of where MOT Deck lives" is a known bug shape here). Widening
# the proxy to the satellites would be a behaviour CHANGE dressed as thoroughness, so
# the fence below asserts the satellites are left alone.
LANE_MODS = {"bridge." + f[:-3].replace("/", ".") for f in appsrc.FILES}
for nm in PATCHED:
    holders = [m for m in sys.modules.values()
               if getattr(m, "__name__", "") in LANE_MODS and nm in vars(m)]
    check(f"`{nm}` is reachable and at least one module holds it", bool(holders))
    if not holders:
        continue
    saved = {m: vars(m)[nm] for m in holders}
    sentinel = object()
    setattr(A, nm, sentinel)
    landed = [m for m in holders if vars(m)[nm] is sentinel]
    check(f"…and setting bridge.app.{nm} reached ALL {len(holders)} of them "
          f"(not just the owner)", len(landed) == len(holders))
    check(f"…and reading it back through the facade agrees",
          getattr(A, nm) is sentinel)
    for m, v in saved.items():
        setattr(m, nm, v)
    if nm in vars(A):
        setattr(A, nm, saved[[m for m in holders
                              if getattr(m, "__name__", "") == "bridge.core.appctx"][0]]
                if any(getattr(m, "__name__", "") == "bridge.core.appctx" for m in holders)
                else list(saved.values())[0])
    check(f"…and it is restored", getattr(A, nm) is not sentinel)

# ROOT is the one whose blast radius is the whole motdeck — spell out that the
# rebinding really is wide, because a partial rebind is the silent-danger case.
_root_holders = [m for m in sys.modules.values()
                 if getattr(m, "__name__", "") in LANE_MODS and "ROOT" in vars(m)]
check(f"ROOT is held by many lanes ({len(_root_holders)}), which is exactly why the "
      "proxy writes to all of them", len(_root_holders) >= 10)

# The other side of that fence: a satellite's own ROOT must NOT move, because it never
# did. bridge/voice.py is the live example.
import bridge.voice as _sat                                       # noqa: E402
_sat_saved, _sentinel = _sat.ROOT, Path("/tmp/facade-fence-sentinel")
A.ROOT = _sentinel
check("a satellite module's own ROOT is NOT rebound by the facade — pre-split "
      "`A.ROOT = tmp` did not reach bridge/voice.py either, and the satellites resolve "
      "their own paths on purpose", _sat.ROOT == _sat_saved)
A.ROOT = ROOT
check("…and ROOT is back to the real repo root afterwards", A.ROOT == ROOT)

# ── 3. dependency direction ──────────────────────────────────────────────────
print("\n── 3. the layering holds ──")


def imports_of(f):
    """Relative imports of sibling/parent modules, as (pkg, module) pairs."""
    out = []
    for n in ast.parse(SRC[f]).body:
        if isinstance(n, ast.ImportFrom) and n.level and n.module:
            here = f.split("/")[0] if "/" in f else ""
            pkg = here if n.level == 1 else n.module.split(".")[0]
            base = n.module if n.level == 1 else n.module.split(".", 1)[-1]
            out.append((pkg, base))
    return out


core_to_router = [(f, m) for f in LANES if f.startswith("core/")
                  for pkg, m in imports_of(f) if pkg == "routers"]
check("no core module imports a router (core is the bottom of the stack)",
      not core_to_router)
if core_to_router:
    print("       offenders:", core_to_router)

imports_app = [f for f in LANES
               if re.search(r"^from \.\.?app import|^from bridge\.app import|"
                            r"^import bridge\.app", SRC[f], re.M)]
check("no lane imports bridge.app (it is the facade OVER them; an import would be a "
      "cycle and would also give the lane a second FastAPI instance)", not imports_app)

graph = {f.split("/")[1][:-3]: {m for pkg, m in imports_of(f) if pkg == "routers"}
         for f in LANES if f.startswith("routers/")}


def find_cycle(node, stack):
    for d in graph.get(node, ()):
        if d in stack:
            return stack[stack.index(d):] + [d]
        c = find_cycle(d, stack + [d])
        if c:
            return c
    return None


cycles = [c for c in (find_cycle(n, [n]) for n in graph) if c]
check("the router import graph is acyclic", not cycles)
if cycles:
    print("       cycle:", cycles[0])

# ── 4. no file is a monolith again ───────────────────────────────────────────
print("\n── 4. the app layer stays modular ──")
CEILING = 1500
oversize = {f: len(SRC[f].splitlines()) for f in appsrc.FILES
            if len(SRC[f].splitlines()) > CEILING}
check(f"every app-layer file is under {CEILING} lines (largest: "
      f"{max(appsrc.FILES, key=lambda f: len(SRC[f].splitlines()))} at "
      f"{max(len(SRC[f].splitlines()) for f in appsrc.FILES)})", not oversize)
if oversize:
    print("       oversize:", oversize)
check("app.py itself stays a facade, not a lane (it holds the /assets mount, the lane "
      "list and the proxy — nothing else)", len(SRC["app.py"].splitlines()) < 400)

# ── 5. the route table is registered in lane order ───────────────────────────
# Import order alone does NOT give this: a lane that imports another lane drags it in
# early, which is why app.py sorts the tail back. Without the sort the ROUTE SET is
# still right, so nothing else in the suite would notice — only /openapi.json and /docs
# would quietly reorder.
print("\n── 5. route order follows the lane order, not the import order ──")
_rank = {n: i for i, n in enumerate(
    m[:-3].replace("/", ".") for m in appsrc.FILES if m != "app.py")}
seq, last, bad = [], -1, []
for r in A.app.routes:
    mod = getattr(getattr(r, "endpoint", None), "__module__", "") or ""
    k = _rank.get(mod.split(".", 1)[-1])
    if k is None:
        continue
    seq.append(k)
    if k < last:
        bad.append((mod, k, last))
    last = k
check(f"the {len(seq)} lane-owned routes are in non-decreasing lane order", not bad)
if bad:
    print("       out of order:", bad[:5])
check("…and there really are the routes this motdeck serves (141 at the split)",
      len(A.app.routes) >= 140)
_hint_errors = []
for _route in A.app.routes:
    _endpoint = getattr(_route, "endpoint", None)
    if _endpoint is None:
        continue
    try:
        typing.get_type_hints(_endpoint)
    except Exception as _e:                                      # noqa: BLE001
        _hint_errors.append(f"{getattr(_route, 'path', '?')}: {_e}")
check("every APIRoute endpoint's postponed annotations resolve after lane extraction",
      not _hint_errors)
if _hint_errors:
    print("       unresolved annotations:", _hint_errors[:5])

# ── 5b. extracted owners remain the one public truth ───────────────────────
print("\n── 5b. extracted owners remain the one public truth ──")
import bridge.routers.component_lifecycle as _lifecycle             # noqa: E402
import bridge.routers.components as _components                     # noqa: E402
import bridge.routers.model_visibility as _visibility               # noqa: E402
import bridge.routers.models as _models                              # noqa: E402

check("components.stop remains callable for historic imports through a lazy forwarder",
      "from .component_lifecycle import stop as _owner" in SRC["routers/components.py"]
      and callable(_components.stop))
check("bridge.app.stop resolves the lifecycle owner rather than the compatibility wrapper",
      A.stop is _lifecycle.stop)
check("models._is_hidden is the exact visibility implementation it re-exports",
      _models._is_hidden is _visibility._is_hidden)
check("the Models hide route is declared exactly once, by the visibility owner",
      appsrc.APP_SOURCE.count('@app.post("/api/models/hide")') == 1
      and '@app.post("/api/models/hide")' in SRC["routers/model_visibility.py"])
for _added in ("routers/component_lifecycle.py", "routers/model_visibility.py"):
    check(f"{_added} is in both source and route-order manifests",
          _added in appsrc.FILES
          and _added[:-3].replace("/", ".") in A._LANES)

# ── 6. the ops path ships the lanes ──────────────────────────────────────────
# ⚠️ THE HIGHEST-CONSEQUENCE CHECK IN THIS FILE, AND THE ONE MOST LIKELY TO ROT.
# The fat app serves a SNAPSHOT, not the repo, and ship.sh copied `bridge/*.py` — a flat
# glob that had been correct for a year and stopped being correct the moment the routes
# moved into subdirectories. Shipping app.py without them puts a facade with nothing
# behind it into the snapshot: the bridge does not import, and the whole panel is dead
# until someone reads a traceback. Nothing else in the suite touches ship.sh's copy
# step, so nothing else would catch its removal.
print("\n── 6. ship.sh puts the lanes in the snapshot ──")
_ship = (ROOT / "scripts" / "ship.sh").read_text()
for _pkg in ("core", "routers"):
    check(f"ship.sh copies bridge/{_pkg}/",
          re.search(rf'bridge/\$_pkg"?/\*\.py|bridge/{_pkg}/\*\.py', _ship) is not None
          and _pkg in _ship)
check("…and it creates the destination directory first (a fresh snapshot has neither)",
      'mkdir -p "$DST/bridge/$_pkg"' in _ship)
check("the snapshot fingerprint ship.sh prints covers the whole app layer, not app.py "
      "alone — over a facade that a normal slice never edits, an app.py-only hash "
      "answers 'yes, your code landed' to every ship",
      "routers/*.py" in _ship and "snapshot app layer" in _ship)

print(f"\n{PASS} passed, {len(FAILS)} failed")
for f in FAILS:
    print("  FAILED:", f)
sys.exit(1 if FAILS else 0)
