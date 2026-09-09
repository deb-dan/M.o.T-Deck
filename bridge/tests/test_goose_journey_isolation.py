"""Concurrent gates must never publish or reap one another's test children."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]

# Execute the actual journey, including its real PTY, ledger, grace expiry,
# takeover and resume assertions. A second bridge import at the failing transition
# reproduced sample's ship failure on 0ae3d87: "resumed session ... detached".
JOURNEY = r'''
from pathlib import Path
import subprocess, sys
root = Path(sys.argv[1])
from bridge.core import appctx
appctx.ROOT = root
from bridge import app as A
A.ROOT = root
from bridge.tests import test_goose_lane as T
from bridge.routers import goose as R
T.ROOT = root
original = R._goose_log
triggered = []
def log(message):
    original(message)
    session = T.G.current()
    if not triggered and 'session DETACHED' in message and session and session.session_id == '20260828_2':
        triggered.append(True)
        code = ('from pathlib import Path; from bridge.core import appctx; '
                'appctx.ROOT = Path(__import__("sys").argv[1]); from bridge import app')
        result = subprocess.run([sys.executable, '-c', code, str(root)],
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'reaped:' not in result.stdout, result.stdout
R._goose_log = log
T.test_routes_live()
assert triggered, 'concurrent startup was never exercised'
assert A.ROOT == appctx.ROOT == root, 'journey did not restore the caller context'
assert not T.G.busy(), 'journey left its child running'
print('concurrent journey passed')
'''


def test_parallel_journeys_survive_another_bridge_startup(tmp_path):
    """Two real route journeys share source, but each must own separate runtime state."""
    manifest = ("bridge:\n  port: 8700\nrunner:\n  port: 1\n"
                "  endpoint: http://127.0.0.1:1/v1\ncomponents: {}\n")
    (tmp_path / "motdeck.yaml").write_text(manifest)
    # A real read_claim creates its persistent advisory-lock file even with no
    # child. Establish that normal startup state before comparing shared files.
    from bridge.core import ownership
    assert ownership.read_claim(tmp_path, "goose") is None
    before = {path.relative_to(tmp_path): path.read_bytes()
              for path in tmp_path.rglob("*") if path.is_file()}

    def run():
        return subprocess.run([sys.executable, "-c", JOURNEY, str(tmp_path)],
                              cwd=ROOT, capture_output=True, text=True, timeout=60)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        results = [future.result() for future in futures]
    for result in results:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "concurrent journey passed" in result.stdout
    # Both gates and their competing startup sweeps must leave shared state alone.
    after = {path.relative_to(tmp_path): path.read_bytes()
             for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before
