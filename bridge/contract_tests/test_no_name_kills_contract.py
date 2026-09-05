"""NO-KILL-BY-NAME CONTRACT — the PROCESS-KILL RULE (CLAUDE.md) pinned mechanically.

The rule, in Debi's words: *agents/builders and the harness may terminate ONLY
processes they themselves spawned, tracked by their own pidfile/child handle,
identity-verified (full command line) before the kill. NEVER pkill/killall by name or
pattern; never kill whatever holds a port.* She runs STANDALONE copies of the very apps
we embed, so a name match is not identity — it is her work closing without warning.

Three incidents wrote this file:
  · 2026-08-28  her standalone Unsloth, killed by our :8888 port clear
  · 2026-08-29  goose Desktop, same class
  · 2026-08-29  U19: `pkill -f "hermes (dashboard|serve)"` AND
                `hermes dashboard --stop` (hermes_cli/dashboard_procs.py::
                _kill_stale_dashboard_processes scans the whole machine for any
                `hermes dashboard|serve` and SIGTERM/SIGKILLs it) sat in the hermes
                Start arm — two name-kills aimed straight at her standalone Hermes.

A fourth wrote its PYTHON arm:
  · 2026-09-02  U64: the fence covered scripts/ and guards/ and NOTHING ELSE, so it
                asserted — correctly and uselessly — that the engine patterns were gone
                from the shell while FIVE `pkill -f` calls went on living in
                bridge/routers/: `_aux_kill` running the very `llama-server.*--port N`
                pattern U19 had removed, `pkill -f "start_component.sh runner"` in
                switch-cancel (which matches every harness root on the machine), and
                three dead `jan serve` sweeps. A sixth site turned up in the sweep:
                the generic component Stop signalled whatever data/<name>.pid said,
                with an explicit "exists but not ours — still attempt the kill" branch.
                A rule fenced in one language is a rule with a hole in it.

What this file fences, forever:

  1. NO shell script under scripts/ (or guards/) may contain pkill / killall / pgrep /
     taskkill, or pipe lsof into kill, or delegate the kill to a vendor CLI that stops
     "any" instance by name.
  1b. AND NEITHER MAY ANY PYTHON MODULE THE BRIDGE RUNS (bridge/**/*.py, tests aside) —
     the same banned list, the same no-exception-list posture, because the layer the
     kills actually lived in was the one nobody was scanning. Python stops go through
     core/procs.reap_pidfile (the pid we wrote, identity re-verified before the signal)
     or _kill_port_listener (ownership-checked), and BOTH are asserted below, live.
  2. The specific sites U19 replaced are asserted individually, so a revert is a red
     test rather than a silent regression:
       · start_component.sh has _reap_pidfile (pidfile-scoped, identity re-verified)
       · the hermes arm reaps by pidfile and then ownership-checks :9119
       · `_cmd_looks_like_ours hermes` carries NO name signature (path evidence only)
       · ship.sh quits the app by Apple Event + bundle path, and refuses a foreign
         :8700 holder instead of clearing it
       · stop.sh routes every stop through the --owner-check seam
  3. U21's sibling class (a readiness poll that lies about a healthy runner): every
     /v1/models poll against the RUNNER port carries the Authorization header that
     llama.cpp b10662 made mandatory.

The banned commands are NAMED in the scripts' comments on purpose — a fix nobody can
read gets re-introduced — so every grep here reads EXECUTABLE lines only.

Run: data/bridge-venv/bin/python -m pytest \
       bridge/contract_tests/test_no_name_kills_contract.py -q
"""
import os
import re

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
GUARDS = os.path.join(ROOT, "guards")

START = os.path.join(SCRIPTS, "start_component.sh")
SHIP = os.path.join(SCRIPTS, "ship.sh")
STOP = os.path.join(SCRIPTS, "stop.sh")


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _code(path: str) -> str:
    """Executable lines only — comments may (and should) name what was banned."""
    return "\n".join(ln for ln in _read(path).splitlines()
                     if not ln.lstrip().startswith("#"))


