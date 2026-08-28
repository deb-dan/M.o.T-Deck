"""ROUTER — the Models pane: list, hide, switch, eject, delete, the RAM ledger, aux."""
from __future__ import annotations

import base64
import os
import subprocess
import threading
from fastapi import Request
from fastapi.responses import JSONResponse, Response
from ..core.appctx import ROOT, _voice, app
from ..core.modelid import _live_model_id
from ..core.procs import PROV, _clear_expected, _kill_port_listener, _port_alive_sync, _registry_models, _running_sync, _script, cfg
from ..core.yamlset import _set_runner_model, _set_yaml_model, _set_yaml_scalar
from .downloads import _registry_drop, _registry_update
from .sampling import _LOAD_AT_LAUNCH, _record_load_launch, launch_view, load_view, sampling_view


# ── hidden models ───────────────────────────────────────────────────────────────
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
    # while still being the thing the harness runs, which is the one state a user
    # cannot reason about. Refuse and say which role holds it.
    if want:
        c = cfg()
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


def _split_audio(models: list) -> tuple:
    """(chat, audio) partition of a registry list. Degrades to 'everything is a chat
    model' when bridge/voice.py is unavailable — never crashes the Models pane."""
    if _voice is not None:
        return _voice.split_audio(models)
    return list(models or []), []


def _voice_cfg() -> dict:
    """The harness.yaml `voice:` block, normalised. Empty string = capability off."""
    v = (cfg().get("voice") or {}) if isinstance(cfg().get("voice"), dict) else {}
    return {"tts_model": str(v.get("tts_model") or "").strip(),
            "stt_model": str(v.get("stt_model") or "").strip()}


def _reject_if_audio(mid: str) -> "JSONResponse | None":
    """Guard for the CHAT slots (runner switch / aux). Loading a TTS backbone into
    llama-server or mlx_lm.server fails in a confusing way — refuse it by name."""
    entry = next((m for m in _registry_models() if m.get("id") == mid), None)
    if entry is not None and _voice is not None and _voice.is_audio_entry(entry):
        return JSONResponse(
            {"ok": False, "log": f"'{mid}' is a voice model — set it in Models → Audio, "
                                 f"not as a chat/aux model"}, status_code=400)
    return None


# ── Model-memory ledger (Fable verdict, promoted) ─────────────────────────────
# Bridge-side RAM accounting so main + aux (+ future voice) loads can't blow past
# the box's memory. APPROXIMATION: a model's RAM footprint ≈ its weight file size
# (real usage adds KV-cache/overhead; the budget headroom below covers that).


def _model_size(models: list, mid: str) -> int:
    m = next((x for x in models if x.get("id") == mid), None)
    return int((m or {}).get("size_bytes") or 0)


def _budget_bytes() -> int:
    mem = cfg().get("memory", {}) or {}
    try:
        gb = float(mem.get("budget_gb"))
    except (TypeError, ValueError):
        gb = 48.0
    return int(gb * (1024 ** 3))


def _resident_voice_bytes() -> int:
    """RAM claimed by a RESIDENT voice model, approximated the same way chat models
    are (weight file size). Zero whenever no worker is alive.

    This closes the recorded "the ledger ignores voice models" item — and it only
    became true-able when the persistent worker landed. One-shot renders really are
    transient (the process dies with the request), so counting them would have made
    the budget lie; a worker that holds 3.6GB until it is unloaded is exactly the
    persistent slot the earlier verdict said to revisit for."""
    if _voice is None:
        return 0
    try:
        return int((_voice.worker_resident() or {}).get("size_bytes") or 0)
    except Exception:                                            # noqa: BLE001
        return 0


def _loaded_models_bytes(exclude_slot: str | None = None) -> int:
    """Approx RAM (by file size) used by models currently SERVED: main runner's
    active model (if its port is up) + aux model (if its port is up) + a resident
    voice worker. exclude_slot ('main'|'aux'|'voice') omits that slot — used to get
    'other-slot usage' for a switch of that slot (so its own current usage isn't
    double-counted against the candidate)."""
    c = cfg()
    # Chat models ONLY: an audio entry must never be able to claim ledger budget
    # (voice weights are transient by design — spec §Architecture 1), and if an
    # audio id ever ended up in runner.model/aux.model the lookup must miss, not
    # silently account for it.
    models, _ = _split_audio(_registry_models())
    total = 0
    rc = c.get("runner", {}) or {}
    if exclude_slot != "main" and rc.get("port") and _port_alive_sync(int(rc["port"])):
        total += _model_size(models, rc.get("model") or "")
    ax = c.get("aux", {}) or {}
    if exclude_slot != "aux" and ax.get("port") and _port_alive_sync(int(ax["port"])):
        total += _model_size(models, ax.get("model") or "")
    if exclude_slot != "voice":
        total += _resident_voice_bytes()
    return total


