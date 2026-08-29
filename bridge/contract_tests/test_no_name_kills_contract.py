"""NO-KILL-BY-NAME CONTRACT — the PROCESS-KILL RULE (CLAUDE.md) pinned mechanically.

The rule, in Debi's words: *agents/builders and the harness may terminate ONLY
processes they themselves spawned, tracked by their own pidfile/child handle,
identity-verified (full command line) before the kill. NEVER pkill/killall by name or
pattern; never kill whatever holds a port.* She runs STANDALONE copies of the very apps
we embed, so a name match is not identity — it is her work closing without warning.

Three incidents wrote this file:
  · 2026-08-28  her standalone Unsloth, killed by our :8888 port clear
  · 2026-08-29  goose Desktop, same class
  · 2026-08-29  U19: `pkill -f "hermes (dashboard|serve)"` AND
                `hermes dashboard --stop` (hermes_cli/dashboard_procs.py::
                _kill_stale_dashboard_processes scans the whole machine for any
                `hermes dashboard|serve` and SIGTERM/SIGKILLs it) sat in the hermes
                Start arm — two name-kills aimed straight at her standalone Hermes.

What this file fences, forever:

  1. NO shell script under scripts/ (or guards/) may contain pkill / killall / pgrep /
     taskkill, or pipe lsof into kill, or delegate the kill to a vendor CLI that stops
     "any" instance by name.
  2. The specific sites U19 replaced are asserted individually, so a revert is a red
     test rather than a silent regression:
       · start_component.sh has _reap_pidfile (pidfile-scoped, identity re-verified)
       · the hermes arm reaps by pidfile and then ownership-checks :9119
       · `_cmd_looks_like_ours hermes` carries NO name signature (path evidence only)
       · ship.sh quits the app by Apple Event + bundle path, and refuses a foreign
         :8700 holder instead of clearing it
       · stop.sh routes every stop through the --owner-check seam
  3. U21's sibling class (a readiness poll that lies about a healthy runner): every
     /v1/models poll against the RUNNER port carries the Authorization header that
     llama.cpp b10662 made mandatory.

The banned commands are NAMED in the scripts' comments on purpose — a fix nobody can
read gets re-introduced — so every grep here reads EXECUTABLE lines only.

Run: data/bridge-venv/bin/python -m pytest \
       bridge/contract_tests/test_no_name_kills_contract.py -q
"""
import os
import re

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
GUARDS = os.path.join(ROOT, "guards")

START = os.path.join(SCRIPTS, "start_component.sh")
SHIP = os.path.join(SCRIPTS, "ship.sh")
STOP = os.path.join(SCRIPTS, "stop.sh")


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _code(path: str) -> str:
    """Executable lines only — comments may (and should) name what was banned."""
    return "\n".join(ln for ln in _read(path).splitlines()
                     if not ln.lstrip().startswith("#"))


def _shell_files():
    out = []
    for base, _dirs, files in os.walk(SCRIPTS):
        if "__pycache__" in base:
            continue
        out += [os.path.join(base, f) for f in files if f.endswith(".sh")]
    for base, _dirs, files in os.walk(GUARDS):
        if "__pycache__" in base:
            continue
        for f in files:
            p = os.path.join(base, f)
            if f.endswith(".sh") or _read(p)[:2] == "#!":
                out.append(p)
    return sorted(out)


SHELL = _shell_files()


# ── 1. the class: no kill by name anywhere in the shell layer ─────────────────
# Each entry: (regex, what it is). All matched against executable lines only.
BANNED = [
    (r"\bpkill\b", "pkill — kills by name/pattern, not identity"),
    (r"\bkillall\b", "killall — kills by name"),
    (r"\bpgrep\b", "pgrep — the same name match, one pipe from a kill"),
    (r"\btaskkill\b", "taskkill — the Windows spelling of the same thing"),
    (r"lsof[^\n]*\|[^\n]*\bkill\b", "lsof piped into kill — a port clear with no owner check"),
    (r"\bkill\b[^\n]*\$\(\s*pgrep", "kill $(pgrep ...) — name match with extra steps"),
    (r"hermes\s+(dashboard|serve)\s+--stop",
     "hermes --stop — the vendor CLI stops EVERY hermes on the machine"),
]


@pytest.mark.parametrize("path", SHELL, ids=[os.path.relpath(p, ROOT) for p in SHELL])
def test_no_kill_by_name_in_shell_layer(path):
    code = _code(path)
    hits = []
    for pat, why in BANNED:
        for m in re.finditer(pat, code):
            line = code[:m.start()].count("\n") + 1
            hits.append(f"{os.path.relpath(path, ROOT)} (code line {line}): "
                        f"{m.group(0)!r} — {why}")
    assert not hits, (
        "PROCESS-KILL RULE violation (CLAUDE.md): terminate only what we spawned,\n"
        "identity-verified. Use _reap_pidfile (our pidfile) or _clear_port (ownership\n"
        "checked; a stranger's port REFUSES the start). Found:\n  " + "\n  ".join(hits))


