"""llama-server contract — pin-bump gate for the RUNNER lane.

Sibling of test_llama_tts_contract.py: both binaries ride `runner.llamacpp_pin`, and
both have already changed underneath us. This file guards the two things that actually
break when that pin moves.

── 1. The UNGATED argv ───────────────────────────────────────────────────────────
scripts/start_component.sh builds the runner's command line in two halves. Most of it
is EVIDENCE-GATED (each optional flag is `grep`ed out of the binary's own --help before
being added, so a removed flag silently drops instead of killing the launch). But the
base ARGS block is passed UNCONDITIONALLY:

    --no-context-shift --host --port --alias --ctx-size --no-cont-batching
    --cache-ram --fit --model --parallel        (+ --mmproj for a vision model)

If upstream renames or drops ANY of those, llama-server exits on argv parsing and the
whole model lane is down with nothing loaded. That must trip here, at the bump, not on
Debi's next chat turn.

── 2. The api-key'd probe (the 2026-08-28 b10427 → b10662 regression) ────────────
`GET /v1/models` used to be exempt from `--api-key` and is not any more. MEASURED, by
running both binaries model-less with `--api-key testkey`:

    b10427   GET /v1/models with no key → 200
    b10662   GET /v1/models with no key → 401

bridge/app.py::_runner_loaded_id is THE single source of truth for "what is live"
(_reconcile_live keys off it, and /api/status + the Models pane both key off that). It
sent no Authorization header, so at b10662 it 401'd on every poll, returned None, and
Mission Control reported `running: false, loaded: false` for a runner that was serving
generations at 14 tok/s — a LIE-TO-USER, plus one "unauthorized: Invalid API Key" in
data/logs/runner.log per status poll. The invariant is asserted on the side we control
(bridge/app.py), so it holds at this pin and at every future one regardless of which
way upstream flips the exemption.

SKIPS CLEANLY when the binary is absent (the sandbox, or a machine that has not run
scripts/install_llamacpp.sh). Part 2 needs no binary at all.

Run: pytest bridge/contract_tests/
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "data" / "llamacpp" / "build" / "bin" / "llama-server"
START = ROOT / "scripts" / "start_component.sh"
APP = ROOT / "bridge" / "app.py"

# The base ARGS block in start_component.sh's runner branch — passed with NO --help
# gate, so each one is load-bearing on its own.
UNGATED = (
    "--no-context-shift", "--host", "--port", "--alias", "--ctx-size",
    "--no-cont-batching", "--cache-ram", "--fit", "--model", "--parallel",
    "--mmproj",
)


def _help():
    """--help text, or None when it cannot be obtained — absent, not executable, or
    (in a Linux build sandbox) a Mach-O we cannot exec. Same shape as the tts test."""
    if not BIN.is_file():
        return None
    try:
        r = subprocess.run([str(BIN), "--help"], capture_output=True, text=True,
                           timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return (r.stdout or "") + (r.stderr or "")


def test_ungated_runner_flags_still_exist():
    txt = _help()
    if txt is None:
        return  # binary absent / unexecutable here — nothing to gate
    for flag in UNGATED:
        assert flag in txt, (
            f"llama-server no longer documents {flag}, and start_component.sh passes "
            "it UNCONDITIONALLY (the base ARGS block, not the --help-gated floors) — "
            "the runner would exit on argv parsing and the model lane would be down "
            "with nothing loaded. Fix start_component.sh before moving the pin.")


def test_flags_the_gated_floors_assume_are_still_named_the_same():
    """The gated floors degrade silently by design, so a rename there is not fatal —
    but it IS a capability loss the user never sees. Assert the ones whose absence
    would change behaviour we advertise: the api-key, the repetition pair, and the
    speculative-decoding entry point (with its draft-mtp value)."""
    txt = _help()
    if txt is None:
        return
    for flag in ("--api-key", "--repeat-penalty", "--repeat-last-n", "--spec-type"):
        assert flag in txt, (
            f"llama-server dropped {flag}; start_component.sh gates on it, so the "
            "launch still succeeds — but the capability quietly disappears. Decide "
            "deliberately, do not discover it later.")
    assert "draft-mtp" in txt, (
        "--spec-type no longer offers draft-mtp — the MTP speculative-decoding path "
        "in start_component.sh (spec_mtp: auto) would degrade to no acceleration")


def test_runner_probe_sends_the_api_key():
    """bridge/app.py::_runner_loaded_id MUST authenticate. See the docstring above:
    /v1/models became api-key-guarded at b10662 and the keyless probe made Mission
    Control claim nothing was loaded while the runner was generating."""
    src = APP.read_text(errors="replace")
    m = re.search(r"def _runner_loaded_id\(.*?\n(?=\n\ndef |\n\n# )", src, re.S)
    assert m, ("_runner_loaded_id is gone from bridge/app.py — this test can no "
               "longer see the seam it guards; re-point it at the new probe")
    # Assert against the CODE, not the prose: this function's docstring explains the
    # regression in words, and a test that a docstring can satisfy is not a test.
    body = m.group(0)
    body = re.sub(r'""".*?"""', "", body, flags=re.S)
    assert "Authorization" in body and "Bearer" in body, (
        "the runner live-probe sends no Authorization header. GET /v1/models is "
        "api-key-guarded from llama.cpp b10662 onward and start_component.sh always "
        "passes --api-key when the binary supports it, so a keyless probe 401s on "
        "every poll, _reconcile_live reads that as 'nothing is loaded', and Mission "
        "Control shows an idle runner while it is serving tokens.")
    assert "api_key" in body, (
        "the probe hard-codes a bearer instead of reading runner.api_key (or "
        "aux.api_key) from harness.yaml — a key change in the manifest would break "
        "the live-model probe again")


def test_start_component_ungated_block_has_not_grown_silently():
    """A guard on the GUARD: if someone adds a new flag to the unconditional ARGS
    block without adding it to UNGATED above, test_ungated_runner_flags_still_exist
    stops covering the whole launch line. This fails loudly when they diverge."""
    if not START.is_file():
        return
    src = START.read_text(errors="replace")
    m = re.search(r"\n\s*ARGS=\((.*?)\)\n", src, re.S)
    assert m, ("the runner branch's ARGS=( … ) block is gone from "
               "scripts/start_component.sh — re-point this test at the new launch line")
    found = set(re.findall(r"(--[a-z][a-z0-9-]*)", m.group(1)))
    unknown = found - set(UNGATED)
    assert not unknown, (
        "scripts/start_component.sh now passes these UNGATED runner flags that this "
        f"contract does not check: {sorted(unknown)}. Add them to UNGATED so a pin "
        "bump that removes one still trips here.")
