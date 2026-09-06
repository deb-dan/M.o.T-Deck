#!/usr/bin/env python3
"""THE REGRESSION FENCE for "installed on disk, 'Not installed' on the card".

The bug (2026-08-21): scripts/install_opencode.sh downloaded, verified and ran the
binary, printed `[opencode] installed: opencode 1.18.19`, and Mission Control still
showed an Install button — because the card does not look at the disk:

    bridge/app.py::status()  ->  "installed": bool(comp.get("installed"))

install_component.sh has flipped `components.<name>.installed` in its own tail since
M0. The STANDALONE installers (opencode, searxng) never learned to, and ship.sh's
manifest merge is additive-only, so nothing downstream would ever fix it.

The rule this file enforces, derived rather than listed: every scripts/install_<x>.sh
whose <x> IS a component in motdeck.yaml must flip that component's flag. Installers
for things that are not components (install_music.sh — the music lane has its own
disk-probe status endpoint; install_aider.sh — a lane, not a card; install_mlx.sh,
install_llamacpp.sh — runtimes) are exempt BY CONSTRUCTION, with no exemption list to
go stale.

Run: data/bridge-venv/bin/python -m pytest bridge/tests/test_installed_flip.py -q
"""
import glob
import os
import re
import subprocess
import sys
import tempfile

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

# ⚠️ THE APP LAYER IS NO LONGER ONE FILE (router/core split, 2026-08-28).
# bridge/app.py is a FACADE over bridge/core/*.py + bridge/routers/*.py, so the
# source-text assertions below read bridge/appsrc.py's assembled view of the whole
# app layer instead of one file. Read bridge/appsrc.py's header for why the
# assertions are source-text in the first place and why order is part of it.
from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402

SCRIPTS = os.path.join(ROOT, "scripts")
FLIP = os.path.join(SCRIPTS, "flip_installed.py")
MANIFEST_PATH = os.path.join(ROOT, "motdeck.yaml")
MANIFEST = yaml.safe_load(open(MANIFEST_PATH, encoding="utf-8").read())
COMPONENTS = list(MANIFEST["components"])
APP = _APP_SOURCE

_checks = [0]


def ok(cond, msg):
    _checks[0] += 1
    assert cond, msg


def run_flip(*args):
    return subprocess.run([sys.executable, FLIP, *args],
                          capture_output=True, text=True, timeout=30)


# ── 1. the card really is manifest-driven (this is WHY the flip matters) ─────
def test_status_reads_the_manifest_flag_not_the_disk():
    m = re.search(r'"installed": bool\(comp\.get\("installed"\)\)', APP)
    ok(m is not None,
       "bridge/app.py::status no longer reads components.<n>.installed — if it became a "
       "disk probe this whole fence can be retired, but until then it is the contract")
    # …and there is no disk fallback for a generic component card.
    seg = APP[max(0, m.start() - 1500):m.start()]
    ok("os.path.exists" not in seg and "Path(" not in seg.split("for name, comp")[-1],
       "a disk probe appeared beside the manifest read — reconcile this test with it")


# ── 2. every component-shaped installer flips its flag ───────────────────────
def _component_installers():
    """{component: script} derived from the filesystem + the manifest, never listed."""
    out = {}
    for path in sorted(glob.glob(os.path.join(SCRIPTS, "install_*.sh"))):
        stem = os.path.basename(path)[len("install_"):-len(".sh")]
        if stem in COMPONENTS:
            out[stem] = path
    return out


def test_every_standalone_component_installer_flips():
    found = _component_installers()
    ok(found, "no component-shaped installers found — the glob or the manifest changed")
    for name, path in found.items():
        src = open(path, encoding="utf-8", errors="replace").read()
        ok("flip_installed.py" in src,
           f"scripts/install_{name}.sh installs a COMPONENT but never sets "
           f"components.{name}.installed — its Mission Control card will say "
           f"'Not installed' forever (the OpenCode bug)")
        ok(re.search(rf"flip_installed\.py\"?\s+{name}\b", src),
           f"install_{name}.sh calls flip_installed.py for the wrong component name")
        # It must not be silent when the flip fails: a card that lies is the bug.
        ok("ERROR" in src.split("flip_installed.py")[1][:600],
           f"install_{name}.sh ignores a failed flip — it must say so loudly")


