#!/usr/bin/env python3
"""Structural guard for a twice-bitten shell gotcha.

macOS /bin/bash 3.2 mis-parses an UNBRACED variable expansion glued to a
multibyte character: `"$f…"` swallows ellipsis bytes into the variable name,
and under `set -u` the script dies with `f?: unbound variable`. It bit the
fat-installer build (2026-07-24, `$APP…`) and measure_music.sh (2026-08-20,
`$f…`). Rule: any `$name` immediately followed by a non-ASCII byte must be
braced — `${name}…`.
"""
import glob, os, re, sys

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
print(f"script hygiene OK — {len(scripts)} scripts, 0 glued expansions")
