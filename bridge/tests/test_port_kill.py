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


# ── there is no unowned takeover path (U24/U25/U66) ───────────────────────────
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

# ── launch-record authorization, exercised ────────────────────────────────────
signalled = []


def _rec_run(argv, **kw):
    signalled.append((argv, kw))
    return _FakeDone("777\n")


_orig = app.subprocess.run
_orig_cmd = app._proc_cmdline
_orig_read_owner = app._read_ownership
_orig_signal_owned = app._ownership.signal_owned
app.subprocess.run = _rec_run
try:
    app._proc_cmdline = lambda _: "/foreign/llama-server"
    ownership_calls = []
    def _refuse(root, component, **kw):
        ownership_calls.append((root, component, kw))
        return False, "no matching claim"
    app._ownership.signal_owned = _refuse
    refused = app._kill_port_listener("6767", force=True, component="runner")
    check("an unrecorded listener is refused", len(refused) == 1)
    check("refused discovery is still LISTEN-scoped",
          any("-sTCP:LISTEN" in a for a in signalled[0][0]))
    check("refused discovery coerces the port to int", "tcp:6767" in signalled[0][0])
    check("the unrecorded listener received no signal",
          all(call[0][0] != "kill" for call in signalled))
    def _accept(root, component, **kw):
        ownership_calls.append((root, component, kw))
        return True, "signalled"
    app._read_ownership = lambda component: (777, "birth-777")
    app._ownership.signal_owned = _accept
    refused = app._kill_port_listener("6767", force=True, component="runner")
    check("the exact recorded listener is accepted", refused == [])
    check("force and exact observed pid reach the shared provenance authority",
          ownership_calls[-1][1] == "runner"
          and ownership_calls[-1][2] == {
              "expected_pid": 777, "expected_birth": "birth-777",
              "force": True, "retire": True})
finally:
    app.subprocess.run = _orig
    app._read_ownership = _orig_read_owner
    app._ownership.signal_owned = _orig_signal_owned
    app._proc_cmdline = _orig_cmd

print()
if FAILS:
    print(f"{len(FAILS)} FAILURE(S):", FAILS)
    sys.exit(1)
print("ALL PASS")
