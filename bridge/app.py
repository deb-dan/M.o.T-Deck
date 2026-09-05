"""Harness bridge — control panel + component lifecycle API.

M0/M1 scope: status, install (with plan → approve → execute), start/stop.
Gearbox (M2) and adapter/self-heal (M3) are stubs; see gearbox.py / adapter.py.

⚠️ THIS FILE IS A FACADE (router/core split, 2026-08-28). The 10,072-line monolith is
now bridge/core/*.py (config/paths, process primitives, health, model identity,
analytics, hermes config) + bridge/routers/*.py (one file per lane). What stays here is
exactly what cannot live anywhere else:

  * the /assets StaticFiles subclass and its mount, which is boot wiring;
  * the imports that PULL IN every router, which is what registers the routes — the
    import order below IS the route-registration order, so it mirrors the order the
    routes sat in the old file;
  * a MODULE PROXY that makes `bridge.app` still answer for every symbol the rest of
    the tree imports from it.

⚠️ THE PROXY IS NOT DECORATION — READ THIS BEFORE TOUCHING IT. 50+ test suites and the
contract gate import bridge.app internals directly (`from bridge import app as A;
A.caps_map_write(...)`), and several of them MONKEYPATCH module globals — `A.ROOT`,
`A._script`, `A._set_runner_model`, `A._proc_cmdline`, `A._port_listener_pids`,
`A._hermes_dash`, `A.aider_spawn_spec` — expecting the patch to change what the code
under test sees. A plain re-export cannot do that: `from .core.procs import _script`
binds a NAME here, and rebinding this module's name leaves core.procs' own global (and
therefore every caller inside core.procs) pointing at the original. So the facade
replaces this module's class with one whose __setattr__ writes the new value into EVERY
module that holds that name, and whose __getattr__ finds anything not bound here. Reads
and writes both propagate; the tests did not have to change.

docs/handoff/APP-FACADE-MANIFEST.md is the generated inventory of that surface.
"""
from __future__ import annotations

import importlib as _importlib
import sys as _sys
import time
from types import ModuleType as _ModuleType

from fastapi.staticfiles import StaticFiles

# ⚠️ __package__ OR "bridge", NOT a relative import — AND THAT IS NOT PEDANTRY.
# bridge/tests/test_parakeet_stt.py puts bridge/ itself on sys.path and does
# `import app as A`, so this module genuinely runs BOTH as `bridge.app` (uvicorn,
# every other test) and as a top-level `app` with no package at all. A relative
# `from .core import …` raises ImportError in the second case, which is why the
# satellite imports below this line have always been written as a relative try with an
# absolute `bridge.…` fallback. Resolving the package name ONCE, here, does the same
# job for the whole facade instead of thirty times.
_PKG = __package__ or "bridge"


def _lane(name: str) -> _ModuleType:
    """Import one lane, and DIAGNOSE a missing one instead of dying anonymously.

    ⚠️ THIS IS DELIBERATELY *NOT* THE DEFENSIVE PATTERN THE SATELLITES USE. voice.py or
    oo.py going missing costs the harness one tab, so those imports swallow the failure
    and the affected route says why. A missing LANE is not a degraded harness — it is
    the routes themselves gone. There is nothing to degrade to and pretending otherwise
    would serve a bridge that answers 404 to half the panel, which is the exact
    LIE-TO-USER shape this project ranks above a crash.

    So this still raises. What it adds is the sentence that turns a bare
    `ModuleNotFoundError: bridge.routers.voice` in a log into an actionable one, because
    there is really only one way to reach that state: something copied bridge/*.py
    without bridge/core/ and bridge/routers/. ship.sh's flat glob did exactly that until
    the split taught it not to, and a hand-copied or half-restored snapshot still can.
    """
    try:
        return _importlib.import_module(f"{_PKG}.{name}")
    except ModuleNotFoundError as e:
        _missing = e.name or ""
        if _missing.startswith(f"{_PKG}.core") or _missing.startswith(f"{_PKG}.routers"):
            raise ModuleNotFoundError(
                f"bridge lane {name!r} is missing ({e}). bridge/app.py is a FACADE: the "
                "routes live in bridge/core/*.py and bridge/routers/*.py and it cannot "
                "serve anything without them. This snapshot has app.py but not the "
                "packages — re-run ./scripts/ship.sh (it copies bridge/{core,routers}/ "
                "since 2026-08-28), or re-provision the snapshot.",
                name=e.name, path=e.path) from e
        raise