def _voice_spawn_guard(size_bytes: int) -> "str | None":
    """Ledger gate handed to voice.get_worker(). None = spawn allowed, else the
    refusal text. Same shape as the runner/aux switch gates, and deliberately owned
    HERE: voice.py must not learn to read harness.yaml."""
    other = _loaded_models_bytes(exclude_slot="voice")
    budget = _budget_bytes()
    if size_bytes and not _within_budget(int(size_bytes), other, budget):
        return (f"loading that voice model would exceed the model-RAM budget "
                f"({(int(size_bytes) + other) / 1024**3:.1f} > {budget / 1024**3:.0f} GB) "
                f"— eject a chat model first")
    return None


def _within_budget(candidate_bytes: int, other_slot_bytes: int, budget_bytes: int) -> bool:
    """Pure predicate (unit-testable): does loading `candidate` alongside the other
    slot's current usage stay within budget? True = OK to load."""
    return (candidate_bytes + other_slot_bytes) <= budget_bytes


def _model_caps(m: dict) -> list:
    """The `capabilities` list for one registry entry. PURE.

    `vision` is unchanged. `tools` joins it ONLY on an explicit True — a null
    verdict (unreadable template, a shape modeltools does not know) must never be
    reported as an absent capability, because the panel and the OpenCode gate both
    read the absence as "this model cannot do it"."""
    caps = []
    if m.get("vision") or m.get("mmproj"):
        caps.append("vision")
    if m.get("tools") is True:
        caps.append("tools")
    return caps


# ── the OpenCode start gate ──────────────────────────────────────────────────
# OpenCode has NO text-edit fallback: every mutation is a native tool call
# (docs/research/2026-08-21-opencode-omnigent-recon.md §1). On a model that cannot
# emit one it does not degrade, it looks broken. So starting it against such a model
# WARNS — loudly, by name — and never refuses: the verdict is a template heuristic,
# and a heuristic may not stand between the user and a program they asked to run.
OPENCODE_TOOLS_OK = ""
OPENCODE_TOOLS_UNKNOWN = (
    "⚠ the loaded model %s does not say whether it supports tool calling — "
    "OpenCode needs it (look for the green `tools` pill in Models)")
OPENCODE_TOOLS_BAD = (
    "⚠ the loaded model %s has NO tool-calling support — OpenCode requires it and "
    "will look broken, not merely worse. Load a model with the green `tools` pill.")
OPENCODE_TOOLS_NONE = (
    "⚠ no model is loaded — OpenCode needs a running runner with a tool-capable model")


def opencode_tools_warning(entry) -> str:
    """'' when the live model is tool-capable, else the sentence to show. PURE.

    `entry` is the live model's registry entry, or None when nothing is loaded."""
    if not isinstance(entry, dict):
        return OPENCODE_TOOLS_NONE
    name = str(entry.get("id") or entry.get("name") or "?")
    t = entry.get("tools")
    if t is True:
        return OPENCODE_TOOLS_OK
    if t is False:
        return OPENCODE_TOOLS_BAD % name
    return OPENCODE_TOOLS_UNKNOWN % name


