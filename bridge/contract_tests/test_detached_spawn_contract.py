"""DETACHED-SPAWN CONTRACT — the 2026-08-30 silent-death incident, pinned forever.

THE INCIDENT. Runner + Hermes + Odysseus died together, at least twice, on an idle
machine with no agent running, while Searxng/Voicestudio/Voicebox/ComfyUI/Unsloth/
OpenCode survived every time.

THE MECHANISM (measured on the live process table, then reproduced from scratch):

  1. `nohup CMD &` blocks SIGHUP and nothing else. It does NOT change the process
     group. A component started through a bridge route (Restart, model switch,
     rebind) runs start_component.sh as a child of the bridge and therefore inherits
     the BRIDGE's pgid. Measured before the fix: llama-server 35558, hermes 35657 and
     odysseus 35673 all carried pgid 25183, which was the bridge's own pid.

  2. macOS Foundation's `Process.terminate()` — app/main.swift calls it in
     applicationWillTerminate — signals THE PROCESS GROUP, not just the child.
     Verified with a purpose-built Swift harness, both directions: a `nohup`ed
     grandchild DIED with the child; a setsid'd grandchild SURVIVED.

  So every quit of MOT Deck was a group kill that reached through the bridge into
  whatever start_component.sh had most recently spawned. The survivors were simply
  components whose spawning shells belonged to groups that were already dead.

THE FIX: every component spawn goes through `_detached`, which setsid()s (own session
⇒ own process group ⇒ no controlling terminal) and then EXECs, so the pid recorded in
data/<comp>.pid is still the component itself.

WHAT THIS FILE FENCES:
  A. the FENCE     — no bare `nohup … &` component launch survives in the shell layer,
                     and every `_detached` call site is backgrounded (the helper uses
                     `exec`, so a foreground call would replace the script).
  B. the BEHAVIOUR — a LIVE scratch process spawned through the real helper gets its
                     own session and process group, and SURVIVES a SIGTERM addressed
                     to the parent shell's whole group. This is the incident,
                     re-staged in miniature, every time the gate runs.
  C. the SINGLETON — one bridge per harness root: a second boot against a live,
                     identity-verified pidfile stands down with a sentence and exit 0;
                     a stale pidfile (dead pid, or a live pid whose command line is
                     NOT our bridge) is ignored, left unsignalled, and overwritten.

PROCESS-KILL RULE COMPLIANCE (CLAUDE.md): the live test signals ONLY pids it spawned
itself in this process, tracked in a pidfile it wrote, and re-verifies the command
line before every signal. Nothing is matched by name and no port is ever cleared.

Run: data/bridge-venv/bin/python -m pytest \
       bridge/contract_tests/test_detached_spawn_contract.py -q
"""
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
START = ROOT / "scripts" / "start_component.sh"
SHIP = ROOT / "scripts" / "ship.sh"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def _code(p: Path) -> list[str]:
    """Executable lines only — the comments deliberately NAME the banned pattern so
    that the fix stays readable, and must not trip the greps below."""
    return [ln for ln in _read(p).splitlines() if not ln.lstrip().startswith("#")]


# ══ A. THE FENCE ══════════════════════════════════════════════════════════════

def test_start_component_defines_the_detach_helper():
    code = "\n".join(_code(START))
    assert "_detached()" in code, "scripts/start_component.sh lost the _detached helper"
    assert "POSIX::setsid()" in code, (
        "the detach helper no longer calls setsid — without a NEW SESSION the "
        "component keeps the bridge's process group and dies with the app again")
    assert "exec { $ARGV[0] } @ARGV" in code, (
        "the helper must exec the block form: it never falls back to /bin/sh, so a "
        "component's argv (spaces, `env VAR=val` prefixes, arrays) survives verbatim")
    assert re.search(r"^\s*exec nohup perl", code, re.M), (
        "the helper must `exec`, or bash's background subshell lingers and `$!` can "
        "name the WRAPPER instead of the component — silently breaking every pidfile")