_appctx = _lane("core.appctx")
app = _appctx.app
ROOT = _appctx.ROOT
PANEL = _appctx.PANEL

# _WatchedStatic logs through the office lane's logger, and a function's global lookup
# goes straight to this module's __dict__ — the facade proxy below cannot serve it. So
# this one name is a REAL import here, not a proxied attribute.
_office_log = _lane("core.officelog")._office_log


class _WatchedStatic(StaticFiles):
    """StaticFiles that LOGS the Univer bundles, and nothing else.

    ⚠️ WHY THIS IS A StaticFiles SUBCLASS AND NOT `@app.middleware("http")`. It exists
    to answer one question — when LOffice's boot trace stops after a given bundle, was
    that file NEVER REQUESTED (the parser died before the tag, or the page never got
    that far) or REQUESTED AND NEVER FINISHED (a stalled transfer)? Those are different
    faults with the same symptom and nothing else in the stack distinguishes them:
    uvicorn's access log is not on in our launch line and a StaticFiles hit is
    otherwise silent.

    A `BaseHTTPMiddleware` would answer it too — and would also wrap EVERY response in
    the harness, including the SSE chat relays, in a queue-and-pump that is documented
    to interfere with streaming and background tasks. The whole Hermes lane rides those
    streams (a 20s heartbeat frame the panel's stall watchdog counts on), so a
    diagnostic for the spreadsheet tab may not go anywhere near them. This subclass
    touches exactly the one mount, and logs only the prefix below.
    """

    # ⚠️ MATCHED AS A SUBSTRING, DELIBERATELY, AND THE FIRST DRAFT GOT THIS WRONG.
    # It watched `scope["path"].startswith("/vendor/univer/")` on the reasoning that a
    # Mount rewrites the path to be relative to itself. This Starlette does NOT: it
    # leaves `path` as the FULL "/assets/vendor/univer/x.js" and puts "/assets" in
    # `root_path` — so the branch never fired and the whole diagnostic was a no-op that
    # looked correct in review. It was caught by driving the real page in a real
    # browser and finding zero lines in the log. A substring is true under BOTH
    # conventions, which is the point.
    #
    # The set is exactly what bridge/panel/office.html's VENDOR list loads: the five
    # univer files plus React and React-DOM, which live one directory up because the
    # artifact renderer already vendored them. ⚠️ Those two are therefore ALSO logged
    # when an artifact opens — two lines, and arguably useful there too.
    WATCH = ("/vendor/univer/", "/vendor/react.production.min.js",
             "/vendor/react-dom.production.min.js")

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if not any(w in path for w in self.WATCH):
            return await super().__call__(scope, receive, send)
        t0 = time.time()
        _office_log(f"loffice-asset → {scope.get('method', '?')} {path}")
        sent = {"status": 0, "bytes": 0}

        async def _send(msg):
            if msg.get("type") == "http.response.start":
                sent["status"] = msg.get("status", 0)
            elif msg.get("type") == "http.response.body":
                sent["bytes"] += len(msg.get("body") or b"")
            await send(msg)

        try:
            await super().__call__(scope, receive, _send)
        except Exception as e:                                   # noqa: BLE001
            _office_log(f"loffice-asset ✗ {path} raised {type(e).__name__}: {e}")
            raise
        # A `→` with no matching `←` is the stalled case, spelled out rather than
        # inferred from a gap in the trace.
        _office_log(f"loffice-asset ← {sent['status']} {path} {sent['bytes']}B "
                    f"{int((time.time() - t0) * 1000)}ms")


app.mount("/assets", _WatchedStatic(directory=str(PANEL / "assets")), name="assets")


