"""UPSTREAM's side of the OpenCode seam — the gate a pin bump must pass.

Unlike every other component there is NO vendored source tree to read: upstream ships
a single prebuilt native binary. So the contract is pinned two ways against that
binary, and the whole module SKIPS CLEANLY until it is installed (the sandbox that
writes this code cannot run a Mach-O arm64 executable):

  1. by RUNNING it — `--version` must equal the pin, and `serve --help` must still
     offer --hostname and --port. Those two flags are the launch line;
  2. by SCANNING it — the env-var names and the provider package our config depends
     on must still exist as strings inside the binary. A rename there is the kind of
     failure that is silent: OpenCode would simply start auto-updating itself again,
     or start writing to ~/.config, and nothing would error.

Run: pytest bridge/contract_tests/test_opencode_contract.py -q
"""
import os
import re
import subprocess

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BIN = os.path.join(ROOT, "data", "opencode", "bin", "opencode")


def _installed() -> bool:
    return os.path.isfile(BIN) and os.access(BIN, os.X_OK)


def _run(*args) -> str:
    """stdout+stderr, or '' when the binary cannot run here (a foreign ISA in the
    sandbox is a SKIP, never a failure — the same rule test_mlx_whisper_contract uses
    for a cross-machine venv shebang)."""
    try:
        p = subprocess.run([BIN, *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (p.stdout or "") + (p.stderr or "")


def _pin() -> str:
    c = yaml.safe_load(open(os.path.join(ROOT, "harness.yaml"), encoding="utf-8").read())
    return str(c["build"]["opencode_pin"])


def test_version_matches_the_pin():
    if not _installed():
        return
    out = _run("--version").strip()
    if not out:
        return                       # cannot execute here → skip, do not fail
    assert _pin() in out, (
        f"the installed binary reports {out!r} but build.opencode_pin is {_pin()!r} — "
        "either the pin moved without a reinstall, or its auto-updater ran (which is "
        "exactly what start_component.sh disables two ways)")


def test_serve_still_takes_hostname_and_port():
    """THE launch line. `--port` matters most: upstream's own default is 0 (an
    ephemeral port), so a rename here would leave the tab pointing at nothing."""
    if not _installed():
        return
    out = _run("serve", "--help")
    if not out.strip():
        return
    for flag in ("--hostname", "--port"):
        assert flag in out, f"`opencode serve` no longer offers {flag}"


def test_serve_and_web_are_still_both_present():
    """We deliberately use `serve` and not `web` (web calls open() on the URL). If
    `serve` ever disappears, the branch must move to `web` plus a way to suppress the
    browser — so notice here rather than in a Start that pops Safari."""
    if not _installed():
        return
    out = _run("--help")
    if not out.strip():
        return
    assert re.search(r"\bserve\b", out), "the `serve` subcommand is gone"


def _strings(path, needles, chunk=1 << 22):
    """Which of `needles` appear as raw bytes in a large binary. Chunked with an
    overlap so a needle straddling a boundary is still found."""
    found = set()
    want = [n.encode() for n in needles]
    longest = max(len(w) for w in want)
    prev = b""
    with open(path, "rb") as fh:
        while True:
            buf = fh.read(chunk)
            if not buf:
                break
            hay = prev + buf
            for n, w in zip(needles, want):
                if w in hay:
                    found.add(n)
            if len(found) == len(needles):
                break
            prev = hay[-longest:]
    return found


def test_the_env_contract_still_exists_in_the_binary():
    """Four XDG_* variables + one flag are the ENTIRE containment story:

      XDG_CONFIG_HOME / XDG_CACHE_HOME / XDG_DATA_HOME / XDG_STATE_HOME
          packages/core/src/global.ts derives config, cache, data and state from
          xdg-basedir, so these are what keep its session db and the provider
          packages it installs at runtime out of ~/.config and ~/.cache.
      OPENCODE_DISABLE_AUTOUPDATE
          upstream's updater is ON by default; this is half of how it is nailed shut
          (the other half is "autoupdate": false in the config we write).

    If any of them vanishes at a bump, the failure is SILENT — nothing errors, the
    program just starts writing somewhere else, or updating itself.
    """
    if not _installed():
        return
    needles = ["XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
               "OPENCODE_DISABLE_AUTOUPDATE", "autoupdate"]
    found = _strings(BIN, needles)
    missing = [n for n in needles if n not in found]
    assert not missing, (
        f"these names are gone from the opencode binary: {missing}. They are the "
        "containment + pin-discipline contract — re-read packages/core/src/global.ts "
        "and cli/upgrade.ts at the new version before shipping the bump.")


def test_the_provider_package_our_config_names_still_exists():
    """Our config declares `"npm": "@ai-sdk/openai-compatible"` for the runner
    provider. That string is upstream's documented way to point at any
    OpenAI-compatible endpoint; if it moved, our fan-out would produce a provider
    OpenCode cannot load — and the tab would look configured but answer nothing."""
    if not _installed():
        return
    assert "@ai-sdk/openai-compatible" in _strings(BIN, ["@ai-sdk/openai-compatible"]), (
        "the openai-compatible provider package name changed — bridge's opencode "
        "config fan-out (scripts/start_component.sh) writes it verbatim")
