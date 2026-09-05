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

# ⚠️ THE APP LAYER IS NO LONGER ONE FILE (router/core split, 2026-08-28).
# bridge/app.py is a FACADE over bridge/core/*.py + bridge/routers/*.py, so the
# source-text assertions below read bridge/appsrc.py's assembled view of the whole
# app layer instead of one file. Read bridge/appsrc.py's header for why the
# assertions are source-text in the first place and why order is part of it.
import sys as _sys                                          # noqa: E402
_sys.path.insert(0, str(ROOT))                              # noqa: E402
from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402
BIN = ROOT / "data" / "llamacpp" / "build" / "bin" / "llama-server"
START = ROOT / "scripts" / "start_component.sh"
APP = ROOT / "bridge" / "appsrc.py"

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
    src = _APP_SOURCE
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


# ══ 3. NAMED API KEYS — the --api-key-file contract (ledger S32) ══════════════════
# MEASURED at b10662 on 2026-08-29 with a scratch llama-server on :6799 (the tester
# launched and reaped it), not read from upstream docs. The full record lives in
# bridge/routers/apikeys.py's header; these are the facts start_component.sh's runner
# arm and the API page are BUILT on, so each one is pinned at the seam it can break:
#
#   F1  --api-key-file exists; one key per line; `#` lines are comments.
#   F2  the file may contain both the built-in and named keys. Production now uses one
#       derived launch file so no secret appears in process argv.
#   F3  there is NO hot-reload: the file is read once, at argument-parse time. Adding a
#       key to a running server does not admit it; removing one does not revoke it.
#       Mint AND revoke therefore bind at the next runner start, and the panel says so.
#   F4  --metrics is off by default (GET /metrics → 501 without it).
#   F5  a --api-key-file that CANNOT BE OPENED is a FATAL ARGV ERROR — llama-server
#       prints `error while handling argument "--api-key-file"` and exits before
#       loading anything. So the launch arm must never pass the flag for a file that
#       is not there, or a missing key file takes the whole model lane down.
#
# F2 and F3 are behavioural and need a loaded model to re-measure, which a gate run
# cannot afford; what IS re-checked here every run is the surface they ride on (the
# flags, their documented format, F5's fatality) plus the seam in our own tree. If the
# --help wording for --api-key-file ever changes, RE-MEASURE F2 and F3 before shipping.
KEYFILE_DOC = "one per line"


def test_api_key_file_flag_and_its_documented_format():
    """F1. The format claim is not ours — it is the binary's own --help sentence, and
    bridge/routers/apikeys.py generates a file in exactly that shape."""
    txt = _help()
    if txt is None:
        return
    assert "--api-key-file" in txt, (
        "llama-server dropped --api-key-file. Named API keys (MOT Deck -> API) are "
        "delivered to the runner through it and there is no other way in at this pin: "
        "every minted key would silently stop working. Do not move the pin until "
        "start_component.sh has another route.")
    assert "--metrics" in txt, (
        "llama-server dropped --metrics; the API page's totals — the ONLY visibility "
        "we have into traffic from apps that call the runner directly — come from "
        "GET /metrics, which is 501 without that flag.")
    seg = txt.split("--api-key-file", 1)[1][:400]
    assert KEYFILE_DOC in seg and "comment" in seg, (
        "--api-key-file no longer documents 'one per line' with hash comments. "
        "bridge/routers/apikeys.py WRITES that format (a two-line `#` header plus one "
        "key per line) — re-measure the parser before moving the pin, and re-measure "
        "F2 (union with --api-key) and F3 (no hot-reload) while you are there.")


