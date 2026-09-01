"""PIDFILE ↔ PORT CONTRACT (U54) — data/<comp>.pid names the process that HOLDS the
port, not the one we reported launching.

THE INCIDENT, measured twice on the live stack (2026-08-30), and pre-existing rather
than caused by the detachment slice:

    data/runner.pid = 35568   while llama-server was 35558
    data/runner.pid = 44288   while :6767 was held by 44276

`runner.log` shows the shape: each Start produced two "llama_server: exiting due to
HTTP server error" lines (a launch losing the port to the one already coming up) and
one "listening on http://127.0.0.1:6767". `_launch_llama`'s speculative-decoding RETRY
arm relaunches and rewrites data/runner.pid with the LAST attempt's `$!` — the one that
died. Consequences, all quiet: `_reap_pidfile runner` could not stop the real runner (it
fell through to `_clear_port`, which is why nobody noticed), and the
"[harness] runner … pid=$(cat data/runner.pid)" line the panel shows was false. Health
never noticed, because health is probe-based — which is exactly why a dead pidfile could
sit there for weeks.

THE FIX is this repo's oldest rule, applied one field over: AN EXIT CODE — or a `$!` —
IS A REPORT, NOT A FACT (see the U15 header in bridge/routers/components.py). Once the
readiness poll says the server answers, `_stamp_pidfile_from_port` ASKS THE PORT who
holds it and records that.

WHAT THIS FILE FENCES:
  A. the FENCE     — the helper exists, both runner engines call it at readiness, and it
                     verifies ownership before writing (a pidfile is the one input
                     _reap_pidfile signals on sight, so an unverified pid in it would be
                     a way to make the next Start kill somebody else's process).
  B. the BEHAVIOUR — LIVE: a pidfile pre-seeded with a lie is corrected to the pid that
                     really holds the port; a second run is a no-op; and a listener that
                     is NOT ours is refused, leaving the file untouched.

PROCESS-KILL RULE COMPLIANCE (CLAUDE.md): every process this file signals was spawned by
this file, in this process, and is held in a local handle. Nothing is matched by name,
no port is ever cleared, and the ports used are ones the OS just told us are free.

Run: data/bridge-venv/bin/python -m pytest \
       bridge/contract_tests/test_pidfile_port_contract.py -q
"""
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
START = ROOT / "scripts" / "start_component.sh"


def _code() -> str:
    """Executable lines only — the comments deliberately quote the banned/old shapes."""
    return "\n".join(ln for ln in START.read_text(encoding="utf-8", errors="replace")
                     .splitlines() if not ln.lstrip().startswith("#"))


# ══ A. THE FENCE ══════════════════════════════════════════════════════════════

def test_the_helper_exists():
    code = _code()
    assert "_stamp_pidfile_from_port()" in code, (
        "scripts/start_component.sh lost _stamp_pidfile_from_port — without it the "
        "pidfile is back to recording whichever attempt happened to be last (U54)")
    assert 'lsof -ti tcp:"$port" -sTCP:LISTEN' in code, (
        "the helper must ASK THE PORT; anything else is another report about the past")


def test_the_helper_never_records_a_stranger():
    """The pidfile is the one input _reap_pidfile trusts enough to signal on sight."""
    body = _code().split("_stamp_pidfile_from_port()")[1].split("\n}")[0]
    assert "_cmd_looks_like_ours" in body, (
        "the helper writes a pid into the file _reap_pidfile signals from — every "
        "candidate must pass the ownership check first (CLAUDE.md PROCESS-KILL RULE)")
    assert "kill" not in body, (
        "the helper RECORDS; it must never signal anything itself")


def test_both_runner_engines_stamp_at_readiness():
    """llama.cpp is where the retry ladder lives, so it is where the bug was — but the
    rule belongs to the FILE, not to one arm, or the next arm to grow a retry
    re-opens U54."""
    code = _code()
    assert code.count("_stamp_pidfile_from_port runner") >= 2, (
        "both runner arms (llama.cpp and MLX) must stamp the pidfile from the port")
    # …and the llama.cpp one is INSIDE the readiness poll's success branch, so every
    # attempt that reaches readiness corrects the file for itself and the retry arm
    # cannot leave a losing $! behind.
    launch = code.split("_launch_llama() {")[1].split("\n    }")[0]
    assert "_stamp_pidfile_from_port runner" in launch, (
        "the llama.cpp stamp must live inside _launch_llama, on the branch where the "
        "readiness probe succeeded — that is the one instant the answer is unambiguous")
    assert launch.index("_stamp_pidfile_from_port") < launch.index("return 0"), (
        "…and before it returns success")


def test_the_stamp_is_never_fatal():
    """An ambiguous port must cost a sentence, not a start. `set -e` is on in this
    script, so an un-guarded non-zero return would abort a runner that is UP."""
    for ln in _code().splitlines():
        if "_stamp_pidfile_from_port runner" in ln:
            assert ln.rstrip().endswith("|| true"), (
                "a failed stamp must never fail the start: " + ln.strip())