def test_every_kill_is_reachable_only_through_a_verified_path():
    """Any `kill` in start_component.sh lives in _reap_pidfile or _clear_port —
    the only two places that hold the ownership evidence."""
    code = _code(START)
    lines = [(i + 1, ln) for i, ln in enumerate(code.splitlines())
             if re.search(r"^\s*kill\s", ln) and "kill -0" not in ln]
    # every signalling site uses the verified $pid variable, never a pattern/name
    for num, ln in lines:
        assert re.search(r'kill\s+("\$sig"|-0|"\$pid")', ln), \
            f"start_component.sh:{num}: unverified kill: {ln.strip()}"


# ── 2. the replaced sites, asserted one by one ───────────────────────────────
def test_reap_pidfile_exists_and_verifies_before_signalling():
    code = _code(START)
    assert "_reap_pidfile() {" in code, "the pidfile-scoped reaper is gone"
    body = code.split("_reap_pidfile() {", 1)[1].split("\n_clear_port", 1)[0]
    assert "_cmd_looks_like_ours" in body, "reaping without an identity check"
    assert body.index("_cmd_looks_like_ours") < body.index('kill "$sig"'), \
        "the identity check must come BEFORE the signal"
    assert "kill -0" in body, "a dead/absent pid must be detected, not signalled blindly"


def test_hermes_arm_reaps_by_pidfile_then_ownership_checks_the_port():
    code = _code(START)
    assert "_reap_pidfile hermes force" in code
    assert '_clear_port "$PORT" hermes force' in code
    assert code.index("_reap_pidfile hermes force") < code.index('_clear_port "$PORT" hermes force')


def test_hermes_ownership_has_no_name_signature():
    """U19's core: 'hermes dashboard' in a command line must NEVER prove ownership —
    that string IS Debi's standalone Hermes. Path evidence only."""
    code = _code(START)
    assert '*"hermes dashboard"*' not in code and '*"hermes serve"*' not in code, \
        "the hermes NAME signature is back — it matches the standalone app it must protect"
    assert '*"/data/hermes-venv/"*' in code, \
        "hermes ownership must be proven by the harness venv PATH"


def test_runner_arms_reap_by_pidfile_not_by_engine_pattern():
    code = _code(START)
    assert code.count("_reap_pidfile runner force") == 3, \
        "the three runner cleanup sites (llamacpp, spec-retry, mlx) must all be pidfile-scoped"
    assert "llama-server.*--port" not in code, "the engine-pattern pkill is back"
    assert "mlx_lm.server.*--port" not in code, "the engine-pattern pkill is back"


def test_ship_quits_the_app_by_apple_event_and_verified_bundle_path():
    code = _code(SHIP)
    assert "osascript -e 'quit app \"Harness\"'" in code, \
        "ship.sh must ASK the app to quit, not signal a process called Harness"
    assert '$APP/Contents/MacOS/' in code, \
        "a surviving app pid must be identified by its bundle path"
    assert "REFUSING to ship" in code and "not this harness" in code, \
        "a foreign :8700 holder must stop the ship, not be killed"


def test_stop_routes_every_stop_through_the_owner_check_seam():
    code = _code(STOP)
    assert "--owner-check" in code, \
        "stop.sh must reuse start_component.sh's single ownership rule"
    assert "-sTCP:LISTEN" in code, "the bridge stop must be listener-scoped"
    assert "left alone" in code, "a foreign bridge-port holder must be reported, not killed"


def test_owner_check_seam_answers_correctly_live():
    """Executed, not grepped: the shell helper itself, on the three cases that matter."""
    import subprocess

    def owns(comp, cmd):
        return subprocess.run(["bash", START, "--owner-check", comp, cmd],
                              capture_output=True, text=True, cwd=ROOT).returncode == 0

    assert owns("hermes", "/somewhere/harness/data/hermes-venv/bin/hermes dashboard")
    assert not owns("hermes", os.path.expanduser("~/.hermes/hermes-agent/venv/bin/hermes")
                    + " dashboard --port 9119")
    assert not owns("hermes", "hermes dashboard")


# ── 3. U21: a readiness poll must not lie about a healthy runner ─────────────
def test_runner_readiness_polls_carry_the_auth_header():
    """llama.cpp b10662 made /v1/models require the api-key we launch with. A poll
    without the header 401s for its whole budget and then reports a running runner
    as 'did not come up' — the LIE-TO-USER class."""
    # join shell line-continuations first — a multi-line curl is still one command
    code = re.sub(r"\\\n\s*", " ", _code(START))
    polls = [ln for ln in code.splitlines()
             if "/v1/models" in ln and "curl" in ln and "${R_PORT}" in ln]
    assert polls, "the runner readiness polls vanished — this fence would pass vacuously"
    for ln in polls:
        assert "Authorization: Bearer" in ln, \
            f"runner /v1/models poll without the auth header (U21 regression): {ln.strip()}"