# ══ THE LANES ════════════════════════════════════════════════════════════════
# Importing a lane IS registering its routes: every route is still declared with the
# literal `@app.get(...)` / `@app.post(...)` decorator it always used, against the one
# FastAPI instance in core/appctx.py. This list is in the order the code sat in the
# pre-split file, so app.routes comes out in the same sequence — and bridge/appsrc.py
# assembles the source view in the same order, which a dozen assertions that slice
# BETWEEN two neighbouring routes depend on.
_LANES = (
    # core.singleton — the one-bridge-per-root guard (2026-08-30 incident). It is
    # imported by core.appctx before anything else runs, and is listed FIRST here for
    # the same reason it is first in appsrc.FILES. Registered in BOTH tuples on the
    # day it was created: a module missing from THIS one is unreachable through the
    # facade (the suite's ~1000-name reachability check catches it), and one missing
    # from appsrc.FILES makes every `not in` source assertion about it pass vacuously.
    "core.singleton",
    "core.appctx",
    "core.procs",
    "routers.panel",
    "core.modelid",
    # S29 — the shared registry rule (the BOTTOM of the model-identity stack;
    # core.health re-exports its path check). Registered here as well as in
    # appsrc.FILES: a module missing from THIS tuple is unreachable through the facade,
    # which the suite's 945-name reachability check catches — and which would otherwise
    # only surface as a confusing AttributeError inside a monkeypatched test.
    "core.modelreg",
    "core.health",
    "routers.components",
    "routers.component_lifecycle",
    "routers.ody",
    "core.analytics",
    "routers.sidecars",
    "routers.version",
    "routers.odychat",
    "core.yamlset",
    "routers.model_visibility",
    "core.modeldelete",
    "routers.models",
    "routers.model_rescan",
    # routers.aux — the aux-runner lane, split out of routers.models by the U64 slice
    # (models.py had reached the app layer's 1,500-line limit). It IMPORTS from
    # routers.models, so it is listed after it; the dependency runs one way only, and
    # `_aux_kill` stayed behind in models.py to keep it that way. Registered in this
    # tuple AND in appsrc.FILES on the day it was created, per the note above.
    "routers.aux",
    "routers.hf",
    "core.hfclient",
    "routers.downloads",
    "routers.sampling",
    "routers.chat",
    "routers.hermes",
    "routers.misc",
    "routers.nav",
    "core.hermescfg",
    "routers.hermestools",
    "routers.voicecomp",
    "routers.voice",
    "routers.music",
    "routers.aider",
    "routers.office",
    "core.officelog",
    "routers.oo",
    # ⚠️ APPENDED, NOT INSERTED, AND THAT IS DELIBERATE. Every other entry above is at
    # the line its code sat on in the pre-split app.py, because a dozen assertions slice
    # bridge/appsrc.py's source view BETWEEN two neighbouring routes. core/events.py
    # (the SSE hub, 2026-08-28) has no pre-split position at all — it is new — so
    # putting it anywhere in the middle would separate a pair that some test expects to
    # be adjacent, for no gain. It goes last in both lists, which costs only the
    # position of /api/events in /openapi.json.
    #
    # It is imported EARLIER than this in practice — core/health.py and five routers do
    # `from ..core.events import publish` — so its two routes register early and the
    # stable sort below is what puts them back here. That is precisely the mechanism
    # documented under ROUTE ORDER, RESTORED.
    "core.events",
    # …and routers/help.py by the SAME rule, stated again so the next new lane copies
    # the rule rather than the position. The Help surface's markdown route (roadmap
    # §2.4) has no pre-split home either, so it goes LAST in both lists. It separates
    # no pair of neighbours; it costs only where /api/help/explainers appears in
    # /openapi.json.
    "routers.help",
    # …and the RAM fit advisor (v1.5.30) by the SAME rule, a third time: core.memory is
    # the live ledger, core.fit the verdict engine, routers.memory their three GETs.
    # None of the three has a pre-split position, so all three go LAST in both lists.
    "core.memory",
    "core.fit",
    "routers.memory",
    # …and the Odysseus VISION SHIM (v1.5.33) by the SAME rule, a fourth time: it is
    # new, it separates no pair of neighbours, and it costs only where
    # /odyvision/v1/* appears in /openapi.json. (⚠️ THE PATH IN THIS COMMENT WAS
    # WRONG until S33/F1: it read /api/ody/vlshim/*, the namespace this slice
    # ABANDONED — a base under /api makes Odysseus classify the endpoint as native
    # Ollama and the wiring dies silently. bridge/routers/odyvision.py:84-102 is the
    # whole story, and it is the exact wrong turn a reader was being aimed at.)
    "routers.odyvision",
    # …and the ComfyUI GENERATE SURFACE (S1) by the SAME rule, a fifth time: new, it
    # separates no pair of neighbours, and it costs only where /comfy and /api/comfy/*
    # appear in /openapi.json.
    "routers.comfy",
    # …and its CURATION/CATALOG/GRAPH core (the S8 extraction). ⚠️ A CORE MODULE WITH NO
    # ROUTES STILL BELONGS IN THIS LIST, and the reason is `_Facade.__setattr__` below:
    # a write through the facade only reaches the modules in `_FACADE_MODULES`, which is
    # built from THIS tuple. `A.ROOT = tmpdir` — which the whole gallery/file-state group
    # of test_comfy_lane.py depends on — would otherwise leave core.comfycur's own ROOT
    # pointing at the real app directory, and those tests would go GREEN while measuring
    # the wrong tree. It registers no route, so route order is untouched.
    "core.comfycur",
    # …and the GOOSE agent lane by the SAME rule, a sixth time: new, it separates no
    # pair of neighbours, and it costs only where /goose and /api/goose/* appear.
    "routers.goose",
    # …and the GOOSE EMBED lane (goose Desktop's own UI, served by us) by the SAME rule,
    # a seventh time: new, it separates no pair of neighbours, and it costs only where
    # /gooseui and /api/gooseui/* appear.
    "routers.gooseui",
    # …and the FIT ENGINE'S GGUF HEADER READER (the U23 extraction, when core/fit.py
    # crossed the 1500-line fence). Route-less, like core.comfycur, and in this list for
    # the same two reasons: `_Facade.__setattr__` only reaches the modules built from
    # THIS tuple, and the facade must answer for its top-level names.
    "core.ggufhdr",
    # …and the LOCAL API ACCESS lane (ledger S32) by the SAME rule, an eighth time:
    # new, it separates no pair of neighbours, and it costs only where /api/apikeys*
    # and /api/apilog appear.
    "routers.apikeys",
    # …and QUIT EVERYTHING (U55, Debi's both-doors ruling 2026-09-02) by the SAME rule, a
    # ninth time: new, it separates no pair of neighbours, and it costs only where
    # /api/quitall and /api/quitall/plan appear in /openapi.json. ⚠️ It imports
    # routers.components — the ONE identity-verified stop path, which it must never
    # reimplement — so it stays AFTER that lane here as well as on disk.
    "routers.quitall",
    # Shared launch-provenance authority. Appended by the same new-module rule and
    # included in the facade so historic bridge.app imports/monkeypatches still reach
    # the implementation used by process-management lanes.
    "core.ownership",
    # U31 durable local Chat/Agent turns. Appended: new modules may not separate
    # source-view neighbours which encode the old monolith's route positions.
    "core.turns",
    "routers.turns",
    # M.O.T-owned reconciliation around Hermes's split WhatsApp enablement state.
    "routers.hermeschannels",
    # U106 bridge-lifetime Hermes relay ownership (route-less, appended).
    "core.hermesturn",
    "core.hermesreplay",
    "core.localsecrets",
)

