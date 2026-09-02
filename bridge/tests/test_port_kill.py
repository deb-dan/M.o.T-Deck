"""Unit tests for the LISTEN-scoped port-kill helper (live-incident fix 2026-07-31:
`lsof -ti tcp:PORT` matched CLIENT sockets too, so port-clears SIGTERMed the bridge
itself via its httpx keep-alive connections). Run: python3 bridge/tests/test_port_kill.py
(from repo root)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from bridge import app  # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


# ── the takeover path: NO shell string, and still listener-scoped (U64) ───────
# `_port_kill_cmd` used to live here: a pure helper returning
# `lsof -ti tcp:N -sTCP:LISTEN | xargs kill` for the HARNESS_PORT_TAKEOVER=1 branch.
# U64 deleted it. An unowned port clear built from a shell string is the exact move that
# closed Debi's standalone Unsloth, and the no-name-kills contract bans that pipeline
# from every shell file in the tree with NO exception list — so keeping a Python copy of
# it behind an env var was that exception coming in through the back door. The override
# now walks the SAME `_port_listener_pids` list every other path walks and signals those
# pids directly: one way to find a process, one way to signal one. The properties this
# block used to assert on the string are asserted on the BEHAVIOUR below instead
# (listener scope by construction, int coercion, and the -9 escalation).
check("the unowned shell-string port clear is gone",
      not hasattr(app, "_port_kill_cmd"))

# ── _port_listener_pids (subprocess faked) ────────────────────────────────────
class _FakeDone:
    def __init__(self, stdout):
        self.stdout = stdout


calls = []


def _fake_run(argv, **kw):
    calls.append(argv)
    return _FakeDone("123\n456\n")


_orig = app.subprocess.run
app.subprocess.run = _fake_run
try:
    pids = app._port_listener_pids(8080)
    check("parses one pid per line", pids == ["123", "456"])
    check("probe itself is LISTEN-scoped", "-sTCP:LISTEN" in calls[0])
    app.subprocess.run = lambda *a, **k: _FakeDone("")
    check("free port → empty list", app._port_listener_pids(8080) == [])
    def _boom(*a, **k):
        raise OSError("no lsof")
    app.subprocess.run = _boom
    check("lsof failure degrades to empty list", app._port_listener_pids(8080) == [])
finally:
    app.subprocess.run = _orig

# ── the takeover override, exercised (U64) ────────────────────────────────────
# Same guarantees the deleted string helper carried, now observed on the call:
# LISTEN-scoped discovery, an int-coerced port, `kill -9` under force, and NO shell.
import os as _os  # noqa: E402

signalled = []


def _rec_run(argv, **kw):
    signalled.append((argv, kw))
    return _FakeDone("777\n")


_orig = app.subprocess.run
_had = _os.environ.get("HARNESS_PORT_TAKEOVER")
app.subprocess.run = _rec_run
_os.environ["HARNESS_PORT_TAKEOVER"] = "1"
try:
    refused = app._kill_port_listener("6767", force=True, component="runner")
    check("takeover refuses nothing (that is what the override is for)", refused == [])
    check("takeover discovery is LISTEN-scoped",
          any("-sTCP:LISTEN" in a for a in signalled[0][0]))
    check("takeover coerces the port to int", "tcp:6767" in signalled[0][0])
    check("takeover signals the listener pid with -9, as a real argv (no shell)",
          signalled[-1][0] == ["kill", "-9", "777"] and not signalled[-1][1].get("shell"))
finally:
    app.subprocess.run = _orig
    if _had is None:
        _os.environ.pop("HARNESS_PORT_TAKEOVER", None)
    else:
        _os.environ["HARNESS_PORT_TAKEOVER"] = _had

print()
if FAILS:
    print(f"{len(FAILS)} FAILURE(S):", FAILS)
    sys.exit(1)
print("ALL PASS")