def _shell_files():
    out = []
    for base, _dirs, files in os.walk(SCRIPTS):
        if "__pycache__" in base:
            continue
        out += [os.path.join(base, f) for f in files if f.endswith(".sh")]
    for base, _dirs, files in os.walk(GUARDS):
        if "__pycache__" in base:
            continue
        for f in files:
            p = os.path.join(base, f)
            if f.endswith(".sh") or _read(p)[:2] == "#!":
                out.append(p)
    return sorted(out)


SHELL = _shell_files()


# ── 1. the class: no kill by name anywhere in the shell layer ─────────────────
# Each entry: (regex, what it is). All matched against executable lines only.
BANNED = [
    (r"\bpkill\b", "pkill — kills by name/pattern, not identity"),
    (r"\bkillall\b", "killall — kills by name"),
    (r"\bpgrep\b", "pgrep — the same name match, one pipe from a kill"),
    (r"\btaskkill\b", "taskkill — the Windows spelling of the same thing"),
    (r"lsof[^\n]*\|[^\n]*\bkill\b", "lsof piped into kill — a port clear with no owner check"),
    (r"\bkill\b[^\n]*\$\(\s*pgrep", "kill $(pgrep ...) — name match with extra steps"),
    (r"hermes\s+(dashboard|serve)\s+--stop",
     "hermes --stop — the vendor CLI stops EVERY hermes on the machine"),
]


@pytest.mark.parametrize("path", SHELL, ids=[os.path.relpath(p, ROOT) for p in SHELL])
def test_no_kill_by_name_in_shell_layer(path):
    code = _code(path)
    hits = []
    for pat, why in BANNED:
        for m in re.finditer(pat, code):
            line = code[:m.start()].count("\n") + 1
            hits.append(f"{os.path.relpath(path, ROOT)} (code line {line}): "
                        f"{m.group(0)!r} — {why}")
    assert not hits, (
        "PROCESS-KILL RULE violation (CLAUDE.md): terminate only what we spawned,\n"
        "identity-verified. Use _reap_pidfile (our pidfile) or _clear_port (ownership\n"
        "checked; a stranger's port REFUSES the start). Found:\n  " + "\n  ".join(hits))


def test_every_kill_is_reachable_only_through_a_verified_path():
    """Every signal names the exact child/listener PID, never a pattern or name."""
    code = _code(START)
    lines = [(i + 1, ln) for i, ln in enumerate(code.splitlines())
             if re.search(r"^\s*kill\s", ln) and "kill -0" not in ln]
    # every signalling site uses the verified $pid variable, never a pattern/name
    for num, ln in lines:
        assert re.search(r'kill\s+(-(TERM|KILL)\s+"\$pid"|"\$sig"|-0|"\$pid")', ln), \
            f"start_component.sh:{num}: unverified kill: {ln.strip()}"


# ── 2. the replaced sites, asserted one by one ───────────────────────────────
def test_reap_pidfile_exists_and_verifies_before_signalling():
    code = _code(START)
    assert "_reap_pidfile() {" in code, "the pidfile-scoped reaper is gone"
    body = code.split("_reap_pidfile() {", 1)[1].split("\n_clear_port", 1)[0]
    assert "_ownership_cli signal" in body, \
        "reaping must use the shared locked verify+signal primitive"
    assert 'kill "$sig"' not in body and 'kill "$pid"' not in body, \
        "shell check-then-kill reopens the ownership race"


def test_hermes_arm_reaps_by_pidfile_then_ownership_checks_the_port():
    code = _code(START)
    assert "_reap_pidfile hermes force" in code
    assert '_clear_port "$PORT" hermes force' in code
    assert code.index("_reap_pidfile hermes force") < code.index('_clear_port "$PORT" hermes force')


def test_hermes_ownership_has_no_name_signature():
    """U19's core: 'hermes dashboard' in a command line must NEVER prove ownership —
    that string IS Debi's standalone Hermes. Path evidence only."""
    code = _code(START)
    assert '*"hermes dashboard"*' not in code and '*"hermes serve"*' not in code, \
        "the hermes NAME signature is back — it matches the standalone app it must protect"
    assert '*"/data/hermes-venv/"*' in code, \
        "hermes ownership must be proven by the harness venv PATH"


