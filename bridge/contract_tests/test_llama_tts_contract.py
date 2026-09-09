"""llama-tts contract — pin-bump gate for MOT Deck-native voice capability.

`llama-tts` ships in the SAME macos-arm64 tarball as `llama-server`, so it rides
`runner.llamacpp_pin` for free — and it therefore changes whenever that pin moves.
It already changed once underneath us: OuteTTS + a WavTokenizer vocoder (`-mv`) was
the tool's shape in the docs the spec was drafted from, and at our pin (b10295) it is
the rewritten mtmd tool taking a backbone plus a multimodal projector (`-mm`).
bridge/voice.py::tts_argv builds exactly the b10295 argv, so a future pin that
reverts or renames those flags must trip HERE, loudly, instead of silently producing
zero-byte wavs (both engines exit 0 on failure — see bridge/tests/test_voice_tts.py).

Verified against the real binary on sample's Mac, 2026-08-07:
    llama-tts -m backbone.gguf -mm mmproj.gguf -p "text to speak" -o output.wav
    -mm, --mmproj FILE            multimodal projector
    -o,  --output, --output-file FNAME   (default: 'output.wav')
    --tts-lang FNAME              ISO 639-1
    --tts-speaker-file FNAME
  (no --voice, no -mv/--vocoder-model)

SKIPS CLEANLY when the binary is absent — the sandbox and any machine that has not
run scripts/install_llamacpp.sh have nothing to check.

Run: pytest bridge/contract_tests/
"""
import subprocess
from functools import lru_cache

import pytest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "data" / "llamacpp" / "build" / "bin" / "llama-tts"


def _present() -> bool:
    return BIN.is_file()


@lru_cache(maxsize=1)
def _help():
    """--help text, or None when it cannot be obtained — the binary is absent, not
    executable, or (in the Linux build sandbox) is a Mach-O we cannot exec even
    though the mounted repo carries it. The gate is real on the Mac, where every
    pin-bump actually happens; it must never fail merely for being run elsewhere.

    The tool prints usage to stdout and/or stderr and may exit non-zero doing it, so
    both streams are joined and the return code is ignored."""
    if not _present():
        return None
    try:
        p = subprocess.run([str(BIN), "--help"], capture_output=True, text=True,
                           timeout=60, cwd=str(ROOT))
    except (OSError, subprocess.SubprocessError):
        return None       # wrong architecture / not executable here
    out = (p.stdout or "") + (p.stderr or "")
    return out or None


def test_pin_is_a_tagged_llamacpp_release():
    """Always runs: the pin contract is ours, not upstream's."""
    c = yaml.safe_load((ROOT / "motdeck.yaml").read_text())
    pin = str(((c.get("runner") or {}).get("llamacpp_pin") or "")).strip()
    assert pin.startswith("b") and pin[1:].isdigit(), (
        f"runner.llamacpp_pin {pin!r} is not a bNNNN release tag — llama-tts rides "
        f"this same pin, so it must never track a branch")


def test_voice_block_exists():
    """Always runs: bridge/voice.py reads these two slots."""
    c = yaml.safe_load((ROOT / "motdeck.yaml").read_text())
    v = c.get("voice")
    assert isinstance(v, dict), "the top-level `voice:` block vanished from motdeck.yaml"
    assert "tts_model" in v and "stt_model" in v, (
        "voice.tts_model / voice.stt_model are the registry ids the bridge writes")


def test_llama_tts_ships_with_the_pinned_build():
    """Informational when absent (install_llamacpp.sh not run), asserted when the
    llama.cpp install exists at all — a pin whose tarball DROPPED llama-tts would
    otherwise only surface as a 500 at speak time."""
    server = ROOT / "data" / "llamacpp" / "build" / "bin" / "llama-server"
    if not server.is_file():
        return   # nothing installed — nothing to gate
    assert BIN.is_file(), (
        "data/llamacpp/build/bin/llama-tts is missing while llama-server is present — "
        "the pinned macos-arm64 tarball no longer ships the TTS tool, so the "
        "MOT Deck-native voice capability has no llama.cpp engine")


def test_mmproj_flag_present():
    h = _help()
    if h is None:
        pytest.skip("the installed engine help is unavailable on this machine")
    assert "--mmproj" in h, (
        "llama-tts no longer advertises --mmproj — bridge/voice.py passes the "
        "projector as `-mm <file>`; re-run Phase-0 recon before bumping the pin")


def test_output_flag_present():
    h = _help()
    if h is None:
        pytest.skip("the installed engine help is unavailable on this machine")
    assert ("--output" in h) or ("-o," in h) or ("-o " in h), (
        "llama-tts no longer advertises an output-file flag — bridge/voice.py writes "
        "the wav via `-o <path>` and checks that exact path for non-emptiness")


def test_tts_lang_flag_present():
    h = _help()
    if h is None:
        pytest.skip("the installed engine help is unavailable on this machine")
    assert "--tts-lang" in h, (
        "llama-tts dropped --tts-lang — bridge/voice.py adds it for registry entries "
        "carrying a `lang` field")


def test_vocoder_flag_is_absent():
    """The inverse gate. If `-mv`/`--vocoder-model` ever comes BACK, the tool has
    changed shape again and tts_argv's `-m/-mm` pair is no longer the right call."""
    h = _help()
    if h is None:
        pytest.skip("the installed engine help is unavailable on this machine")
    assert "--vocoder-model" not in h, (
        "llama-tts advertises --vocoder-model again — the OuteTTS+vocoder shape is "
        "back and bridge/voice.py's `-m backbone -mm mmproj` argv needs re-recon")


def test_no_voice_flag():
    """Pins the honest limit surfaced to sample: voice PICKING is MLX-only."""
    h = _help()
    if h is None:
        pytest.skip("the installed engine help is unavailable on this machine")
    assert "--voice " not in h and "--voice\n" not in h, (
        "llama-tts now has a --voice flag — the panel's 'voice selection is MLX-only' "
        "limitation can be lifted (and tts_argv should pass it)")