def test_no_bare_nohup_component_launch_survives():
    """THE REGRESSION FENCE. A `nohup … &` line that is not the helper itself is a
    component spawned back into the bridge's process group."""
    offenders = []
    for ln in _code(START):
        if "nohup" not in ln:
            continue
        if "exec nohup perl" in ln:      # the helper's own single, sanctioned line
            continue
        offenders.append(ln.strip())
    assert not offenders, (
        "bare nohup launches found in scripts/start_component.sh — these inherit the "
        "caller's process group and die with the app (2026-08-30 incident):\n  "
        + "\n  ".join(offenders))


def test_every_detached_call_site_is_backgrounded():
    """`_detached` ends in `exec`. Called in the FOREGROUND it would replace
    start_component.sh itself, so every call site must end in `&`."""
    lines = _code(START)
    bad = []
    for i, ln in enumerate(lines):
        if not re.search(r"(^|\s)_detached\s", ln):
            continue
        if "_detached()" in ln:
            continue
        # follow shell line-continuations to the end of the command
        j, tail = i, ln
        while tail.rstrip().endswith("\\") and j + 1 < len(lines):
            j += 1
            tail = lines[j]
        if not tail.rstrip().endswith("&"):
            bad.append(ln.strip())
    assert not bad, (
        "_detached call sites that are not backgrounded (the helper execs — a "
        "foreground call replaces the whole script):\n  " + "\n  ".join(bad))


def test_every_component_arm_spawns_through_the_helper():
    """Every component the harness starts must be routed through _detached — a new
    arm that forgets is exactly how this incident comes back."""
    code = "\n".join(_code(START))
    for comp, needle in [
        ("runner (llama.cpp)", '_detached "$BIN" "$@"'),
        ("runner (MLX)", '_detached "${CMD[@]}" --model "$MODEL_PATH"'),
        ("odysseus", "_detached python -m uvicorn app:app"),
        ("searxng", "_detached env SEARXNG_SETTINGS_PATH="),
        ("voicestudio", '_detached env "${VS_ENV[@]}"'),
        ("voicebox", '_detached "$VBPY" "${VB_CMD[@]}"'),
        ("comfyui", '_detached "$CUPY" "${CU_CMD[@]}"'),
        ("unsloth", '_detached "${US_BIN[@]}" "${US_CMD[@]}"'),
        ("opencode", "_detached env XDG_CONFIG_HOME="),
        ("hermes", "_detached env HERMES_DESKTOP=1"),
    ]:
        assert needle in code, f"the {comp} arm no longer spawns through _detached"


def test_opencode_passes_its_confinement_through_env_not_a_bash_prefix():
    """`VAR=val _detached …` is a temporary-assignment prefix on a FUNCTION call:
    bash sets the variable in the shell rather than reliably placing it in the
    exec'd program's environment. OpenCode's four XDG_* variables are the ONLY thing
    keeping its sessions db and runtime-installed packages inside data/opencode, so
    losing them is a silent-wrong, not a crash."""
    code = "\n".join(_code(START))
    assert "_detached env XDG_CONFIG_HOME=" in code
    assert not re.search(r'XDG_CONFIG_HOME="[^"]*"\s+XDG_CACHE_HOME.*\n.*\n.*_detached\s+"\$OC_BIN"',
                         code), "opencode's env is being passed as a bash prefix again"


def test_ship_starts_the_bridge_detached_and_reaps_by_pidfile():
    code = "\n".join(_code(SHIP))
    assert "POSIX::setsid()" in code, (
        "ship.sh must start the bridge in its own session, or a teardown of the "
        "agent/terminal process tree takes the bridge with it")
    assert "--timeout-graceful-shutdown" in code, (
        "ship.sh's bridge launch lost --timeout-graceful-shutdown: uvicorn then waits "
        "forever on the infinite /api/events stream and the process never exits")
    assert "data/bridge.pid" in code, "ship.sh must reap the bridge by its pidfile first"
    assert "_bridge_cmd_is_ours" in code, (
        "ship.sh must identity-verify a bridge pid before signalling it")