# ── the OpenCode LANDING ─────────────────────────────────────────────────────
# THE COMPLAINT THIS ANSWERS: the tab opened OpenCode's home screen, which read
# "Nothing here yet — Create a session to get started" beside a Projects rail whose
# only entry was "Add project". Everything was running; being useful was gated on a
# setup step, which is indistinguishable from broken.
#
# There is nothing to seed. Read at pin 1.18.19: the Projects rail is CLIENT state,
# persisted in the webview's own localStorage under `opencode.global.dat:server`
# (packages/app/src/context/server.tsx:263-274, utils/persist.ts:491-494) — an
# internal, migrating format inside WebKit's storage that we have no business writing.
# The home session list is filtered by that same local rail
# (pages/home/home-sessions-controller.tsx:248-256), so pre-creating a session
# server-side would not clear the empty screen either.
#
# What DOES work is its own routing: `/:dir` is a DirectoryLayout whose `:dir` is the
# base64url of an absolute path (packages/app/src/app.tsx:633-636,
# pages/directory-layout.tsx:80-84, core/src/util/encode.ts:1-5), and `/:dir/session`
# with no session id opens a NEW-SESSION composer for that directory (app.tsx:94-101).
# So the tab is pointed straight at our workspace and the home screen never appears.
#
# ⚠️ THIS IS A DEEP LINK INTO A THIRD-PARTY SPA'S INTERNAL ROUTE SHAPE. The downside is
# bounded and was checked: an undecodable `:dir` toasts and navigates to "/"
# (directory-layout.tsx:97-111), i.e. the worst case is exactly today's behaviour. A
# contract test pins the route and the encoder so a pin bump trips instead of quietly
# regressing to the empty home.
#
# ⚠️ It is a BRIDGE route rather than a URL baked into app/main.swift because only the
# bridge knows both ROOT (repo vs snapshot) and the configured port, and because a
# route can be tested here. Cost: the tab needs the bridge up — which it always is,
# since the bridge is what the app launches and Mission Control is served from it.
def opencode_landing_url(root, port) -> str:
    """PURE. The URL the OpenCode tab should open. base64url, no padding, exactly as
    upstream's own `base64Encode` produces it (core/src/util/encode.ts)."""
    ws = os.path.join(str(root), "data", "opencode-workspace")
    b64 = base64.urlsafe_b64encode(ws.encode("utf-8")).decode("ascii").rstrip("=")
    try:
        p = int(port)
    except (TypeError, ValueError):
        p = 4096
    if not (0 < p < 65536):
        p = 4096
    return f"http://127.0.0.1:{p}/{b64}/session"


@app.get("/opencode")
def opencode_landing() -> Response:
    """307 → OpenCode's new-session composer for data/opencode-workspace."""
    port = ((cfg().get("components") or {}).get("opencode") or {}).get("port") or 4096
    return Response(status_code=307,
                    headers={"Location": opencode_landing_url(ROOT, port),
                             "Cache-Control": "no-store"})


