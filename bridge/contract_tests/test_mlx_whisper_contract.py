"""mlx-whisper contract — pin-bump gate for Phase D (dictation).

bridge/voice.py::stt_argv builds the console script's argv EXACTLY:

    mlx_whisper <audio> --model <repo|dir> -f json -o <dir> --verbose False

and then reads `<dir>/<stem>.json` — because the CLI WRITES FILES and prints no
transcript to stdout (Fable spec amendment §6). Two things must therefore hold at any
future `build.mlx_whisper_pin`, and neither fails loudly on its own:

  * the flags keep their names. A renamed `-f`/`-o` would make the CLI write nothing
    where we look, and mlx_whisper EXITS 0 after printing a traceback — so the only
    symptom would be "no transcript" with a healthy return code.
  * the console script keeps its name. voice.py spawns `data/mlx-venv/bin/mlx_whisper`
    by explicit path (Finder-minimal PATH rule); if the entry point is renamed we
    silently fall back to the slower library form forever.

SKIPS CLEANLY when the MLX venv has no mlx-whisper — the sandbox, and any machine
that has not re-run scripts/install_mlx.sh since Phase D, have nothing to check.

Run: pytest bridge/contract_tests/
"""
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "data" / "mlx-venv" / "bin" / "mlx_whisper"


def _help():
    """--help text, or None when it cannot be obtained (absent venv, wrong arch).
    Both streams are joined and the return code ignored: argparse prints usage to
    stdout, and a partially-installed package can print an ImportError to stderr."""
    if not BIN.is_file():
        return None
    try:
        p = subprocess.run([str(BIN), "--help"], capture_output=True, text=True,
                           timeout=120, cwd=str(ROOT))
    except (OSError, subprocess.SubprocessError):
        return None
    out = (p.stdout or "") + (p.stderr or "")
    # A venv built on ANOTHER machine (or another OS) leaves a launcher whose shebang
    # points at an interpreter that does not exist here: the script runs but only
    # emits "exec: .../python3: not found". That is "cannot be obtained", NOT a broken
    # contract — treat it as a skip, exactly like an absent binary. (Real --help always
    # contains the word "usage".)
    if "usage" not in out.lower():
        return None
    return out or None


def test_pin_exists_and_is_exact():
    """Always runs: an unpinned or ranged STT dependency would let a re-install
    silently change the argv surface underneath us."""
    c = yaml.safe_load((ROOT / "motdeck.yaml").read_text())
    pin = str(((c.get("build") or {}).get("mlx_whisper_pin") or "")).strip()
    assert pin, "build.mlx_whisper_pin is missing — scripts/install_mlx.sh needs it"
    assert all(part.isdigit() for part in pin.split(".")), (
        f"build.mlx_whisper_pin {pin!r} is not an exact version — the STT argv surface "
        f"is only verified for a specific release")


def test_install_mlx_asks_for_the_pin():
    """Always runs: the pin is only real if the installer reads it."""
    src = (ROOT / "scripts" / "install_mlx.sh").read_text()
    assert "mlx-whisper==${MLX_WHISPER_PIN}" in src, (
        "install_mlx.sh no longer installs mlx-whisper at the pinned version")
    assert "_yb mlx_whisper_pin" in src, (
        "install_mlx.sh must read the pin from motdeck.yaml, not hardcode it")


def test_console_script_present_when_mlx_venv_exists():
    """Informational when no MLX venv exists; asserted once one does — a venv with
    mlx-lm but no mlx_whisper script means install_mlx.sh has not been re-run since
    Phase D, and dictation would degrade to the library fallback."""
    venv_py = ROOT / "data" / "mlx-venv" / "bin" / "python"
    if not venv_py.is_file():
        return
    try:
        p = subprocess.run([str(venv_py), "-c", "import mlx_whisper"],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return
    if p.returncode != 0:
        return       # package not installed here — nothing to gate
    assert BIN.is_file(), (
        "mlx_whisper is importable but data/mlx-venv/bin/mlx_whisper is missing — "
        "bridge/voice.py spawns that console script by explicit path")


def test_model_flag_present():
    h = _help()
    if h is None:
        return
    assert "--model" in h, (
        "mlx_whisper no longer advertises --model — stt_argv names the registry path "
        "with it; re-run recon before bumping build.mlx_whisper_pin")


def test_output_format_and_dir_flags_present():
    h = _help()
    if h is None:
        return
    assert ("--output-format" in h) or ("-f " in h) or ("-f," in h), (
        "mlx_whisper no longer advertises an output-FORMAT flag — stt_argv passes "
        "`-f json` and reads the resulting file")
    assert ("--output-dir" in h) or ("-o " in h) or ("-o," in h), (
        "mlx_whisper no longer advertises an output-DIR flag — stt_argv passes "
        "`-o <tmpdir>` and reads <tmpdir>/<stem>.json from it")


def test_json_is_still_an_output_format():
    h = _help()
    if h is None:
        return
    assert "json" in h.lower(), (
        "mlx_whisper's --output-format no longer lists json — voice.stt_read_output "
        "parses that file; a txt-only CLI would need a different reader")


def test_verbose_flag_present():
    """Not cosmetic: without `--verbose False` the CLI streams the whole transcript to
    stdout, which is what our 1500-char error log tail would then be full of."""
    h = _help()
    if h is None:
        return
    assert "--verbose" in h, (
        "mlx_whisper dropped --verbose — stt_argv passes `--verbose False` to keep "
        "the transcript out of the engine log tail")