def test_runner_arms_reap_by_pidfile_not_by_engine_pattern():
    code = _code(START)
    assert code.count("_reap_pidfile runner force") == 3, \
        "the three runner cleanup sites (llamacpp, spec-retry, mlx) must all be pidfile-scoped"
    assert "llama-server.*--port" not in code, "the engine-pattern pkill is back"
    assert "mlx_lm.server.*--port" not in code, "the engine-pattern pkill is back"


def test_ship_quits_the_app_by_apple_event_and_verified_bundle_path():
    code = _code(SHIP)
    assert 'tell application \\"$_APP_AS\\" to quit' in code, \
        "ship.sh must ASK the exact resolved bundle path, not signal a process by name"
    assert "osascript -e 'quit app \"Harness\"'" not in code, \
        "the old filename-based Apple Event quit is back"
    assert '$APP/Contents/MacOS/' in code, \
        "a surviving app pid must be identified by its bundle path"
    assert "REFUSING to ship" in code and "without a matching M.O.T launch record" in code, \
        "a foreign :8700 holder must stop the ship, not be killed"


def test_stop_routes_every_stop_through_the_owner_check_seam():
    code = _code(STOP)
    assert "bridge/core/ownership.py" in code and " signal " in code, \
        "stop.sh must use the shared locked verify+signal primitive"
    assert 'kill "$pid"' not in code, \
        "stop.sh must not split ownership verification from signalling"
    assert "-sTCP:LISTEN" in code, "the bridge stop must be listener-scoped"
    assert "left alone" in code, "an unrecorded bridge-port holder must be reported, not killed"
    listener = code.split('for pid in $(lsof -ti tcp:"$BR_PORT"', 1)[1]
    assert 'kill "$pid"' not in listener, "the diagnostic bridge-port sweep became a kill"


def test_owner_check_seam_answers_correctly_live():
    """Executed, not grepped: the shell helper itself, on the three cases that matter."""
    import subprocess

    def owns(comp, cmd):
        return subprocess.run(["bash", START, "--owner-check", comp, cmd],
                              capture_output=True, text=True, cwd=ROOT).returncode == 0

    assert owns("hermes", "/somewhere/harness/data/hermes-venv/bin/hermes dashboard")
    assert not owns("hermes", os.path.expanduser("~/.hermes/hermes-agent/venv/bin/hermes")
                    + " dashboard --port 9119")
    assert not owns("hermes", "hermes dashboard")


# ── 3. U21: a readiness poll must not lie about a healthy runner ─────────────
def test_runner_readiness_polls_carry_the_auth_header():
    """llama.cpp b10662 made /v1/models require the api-key we launch with. A poll
    without the header 401s for its whole budget and then reports a running runner
    as 'did not come up' — the LIE-TO-USER class."""
    # join shell line-continuations first — a multi-line curl is still one command
    code = re.sub(r"\\\n\s*", " ", _code(START))
    polls = [ln for ln in code.splitlines()
             if "/v1/models" in ln and "curl" in ln and "${R_PORT}" in ln]
    assert polls, "the runner readiness polls vanished — this fence would pass vacuously"
    for ln in polls:
        assert "Authorization: Bearer" in ln, \
            f"runner /v1/models poll without the auth header (U21 regression): {ln.strip()}"


# ── 4. THE PYTHON ARM (U64, 2026-09-02) ──────────────────────────────────────
# The class did not come back in the shell; it had never left Python. Same banned list,
# same posture, no exception list — applied to every module the BRIDGE RUNS.
#
# WHY THE TEST LAYER IS OUT OF SCOPE and that is not a loophole: bridge/tests/ and this
# directory exist to NAME the banned commands (this very file is full of them), exactly
# as the shell arm reads scripts/ and guards/ rather than the tests that assert on them.
# Nothing under either directory is imported by the running bridge.
BRIDGE = os.path.join(ROOT, "bridge")
_SKIP_DIRS = (os.path.join(BRIDGE, "tests"), os.path.join(BRIDGE, "contract_tests"))


def _python_files():
    out = []
    for base, _dirs, files in os.walk(BRIDGE):
        if "__pycache__" in base or base.startswith(_SKIP_DIRS):
            continue
        out += [os.path.join(base, f) for f in files if f.endswith(".py")]
    return sorted(out)


