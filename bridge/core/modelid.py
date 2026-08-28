"""CORE — which model is the runner ACTUALLY serving, and what do we call it.

The wire-identifier / registry-id distinction and the single source of truth for
"live", extracted whole. Read by the components, models, chat and aider lanes.
"""
from __future__ import annotations

import os
from .appctx import ROOT
from .procs import _registry_models, cfg


def _runner_engine(rc: dict) -> str:
    """Human label for the engine the active model will run on (mirrors the
    start script's dispatch: gguf→llama.cpp, mlx→mlx-lm, mlx+vision→mlx-vlm)."""
    adapter = (rc.get("adapter") or "auto").strip()
    if adapter == "lmstudio":
        return "lmstudio"   # reserved-but-unimplemented fallback
    try:
        import json as _json
        models = _json.loads((ROOT / "data" / "models.json").read_text()).get("models", [])
        m = next((x for x in models if x.get("id") == rc.get("model")), None)
    except Exception:
        m = None
    if adapter in ("auto", "mlx") and m and m.get("format") == "mlx":
        return "mlx-vlm · vision" if m.get("vision") else "mlx-lm"
    if adapter == "mlx":
        return "mlx-lm"
    return "llama.cpp"


# ── Wire identifier vs registry id (Fable, 2026-08-06 — MLX "runner 400" fix) ─
# Our REGISTRY ID is the internal key everywhere (harness.yaml runner.model, the
# RAM ledger, panel labels/selects). But the identifier that goes ON THE WIRE to
# the runner is engine-dependent:
#   • llama.cpp — start_component.sh launches with `--alias <registry id>`, so the
#     registry id IS the served model name. Unchanged.
#   • MLX (mlx_lm.server / mlx_vlm.server) — the request's `model` field is treated
#     as A MODEL TO LOAD (server.py ModelProvider.load → mlx_lm.utils.load), so an
#     unresolvable name is looked up on HuggingFace → 404 → the server answers 400
#     ("Failed to load model: … Repository Not Found"). Neither server has an
#     alias/served-model-name flag (recon: mlx-lm 0.31.3 + mlx-vlm 0.6.10 argv).
#     Therefore the wire identifier is the model's LOCAL PATH, byte-identical to the
#     `--model` argument used at launch (both read the same registry `path`), so the
#     provider's model_key matches and it does NOT reload the weights.
def wire_model_id(model_id: "str | None", models: list) -> str:
    """PURE. Registry id → the identifier to put on the wire for the runner.
    gguf/unknown format → the id unchanged; mlx → the registry path (falls back to
    the id when the entry has no path). Empty id → "". Unknown id → unchanged
    (safe fallback = previous behavior)."""
    mid = (model_id or "").strip()
    if not mid:
        return ""
    m = next((x for x in (models or []) if x.get("id") == mid), None)
    if not m:
        return mid
    if str(m.get("format") or "gguf").strip().lower() == "mlx":
        return str(m.get("path") or "").strip() or mid
    return mid


def display_model_id(wire: "str | None", models: list) -> str:
    """PURE inverse of wire_model_id, for LABELS ONLY: a wire identifier (for MLX a
    long filesystem path — which is also what Odysseus stores as a session's model)
    → our registry id when we can recognise it, else the input unchanged. Matches on
    exact id, then exact path, then trailing-slash-insensitive path, then path
    basename (covers a resolved/symlinked path reported by the runner probe)."""
    w = (wire or "").strip()
    if not w:
        return ""
    ms = [x for x in (models or []) if x.get("id")]
    if any(x.get("id") == w for x in ms):
        return w
    paths = [(x, str(x.get("path") or "").strip()) for x in ms]
    for x, p in paths:
        if p and p == w:
            return x["id"]
    wn = w.rstrip("/")
    for x, p in paths:
        if p and p.rstrip("/") == wn:
            return x["id"]
    base = os.path.basename(wn)
    if base:
        for x, p in paths:
            if p and os.path.basename(p.rstrip("/")) == base:
                return x["id"]
    return w


def runner_wire_model() -> str:
    """The wire identifier for the ACTIVE runner model (harness.yaml runner.model)."""
    return wire_model_id((cfg().get("runner", {}) or {}).get("model") or "",
                         _registry_models())


