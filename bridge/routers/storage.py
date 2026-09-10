"""ROUTER — previewed runtime uninstall and conversation-clear transactions."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import threading
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..core.appctx import ROOT, app
from ..core.events import publish
from ..core.storageops import (PLAN_TTL_S, RUNTIME_SPECS, StorageRefusal,
                               apply_artifact_plan, apply_runtime_plan, artifact_plan,
                               runtime_installed, runtime_plan, verify_artifact_plan,
                               verify_runtime_plan)


_PLANS: dict[str, dict] = {}
_PLAN_LOCK = threading.Lock()
_OPTIONAL_LOCK = threading.Lock()
_OPTIONAL_JOB: dict = {"running": False, "queue": [], "receipts": [], "current": ""}


OPTIONAL_INSTALLS = {
    "voicestudio": {"label": "VoiceStudio", "script": "install_component.sh",
                    "args": ("voicestudio", "--yes"), "timeout": 7200,
                    "probe": (("data/voicestudio-venv/bin/python", "exec"),
                              ("vendor/voicestudio/backend/main.py", "file")),
                    "note": "TTS/STT studio; several GB and third-party onboarding."},
    "voicebox": {"label": "Voicebox", "script": "install_component.sh",
                 "args": ("voicebox", "--yes"), "timeout": 7200,
                 "probe": (("data/voicebox-venv/bin/python", "exec"),
                           ("vendor/voicebox/backend/main.py", "file")),
                 "note": "Local voice toolkit; several engines and shared audio helpers."},
    "comfyui": {"label": "ComfyUI + Generate", "script": "install_component.sh",
                "args": ("comfyui", "--yes"), "timeout": 7200,
                "probe": (("data/comfyui-venv/bin/python", "exec"),
                          ("vendor/comfyui/main.py", "file")),
                "note": "Image/video engine. Model downloads remain separately chosen."},
    "unsloth": {"label": "Unsloth Studio", "script": "install_component.sh",
                "args": ("unsloth", "--yes"), "timeout": 7200,
                "probe": (("data/unsloth-home/unsloth_studio/bin/python", "exec"),
                          ("vendor/unsloth/studio/backend/run.py", "file")),
                "note": "Training/serving studio with its own isolated home."},
    "opencode": {"label": "OpenCode", "script": "install_opencode.sh", "args": (),
                 "timeout": 1800, "probe": (("data/opencode/bin/opencode", "exec"),),
                 "note": "Local coding agent binary."},
    "deepseek": {"label": "DeepSeek Harness", "script": "install_deepseek.sh", "args": (),
                 "timeout": 7200,
                 "probe": (("data/deepseek/npm/node_modules/.bin/dsh", "exec"),),
                 "note": "Pinned npm application in an isolated prefix."},
    "aider": {"label": "Aider", "script": "install_aider.sh", "args": (),
              "timeout": 1800, "probe": (("data/aider-venv/bin/aider", "exec"),),
              "note": "Terminal coding agent; workspace is preserved."},
    "goose": {"label": "Goose CLI", "script": "install_goose.sh", "args": (),
              "timeout": 1800, "probe": (("data/goose/bin/goose", "exec"),),
              "note": "Pinned local Goose binary and CLI lane."},
    "gooseui": {"label": "Goose UI", "script": "install_goose_ui.sh", "args": (),
                "timeout": 1800, "requires": ("goose",),
                "probe": (("data/goose/UI-INSTALLED", "file"), ("data/goose/ui", "dir")),
                "note": "Desktop-style UI; selecting it also selects Goose CLI."},
    "loffice": {"label": "LOffice", "script": "install_onlyoffice.sh", "args": (),
                "timeout": 3600, "probe": (("data/onlyoffice/INSTALLED", "file"),),
                "note": "Rich local document editors; documents stay separate."},
    "music-minimax": {"label": "MiniMax Music", "script": "install_music.sh",
                      "args": ("minimax",), "timeout": 7200,
                      "note": "About 11.9 GB shared Hugging Face cache; MLX engine."},
    "music-acestep": {"label": "ACE-Step Music", "script": "install_music.sh",
                      "args": ("acestep",), "timeout": 7200,
                      "note": "About 7.7 GB plus a local Metal build."},
}


def _option_installed(key: str) -> bool:
    if key == "music-minimax" or key == "music-acestep":
        from ..core.appctx import _music
        from ..core.procs import cfg
        if _music is None:
            return False
        engine = key.split("-", 1)[1]
        revision = str(((cfg().get("build") or {}).get("music_minimax_pin") or ""))
        return bool(_music.engine_installed(ROOT, engine, revision if engine == "minimax" else "")[0])
    spec = OPTIONAL_INSTALLS.get(key) or {}
    probes = spec.get("probe") or ()
    if not probes:
        return runtime_installed(ROOT, key)
    for rel, kind in probes:
        path = ROOT / rel
        if kind == "exec" and not (path.is_file() and os.access(path, os.X_OK)):
            return False
        if kind == "file" and not path.is_file():
            return False
        if kind == "dir" and not path.is_dir():
            return False
    return True


def _optional_rows() -> list[dict]:
    return [{"id": key, "label": spec["label"], "installed": _option_installed(key),
             "note": spec["note"], "requires": list(spec.get("requires") or ())}
            for key, spec in OPTIONAL_INSTALLS.items()]


def _optional_snapshot() -> dict:
    with _OPTIONAL_LOCK:
        return json.loads(json.dumps(_OPTIONAL_JOB))


def _install_one(key: str) -> dict:
    """Run one existing, audited installer and return a bounded receipt.

    Installation is intentionally delegated to the same scripts used by Help and
    Mission Control.  This route does not reproduce their pin, digest, manifest or
    rollback logic in a second implementation.
    """
    spec = OPTIONAL_INSTALLS[key]
    from ..core.procs import _script
    started = time.time()
    try:
        result = _script(spec["script"], *spec["args"], timeout=int(spec["timeout"]))
        output = ((result.stdout or "") + ("\n" + result.stderr if result.stderr else "")).strip()
        installed = _option_installed(key)
        ok = result.returncode == 0 and installed
        if result.returncode == 0 and not installed:
            output = (output + "\n" if output else "") + (
                "installer exited successfully, but the exact on-disk install contract "
                "is still incomplete")
        return {"id": key, "label": spec["label"], "ok": ok,
                "returncode": int(result.returncode), "seconds": round(time.time() - started, 2),
                "installed": installed, "tail": output[-4000:]}
    except subprocess.TimeoutExpired as exc:
        return {"id": key, "label": spec["label"], "ok": False, "returncode": None,
                "seconds": round(time.time() - started, 2), "installed": _option_installed(key),
                "tail": f"installer exceeded its {spec['timeout']} second safety limit: {exc}"}
    except Exception as exc:                                    # noqa: BLE001
        return {"id": key, "label": spec["label"], "ok": False, "returncode": None,
                "seconds": round(time.time() - started, 2), "installed": _option_installed(key),
                "tail": str(exc)[-4000:]}


def _optional_worker(job_id: str, queue: list[str]) -> None:
    for key in queue:
        with _OPTIONAL_LOCK:
            if _OPTIONAL_JOB.get("id") != job_id:
                return
            _OPTIONAL_JOB["current"] = key
        publish("storage", operation="install-optional", target=key, state="running")
        try:
            receipt = _install_one(key)
        except Exception as exc:
            # Even a failing disk probe must leave a receipt and release the queue.
            receipt = {"id": key, "label": OPTIONAL_INSTALLS[key]["label"],
                       "ok": False, "returncode": None, "seconds": 0,
                       "installed": None, "tail": str(exc)[-4000:]}
        with _OPTIONAL_LOCK:
            if _OPTIONAL_JOB.get("id") != job_id:
                return
            _OPTIONAL_JOB["receipts"].append(receipt)
            _OPTIONAL_JOB["completed"] = len(_OPTIONAL_JOB["receipts"])
        publish("storage", operation="install-optional", target=key,
                state="done" if receipt["ok"] else "failed")
    with _OPTIONAL_LOCK:
        if _OPTIONAL_JOB.get("id") == job_id:
            _OPTIONAL_JOB["running"] = False
            _OPTIONAL_JOB["current"] = ""
            _OPTIONAL_JOB["finished_at"] = time.time()


def _expand_optional_selection(raw: object) -> list[str]:
    if not isinstance(raw, list) or not raw:
        raise StorageRefusal("select at least one optional tool")
    selected: list[str] = []
    visiting: set[str] = set()

    def add(key: str) -> None:
        if key not in OPTIONAL_INSTALLS:
            raise StorageRefusal(f"unknown optional install: {key}")
        if key in selected:
            return
        if key in visiting:
            raise StorageRefusal("optional install dependency cycle")
        visiting.add(key)
        for dep in OPTIONAL_INSTALLS[key].get("requires") or ():
            add(str(dep))
        visiting.remove(key)
        if not _option_installed(key):
            selected.append(key)

    for value in raw:
        add(str(value or "").strip().lower())
    return selected


@app.get("/api/storage/optional")
def storage_optional() -> JSONResponse:
    return JSONResponse({"ok": True,
                         "core": ["MOT Deck shell and panel", "runner", "Hermes",
                                  "Odysseus", "SearXNG", "API and Capabilities"],
                         "options": _optional_rows(), "job": _optional_snapshot()})


@app.post("/api/storage/optional/install")
async def storage_optional_install(req: Request) -> JSONResponse:
    try:
        body = await req.json()
        queue = _expand_optional_selection((body or {}).get("ids"))
        with _OPTIONAL_LOCK:
            if _OPTIONAL_JOB.get("running"):
                raise StorageRefusal("another optional installation is already running")
            if not queue:
                return JSONResponse({"ok": True, "started": False,
                                     "message": "Every selected tool is already installed",
                                     "job": json.loads(json.dumps(_OPTIONAL_JOB))})
            job_id = uuid.uuid4().hex
            _OPTIONAL_JOB.clear()
            _OPTIONAL_JOB.update({"id": job_id, "running": True, "queue": queue,
                                  "receipts": [], "current": "", "completed": 0,
                                  "started_at": time.time(), "finished_at": None})
        thread = threading.Thread(target=_optional_worker, args=(job_id, queue),
                                  name="motdeck-optional-install", daemon=True)
        try:
            thread.start()
        except Exception:
            with _OPTIONAL_LOCK:
                if _OPTIONAL_JOB.get("id") == job_id:
                    _OPTIONAL_JOB.update(running=False, current="", finished_at=time.time())
            raise
        return JSONResponse({"ok": True, "started": True, "job": _optional_snapshot()})
    except StorageRefusal as exc:
        return _refusal(exc)
    except Exception as exc:                                    # noqa: BLE001
        return _refusal(exc, 500)


def _response_data(response) -> object:
    try:
        return json.loads(bytes(response.body).decode("utf-8"))
    except Exception:                                            # noqa: BLE001
        return None


def _put_plan(plan: dict) -> tuple[str, int]:
    token = secrets.token_urlsafe(24)
    now = time.time()
    with _PLAN_LOCK:
        for key, row in list(_PLANS.items()):
            if float(row.get("expires") or 0) <= now:
                _PLANS.pop(key, None)
        _PLANS[token] = {"expires": now + PLAN_TTL_S, "plan": plan}
    return token, PLAN_TTL_S


def _take_plan(token: str, operation: str) -> dict:
    with _PLAN_LOCK:
        row = _PLANS.pop(str(token or ""), None)
    if not row or float(row.get("expires") or 0) <= time.time():
        raise StorageRefusal("the preview expired or was already used; review it again")
    plan = row.get("plan") or {}
    if plan.get("operation") != operation:
        raise StorageRefusal("the confirmation does not match this operation")
    return plan


def _refusal(exc: Exception, status: int = 409) -> JSONResponse:
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=status)


IDLE_PREFS_FILE = "idle_prefs.json"
VALID_IDLE_POLICIES = {"auto", "awake", "sleep"}
_IDLE_LOCK = threading.RLock()


def _read_idle_prefs(root: Path = ROOT) -> dict[str, str]:
    path = Path(root) / "data" / IDLE_PREFS_FILE
    with _IDLE_LOCK:
        try:
            if not path.is_file():
                return {}
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                raw = data.get("prefs") if "prefs" in data else data
                if isinstance(raw, dict):
                    return {str(k): str(v) for k, v in raw.items() if str(v) in VALID_IDLE_POLICIES}
        except Exception:
            pass
        return {}


def _write_idle_prefs(patch: dict, root: Path = ROOT) -> dict[str, str]:
    with _IDLE_LOCK:
        current = _read_idle_prefs(root)
        for k, v in patch.items():
            k_clean = str(k).strip().lower()
            v_clean = str(v).strip().lower()
            if v_clean in VALID_IDLE_POLICIES:
                current[k_clean] = v_clean
        path = Path(root) / "data" / IDLE_PREFS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".idle-prefs-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, "prefs": current}, fh, indent=2)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        return current


@app.get("/api/storage/idle_prefs")
def get_idle_prefs() -> JSONResponse:
    return JSONResponse({"ok": True, "prefs": _read_idle_prefs(ROOT)})


@app.post("/api/storage/idle_prefs")
async def update_idle_prefs(req: Request) -> JSONResponse:
    try:
        body = await req.json()
        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "error": "payload must be an object"}, status_code=400)
        patch = {}
        if "id" in body and "policy" in body:
            patch[str(body["id"])] = str(body["policy"])
        elif "prefs" in body and isinstance(body["prefs"], dict):
            patch = body["prefs"]
        else:
            patch = body
        updated = _write_idle_prefs(patch, ROOT)
        publish("storage", operation="idle_prefs", prefs=updated)
        return JSONResponse({"ok": True, "prefs": updated})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.get("/api/storage/runtimes")
def storage_runtimes() -> JSONResponse:
    rows = []
    idle_prefs = _read_idle_prefs(ROOT)
    for key, spec in RUNTIME_SPECS.items():
        rows.append({"id": key, "label": spec.label,
                     "installed": runtime_installed(ROOT, key),
                     "idle_policy": idle_prefs.get(key, "auto"),
                     "preserve": list(spec.preserve), "note": spec.note})
    return JSONResponse({"ok": True, "runtimes": rows, "count": len(rows),
                         "reset": _reset_capability(),
                         "idle_prefs": idle_prefs})


@app.post("/api/storage/runtime/plan")
async def storage_runtime_plan(req: Request) -> JSONResponse:
    try:
        body = await req.json()
        plan = await run_in_threadpool(runtime_plan, ROOT, str((body or {}).get("target") or ""))
        token, ttl = _put_plan(plan)
        return JSONResponse({"ok": True, "token": token, "expires_in": ttl, **plan})
    except StorageRefusal as exc:
        return _refusal(exc)
    except Exception as exc:                                    # noqa: BLE001
        return _refusal(exc, 500)


def _stop_for_runtime(target: str, component: str) -> JSONResponse | None:
    """Use the lane's one existing exact-owner stop path; never discover a process."""
    if component:
        from .component_lifecycle import stop
        return stop(component)
    if target == "aider":
        from .aider import aider_end
        return aider_end()
    if target == "goose":
        from .goose import goose_end
        return goose_end()
    if target == "gooseui":
        from .gooseui import gooseui_stop
        return gooseui_stop()
    return None


