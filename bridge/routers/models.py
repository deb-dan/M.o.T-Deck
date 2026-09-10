"""ROUTER — the Models pane: list, hide, switch, eject, delete, the RAM ledger, aux."""
from __future__ import annotations

import base64
import asyncio
import os
import subprocess
import time
# ⚠️ `sys` WAS NEVER IMPORTED HERE, and the S28 rebind has referenced `sys.executable`
# since v1.5.62 (_rebind_odysseus_offline's fallback). It never fired because the
# Odysseus venv has always existed on this machine, so a NameError sat dormant on the
# one path that runs when a component is half-provisioned. Found by running the new
# rescan fan-out against the real snapshot — a code read would not have caught it.
import sys
import threading
from fastapi import Request
from fastapi.responses import JSONResponse, Response
from ..core.appctx import ROOT, _voice, app
from ..core.events import publish
from ..core.health import file_state_track
from ..core.modeldelete import (delete_owned_model_transaction,
                                delete_target_collisions as _delete_target_collisions,
                                deletable_target as _deletable_target,
                                recover_owned_model_transaction)
from ..core.modelreg import (artifact_probe, is_source_unlisted, registry_lock,
                             source_availability, write_registry)
from ..core.modelid import _live_model_id
from ..core.procs import NO_PIDFILE_NOTE, PROV, _clear_expected, _kill_port_listener, _port_alive_sync, _registry_models, _running_sync, _script, _script_tracked, cfg, reap_pidfile, stop_owned_component
from ..core.yamlset import _set_runner_model, _set_yaml_model, _set_yaml_scalar
from .downloads import _registry_update
from .model_visibility import (HIDEABLE_SOURCES, _hidden_view, _hideable,
                               _is_hidden, api_models_hide)
from .sampling import _LOAD_AT_LAUNCH, _record_load_launch, launch_view, load_view, sampling_view


_MODEL_DELETE_RECOVERY_ERROR = ""


def _delete_assignment_resolver(label: str, old: str):
    if label == "runner.model":
        return (lambda: _set_runner_model(""), lambda: _set_runner_model(old))
    if label == "aux.model":
        return (lambda: _set_yaml_model("aux", ""),
                lambda: _set_yaml_model("aux", old))
    if label in {"voice.tts_model", "voice.stt_model"}:
        field = label.split(".", 1)[1]
        return (lambda: _set_yaml_scalar("voice", field, ""),
                lambda: _set_yaml_scalar("voice", field, old))
    raise ValueError(f"unknown saved model assignment: {label}")


async def _recover_interrupted_model_delete() -> None:
    global _MODEL_DELETE_RECOVERY_ERROR
    _MODEL_DELETE_RECOVERY_ERROR = await asyncio.to_thread(
        recover_owned_model_transaction,
        root=ROOT, assignment_resolver=_delete_assignment_resolver) or ""
    if _MODEL_DELETE_RECOVERY_ERROR:
        print(f"[delete] ATTENTION: {_MODEL_DELETE_RECOVERY_ERROR}", flush=True)


# An interrupted destructive operation is reconciled before the first request. The
# error remains visible in /api/models instead of taking the whole bridge down or being
# hidden in a log line.
app.router.on_startup.append(_recover_interrupted_model_delete)


# ── A FOREIGN APP'S llama-server IS NOT OUR PINNED CONTRACT (bug-echo W-04) ─────
# ⚠️ KEEP THIS IDENTICAL, IN RULES AND IN WORDS, TO scripts/start_component.sh's runner
# branch — the binary-discovery order is already declared shared there, and a gate that
# exists on only one of the two paths is a gate a user finds by getting past it.
#
# The last two steps of that order run a binary that belongs to Jan or LM Studio. A
# different app upgrades it whenever it likes, while this MOT Deck's probe/auth
# expectations are pinned against ONE build: llama.cpp b10662 made /v1/models REQUIRE a
# key where the build before it did not, and the 401 regression that caused cost a
# session to find. Starting a stranger's binary of unknown vintage re-opens exactly that.
# An EXPLICIT runner.binary is exempt — that is a person naming a binary on purpose.
FOREIGN_RUNNER_ENV = "MOT_DECK_ALLOW_FOREIGN_RUNNER"


def _llama_build(binp: str) -> str:
    """The llama.cpp BUILD NUMBER this binary reports ("10662"), or "". Never raises."""
    import re as _re
    try:
        p = subprocess.run([binp, "--version"], capture_output=True, text=True,
                           timeout=15)
    except Exception:                                            # noqa: BLE001
        return ""
    m = _re.search(r"build (\d+)", (p.stdout or "") + (p.stderr or ""))
    return m.group(1) if m else ""


def foreign_runner_gate(binp: str, owner: str) -> tuple:
    """(note, refusal). `owner` is the app the binary belongs to ("" = ours or explicit).

    A matching build passes with a note; a mismatched or unreadable one is REFUSED with
    the install command, unless MOT_DECK_ALLOW_FOREIGN_RUNNER=1 says otherwise. Either
    way the binary and its build are NAMED — the one thing this must never do again is
    run a foreign llama-server without saying so.
    """
    if not owner:
        return "", ""
    pin = str(((cfg().get("runner") or {}).get("llamacpp_pin") or "")).strip()
    build = _llama_build(binp)
    said = (f"⚠️ the runner binary is not ours — it belongs to {owner}: {binp} "
            f"(build {build or 'unreadable'}; MOT Deck is pinned to "
            f"{pin or 'no pin set'})")
    if pin and build and build == pin.lstrip("b"):
        return said + " — the build MATCHES the pin, so the pinned contracts hold.", ""
    if os.environ.get(FOREIGN_RUNNER_ENV) == "1":
        return (said + f" — {FOREIGN_RUNNER_ENV}=1, starting it anyway, deliberately. "
                "If /v1/models 401s or the panel reads the runner as down, suspect this "
                "first."), ""
    return said, (
        said + f". REFUSED: {owner} can change that binary at any time without telling "
        "us, and our /v1/models auth probe is pinned per build (b10662 made that "
        "endpoint require a key where the build before it did not; the same drift the "
        "other way reads as 'the runner is down'). Run ./scripts/install_llamacpp.sh, "
        "or set runner.binary in motdeck.yaml to name a binary on purpose, or set "
        f"{FOREIGN_RUNNER_ENV}=1 knowing the above.")




def _split_audio(models: list) -> tuple:
    """(chat, audio) partition of a registry list. Degrades to 'everything is a chat
    model' when bridge/voice.py is unavailable — never crashes the Models pane."""
    if _voice is not None:
        return _voice.split_audio(models)
    return list(models or []), []