@app.get("/api/models")
def api_models() -> JSONResponse:
    """Installed models (from OUR registry data/models.json — the only source since
    jan was retired), the active runner model + state, aux state, and the
    model-RAM ledger (approx by file size).

    AUDIO models (kind:"audio") are partitioned OUT of `installed` and returned under
    `audio` instead. This is load-bearing: `installed` feeds the runner switch, the
    aux picker and the chat model popover, and a TTS backbone in any of those would
    wedge the runner. The partition lives in ONE place (bridge/voice.split_audio)."""
    import json as _json
    installed, audio, hidden, err = [], [], [], None
    c = cfg()
    rc = c.get("runner", {})
    adapter = (rc.get("adapter") or "auto")

    def _load_registry():
        reg = ROOT / "data" / "models.json"
        if not reg.exists():
            subprocess.run(["python3", "scripts/seed_registry.py"],
                           cwd=ROOT, capture_output=True, text=True,
                           timeout=60, check=False)
        return _json.loads(reg.read_text()).get("models", [])
    try:
        try:
            models = _load_registry()
        except Exception:
            # missing/invalid → seed once and retry
            subprocess.run(["python3", "scripts/seed_registry.py"],
                           cwd=ROOT, capture_output=True, text=True,
                           timeout=60, check=False)
            models = _json.loads((ROOT / "data" / "models.json").read_text()).get("models", [])
        models, _audio_models = _split_audio(models)
        # HIDDEN: a read-only import the user does not want in their lists (Debi's
        # ask — the HF cache and LM Studio both hand us models we will never use).
        # They are filtered out of `installed` and `audio` at the BRIDGE, not in the
        # panel, so a hidden model cannot leak into the chat popover, the runner
        # switch, or the aux picker through a renderer that forgot to filter.
        hidden = [_hidden_view(m) for m in (models + _audio_models) if _is_hidden(m)]
        models = [m for m in models if not _is_hidden(m)]
        _audio_models = [m for m in _audio_models if not _is_hidden(m)]
        if _voice is not None:
            audio = [_voice.audio_entry_view(m) for m in _audio_models]
        for m in models:
            installed.append({
                "id": m.get("id"), "name": m.get("name") or m.get("id"),
                "size_bytes": m.get("size_bytes"),
                "engine": ("mlx" if m.get("format") == "mlx" else "llamacpp"),
                "embedding": False,
                "capabilities": _model_caps(m),
                # TOOL-CALLING (the OpenCode slice): True / False / None, derived
                # from the model's own chat template by bridge/modeltools.py.
                # `None` = we could not tell, and the panel draws NOTHING for it —
                # a missing pill must never read as "this model cannot".
                "tools": (m.get("tools") if isinstance(m.get("tools"), bool) else None),
                "format": m.get("format", "gguf"),
                "ctx": m.get("ctx"), "source": m.get("source"), "path": m.get("path"),
                # Per-model sampling: the READ side of /api/models/settings lives
                # here (one key on a payload the panel already polls) rather than in
                # a second route. `sampling` is the rendered view (engine-filtered
                # fields + harness defaults + overrides); `settings` is the raw pin.
                "settings": (m.get("settings") if isinstance(m.get("settings"), dict)
                             else None),
                "sampling": sampling_view(m),
                # Same pattern for the LOAD group (v2): raw pin + rendered view.
                "load": (m.get("load") if isinstance(m.get("load"), dict) else None),
                "loadview": load_view(m),
                # v2.1: the shared Apply & reload row — sampling floors + load, in
                # one claim, so an MLX model (no Load fields) still gets the chip.
                "launch": launch_view(m, _LOAD_AT_LAUNCH.get(m.get("id")))})
    except Exception as e:
        err = str(e)[:200]
        hidden = []
    port = rc.get("port")
    # Authoritative "live" = what the runner is ACTUALLY serving (ISSUE C), not just
    # "runner.model is set + port answers". runner_up is now gated on a real load, so
    # the Models pane and MC agree; live_id names the loaded model for the "live" pill.
    live_id = _live_model_id(int(port)) if port else None
    ax = c.get("aux", {}) or {}
    aux = {"model": ax.get("model") or "", "port": ax.get("port"),
           "up": _port_alive_sync(int(ax["port"])) if ax.get("port") else False}
    ledger = {"used_bytes": _loaded_models_bytes(), "budget_bytes": _budget_bytes()}
    vcfg = _voice_cfg()
    return JSONResponse({
        "installed": installed, "active": rc.get("model"),
        "runner_up": bool(live_id), "live_id": live_id,
        "aux": aux, "adapter": adapter, "ledger": ledger, "error": err,
        # Phase A (Models → Audio tab) reads these; the chat lists above never see them.
        "audio": audio, "voice": vcfg,
        # The models the user hid — a light view, only ever used to draw the
        # "N hidden — show" affordance and to unhide them again.
        "hidden": hidden})


@app.post("/api/models/rescan")
def api_models_rescan() -> JSONResponse:
    """Re-run the registry seed the same way api_models / start_component.sh do it
    (subprocess to scripts/seed_registry.py). seed_registry.merge() prunes the
    re-scanned sets ('local'/'jan-import'/'lmstudio-import') by replacing them with a
    fresh scan, so models the user deleted in LM Studio (or Jan) drop out; source
    "download" entries + known ctx are preserved. Does NOT touch the runner/live
    model. Returns {ok, count} (models after rescan); never raises into the caller."""
    import json as _json
    try:
        r = subprocess.run(["python3", "scripts/seed_registry.py"],
                           cwd=ROOT, capture_output=True, text=True,
                           timeout=120, check=False)
        if r.returncode != 0:
            return JSONResponse(
                {"ok": False, "error": (r.stderr or r.stdout or "seed failed")[:300]},
                status_code=500)
        reg = ROOT / "data" / "models.json"
        count = len(_json.loads(reg.read_text()).get("models", []))
        return JSONResponse({"ok": True, "count": count})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:300]}, status_code=500)


_SWITCH = {"busy": False, "log": ""}