@app.post("/api/storage/runtime/apply")
async def storage_runtime_apply(req: Request) -> JSONResponse:
    try:
        body = await req.json()
        plan = _take_plan(str((body or {}).get("token") or ""), "uninstall-runtime")
        # Refuse stale evidence before even stopping a healthy component. The apply
        # transaction verifies again after the stop and immediately before the moves.
        await run_in_threadpool(verify_runtime_plan, ROOT, plan)
        stopped = await run_in_threadpool(_stop_for_runtime, plan["target"], str(plan.get("stop_component") or ""))
        if stopped is not None and int(getattr(stopped, "status_code", 500)) >= 400:
            detail = _response_data(stopped)
            raise StorageRefusal(str((detail or {}).get("log") or
                                     (detail or {}).get("error") or
                                     "the owned process could not be stopped"))
        result = await run_in_threadpool(apply_runtime_plan, ROOT, plan)
        publish("storage", operation="uninstall-runtime", target=plan["target"],
                state="done")
        return JSONResponse(result)
    except StorageRefusal as exc:
        return _refusal(exc)
    except OSError as exc:
        return _refusal(StorageRefusal(
            f"the runtime was not removed: {exc}. Nothing is copied across filesystems."))
    except Exception as exc:                                    # noqa: BLE001
        return _refusal(exc, 500)


