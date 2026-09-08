"""mlx-audio STT contract — pin-bump gate for the SECOND speech-to-text engine.

bridge/voice.py::stt_argv builds this console script's argv EXACTLY:

    mlx_audio.stt.generate --model <dir> --audio <file>
                           --output-path <dir>/<stem> --format json

and then reads `<dir>/<stem>.json`, because `save_as_json()` writes
f"{output_path}.json" — `--output-path` is a PREFIX, not a directory. That single
fact is what lets voice.stt_read_output stay byte-identical for both engines, and it
is exactly the kind of thing an upstream release can change without anyone noticing:
mlx-audio would simply write somewhere else and we would read "no transcript".

Four things must hold at any future `build.mlx_audio_pin`, none of which fails loudly
on its own:

  * `--model`, `--audio`, `--output-path`, `--format` keep their names. `--audio` in
    particular is a FLAG here where mlx_whisper takes the file positionally, so the
    two CLIs are NOT interchangeable and a copy-paste between the branches would
    silently produce a command that transcribes nothing.
  * json is still an output format (the default is `txt`, which our reader cannot
    parse — passing --format is not optional).
  * the console script keeps its name; voice.py spawns it by explicit path under the
    Finder-minimal-PATH rule.
  * ⚠️ UNVERIFIED and NOT gated here: whether this CLI honours the exit-0-on-failure
    invariant the whisper path relies on. It is a different CLI from a different
    package and could plausibly exit nonzero. voice.stt_transcribe therefore treats
    an EMPTY transcript as the failure signal regardless of the return code, which is
    correct in both worlds — see the comment there.

SKIPS CLEANLY when the MLX venv has no mlx-audio, or when its launcher's shebang
points at another machine's interpreter (the sandbox reads a Mac-built venv).

Run: pytest bridge/contract_tests/
"""
import subprocess
from functools import lru_cache

import pytest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "data" / "mlx-venv" / "bin" / "mlx_audio.stt.generate"


@lru_cache(maxsize=1)
def _help():
    """--help text, or None when it cannot be obtained. Same skip discipline as
    test_mlx_whisper_contract: real --help always contains "usage"."""
    if not BIN.is_file():
        return None
    try:
        p = subprocess.run([str(BIN), "--help"], capture_output=True, text=True,
                           timeout=180, cwd=str(ROOT))
    except (OSError, subprocess.SubprocessError):
        return None
    out = (p.stdout or "") + (p.stderr or "")
    if "usage" not in out.lower():
        return None
    return out or None


def test_pin_exists_and_is_exact():
    """Always runs. The whole case for this engine is "no new pin" — it rides the
    mlx-audio version the TTS half already pins — so that pin must stay exact."""
    c = yaml.safe_load((ROOT / "motdeck.yaml").read_text())
    pin = str(((c.get("build") or {}).get("mlx_audio_pin") or "")).strip()
    assert pin, "build.mlx_audio_pin is missing — the STT engine rides it too now"
    assert all(part.isdigit() for part in pin.split(".")), (
        f"build.mlx_audio_pin {pin!r} is not an exact version — the STT argv surface "
        f"is only verified for a specific release")


def test_console_script_present_when_mlx_audio_is_installed():
    """A venv with mlx_audio but no `mlx_audio.stt.generate` script means the entry
    point was renamed — voice.py spawns it by explicit path and would fall back to
    the `-m` form forever without saying so."""
    venv_py = ROOT / "data" / "mlx-venv" / "bin" / "python"
    if not venv_py.is_file():
        return
    try:
        p = subprocess.run([str(venv_py), "-c", "import mlx_audio.stt.generate"],
                           capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError):
        return
    if p.returncode != 0:
        return       # not installed / wrong arch — nothing to gate
    assert BIN.is_file(), (
        "mlx_audio.stt.generate is importable but data/mlx-venv/bin/"
        "mlx_audio.stt.generate is missing — bridge/voice.py spawns that console "
        "script by explicit path")


def test_model_and_audio_flags_present():
    h = _help()
    if h is None:
        pytest.skip("the installed engine help is unavailable on this machine")
    assert "--model" in h, (
        "mlx_audio.stt.generate no longer advertises --model — stt_argv names the "
        "registry path with it")
    assert "--audio" in h, (
        "mlx_audio.stt.generate no longer advertises --audio — this CLI takes the "
        "audio as a FLAG (mlx_whisper takes it positionally); stt_argv's branches "
        "are not interchangeable")


def test_output_path_flag_present():
    h = _help()
    if h is None:
        pytest.skip("the installed engine help is unavailable on this machine")
    assert "--output-path" in h, (
        "mlx_audio.stt.generate no longer advertises --output-path — stt_argv passes "
        "<tmpdir>/<stem> as a PREFIX and voice.stt_read_output reads <stem>.json")


def test_json_is_still_an_output_format():
    h = _help()
    if h is None:
        pytest.skip("the installed engine help is unavailable on this machine")
    assert "--format" in h, (
        "mlx_audio.stt.generate dropped --format — its DEFAULT is txt, which "
        "voice.stt_read_output cannot parse, so passing it is mandatory")
    assert "json" in h.lower(), (
        "mlx_audio.stt.generate's --format no longer lists json")


def test_parakeet_family_ships_in_the_pinned_package():
    """The adoption case rests on Parakeet already being in the pinned mlx-audio. If
    a bump ever drops the family, the Audio-tab starter would download a 2.5 GB model
    nothing can load."""
    d = ROOT / "data" / "mlx-venv" / "lib"
    if not d.is_dir():
        return
    hits = list(d.glob("python*/site-packages/mlx_audio/stt/models/parakeet"))
    if not hits:
        pkg = list(d.glob("python*/site-packages/mlx_audio"))
        if not pkg:
            return          # mlx-audio not installed here — nothing to gate
    assert hits, (
        "mlx_audio/stt/models/parakeet/ is gone from the pinned mlx-audio — the "
        "stt-mlx-audio format has no engine behind it any more")
