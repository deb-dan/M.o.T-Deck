"""Unit tests for the PURE artifact-save filename sanitizer (canvas Save-to-file).

Security gate for POST /api/artifact/save: the sanitizer must reduce any untrusted
filename to a safe, extension-whitelisted basename or reject it (None).
Run: python3 bridge/tests/test_artifact_save.py  (from repo root).
"""
import os
import sys
from pathlib import Path

# Sandbox hygiene: importing bridge.app builds an httpx client at module level,
# which explodes on SOCKS *_proxy env vars in CI-ish sandboxes. Scrub them —
# irrelevant to the pure function under test.
for _k in [k for k in os.environ if k.lower().endswith("_proxy")]:
    os.environ.pop(_k, None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from bridge.app import sanitize_artifact_filename as san  # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


# ── happy paths ───────────────────────────────────────────────────────────────
check("plain html kept", san("page.html") == "page.html")
check("jsx kept", san("Counter.jsx") == "Counter.jsx")
check("mermaid kept", san("flow.mmd") == "flow.mmd")
check("case: extension lowercased", san("NOTES.MD") == "NOTES.md")
check("spaces in stem kept (collapsed)", san("my   page.html") == "my page.html")
check("inner dots kept", san("a.b.html") == "a.b.html")

# ── traversal / separators ────────────────────────────────────────────────────
check("unix traversal → basename", san("../../etc/passwd.html") == "passwd.html")
check("bare traversal target no-ext rejected", san("../../etc/passwd") is None)
check("windows traversal → basename", san("..\\..\\win.js") == "win.js")
check("absolute path → basename", san("/Users/x/evil.svg") == "evil.svg")
check("dot-run collapsed inside stem", san("a..b.html") == "a.b.html")
check("pure dots rejected", san("....") is None)
check("dotfile rejected", san(".env") is None)
check("hidden traversal remnant rejected", san("..html") is None)

# ── charset / unicode / control chars ─────────────────────────────────────────
check("unicode letters → underscore", san("héllo.html") == "h_llo.html")
check("RLO override stripped (format char)", san("evil\u202e.html") == "evil.html")
check("newline stripped", san("a\nb.svg") == "ab.svg")
check("NUL stripped", san("a\x00b.md") == "ab.md")
check("shell metachars neutralized", san("a;rm -rf$(x).py" ) == "a_rm -rf_x_.py")

# ── extension whitelist ───────────────────────────────────────────────────────
check("exe rejected", san("payload.exe") is None)
check("dylib rejected", san("inject.dylib") is None)
check("no extension rejected", san("README") is None)
check("txt allowed", san("notes.txt") == "notes.txt")
check("double-ext takes the LAST ext", san("safe.html.exe") is None)
check("trailing dot rejected (no ext)", san("file.") is None)

# ── degenerate inputs ─────────────────────────────────────────────────────────
check("empty rejected", san("") is None)
check("None rejected", san(None) is None)
check("whitespace-only rejected", san("   ") is None)
check("only-ext rejected (empty stem)", san(".html") is None)
check("overlong input rejected", san("x" * 600 + ".html") is None)
check("overlong stem capped to 80", san("y" * 200 + ".md") == "y" * 80 + ".md")
check("non-string coerced", san(123) is None)  # "123" has no extension

# ── result invariants (fuzz-ish sweep) ────────────────────────────────────────
for probe in ["../a.html", "a/../b.md", "~/.ssh/id_rsa.txt", "c:\\x\\y.js",
              "ok.svg", "\u2028line.py", "%2e%2e%2fz.css"]:
    out = san(probe)
    if out is not None:
        ok = ("/" not in out and "\\" not in out and ".." not in out
              and out == os.path.basename(out) and not out.startswith("."))
        check(f"invariants hold for {probe!r} → {out!r}", ok)

print()
if FAILS:
    print(f"{len(FAILS)} FAILED"); sys.exit(1)
print("ALL PASS")