def _music_asset_plan(engine: str) -> dict:
    from ..core.appctx import _music
    if _music is None:
        raise StorageRefusal("the Music module is unavailable")
    engine = str(engine or "").strip().lower()
    if engine not in _music.ENGINES:
        raise StorageRefusal("unknown Music engine")
    if _music.job_busy():
        raise StorageRefusal("a Music render is active; stop or finish it before removing its engine")
    from ..core.procs import cfg
    revision = str(((cfg().get("build") or {}).get("music_minimax_pin") or ""))
    if not _music.engine_installed(ROOT, engine, revision if engine == "minimax" else "")[0]:
        raise StorageRefusal("that Music engine is not installed")
    cache = Path(os.path.abspath(_music.hf_cache_root()))
    if engine == "minimax":
        repo = _music.MINIMAX_REPO
        repo_dir = cache / ("models--" + repo.replace("/", "--"))
        return artifact_plan(
            "remove-music-assets", engine, "MiniMax Music engine and model",
            (repo_dir,), owned_roots=(cache,),
            preserve=("data/music-venv shared helper", "Music library and outputs"),
            note=("This is a shared Hugging Face cache repository. Other local apps "
                  "using the same MiniMax revision will need to download it again."),
            impact=({"engine": engine, "shared_cache": True,
                     "repo": repo, "effect": "engine becomes not installed"},),
        )
    repo = "Serveurperso/ACE-Step-1.5-GGUF"
    repo_dir = cache / ("models--" + repo.replace("/", "--"))
    integration = ROOT / "data" / "acestep"
    return artifact_plan(
        "remove-music-assets", engine, "ACE-Step integration and model",
        (integration, repo_dir), owned_roots=(ROOT / "data", cache),
        preserve=("data/music-venv shared helper", "Music library and outputs"),
        note=("The GGUF repository is in the shared Hugging Face cache. Other local "
              "apps using this exact repository will need to download it again."),
        impact=({"engine": engine, "shared_cache": True,
                 "repo": repo, "effect": "engine becomes not installed"},),
    )


