"""ROUTER — the AUX runner lane: set the aux model, start it, stop it.

Aux is an optional SECOND, small model on its own port, so Odysseus's background tasks
(titles, search-query generation, memory extraction) stop competing for the main
runner's single slot. The model is user-chosen from installed models ("Set aux" in the
Models pane) and never hardcoded.

WHY THIS IS ITS OWN FILE (U64 slice, 2026-09-02). These three routes lived at the bottom
of routers/models.py, which had reached 1,492 lines against the app layer's 1,500-line
fence (bridge/tests/test_app_facade.py) — eight lines of headroom, i.e. no room to
document a fix inside the file the fix was in. The aux lane is the natural seam: one
feature, three routes, one process. `_aux_kill` deliberately STAYED in models.py because
the model-delete path calls it, and importing it back from here would make the two
modules mutually dependent; the dependency runs one way only, aux → models.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from fastapi import Request
from fastapi.responses import JSONResponse
from ..core.appctx import ROOT, app
from ..core import ownership as _ownership
from ..core.modelreg import artifact_probe, is_source_unlisted
from ..core.procs import NO_PIDFILE_NOTE, _port_alive_sync, cfg, write_pidfile
from ..core.yamlset import _set_yaml_model
from .models import _aux_kill, _fit_advice, _reject_if_audio, foreign_runner_gate


# U65 — RETAIN THE ACTUAL CHILD HANDLE UNTIL IT HAS BEEN WAITED.
#
# The ownership record controls signal authority; this handle controls parent/child
# lifecycle.  They are deliberately different responsibilities.  Before this waiter,
# Stop correctly signalled only the PID+birth child we launched, but nobody called
# wait(2), leaving one zombie per Aux start/stop until the bridge itself exited.
_AUX_LIFECYCLE_LOCK = threading.Lock()
_AUX_PROC: subprocess.Popen | None = None
_AUX_BIRTH = ""


def _reap_aux_child(proc: subprocess.Popen, birth: str) -> None:
    """Wait for one exact child, then retire only its matching launch record."""
    global _AUX_PROC, _AUX_BIRTH
    proc.wait()
    _ownership.retire_owned(ROOT, "aux", proc.pid, birth)
    with _AUX_LIFECYCLE_LOCK:
        # A later Start may already have installed a replacement handle.  The old
        # waiter must not erase it; object identity is stronger than a recycled PID.
        if _AUX_PROC is proc:
            _AUX_PROC = None
            _AUX_BIRTH = ""


def _retain_aux_child(proc: subprocess.Popen, birth: str) -> None:
    """Caller holds ``_AUX_LIFECYCLE_LOCK``; preserve and start its one waiter."""
    global _AUX_PROC, _AUX_BIRTH
    _AUX_PROC, _AUX_BIRTH = proc, birth
    waiter = threading.Thread(
        target=_reap_aux_child, args=(proc, birth),
        name=f"secondary-runner-reaper-{proc.pid}", daemon=True)
    try:
        waiter.start()
    except BaseException:
        _AUX_PROC, _AUX_BIRTH = None, ""
        raise


@app.post("/api/aux/set")
async def aux_set(req: Request) -> JSONResponse:
    new_id = ((await req.json()).get("id") or "").strip()
    if not new_id:
        return JSONResponse({"ok": False, "log": "no model id"}, status_code=400)
    _bad = _reject_if_audio(new_id)
    if _bad is not None:
        return _bad
    try:
        models = json.loads((ROOT / "data" / "models.json").read_text()).get("models", [])
    except Exception:
        models = []
    entry = next((m for m in models if m.get("id") == new_id), None)
    if entry is None:
        return JSONResponse({"ok": False, "log": f"aux model '{new_id}' not in registry"}, status_code=400)
    if is_source_unlisted(entry):
        return JSONResponse({"ok": False,
                             "log": f"aux model '{new_id}' is no longer listed by its source manager. Rescan or pick another model"},
                            status_code=409)
    probe = artifact_probe(entry)
    if probe["state"] != "ready":
        status = 400 if probe["state"] == "missing" else 409
        return JSONResponse({"ok": False,
                             "log": f"aux model '{new_id}' is {probe['state']}: "
                                    f"{probe['detail']}. Rescan or pick another model"},
                            status_code=status)
    _set_yaml_model("aux", new_id)
    return JSONResponse({"ok": True, "model": new_id})


@app.post("/api/aux/start")
def aux_start(req: Request) -> JSONResponse:
    # Start and Stop can arrive on different FastAPI worker threads.  One lifecycle
    # lock prevents two callers from both observing a clear port and spawning into it.
    with _AUX_LIFECYCLE_LOCK:
        return _aux_start_locked(req)


def _aux_start_locked(req: Request) -> JSONResponse:
    """Launch the aux model on its own port using the SAME engine dispatch as the
    main runner (registry format: gguf→llama-server, mlx→mlx servers). The old
    `jan serve` path knew nothing about motdeck-downloaded models."""
    import json as _json, os as _os, glob as _glob
    note = ""                    # the W-04 line about a foreign binary, "" when ours
    ax = cfg().get("aux", {}) or {}
    model, port = ax.get("model") or "", int(ax.get("port") or 6768)
    key = str(ax.get("api_key") or "")
    if not key:
        return JSONResponse({"error": "aux API key is not provisioned"}, status_code=503)
    if not model:
        return JSONResponse({"ok": False, "log": "no aux model set — use 'Set aux' on an installed model"}, status_code=400)
    try:
        models = _json.loads((ROOT / "data" / "models.json").read_text()).get("models", [])
    except Exception:
        models = []
    m = next((x for x in models if x.get("id") == model), None)
    if not m or not m.get("path"):
        return JSONResponse({"ok": False, "log": f"aux model '{model}' not in registry"}, status_code=400)
    if is_source_unlisted(m):
        return JSONResponse({"ok": False,
                             "log": f"aux model '{model}' is no longer listed by its source manager. Rescan or pick another model"},
                            status_code=409)
    probe = artifact_probe(m)
    if probe["state"] != "ready":
        return JSONResponse(
            {"ok": False,
             "log": f"aux model '{model}' is {probe['state']}: {probe['detail']}. "
                    "Rescan or pick another model"}, status_code=400)
    fmt, path, mmproj = m.get("format", "gguf"), m["path"], m.get("mmproj")
    # The aux slot gets the SAME advisory gate as the main one (v1.5.30) — it is a
    # second model resident BESIDE the first, so nothing is freed by starting it and
    # `freeing_bytes` stays 0. Consent rides `?confirm=1` here because this route has
    # never taken a body; the override exists on every surface either way.
    _confirm = str(req.query_params.get("confirm") or "").lower() in ("1", "true", "yes")
    _adv = _fit_advice(model, slot="aux")
    from ..core import memoryprefs as _memoryprefs
    if (_adv is not None and _memoryprefs.needs_confirmation(
            _adv.get("verdict"), model) and not _confirm):
        _c = _adv.get("copy") or {}
        return JSONResponse({"ok": False, "needs_confirm": True, "advisory": _adv,
                             "log": _c.get("line") or "this may not fit"},
                            status_code=409)
    if _adv is not None and _confirm and _adv.get("verdict") in ("tight", "over"):
        try:
            _memoryprefs.acknowledge(model)
        except (OSError, ValueError) as exc:
            print(f"[fit] could not remember aux override for {model}: {exc}",
                  flush=True)
    # Clear the slot, and if we could NOT clear it SAY SO rather than launch a second
    # server onto a held port and let the bind fail into aux.log where nobody looks —
    # a port held by something not provably ours is a refusal by design now (U64).
    # ⚠️ AND WAIT FIRST: a kill returns before the kernel releases the socket, so an
    # immediate probe would refuse our OWN just-stopped aux (the race the runner Stop
    # documents at length in routers/components.py).
    _pre = _aux_kill(port)
    if _pre:
        return JSONResponse({"ok": False, "log": "; ".join(_pre)}, status_code=409)
    for _ in range(8):
        if not _port_alive_sync(port):
            break
        time.sleep(0.25)
    if _port_alive_sync(port):
        return JSONResponse(
            {"ok": False,
             "log": "; ".join(_pre) or f"something is still listening on :{port} — "
                    f"refusing to start a second aux server on top of it"},
            status_code=409)
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
        owner = ""
        if not binp:
            # SHARED binary-discovery order (keep identical in start_component.sh):
            #   explicit runner.binary → OUR pin (data/llamacpp) → Jan backends → LM Studio.
            pin_bin = str(ROOT / "data" / "llamacpp" / "build" / "bin" / "llama-server")
            if _os.path.isfile(pin_bin) and _os.access(pin_bin, _os.X_OK):
                binp = pin_bin
            else:
                jan = sorted(_glob.glob(_os.path.expanduser(
                          "~/Library/Application Support/Jan/data/llamacpp/backends/*/macos-arm64/build/bin/llama-server")),
                          key=_os.path.getmtime, reverse=True)
                lms = sorted(_glob.glob(_os.path.expanduser("~/.lmstudio/extensions/backends/*/llama-server")),
                          key=_os.path.getmtime, reverse=True)
                cands = jan or lms
                if not cands:
                    return JSONResponse({"ok": False, "log": "no llama-server binary found — run scripts/install_llamacpp.sh"}, status_code=500)
                binp = cands[0]
                # WHOSE binary this is — the whole of the W-04 gate below rests on it.
                owner = "Jan" if jan else "LM Studio"
        # ⚠️ A FOREIGN llama-server IS NAMED, AND REFUSED UNLESS ITS BUILD IS THE PIN
        # (bug-echo W-04). See foreign_runner_gate: same rules, same words, as
        # scripts/start_component.sh's runner branch.
        note, refusal = foreign_runner_gate(binp, owner)
        if refusal:
            return JSONResponse({"ok": False, "log": refusal}, status_code=409)
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
    # ⚠️ A FOREIGN BINARY THAT IS ALLOWED THROUGH IS STILL SAID OUT LOUD — on the card
    # (the log string the pane renders) AND in aux.log, where somebody debugging the
    # thing an hour later will be looking (bug-echo W-04). `note` is "" on every ordinary
    # start, so this costs the normal path nothing.
    if note:
        logf.write(("[motdeck] " + note + "\n").encode())
        logf.flush()
    proc = subprocess.Popen(cmd, stdout=logf, stderr=logf, start_new_session=True)
    # ⛔ AND WE WRITE DOWN THE PID (U64) — without it Stop aux has no identity to verify,
    # which is exactly why it used to reach for a pattern. This is our own child handle
    # (the engine is exec'd directly, no shell between), and only a pid we launched may
    # ever enter a pidfile: reap_pidfile signals what this file names.
    try:
        _, birth = write_pidfile("aux", proc.pid)
        _retain_aux_child(proc, birth)
    except Exception as exc:
        proc.terminate()  # exact child handle; never search by name or port
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
        try:
            _ownership.retire_owned(ROOT, "aux", proc.pid,
                                    locals().get("birth", ""))
        except Exception:
            pass
        logf.close()
        return JSONResponse({"ok": False,
                             "log": f"could not retain aux launch lifecycle: {exc}"},
                            status_code=500)
    logf.close()
    return JSONResponse({"ok": True, "log": (note + " · " if note else "")
                         + "loading in background — refresh in ~20-60s"})


@app.post("/api/aux/stop")
def aux_stop() -> JSONResponse:
    with _AUX_LIFECYCLE_LOCK:
        return _aux_stop_locked()


def _aux_stop_locked() -> JSONResponse:
    """Stop the aux model, and REPORT WHAT ACTUALLY HAPPENED.

    A quiet port cannot overrule a refused stop: an owned child may still be loading
    before it binds. Preserve that refusal before checking socket shutdown."""
    ax = cfg().get("aux", {}) or {}
    port = int(ax.get("port") or 6768)
    was_up = _port_alive_sync(port)
    notes = _aux_kill(port)
    notes = [n for n in notes if NO_PIDFILE_NOTE not in n]
    if notes:
        return JSONResponse({"ok": False, "log": "; ".join(notes)}, status_code=409)
    if not was_up:
        log = f"nothing was listening on :{port}"
        return JSONResponse({"ok": True, "log": log})
    for _ in range(12):                     # up to ~3s for the socket to be torn down
        if not _port_alive_sync(port):
            return JSONResponse({"ok": True, "log": "aux stopped"})
        time.sleep(0.25)
    return JSONResponse(
        {"ok": False,
         "log": "; ".join(notes) or f"port :{port} still answers 3s after the stop"},
        status_code=409)