PYTHON = _python_files()


def _py_code(path):
    """Executable Python only: `#` comments AND DOCSTRINGS blanked, line numbers kept.

    The shell arm strips comment LINES because that is all the prose a shell script has.
    Python's prose is comments *and* docstrings, and in this tree the docstrings are
    where the incidents are written down — so both go, AND NOTHING ELSE DOES. Ordinary
    string literals stay, because that is exactly where all five of U64's kills lived:
    a subprocess call whose command was built as an f-string. Blanking rather than
    deleting keeps the reported line numbers honest."""
    import ast
    src = _read(path)
    keep = [("" if ln.lstrip().startswith("#") else ln) for ln in src.splitlines()]
    try:
        tree = ast.parse(src)
    except SyntaxError:               # unparseable module: scanned anyway, prose and all
        return "\n".join(keep)
    for node in ast.walk(tree):
        # Any statement that is JUST a string literal — module/class/function docstrings
        # and the bare-string comment blocks this tree uses in a few places.
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            for i in range(node.lineno - 1, min(node.end_lineno, len(keep))):
                keep[i] = ""
    return "\n".join(keep)


@pytest.mark.parametrize("path", PYTHON, ids=[os.path.relpath(p, ROOT) for p in PYTHON])
def test_no_kill_by_name_in_the_python_layer(path):
    code = _py_code(path)
    hits = []
    for pat, why in BANNED:
        for m in re.finditer(pat, code):
            line = code[:m.start()].count("\n") + 1
            hits.append(f"{os.path.relpath(path, ROOT)} (code line {line}): "
                        f"{m.group(0)!r} — {why}")
    assert not hits, (
        "PROCESS-KILL RULE violation (CLAUDE.md) in the PYTHON layer — U64's whole\n"
        "point. Stop what we spawned: core/procs.reap_pidfile (our pidfile, identity\n"
        "re-verified before the signal) or _kill_port_listener (ownership-checked; a\n"
        "stranger's port is REFUSED, not cleared). Found:\n  " + "\n  ".join(hits))


def test_python_has_no_unowned_port_clear_helper():
    """`_port_kill_cmd` built `lsof -ti tcp:N -sTCP:LISTEN | xargs kill` for the
    old HARNESS_PORT_TAKEOVER branch — the move that closed Debi's Unsloth. No
    environment variable may restore an unowned kill."""
    procs = _read(os.path.join(BRIDGE, "core", "procs.py"))
    assert "_port_kill_cmd" not in _code(os.path.join(BRIDGE, "core", "procs.py")), \
        "the unowned port-clear helper is back"
    assert 'os.environ.get("HARNESS_PORT_TAKEOVER")' not in procs, \
        "an environment-controlled unowned port kill is back"


def test_reap_pidfile_verifies_identity_before_signalling():
    """The Python mirror of the shell's _reap_pidfile, asserted the same way U19
    asserts the original: the ownership check must precede the signal IN THE SOURCE."""
    code = _code(os.path.join(BRIDGE, "core", "procs.py"))
    assert "def reap_pidfile(" in code, "the pidfile-scoped reaper is gone"
    body = code.split("def reap_pidfile(", 1)[1].split("\ndef ", 1)[0]
    assert "_ownership.signal_owned" in body, \
        "reaping must use the shared locked verify+signal primitive"
    assert "_cmd_is_under_root" not in body and "_proc_cwd" not in body, (
        "path or CWD evidence has become signal authority again")
    assert 'subprocess.run(["kill"]' not in body, \
        "Python check-then-kill reopens the ownership race"