@app.post("/api/storage/music/plan")
async def storage_music_plan(req: Request) -> JSONResponse:
    try:
        body = await req.json()
        plan = await run_in_threadpool(_music_asset_plan, str((body or {}).get("engine") or ""))
        token, ttl = _put_plan(plan)
        return JSONResponse({"ok": True, "token": token, "expires_in": ttl, **plan})
    except StorageRefusal as exc:
        return _refusal(exc)
    except Exception as exc:                                    # noqa: BLE001
        return _refusal(exc, 500)


@app.post("/api/storage/music/apply")
async def storage_music_apply(req: Request) -> JSONResponse:
    try:
        body = await req.json()
        plan = _take_plan(str((body or {}).get("token") or ""), "remove-music-assets")
        from ..core.appctx import _music
        if _music is None or _music.job_busy():
            raise StorageRefusal("Music became busy after preview; review the removal again")
        result = apply_artifact_plan(plan)
        publish("storage", operation="remove-music-assets", target=plan["target"], state="done")
        return JSONResponse(result)
    except StorageRefusal as exc:
        return _refusal(exc)
    except OSError as exc:
        return _refusal(StorageRefusal(f"the Music assets were not removed: {exc}"))
    except Exception as exc:                                    # noqa: BLE001
        return _refusal(exc, 500)


