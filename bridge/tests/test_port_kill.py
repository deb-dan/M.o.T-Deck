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


# ── _port_kill_cmd (pure) ──────────────────────────────────────────────────────
c = app._port_kill_cmd(7860)
check("listener scope present", "-sTCP:LISTEN" in c)
check("scope attaches to the lsof selector", "lsof -ti tcp:7860 -sTCP:LISTEN" in c)
check("default is plain kill (SIGTERM)", "| xargs kill 2>/dev/null" in c)
check("no -9 without force", "-9" not in c)

cf = app._port_kill_cmd(6767, force=True)
check("force uses kill -9", "| xargs kill -9 2>/dev/null" in cf)
check("force keeps listener scope", "lsof -ti tcp:6767 -sTCP:LISTEN" in cf)

check("port coerced to int (no injection via str port)",
      "lsof -ti tcp:9119 -sTCP:LISTEN" in app._port_kill_cmd("9119"))
try:
    app._port_kill_cmd("9119; rm -rf /")
    check("non-numeric port rejected", False)
except (ValueError, TypeError):
    check("non-numeric port rejected", True)

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

print()
if FAILS:
    print(f"{len(FAILS)} FAILURE(S):", FAILS)
    sys.exit(1)
print("ALL PASS")