def _do_switch(new_id: str, old_id: str, restart_hermes: bool, restart_ody: bool) -> None:
    """Fable QA hardening: check exit codes (a failed load must NOT report success),
    and roll harness.yaml back to the previous model on failure so the next Start
    uses a known-good model instead of retrying a broken one."""
    try:
        _SWITCH["log"] = (f"downloading + loading {new_id} — large downloads take minutes…"
                          if "/" in new_id else f"loading {new_id}…")
        r = _script("start_component.sh", "runner")
        if r.returncode != 0:
            _set_runner_model(old_id)   # rollback pin; runner is down but recoverable
            tail = (r.stdout + r.stderr)[-400:]
            _SWITCH["log"] = f"FAILED to load {new_id} — reverted to {old_id}. {tail}"
            return
        # The runner is now running with whatever `load` was saved at this moment —
        # record it so the panel can say "not applied yet" only when it is TRUE.
        _record_load_launch(new_id)
        if restart_hermes:
            _SWITCH["log"] = "re-wiring Hermes…"
            if _script("start_component.sh", "hermes").returncode != 0:
                _SWITCH["log"] = f"active: {new_id} — but Hermes restart FAILED (see logs)"
                return
        if restart_ody:
            _SWITCH["log"] = "re-wiring Odysseus…"
            if _script("start_component.sh", "odysseus").returncode != 0:
                _SWITCH["log"] = f"active: {new_id} — but Odysseus restart FAILED (see logs)"
                return
        _SWITCH["log"] = f"active: {new_id}"
    except Exception as e:
        _SWITCH["log"] = f"switch error: {str(e)[:200]}"
    finally:
        _SWITCH["busy"] = False


@app.post("/api/models/switch")
async def api_switch_model(req: Request) -> JSONResponse:
    """Switch the runner's model (loads it via the engine dispatch), then re-fan-out
    the new model NAME to any running Hermes/Odysseus (their configs bind the name).
    Runs in the background — poll /api/models/switch-status. `id` must be an INSTALLED
    registry model (HF repo ids are rejected — downloads go via the download manager)."""
    if _SWITCH["busy"]:
        return JSONResponse({"ok": False, "log": "a switch is already in progress"}, status_code=409)
    new_id = ((await req.json()).get("id") or "").strip()
    if not new_id:
        return JSONResponse({"ok": False, "log": "no model id"}, status_code=400)
    c = cfg()
    if (c.get("runner", {}) or {}).get("adapter") in ("llamacpp", "mlx", "auto") and "/" in new_id:
        return JSONResponse(
            {"ok": False, "log": "downloads arrive with the download manager (next slice) — this adapter loads only installed models"},
            status_code=400)
    _bad = _reject_if_audio(new_id)
    if _bad is not None:
        return _bad
    old_id = (c.get("runner", {}) or {}).get("model") or ""
    # Model-RAM ledger gate: candidate + the OTHER slot (aux) must fit the budget.
    # Switching the MAIN slot replaces its own usage → exclude "main" from "other".
    _models = _registry_models()
    _cand = _model_size(_models, new_id)
    _other = _loaded_models_bytes(exclude_slot="main")
    _budget = _budget_bytes()
    if _cand and not _within_budget(_cand, _other, _budget):
        _g = lambda b: round(b / (1024 ** 3), 1)
        msg = (f"would exceed model-RAM budget: {_g(_cand)} + {_g(_other)} > "
               f"{_g(_budget)} GB — eject something first")
        return JSONResponse({"ok": False, "log": msg}, status_code=409)
    hermes_up, ody_up = _running_sync("hermes", c), _running_sync("odysseus", c)
    # set BEFORE the thread: no double-switch race. (Download progress lives in the
    # download manager now — "/" repo ids are rejected above, so no HF fetch here.)
    _SWITCH.update(busy=True, log="starting…")
    _set_runner_model(new_id)
    threading.Thread(target=_do_switch, args=(new_id, old_id, hermes_up, ody_up), daemon=True).start()
    return JSONResponse({"ok": True, "log": "switch started"})


def _eject_runner() -> None:
    """Stop the main runner by PORT AND clear the active-model designation
    (runner.model → empty) so a later Start does NOT silently resurrect the model.
    Shared by the eject endpoint and the delete endpoint (deleting a live model)."""
    rc = cfg().get("runner", {}) or {}
    port = rc.get("port")
    if port:
        # legacy jan-supervisor sweep (harmless no-op post-Jan) + kill whatever holds the port
        subprocess.run(f'pkill -f "jan serve.*port[= ]{int(port)}"', shell=True, check=False)
        _kill_port_listener(int(port), force=True, component="runner")
    (ROOT / "data" / "runner.pid").unlink(missing_ok=True)
    _clear_expected("runner")     # intentional → "stopped", not "degraded"
    PROV.pop("runner", None)
    _set_runner_model("")         # no active model — Start must route the user to pick