# The route table BEFORE any lane is imported: FastAPI's own four (/openapi.json,
# /docs, /docs/oauth2-redirect, /redoc) plus the /assets mount above. Frozen here so
# the reordering below can never touch them.
_PRE_ROUTES = len(app.router.routes)

_FACADE_MODULES = tuple(_lane(_n) for _n in _LANES)

# U77 — compatibility forwarders stay in components.py, while the facade exposes the
# lifecycle owner's actual callable after all lanes have loaded.
_FACADE_OWNERS = {
    "start_plan": "routers.component_lifecycle",
    "_opencode_live_warning": "routers.component_lifecycle",
    "start": "routers.component_lifecycle",
    "stop": "routers.component_lifecycle",
    "restart": "routers.component_lifecycle",
    "update": "routers.component_lifecycle",
    "_prov_set": "routers.component_lifecycle",
    "_provision": "routers.component_lifecycle",
}

# ── ROUTE ORDER, RESTORED ────────────────────────────────────────────────────
# ⚠️ THE ONE THING THE SPLIT CHANGED THAT HAD TO BE CHANGED BACK, AND IT IS NOT
# COSMETIC. In one file, a route was registered when the interpreter reached its
# decorator, so app.routes came out in reading order. Across modules, a route is
# registered when its module is first IMPORTED — and a lane that imports another lane
# drags it in early. routers/component_lifecycle.py needs live_tools_warning from
# routers/models.py, so importing the lifecycle lane registers models routes before
# its own routes. The route SET is identical and no request is
# matched differently (no two paths in this app are ambiguous — checked), but the order
# is visible on the wire in /openapi.json and in /docs, and "identical payloads" is the
# bar for this refactor. So the tail is stable-sorted back into lane order: stable, so
# each lane's internal order — which is still plain reading order — survives untouched.
_LANE_RANK = {_n: _i for _i, _n in enumerate(_LANES)}


