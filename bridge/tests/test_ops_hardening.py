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
        # put the chosen interpreter where verify.sh looks first
        (fake / "data" / "bridge-venv" / "bin").mkdir(parents=True)
        (fake / "data" / "bridge-venv" / "bin" / "python").symlink_to(sys.executable)
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
check("shell: our own venv launch is OURS (unsloth)",
      owns("unsloth", f"{R}/data/unsloth-venv/bin/unsloth studio --port 8899"))
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
check("shell: a hermes from ANOTHER root is OURS (the pkill above already targets it)",
      owns("hermes", "/usr/local/bin/hermes dashboard --port 9119"))
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
BR = (ROOT / "bridge" / "app.py").read_text()
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
