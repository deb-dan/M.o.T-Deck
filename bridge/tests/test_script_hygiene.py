#!/usr/bin/env python3
"""Structural guards for two repeatedly-bitten shell gotchas.

1. macOS /bin/bash 3.2 mis-parses an UNBRACED variable expansion glued to a
   multibyte character: `"$f…"` swallows ellipsis bytes into the variable name,
   and under `set -u` the script dies with `f?: unbound variable`. It bit the
   fat-installer build (2026-07-24, `$APP…`) and measure_music.sh (2026-08-20,
   `$f…`). Rule: any `$name` immediately followed by a non-ASCII byte must be
   braced — `${name}…`.

2. THE EXECUTE BIT. The bridge runs installers as `subprocess.run([<path>])`, so a
   script that lost its `chmod +x` raises PermissionError inside a background
   thread — which is exactly how `install_aider.sh` shipped at mode 100644 and made
   the Aider tab's Install button do nothing at all (2026-08-21). `cp -R` and the
   fat-seed tar both preserve the mode, so a missing bit reaches every snapshot.
   Every `scripts/*.sh` is executed by something; none may lose it.
"""
import glob, os, re, subprocess, sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
PAT = re.compile(r"\$[A-Za-z_][A-Za-z_0-9]*[^\x00-\x7F]")

bad = []
scripts = sorted(glob.glob(os.path.join(ROOT, "scripts", "*.sh")))
assert scripts, "no scripts found — the glob is broken, not the repo"
for path in scripts:
    with open(path, encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh, 1):
            if PAT.search(line):
                bad.append(f"{os.path.basename(path)}:{i}: {line.strip()}")

assert not bad, (
    "unbraced $var glued to a multibyte char (bash-3.2 nounset trap) — use ${var}…:\n"
    + "\n".join(bad)
)

# ── 2. the execute bit, on disk AND in the index ─────────────────────────────
# The working-tree mode is what subprocess actually sees; the git mode is what a
# fresh clone / the fat seed will hand out. Both are checked, because a chmod that
# never gets committed fixes one machine and no other.
noexec = [os.path.basename(p) for p in scripts if not os.access(p, os.X_OK)]
assert not noexec, (
    "scripts/*.sh must be executable — the bridge runs them directly and a missing "
    "bit is a silent PermissionError in a background thread. Fix with:\n"
    + "\n".join(f"  chmod +x scripts/{n}" for n in noexec)
)

git_noexec = []
try:
    out = subprocess.run(["git", "ls-files", "-s", "--", "scripts"],
                         cwd=os.path.abspath(ROOT), capture_output=True, text=True,
                         timeout=30)
    if out.returncode == 0:
        for line in out.stdout.splitlines():
            mode, _rest = line.split(" ", 1)
            name = line.split("\t", 1)[-1]
            if name.endswith(".sh") and mode != "100755":
                git_noexec.append(f"{name} (mode {mode})")
except Exception as e:                                             # noqa: BLE001
    print(f"  (git mode check skipped: {e})")

assert not git_noexec, (
    "scripts/*.sh are committed WITHOUT the execute bit — a fresh clone and the fat "
    "seed would both be broken. `chmod +x` them and commit the mode change:\n"
    + "\n".join("  " + n for n in git_noexec)
)

print(f"script hygiene OK — {len(scripts)} scripts, 0 glued expansions, "
      f"all executable")