def _display_model(name):
    """Label-safe wrapper for values we hand back to the panel: keeps falsy values
    as-is (Odysseus may report null) and never raises."""
    if not name:
        return name
    try:
        return display_model_id(name, _registry_models())
    except Exception:
        return name


# ── Single source of truth for "live" (Fable ISSUE C) ────────────────────────
# harness.yaml's runner.model records INTENT, not reality — which is why MC could
# show a runner "green + model" while nothing was actually loaded. The authoritative
# signal is the runner ITSELF: ask what it is serving (GET :port/v1/models). Both
# MC (/api/status) and the Models pane (/api/models) key off this so they agree.
def _runner_loaded_id(port: int) -> "str | None":
    """Probe the runner for the model it is actually serving. Returns the loaded
    model id, or None if the runner is down / has nothing loaded. Short timeout.

    ⚠️ THE API KEY IS NOT OPTIONAL HERE (fixed 2026-08-28, llama.cpp b10427 → b10662).
    This function used to send no Authorization header, and said in this docstring that
    "/v1/models needs no api-key on llama-server". That was TRUE at b10427 and became
    FALSE at b10662 — measured, not guessed, by running both binaries model-less with
    `--api-key testkey`:

        b10427   GET /v1/models with no key → 200
        b10662   GET /v1/models with no key → 401

    start_component.sh always passes `--api-key` when the binary supports it, so on
    b10662 the keyless probe 401s every time, returns None here, and `_reconcile_live`
    reads that as "nothing is loaded". Mission Control then showed `running: false,
    loaded: false` for a runner that was serving generations at 14 tok/s — a
    LIE-TO-USER, and it also filled data/logs/runner.log with one
    "unauthorized: Invalid API Key" per status poll.

    The key is sent unconditionally: llama-server ignores a bearer it does not require,
    and the loopback MLX servers ignore it too, so one code path covers every engine.
    Which key is chosen is decided BY PORT rather than assuming the runner's: every
    caller today passes runner.port, but aux serves on its own port with its own key,
    and hard-coding runner.api_key here would plant exactly the same 401 for whoever
    first probes aux.
    """
    import json as _json
    from urllib.request import Request, urlopen
    try:
        req = Request(f"http://127.0.0.1:{int(port)}/v1/models")
        _c = cfg()
        _rc = _c.get("runner", {}) or {}
        _ax = _c.get("aux", {}) or {}
        key = _rc.get("api_key") or ""
        try:
            if _ax.get("port") and int(_ax["port"]) == int(port) \
                    and int(_rc.get("port") or 0) != int(port):
                key = _ax.get("api_key") or key
        except (TypeError, ValueError):
            pass
        if key:
            req.add_header("Authorization", f"Bearer {key}")
        with urlopen(req, timeout=0.8) as resp:
            data = _json.loads(resp.read().decode() or "{}").get("data") or []
        return (data[0].get("id") or None) if data else None
    except Exception:
        return None


def _reconcile_live(probed: "str | None", registry_ids: set, intent_model: "str | None",
                    models: "list | None" = None) -> "str | None":
    """Pure (unit-tested) reconciliation of the runner probe against our registry.
      probed None            → nothing is loaded → nothing is live (None).
      probed in registry_ids → exact truth (llama.cpp launches with --alias <our id>).
      probed maps to a registry PATH → that model (MLX servers report a path).
      otherwise              → the runner reports something we can't map (MLX's
                               /v1/models enumerates the whole HuggingFace CACHE, so
                               data[0] is often an unrelated repo id) → fall back to
                               the model we intended to launch (harness.yaml
                               runner.model). NEVER trust an unmappable probe."""
    if not probed:
        return None
    if probed in registry_ids:
        return probed
    if models:
        mapped = display_model_id(probed, models)
        if mapped and mapped != probed:
            return mapped
    return intent_model or probed


def _live_model_id(port: int) -> "str | None":
    """Authoritative live id: probe the runner, reconcile against the registry +
    harness.yaml intent. None ⇒ nothing loaded (single source of truth for 'live')."""
    probed = _runner_loaded_id(port)
    if not probed:
        return None
    models = _registry_models()
    ids = {m.get("id") for m in models}
    intent = (cfg().get("runner", {}) or {}).get("model") or None
    return _reconcile_live(probed, ids, intent, models)