def _voice_cfg() -> dict:
    """motdeck.yaml `voice:` block, normalised. Empty string = capability off."""
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
    from bridge.core import memory as _mem
    sysv = _mem.system_view()
    total_gb = (sysv.get("total_bytes") or 0) / (1024 ** 3)
    dynamic_default = min(48.0, round(total_gb * 0.70, 1)) if total_gb > 0 else 48.0
    mem = cfg().get("memory", {}) or {}
    raw_gb = mem.get("budget_gb")
    if raw_gb == "auto" or raw_gb is None:
        gb = dynamic_default
    else:
        try:
            gb = float(raw_gb)
            if total_gb > 0 and gb > total_gb:
                gb = dynamic_default
        except (TypeError, ValueError):
            gb = dynamic_default
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
    HERE: voice.py must not learn to read motdeck.yaml."""
    other = _loaded_models_bytes(exclude_slot="voice")
    budget = _budget_bytes()
    if size_bytes and not _within_budget(int(size_bytes), other, budget):
        return (f"loading that voice model would exceed the model-RAM budget "
                f"({(int(size_bytes) + other) / 1024**3:.1f} > {budget / 1024**3:.0f} GB) "
                f"— eject a chat model first")
    return None


def _wants_confirm(body: dict) -> bool:
    """Did the caller EXPLICITLY consent? Nothing else counts as consent — not a
    retry, not a second click, not a header. Same predicate shape the music lane
    already uses, so the two heavy lanes cannot drift apart."""
    if not isinstance(body, dict):
        return False
    v = body.get("confirm")
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in ("1", "true", "yes")


def _fit_advice(mid: str, slot: str = "main") -> "dict | None":
    """The fit verdict for loading `mid` into `slot`, or None if we cannot say.

    ⚠️ THE SLOT IS NOT COSMETIC. A MAIN-slot switch EJECTS the resident model, so its
    footprint comes back as budget; an AUX start puts a second model beside the first
    and frees nothing. Crediting the runner's 13 GB to an aux start would be a
    confident "fits" for a load that doubles the machine's model memory.

    None is deliberate and it is the safe direction: an engine that cannot produce a
    verdict must not produce a REFUSAL either. Whatever goes wrong here — the header
    unreadable, the oracle missing, Metal unreachable — the load proceeds exactly as
    it did before this feature existed."""
    try:
        from ..core import fit as _fitmod
        from ..core import memory as _memmod
        entry = next((m for m in _split_audio(_registry_models())[0]
                      if m.get("id") == mid), None)
        if entry is None:
            return None
        snap = _memmod.snapshot()
        rc = cfg().get("runner", {}) or {}
        live_up = bool(rc.get("port") and _port_alive_sync(int(rc["port"])))
        # What the runner REPORTS serving, not what motdeck.yaml pins — the two can
        # disagree after a failed switch, and crediting the wrong model's memory is
        # how the advisor starts describing a process that is not there.
        live_id = ((_live_model_id(int(rc["port"])) or rc.get("model") or "")
                   if live_up else "")
        runner_row = next((r for r in (snap.get("components") or [])
                           if r.get("name") == "runner"), None)
            # ⚠️ A RELOAD OF THE MODEL ALREADY RESIDENT ALSO FREES IT. The first draft
            # credited the runner's footprint only when the target was a DIFFERENT
            # model, so the live model's own row read "Over by ~3.7 GB" — a model
            # visibly running, and running fine, marked as not fitting. Any switch
            # into the main slot ejects what is there first, including itself.
        freeing = int((runner_row or {}).get("footprint_bytes") or 0) if (
            slot == "main" and live_up) else 0
        hold = [{"name": r.get("name"),
                 "title": (live_id if r.get("name") == "runner" and live_id
                           else (r.get("label") or r.get("name"))),
                 "footprint_bytes": r.get("footprint_bytes") or 0}
                for r in (snap.get("components") or [])
                if r.get("name") not in ("bridge", "app")
                and not (r.get("name") == "runner" and freeing)]
        got = _fitmod.fit(entry, None, freeing_bytes=freeing, holders=hold,
                          replaces=(live_id if (freeing and live_id != mid) else ""))
        got["replaces"] = live_id if (freeing and live_id != mid) else ""
        return got
    except Exception as e:                                       # noqa: BLE001
        print(f"[fit] advisory unavailable for {mid}: {str(e)[:120]}", flush=True)
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


def live_tools_warning(entry, who: str = "OpenCode") -> str:
    """opencode_tools_warning with the PRODUCT NOUN swapped. PURE.

    ⚠️ WHY THIS EXISTS RATHER THAN A SECOND SET OF CONSTANTS (S34). The DeepSeek
    MOT Deck lane has the identical requirement — every mutation is a native tool call,
    no text-edit fallback — so start_plan reuses this decision table for it. Reusing it
    VERBATIM would have printed "OpenCode needs it" on the DeepSeek card: a sentence
    about a product the user is not starting, which is the LIES-TO-USER class, not a
    cosmetic slip. Duplicating the four constants per component would instead give the
    fact two answers, which is how the wording drifts.
    So: ONE decision table, ONE wording, and the product noun substituted at the edge.
    The default keeps every existing caller byte-identical.
    """
    s = opencode_tools_warning(entry)
    if not s or not who or who == "OpenCode":
        return s
    return s.replace("OpenCode", who)


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


# ══ THE PERSISTED `absent` FLAG (S29) ═══════════════════════════════════════════
# The two-strike file verdict already existed (U15, core/health.file_state_track) and
# it is honest — but it lived only in the /api/models RESPONSE. Nothing on disk carried
# it, so every OTHER enumerator (the four seeders, all of which read data/models.json
# directly and none of which stat anything) went on offering models whose weights Debi
# had deleted days earlier. Writing the verdict INTO the row is what lets one file be
# the single source of truth for "what may be offered".
#
# Three rules:
#   1. WRITE ONLY ON A CHANGE. This runs inside a polled GET; a read-modify-write per
#      poll would rewrite a 20KB file every 6s for no reason.
#   2. FLAG, NEVER DELETE. The row keeps its identity (id, ctx, pinned voice, sampling
#      overrides). The file may be on a volume that is unplugged. Removal is RESCAN's
#      job alone, under an explicit human click, and it prints what it took.
#   3. ONLY A DEBOUNCED VERDICT MAY WRITE. "checking" (one missed stat — what a sleeping
#      network mount produces) and "unknown" change nothing, in either direction.
def _persist_absent(states: dict) -> None:
    """`states` is {model id: file_state}. Best-effort; never raises into the route."""
    import json as _json
    from ..core.modelreg import ABSENT_KEY
    try:
        reg = ROOT / "data" / "models.json"
        with registry_lock(str(reg)):
            data = _json.loads(reg.read_text())
            models = data.get("models") or []
            dirty = False
            for m in models:
                if not isinstance(m, dict):
                    continue
                st = states.get(m.get("id"))
                if st == "gone" and m.get(ABSENT_KEY) is not True:
                    try:
                        probe = artifact_probe(m)
                        source = source_availability(m, probe).get("state")
                    except Exception:                              # noqa: BLE001
                        probe = {"state": "unknown"}
                        source = "unknown"
                    # The two-strike response can be stale by this second read.  Only a
                    # fresh missing probe authorizes an absent flag; ready clears through
                    # the normal `ok` pass rather than turning a returned model red.
                    if probe.get("state") == "missing" and source == "available":
                        m[ABSENT_KEY] = True
                        dirty = True
                elif st == "ok" and m.get(ABSENT_KEY) is not None:
                    m.pop(ABSENT_KEY, None)
                    dirty = True
            if not dirty:
                return
            write_registry(str(reg), data)
    except Exception:                                          # noqa: BLE001
        pass                              # a registry we cannot rewrite is not an alarm


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
        _file_states: dict = {}
        for m in models:
            _file_probe = file_state_track(f"models:{m.get('id')}", m)
            _fs = _file_probe["state"]
            _file_states[m.get("id")] = _fs
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
                "source_membership": (m.get("source_membership")
                                      if m.get("source_membership") in ("listed", "unlisted")
                                      else "unknown"),
                # U15 — IS THE FILE STILL THERE? One stat(), debounced two-strikes
                # (health.file_state_track), so a sleeping network mount cannot make
                # the pane accuse the user of deleting a model they still have. Values:
                # ok | checking | gone | incomplete | unknown. "checking" is deliberately
                # invisible, while an observable broken artifact is shown immediately.
                "file": _fs,
                "file_reason": _file_probe.get("reason"),
                "file_detail": _file_probe.get("detail"),
                # S29 — THE PERSISTED verdict, as opposed to `file` above, which is this
                # process's live debounce. The panel needs both: `file` draws the chip
                # the instant we know, `absent` is what every OTHER enumerator (the four
                # app seeders, all reading data/models.json off disk) will act on, and
                # therefore what the composer picker must agree with so one screen never
                # offers what another screen refuses.
                "absent": m.get("absent") is True,
                # Per-model sampling: the READ side of /api/models/settings lives
                # here (one key on a payload the panel already polls) rather than in
                # a second route. `sampling` is the rendered view (engine-filtered
                # fields + motdeck defaults + overrides); `settings` is the raw pin.
                "settings": (m.get("settings") if isinstance(m.get("settings"), dict)
                             else None),
                "sampling": sampling_view(m),
                # Same pattern for the LOAD group (v2): raw pin + rendered view.
                "load": (m.get("load") if isinstance(m.get("load"), dict) else None),
                "loadview": load_view(m),
                # v2.1: the shared Apply & reload row — sampling floors + load, in
                # one claim, so an MLX model (no Load fields) still gets the chip.
                "launch": launch_view(m, _LOAD_AT_LAUNCH.get(m.get("id")))})
        # Write the debounced verdict back into the row (see _persist_absent). Done
        # AFTER the list is built so a failure here can never cost the caller a payload.
        _persist_absent(_file_states)
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
        "recovery_error": _MODEL_DELETE_RECOVERY_ERROR or None,
        # Phase A (Models → Audio tab) reads these; the chat lists above never see them.
        "audio": audio, "voice": vcfg,
        # The models the user hid — a light view, only ever used to draw the
        # "N hidden — show" affordance and to unhide them again.
        "hidden": hidden})


_SWITCH = {"busy": False, "log": ""}

# U64: the pidfile the switch's start-script run is tracked under, so Cancel stops THAT
# process instead of pattern-matching a script name across every motdeck root here.
SWITCH_TRACK = "switch-runner"


def _switch_log(msg: str, done: bool = False) -> None:
    """THE single writer of the switch log — and therefore the single SSE emit point
    for "the runner's model is changing" (2026-08-28).

    The panel's own 2s switch-status poll is NOT removed by this and must not be: it is
    what drives the modal's progress line, and a switch is the one moment the user is
    staring at the screen waiting. What the push adds is that every OTHER surface — the
    Mission Control cards, the chat header's model stamp, the sidebar dots — repaints on
    the transition instead of on its own next tick.

    ⚠️ Called from _do_switch's daemon THREAD as well as from the route. publish() is
    thread-safe and never raises."""
    _SWITCH["log"] = msg
    publish("model", phase=msg[:160], done=bool(done))


def model_file_alive(mid: str) -> bool:
    """Is `mid` a registry entry whose artifact is STILL ON DISK? (U15)

    Undebounced on purpose — this is asked once, at a decision point, and the safe
    direction is inverted from the status card's: here an unreadable path must count as
    NOT a safe rollback target, whereas on the card it must not become an accusation."""
    if not mid:
        return False
    entry = next((m for m in _registry_models() if m.get("id") == mid), None)
    if entry is None:
        return False
    return artifact_probe(entry).get("state") == "ready"


# ══ THE COHERENCE WAVE (S28) — AFTER A SWITCH, NOTHING MAY KEEP NAMING THE OLD MODEL ══
#
# THE INCIDENT THIS EXISTS FOR (docs/research/2026-08-29-post-switch-audit.md, measured
# end to end on the live machine): the runner served Parable-Qwen3-4B while Odysseus's
# default, its picker, the Goose UI chip, OpenCode's catalog and our own Chat lane's turn
# labels all still said a 27B whose weights had been deleted. Nothing crashed. llama.cpp
# IGNORES the request's `model` field, so every one of those surfaces got Parable's
# tokens under the wrong name — the system did not fail, it LIED QUIETLY, which the
# doctrine ranks as the worst class there is.
#
# The root cause was not the seeders: every one of them is idempotent and never-clobber
# (v1.5.49-56, ledger U11/U12). It was that they only ever ran at component START, and a
# runner switch is not a component start. This function is the missing TRIGGER — it
# re-runs the seeding each dependent already has, with the model we JUST LOADED as the
# input, and it adds no new write of any kind.
#
# THREE RULES, and they are the same three every seeder here obeys:
#   1. NEVER CLOBBER. Nothing below writes a value a human chose. The Odysseus seed
#      honours renames/keys/curated lists; the goose provider file merges OWNED_KEYS
#      only; the one goose key we now repair is repaired ONLY when it dangles.
#   2. LIVE OUTRANKS THE PIN. The wire we hand round is the model the runner is actually
#      serving, not motdeck.yaml's — the rule the hermes arm proved in v1.5.56.
#   3. WHAT WE CANNOT REBIND, WE SIGNAL. A running goosed carries GOOSE_MODEL in its
#      ENVIRONMENT and no file write can change that; we refuse to restart somebody's
#      live agent session to fix a label, so /api/deps' new `gooseui` binding raises the
#      banner with a Restart button instead. Honest limit, not an omission.
def _rebind_goose(wire: str) -> str:
    """Re-seed BOTH goose lanes' provider files and repair a DANGLING model choice.

    File-side only, and deliberately: the live goosed's `GOOSE_MODEL` comes from its
    process ENV (gooseprov F6, measured), so it cannot change without a respawn — and a
    respawn kills whatever session the user is in. The deps banner covers that half.
    Returns a short log line, never raises."""
    from .. import gooseprov as _p
    said = []
    c = cfg()
    rc = c.get("runner", {}) or {}
    endpoint, port = rc.get("endpoint") or "", rc.get("port") or 6767
    reg = _registry_models()
    offered = [m["name"] for m in _p.model_entries(reg)]
    for lane, cfg_dir in (
            ("Goose UI", ROOT / "data" / "goose" / "ui-home" / "goose" / "config"),
            ("Goose CLI", ROOT / "data" / "goose" / "home" / ".config" / "goose")):
        if not cfg_dir.is_dir():
            continue                      # lane never installed — S23, say nothing
        try:
            _p.seed_provider(str(cfg_dir), endpoint, reg, port)
        except Exception as e:                                       # noqa: BLE001
            said.append(f"{lane}: provider re-seed failed ({str(e)[:80]})")
            continue
        # BOTH SLUGS. `providers.openai.model` is not goose's stock provider being
        # helpful — it is OUR OWN pre-v1.5.49 anonymous seeding (gooseprov's
        # LEGACY_PROVIDER, the one value provider_choice() is allowed to migrate away
        # from), so a ghost left there is our litter, and it would be honoured the
        # moment anyone switched back to it. Found in the live walk: the active slug
        # rebound cleanly while the legacy one still named the deleted 27B.
        for slug in (_p.PROVIDER_NAME, _p.LEGACY_PROVIDER):
            old, new, changed, err = _p.repair_config_model(
                str(cfg_dir / "config.yaml"), offered, wire, slug)
            if err:
                said.append(f"{lane}/{slug}: {err[:80]}")
            elif changed:
                said.append(f"{lane}/{slug}: repaired a dangling model choice "
                            f"({old} → {new})")
            elif old and old != wire:
                said.append(f"{lane}/{slug}: honoured your model choice ({old})")
    return "; ".join(said)


def _rebind_odysseus_offline(wire: str) -> str:
    """Run the Odysseus DB seed with MOT_DECK_WIRE_MODEL — the seam that had no callers.

    ⚠️ ONLY WHEN ODYSSEUS IS NOT RUNNING. The seeder wants offline sqlite access (ledger
    S28's own note); against a live Odysseus the correct rebind is the RESTART arm above,
    which runs this same script through start_component.sh. Best-effort, never raises."""
    ody = ROOT / "vendor" / "odysseus"
    script = ROOT / "scripts" / "seed_odysseus_jan.py"
    if not ody.is_dir() or not script.is_file():
        return ""                     # not installed — S23, say nothing at all
    # ⚠️ THE ODYSSEUS VENV IS data/odysseus-venv, NOT vendor/odysseus/.venv. Caught in
    # the live walk: sys.executable (the BRIDGE's venv) reaches the script but not
    # Odysseus's own modules, so the seed failed with `No module named 'bcrypt'` and
    # a rebind that reported nothing wrong did nothing at all. Same source of truth as
    # start_component.sh's odysseus branch.
    py = ROOT / "data" / "odysseus-venv" / "bin" / "python"
    if not py.is_file():
        # No venv ⇒ Odysseus was never provisioned here. Refuse honestly rather than
        # run the script under an interpreter that cannot import its modules — that is
        # the shape this bug already took once, and a confusing traceback in the log is
        # worse than a sentence naming the missing thing.
        return "Odysseus venv missing (data/odysseus-venv) — nothing to rebind offline"
    rc = cfg().get("runner", {}) or {}
    env = dict(os.environ,
               MOT_DECK_WIRE_MODEL=wire or "",
               JAN_BASE_URL=str(rc.get("endpoint") or "http://127.0.0.1:6767/v1"),
               JAN_API_KEY=str(rc.get("api_key") or ""))
    try:
        r = subprocess.run([str(py) if py.is_file() else sys.executable, str(script)],
                           cwd=str(ody), env=env, capture_output=True, text=True,
                           timeout=60)
    except Exception as e:                                           # noqa: BLE001
        return f"Odysseus seed failed: {str(e)[:80]}"
    return "" if r.returncode == 0 else \
        f"Odysseus seed exited {r.returncode}: {(r.stderr or r.stdout)[-160:].strip()}"


def _rebind_opencode(wire: str) -> str:
    """Rewrite OpenCode's provider catalog + default from the CURRENT registry.

    THE GAP THIS CLOSES (audit §1, and Debi's words: "very old deleted models"):
    OpenCode's catalog was only ever rewritten by its OWN Start. Her live config, last
    written 2026-08-28 01:49, still advertised sixteen models — the muse/glimmer family,
    the gemma-4 DECKARD, the deleted 27B — while the registry held fourteen and the
    runner served one. Picking a ghost is not an error (llama.cpp ignores the request's
    `model`), so the turn answers under a dead model's name: the lie class.

    ⚠️ WHAT THIS DOES AND DOES NOT ACHIEVE — MEASURED ON THE LIVE SERVER 2026-08-29,
    and the first draft of this comment claimed the opposite. After writing the pruned
    catalog, an authenticated directory-scoped `GET :4096/provider` STILL RETURNED THE
    SIXTEEN OLD MODELS, muse/glimmer and all: OpenCode reads its config at BOOT and
    holds it for the life of the process. A file write alone changes nothing the user
    can see. (The lane's own Start self-check already prints this fact — "a running
    OpenCode reads its config at boot" — so assuming otherwise would have shipped a fix
    that reported success and did nothing, which is the exact class this slice is about.)

    The division of labour, therefore: THIS makes the file correct and durable, so no
    future Start can re-introduce the ghosts and a component restart is all that is left
    to do — and the CALLER says out loud that the restart is what makes it visible.
    Never raises; returns a short log line, restart note included."""
    root_env = dict(os.environ)
    oc_home = ROOT / "data" / "opencode" / "xdg"
    cfg_path = oc_home / "config" / "opencode" / "opencode.json"
    if not cfg_path.is_file():
        return ""                        # lane never started here — S23, say nothing
    rc = cfg().get("runner", {}) or {}
    root_env.update(
        MOT_DECK_ROOT=str(ROOT),
        OC_CFG=str(cfg_path),
        OC_PCFG=str(ROOT / "data" / "opencode-workspace" / "opencode.json"),
        OC_BASE=str(rc.get("endpoint") or ""),
        OC_KEY=str(rc.get("api_key") or ""),
        # LIVE OUTRANKS THE PIN (rule 2 above) — the Start arm can only read
        # motdeck.yaml, but we know what is actually serving.
        OC_MODEL=str(wire or ""))
    try:
        r = subprocess.run([sys.executable, "scripts/seed_opencode_config.py"],
                           cwd=str(ROOT), env=root_env, capture_output=True,
                           text=True, timeout=60)
    except Exception as e:                                           # noqa: BLE001
        return f"OpenCode catalog re-seed failed: {str(e)[:80]}"
    if r.returncode != 0:
        return (f"OpenCode catalog re-seed exited {r.returncode}: "
                f"{(r.stderr or r.stdout)[-160:].strip()}")
    # Only the REPAIRS travel (a config we rewrote under the user must be visible); the
    # routine "provider llama.cpp -> N model(s)" line is the caller's to summarise.
    bits = [ln.split("REPAIRED:", 1)[1].strip()
            for ln in (r.stdout or "").splitlines() if "REPAIRED:" in ln]
    # THE HONEST HALF (see the ⚠️ above): while the process is UP, its picker keeps the
    # catalog it read at boot. Say so, or a correct file reads as a fixed UI.
    try:
        port = ((cfg().get("components") or {}).get("opencode") or {}).get("port") or 4096
        if _port_alive_sync(int(port)):
            bits.append("catalog written — RESTART OpenCode to load it "
                        "(it reads its config at boot)")
    except Exception:                                                # noqa: BLE001
        pass
    return "; ".join(bits)[:400]


def _rebind_deepseek(wire: str) -> str:
    """Rewrite the DeepSeek lane's provider route + default from the CURRENT registry.

    Same gap, same closure as _rebind_opencode: a config-resident model catalog that
    only its own Start rewrites is a catalog that goes on advertising models the user
    deleted days ago, and picking a ghost does not fail — llama.cpp ignores the
    request's `model` field, so the turn answers under a dead model's name. Lie class.
    So this lane joins BOTH fan-outs (the model switch and Rescan) from the day it
    lands, rather than being the one dependent left out the way OpenCode was in
    v1.5.62.

    ⚠️ AND HERE THE FILE WRITE IS THE WHOLE FIX — the one place this differs from
    OpenCode, in DeepSeek's favour, and it is upstream's own documented property rather
    than our hope: dsh's llm-pi-ai adapter "reads its profiles through a thunk ONCE PER
    OPERATION instead of freezing them at construction", the settings provider watches
    the document and hot-publishes external edits, and the docs state plainly that
    "model changes take effect on the next request without restarting the server". So
    there is NO "restart it to see this" half to append here, and appending one would
    be a false instruction. That asymmetry is exactly why the note this returns is
    shorter than OpenCode's, and why it must not be copied from it.

    Never raises; returns a short log line ('' when there is nothing to say)."""
    root_env = dict(os.environ)
    ds_home = ROOT / "data" / "deepseek" / "home"
    settings = ds_home / "settings.yaml"
    # S23: installed-ness is the existence of the document the lane's own Start wrote.
    # A lane that has never started here says NOTHING at all rather than reporting a
    # re-seed of a file nobody asked for.
    if not settings.is_file():
        return ""
    rc = cfg().get("runner", {}) or {}
    # The key env-var NAME is DERIVED by the seeder, never restated here — the same
    # rule the shell arm follows. Import by path: this module must not depend on
    # scripts/ being importable as a package.
    key_env = "MOT_DECK_LOCAL_API_KEY"
    try:
        import importlib.util
        _p = ROOT / "scripts" / "seed_deepseek_config.py"
        _s = importlib.util.spec_from_file_location("motdeck_seed_dsh", str(_p))
        if _s is not None and _s.loader is not None:
            _m = importlib.util.module_from_spec(_s)
            _s.loader.exec_module(_m)
            key_env = _m.key_env_name()
    except Exception:                                                # noqa: BLE001
        pass                    # the fallback IS that function's value for the default
    root_env.update(
        MOT_DECK_ROOT=str(ROOT),
        DS_SETTINGS=str(settings),
        DS_BASE=str(rc.get("endpoint") or ""),
        DS_KEY_ENV=str(key_env),
        # LIVE OUTRANKS THE PIN — the Start arm can only read motdeck.yaml, but we know
        # what is actually serving.
        DS_MODEL=str(wire or ""))
    try:
        r = subprocess.run([sys.executable, "scripts/seed_deepseek_config.py"],
                           cwd=str(ROOT), env=root_env, capture_output=True,
                           text=True, timeout=60)
    except Exception as e:                                           # noqa: BLE001
        return f"DeepSeek catalog re-seed failed: {str(e)[:80]}"
    if r.returncode != 0:
        return (f"DeepSeek catalog re-seed exited {r.returncode}: "
                f"{(r.stderr or r.stdout)[-160:].strip()}")
    # Only the REPAIRS travel (a config we rewrote under the user must be visible)…
    bits = [ln.split("REPAIRED:", 1)[1].strip()
            for ln in (r.stdout or "").splitlines() if "REPAIRED:" in ln]
    # …plus the REFUSAL, which is the one line that must never be silent. The seeder
    # exits 0 when it declines to write (an empty enumeration, an unparseable
    # document), because a Start must not fail for that — but in the switch/rescan
    # fan-out the user has just pressed a button, and "we left your models alone and
    # here is why" is the answer they are owed.
    for ln in (r.stdout or "").splitlines():
        if "NOT WRITTEN" in ln:
            bits.append(ln.split("NOT WRITTEN —", 1)[-1].strip() or "not written")
    return "; ".join(bits)[:400]


def _rebind_hermes_file(wire: str) -> str:
    """The Hermes provider seed WITHOUT a restart — the config half of its Start arm.

    Hermes reads ~/.hermes/config.yaml at USE time (audit §1, the one third-party app
    that was already coherent), so the file write is the whole rebind for a catalog
    change. `MODEL` is passed but the seed is SEEDED-NOT-ENFORCED for the main slot
    (U12) — a model the user picked inside Hermes is honoured, with a printed line."""
    script = ROOT / "scripts" / "seed_hermes_provider.py"
    hcfg = os.path.expanduser("~/.hermes/config.yaml")
    if not script.is_file() or not os.path.isfile(hcfg):
        return ""
    rc = cfg().get("runner", {}) or {}
    env = dict(os.environ, HERMES_CFG=hcfg, MOT_DECK_ROOT=str(ROOT),
               BASE_URL=str(rc.get("endpoint") or ""),
               KEY=str(rc.get("api_key") or ""), MODEL=str(wire or ""))
    try:
        r = subprocess.run([sys.executable, str(script)], cwd=str(ROOT), env=env,
                           capture_output=True, text=True, timeout=60)
    except Exception as e:                                           # noqa: BLE001
        return f"Hermes provider re-seed failed: {str(e)[:80]}"
    return "" if r.returncode == 0 else \
        f"Hermes provider re-seed exited {r.returncode}"


def _rescan_fanout() -> str:
    """Push the JUST-PRUNED registry into every dependent's catalog. FILE WRITES ONLY.

    Debi's actual question was "isn't there a way to make the different apps scan?" —
    and the honest answer is that they should never have to: they do not own the
    registry, we do. RESCAN is the moment the registry changes, so it is the moment
    every catalog built from it must be rebuilt.

    ⚠️ NO RESTARTS HERE, deliberately, and this is the difference from the switch
    fan-out. A switch is already a disruptive act the user asked for; a rescan is a
    read-the-disk button, and killing a live Odysseus or a goose session the user is
    mid-conversation in to refresh a picker would be a far worse surprise than a stale
    list. So: every catalog that is a file gets rewritten now, and anything that needs
    a process restart is left to /api/deps' banner, which already carries that sentence
    and that button. Returns a one-line summary for the panel."""
    from ..core.modelid import wire_model_id
    rc = cfg().get("runner", {}) or {}
    port = rc.get("port")
    live = _live_model_id(int(port)) if port else None
    # LIVE OUTRANKS THE PIN; the pin is the fallback for a runner that is down.
    base = live or rc.get("model") or ""
    wire = wire_model_id(base, _registry_models()) or base
    # How many models the catalogs will now carry — the number that makes the summary
    # CHECKABLE. ("Refreshed" with no figure is indistinguishable from "did nothing",
    # and this whole slice exists because a list nobody could check went stale.)
    try:
        from ..core.modelreg import offerable
        n = len(offerable(_registry_models()))
    except Exception:                                                # noqa: BLE001
        n = -1
    said = []
    # ⚠️ THE FOUR SEEDS ALL RETURN '' ON A CLEAN, NO-CHANGE RUN — which is right for
    # the switch log (silence = nothing to report) and WRONG here, where the user has
    # just pressed a button and is owed an answer. Installed-ness is checked FIRST so
    # a lane that is not on this machine still says nothing at all (S23).
    for label, fn, present in (
            ("OpenCode", _rebind_opencode,
             (ROOT / "data" / "opencode" / "xdg" / "config" / "opencode"
              / "opencode.json").is_file()),
            # S34: the DeepSeek lane, joined to BOTH fan-outs on the day it landed
            # rather than a release later. Its presence test is the settings document
            # its own Start writes — see _rebind_deepseek.
            ("DeepSeek", _rebind_deepseek,
             (ROOT / "data" / "deepseek" / "home" / "settings.yaml").is_file()),
            ("Hermes", _rebind_hermes_file,
             os.path.isfile(os.path.expanduser("~/.hermes/config.yaml"))),
            ("goose", _rebind_goose,
             (ROOT / "data" / "goose" / "ui-home" / "goose" / "config").is_dir()
             or (ROOT / "data" / "goose" / "home" / ".config" / "goose").is_dir())):
        if not present:
            continue
        try:
            note = fn(wire)
        except Exception as e:                                       # noqa: BLE001
            note = f"failed ({str(e)[:60]})"
        said.append(f"{label}: {note}" if note else
                    f"{label}: catalog refreshed ({n} models)" if n >= 0 else
                    f"{label}: catalog refreshed")
    # Odysseus is intentionally absent from this synchronous file fan-out. Its live
    # picker belongs to its authenticated admin API, while its stopped state belongs to
    # the offline seeder. ``model_rescan._rebind_odysseus_after_rescan`` chooses between
    # those two authoritative paths from the ASGI loop and appends the truthful result.
    # Keeping a network client out of this worker also avoids driving one global
    # AsyncClient from a second event loop.
    return "; ".join(said)[:600] or "no file-backed dependent catalogs present"


def _rebind_dependents(new_id: str, restart_hermes: bool, restart_ody: bool) -> str:
    """Fan the just-loaded model out to every dependent. '' on success, else the ONE
    sentence _do_switch should report instead of a bare "active"."""
    from ..core.modelid import wire_model_id
    wire = wire_model_id(new_id, _registry_models()) or new_id
    if restart_hermes:
        # Already correct since v1.5.56: its Start arm curls the authenticated
        # /v1/models and lets the runner's answer outrank motdeck.yaml. Included for
        # completeness so ONE list names every dependent.
        _switch_log("re-wiring Hermes…")
        if _script("start_component.sh", "hermes").returncode != 0:
            return f"active: {new_id} — but Hermes restart FAILED (see logs)"
    _switch_log("re-wiring Odysseus…")
    if restart_ody:
        if _script("start_component.sh", "odysseus").returncode != 0:
            return f"active: {new_id} — but Odysseus restart FAILED (see logs)"
    else:
        note = _rebind_odysseus_offline(wire)
        if note:
            print(f"[switch] {note}", flush=True)
    _switch_log("re-wiring goose…")
    gnote = _rebind_goose(wire)
    if gnote:
        print(f"[switch] goose: {gnote}", flush=True)
    # S29 — OPENCODE JOINS THE FAN-OUT. It was the one dependent left out of v1.5.62,
    # and it is the one Debi named ("very old deleted models"): its catalog was rewritten
    # ONLY by its own Start, so it kept advertising models deleted days earlier. A file
    # write, no restart, same never-clobber rules — see _rebind_opencode.
    _switch_log("re-wiring OpenCode…")
    onote = _rebind_opencode(wire)
    if onote:
        print(f"[switch] opencode: {onote}", flush=True)
    # S34 — THE DEEPSEEK LANE JOINS THE FAN-OUT, on the day it landed. It is a
    # config-resident catalog of exactly the same shape, so leaving it out would have
    # rebuilt the S29 bug in a new lane and waited for Debi to find it again.
    # ⚠️ And here the file write really is the whole fix — dsh re-reads its settings
    # per operation — so unlike OpenCode there is no restart to advise. See
    # _rebind_deepseek.
    _switch_log("re-wiring DeepSeek…")
    dnote = _rebind_deepseek(wire)
    if dnote:
        print(f"[switch] deepseek: {dnote}", flush=True)
    return ""


def _do_switch(new_id: str, old_id: str, restart_hermes: bool, restart_ody: bool) -> None:
    """Fable QA hardening: check exit codes (a failed load must NOT report success),
    and roll motdeck.yaml back to the previous model on failure so the next Start
    uses a known-good model instead of retrying a broken one.

    ⚠️ U15 REWROTE THE FAILURE ARM, AND THE LIVE INCIDENT IS WHY. On 2026-08-29 Debi
    switched to Parable-Qwen3-4B; llama-server loaded it in 1.3s and served it. The
    start script still exited non-zero (its readiness poll sends no Authorization
    header and has 401'd against every b10662 runner since — ledger U16), so this
    function declared "FAILED to load Parable… — reverted to Qwen3.6-27B…" and rolled
    the pin back to a model whose FILE SHE HAD DELETED. Every clause of that sentence
    was false, and the rollback armed the next failure.

    Three rules now, in order:
      1. VERIFY BEFORE BELIEVING. An authenticated /v1/models probe outranks the exit
         code, because it observes the thing the exit code only reports on.
      2. NEVER ROLL BACK ONTO A MODEL THAT CANNOT LOAD. A rollback target whose file is
         gone (or that left the registry) is not a "known-good model" — keeping the new
         pin and saying so is strictly more honest and strictly more recoverable.
      3. THE USER GETS A SENTENCE, NOT A LOG TAIL. `2.49.854.040 W srv operator():
         unauthorized: Invalid API Key` is what she actually read on screen."""
    from .components import start_failure_reason
    try:
        _switch_log(f"downloading + loading {new_id} — large downloads take minutes…"
                    if "/" in new_id else f"loading {new_id}…")
        # TRACKED, not merely run (U64): the pid lands in data/switch-runner.pid for
        # the duration, which is what lets Cancel stop this exact process by identity.
        r = _script_tracked("start_component.sh", "runner", track=SWITCH_TRACK)
        if r.returncode != 0:
            # RULE 1 — ask the runner itself before repeating the script's verdict.
            port = (cfg().get("runner", {}) or {}).get("port")
            served = _live_model_id(int(port)) if port else None
            # …and it must be serving THIS switch's model. A runner still holding the
            # PREVIOUS model is the definition of a switch that did not happen; a bare
            # truthiness check here would have reported exactly that as success.
            if served and served == new_id:
                print(f"[switch] start_component.sh exited {r.returncode} but the "
                      f"runner is serving “{served}” — believing the probe (U16)",
                      flush=True)
                _record_load_launch(new_id)
                # THE SAME FAN-OUT AS THE SUCCESS PATH. This arm is not a lesser
                # success — it is the path Debi's own switch took (a false non-zero
                # exit over a runner that had loaded in 1.3s), so a rebind that only
                # hung off the other branch would have missed the real incident.
                _bad = _rebind_dependents(new_id, restart_hermes, restart_ody)
                _switch_log(_bad or f"active: {new_id}", done=not _bad)
                return
            out = r.stdout + r.stderr
            entry = next((m for m in _registry_models() if m.get("id") == new_id), None)
            why = start_failure_reason(
                out, model=new_id, path=str((entry or {}).get("path") or ""),
                file_state=("ok" if model_file_alive(new_id) else "gone")
                           if entry else "")
            # RULE 2 — only revert onto a model that could actually load.
            if old_id and old_id != new_id and model_file_alive(old_id):
                _set_runner_model(old_id)
                where = f" — reverted the pin to {old_id}"
            elif old_id and old_id != new_id:
                where = (f" — the previous model ({old_id}) is gone from disk too, so "
                         f"the pin was left on {new_id}")
            else:
                where = ""
            # RULE 3 — the sentence, then the raw tail, clearly separated.
            _switch_log(f"FAILED to load {new_id}: {why['text']}{where}. "
                        f"Details: {(out or '').strip()[-300:]}")
            return
        # The runner is now running with whatever `load` was saved at this moment —
        # record it so the panel can say "not applied yet" only when it is TRUE.
        _record_load_launch(new_id)
        # S28 — the coherence wave. Every dependent re-seeds off the model we just
        # loaded, not off motdeck.yaml's pin. See _rebind_dependents.
        bad = _rebind_dependents(new_id, restart_hermes, restart_ody)
        if bad:
            _switch_log(bad)
            return
        _switch_log(f"active: {new_id}")
    except Exception as e:
        _switch_log(f"switch error: {str(e)[:200]}")
    finally:
        _SWITCH["busy"] = False
        # The switch is OVER — whatever the outcome. `done` is what lets the panel
        # re-read the model list once instead of on every phase.
        publish("model", phase="switch finished", done=True)


@app.post("/api/models/switch")
async def api_switch_model(req: Request) -> JSONResponse:
    """Switch the runner's model (loads it via the engine dispatch), then re-fan-out
    the new model NAME to any running Hermes/Odysseus (their configs bind the name).
    Runs in the background — poll /api/models/switch-status. `id` must be an INSTALLED
    registry model (HF repo ids are rejected — downloads go via the download manager)."""
    if _SWITCH["busy"]:
        return JSONResponse({"ok": False, "log": "a switch is already in progress"}, status_code=409)
    _body = await req.json()
    if not isinstance(_body, dict):
        _body = {}
    new_id = (_body.get("id") or "").strip()
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
    entry = next((m for m in _registry_models() if m.get("id") == new_id), None)
    if entry is None:
        return JSONResponse({"ok": False, "log": f"model '{new_id}' not in registry"}, status_code=400)
    if is_source_unlisted(entry):
        return JSONResponse(
            {"ok": False, "log": f"model '{new_id}' is no longer listed by its source manager. "
                                  "Eject it if it is live, or Rescan after restoring it there"},
            status_code=409)
    probe = artifact_probe(entry)
    if probe["state"] != "ready":
        status = 400 if probe["state"] == "missing" else 409
        return JSONResponse(
            {"ok": False,
             "log": f"model '{new_id}' is {probe['state']}: {probe['detail']}. "
                    "Rescan or pick another model"}, status_code=status)
    old_id = (c.get("runner", {}) or {}).get("model") or ""
    # ── THE LOAD CONSENT GATE (v1.5.30) ──────────────────────────────────────
    # THIS USED TO BE A WALL AND IS NOW AN ADVISOR, and it is the same engine the
    # chips and the strip use (bridge/core/fit.py) — one verdict, one grammar, no
    # divergence between what the list said and what the loader says. Debi's
    # advisory-gates ruling: a projected-doesn't-fit load shows the measured numbers,
    # a recommendation and a proceed-anyway, and it never refuses.
    #
    # The old gate compared FILE SIZE against a hand-written budget_gb, which was
    # wrong in both directions: it ignored the KV cache (the whole point of the
    # feature — 4 GB of it on the resident 27B at 65k) and it counted the model this
    # switch is about to EJECT against the model replacing it.
    #
    # ⚠️ PARITY IS A REQUIREMENT, NOT A COURTESY. `confirm: true` is the override and
    # it works on this route, i.e. for the CLI and any API client, exactly as it works
    # for the panel — LM Studio's documented defect (lms#499) is an advisory GUI over a
    # hard-blocking API, so a headless caller is stuck behind a number it cannot see.
    _adv = _fit_advice(new_id)
    if _adv is not None:
        _refuse = _adv.get("refuse")
        if _refuse:
            # THE ONE HARD STOP IN THE FEATURE: a hand-set context past Metal's wired
            # ceiling. Documented kernel PANIC, not an OOM — a warning that precedes a
            # panic is not a warning.
            #
            # ⚠️ `confirm: true` DOES NOT CLEAR THIS, and an earlier draft let it: the
            # consent flag is the answer to "this will be slow", not to "this may take
            # the machine down with it". The only key that opens this door is the
            # environment variable named in the message — a deliberate act outside the
            # click that provoked it. Caught in the adversarial pass.
            return JSONResponse({"ok": False, "refuse": True,
                                 "advisory": _adv,
                                 "log": _refuse["reason"] + " " + _refuse["remedy"]},
                                status_code=409)
        from ..core import memoryprefs
        _confirmed = _wants_confirm(_body)
        if memoryprefs.needs_confirmation(_adv.get("verdict"), new_id) and not _confirmed:
            _c = _adv.get("copy") or {}
            return JSONResponse({"ok": False, "needs_confirm": True,
                                 "advisory": _adv,
                                 "log": (_c.get("line") or "this may not fit"),
                                 "error": (_c.get("line") or "this may not fit")},
                                status_code=409)
        if _confirmed and _adv.get("verdict") in ("over", "tight"):
            try:
                memoryprefs.acknowledge(new_id)
            except (OSError, ValueError) as exc:
                # Losing the warn-once convenience must not turn an explicitly
                # confirmed advisory into a refusal to load the model.
                print(f"[fit] could not remember override for {new_id}: {exc}",
                      flush=True)
        if _adv.get("verdict") in ("over", "tight"):
            print(f"[fit] {new_id}: {_adv.get('verdict')} — "
                  f"{(_adv.get('copy') or {}).get('line', '')}"
                  f"{' (user confirmed)' if _confirmed else ''}", flush=True)
    hermes_up, ody_up = _running_sync("hermes", c), _running_sync("odysseus", c)
    # set BEFORE the thread: no double-switch race. (Download progress lives in the
    # download manager now — "/" repo ids are rejected above, so no HF fetch here.)
    _SWITCH.update(busy=True, log="starting…")
    publish("model", phase="starting…")
    _set_runner_model(new_id)
    threading.Thread(target=_do_switch, args=(new_id, old_id, hermes_up, ody_up), daemon=True).start()
    return JSONResponse({"ok": True, "log": "switch started"})


@app.post("/api/models/pin")
async def api_pin_model(req: Request) -> JSONResponse:
    """PIN THE MODEL THAT IS ALREADY SERVING — the affordance Debi hit a wall on.

    v1.5.57 ruled, correctly, that MOT Deck never SILENTLY rewrites `runner.model`:
    the pin is an INTENT RECORD, and a system that quietly edits the user's intent to
    match reality teaches them to stop trusting it. But the audit found the other half
    of that ruling missing (§5.5): with the pin dangling onto a deleted 27B and Parable
    live, the ONLY advice on screen was "pick another model" — and Parable's own row
    offers Eject, not Pin, because it is already loaded. The drift state was therefore
    STABLE: nothing in the UI could end it except ejecting the working model and
    reloading it, or hand-editing yaml.

    This is that one missing click, and it is deliberately the smallest thing that
    works: no load, no restart, no runner touched at all — the model is ALREADY up.
    It writes exactly what the user asked it to write, which is the opposite of the
    silent rewrite the ruling forbids.

    Refuses anything that is not the live model: a "pin" that changed the intent record
    to a model nobody has loaded would re-create the drift under a different name."""
    body = await req.json()
    if not isinstance(body, dict):
        body = {}
    want = (body.get("id") or "").strip()
    rc = cfg().get("runner", {}) or {}
    live = _live_model_id(int(rc["port"])) if rc.get("port") else None
    if not live:
        return JSONResponse({"ok": False,
                             "log": "nothing is loaded — there is no served model to pin"},
                            status_code=409)
    live_entry = next((m for m in _registry_models() if m.get("id") == live), None)
    if is_source_unlisted(live_entry):
        return JSONResponse(
            {"ok": False, "live": live,
             "log": f"'{live}' is no longer listed by its source manager and cannot be newly pinned. "
                    "Eject it or restore it in that manager, then Rescan."}, status_code=409)
    if want and want != live:
        return JSONResponse(
            {"ok": False, "live": live,
             "log": f"only the model the runner is actually serving can be pinned this "
                    f"way — that is “{live}”, not “{want}”. Use Switch to load another."},
            status_code=409)
    if (rc.get("model") or "") == live:
        return JSONResponse({"ok": True, "pin": live, "changed": False,
                             "log": f"already pinned to {live}"})
    _set_runner_model(live)
    # The panel re-reads on this event, so the yellow clears without a reload — the
    # "without a reload" half is the point: a fix that needs a refresh to be believed
    # is a fix the user has to take on faith.
    publish("model", phase=f"pinned {live}", done=True)
    return JSONResponse({"ok": True, "pin": live, "changed": True,
                         "log": f"pinned {live}"})


def _eject_runner(*, clear_pin: bool = True) -> list[str]:
    """Stop the exact owned runner and, for a normal eject, clear its saved pin.

    Model deletion passes ``clear_pin=False`` until its reversible persistence
    transaction commits. That keeps a failed delete from also changing launch intent.
    """
    rc = cfg().get("runner", {}) or {}
    port = rc.get("port")
    if port:
        # ⛔ U64: a kill-by-pattern "jan serve" sweep stood here — dead code since Jan
        # was retired 2026-07-23, but still able to reach a process we did not launch.
        # Deleted, not replaced: the ownership-checked port kill is what stops OUR
        # runner, and always was.
        refused = stop_owned_component("runner", int(port), force=True)
        if refused:
            return refused
        for _ in range(30):
            if not _port_alive_sync(int(port)):
                break
            time.sleep(0.1)
        if _port_alive_sync(int(port)):
            return [f"runner port :{port} is still answering after the exact stop; "
                    "the pin and model files were left unchanged"]
    _clear_expected("runner")     # intentional → "stopped", not "degraded"
    PROV.pop("runner", None)
    if clear_pin:
        _set_runner_model("")     # no active model — Start must route the user to pick
        publish("model", phase="ejected", done=True)
    publish("component", name="runner", state="stopping")
    return []


@app.post("/api/models/eject")
def api_eject_model() -> JSONResponse:
    """Eject the live model (Fable ISSUE 2 state machine): stop the runner by PORT
    AND clear the active-model designation. Going live again requires an explicit
    Load from the Models pane. Frees the main slot's RAM in the ledger."""
    refused = _eject_runner()
    if refused:
        return JSONResponse({"ok": False, "log": "; ".join(refused)}, status_code=409)
    return JSONResponse({"ok": True})


# ── Delete an APP-OWNED model (files live under data/models/) ──────────────────
# App-owned = source in {download, local}: MOT Deck downloaded these or holds the
# local files under data/models/<folder>/, so we may delete both the files and the
# registry entry. Read-only imports (lmstudio-import, jan-import) point at files the
# motdeck does NOT own (e.g. the user's LM Studio library) — deleting those would
# them too). The path/collision/rollback boundary lives in core/modeldelete.py; this
# route owns only process quiescence and the user-facing state transition.


@app.post("/api/models/delete")
async def api_delete_model(req: Request) -> JSONResponse:
    """Delete an app-owned model: remove its folder under data/models/ + its registry
    entry. HARD-guarded — only source in {download, local} AND a realpath strictly
    under data/models/ is ever deleted (never an LM Studio / Jan import, never a path
    outside our dir). If the model is currently live (main runner or aux), it is
    ejected/stopped first."""
    import os as _os
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
    collisions = _delete_target_collisions(_registry_models(), mid, target)
    if collisions:
        return JSONResponse(
            {"ok": False,
             "log": "refused: this filesystem target is also referenced by: "
                    + ", ".join(collisions)}, status_code=409)

    c = cfg()
    rc = c.get("runner", {}) or {}
    port = rc.get("port")
    live = _live_model_id(int(port)) if port else None
    was_live = (live == mid) or ((rc.get("model") or "") == mid)
    if was_live:
        # Stop and verify first, but retain the saved pin until the file+registry
        # transaction commits. A failed delete may leave the runner stopped; it must
        # never also make the user's launch intent disappear.
        refused = _eject_runner(clear_pin=False)
        if refused:
            return JSONResponse({"ok": False, "log": "; ".join(refused)}, status_code=409)
    # If it's the aux model, stop aux (if up) + clear the aux designation.
    ax = c.get("aux", {}) or {}
    was_aux = (ax.get("model") or "") == mid
    if was_aux:
        if ax.get("port"):
            aux_notes = _aux_kill(int(ax["port"]))
            if aux_notes:
                return JSONResponse({"ok": False, "log": "; ".join(aux_notes)}, status_code=409)
            for _ in range(30):
                if not _port_alive_sync(int(ax["port"])):
                    break
                await asyncio.sleep(0.1)
            if _port_alive_sync(int(ax["port"])):
                return JSONResponse({"ok": False,
                                     "log": "aux is still answering; model files were left unchanged"},
                                    status_code=409)
    # If it was a VOICE default, clear that slot too — leaving motdeck.yaml pointing at
    # deleted weights would only fail later, at speak time, far from this click.
    vc = _voice_cfg()
    was_voice = [k for k in ("tts_model", "stt_model") if vc.get(k) == mid]
    # …and if it is RESIDENT in the persistent worker, kill that first: the process
    # holds the weights open, and on a re-download the same path would then serve a
    # deleted checkpoint from memory.
    if _voice is not None:
        _voice.worker_stop_if_model(mid, "model deleted")

    assignments = []
    if was_live:
        old_pin = str(rc.get("model") or "")
        assignments.append(("runner.model", old_pin, lambda: _set_runner_model(""),
                            lambda value=old_pin: _set_runner_model(value)))
    if was_aux:
        old_aux = str(ax.get("model") or "")
        assignments.append(("aux.model", old_aux, lambda: _set_yaml_model("aux", ""),
                            lambda value=old_aux: _set_yaml_model("aux", value)))
    for key in was_voice:
        old_voice = str(vc.get(key) or "")
        assignments.append((f"voice.{key}", old_voice,
                            lambda field=key: _set_yaml_scalar("voice", field, ""),
                            lambda field=key, value=old_voice:
                                _set_yaml_scalar("voice", field, value)))
    detail = delete_owned_model_transaction(
        root=ROOT, mid=mid, expected_target=target, assignments=assignments)
    if detail:
        print(f"[delete] {mid!r}: {detail}", flush=True)
        return JSONResponse({"ok": False, "log": detail}, status_code=500)

    if was_live:
        publish("model", phase="ejected", done=True)
    print(f"[delete] removed {mid!r} (dir {target}, was_live={was_live}, "
          f"was_aux={was_aux}, was_voice={was_voice or 'no'})", flush=True)
    return JSONResponse({"ok": True, "id": mid, "was_live": was_live,
                         "was_aux": was_aux, "was_voice": was_voice})


@app.get("/api/models/switch-status")
def api_switch_status() -> JSONResponse:
    """Poll target: busy flag + human-readable log line. (Download progress moved to
    the download manager — this endpoint tracks model LOADS only.)"""
    return JSONResponse({k: _SWITCH.get(k) for k in ("busy", "log")})


# ⛔ U64 — TWO KILLS BY PATTERN LIVED IN THE CANCEL BELOW: a dead "jan serve" sweep, and
# one matching the runner START SCRIPT BY NAME, which names that script in EVERY motdeck
# root on this machine (the repo's own checkout included). The script is now launched
# through _script_tracked and stopped by ITS OWN pid, identity re-verified first.
@app.post("/api/models/switch-cancel")
def api_switch_cancel() -> JSONResponse:
    """Cancel an in-flight switch: stop the runner on its port AND the start script WE
    launched — _do_switch then sees the failure and rolls the model pin back to the
    previous one automatically."""
    if not _SWITCH.get("busy"):
        return JSONResponse({"ok": False, "log": "no switch in progress"}, status_code=400)
    port = int((cfg().get("runner", {}) or {}).get("port") or 6767)
    notes = stop_owned_component("runner", port, force=True)
    notes += reap_pidfile(SWITCH_TRACK)
    log = "cancelling — pin will revert to the previous model"
    if notes:
        # An honest cancel says what it could NOT stop. The switch still unwinds (the
        # script's own readiness poll fails against a dead port), it just takes longer.
        log += " · " + "; ".join(notes)
    return JSONResponse({"ok": True, "log": log})


# ── Aux runner (optional): a small second model on its own port for Odysseus's
# background tasks. ⚠️ ITS THREE ROUTES NOW LIVE IN routers/aux.py — moved there by the
# U64 slice because this file had reached 1,492 of the app layer's 1,500-line limit
# (bridge/tests/test_app_facade.py) and a fix has to be allowed to explain itself.
# `_aux_kill` STAYS here: the model-delete path below calls it, and importing it back
# out of routers/aux.py would make the two modules mutually dependent. aux → models,
# one direction, for ever.
#
# ⛔ U64 — _aux_kill WAS THE ORIGINAL SHAPE OF THE WHOLE INCIDENT CLASS: four
# kill-by-pattern sweeps, three of them the very ENGINE patterns (llama-server /
# mlx_lm.server / mlx_vlm.server + "--port N") that U19 had already torn out of
# scripts/start_component.sh. A pattern is not an identity, and Debi runs standalone
# llama-server / LM Studio / MLX backends: "Stop aux" reached anything on this machine
# whose command line happened to match. Now, in order: (1) data/aux.pid — the pid WE
# wrote at launch, command line re-verified before the signal (core/procs.reap_pidfile);
# (2) the ownership-checked kill on the aux PORT, which refuses a holder that is not
# provably ours. There is no third step. Fenced by
# bridge/contract_tests/test_no_name_kills_contract.py, which is also where the banned
# commands are still spelled out.
def _aux_kill(port: int) -> list:
    """Stop the aux model. Returns the notes for anything it declined to stop."""
    return [note for note in stop_owned_component("aux", port, force=True)
            if NO_PIDFILE_NOTE not in note]
