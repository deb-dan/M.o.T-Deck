"""ROUTER — imported-model visibility: hide and unhide read-only registry rows."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from ..core.appctx import _voice, app
from ..core.procs import _registry_models, cfg
from .downloads import _registry_update


# ── hidden models ───────────────────────────────────────────────────────────
# Debi's ask: the HF cache and LM Studio hand us models that will never be used here,
# and the list is the worse for them. HIDE is deliberately NOT delete: the files
# belong to another app, so the only honest operation is to stop listing them.
#
# Only IMPORTED / CACHED sources may be hidden. An app-owned model (source
# download/local) already has a real Delete, and offering both would give the same
# row two different ways to disappear — one of which does not free any disk.
HIDEABLE_SOURCES = ("lmstudio-import", "jan-import", "audio-hf-cache")


def _is_hidden(m: object) -> bool:
    return bool(isinstance(m, dict) and m.get("hidden"))


def _hideable(m: object) -> bool:
    """PURE. True when this entry may be hidden from the lists."""
    return bool(isinstance(m, dict)
                and str(m.get("source") or "") in HIDEABLE_SOURCES)


def _hidden_view(m: dict) -> dict:
    """The minimum a hidden row needs: enough to name it and to unhide it."""
    return {"id": m.get("id"), "name": m.get("name") or m.get("id"),
            "source": m.get("source"),
            "kind": ("audio" if (_voice is not None and _voice.is_audio_entry(m))
                     else "chat")}


@app.post("/api/models/hide")
async def api_models_hide(req: Request) -> JSONResponse:
    """{id, hidden} → hide/unhide one imported model from every list.

    Writes `hidden:true` onto the registry entry through the SAME atomic
    _registry_update the voice pins use, and seed_registry.merge carries it across a
    RESCAN (a rescan reads FILES and hiding is a user decision that lives nowhere on
    disk — exactly the bug the voice-pin carry-forward already fixed once)."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    mid = str(body.get("id") or "").strip()
    want = bool(body.get("hidden", True))
    if not mid:
        return JSONResponse({"ok": False, "error": "no model id given"}, status_code=400)
    entry = next((m for m in _registry_models() if m.get("id") == mid), None)
    if entry is None:
        return JSONResponse({"ok": False, "error": f"'{mid}' is not in the registry"},
                            status_code=400)
    # Unhiding is always allowed — otherwise a source change could strand a row.
    if want and not _hideable(entry):
        return JSONResponse(
            {"ok": False, "error": f"'{mid}' is app-owned — delete it instead of "
                                  f"hiding it (hiding is for read-only imports)"},
            status_code=400)
    # A model that is IN USE must not be hidden: it would vanish from every picker
    # while still being the thing MOT Deck runs, which is the one state a user
    # cannot reason about. Call the legacy normalizer at use time: importing it at
    # module scope would invert the visibility -> models ownership seam.
    if want:
        c = cfg()
        from .models import _voice_cfg
        v = _voice_cfg()
        in_use = {"the chat runner": (c.get("runner", {}) or {}).get("model"),
                  "the aux runner": (c.get("aux", {}) or {}).get("model"),
                  "the default TTS": v["tts_model"], "the default STT": v["stt_model"]}
        for role, held in in_use.items():
            if held and held == mid:
                return JSONResponse(
                    {"ok": False, "error": f"'{mid}' is {role} right now — clear it "
                                          f"there first, then hide it"},
                    status_code=400)
    _registry_update(mid, {"hidden": True if want else None})
    print(f"[models] {'hid' if want else 'unhid'} {mid}", flush=True)
    return JSONResponse({"ok": True, "id": mid, "hidden": want})
