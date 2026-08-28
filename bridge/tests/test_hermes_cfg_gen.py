"""Unit tests for the HERMES CONFIG GENERATION — the signal that makes Hermes's
own dashboard reload itself after we change its configuration.

WHY IT EXISTS (the bug it closes, with the evidence):
  * Hermes's `web/src/pages/SkillsPage.tsx:155-174` fetches its toolset/skill
    lists ONCE on mount (the useEffect is keyed only on the profile) and patches
    local state optimistically on its OWN toggles (:180-186). It never re-fetches.
  * `app/main.swift`'s only reload rule was `maybeReloadStaleHermes` — backgrounded
    longer than `staleAfter` (600s). So for ten minutes after a tab switch the user
    reads a frozen page and OUR lever looks broken.
  * The fix is a counter the shell can cheaply compare against.

THE PROPERTIES THAT MATTER, and what would break if each were wrong:
  * MONOTONIC. The shell only reloads on a strict INCREASE. A counter that could
    go down mid-process would silently stop signalling.
  * PROCESS-LIFETIME, and that is deliberate: a bridge restart resets it to 0,
    which the shell must read as a decrease (record, do not reload) rather than a
    change — otherwise every bridge restart would reload the Hermes tab for
    nothing. Tested here as "a fresh process starts at 0".
  * BUMPED ONLY ON A REAL WRITE. `_hermes_write_mcp` has two no-op branches
    (already-absent, already-exact) that return BEFORE the file is touched; if
    the bump sat at the top of that function an idempotent toggle would reload
    Hermes for a write that never happened.
  * PUBLISHED ON AN ENDPOINT THE SHELL ALREADY CALLS. /api/status is the one URL
    `portOpen` in main.swift already fetches, so this needs no new route and no
    new client.

Run: python3 bridge/tests/test_hermes_cfg_gen.py   (from repo root).
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

for _k in [k for k in os.environ if k.lower().endswith("_proxy")]:
    os.environ.pop(_k, None)

_TMP = tempfile.mkdtemp(prefix="harness-hgen-home-")
os.environ["HERMES_HOME"] = _TMP

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# ⚠️ THE APP LAYER IS NO LONGER ONE FILE (router/core split, 2026-08-28).
# bridge/app.py is a FACADE over bridge/core/*.py + bridge/routers/*.py, so the
# source-text assertions below read bridge/appsrc.py's assembled view of the whole
# app layer instead of one file. Read bridge/appsrc.py's header for why the
# assertions are source-text in the first place and why order is part of it.
from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402
import bridge.app as A  # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


# ── the counter itself ───────────────────────────────────────────────────────
check("a fresh process starts at 0 (so a bridge restart is a DECREASE, which the "
      "shell records rather than reloading for)", A.hermes_cfg_gen() == 0)

n0 = A.hermes_cfg_gen()
n1 = A._hermes_cfg_bump()
check("a bump returns the NEW generation", n1 == n0 + 1)
check("...and the reader agrees with it", A.hermes_cfg_gen() == n1)

seq = [A._hermes_cfg_bump() for _ in range(25)]
check("strictly monotonic over many bumps", seq == sorted(set(seq)) and len(seq) == 25)
check("...and every step is exactly +1", all(b - a == 1 for a, b in zip(seq, seq[1:])))
check("the reader never mutates", [A.hermes_cfg_gen() for _ in range(3)]
      == [A.hermes_cfg_gen()] * 3)
check("the counter is an int, not a float/str (the shell parses it as an Int)",
      type(A.hermes_cfg_gen()) is int)

# ── the mcp writer bumps ONLY on a real write ────────────────────────────────
CFG = Path(_TMP) / "config.yaml"
if CFG.exists():
    CFG.unlink()

before = A.hermes_cfg_gen()
A._hermes_write_mcp("spike", None)              # no file at all + remove
check("removing a server from a config that does not exist writes nothing and "
      "does not bump", A.hermes_cfg_gen() == before and not CFG.exists())

before = A.hermes_cfg_gen()
A._hermes_write_mcp("spike", {"url": "http://127.0.0.1:1/mcp"})
check("adding a server bumps", A.hermes_cfg_gen() == before + 1)
check("...and really wrote the file", CFG.exists())

before = A.hermes_cfg_gen()
A._hermes_write_mcp("spike", {"url": "http://127.0.0.1:1/mcp"})
check("re-adding the IDENTICAL entry is a no-op and does NOT bump "
      "(an idempotent toggle must not reload Hermes)",
      A.hermes_cfg_gen() == before)

before = A.hermes_cfg_gen()
A._hermes_write_mcp("spike", {"url": "http://127.0.0.1:2/mcp"})
check("changing the entry bumps", A.hermes_cfg_gen() == before + 1)

before = A.hermes_cfg_gen()
A._hermes_write_mcp("spike", None)
check("removing a PRESENT server bumps", A.hermes_cfg_gen() == before + 1)

before = A.hermes_cfg_gen()
A._hermes_write_mcp("spike", None)
check("removing an ALREADY-ABSENT server does not bump",
      A.hermes_cfg_gen() == before)

# ── /api/status publishes it ─────────────────────────────────────────────────
st = asyncio.run(A.status())
check("/api/status carries hermes_config_gen", "hermes_config_gen" in st)
check("...with the current value", st["hermes_config_gen"] == A.hermes_cfg_gen())
check("...as a plain int", type(st["hermes_config_gen"]) is int)
check("the rest of the status shape is untouched",
      st.get("bridge") == "ok" and "components" in st and "disk" in st)

A._hermes_cfg_bump()
st2 = asyncio.run(A.status())
check("a later read reflects a bump in between",
      st2["hermes_config_gen"] == st["hermes_config_gen"] + 1)

# ── wiring (bridge) ──────────────────────────────────────────────────────────
SRC = _APP_SOURCE


def _slice(start, end):
    return SRC.split(start, 1)[1].split(end, 1)[0]


check("the generation is published from /api/status, not a new route",
      '"hermes_config_gen": hermes_cfg_gen()' in
      _slice('@app.get("/api/status")', '@app.get("/api/logs/{name}")')
      and "/api/hermes/gen" not in SRC and "/api/hermes/generation" not in SRC)
check("...and it is the ONLY place the field name is emitted",
      SRC.count('"hermes_config_gen"') == 1)

ts = _slice('@app.post("/api/hermes/toolsets")', "async def _hermes_skill_rows")
check("the TOOLSET lever bumps", "_hermes_cfg_bump()" in ts)
check("...inside the success branch, after changed.append (never on a failure)",
      ts.index("changed.append(name)") < ts.index("_hermes_cfg_bump()")
      and ts.index("_hermes_cfg_bump()") < ts.index("except Exception as e:\n"
                                                    "            failed.append"))
check("...exactly once (one bump site, not scattered)", ts.count("_hermes_cfg_bump()") == 1)

sk = _slice('@app.post("/api/hermes/skills")', '@app.get("/api/browse/status")')
check("the SKILL lever bumps", "_hermes_cfg_bump()" in sk)
check("...inside the success branch, after changed.append",
      sk.index("changed.append(name)") < sk.index("_hermes_cfg_bump()"))
check("...exactly once", sk.count("_hermes_cfg_bump()") == 1)

mcp = _slice("def _hermes_write_mcp", "def _hermes_set_mcp")
check("the mcp writer bumps", "_hermes_cfg_bump()" in mcp)
check("...AFTER the atomic replace, i.e. only when the file really changed",
      mcp.index("os.replace(tmp, path)") < mcp.index("_hermes_cfg_bump()"))
check("...and after both no-op early-returns",
      mcp.index("return False                      # already absent") <
      mcp.index("_hermes_cfg_bump()")
      and mcp.index("return True                       # already exact") <
      mcp.index("_hermes_cfg_bump()"))

check("every bump site is one of the three writes we make (no bump on a READ path)",
      SRC.count("_hermes_cfg_bump()") == 3 + 1)   # 3 call sites + the def itself
check("the read helper is pure (no I/O, no global write)",
      "return _HERMES_CFG_GEN" in _slice("def hermes_cfg_gen", "def _hermes_config_path")
      and "global" not in _slice("def hermes_cfg_gen", "def _hermes_config_path"))

# ── wiring (shell) — the compare/record half lives in app/main.swift ─────────
SWIFT = (ROOT / "app" / "main.swift").read_text()
check("the shell reads the field off /api/status (the endpoint it already fetches)",
      'obj["hermes_config_gen"] as? Int' in SWIFT
      and 'appendingPathComponent("api/status")' in SWIFT)
check("the shell reloads only on a STRICT increase",
      "let p = prev, gen > p" in SWIFT)
# scoped to syncHermesGen's own body: STUDIO PHASE 2 added a second generation poll
# (nav) with the same record-then-decide shape, so an unscoped index() would answer
# about the wrong one.
_sync = SWIFT.split("func syncHermesGen", 1)[1].split("func retryIfFailed", 1)[0]
check("the shell records BEFORE deciding (so a reload cannot loop)",
      _sync.index("self.hermesCfgGen = gen") < _sync.index("let p = prev, gen > p"))
_swift_stale = (SWIFT.split("func maybeReloadStaleHermes", 1)[1]
                .split("func syncHermesGen", 1)[0])
check("the check still hangs off the EXISTING staleness entry point",
      SWIFT.count("func maybeReloadStaleHermes") == 1
      and "syncHermesGen(reloadIfNewer: true)" in _swift_stale)
# That entry point only runs when a tab BECOMES visible, which never happens to a Hermes
# pane already open beside the panel in split view. A visibility-gated poll drives the
# SAME function for that case — one implementation, two triggers.
check("...and a visibility-gated poll drives the same function for split view",
      SWIFT.count("func updateHermesGenTimer") == 1
      and 'syncHermesGen(reloadIfNewer: true, why: "poll")' in SWIFT
      and SWIFT.count("func syncHermesGen") == 1)
check("the 600s staleness rule survives untouched inside it",
      "Date().timeIntervalSince(since) > staleAfter" in _swift_stale
      and "hermesLastActive = nil" in _swift_stale)
check("the reload logs in the house idiom",
      "[hermes] reload -> config generation" in SWIFT)

print()
print(("FAILED: " + "; ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