def test_aux_stop_is_pidfile_first_then_ownership_checked_port():
    """U64's headline site: Stop aux reached any llama-server on the machine that
    matched a port number. Now it reaps data/aux.pid, then ownership-checks the port."""
    code = _code(os.path.join(BRIDGE, "routers", "models.py"))
    body = code.split("def _aux_kill(", 1)[1].split("\ndef ", 1)[0]
    assert 'stop_owned_component("aux", port' in body, \
        "the aux stop no longer uses the shared launch-record-first transaction"
    primitive = _code(os.path.join(BRIDGE, "core", "procs.py")).split(
        "def stop_owned_component(", 1)[1].split("\ndef ", 1)[0]
    assert "_read_ownership(component)" in primitive
    assert "_port_listener_pids(int(port))" in primitive
    assert primitive.index("_read_ownership(component)") < primitive.index(
        "_port_listener_pids(int(port))"), \
        "launch provenance must be checked before the port postcondition"
    # …and the pidfile only exists because the START writes it. Without this the reap
    # above degrades to a no-op and the fix is decoration. (The aux ROUTES moved to
    # routers/aux.py in the same slice; _aux_kill stayed in models.py because the
    # model-delete path calls it.)
    assert 'write_pidfile("aux"' in _code(os.path.join(BRIDGE, "routers", "aux.py")), \
        "aux_start stopped recording its own pid — reap_pidfile then has nothing to verify"


def test_switch_cancel_stops_the_script_we_launched_by_pidfile():
    code = _code(os.path.join(BRIDGE, "routers", "models.py"))
    assert "_script_tracked(" in code, \
        "the switch's start script is untracked again — cancel can then only guess"
    assert "reap_pidfile(SWITCH_TRACK" in code
    assert "start_component.sh runner" not in code, \
        "the cross-root start-script pattern is back (it names EVERY harness root)"


def test_component_stop_routes_the_pid_kill_through_the_verified_reaper():
    """The sixth site. It signalled data/<name>.pid unverified, and its
    PermissionError branch signalled a pid it had just proven belonged to someone else."""
    code = _code(os.path.join(BRIDGE, "routers", "component_lifecycle.py"))
    assert "reap_pidfile(name, retire=False)" in code, \
        "the generic component stop is not retaining its verified claim through shutdown"
    assert 'subprocess.run(["kill", str(pid)]' not in code, \
        "the unverified pid signal is back in the generic stop"