# A route the lane map cannot place INHERITS THE RANK OF THE ONE BEFORE IT, rather than
# falling to the end. That is not a fudge for a corner case — it is the office lane's
# `app.include_router(_office_mcp.build_router())`, whose endpoints live in
# bridge/office_mcp.py and so match no lane. It was appended right after the office
# routes when the office module ran, which is exactly where it belongs; ranking it
# "unknown, therefore last" moved it past the oo lane instead.
def _ranks(_routes) -> list:
    _out, _last = [], 0
    for _r in _routes:
        _mod = getattr(getattr(_r, "endpoint", None), "__module__", "") or ""
        _k = _LANE_RANK.get(_mod.split(".", 1)[-1])
        _last = _last if _k is None else _k
        _out.append(_last)
    return _out


_rest = app.router.routes[_PRE_ROUTES:]
_rk = _ranks(_rest)
app.router.routes[_PRE_ROUTES:] = [
    _rest[_i] for _i in sorted(range(len(_rest)), key=lambda _j: (_rk[_j], _j))]


# ══ THE FACADE ═══════════════════════════════════════════════════════════════
class _Facade(_ModuleType):
    """bridge.app's module class: reads AND writes reach the module that owns the name.

    __getattr__ is the easy half (PEP 562 would have done it): anything not bound in
    this module is looked up across the lanes, so `A.caps_map_write`, `A.PROBE_TIMEOUT_S`
    and `from bridge.app import sampling_view` all still resolve.

    __setattr__ is the half that actually matters, and the half a re-export list cannot
    do. `A._script = fake` has to change what the code under test CALLS — and that code
    now lives in another module, whose own global `_script` a rebinding here would not
    touch. So a write goes to every lane that holds the name (the owner AND every lane
    that imported it), which is exactly the set of globals that could resolve it. Same
    for `A.ROOT = tmpdir`, which the aider / nav / installed-flip / office-mcp suites
    use to redirect the whole harness at a temp tree.

    A name NO lane holds is simply set here — that is a test adding a new attribute, and
    nothing else could have been meant by it.
    """

    def __getattr__(self, name: str):
        owner = _FACADE_OWNERS.get(name)
        if owner:
            for _m in _FACADE_MODULES:
                if _m.__name__.split(".", 1)[-1] == owner:
                    return getattr(_m, name)
        for _m in _FACADE_MODULES:
            try:
                return getattr(_m, name)
            except AttributeError:
                continue
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    def __setattr__(self, name: str, value) -> None:
        for _m in _FACADE_MODULES:
            if name in vars(_m):
                setattr(_m, name, value)
        object.__setattr__(self, name, value)


_sys.modules[__name__].__class__ = _Facade