@app.post("/api/models/eject")
def api_eject_model() -> JSONResponse:
    """Eject the live model (Fable ISSUE 2 state machine): stop the runner by PORT
    AND clear the active-model designation. Going live again requires an explicit
    Load from the Models pane. Frees the main slot's RAM in the ledger."""
    _eject_runner()
    return JSONResponse({"ok": True})


# ── Delete an APP-OWNED model (files live under data/models/) ──────────────────
# App-owned = source in {download, local}: the harness downloaded these or holds the
# local files under data/models/<folder>/, so we may delete both the files and the
# registry entry. Read-only imports (lmstudio-import, jan-import) point at files the
# harness does NOT own (e.g. the user's LM Studio library) — deleting those would
# nuke the user's data, so they are HARD-refused here (the panel hides Delete for
# them too). Pure predicate factored out + unit-tested (see bridge/tests).
_DELETABLE_SOURCES = ("download", "local")


def _deletable_target(entry: dict, models_root: str):
    """Return (target_dir, None) if `entry` is an app-owned model whose files live
    strictly UNDER models_root and may be safely deleted; else (None, reason).

    Pure/testable: uses only os.path (realpath normalizes even non-existent paths,
    so tests don't need real files). The target is the model's OWN folder — the
    first path segment beneath models_root — regardless of whether the registry
    `path` points at a file (…/model.gguf) or the model dir itself (MLX). Any path
    that resolves outside models_root (traversal, symlink escape, an import pointing
    elsewhere) fails the containment check and is refused."""
    import os as _os
    src = (entry or {}).get("source")
    if src not in _DELETABLE_SOURCES:
        return None, (f"'{src or 'unknown'}' models are read-only imports the harness "
                      f"does not own — remove them in the app that manages them")
    path = (entry or {}).get("path")
    if not path:
        return None, "no file path on record for this model"
    real_root = _os.path.realpath(_os.path.expanduser(str(models_root)))
    real_path = _os.path.realpath(_os.path.expanduser(str(path)))
    # Must sit strictly under the harness models dir (never the dir itself, never outside).
    if real_path != real_root and not real_path.startswith(real_root + _os.sep):
        return None, "model path is outside the harness models directory"
    rel = _os.path.relpath(real_path, real_root)
    first = rel.split(_os.sep)[0]
    if first in ("", ".", ".."):
        return None, "could not resolve a model folder under the models directory"
    return _os.path.join(real_root, first), None