def test_reap_pidfile_refuses_a_foreign_pid_and_reaps_our_own_live():
    """EXECUTED, not grepped — the journey that matters, both directions, on real
    processes: a pidfile pointing at a process that is NOT ours must survive (this is
    Debi's standalone app, and the pid-recycling case), and one that IS ours must die."""
    import subprocess as sp
    import sys
    import time

    sys.path.insert(0, ROOT)
    from bridge.core import procs

    data = os.path.join(ROOT, "data")
    os.makedirs(data, exist_ok=True)
    pf = os.path.join(data, "u64probe.pid")

    # (a) FOREIGN: /bin/sleep — a real live process with no path of ours in its command
    #     line. This stands in for her standalone llama-server / Unsloth / goose.
    # ⚠️ cwd="/" IS PART OF THE FIXTURE, not tidiness. Ownership evidence is a path in
    #    our tree — in the command line OR as the process's WORKING DIRECTORY (that
    #    second factor exists because start_component.sh cd's into our tree and launches
    #    RELATIVE commands: Odysseus runs as a bare `python -m uvicorn app:app`). A child
    #    spawned by pytest inherits the REPO ROOT as its cwd, which correctly reads as
    #    ours — so a stand-in for Debi's standalone app has to live somewhere else, as
    #    hers does.
    foreign = sp.Popen(["/bin/sleep", "37"], cwd="/")
    try:
        with open(pf, "w") as fh:
            fh.write(str(foreign.pid))
        notes = procs.reap_pidfile("u64probe")
        assert notes and "no matching M.O.T launch record" in notes[0], \
            f"a foreign pid was not refused: {notes}"
        assert foreign.poll() is None, "IT KILLED A PROCESS THAT WAS NOT OURS"
        assert not os.path.exists(pf), "the stale pidfile should be discarded"
    finally:
        foreign.kill()                      # our own child handle, no name, no pattern
        foreign.wait()

    # (b) OURS: the same binary, run from a path UNDER OUR ROOT — which is the whole of
    #     the evidence the rule accepts.
    # A script UNDER OUR ROOT, run by whatever interpreter is handy: the ownership
    # evidence the rule accepts is a path under ROOT/data in the command line, and this
    # produces exactly that.
    # (Copying /bin/sleep into data/ was the first attempt and it does not work on
    # Apple silicon: a relocated platform binary fails its signature check and is
    # SIGKILLed on exec — `ps` then shows <defunct>, which is not "ours" either.)
    mine_bin = os.path.join(data, "u64probe-sleep.py")
    with open(mine_bin, "w") as fh:
        fh.write("import time\ntime.sleep(37)\n")
    mine = sp.Popen([sys.executable, mine_bin])
    try:
        procs.write_pidfile("u64probe", mine.pid)
        notes = procs.reap_pidfile("u64probe", force=True)
        assert notes == [], f"our own process was refused: {notes}"
        for _ in range(20):
            if mine.poll() is not None:
                break
            time.sleep(0.1)
        assert mine.poll() is not None, "a process we launched from our own ROOT survived"
    finally:
        if mine.poll() is None:
            mine.kill()
            mine.wait()
        for p in (mine_bin, pf):
            try:
                os.remove(p)
            except OSError:
                pass

    # (c) THE REGRESSION THIS SLICE'S OWN ADVERSARIAL PASS FOUND, 2026-09-02.
    #     A foreign process whose command line CONTAINS AN ENGINE NAME ("llama-server")
    #     but no path of ours, with its pid planted in OUR pidfile — i.e. a recycled pid
    #     that happens to be somebody's standalone backend. The first draft of
    #     reap_pidfile reused `_port_owner_verdict`, whose runner/aux arm accepts that
    #     name, and POST /api/aux/stop SIGKILLed it on the live stack. Path evidence
    #     only, for ever: this must be a refusal.
    #     ⚠️ IT MUST BE REAPED UNDER THE REAL COMPONENT NAMES ("aux", "runner"): the
    #     engine signatures live in _PORT_OWNER_SIGS keyed by exactly those, so a probe
    #     component name would make this test pass vacuously. Their pidfiles are
    #     therefore BACKED UP AND RESTORED around the probe.
    import shutil as _sh
    import tempfile
    tmpd = tempfile.mkdtemp(prefix="u64probe-foreign-")
    foreign_script = os.path.join(tmpd, "llama-server")   # the NAME is the whole point
    with open(foreign_script, "w") as fh:
        fh.write("import time\ntime.sleep(37)\n")
    # ⚠️ THE SYSTEM python, NOT sys.executable. The gate runs out of
    # data/bridge-venv/bin/python, which is itself a path under our ROOT — using it here
    # made the stranger look OURS and this assertion pass for the wrong reason (caught
    # while writing it). The interpreter has to be as foreign as the script.
    stranger = sp.Popen(["/usr/bin/python3", foreign_script, "--port", "6768"], cwd="/")
    saved = {}
    try:
        for comp in ("aux", "runner"):
            real = os.path.join(data, f"{comp}.pid")
            owner = os.path.join(data, f"{comp}.owner")
            for candidate in (real, owner):
                if os.path.exists(candidate):
                    saved[candidate] = _read(candidate)
                    os.remove(candidate)
            with open(real, "w") as fh:
                fh.write(str(stranger.pid))
            notes = procs.reap_pidfile(comp)
            assert notes and "no matching M.O.T launch record" in notes[0], (comp, notes)
            assert stranger.poll() is None, (
                f"AN ENGINE NAME PROVED OWNERSHIP FOR {comp} — a recycled pid just "
                f"became a name-match kill, which is the whole of U64")
    finally:
        stranger.kill()
        stranger.wait()
        _sh.rmtree(tmpd, ignore_errors=True)
        for comp in ("aux", "runner"):
            for candidate in (os.path.join(data, f"{comp}.pid"),
                              os.path.join(data, f"{comp}.owner")):
                if candidate in saved:         # put live bookkeeping back byte for byte
                    with open(candidate, "w") as fh:
                        fh.write(saved[candidate])
                elif os.path.exists(candidate):
                    os.remove(candidate)

    # (d) NO PIDFILE AT ALL → a sentence, and nothing signalled. There is no fallback
    #     to a name sweep, which is the entire point of the rule.
    notes = procs.reap_pidfile("u64probe-absent")
    assert notes and "refusing to search for one by name" in notes[0], notes