def test_app_launches_the_bridge_with_a_graceful_shutdown_deadline():
    swift = _read(ROOT / "app" / "main.swift")
    assert '"--timeout-graceful-shutdown", "10"' in swift, (
        "app/main.swift lost the graceful-shutdown deadline. Without it, SIGTERM "
        "closes the listening socket but the process waits forever on an open "
        "text/event-stream — the three-live-bridges state of 2026-08-30.")


# ══ B. THE BEHAVIOUR — the incident, re-staged, live ══════════════════════════

@pytest.mark.skipif(sys.platform != "darwin", reason="the incident is macOS-specific")
def test_live_detached_process_survives_a_group_kill(tmp_path):
    """Re-stage the incident in miniature: a CONTROL process launched the old way
    (`nohup … &`) beside one launched through the REAL helper, both under a launcher
    shell that owns its own process group. SIGTERM that group — exactly what
    Foundation's Process.terminate() does to the bridge — and assert the control DIED
    while the detached one LIVED.

    The fence tests above read the source; this one asks the kernel, and it is the
    only test here that can fail the way the incident actually failed.

    ⚠️ THE SIGNAL GOES TO A GROUP WE CREATED, NEVER OURS. An earlier draft did
    `os.killpg(os.getpgid(0), SIGTERM)` "because pytest ignores SIGTERM anyway" — and
    took down the terminal that was running the gate, because a group signal reaches
    every OTHER member of the group too. A test that proves detachment by killing the
    developer's shell is not a test. `start_new_session=True` on the launcher gives us
    a group whose entire membership we put there ourselves.
    """
    marker = f"harness-detach-selftest-{os.getpid()}"
    pidfile = tmp_path / "pids.txt"
    errfile = tmp_path / "selftest.err"

    def _cmd(pid: int) -> str:
        r = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                           capture_output=True, text=True)
        return r.stdout.strip()

    # Both scratch processes LOOP rather than `exec sleep 30`: an exec REPLACES argv,
    # so the marker would vanish at the very moment the process became the thing we
    # need to identify — leaving the reaper below with nothing to verify against.
    #
    # ⚠️ THE SCRIPT PATH IS QUOTED. The repo lives under "Claude Proj Rootz/New
    # Harness/…" — an unquoted $START word-splits, the inner bash never runs, no
    # second pid is ever printed, and the readline below blocks until the suite
    # times out with no explanation at all. `set -e` is here for the same reason:
    # a launcher that fails must close the pipe so the test fails LOUDLY instead
    # of hanging.
    body = f"""
      set -e
      nohup /bin/sh -c ': {marker}-control ; while : ; do sleep 1 ; done' >/dev/null 2>&1 &
      echo $!
      bash '{START!s}' --detach-selftest \
        /bin/sh -c ': {marker}-detached ; while : ; do sleep 1 ; done'
      while : ; do sleep 1 ; done
    """
    with errfile.open("w") as eh:
        launcher = subprocess.Popen(
            ["bash", "-c", body], cwd=ROOT,
            stdout=subprocess.PIPE, stderr=eh, text=True,
            start_new_session=True)          # its OWN session/group: pgid == its pid

    control = detached = 0
    try:
        def _pid_line(what: str) -> int:
            ln = launcher.stdout.readline().strip()
            assert ln.isdigit(), (
                f"the launcher printed no {what} pid (got {ln!r}); its stderr was: "
                f"{errfile.read_text()!r}")
            return int(ln)

        control = _pid_line("control")
        detached = _pid_line("detached")
        pidfile.write_text(f"{control}\n{detached}\n")

        err = errfile.read_text()
        assert "setsid failed" not in err, f"the detach helper could not setsid: {err}"

        # Wait for the detached one to finish its exec chain.
        #
        # ⚠️ WAITING FOR THE MARKER ALONE IS A RACE, AND IT COST AN HOUR: the marker
        # sits in the WRAPPER's argv too (`perl … -- /bin/sh -c ": <marker>; …"`), so
        # `marker in _cmd()` is already true while perl is still starting, BEFORE it
        # has called setsid. Polling on that produced a confident, WRONG "setsid did
        # not take effect" failure against a helper that works perfectly. The honest
        # signal is the wrapper being gone from the command line.
        def _execed() -> bool:
            c = _cmd(detached)
            return f"{marker}-detached" in c and "-MPOSIX" not in c

        for _ in range(100):
            if _execed():
                break
            time.sleep(0.1)
        assert _execed(), f"the detached process never execed: {_cmd(detached)!r}"
        assert f"{marker}-control" in _cmd(control), "the control process never started"

        group = os.getpgid(launcher.pid)
        assert group == launcher.pid, "the launcher did not get its own process group"

        # THE ASYMMETRY, stated before the kill so a failure says which half broke.
        assert os.getpgid(control) == group, (
            "the CONTROL process is not in the launcher's group — the `nohup … &` "
            "baseline is not reproducing the pre-fix behaviour, so this test would "
            "pass vacuously")
        assert os.getsid(detached) == detached, (
            f"detached pid {detached} is in session {os.getsid(detached)}, not its own")
        assert os.getpgid(detached) == detached, (
            f"detached pid {detached} is in process group {os.getpgid(detached)}, not its own")
        assert os.getpgid(detached) != group

        # ── THE INCIDENT ──────────────────────────────────────────────────────
        os.killpg(group, signal.SIGTERM)
        time.sleep(1.5)

        assert f"{marker}-control" not in _cmd(control), (
            "the CONTROL process survived a SIGTERM to its process group — the "
            "baseline is wrong and this test proves nothing")
        assert f"{marker}-detached" in _cmd(detached), (
            "the DETACHED process died with its launcher's process group. This is the "
            "2026-08-30 incident reproducing: components are not detached, and the "
            "next quit of MOT Deck will take the runner, Hermes and Odysseus with it.")
    finally:
        # PROCESS-KILL RULE: only pids THIS test spawned and wrote down, each one
        # re-verified by its unique marker before the signal. A recycled pid gets
        # nothing. Nothing here is matched by name and no port is touched.
        for pid in (control, detached):
            if pid and marker in _cmd(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        try:
            launcher.kill()
            launcher.stdout.close()
            launcher.wait(timeout=5)
        except Exception:                                # noqa: BLE001
            pass


def test_the_perl_fallback_is_dependency_free():
    """The fallback exists BECAUSE the environment is already missing something it
    should have, so it must not lean on a second external binary. It once read
    `exec nohup "$@"`; with nohup also absent that died as `exec: nohup: not found`,
    leaving a dead pid in the component's pidfile and a component that never started
    — a graceful-absence path that fails silently is worse than none."""
    code = "\n".join(_code(START))
    assert "command -v perl" in code, "the detach helper no longer checks for perl"
    assert "trap '' HUP" in code, (
        "the perl-absent fallback must ignore SIGHUP itself rather than shelling out "
        "to nohup — that is the one thing nohup was doing for it")
    fb = code[code.index("command -v perl"):code.index("exec nohup perl")]
    assert "nohup" not in fb, "the perl-absent fallback depends on nohup again"


@pytest.mark.skipif(sys.platform != "darwin", reason="the incident is macOS-specific")
def test_a_missing_perl_still_starts_the_component_and_says_what_was_lost(tmp_path):
    """GRACEFUL ABSENCE (walked, not asserted from source). With perl gone the
    component must still start — un-detached — and the log must say so in sentences.
    Refusing to start would be a worse regression than starting unprotected."""
    binp = tmp_path / "bin"
    binp.mkdir()
    needed = ["bash", "dirname", "mkdir", "ps", "tr", "cat", "sleep",
              "basename", "awk", "sed", "grep", "uname"]
    for b in needed:
        real = subprocess.run(["command", "-v", b], capture_output=True, text=True,
                              shell=False, executable="/bin/bash").stdout.strip() \
            or subprocess.run(["/bin/bash", "-c", f"command -v {b}"],
                              capture_output=True, text=True).stdout.strip()
        if real:
            (binp / b).symlink_to(real)
    assert not (binp / "perl").exists()

    marker = f"harness-noperl-{os.getpid()}"
    errfile = tmp_path / "noperl.err"
    env = dict(os.environ, PATH=str(binp))
    with errfile.open("w") as eh:
        out = subprocess.run(
            ["/bin/bash", str(START), "--detach-selftest",
             "/bin/sh", "-c", f": {marker} ; while : ; do sleep 1 ; done"],
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=eh, text=True, timeout=30)
    pid = int(out.stdout.strip())

    def _cmd(p: int) -> str:
        return subprocess.run(["ps", "-o", "command=", "-p", str(p)],
                              capture_output=True, text=True).stdout.strip()

    try:
        # ⚠️ POLLED, NOT READ ONCE. The helper's sentences are written by the
        # BACKGROUND subshell while the parent shell is already running `echo $!;
        # exit 0`, so subprocess.run can return with only the first two lines on
        # disk. Reading once made this test pass alone and fail in the full suite —
        # the classic shape of a flake nobody trusts.
        err = ""
        for _ in range(50):
            err = errfile.read_text()
            if "2026-08-30" in err:
                break
            time.sleep(0.1)
        assert "perl is not on PATH" in err, f"the fallback said nothing useful: {err!r}"
        assert "2026-08-30" in err, (
            f"the sentence must name the incident it re-opens; got {err!r}")
        for _ in range(50):
            if marker in _cmd(pid):
                break
            time.sleep(0.1)
        assert marker in _cmd(pid), (
            f"with perl absent the component did not start at all: {err!r}")
    finally:
        if marker in _cmd(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


# ══ C. THE SINGLETON ══════════════════════════════════════════════════════════

sys.path.insert(0, str(ROOT))
from bridge.core import singleton as S       # noqa: E402


class _Stood(Exception):
    """Stands in for os._exit so the test can observe the stand-down."""


def _exit_probe(code):
    raise _Stood(code)


def _as_bridge_boot(monkeypatch, port="8700"):
    monkeypatch.setattr(
        S.sys, "argv",
        ["uvicorn", "bridge.app:app", "--host", "127.0.0.1", "--port", port])


def test_identity_is_path_evidence_not_a_name():
    """`python` or `uvicorn` in a command line is evidence of nothing — Debi runs
    standalone copies of what we embed. Only THIS root's venv python counts."""
    root = Path("/tmp/h")
    ours = "/tmp/h/data/bridge-venv/bin/python -m uvicorn bridge.app:app --host 127.0.0.1 --port 8700"
    assert S.is_our_bridge(ours, root, "8700")
    assert not S.is_our_bridge(ours, Path("/tmp/other"), "8700"), "another harness root matched"
    assert not S.is_our_bridge(ours, root, "8701"), "a different port matched"
    assert not S.is_our_bridge("/usr/bin/python3 -m uvicorn other.app:app --port 8700",
                               root, "8700"), "a stranger's uvicorn matched"
    assert not S.is_our_bridge("", root, "8700")


def test_second_boot_against_a_live_pidfile_stands_down_with_a_sentence(tmp_path, monkeypatch):
    _as_bridge_boot(monkeypatch)
    (tmp_path / "data").mkdir()
    # A pid that IS alive and whose command line verifies as ours: this test process,
    # with _cmdline stubbed. Nothing is spawned and nothing is ever signalled.
    other = os.getpid() + 1
    monkeypatch.setattr(S, "_alive", lambda p: True)
    monkeypatch.setattr(
        S, "_cmdline",
        lambda p: f"{tmp_path}/data/bridge-venv/bin/python -m uvicorn bridge.app:app --port 8700")
    (tmp_path / "data" / "bridge.pid").write_text(str(other))

    with pytest.raises(_Stood) as ei:
        S.claim_or_exit(tmp_path, _exit=_exit_probe)
    assert ei.value.args[0] == 0, "standing down in favour of a working bridge is exit 0, not 1"
    # the incumbent's claim is untouched — we never overwrite or delete it
    assert (tmp_path / "data" / "bridge.pid").read_text() == str(other)


def test_a_dead_pid_in_the_pidfile_is_ignored_and_overwritten(tmp_path, monkeypatch, capsys):
    _as_bridge_boot(monkeypatch)
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(S, "_alive", lambda p: False)
    monkeypatch.setattr(S, "_listener_pid", lambda port: 0)
    (tmp_path / "data" / "bridge.pid").write_text("999999")

    msg = S.claim_or_exit(tmp_path, _exit=_exit_probe)
    assert "claimed" in msg
    assert (tmp_path / "data" / "bridge.pid").read_text() == str(os.getpid())
    assert "not running" in capsys.readouterr().out, "a stale pidfile must be explained, not silently dropped"


def test_a_live_pid_that_is_not_our_bridge_is_ignored_and_never_signalled(tmp_path, monkeypatch, capsys):
    """The PROCESS-KILL RULE in the singleton: a recycled pid belonging to somebody
    else's process must be left completely alone — not signalled, not deferred to."""
    _as_bridge_boot(monkeypatch)
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(S, "_alive", lambda p: True)
    monkeypatch.setattr(S, "_cmdline", lambda p: "/Applications/Some.app/Contents/MacOS/Some")
    monkeypatch.setattr(S, "_listener_pid", lambda port: 0)
    (tmp_path / "data" / "bridge.pid").write_text("4242")

    msg = S.claim_or_exit(tmp_path, _exit=_exit_probe)
    assert "claimed" in msg
    assert (tmp_path / "data" / "bridge.pid").read_text() == str(os.getpid())
    out = capsys.readouterr().out
    assert "leaving that process alone" in out


def test_the_guard_never_fires_on_a_plain_import(tmp_path, monkeypatch):
    """~40 test files import bridge.app in process. If the guard were argv-blind, a
    pytest run against a live harness would exit the test session."""
    monkeypatch.setattr(S.sys, "argv", ["pytest", "-q", "bridge/tests"])
    msg = S.claim_or_exit(tmp_path, _exit=_exit_probe)
    assert "guard skipped" in msg
    assert not (tmp_path / "data" / "bridge.pid").exists()


def test_singleton_contains_no_kill_of_any_kind():
    """The incumbent WINS. There is no branch anywhere in this guard that signals
    another process or clears a port."""
    import ast
    src = _read(ROOT / "bridge" / "core" / "singleton.py")
    # Strip comments AND docstrings: this file's prose deliberately NAMES the
    # mechanism ("on SIGTERM uvicorn closes…") because a fix nobody can read gets
    # re-introduced. Only executable code is fenced.
    tree = ast.parse(src)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(getattr(body[0], "value", None), ast.Constant) \
                and isinstance(body[0].value.value, str):
            body.pop(0)
    code = ast.unparse(tree)
    for banned in ("os.kill(", "killpg", "pkill", "SIGTERM", "SIGKILL", "terminate("):
        if banned == "os.kill(":
            # os.kill(pid, 0) is a liveness PROBE, not a signal — allowed, pinned here.
            assert "os.kill(pid, 0)" in code
            assert code.count("os.kill(") == 1, "a real signal appeared in the singleton"
            continue
        assert banned not in code, f"{banned} appeared in the bridge singleton"