@app.post("/api/models/delete")
async def api_delete_model(req: Request) -> JSONResponse:
    """Delete an app-owned model: remove its folder under data/models/ + its registry
    entry. HARD-guarded — only source in {download, local} AND a realpath strictly
    under data/models/ is ever deleted (never an LM Studio / Jan import, never a path
    outside our dir). If the model is currently live (main runner or aux), it is
    ejected/stopped first."""
    import os as _os, shutil as _shutil
    mid = ((await req.json()).get("id") or "").strip()
    if not mid:
        return JSONResponse({"ok": False, "log": "no model id"}, status_code=400)
    entry = next((m for m in _registry_models() if m.get("id") == mid), None)
    if not entry:
        return JSONResponse({"ok": False, "log": f"model '{mid}' not in registry"}, status_code=404)
    models_root = str(ROOT / "data" / "models")
    target, reason = _deletable_target(entry, models_root)
    if not target:
        print(f"[delete] reject {mid!r}: {reason}", flush=True)
        return JSONResponse({"ok": False, "log": reason}, status_code=400)
    # Belt-and-suspenders: re-affirm containment on the resolved target itself.
    real_root = _os.path.realpath(models_root)
    if not (target == _os.path.join(real_root, _os.path.basename(target))
            and target.startswith(real_root + _os.sep)):
        print(f"[delete] reject {mid!r}: target {target} not under {real_root}", flush=True)
        return JSONResponse({"ok": False, "log": "refused: unsafe target path"}, status_code=400)

    c = cfg()
    rc = c.get("runner", {}) or {}
    port = rc.get("port")
    live = _live_model_id(int(port)) if port else None
    was_live = (live == mid) or ((rc.get("model") or "") == mid)
    if was_live:
        _eject_runner()   # stop the runner + clear runner.model before removing files
    # If it's the aux model, stop aux (if up) + clear the aux designation.
    ax = c.get("aux", {}) or {}
    was_aux = (ax.get("model") or "") == mid
    if was_aux:
        if ax.get("port"):
            _aux_kill(int(ax["port"]))
        _set_yaml_model("aux", "")
    # If it was a VOICE default, clear that slot too — leaving harness.yaml pointing at
    # deleted weights would only fail later, at speak time, far from this click.
    vc = _voice_cfg()
    was_voice = [k for k in ("tts_model", "stt_model") if vc.get(k) == mid]
    # …and if it is RESIDENT in the persistent worker, kill that first: the process
    # holds the weights open, and on a re-download the same path would then serve a
    # deleted checkpoint from memory.
    if _voice is not None:
        _voice.worker_stop_if_model(mid, "model deleted")
    for k in was_voice:
        _set_yaml_scalar("voice", k, "")

    if _os.path.isdir(target):
        _shutil.rmtree(target, ignore_errors=True)
    _registry_drop(mid)
    print(f"[delete] removed {mid!r} (dir {target}, was_live={was_live}, "
          f"was_aux={was_aux}, was_voice={was_voice or 'no'})", flush=True)
    return JSONResponse({"ok": True, "id": mid, "was_live": was_live,
                         "was_aux": was_aux, "was_voice": was_voice})


@app.get("/api/models/switch-status")
def api_switch_status() -> JSONResponse:
    """Poll target: busy flag + human-readable log line. (Download progress moved to
    the download manager — this endpoint tracks model LOADS only.)"""
    return JSONResponse({k: _SWITCH.get(k) for k in ("busy", "log")})


@app.post("/api/models/switch-cancel")
def api_switch_cancel() -> JSONResponse:
    """Cancel an in-flight switch: kill the runner on its port AND the waiting start
    script (legacy jan-serve sweep kept, harmless) — _do_switch then sees the failure
    and rolls the model pin back to the previous one automatically."""
    if not _SWITCH.get("busy"):
        return JSONResponse({"ok": False, "log": "no switch in progress"}, status_code=400)
    port = int((cfg().get("runner", {}) or {}).get("port") or 6767)
    subprocess.run(f'pkill -f "jan serve.*port[= ]{port}"', shell=True, check=False)
    _kill_port_listener(port, force=True, component="runner")
    subprocess.run('pkill -f "start_component.sh runner"', shell=True, check=False)
    return JSONResponse({"ok": True, "log": "cancelling — pin will revert to the previous model"})


# ── Aux runner (optional): a small second model on its own port for Odysseus's
# Background Tasks (titles, search-query gen, memory extraction) so they stop
# hogging the main runner's single slot. Model is user-chosen from installed
# models ("Set aux" in the Models pane) — never hardcoded.
@app.post("/api/aux/set")
async def aux_set(req: Request) -> JSONResponse:
    new_id = ((await req.json()).get("id") or "").strip()
    if not new_id:
        return JSONResponse({"ok": False, "log": "no model id"}, status_code=400)
    _bad = _reject_if_audio(new_id)
    if _bad is not None:
        return _bad
    _set_yaml_model("aux", new_id)
    return JSONResponse({"ok": True, "model": new_id})


def _aux_kill(port: int) -> None:
    for pat in (f'jan serve.*port[= ]{port}', f'llama-server.*--port {port}',
                f'mlx_lm.server.*--port {port}', f'mlx_vlm.server.*--port {port}'):
        subprocess.run(f'pkill -f "{pat}"', shell=True, check=False)
    _kill_port_listener(port, force=True, component="aux")