def test_the_generic_installer_still_flips():
    src = open(os.path.join(SCRIPTS, "install_component.sh"),
               encoding="utf-8", errors="replace").read()
    ok("flip_installed.py" in src, "install_component.sh lost its flip")
    ok(re.search(r'flip_installed\.py"?\s+"\$NAME"', src),
       "install_component.sh must flip the component it just installed")
    # ONE implementation: the old inline regex must be gone, not living beside it.
    ok("installed: )false" not in src,
       "install_component.sh still carries its own private copy of the flip — two "
       "writers of the same key is the drift class this project keeps getting bitten by")


def test_every_installable_component_has_an_installer_that_flips():
    """The bridge's install allowlist is the set of cards with an Install button; each
    one must reach a script that flips."""
    m = re.search(r"def install\(name: str\).*?if name not in \(([^)]*)\)", APP, re.S)
    ok(m is not None, "the /api/components/{name}/install allowlist moved")
    allow = re.findall(r'"([a-z0-9_-]+)"', m.group(1))
    ok(allow, "the allowlist parsed empty")
    standalone = _component_installers()
    for name in allow:
        ok(name in COMPONENTS, f"{name} is installable but is not in motdeck.yaml")
        if name in standalone:
            continue                       # covered above
        # …otherwise it must be a branch of install_component.sh, whose tail flips.
        gen = open(os.path.join(SCRIPTS, "install_component.sh"),
                   encoding="utf-8", errors="replace").read()
        ok(re.search(re.escape(name) + r"[|)]", gen),
           f"{name} has neither its own installer nor a branch in install_component.sh")


# ── 3. the writer itself, EXECUTED against a real manifest copy ──────────────
def test_flip_runs_on_a_copy_of_the_real_manifest():
    src = open(MANIFEST_PATH, encoding="utf-8").read()
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "motdeck.yaml")
        open(p, "w", encoding="utf-8").write(src)
        for name, comp in MANIFEST["components"].items():
            r = run_flip(name, p)
            ok(r.returncode == 0, f"flip {name} exited {r.returncode}: {r.stderr}")
            if not comp.get("installed"):
                ok("-> true" in r.stdout, f"flip {name} did not report a change")
        after = yaml.safe_load(open(p, encoding="utf-8").read())
        for name in COMPONENTS:
            ok(after["components"][name]["installed"] is True,
               f"{name} is still not installed after the flip")

        # IDEMPOTENT, and a no-op write is really a no-op.
        before = open(p, encoding="utf-8").read()
        r = run_flip(COMPONENTS[0], p)
        ok(r.returncode == 0 and "already true" in r.stdout, "a second flip must no-op")
        ok(open(p, encoding="utf-8").read() == before, "the no-op path rewrote the file")

        # NO YAML REFLOW. Same line count, and every line but the flipped ones is
        # byte-identical — comments, ordering and EMPTY SCALARS survive. (yaml.safe_dump
        # writes an empty key as the literal `null`, which the shell readers take as a
        # path; that incident broke every model load on 2026-08-07.)
        a, b = src.splitlines(), open(p, encoding="utf-8").read().splitlines()
        ok(len(a) == len(b), "the flip changed the line count — it reflowed the file")
        changed = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        ok(all("installed:" in a[i] for i in changed),
           f"the flip touched lines that are not `installed:`: "
           f"{[a[i] for i in changed if 'installed:' not in a[i]][:3]}")
        # trailing comments on the flipped line survive
        for i in changed:
            if "#" in a[i]:
                ok(a[i].split("#", 1)[1] == b[i].split("#", 1)[1],
                   "a trailing comment was lost on the flipped line")


def test_flip_is_loud_when_it_cannot_work():
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "motdeck.yaml")
        open(p, "w", encoding="utf-8").write(
            "components:\n  alpha:\n    port: 1\n  beta:\n    installed: false\n")
        r = run_flip("nosuch", p)
        ok(r.returncode == 1 and "not in" in r.stderr, "an unknown component must fail 1")
        r = run_flip("alpha", p)
        ok(r.returncode == 1 and "installed:" in r.stderr,
           "a component with no `installed:` key must fail 1, not silently pass")
        ok(open(p, encoding="utf-8").read().count("installed:") == 1,
           "a failing flip must not write anything")
        # …and the neighbour still flips (the block scan stops at the sibling key).
        r = run_flip("beta", p)
        ok(r.returncode == 0, "beta must flip")
        ok("beta:\n    installed: true" in open(p, encoding="utf-8").read(),
           "beta's own key was not the one written")
        ok("alpha:\n    port: 1" in open(p, encoding="utf-8").read(),
           "the flip leaked into the previous block")


