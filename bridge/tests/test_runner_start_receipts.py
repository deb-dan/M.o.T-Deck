"""Execute the actual shell launch function in its conditional-call context."""
import hashlib
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("failure", ["record", "identity", "none"])
def test_launch_requires_ownership_and_stamps_the_supplied_keys(tmp_path, failure):
    source = (ROOT / "scripts/start_component.sh").read_text()
    start = source.index("    _launch_llama() {")
    end = source.index("\n    up=0", start)
    launch = source[start:end]
    (tmp_path / "data" / "logs").mkdir(parents=True)
    (tmp_path / "launch.keys").write_text("built-in-test-key\nold-named-test-key\n")
    (tmp_path / "named.keys").write_text("old-named-test-key\n")
    script = r'''
set -euo pipefail
BIN=unused
R_KEY=built-in-test-key
R_PORT=1
ROOT_ABS="$PWD"
KEYFILE_ARMED=1
KEYFILE="$PWD/named.keys"
LAUNCH_KEYFILE="$PWD/launch.keys"
_detached() { :; }
_record_child() {
  wait "$2"
  [[ "$failure" != record ]] || return 1
  # A mint can complete after the launch input has already been constructed.
  printf '%s\n' newer-named-test-key > "$KEYFILE"
}
_stamp_pidfile_from_port() { [[ "$failure" != identity ]]; }
curl() { return 0; }
sleep() { :; }
'''
    script += launch + '\nif _launch_llama; then echo READY; else echo REFUSED; fi\n'
    result = subprocess.run(["bash", "-c", 'failure="$1"\n' + script, "test", failure],
                            cwd=tmp_path, capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ("READY" if failure == "none" else "REFUSED")
    if failure == "none":
        expected = hashlib.sha256(b"old-named-test-key\n").hexdigest()
        assert (tmp_path / "data" / "api_keys.applied").read_text().strip() == expected
    else:
        assert not (tmp_path / "data" / "api_keys.applied").exists()