@app.post("/api/aux/start")
def aux_start() -> JSONResponse:
    """Launch the aux model on its own port using the SAME engine dispatch as the
    main runner (registry format: gguf→llama-server, mlx→mlx servers). The old
    `jan serve` path knew nothing about harness-downloaded models."""
    import json as _json, os as _os, glob as _glob
    ax = cfg().get("aux", {}) or {}
    model, port = ax.get("model") or "", int(ax.get("port") or 6768)
    key = ax.get("api_key", "harness-aux")
    if not model:
        return JSONResponse({"ok": False, "log": "no aux model set — use 'Set aux' on an installed model"}, status_code=400)
    try:
        models = _json.loads((ROOT / "data" / "models.json").read_text()).get("models", [])
    except Exception:
        models = []
    m = next((x for x in models if x.get("id") == model), None)
    if not m or not m.get("path"):
        return JSONResponse({"ok": False, "log": f"aux model '{model}' not in registry"}, status_code=400)
    fmt, path, mmproj = m.get("format", "gguf"), m["path"], m.get("mmproj")
    # Model-RAM ledger gate: aux candidate + the OTHER slot (main) must fit budget.
    _cand = int(m.get("size_bytes") or 0)
    _other = _loaded_models_bytes(exclude_slot="aux")
    _budget = _budget_bytes()
    if _cand and not _within_budget(_cand, _other, _budget):
        _g = lambda b: round(b / (1024 ** 3), 1)
        return JSONResponse(
            {"ok": False, "log": (f"would exceed model-RAM budget: {_g(_cand)} + "
                                  f"{_g(_other)} > {_g(_budget)} GB — eject something first")},
            status_code=409)
    _aux_kill(port)
    if fmt == "mlx":
        venv = ROOT / "data" / "mlx-venv"
        if not (venv / "bin" / "python").exists():
            return JSONResponse({"ok": False, "log": "mlx runtime missing — run scripts/install_mlx.sh"}, status_code=500)
        mod = "mlx_vlm.server" if m.get("vision") else "mlx_lm.server"
        srv = venv / "bin" / mod
        cmd = ([str(srv)] if srv.exists() else [str(venv / "bin" / "python"), "-m", mod])
        cmd += ["--model", path, "--host", "127.0.0.1", "--port", str(port)]
    else:
        binp = (cfg().get("runner") or {}).get("binary") or ""
        if not binp:
            # SHARED binary-discovery order (keep identical in start_component.sh):
            #   explicit runner.binary → OUR pin (data/llamacpp) → Jan backends → LM Studio.
            pin_bin = str(ROOT / "data" / "llamacpp" / "build" / "bin" / "llama-server")
            if _os.path.isfile(pin_bin) and _os.access(pin_bin, _os.X_OK):
                binp = pin_bin
            else:
                cands = (sorted(_glob.glob(_os.path.expanduser(
                            "~/Library/Application Support/Jan/data/llamacpp/backends/*/macos-arm64/build/bin/llama-server")),
                            key=_os.path.getmtime, reverse=True)
                         or sorted(_glob.glob(_os.path.expanduser("~/.lmstudio/extensions/backends/*/llama-server")),
                            key=_os.path.getmtime, reverse=True))
                if not cands:
                    return JSONResponse({"ok": False, "log": "no llama-server binary found — run scripts/install_llamacpp.sh"}, status_code=500)
                binp = cands[0]
        helptxt = ""
        try:
            hp = subprocess.run([binp, "--help"], capture_output=True, text=True, timeout=15)
            helptxt = (hp.stdout or "") + (hp.stderr or "")
        except Exception:
            pass
        # Aux tasks are short — small ctx keeps the second model light in RAM.
        ctx = m.get("ctx") or 8192
        cmd = [binp, "--no-context-shift", "--host", "127.0.0.1", "--port", str(port),
               "--alias", model, "--ctx-size", str(ctx), "--no-cont-batching",
               "--cache-ram", "-1", "--fit", "off", "--model", path, "--parallel", "1"]
        if mmproj:
            cmd += ["--mmproj", mmproj]
        if "--api-key" in helptxt:
            cmd += ["--api-key", key]
    logf = open(ROOT / "data" / "logs" / "aux.log", "ab")
    subprocess.Popen(cmd, stdout=logf, stderr=logf, start_new_session=True)
    return JSONResponse({"ok": True, "log": "loading in background — refresh in ~20-60s"})


@app.post("/api/aux/stop")
def aux_stop() -> JSONResponse:
    ax = cfg().get("aux", {}) or {}
    _aux_kill(int(ax.get("port") or 6768))
    return JSONResponse({"ok": True})