def _generate_asset_plan(cat: dict, scope: str, item_id: str) -> dict:
    from ..core.comfycur import models_dir
    scope = str(scope or "").strip().lower()
    item_id = str(item_id or "").strip()
    if scope not in ("model", "workflow") or not item_id:
        raise StorageRefusal("pick one Generate model or workflow")
    models = [m for m in (cat.get("models") or []) if isinstance(m, dict)]
    selected: list[dict] = []
    label = ""
    if scope == "model":
        model = next((m for m in models if str(m.get("id") or "") == item_id), None)
        if model is None:
            raise StorageRefusal("that Generate model is no longer in the live catalogue")
        selected = [w for w in (model.get("workflows") or []) if isinstance(w, dict)]
        label = str(model.get("title") or item_id)
    else:
        for model in models:
            workflow = next((w for w in (model.get("workflows") or [])
                             if str(w.get("id") or "") == item_id), None)
            if workflow is not None:
                selected = [workflow]
                label = str(workflow.get("title") or item_id)
                break
        if not selected:
            raise StorageRefusal("that Generate workflow is no longer in the live catalogue")
    keys: dict[tuple[str, str], dict] = {}
    for workflow in selected:
        for row in workflow.get("files") or []:
            if isinstance(row, dict) and row.get("present"):
                directory, name = str(row.get("directory") or ""), str(row.get("name") or "")
                if directory and name:
                    keys[(directory, name)] = row
    if not keys:
        raise StorageRefusal("the selected Generate entry has no downloaded files to remove")
    base = Path(os.path.abspath(models_dir()))
    paths = [base / directory / name for directory, name in keys]
    sharing = []
    for directory, name in keys:
        users = []
        for model in models:
            for workflow in model.get("workflows") or []:
                if any(str(f.get("directory") or "") == directory
                       and str(f.get("name") or "") == name
                       for f in (workflow.get("files") or []) if isinstance(f, dict)):
                    users.append({"model": str(model.get("title") or model.get("id") or ""),
                                  "workflow": str(workflow.get("title") or workflow.get("id") or ""),
                                  "workflow_id": str(workflow.get("id") or "")})
        sharing.append({"file": f"{directory}/{name}", "workflows": users,
                        "shared": len(users) > 1})
    return artifact_plan(
        "remove-generate-assets", f"{scope}:{item_id}",
        f"{label} downloaded files", paths, owned_roots=(base,),
        preserve=("upstream workflow catalogue metadata", "ComfyUI inputs and outputs",
                  "user-authored workflows"),
        note=("This removes only files currently required by the selected " + scope
              + ". The workflow definition remains discoverable and can download them again."),
        impact=sharing,
    )


@app.post("/api/storage/generate/plan")
async def storage_generate_plan(req: Request) -> JSONResponse:
    try:
        body = await req.json()
        from .comfy import CDL, JOBS, catalog_live
        if any(row.get("state") in ("downloading", "verifying") for row in CDL.values()):
            raise StorageRefusal("a Generate download is active; finish or cancel it first")
        if any(row.get("state") in ("running", "finishing") for row in JOBS.values()):
            raise StorageRefusal("a Generate job is active; stop or finish it first")
        plan = await run_in_threadpool(_generate_asset_plan, await catalog_live(force=True),
                                       str((body or {}).get("scope") or ""),
                                       str((body or {}).get("id") or ""))
        token, ttl = _put_plan(plan)
        return JSONResponse({"ok": True, "token": token, "expires_in": ttl, **plan})
    except StorageRefusal as exc:
        return _refusal(exc)
    except Exception as exc:                                    # noqa: BLE001
        return _refusal(exc, 500)


