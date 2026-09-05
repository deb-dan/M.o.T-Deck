"""aider contract — pin-bump gate for the coding-agent lane.

`build.aider_pin` is a bare COMMIT on upstream `main`, so the surface bridge/pty_aider.py
builds its launch line against can move without a release ever being cut. Every flag in
that line is load-bearing, and two of them are load-bearing for SAFETY rather than
convenience:

  --analytics-disable   mixpanel AND posthog are CORE dependencies of aider, and its
                        default behaviour enables analytics "for a random subset of
                        users". If this flag is renamed and we keep passing the old
                        spelling, argparse errors out — loudly, which is fine — but if
                        it is silently DROPPED from the parser, aider starts phoning
                        home from inside the harness. This test is the tripwire.
  --disable-playwright  without it aider can print "Install playwright?" and BLOCK ON
                        STDIN inside our PTY tab.

It also pins the two flags we must NEVER pass, from the other direction: they still
exist upstream (so their absence from our argv is a deliberate choice, not a stale
memory of a removed feature).

SKIPS CLEANLY when aider is not installed — the sandbox, and any Mac that has not run
scripts/install_aider.sh, have nothing to check.

Run: pytest bridge/contract_tests/
"""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "data" / "aider-venv" / "bin" / "aider"
PYTHON = ROOT / "data" / "aider-venv" / "bin" / "python"


def _help():
    """--help text, or None when it cannot be obtained (absent binary, or a venv built
    on another machine whose shebang interpreter does not exist here — the same
    cross-machine skip the mlx-whisper contract already carries)."""
    if not BIN.is_file():
        return None
    try:
        r = subprocess.run([str(BIN), "--help"], capture_output=True, text=True,
                           timeout=120)
    except Exception:                                            # noqa: BLE001
        return None
    text = (r.stdout or "") + (r.stderr or "")
    return text if "usage" in text.lower() else None


HELP = _help()
skip_if_absent = pytest.mark.skipif(HELP is None,
                                    reason="aider not installed (or not runnable here)")


def _assert_edit_format_parser(python):
    """Invoke Aider's actual parser without starting a session or using ``--help``."""
    sentinel = "__harness_invalid_format__"
    program = (
        "import sys; from aider.args import get_parser; "
        "parsed=get_parser([], None).parse_args(['--edit-format', sys.argv[1]]); "
        "print(parsed.edit_format)"
    )
    try:
        valid = subprocess.run([str(python), "-c", program, "whole"],
                               capture_output=True, text=True, timeout=120)
        invalid = subprocess.run([str(python), "-c", program, sentinel],
                                 capture_output=True, text=True, timeout=120)
    except Exception as exc:                                      # noqa: BLE001
        raise AssertionError(
            f"aider parser probe could not run for {python}; its --help was runnable"
        ) from exc

    valid_text = (valid.stdout or "") + (valid.stderr or "")
    assert valid.returncode == 0, valid_text
    assert valid.stdout.strip().splitlines()[-1] == "whole", valid_text

    invalid_text = (invalid.stdout or "") + (invalid.stderr or "")
    assert invalid.returncode != 0, invalid_text
    assert sentinel in invalid_text, invalid_text


@skip_if_absent
def test_launch_flags_still_exist():
    """Every flag bridge/pty_aider.py puts on the line."""
    from bridge import pty_aider as P
    for flag in ("--model", "--edit-format", *P.LOCKDOWN_FLAGS):
        assert flag in HELP, f"aider no longer documents {flag} — the launch line is stale"


@skip_if_absent
def test_edit_format_whole_is_still_offered():
    """`whole` is the only format a 4B reliably produces (recon §2.1). If upstream ever
    removes it, the lane needs a new default, not a silent fallback."""
    assert PYTHON.is_file(), "aider launcher exists but its venv python is missing"
    _assert_edit_format_parser(PYTHON)


def test_edit_format_parser_fixture_exercises_valid_and_invalid_branches(tmp_path):
    """The optional runtime probe must reject a bad format as well as accept ``whole``."""
    fixture = tmp_path / "python"
    fixture.write_text(
        "#!/bin/sh\n"
        "if [ \"$3\" = whole ]; then\n"
        "    echo whole\n"
        "    exit 0\n"
        "fi\n"
        "echo \"error: invalid edit format $3\" >&2\n"
        "exit 2\n"
    )
    fixture.chmod(0o755)

    _assert_edit_format_parser(fixture)


@skip_if_absent
def test_the_two_flags_we_refuse_still_exist():
    """Both are real upstream flags. Our not passing them is a decision — this asserts
    the decision still has something to refuse."""
    from bridge import pty_aider as P
    for flag in P.FORBIDDEN_FLAGS:
        assert flag in HELP, (
            f"{flag} is gone from aider — re-read the guardrail before changing anything")


@skip_if_absent
def test_our_argv_is_a_subset_of_the_real_parser():
    """The strongest form: build the actual launch line and check every option token in
    it against the help text."""
    from bridge import pty_aider as P
    argv = P.aider_argv(ROOT, "some-model")
    for token in argv[1:]:
        if token.startswith("--"):
            assert token in HELP, f"{token} is not a flag this aider knows"


def test_pin_is_a_commit_sha():
    """A tag would be wrong here (the newest is ~1 year old) and a branch name would be
    a moving target — the pin must be a full 40-char sha. Runs everywhere."""
    yml = (ROOT / "harness.yaml").read_text()
    m = re.search(r'^  aider_pin:\s*"([0-9a-f]{40})"\s*$', yml, re.M)
    assert m, "build.aider_pin must be a full 40-character commit sha"