def test_flip_never_round_trips_yaml():
    """Asserted over the AST, not the text: the file NAMES safe_dump in its own comment
    explaining why it does not use it, and a grep cannot tell those apart."""
    import ast

    src = open(FLIP, encoding="utf-8").read()
    called = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                called.add(f.attr)
            elif isinstance(f, ast.Name):
                called.add(f.id)
    for bad in ("safe_dump", "dump", "dump_all"):
        ok(bad not in called,
           f"flip_installed.py CALLS {bad} — a yaml round-trip writes an empty key as "
           f"`null`, which the shell readers take as a real path (2026-08-07 incident)")
    shared = open(os.path.join(ROOT, "bridge", "yamlfile.py"), encoding="utf-8").read()
    ok("transform_file" in called and "os.replace" in shared,
       "the flip must use the shared atomic transaction writer (os.replace)")


def test_flip_defaults_to_its_own_root():
    """$ROOT is the install that is RUNNING: the snapshot when the bridge spawns the
    installer from ~/Library/Application Support/MOT Deck, the repo when run there."""
    src = open(FLIP, encoding="utf-8").read()
    ok("os.path.dirname(os.path.abspath(__file__))" in src and "os.pardir" in src,
       "the default manifest is no longer resolved relative to the script itself")


# ── 4. the whole card lifecycle, through the real app ────────────────────────
def test_card_lifecycle_live():
    """Prove the fix end to end: a manifest whose flag is false shows installed=false,
    the flip makes /api/status say true, and start-plan stops refusing. Driven against
    a TEMP ROOT so nothing real is touched."""
    try:
        from fastapi.testclient import TestClient
    except Exception as e:                                        # noqa: BLE001
        print(f"  (skipped live lifecycle test — no TestClient: {e})")
        return
    import warnings
    warnings.filterwarnings("ignore")
    from pathlib import Path

    from bridge import app as A

    client = TestClient(A.app)
    with tempfile.TemporaryDirectory() as td:
        # A minimal manifest with a component on a port nothing holds — found by
        # binding port 0, NOT hardcoded 4096: on the dev Mac the real OpenCode is
        # live on 4096 and `running` would honestly read True there
        import socket
        with socket.socket() as _s:
            _s.bind(("127.0.0.1", 0))
            free_port = _s.getsockname()[1]
        open(os.path.join(td, "motdeck.yaml"), "w", encoding="utf-8").write(
            "components:\n"
            "  opencode:\n"
            "    pin: \"1.18.19\"\n"
            "    installed: false          # OPTIONAL\n"
            "    enabled: false\n"
            f"    port: {free_port}\n"
            "    depends_on: []\n")
        os.makedirs(os.path.join(td, "data"), exist_ok=True)
        old = A.ROOT
        A.ROOT = Path(td)
        try:
            r = client.get("/api/status")
            ok(r.status_code == 200, "GET /api/status is 200")
            comp = r.json()["components"]["opencode"]
            ok(comp["installed"] is False,
               "a false flag must read as NOT installed (this is the bug's surface)")

            # The installer's flip, run exactly as install_opencode.sh runs it.
            r2 = run_flip("opencode", os.path.join(td, "motdeck.yaml"))
            ok(r2.returncode == 0, f"the flip failed: {r2.stderr}")

            comp = client.get("/api/status").json()["components"]["opencode"]
            ok(comp["installed"] is True,
               "after the flip the card must read installed — THE FIX")
            ok(comp["running"] is False, "nothing is listening on the free test port")
            ok(comp["port"] == free_port, "the card carries the manifest port")

            # …and the Start path renders a plan (the card's other half).
            r3 = client.get("/api/components/opencode/start-plan")
            ok(r3.status_code == 200, "GET the opencode start-plan is 200")
            body = r3.json()
            ok(body["target"] == "opencode", "the plan names the component")
            ok(body["to_start"] == ["opencode"],
               "with nothing running and no deps, the plan starts exactly opencode")

            # And the Install button is still offered by the bridge for this name —
            # the flip changes the CARD's state, never the allowlist.
            r4 = client.get("/api/components/opencode/plan")
            ok(r4.status_code == 200, "the install plan is still reachable")
        finally:
            A.ROOT = old


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    print(f"installed-flip fence OK — {_checks[0]} checks")
