"""THE APP-LAYER SOURCE VIEW — the app layer's source as one string.

⚠️ WHY THIS FILE EXISTS, AND WHY DELETING IT BREAKS ~40 TEST FILES.

A large part of this suite asserts against bridge/app.py's SOURCE TEXT rather than
against imported objects, and it does so deliberately, for two different reasons that
are both still true:

  * importing bridge.app builds httpx clients and touches the network stack at import
    time, so a pure unit test of one decision table cannot afford to import it — it
    ast-extracts the one function it wants and execs it in a hand-built namespace
    (test_vision_content.py, test_path_guard.py, test_thinking_sidecar.py, …);
  * some facts have no runtime handle at all. "There is no GET on this route",
    "this endpoint does not mention truncate", "the marker string is spelled exactly
    this way in both the bridge and the panel" — those are properties of the text, and
    a source assertion is the only honest way to pin them.

Both reasons survive the router/core split (2026-08-28). What did NOT survive is the
assumption baked into every one of those tests: that the app layer is ONE FILE. app.py
is now a facade over bridge/core/*.py + bridge/routers/*.py, so `(ROOT / "bridge" /
"app.py").read_text()` stopped being "the app layer" and became "the 300-line facade".
Every one of those assertions would have gone green-by-vacuity — the substring is
absent, so a `not in` check passes, and a positive check fails loudly (better) while a
NEGATIVE check passes SILENTLY (much worse: a gate that cannot fail).

So the tests now read THIS, and this is the whole app layer, concatenated in the order
the code sat in app.py before the split. Order is part of the contract: a dozen
assertions slice the source BETWEEN two route decorators ("nothing between
/api/hermes/toolsets and _hermes_skill_rows mentions PUT"), which only means anything
if neighbours stay neighbours. FILES below is therefore an ORDERED list, not a glob —
adding a module means putting it where its code used to be, and `python -m
bridge.appsrc` prints the boundaries so that is checkable.

The `from __future__` lines are dropped from every file but the first: they are only
legal at the top of a module, and ast.parse() of the concatenation is exactly what
half these tests do to it.
"""
from __future__ import annotations

from pathlib import Path

BRIDGE = Path(__file__).resolve().parent

# ── THE ORDER IS THE ORIGINAL app.py ORDER ───────────────────────────────────
# Not the import order and not alphabetical: the line each module's code sat on in the
# pre-split file. core/appctx.py is first because it holds what were app.py's first 155
# lines (the imports, ROOT/PANEL, the satellite handles, the FastAPI instance); app.py
# is second because what remains of it — the /assets subclass and its mount — sat at
# 156-219; and so on down. `python -m bridge.appsrc` prints the boundaries.
FILES: tuple[str, ...] = (
    "core/appctx.py",
    "app.py",
    "core/procs.py",
    "routers/panel.py",
    "core/modelid.py",
    # S29 — core/modelreg.py is the BOTTOM of the model-identity stack (health.py
    # re-exports its path check and every seeder loads it by path), so it sits directly
    # before its first consumer. Registered here the moment it was created: a module on
    # disk and missing from this tuple is invisible to every source-text assertion in
    # the gate, and the NEGATIVE ones would then pass vacuously forever.
    "core/modelreg.py",
    "core/health.py",
    "routers/components.py",
    "routers/ody.py",
    "core/analytics.py",
    "routers/sidecars.py",
    "routers/version.py",
    "routers/odychat.py",
    "core/yamlset.py",
    "routers/models.py",
    "routers/hf.py",
    "core/hfclient.py",
    "routers/downloads.py",
    "routers/sampling.py",
    "routers/chat.py",
    "routers/hermes.py",
    "routers/misc.py",
    "routers/nav.py",
    "core/hermescfg.py",
    "routers/hermestools.py",
    "routers/voicecomp.py",
    "routers/voice.py",
    "routers/music.py",
    "routers/aider.py",
    "routers/office.py",
    "core/officelog.py",
    "routers/oo.py",
    # APPENDED, not inserted — a module with no pre-split position must not separate a
    # pair of neighbours some assertion slices between. See the matching note in
    # bridge/app.py's _LANES.
    "core/events.py",
    "routers/help.py",
    # The RAM fit advisor (v1.5.30), appended by the same rule.
    "core/memory.py",
    "core/fit.py",
    "routers/memory.py",
    # The Odysseus vision shim (v1.5.33), appended by the same rule.
    "routers/odyvision.py",
    # The ComfyUI generate surface (S1), appended by the same rule.
    "routers/comfy.py",
    # …and its curation/catalog/graph core (S8 extraction, v1.5.49). It owns no route,
    # but it MUST be here anyway: the contract seam test requires FILES to equal the app
    # layer on disk both ways, and a module missing from this view makes every
    # `X not in APP_SOURCE` assertion about it pass VACUOUSLY.
    "core/comfycur.py",
    # The goose agent lane, appended by the same rule.
    "routers/goose.py",
    # The goose EMBED lane (goose Desktop's UI served by us), appended by the same rule.
    "routers/gooseui.py",
    # The fit engine's GGUF HEADER READER (U23 extraction), appended by the same rule.
    # Route-less, like core/comfycur.py, and here for the same reason: the contract seam
    # test requires FILES to equal the app layer on disk both ways, and a module missing
    # from this view makes every `X not in APP_SOURCE` assertion about it pass VACUOUSLY.
    "core/ggufhdr.py",
    # The LOCAL API ACCESS lane (ledger S32), appended by the same rule. Registered
    # here the moment it was created: a module on disk and missing from this tuple is
    # invisible to every source-text assertion in the gate, and this lane's NEGATIVE
    # assertions are the ones that matter most (no key value in /api/status, no key
    # value in any log line) — exactly the ones that would pass vacuously.
    "routers/apikeys.py",
)

# EVERYTHING FROM app.py's LANE LIST DOWN IS EXCLUDED from the view: the lane tuple, the
# route-order restoration and the facade proxy. That is bookkeeping about the split
# rather than app-layer code, and it NAMES a lot of symbols (`_script`, `ROOT`,
# `caps_map_write`, every module path) — so including it would let a `X in SOURCE`
# assertion pass on the strength of a mention in the facade and could flip a `not in`
# assertion red for no behavioural reason at all.
FACADE_SENTINEL = "# ══ THE LANES"


def _read(rel: str, first: bool) -> str:
    src = (BRIDGE / rel).read_text(encoding="utf-8", errors="replace")
    if rel == "app.py" and FACADE_SENTINEL in src:
        src = src.split(FACADE_SENTINEL)[0]
    if not first:
        src = "\n".join(ln for ln in src.splitlines()
                        if not ln.startswith("from __future__ import"))
    return src


def app_source() -> str:
    """The app layer as one string, in original-app.py order."""
    parts = []
    for i, rel in enumerate(FILES):
        parts.append(f"# ══════ appsrc: bridge/{rel} ══════")
        parts.append(_read(rel, i == 0))
    return "\n".join(parts) + "\n"


APP_SOURCE = app_source()

if __name__ == "__main__":                                   # pragma: no cover
    _off = 1
    for rel in FILES:
        n = len(_read(rel, rel == FILES[0]).splitlines()) + 1
        print(f"{_off:6d}  bridge/{rel}  (+{n})")
        _off += n
    print(f"{_off:6d}  <end>   {len(APP_SOURCE)} chars")