# ══ B. THE BEHAVIOUR, LIVE ════════════════════════════════════════════════════

def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


LISTENER = (
    "import socket,sys,time\n"
    "s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)\n"
    "s.bind(('127.0.0.1',int(sys.argv[1]))); s.listen(5)\n"
    "time.sleep(120)\n"
)


class _Spawned:
    """A listener this test owns outright: its own pid in a local handle, killed here.
    `where` decides whether its ARGV lands inside the tree (so the script's ownership
    rule recognises it) or outside it (so the script must refuse to record it)."""

    def __init__(self, script_path: Path, port: int, python: "str | None" = None):
        script_path.write_text(LISTENER)
        self.path = script_path
        # ⚠️ THE INTERPRETER IS PART OF THE ARGV, AND THEREFORE PART OF THE EVIDENCE.
        # Found by this test failing: `sys.executable` under the gate IS
        # data/bridge-venv/bin/python, i.e. a path INSIDE the tree, so a "stranger"
        # launched with it is recognised as ours by _cmd_looks_like_ours' path rule —
        # correctly. The foreign case therefore has to use a python that is not ours.
        self.proc = subprocess.Popen([python or sys.executable, str(script_path), str(port)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            with socket.socket() as c:
                if c.connect_ex(("127.0.0.1", port)) == 0:
                    return
            time.sleep(0.1)
        raise RuntimeError(f"scratch listener never came up on :{port}")

    def close(self):
        self.proc.kill()
        self.proc.wait(timeout=5)
        self.path.unlink(missing_ok=True)


def _stamp(comp: str, port: int) -> str:
    r = subprocess.run(["bash", str(START), "--pidfile-from-port", comp, str(port)],
                       cwd=str(ROOT), capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout + r.stderr


@pytest.mark.skipif(not START.exists(), reason="no start_component.sh in this tree")
def test_a_lying_pidfile_is_corrected_to_the_real_port_holder(tmp_path):
    """THE INCIDENT, re-staged in miniature: the file names a pid that is not serving,
    and one run of the helper makes it name the one that is."""
    port = _free_port()
    comp = "u54test"
    pf = ROOT / "data" / f"{comp}.pid"
    listener = None
    try:
        # ARGV inside the tree ⇒ _cmd_looks_like_ours' path rule recognises it, exactly
        # as it recognises data/llamacpp/build/bin/llama-server.
        listener = _Spawned(ROOT / "data" / f"{comp}_listener.py", port)
        pf.write_text("999999\n")           # the losing retry's $!, in effect
        out = _stamp(comp, port)
        assert pf.read_text().strip() == str(listener.proc.pid), (
            f"the pidfile was not corrected to the port holder\n{out}")
        assert "U54" in out, "…and it says so, rather than changing the file in silence"
        # IDEMPOTENT: a second run finds the file already true and changes nothing.
        out2 = _stamp(comp, port)
        assert pf.read_text().strip() == str(listener.proc.pid)
        assert "recorded the listener" not in out2, (
            "a pidfile that is already correct must not be rewritten (or logged) again")
    finally:
        if listener:
            listener.close()
        pf.unlink(missing_ok=True)


@pytest.mark.skipif(not START.exists(), reason="no start_component.sh in this tree")
def test_a_listener_that_is_not_ours_is_never_recorded(tmp_path):
    """⛔ THE SAFETY HALF. Debi runs standalone copies of the apps we embed. Writing a
    stranger's pid here would arm the NEXT start's _reap_pidfile against her process."""
    port = _free_port()
    comp = "u54foreign"
    pf = ROOT / "data" / f"{comp}.pid"
    listener = None
    stranger_py = next((p for p in ("/usr/bin/python3", "/usr/bin/perl")
                        if Path(p).exists()), None)
    if not stranger_py:
        pytest.skip("no interpreter outside the tree to stage a stranger with")
    try:
        # ARGV OUTSIDE the tree — interpreter AND script — ⇒ not ours by any rule.
        listener = _Spawned(tmp_path / "stranger.py", port, python=stranger_py)
        pf.write_text("999999\n")
        out = _stamp(comp, port)
        assert pf.read_text().strip() == "999999", (
            f"a foreign listener was written into our pidfile\n{out}")
        assert "nothing we own" in out, (
            "…and the refusal is a sentence, not a silent no-op")
    finally:
        if listener:
            listener.close()
        pf.unlink(missing_ok=True)


def test_the_selftest_hook_is_the_real_helper_and_nothing_else():
    """The hook above must not be a second implementation that can drift from the one
    the runner actually uses — the wire_id lesson, in shell."""
    code = _code()
    hook = code.split('if [[ "$NAME" == "--pidfile-from-port" ]]; then')[1].split("\nfi")[0]
    assert "_stamp_pidfile_from_port" in hook and "lsof" not in hook, (
        "the --pidfile-from-port hook must CALL the helper, never re-implement it")