@app.post("/api/storage/generate/apply")
async def storage_generate_apply(req: Request) -> JSONResponse:
    try:
        body = await req.json()
        plan = _take_plan(str((body or {}).get("token") or ""), "remove-generate-assets")
        from .comfy import CDL, JOBS, catalog_invalidate
        if any(row.get("state") in ("downloading", "verifying") for row in CDL.values()) \
                or any(row.get("state") in ("running", "finishing") for row in JOBS.values()):
            raise StorageRefusal("Generate became busy after preview; review the removal again")
        # Refuse changed files before stopping ComfyUI; apply_artifact_plan repeats
        # this immediately before the recoverable rename transaction.
        await run_in_threadpool(verify_artifact_plan, plan)
        stopped = await run_in_threadpool(_stop_for_runtime, "comfyui", "comfyui")
        if stopped is not None and int(getattr(stopped, "status_code", 500)) >= 400:
            detail = _response_data(stopped)
            raise StorageRefusal(str((detail or {}).get("log") or
                                     "ComfyUI could not be stopped by its ownership record"))
        if any(row.get("state") in ("downloading", "verifying") for row in CDL.values()) \
                or any(row.get("state") in ("running", "finishing") for row in JOBS.values()):
            raise StorageRefusal("Generate became busy while stopping; review the removal again")
        result = apply_artifact_plan(plan)
        catalog_invalidate()
        publish("storage", operation="remove-generate-assets", target=plan["target"], state="done")
        return JSONResponse(result)
    except StorageRefusal as exc:
        return _refusal(exc)
    except OSError as exc:
        return _refusal(StorageRefusal(f"the Generate files were not removed: {exc}"))
    except Exception as exc:                                    # noqa: BLE001
        return _refusal(exc, 500)


def _reset_plan(mode: str) -> dict:
    from ..core.appidentity import (AppIdentityError, require_current_factory_seed,
                                    resolve_installed_bundle)
    mode = str(mode or "").strip().lower()
    if mode not in ("factory-reset", "full-uninstall"):
        raise StorageRefusal("unknown reset mode")
    canonical = Path.home() / "Library/Application Support/MOT Deck"
    if Path(os.path.abspath(ROOT)) != Path(os.path.abspath(canonical)):
        raise StorageRefusal("reset is available only from the canonical installed MOT Deck copy")
    if ROOT.is_symlink() or not ROOT.is_dir():
        raise StorageRefusal("the canonical MOT Deck support root is not a real directory")
    try:
        app_path = resolve_installed_bundle()
    except AppIdentityError as exc:
        raise StorageRefusal(str(exc)) from exc
    expected_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    seed_version = ""
    if mode == "factory-reset":
        try:
            seed_version = require_current_factory_seed(app_path, expected_version)
        except (AppIdentityError, OSError) as exc:
            raise StorageRefusal(str(exc)) from exc
    helper = ROOT / "scripts/storage_reset_helper.py"
    if helper.is_symlink() or not helper.is_file():
        raise StorageRefusal("the reset helper is missing or is not a regular installed file")
    root_st, app_st, helper_st = os.lstat(ROOT), os.lstat(app_path), os.lstat(helper)
    helper_digest = hashlib.sha256(helper.read_bytes()).hexdigest()
    from .quitall import quitall_plan
    running_data = _response_data(quitall_plan()) or {}
    plan = {
        "operation": mode, "target": mode,
        "label": "Factory reset MOT Deck" if mode == "factory-reset" else "Uninstall MOT Deck",
        "root": {"path": str(ROOT), "dev": int(root_st.st_dev), "ino": int(root_st.st_ino)},
        "app": {"path": str(app_path), "dev": int(app_st.st_dev), "ino": int(app_st.st_ino)},
        "helper": {"path": str(helper), "dev": int(helper_st.st_dev),
                   "ino": int(helper_st.st_ino), "size": int(helper_st.st_size),
                   "mtime_ns": int(helper_st.st_mtime_ns), "sha256": helper_digest},
        "running": list(running_data.get("running") or []),
        # Do not recursively size the entire live support root here.  It can contain
        # hundreds of gigabytes of runtimes and media, and doing that work in this
        # request would freeze every bridge route while the confirmation sheet says
        # "Verifying".  Exact identity/path evidence is the safety boundary; byte
        # totals are presentation only and are therefore omitted truthfully.
        "bytes": None,
        "size_note": "Size is not scanned here so the running app stays responsive.",
        "preserve": ["repository checkouts", "external workspaces", "shared ~/.hermes",
                     "LM Studio and other external model-manager libraries",
                     "shared Hugging Face caches outside Application Support"],
        "moves": [str(ROOT)] + ([str(app_path)] if mode == "full-uninstall" else []),
        "reopens": mode == "factory-reset",
        "seed_version": seed_version,
        "note": ("The current Application Support root moves to Trash. The installed app "
                 "then reopens and runs its normal first setup. External/shared stores are preserved."
                 if mode == "factory-reset" else
                 "The verified app bundle and its Application Support root move to Trash. "
                 "External/shared stores and every repository checkout are preserved."),
    }
    return plan


