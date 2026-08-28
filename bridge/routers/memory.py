"""ROUTER — the memory ledger + the fit advisor's HTTP surface.

Three questions, three routes, one engine (bridge/core/fit.py) behind all of them and
behind the load-consent flow in routers/models.py — so the chip on a row, the line in
the consent panel and the answer an API client gets can never disagree. That was the
point of building the engine first: LM Studio's documented failure is a browser badge
and a loader that price the same model differently.

  GET /api/memory              the live ledger (add ?external=1 for the top outside
                               consumers — read-only, we name them and never touch them)
  GET /api/memory/fit          one verdict, with arithmetic and remedies
  GET /api/memory/fits         a verdict per installed chat model, for the row chips

⚠️ NO ROUTE HERE CAN BLOCK ANYTHING. They are all GETs that return numbers. The only
refusal in the whole feature lives in core/fit.py (hand-set Metal over-commit) and it
is REPORTED by these routes, never enforced by them.
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from ..core import fit as _fit
from ..core import memory as _mem
from ..core.appctx import app
from ..core.modelid import _live_model_id
from ..core.procs import _port_alive_sync, _registry_models, cfg
from .models import _split_audio


def _live_slot() -> dict:
    """What the main slot is holding right now: {'id', 'up'}. The fit question for an
    installed model is "if I load THIS", and loading it into a busy slot ejects what is
    there — so the resident model's footprint is money the switch gets back. Not
    counting it is how an advisor tells you a 7 GB model will not fit while the 20 GB
    one it replaces is still on the books.

    ⚠️ THE LIVE MODEL IS WHAT THE RUNNER REPORTS SERVING, NOT WHAT harness.yaml PINS.
    The two can disagree, and the adversarial pass hit it live: a switch whose
    readiness probe failed reverted the PIN to the old model while the process went on
    serving the NEW one — and the ledger then labelled the pinned model "Live · ~5.0
    GB", a measurement of a process running something else. `_live_model_id` is the
    same authoritative read the Models pane's own "live" pill uses (its ISSUE C), and
    the pin is only the fallback for when the runner will not say."""
    rc = cfg().get("runner", {}) or {}
    port = rc.get("port")
    up = bool(port and _port_alive_sync(int(port)))
    served = _live_model_id(int(port)) if up else None
    return {"id": (served or rc.get("model") or "") if up else "", "up": up}


def _runner_row(snap: dict) -> "dict | None":
    for row in snap.get("components") or []:
        if row.get("name") == "runner":
            return row
    return None


def holders(snap: dict, live_id: str) -> list:
    """Named things whose memory a remedy could free, biggest first. The ledger's own
    rows, so the consent panel and the strip name the same processes."""
    out = []
    for row in snap.get("components") or []:
        if row.get("name") in ("bridge", "app"):
            continue                       # never suggest evicting the app you are in
        title = row.get("label") or row.get("name")
        if row.get("name") == "runner" and live_id:
            title = live_id
        out.append({"name": row.get("name"), "title": title,
                    "footprint_bytes": row.get("footprint_bytes") or 0})
    return out


def _entry(mid: str) -> "dict | None":
    models, _audio = _split_audio(_registry_models())
    return next((m for m in models if m.get("id") == mid), None)


def _override(req: Request) -> dict:
    q = req.query_params
    out = {}
    try:
        if q.get("ctx"):
            out["ctx"] = int(q.get("ctx"))
    except (TypeError, ValueError):
        pass
    if q.get("kv_quant"):
        out["kv_quant"] = str(q.get("kv_quant"))
    return out


@app.get("/api/memory")
def api_memory(req: Request) -> JSONResponse:
    """The ledger. Reading it also marks the ledger WATCHED, which is what moves the
    background sampler from its 15 s idle cadence to 2 s — and it decays on its own, so
    a closed tab stops costing samples without needing to tell us."""
    # `?watch=0` reads the ledger WITHOUT claiming somebody is watching it. The MOT
    # Deck tile polls on the deck's own cadence and should not, by existing, pin the
    # sampler at its 2 s rate for the rest of the session.
    if str(req.query_params.get("watch") or "1") not in ("0", "false", "no"):
        _mem.watch()
    _mem.start_sampler()
    want_ext = str(req.query_params.get("external") or "") in ("1", "true", "yes")
    snap = _mem.snapshot(external=want_ext)
    live = _live_slot()
    row = _runner_row(snap)
    if row is not None and live["id"]:
        row["title"] = live["id"]
    snap["live_model"] = live["id"]
    snap["budget"] = _fit.budget()
    _res = int((row or {}).get("footprint_bytes") or 0)
    snap["budget_after_eject"] = _fit.budget(freeing_bytes=_res) if _res else None
    return JSONResponse(snap)


@app.get("/api/memory/fit")
def api_memory_fit(req: Request) -> JSONResponse:
    """One verdict for one installed model, at the settings it would load with (or at
    the settings passed as ?ctx=/&kv_quant= — that is the remedy recalculation, and it
    is a GET so a headless caller can ask the same question the panel asks)."""
    mid = (req.query_params.get("id") or "").strip()
    if not mid:
        return JSONResponse({"ok": False, "error": "no model id"}, status_code=400)
    entry = _entry(mid)
    if entry is None:
        return JSONResponse({"ok": False, "error": f"'{mid}' is not installed"},
                            status_code=404)
    _mem.watch()
    snap = _mem.snapshot()
    live = _live_slot()
    row = _runner_row(snap)
    # ⚠️ A RELOAD OF THE MODEL ALREADY RESIDENT ALSO FREES IT. The first draft
    # credited the runner's footprint only when the target was a DIFFERENT
    # model, so the live model's own row read "Over by ~3.7 GB" — a model
    # visibly running, and running fine, marked as not fitting. Any switch
    # into the main slot ejects what is there first, including itself.
    freeing = int((row or {}).get("footprint_bytes") or 0) if live["up"] else 0
    hold = [h for h in holders(snap, live["id"])
            if not (h["name"] == "runner" and freeing)]
    if live["up"] and live["id"] == mid and not _override(req):
        got = _fit.live_verdict(int((row or {}).get("footprint_bytes") or 0),
                                int((row or {}).get("peak_bytes") or 0))
        got.update(ok=True, id=mid, replaces="", settings=_fit.settings_for(entry),
                   budget=_fit.budget(freeing))
        return JSONResponse(got)
    got = _fit.fit(entry, _override(req), freeing_bytes=freeing, holders=hold,
                   replaces=(live["id"] if (freeing and live["id"] != mid) else ""))
    got["ok"] = True
    got["id"] = mid
    got["replaces"] = live["id"] if (freeing and live["id"] != mid) else ""
    return JSONResponse(got)


@app.get("/api/memory/fits")
def api_memory_fits(req: Request) -> JSONResponse:
    """A verdict per installed chat model — what the Models list paints its chips from.

    One ledger sample and one budget for the whole page: rows that disagree with each
    other about how much memory is free are worse than rows with no chip at all."""
    _mem.watch()
    _mem.start_sampler()
    snap = _mem.snapshot()
    live = _live_slot()
    row = _runner_row(snap)
    resident = int((row or {}).get("footprint_bytes") or 0)
    models, _audio = _split_audio(_registry_models())
    out = {}
    warm = []
    for m in models:
        mid = m.get("id") or ""
        freeing = resident if live["up"] else 0
        hold = [h for h in holders(snap, live["id"])
                if not (h["name"] == "runner" and freeing)]
        if live["up"] and live["id"] == mid:
            lv = _fit.live_verdict(int((row or {}).get("footprint_bytes") or 0),
                                   int((row or {}).get("peak_bytes") or 0))
            out[mid] = {"verdict": "live", "need_bytes": lv["need_bytes"],
                        "gap_bytes": 0, "oracle": False, "copy": lv["copy"],
                        "settings": _fit.settings_for(m), "refuse": False}
            continue
        try:
            # CACHED ORACLE ONLY. This route paints a page; it may not spend 0.3 s per
            # installed model shelling out to the fitter (16 models = 4.6 s of blank
            # list, measured on the first draft). Rows come back on the formula — which
            # matches the oracle to within 0.4% on every architecture in this registry
            # — and the oracle warm-up below upgrades them for the next tick.
            got = _fit.fit(m, None, freeing_bytes=freeing, holders=hold,
                           cached_oracle=True,
                           replaces=(live["id"] if (freeing and live["id"] != mid) else ""))
            if not got.get("oracle") and str(m.get("format") or "") == "gguf":
                warm.append((m.get("path") or "", got.get("settings") or {}))
        except Exception as e:                                   # noqa: BLE001
            out[mid] = {"verdict": "unknown", "reason": str(e)[:120],
                        "copy": {"chip": "No estimate"}}
            continue
        out[mid] = {"verdict": got["verdict"], "need_bytes": got.get("need_bytes"),
                    "gap_bytes": got.get("gap_bytes"),
                    "oracle": got.get("oracle"), "copy": got.get("copy"),
                    "settings": got.get("settings"),
                    "refuse": bool(got.get("refuse"))}
    if warm:
        _fit.warm_oracle([(p, s) for p, s in warm if p])
    # TWO BUDGETS, BOTH TRUE, AND THE STRIP SAYS SO. Measured live on this machine:
    # 5.0 GB free with the 27B resident, 14.9 GB the moment it is ejected — because
    # its weights are GPU-WIRED and a switch releases them. Showing only the first
    # makes every "Fits" chip look like an arithmetic error; showing only the second
    # is an invitation to load two models. The strip prints both.
    return JSONResponse({"ok": True, "fits": out, "budget": _fit.budget(),
                         "budget_after_eject": (_fit.budget(freeing_bytes=resident)
                                                if resident else None),
                         "warming": len(warm),
                         "live_model": live["id"],
                         "pressure": (snap.get("system") or {}).get("pressure"),
                         "system": snap.get("system"),
                         "components": snap.get("components"),
                         "ours_bytes": snap.get("ours_bytes"),
                         "other_bytes": snap.get("other_bytes"),
                         "metric_note": snap.get("metric_note")})