def test_a_missing_key_file_is_fatal_so_the_launch_arm_must_guard_it():
    """F5, MEASURED HERE rather than asserted from memory: it costs one exec and no
    model. `--api-key-file <absent>` must be rejected at argument-parse time — that is
    precisely why scripts/start_component.sh tests the file before passing the flag."""
    if not BIN.is_file():
        return
    try:
        r = subprocess.run([str(BIN), "--api-key-file",
                            "/harness-no-such-key-file.txt", "--model",
                            "/harness-no-such-model.gguf"],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return
    out = (r.stdout or "") + (r.stderr or "")
    assert "--api-key-file" in out and "failed to open" in out, (
        "llama-server no longer refuses an unreadable --api-key-file. That is a "
        "RELAXATION, not a break — but start_component.sh's guard was written for the "
        "strict behaviour, so re-read the arm before relying on the new one.")


def test_start_component_arms_the_key_file_and_the_metrics_flag():
    """The seam in OUR tree, which is the half a pin bump cannot fix for us."""
    if not START.is_file():
        return
    src = START.read_text(errors="replace")
    assert 'KEYFILE="$ROOT_ABS/data/api_keys.keys"' in src, (
        "the runner arm no longer points at data/api_keys.keys — that is the file "
        "bridge/routers/apikeys.py generates, and nothing else delivers minted keys. "
        "⚠️ It must be $ROOT_ABS (file scope, :7) and NOT $ROOT, which this script sets "
        "PER-ARM and the runner arm never sets: under `set -u` that aborts the launch "
        "before the model is touched and takes the whole model lane down (finding L2).")
    assert '"$ROOT/data/api_keys' not in src, (
        "the runner arm reads $ROOT again — see L2 above; it is unset in this arm")
    assert '--api-key-file' in src and 'grep -q -- "--api-key-file"' in src, (
        "the --api-key-file flag is no longer EVIDENCE-GATED against the binary's own "
        "--help, so a pin that drops it would kill the launch instead of degrading")
    assert 'LAUNCH_KEYFILE="$ROOT_ABS/data/.runner-api.keys"' in src
    assert 'printf \'%s\\n\' "$R_KEY"' in src, (
        "the derived launch file no longer includes the protected built-in key")
    assert 'ARGS+=(--api-key-file "$LAUNCH_KEYFILE")' in src
    assert 'rm -f "$LAUNCH_KEYFILE"' in src, (
        "the parsed launch-only secret file is no longer unlinked")
    assert 'trap _cleanup_runner_launch_key EXIT' in src, (
        "an interrupted runner launch can strand the derived built-in-key file")
    assert 'grep -q -- "--metrics"' in src, (
        "--metrics is no longer gated/passed; the API page's totals go blank")
    assert "data/api_keys.applied" in src, (
        "the launch no longer stamps the applied key-set digest. F3: there is no "
        "hot-reload, so WITHOUT that stamp the panel cannot tell a key that is live "
        "from one that needs a restart — and would imply every minted key works "
        "immediately, which is the LIE-TO-USER class this stamp exists to prevent.")
    assert 'ARGS+=(--api-key "$R_KEY")' not in src, (
        "the protected built-in key is exposed in llama-server process argv")


def test_the_route_catalogue_matches_what_this_launch_actually_enables():
    """THE API PAGE'S "not enabled" ROWS ARE A CLAIM ABOUT **OUR LAUNCH**, not upstream.

    bridge/routers/apikeys.py::ENDPOINTS tells the user /v1/embeddings and /v1/rerank
    answer 501 "because this launch does not enable them" — measured, 2026-08-29, by
    POSTing `{}` at each path on the live runner and reading 501 apart from 400 (served)
    and 404 (absent). That sentence stops being true the day somebody adds --embeddings
    to the runner arm, and it would go on being SHOWN: a page telling a user a working
    route is off is the LIE-TO-USER class, just pointing the other way.

    The catalogue cannot be re-probed on a gate run — probing needs a loaded model and
    writes one `got exception:` line into runner.log per path, which is log vomit aimed
    at the log a user reads when the model misbehaves. So what is fenced here is the
    half that lives in our tree and decides the answer."""
    ep = ROOT / "bridge" / "routers" / "apikeys.py"
    if not (ep.is_file() and START.is_file()):
        return
    src = START.read_text(errors="replace")
    cat = ep.read_text(errors="replace")
    for flag, path in (("--embeddings", "/v1/embeddings"), ("--reranking", "/v1/rerank")):
        listed_off = f'"enabled_by": "{flag}"' in cat
        passed = f"ARGS+=({flag})" in src or f'ARGS+=({flag} ' in src
        assert not (listed_off and passed), (
            f"scripts/start_component.sh now passes {flag}, so {path} IS served — but "
            f"bridge/routers/apikeys.py::ENDPOINTS still lists it as needing that flag, "
            f"and the API page still shows it off. Set `served: True` and drop "
            f"`enabled_by`, or the page lies about a route that works.")
    assert '"path": "/v1/chat/completions"' in cat, (
        "the route catalogue no longer lists /v1/chat/completions. It is the route every "
        "provider form actually calls, and the API page's Endpoints section is the only "
        "place a user is told what this address serves.")


def test_the_applied_digest_recipe_matches_on_both_sides():
    """The shell computes the stamp; the bridge compares against it. Two languages,
    one number — so it is EXECUTED here rather than eyeballed. A drift means the panel
    says 'restart the runner' forever, or (worse) stops saying it when it should."""
    import hashlib
    import subprocess as sp
    import tempfile
    keys = ["mot-bbb", "mot-aaa"]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "k"
        p.write_text("# header\n\n" + "\n".join(keys) + "\n")
        shell = sp.run(["sh", "-c",
                        "grep -v '^[[:space:]]*\\(#\\|$\\)' \"$1\" | LC_ALL=C sort "
                        "| shasum -a 256 | cut -d' ' -f1", "sh", str(p)],
                       capture_output=True, text=True).stdout.strip()
    h = hashlib.sha256()
    for k in sorted(keys):
        h.update(k.encode()); h.update(b"\n")
    assert shell == h.hexdigest(), (
        "scripts/start_component.sh's applied-digest recipe and "
        "bridge/routers/apikeys.py::digest() no longer agree "
        f"({shell} vs {h.hexdigest()})")