def _reset_capability() -> dict:
    """Cheap truth for the reset controls; plans still repeat every proof."""
    from ..core.appidentity import (AppIdentityError, require_current_factory_seed,
                                    resolve_installed_bundle)
    canonical = Path.home() / "Library/Application Support/MOT Deck"
    if Path(os.path.abspath(ROOT)) != Path(os.path.abspath(canonical)):
        return {"full_uninstall": False, "factory_reset": False,
                "reason": "Reset is available only from the installed MOT Deck copy."}
    try:
        app_path = resolve_installed_bundle()
    except AppIdentityError as exc:
        return {"full_uninstall": False, "factory_reset": False, "reason": str(exc)}
    try:
        expected = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        require_current_factory_seed(app_path, expected)
        return {"full_uninstall": True, "factory_reset": True, "reason": ""}
    except (AppIdentityError, OSError) as exc:
        return {"full_uninstall": True, "factory_reset": False, "reason": str(exc)}


@app.post("/api/storage/reset/plan")
async def storage_reset_plan(req: Request) -> JSONResponse:
    try:
        body = await req.json()
        plan = await run_in_threadpool(_reset_plan, str((body or {}).get("mode") or ""))
        token, ttl = _put_plan(plan)
        return JSONResponse({"ok": True, "token": token, "expires_in": ttl, **plan})
    except StorageRefusal as exc:
        return _refusal(exc)
    except Exception as exc:                                    # noqa: BLE001
        return _refusal(exc, 500)


def _same_identity(row: dict) -> bool:
    try:
        st = os.lstat(str(row.get("path") or ""))
        return int(st.st_dev) == int(row.get("dev")) and int(st.st_ino) == int(row.get("ino"))
    except (OSError, TypeError, ValueError):
        return False


def _same_helper(row: dict) -> bool:
    path = Path(str(row.get("path") or ""))
    try:
        st = os.lstat(path)
        if path.is_symlink() or not path.is_file():
            return False
        expected = (int(row.get("dev")), int(row.get("ino")), int(row.get("size")),
                    int(row.get("mtime_ns")))
        actual = (int(st.st_dev), int(st.st_ino), int(st.st_size), int(st.st_mtime_ns))
        return actual == expected and hashlib.sha256(path.read_bytes()).hexdigest() == row.get("sha256")
    except (OSError, TypeError, ValueError):
        return False


@app.post("/api/storage/reset/apply")
async def storage_reset_apply(req: Request) -> JSONResponse:
    try:
        body = await req.json()
        token = str((body or {}).get("token") or "")
        # Tokens are mode-bound, but the client does not need to repeat a mode after
        # the preview. Resolve the one stored operation without accepting either from
        # the request body as authority.
        with _PLAN_LOCK:
            row = _PLANS.get(token) or {}
            operation = str((row.get("plan") or {}).get("operation") or "")
        if operation not in ("factory-reset", "full-uninstall"):
            raise StorageRefusal("the reset preview expired or does not match this operation")
        plan = _take_plan(token, operation)
        if (not _same_identity(plan["root"]) or not _same_identity(plan["app"])
                or not _same_helper(plan.get("helper") or {})):
            raise StorageRefusal("the app, support root, or reset helper changed after preview")
        from ..core.procs import cfg
        from .quitall import _order, _sweep, schedule_bridge_exit
        configuration = cfg()
        sweep = _sweep(_order(configuration), configuration, {"keep_bridge": True})
        sweep_data = _response_data(sweep) or {}
        if int(getattr(sweep, "status_code", 500)) >= 400 or not sweep_data.get("ok"):
            raise StorageRefusal("reset stopped because some owned processes did not stop: "
                                 + "; ".join(sweep_data.get("sentences") or []))
        helper = Path(plan["helper"]["path"])
        log_path = Path(tempfile.gettempdir()) / f"motdeck-{operation}-{secrets.token_hex(5)}.log"
        argv = ["/usr/bin/python3", str(helper), "--mode", operation,
                "--root", plan["root"]["path"], "--app", plan["app"]["path"],
                "--root-dev", str(plan["root"]["dev"]), "--root-ino", str(plan["root"]["ino"]),
                "--app-dev", str(plan["app"]["dev"]), "--app-ino", str(plan["app"]["ino"]),
                "--bridge-pid", str(os.getpid()),
                "--expected-version", str(plan.get("seed_version") or "")]
        with log_path.open("ab") as log:
            subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             start_new_session=True, close_fds=True)
        publish("storage", operation=operation, target="motdeck", state="scheduled")
        schedule_bridge_exit()
        return JSONResponse({"ok": True, "scheduled": True, "mode": operation,
                             "log": str(log_path), "stopped": sweep_data.get("stopped") or [],
                             "message": ("MOT Deck will close, reset, and reopen."
                                         if operation == "factory-reset" else
                                         "MOT Deck will close and move the app plus its data to Trash.")})
    except StorageRefusal as exc:
        return _refusal(exc)
    except Exception as exc:                                    # noqa: BLE001
        return _refusal(exc, 500)


