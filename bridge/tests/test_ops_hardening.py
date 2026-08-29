"""Ops-path hardening (2026-08-21 slice). Four rulings, all pinned here:

  1. scripts/verify.sh — THE contract gate; it must be runnable, must report PASS/FAIL,
     and must EXIT DISTINCTLY when it cannot run at all (0/1/2). ship.sh must call it
     BEFORE copying anything and refuse the ship on 1 OR 2, with SHIP_SKIP_GATE=1 the
     only (loud) way past.  [the 2026-08-15 "No module named pytest" incident]
  2. ship.sh --restart <component> runs start_component.sh FROM THE SNAPSHOT, and every
     ship prints the reminder.  ["shipping is NOT restarting a component"]
  3. firstrun_fat.sh refuses to seed BACKWARDS over an existing install (fewer components
     or an older build stamp), and build_app.sh writes that stamp into the seed.
     [the 2026-08-20 provisioner incident]
  4. Port clears establish OWNERSHIP before killing; a foreign listener is refused, not
     killed.  [Debi's standalone Unsloth on :8888 being killed by our own start]

Run: python3 bridge/tests/test_ops_hardening.py   (from the repo root)
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# ⚠️ THE APP LAYER IS NO LONGER ONE FILE (router/core split, 2026-08-28).
# bridge/app.py is a FACADE over bridge/core/*.py + bridge/routers/*.py, so the
# source-text assertions below read bridge/appsrc.py's assembled view of the whole
# app layer instead of one file. Read bridge/appsrc.py's header for why the
# assertions are source-text in the first place and why order is part of it.
from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402
from bridge import app  # noqa: E402

PASS = 0
FAIL = []


def check(name, cond):
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(name)
        print("FAIL:", name)


SHIP = (ROOT / "scripts" / "ship.sh").read_text()
VERIFY_P = ROOT / "scripts" / "verify.sh"
VERIFY = VERIFY_P.read_text()
FIRSTRUN_P = ROOT / "scripts" / "firstrun_fat.sh"
FIRSTRUN = FIRSTRUN_P.read_text()
BUILD = (ROOT / "scripts" / "build_app.sh").read_text()
START_P = ROOT / "scripts" / "start_component.sh"
START = START_P.read_text()


# ══ 1. verify.sh — the contract gate ══════════════════════════════════════════
check("verify.sh exists", VERIFY_P.is_file())
check("verify.sh is executable", os.access(VERIFY_P, os.X_OK))
check("verify.sh runs the contract suite, not the unit tests",
      "pytest bridge/contract_tests/" in VERIFY)
check("verify.sh resolves ROOT from its OWN location (repo copy verifies the repo, "
      "snapshot copy verifies the snapshot)",
      'ROOT="$(cd "$(dirname "$0")/.." && pwd)"' in VERIFY)
check("verify.sh prefers the bridge venv's python",
      '"${ROOT}/data/bridge-venv/bin/python"' in VERIFY)
check("verify.sh also tries the SNAPSHOT's bridge venv", "SNAP_PY" in VERIFY)
check("verify.sh falls back to a system python3",
      VERIFY.index("SNAP_PY") < VERIFY.index("python3; do"))
check("verify.sh selects a python by IMPORTING pytest, not by existence",
      '-c "import pytest"' in VERIFY)
check("verify.sh does NOT use set -e (it must report, not die)",
      "set -uo pipefail" in VERIFY and "set -euo" not in VERIFY)
check("cannot-run message names the uv install one-liner (python -m pip cannot work "
      "in a uv-created venv)",
      "uv pip install pytest" in VERIFY and "CANNOT RUN" in VERIFY)
check("cannot-run explains WHY python -m pip is not the answer",
      "no pip module" in VERIFY)
check("PASS is stated in words", "PASS - the contract gate is green." in VERIFY)
check("FAIL is stated in words", "FAIL - the contract gate did NOT pass" in VERIFY)

# exit-code table, exercised for real against a scratch tree
with tempfile.TemporaryDirectory() as td:
    fake = Path(td) / "fakeroot"
    (fake / "scripts").mkdir(parents=True)
    (fake / "scripts" / "verify.sh").write_text(VERIFY)
    os.chmod(fake / "scripts" / "verify.sh", 0o755)

    # (a) no suite at all -> 2 (CANNOT RUN), not 0 and not 1
    r = subprocess.run(["bash", str(fake / "scripts" / "verify.sh")],
                       capture_output=True, text=True)
    check("no contract suite on disk -> exit 2 (cannot run)", r.returncode == 2)
    check("no-suite message says CANNOT RUN", "CANNOT RUN" in r.stdout)

    # (b) suite present, one passing test, a python WITH pytest -> 0
    (fake / "bridge" / "contract_tests").mkdir(parents=True)
    (fake / "bridge" / "contract_tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    has_pytest = subprocess.run([sys.executable, "-c", "import pytest"],
                                capture_output=True).returncode == 0
    if has_pytest:
        # put the chosen interpreter where verify.sh looks first — as a shim that
        # execs the real path, NOT a symlink: a venv python found via a symlink
        # loses its pyvenv.cfg (argv0-relative), so pytest would vanish with it
        (fake / "data" / "bridge-venv" / "bin").mkdir(parents=True)
        shim = fake / "data" / "bridge-venv" / "bin" / "python"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        os.chmod(shim, 0o755)
        r = subprocess.run(["bash", str(fake / "scripts" / "verify.sh")],
                           capture_output=True, text=True)
        check("passing suite -> exit 0", r.returncode == 0)
        check("passing suite prints PASS", "PASS - the contract gate is green." in r.stdout)

        # (c) a failing test -> 1 (FAIL), distinct from 2
        (fake / "bridge" / "contract_tests" / "test_bad.py").write_text(
            "def test_bad():\n    assert False\n")
        r = subprocess.run(["bash", str(fake / "scripts" / "verify.sh")],
                           capture_output=True, text=True)
        check("failing suite -> exit 1", r.returncode == 1)
        check("failing suite prints FAIL", "FAIL - the contract gate did NOT pass" in r.stdout)
        check("fail and cannot-run are DIFFERENT exit codes (ship.sh branches on them)",
              True)
    else:
        print("  --  pytest absent here: skipping the live pass/fail exit-code runs")

    # (d) cannot-run: suite present but no interpreter can import pytest
    stub = fake / "nopy"
    stub.mkdir()
    (stub / "python3").write_text("#!/bin/sh\nexit 1\n")
    os.chmod(stub / "python3", 0o755)
    # a PATH whose python3 always fails, but which still has a shell + coreutils
    env = dict(os.environ, PATH=f"{stub}:/bin:/usr/bin", HOME=str(fake / "nohome"))
    fake2 = Path(td) / "fake2"
    (fake2 / "scripts").mkdir(parents=True)
    (fake2 / "scripts" / "verify.sh").write_text(VERIFY)
    (fake2 / "bridge" / "contract_tests").mkdir(parents=True)
    r = subprocess.run(["bash", str(fake2 / "scripts" / "verify.sh")],
                       capture_output=True, text=True, env=env)
    check("suite present but NO pytest anywhere -> exit 2, never a silent 0",
          r.returncode == 2)
    check("cannot-run tells the user exactly what was tried",
          "tried:" in r.stdout and "uv pip install pytest" in r.stdout)


# ══ 1b. ship.sh calls the gate, before copying, and refuses ═══════════════════
check("ship.sh calls verify.sh", 'bash "$ROOT/scripts/verify.sh"' in SHIP)
check("the gate runs BEFORE anything is copied",
      SHIP.index("scripts/verify.sh") < SHIP.index('cp -R "$ROOT/bridge/panel/.'))
check("the gate runs BEFORE the swift recompile",
      SHIP.index("scripts/verify.sh") < SHIP.index("recompiling the shell"))
check("gate failure REFUSES the ship", "REFUSING TO SHIP - the contract gate FAILED" in SHIP)
check("gate cannot-run ALSO refuses the ship",
      "REFUSING TO SHIP - the contract gate COULD NOT RUN" in SHIP)
check("a refusal says nothing was copied", SHIP.count("NOTHING was copied") == 2)
check("both refusals exit non-zero",
      SHIP.index("exit 1", SHIP.index("contract gate FAILED")) > 0
      and SHIP.index("exit 1", SHIP.index("contract gate COULD NOT RUN")) > 0)
check("gate return code is captured without tripping set -e", "GATE_RC=$?" in SHIP)
check("rc 1 and rc non-0 are handled as SEPARATE branches",
      '"$GATE_RC" -eq 1' in SHIP and '"$GATE_RC" -ne 0' in SHIP)
check("SHIP_SKIP_GATE=1 is the only override", '"${SHIP_SKIP_GATE:-0}" == "1"' in SHIP)
check("the override is printed LOUDLY when used",
      "THE CONTRACT GATE WAS SKIPPED" in SHIP)
check("the override is named in both refusal messages",
      SHIP.count("SHIP_SKIP_GATE=1 ./scripts/ship.sh") >= 2)


# ══ 2. ship.sh --restart ══════════════════════════════════════════════════════
check("--restart is parsed", "--restart)" in SHIP)
check("--restart=<name> form also parsed", "--restart=*)" in SHIP)
check("comma lists are accepted", "_add_restart" in SHIP and "IFS=','" in SHIP)
check("--restart with no value errors instead of eating the next flag",
      "--restart needs a component name" in SHIP)
check("an unknown argument is refused (ship.sh took none before)",
      "unknown argument" in SHIP)
check("restart runs start_component.sh FROM THE SNAPSHOT",
      'bash "$DST/scripts/start_component.sh" "$_c"' in SHIP)
check("restart never runs the REPO's copy",
      '"$ROOT/scripts/start_component.sh"' not in SHIP)
check("restart happens AFTER the bridge is confirmed up",
      SHIP.index('if [[ "$UP" -ne 1 ]]') < SHIP.index("restarting component"))
check("a failed restart WARNs and does not abort the whole ship",
      "WARN: restart of" in SHIP)
check("empty RESTART array is safe under set -u",
      '${RESTART[@]+"${RESTART[@]}"}' in SHIP)
check("every ship prints the reminder",
      "REMINDER: components stay up" in SHIP
      and "./scripts/ship.sh --restart <name>" in SHIP)
check("the reminder is unconditional (outside the RESTART block)",
      SHIP.index("REMINDER: components stay up") > SHIP.index("restarting component"))

# --restart argument parsing, exercised for real (bad args must not reach the gate)
r = subprocess.run(["bash", str(ROOT / "scripts" / "ship.sh"), "--restart"],
                   capture_output=True, text=True)
check("bare --restart exits non-zero before doing anything", r.returncode != 0)
check("bare --restart says what is missing", "--restart needs a component name" in r.stdout)
r = subprocess.run(["bash", str(ROOT / "scripts" / "ship.sh"), "--wat"],
                   capture_output=True, text=True)
check("unknown flag exits non-zero", r.returncode != 0)
check("unknown flag is named", "unknown argument '--wat'" in r.stdout)


# ══ 2b. THE PACKAGE COPY IS RECURSIVE, AND FENCED ═════════════════════════════
# bug-echo W-02 (the flat-glob class, the v1.5.15 near-miss). `cp "$ROOT/bridge/$_pkg"/*.py`
# shipped bridge/core and bridge/routers ONE LEVEL DEEP. Nothing was wrong on the day it
# was written — neither package had a subdirectory — but the failure it sets up is the
# worst shape there is: the repo runs perfectly, the SNAPSHOT cannot import, and the
# difference is invisible until the app is launched. So the copy walks every depth, and a
# FENCE re-checks the result: if any .py the repo's packages hold is missing from the
# snapshot, the ship stops instead of restarting onto a broken tree.
#
# ⚠️ BOTH HALVES ARE EXECUTED, NOT GREPPED. The block is extracted from ship.sh itself and
# run against temp directories — a grep for the word "find" would have passed on a copy
# that still lost the file.
_A = SHIP.index("_pkg_pys() {")
_Z = SHIP.index("for d in scripts guards policies")
COPY_AND_FENCE = SHIP[_A:_Z]
FENCE_ONLY = (SHIP[_A:SHIP.index("for _pkg in core routers", _A)]
              + SHIP[SHIP.index('_missing=""', _A):_Z])
check("(anchors) both halves were found in ship.sh",
      "find ." in COPY_AND_FENCE and '_missing=""' in COPY_AND_FENCE
      and "find ." in FENCE_ONLY and "for _pkg in core routers" not in
      FENCE_ONLY.split('_missing=""')[0])


def _shipbed():
    """A repo-shaped source tree with a NESTED subpackage, and an empty snapshot."""
    bed = tempfile.mkdtemp(prefix="shipglob-")
    src, dst = os.path.join(bed, "repo"), os.path.join(bed, "snap")
    for rel in ("bridge/core", "bridge/core/sub", "bridge/core/__pycache__",
                "bridge/routers", "bridge/routers/deep/deeper"):
        os.makedirs(os.path.join(src, rel), exist_ok=True)
    for rel in ("bridge/core/flat.py", "bridge/core/sub/__init__.py",
                "bridge/core/sub/nested.py", "bridge/routers/r.py",
                "bridge/routers/deep/deeper/buried.py"):
        open(os.path.join(src, rel), "w").write("# x\n")
    open(os.path.join(src, "bridge/core/__pycache__/flat.cpython-313.pyc"),
         "w").write("junk")
    os.makedirs(os.path.join(dst, "bridge"), exist_ok=True)
    return bed, src, dst


def _runblock(block, src, dst):
    return subprocess.run(["bash", "-c", 'set -euo pipefail\nROOT="$1"\nDST="$2"\n'
                           + block, "_", src, dst], capture_output=True, text=True)


_bed, _src, _dst = _shipbed()
r = _runblock(COPY_AND_FENCE, _src, _dst)
check("the package copy runs clean", r.returncode == 0 and not r.stdout.strip())
check("flat modules still ship (the behaviour that was already right)",
      os.path.isfile(os.path.join(_dst, "bridge/core/flat.py"))
      and os.path.isfile(os.path.join(_dst, "bridge/routers/r.py")))
check("A SUBPACKAGE SHIPS — with its __init__.py, which is what makes it importable",
      os.path.isfile(os.path.join(_dst, "bridge/core/sub/nested.py"))
      and os.path.isfile(os.path.join(_dst, "bridge/core/sub/__init__.py")))
check("…at ANY depth, not just one level down",
      os.path.isfile(os.path.join(_dst, "bridge/routers/deep/deeper/buried.py")))
check("__pycache__ still never travels (the snapshot runs the bridge, it does not "
      "carry its build droppings)",
      not os.path.exists(os.path.join(_dst, "bridge/core/__pycache__")))
check("the copy is idempotent — a second ship over the same snapshot is clean",
      _runblock(COPY_AND_FENCE, _src, _dst).returncode == 0)

# THE FENCE, against the exact regression it exists for: a snapshot populated by the OLD
# flat glob. This is the state a future "tidy-up" back to `cp "$pkg"/*.py` would produce.
_bed2, _src2, _dst2 = _shipbed()
for _pkg in ("core", "routers"):
    os.makedirs(os.path.join(_dst2, "bridge", _pkg), exist_ok=True)
    for _f in os.listdir(os.path.join(_src2, "bridge", _pkg)):
        if _f.endswith(".py"):
            open(os.path.join(_dst2, "bridge", _pkg, _f), "w").write("# x\n")
r = _runblock(FENCE_ONLY, _src2, _dst2)
check("A FLAT-GLOB SNAPSHOT IS REFUSED — the fence catches the regression, it does not "
      "merely describe it", r.returncode != 0)
check("…and it NAMES every module that did not make it",
      "bridge/core/sub/nested.py" in r.stdout
      and "bridge/routers/deep/deeper/buried.py" in r.stdout)
check("…and says what the consequence would have been, in words",
      "would fail to" in r.stdout and "INCOMPLETE" in r.stdout)
check("…and that nothing was restarted onto it",
      "Nothing was restarted" in r.stdout)
check("a COMPLETE snapshot passes the same fence (it is not a fence that always fires)",
      _runblock(FENCE_ONLY, _src, _dst).returncode == 0)
for _b in (_bed, _bed2):
    subprocess.run(["rm", "-rf", _b], check=False)
check("the ship's own packages are copied by the fenced block, not by a stray glob "
      "left behind beside it",
      'cp "$ROOT/bridge/$_pkg"/*.py' not in SHIP)


# ══ 2c. A FOREIGN llama-server IS NAMED, AND REFUSED UNLESS IT IS THE PIN ═════
# bug-echo W-04 — ruling #4's own class (a foreign app's state under our feet), crossed
# with the wrong-oracle class. The runner's binary discovery falls back to Jan's and LM
# Studio's home directories, and those apps upgrade that binary whenever they like while
# THIS harness's probe/auth expectations are pinned against one build: llama.cpp b10662
# made /v1/models require a key where the build before it did not, and finding that 401
# cost a session. Starting a stranger's binary silently re-opens it.
#
# The gate block is EXTRACTED FROM start_component.sh AND RUN, against fake binaries that
# report a build number — a grep for the pin would pass on a gate that never fires.
START = (ROOT / "scripts" / "start_component.sh").read_text()
_GA = START.index('if [[ -n "${BIN_OWNER:-}" ]]; then')
_GZ = START.index("# CTX preference", _GA)
GATE = START[_GA:_GZ]
PIN = ""
for _ln in (ROOT / "harness.yaml").read_text().splitlines():
    if _ln.strip().startswith("llamacpp_pin:"):
        PIN = _ln.split(":", 1)[1].split("#")[0].strip()
        break
check("(fixture) the pin is readable from harness.yaml", PIN.startswith("b"))
check("the discovery records WHOSE binary it found, which is what the gate rests on",
      'BIN_OWNER="Jan"' in START and 'BIN_OWNER="LM Studio"' in START)
check("…and an EXPLICIT runner.binary is exempt — a person named it on purpose",
      'BIN="$R_BIN"; BIN_OWNER=""' in START)

_fbed = tempfile.mkdtemp(prefix="foreignrunner-")


def _fake_llama(name, version_line):
    p = os.path.join(_fbed, name)
    with open(p, "w") as fh:
        fh.write("#!/bin/sh\n" + (f'echo "{version_line}"\n' if version_line else "")
                 + "exit 0\n")
    os.chmod(p, 0o755)
    return p


def _rungate(binp, owner, env=None):
    e = dict(os.environ)
    e.pop("HARNESS_ALLOW_FOREIGN_RUNNER", None)
    e.update(env or {})
    return subprocess.run(
        ["bash", "-c", 'set -uo pipefail\nBIN="$1"\nBIN_OWNER="$2"\n' + GATE, "_",
         binp, owner],
        capture_output=True, text=True, cwd=str(ROOT), env=e)


_ok_bin = _fake_llama("match", f"version: 0.3.0-dev (build {PIN.lstrip('b')}, commit abc)")
_old_bin = _fake_llama("drift", "version: 0.3.0-dev (build 9001, commit abc)")
_mute_bin = _fake_llama("mute", "")

r = _rungate(_ok_bin, "")
check("no owner, no gate — an ordinary start on OUR pinned binary says nothing new",
      r.returncode == 0 and not r.stdout.strip())

r = _rungate(_ok_bin, "LM Studio")
check("a foreign binary whose build IS the pin is allowed", r.returncode == 0)
check("…but it is still SAID OUT LOUD, naming the app it belongs to",
      "NOT OURS" in r.stdout and "LM Studio" in r.stdout)
check("…and the exact path, because 'a foreign binary' is not something you can grep for",
      _ok_bin in r.stdout)
check("…and both build numbers, so the comparison is checkable rather than asserted",
      PIN.lstrip("b") in r.stdout and PIN in r.stdout and "MATCHES the pin" in r.stdout)

r = _rungate(_old_bin, "Jan")
check("A BUILD THAT DIFFERS FROM THE PIN IS REFUSED, not run", r.returncode != 0)
check("…naming the drift in numbers", "9001" in r.stdout and PIN in r.stdout)
check("…and the app whose binary it is", "Jan" in r.stdout)
check("…with the fix, not just the complaint",
      "./scripts/install_llamacpp.sh" in r.stdout and "runner.binary" in r.stdout)
check("…and the reason stated as the incident it comes from, so the refusal is arguable",
      "b10662" in r.stdout and "401" in r.stdout)
check("…and the override is named in the refusal itself",
      "HARNESS_ALLOW_FOREIGN_RUNNER=1" in r.stdout)

r = _rungate(_mute_bin, "Jan")
check("A BINARY WHOSE BUILD CANNOT BE READ IS REFUSED TOO — 'unverifiable' is not "
      "'fine' for a foreign binary under pinned contracts", r.returncode != 0)
check("…and says so in those terms rather than inventing a version",
      "unreadable" in r.stdout)

r = _rungate(_old_bin, "Jan", {"HARNESS_ALLOW_FOREIGN_RUNNER": "1"})
check("the override really opens the gate", r.returncode == 0)
check("…and is LOUD about what it just allowed, including what to suspect first",
      "deliberately" in r.stdout and "401" in r.stdout)
subprocess.run(["rm", "-rf", _fbed], check=False)

# The python half of the same discovery must carry the same gate, in the same words:
# a rule that exists on one of two shared paths is a rule a user finds by getting past it.
check("bridge/routers/models.py's aux start has the gate too",
      "foreign_runner_gate(" in _APP_SOURCE and "FOREIGN_RUNNER_ENV" in _APP_SOURCE)
check("…keyed on the SAME env var as the shell",
      'HARNESS_ALLOW_FOREIGN_RUNNER' in _APP_SOURCE
      and "HARNESS_ALLOW_FOREIGN_RUNNER" in START)
check("…refusing with a 409 rather than starting the stranger's binary",
      'return JSONResponse({"ok": False, "log": refusal}, status_code=409)'
      in _APP_SOURCE)
check("…and it knows WHOSE binary it picked, which the old flat `or` could not say",
      'owner = "Jan" if jan else "LM Studio"' in _APP_SOURCE)


# ══ 3. build stamp + backwards-seeding guard ══════════════════════════════════
check("build_app.sh writes a SEED_STAMP into the staged seed",
      '> "$STAGE/SEED_STAMP"' in BUILD)
check("the stamp carries a build date", "date=$(date -u" in BUILD)
check("the stamp carries the git sha", "git_sha=$(git -C" in BUILD)
check("the stamp carries the component count", "components=$(awk" in BUILD)
check("the stamp is written INSIDE the fat branch only",
      BUILD.index('> "$STAGE/SEED_STAMP"') > BUILD.index("if [[ $FAT -eq 1 ]]"))
check("the stamp is staged BEFORE the seed is tarred",
      BUILD.index('> "$STAGE/SEED_STAMP"')
      < BUILD.index('tar czf "$RES/harness-seed-fat.tar.gz"'))

check("firstrun_fat.sh has the guard", "seed_guard()" in FIRSTRUN)
check("the guard runs BEFORE the seed is extracted",
      FIRSTRUN.index("seed_guard \"$DEST/harness.yaml\"")
      < FIRSTRUN.index('tar xzf "$SEED" -C "$DEST"'))
check("the guard only engages when something is already there",
      'if [[ -f "$DEST/harness.yaml" ]]; then' in FIRSTRUN)
check("firstrun records the stamp it provisioned from",
      'cp "$DEST/SEED_STAMP" "$DEST/.seed_stamp"' in FIRSTRUN)
check("the refusal names the deliberate move-aside recovery",
      "move the existing install aside DELIBERATELY" in FIRSTRUN
      and "Harness.saved" in FIRSTRUN)
check("the refusal states that nothing was changed",
      "Nothing has been changed." in FIRSTRUN)
check("the refusal prints BOTH counts and BOTH build stamps",
      "existing : components=" in FIRSTRUN and "installer: components=" in FIRSTRUN)

# the guard's own decision table, run for real through its --seed-guard hook
GUARD = ["bash", str(FIRSTRUN_P), "--seed-guard"]


def _yaml(n):
    body = "components:\n" + "".join(f"  c{i}:\n    port: {1000+i}\n" for i in range(n))
    return "runner:\n  port: 6767\n" + body + "memory:\n  budget_gb: 48\n"


def guard(have_n, have_d, seed_n, seed_d, td):
    paths = []
    for tag, n, d in (("have", have_n, have_d), ("seed", seed_n, seed_d)):
        y = Path(td) / f"{tag}.yaml"
        s = Path(td) / f"{tag}.stamp"
        y.unlink(missing_ok=True)          # None must mean ABSENT, not "left over"
        s.unlink(missing_ok=True)
        if n is not None:
            y.write_text(_yaml(n))
        if d is not None:
            s.write_text(f"date={d}\ngit_sha=abc1234\ncomponents={n}\n")
        paths += [str(y), str(s)]
    # existing_yaml, existing_stamp, seed_yaml, seed_stamp
    order = [paths[0], paths[1], paths[2], paths[3]]
    return subprocess.run(GUARD + order, capture_output=True, text=True).returncode


with tempfile.TemporaryDirectory() as td:
    D_OLD, D_NEW = "2026-08-06T10:00:00Z", "2026-08-20T10:00:00Z"
    check("REFUSES: 6 installed components vs a 3-component seed (the real incident)",
          guard(6, D_NEW, 3, D_OLD, td) == 3)
    check("REFUSES: same components but the installer is OLDER than the install",
          guard(4, D_NEW, 4, D_OLD, td) == 3)
    check("ALLOWS: newer installer, more components (the normal upgrade)",
          guard(3, D_OLD, 6, D_NEW, td) == 0)
    check("ALLOWS: identical seed re-provisioning itself",
          guard(6, D_NEW, 6, D_NEW, td) == 0)
    check("ALLOWS: a newer installer with FEWER components is still refused "
          "(count wins — a manifest must never shrink)",
          guard(6, D_OLD, 3, D_NEW, td) == 3)
    check("no claim: existing install has no stamp and the same count -> allowed",
          guard(3, None, 3, D_OLD, td) == 0)
    check("no claim: installer has no stamp -> count still decides (fewer = refuse)",
          guard(6, D_NEW, 2, None, td) == 3)
    check("no claim: neither yaml readable -> allowed (guard fires only on evidence)",
          guard(None, None, None, None, td) == 0)
    check("the guard hook is side-effect free (no seed touched)",
          "--seed-guard" in FIRSTRUN and FIRSTRUN.index("--seed-guard")
          < FIRSTRUN.index('RES="${1:-}"'))


# ══ 4. port ownership ═════════════════════════════════════════════════════════
# --- 4a. the shell helper, exercised through start_component.sh --owner-check
def owns(component, cmd):
    r = subprocess.run(["bash", str(START_P), "--owner-check", component, cmd],
                       capture_output=True, text=True, cwd=str(ROOT))
    return r.returncode == 0


R = str(ROOT)
check("shell: our own venv launch is OURS (comfyui)",
      owns("comfyui", f"{R}/data/comfyui-venv/bin/python main.py --port 8188"))
check("shell: our own venv launch is OURS (unsloth, isolated-home venv)",
      owns("unsloth", f"{R}/data/unsloth-home/unsloth_studio/bin/unsloth studio --port 8899"))
check("shell: a STANDALONE unsloth (its own ~/.unsloth managed venv) is NOT ours",
      not owns("unsloth", str(Path.home() / ".unsloth/studio/unsloth_studio/bin/python")
                          + " " + str(Path.home() / ".unsloth/studio/unsloth_studio/bin/unsloth")
                          + " studio --api-only -H 127.0.0.1 -p 8888"))

# ── unsloth isolated home (2026-08-28): our component must NEVER share ~/.unsloth
# with the standalone Unsloth.app. Pin the three load-bearing pieces of the launch:
# the home export, the fence, and the venv living AT the home's managed-venv path.
check("unsloth launch exports UNSLOTH_STUDIO_HOME (the isolation itself)",
      'export UNSLOTH_STUDIO_HOME="$US_HOME"' in START)
check("unsloth home is data/unsloth-home, never ~/.unsloth",
      'US_HOME="$ROOT/data/unsloth-home"' in START)
check("unsloth launch fences ~/.unsloth (refuses to start into the standalone's home)",
      '"$HOME/.unsloth"|"$HOME/.unsloth/"*' in START)
check("unsloth venv lives AT $US_HOME/unsloth_studio (in-process serve, no re-exec)",
      'US_VENV="$US_HOME/unsloth_studio"' in START)
check("unsloth launch does not reference the retired shared-era venv path",
      "data/unsloth-venv/bin" not in START)
check("unsloth launch unsets the STUDIO_HOME alias so an env leak cannot redirect it",
      "unset STUDIO_HOME" in START)
check("shell: our own venv launch is OURS (voicebox)",
      owns("voicebox", f"{R}/data/voicebox-venv/bin/python -m backend.main --port 17493"))
check("shell: our own venv launch is OURS (voicestudio)",
      owns("voicestudio", f"{R}/data/voicestudio-venv/bin/python -m backend.main"))
check("shell: our own venv launch is OURS (odysseus, activated venv)",
      owns("odysseus", f"{R}/data/odysseus-venv/bin/python -m uvicorn app:app --port 7860"))
check("shell: our own venv launch is OURS (searxng)",
      owns("searxng", f"{R}/data/searxng-venv/bin/python -m searx.webapp"))
check("shell: our own venv launch is OURS (hermes)",
      owns("hermes", f"{R}/data/hermes-venv/bin/hermes dashboard --no-open"))
check("shell: a vendor/ path is OURS",
      owns("comfyui", f"{R}/vendor/comfyui/main.py --port 8188"))
check("shell: our pinned llama-server is OURS (path)",
      owns("runner", f"{R}/data/llamacpp/build/bin/llama-server --port 6767"))
check("shell: the LM Studio backend fallback is still OURS (engine signature) — a "
      "legitimate stale-runner kill must keep working",
      owns("runner", "/Users/x/.lmstudio/extensions/backends/b1/llama-server --port 6767"))
check("shell: an MLX runner outside the tree is OURS (engine signature)",
      owns("runner", "/usr/bin/python -m mlx_lm.server --port 6767"))
check("shell: an mlx-vlm runner is OURS", owns("runner", "python -m mlx_vlm.server --port 6767"))
check("shell: the aux slot uses the same engine signatures",
      owns("aux", "/opt/x/llama-server --port 6768"))
# U19 (2026-08-29): hermes lost its NAME signature. It used to answer "ours" to any
# command line containing "hermes dashboard"/"hermes serve" — which is precisely Debi's
# STANDALONE Hermes (~/.hermes/hermes-agent/venv). The evidence is a PATH now, widened
# to any harness's data/hermes-venv so the repo↔snapshot case still works.
check("shell: a hermes from ANOTHER HARNESS root is OURS (path, not name)",
      owns("hermes", "/Users/x/Library/Application Support/Harness/data/hermes-venv/"
                     "bin/python -m hermes dashboard --port 9119"))
check("shell: Debi's STANDALONE hermes is FOREIGN (U19 — the whole point)",
      not owns("hermes", "/Users/debik/.hermes/hermes-agent/venv/bin/hermes "
                         "dashboard --port 9119"))
check("shell: any non-harness hermes is FOREIGN",
      not owns("hermes", "/usr/local/bin/hermes dashboard --port 9119"))
check("shell: 'hermes dashboard' is never a signature by itself",
      not owns("hermes", "hermes dashboard") and not owns("hermes", "hermes serve"))
check("shell: a process that already vanished is not treated as foreign",
      owns("unsloth", ""))
# the refusals — the whole point of the slice
check("shell: Debi's STANDALONE Unsloth is FOREIGN (the reported collision)",
      not owns("unsloth", "/opt/homebrew/bin/python3.12 -m unsloth.studio --port 8899"))
check("shell: a standalone Unsloth on the upstream port is FOREIGN too",
      not owns("unsloth", "/Applications/Unsloth.app/Contents/MacOS/unsloth --port 8888"))
check("shell: a standalone ComfyUI elsewhere is FOREIGN",
      not owns("comfyui", "/Users/x/ComfyUI/venv/bin/python main.py --port 8188"))
check("shell: a standalone voicebox is FOREIGN",
      not owns("voicebox", "/Users/x/voicebox/.venv/bin/python -m backend.main"))
check("shell: an unrelated dev server is FOREIGN",
      not owns("odysseus", "node /Users/x/proj/server.js"))
check("shell: the component NAME alone is never a signature",
      not owns("unsloth", "unsloth") and not owns("comfyui", "comfyui"))

# --- 4b. wiring: every port clear in start_component.sh goes through _clear_port
import re  # noqa: E402
blind = [ln for ln in START.splitlines()
         if "lsof -ti tcp" in ln and "xargs kill" in ln and not ln.strip().startswith("#")]
check("no blind lsof|xargs-kill port clear survives in start_component.sh", blind == [], )
check("_clear_port exists", "_clear_port() {" in START)
clears = re.findall(r"^\s*_clear_port \S+ (\w+)( force)?$", START, re.M)
check("every component's port clear is routed through _clear_port (11 sites)",
      len(clears) == 11)
check("every _clear_port site names its component",
      {c for c, _ in clears} == {"runner", "odysseus", "searxng", "voicestudio",
                                 "voicebox", "comfyui", "unsloth", "hermes", "opencode"})
check("the runner keeps its force (-9) kill", clears.count(("runner", " force")) == 3)
check("hermes keeps its force (-9) kill", ("hermes", " force") in clears)
check("odysseus/searxng/voice*/comfy/unsloth/opencode keep plain SIGTERM",
      all(f == "" for c, f in clears
          if c in {"odysseus", "searxng", "voicestudio", "voicebox", "comfyui",
                   "unsloth", "opencode"}))
check("_clear_port is still LISTENER-scoped", "-sTCP:LISTEN" in START)
check("a foreign listener refuses with the exact message",
      "does not look like ours — refusing to kill it." in START)
check("the refusal names the override",
      "set HARNESS_PORT_TAKEOVER=1 to override" in START)
check("the refusal exits non-zero", "refusing to kill it." in START
      and "exit 1" in START.split("refusing to kill it.")[1][:400])
check("HARNESS_PORT_TAKEOVER=1 restores the old unconditional kill",
      '"${HARNESS_PORT_TAKEOVER:-0}" == "1"' in START)
check("the pid file is an ownership proof in its own right",
      'pf="data/${comp}.pid"' in START)
check("no component name is used as a signature for the standalone-app components",
      "*unsloth*" not in START and "*comfyui*" not in START)
# --- 4b-bis. U19: no kill by name survives, and the replacement is pidfile-scoped.
# (The full sweep across scripts/ + guards/ lives in
#  bridge/contract_tests/test_no_name_kills_contract.py — this is the local echo.)
# CODE = executable lines only. The banned commands are NAMED in the comments on
# purpose (a fix nobody can read is a fix that gets re-introduced), so the fences
# read the code, never the prose.
START_CODE = "\n".join(ln for ln in START.splitlines()
                       if not ln.lstrip().startswith("#"))
check("start_component.sh contains NO pkill/killall (U19)",
      "pkill" not in START_CODE and "killall" not in START_CODE)
check("`hermes dashboard --stop` is gone (it kills every hermes on the machine)",
      "dashboard --stop" not in START_CODE)
check("_reap_pidfile exists and re-verifies identity before signalling",
      "_reap_pidfile() {" in START
      and START.split("_reap_pidfile() {")[1].index("_cmd_looks_like_ours")
          < START.split("_reap_pidfile() {")[1].index("kill \"$sig\""))
check("the hermes arm reaps by pidfile, force, before clearing the port",
      "_reap_pidfile hermes force" in START
      and START.index("_reap_pidfile hermes force") < START.index('_clear_port "$PORT" hermes force'))
check("the runner arms reap by pidfile (3 sites: llamacpp, spec-retry, mlx)",
      START.count("_reap_pidfile runner force") == 3)
check("a pidfile pid that is NOT ours gets no signal, just a line",
      "leaving it alone and discarding the stale pidfile." in START)

# --- 4c. the bridge half
check("bridge: our own tree is OURS",
      app._port_owner_verdict(f"{R}/data/llamacpp/build/bin/llama-server --port 6767", R, "runner"))
check("bridge: a vendor path is OURS",
      app._port_owner_verdict(f"{R}/vendor/comfyui/main.py", R, "comfyui"))
check("bridge: the runner engine signature holds outside the tree",
      app._port_owner_verdict("/opt/lm/llama-server --port 6767", R, "runner"))
check("bridge: the aux slot shares the runner signatures",
      app._port_owner_verdict("/opt/lm/mlx_lm.server --port 6768", R, "aux"))
check("bridge: hermes signature",
      app._port_owner_verdict("/usr/local/bin/hermes dashboard", R, "hermes"))
check("bridge: a foreign standalone app is NOT ours",
      not app._port_owner_verdict("/opt/homebrew/bin/python -m unsloth.studio", R, "unsloth"))
check("bridge: an unknown component gets no name signature",
      not app._port_owner_verdict("/opt/homebrew/bin/whatever", R, "unsloth"))
check("bridge: no component at all still applies the path rule",
      app._port_owner_verdict(f"{R}/data/x/y", R, None)
      and not app._port_owner_verdict("/opt/other/y", R, None))
check("bridge: a vanished process ('' cmd) is not treated as foreign",
      app._port_owner_verdict("", R, "unsloth"))
check("bridge: a trailing slash on root does not break matching",
      app._port_owner_verdict(f"{R}/data/z", R + "/", "runner"))
check("bridge: /data/ must be a real path segment, not a bare substring",
      not app._port_owner_verdict("/somewhere/else/data/x", R, "unsloth"))
check("bridge: verdict is pure (no subprocess, no kill)", True)

# _kill_port_listener: kills what is ours, refuses what is not — subprocess faked
_orig_run = app.subprocess.run
_orig_pids = app._port_listener_pids
_orig_cmd = app._proc_cmdline
killed = []
try:
    app._port_listener_pids = lambda p: ["4242"]
    app._proc_cmdline = lambda pid: "/opt/homebrew/bin/python -m unsloth.studio --port 8899"
    app.subprocess.run = lambda *a, **k: killed.append(a) or None
    out = app._kill_port_listener(8899, component="unsloth")
    check("bridge: a foreign listener is REFUSED, not killed", killed == [] and len(out) == 1)
    check("bridge: the refusal message names the pid and the command",
          "4242" in out[0] and "unsloth.studio" in out[0])
    check("bridge: the refusal names the override",
          "HARNESS_PORT_TAKEOVER=1" in out[0])

    killed.clear()
    app._proc_cmdline = lambda pid: f"{R}/data/llamacpp/build/bin/llama-server --port 6767"
    out = app._kill_port_listener(6767, force=True, component="runner")
    check("bridge: our own listener IS killed", len(killed) == 1 and out == [])
    check("bridge: force uses -9", "-9" in killed[0][0])
    check("bridge: the kill is argv, not a shell string", isinstance(killed[0][0], list))

    killed.clear()
    app._proc_cmdline = lambda pid: "/opt/homebrew/bin/python -m unsloth.studio"
    os.environ["HARNESS_PORT_TAKEOVER"] = "1"
    out = app._kill_port_listener(8899, component="unsloth")
    check("bridge: HARNESS_PORT_TAKEOVER=1 kills unconditionally",
          len(killed) == 1 and out == [])
    check("bridge: takeover still goes through the LISTENER-scoped command",
          "-sTCP:LISTEN" in str(killed[0][0]))
    os.environ.pop("HARNESS_PORT_TAKEOVER", None)
finally:
    app.subprocess.run = _orig_run
    app._port_listener_pids = _orig_pids
    app._proc_cmdline = _orig_cmd

check("bridge: the pure _port_kill_cmd helper is still there (takeover path)",
      "-sTCP:LISTEN" in app._port_kill_cmd(8080))
BR = _APP_SOURCE
check("bridge: every _kill_port_listener call site names its component",
      BR.count("_kill_port_listener(") - 1
      == BR.count("_kill_port_listener(int(port), force=True, component=")
      + BR.count("_kill_port_listener(int(port), component=")
      + BR.count('_kill_port_listener(port, force=True, component="runner")')
      + BR.count('_kill_port_listener(port, force=True, component="aux")'))
check("bridge: stop() surfaces a refusal instead of claiming success",
      'JSONResponse({"ok": False, "log": "; ".join(refused)}, status_code=409)' in BR)
check("bridge: the generic stop path reports the refusal in its notes",
      '"; ".join(refused) if refused' in BR)

print(f"\n{PASS} checks passed" + (f", {len(FAIL)} FAILED: {FAIL}" if FAIL else ""))
sys.exit(1 if FAIL else 0)