async def _chat_rows(lane: str) -> list[dict]:
    if lane == "odysseus":
        from .ody import ody_sessions
        response = await ody_sessions()
    elif lane == "hermes":
        from .hermes import hermes_sessions
        response = await hermes_sessions()
    else:
        raise StorageRefusal("chat clearing currently supports Odysseus and Hermes")
    if int(getattr(response, "status_code", 500)) >= 400:
        raise StorageRefusal(f"{lane} could not list its sessions")
    rows = _response_data(response)
    if not isinstance(rows, list):
        raise StorageRefusal(f"{lane} returned an unreadable session list")
    return [row for row in rows if isinstance(row, dict) and str(row.get("id") or "")]


def _session_evidence(rows: list[dict]) -> list[dict]:
    return [{"id": str(row.get("id") or ""),
             "updated_at": row.get("updated_at"),
             "message_count": row.get("message_count")}
            for row in rows]


@app.post("/api/storage/chats/plan")
async def storage_chats_plan(req: Request) -> JSONResponse:
    try:
        body = await req.json()
        lane = str((body or {}).get("lane") or "").strip().lower()
        rows = await _chat_rows(lane)
        evidence = _session_evidence(rows)
        plan = {"operation": "clear-chats", "lane": lane, "sessions": evidence,
                "count": len(evidence), "atomic": False,
                "note": ("Sessions are deleted one by one through the app's supported "
                         "API; any partial result is reported per session.")}
        token, ttl = _put_plan(plan)
        return JSONResponse({"ok": True, "token": token, "expires_in": ttl, **plan})
    except StorageRefusal as exc:
        return _refusal(exc)
    except Exception as exc:                                    # noqa: BLE001
        return _refusal(exc, 500)


async def _delete_one_chat(lane: str, sid: str) -> tuple[bool, str]:
    if lane == "odysseus":
        from .ody import ody_session_delete
        response = await ody_session_delete(sid)
    else:
        from .hermes import _HERMES, HERMES_TURNS
        turn = HERMES_TURNS.find(stored_sid=sid, active_only=True)
        if turn is not None:
            try:
                await _HERMES.rpc("session.close", {"session_id": turn.sid}, timeout=15.0)
            except Exception:                                  # noqa: BLE001
                pass
        try:
            result = await _HERMES.rpc("session.delete", {"session_id": sid})
            return True, str(result.get("deleted") or sid)
        except Exception as exc:                               # noqa: BLE001
            return False, str(exc)[:300]
    data = _response_data(response)
    ok = int(getattr(response, "status_code", 500)) < 400 and bool((data or {}).get("ok"))
    return ok, "deleted" if ok else str((data or {}).get("error") or "delete refused")[:300]


@app.post("/api/storage/chats/apply")
async def storage_chats_apply(req: Request) -> JSONResponse:
    try:
        body = await req.json()
        plan = _take_plan(str((body or {}).get("token") or ""), "clear-chats")
        fresh = _session_evidence(await _chat_rows(plan["lane"]))
        if fresh != plan["sessions"]:
            raise StorageRefusal("the session list changed after preview; review it again")
        receipts = []
        for row in plan["sessions"]:
            try:
                ok, detail = await _delete_one_chat(plan["lane"], row["id"])
            except Exception as exc:  # retain every receipt after a partial mutation
                ok, detail = False, f"could not confirm deletion: {str(exc)[:250]}"
            receipts.append({"id": row["id"], "ok": ok, "detail": detail})
        deleted = sum(1 for row in receipts if row["ok"])
        result = {"ok": deleted == len(receipts), "lane": plan["lane"],
                  "deleted": deleted, "count": len(receipts), "receipts": receipts,
                  "atomic": False}
        publish("storage", operation="clear-chats", target=plan["lane"],
                state="done" if result["ok"] else "partial")
        return JSONResponse(result, status_code=200 if result["ok"] else 409)
    except StorageRefusal as exc:
        return _refusal(exc)
    except Exception as exc:                                    # noqa: BLE001
        return _refusal(exc, 500)
