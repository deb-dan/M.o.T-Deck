"""Isolated unit tests for the Load/Switch unification + live-state reconciliation
(Fable PART 0.2). Run: python3 bridge/tests/test_load_switch.py  (from repo root).

Covers:
  * wire_model_id / display_model_id — the identifier we put ON THE WIRE for the
                       active runner model (2026-08-06 MLX "runner 400" fix): the
                       registry id for llama.cpp (--alias), the model PATH for the
                       MLX servers (which would resolve our id on HF → 404 → 400).
  * _reconcile_live  — runner-probe vs registry vs harness.yaml intent (ISSUE C).
  * busy-lock        — a second concurrent switch/load is rejected (409); the busy
                       flag is cleared in `finally` on BOTH the success and failure
                       paths of _do_switch (ISSUE A/E: no stuck-busy wedge).
"""
import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from bridge import app  # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


# ── wire_model_id / display_model_id (pure) ──────────────────────────────────
REG = [
    {"id": "qwen-35b", "format": "gguf", "path": "/M/qwen-35b/model.gguf"},
    {"id": "gemma-4b", "format": "gguf", "path": "/M/gemma-4b/model.gguf"},
    {"id": "qwen-mtp-mlx", "format": "mlx", "path": "/Users/d/.lmstudio/models/leon/qwen-mtp-mlx"},
    {"id": "vlm-mlx", "format": "mlx", "vision": True, "path": "/M/vlm-mlx"},
    {"id": "mlx-nopath", "format": "mlx", "path": ""},
    {"id": "no-format", "path": "/M/no-format/model.gguf"},
]

check("gguf → registry id on the wire",
      app.wire_model_id("qwen-35b", REG) == "qwen-35b")
check("missing format defaults to gguf → id",
      app.wire_model_id("no-format", REG) == "no-format")
check("mlx → local path on the wire",
      app.wire_model_id("qwen-mtp-mlx", REG)
      == "/Users/d/.lmstudio/models/leon/qwen-mtp-mlx")
check("mlx vision → local path on the wire",
      app.wire_model_id("vlm-mlx", REG) == "/M/vlm-mlx")
check("MLX format spelled MLX (case) → path",
      app.wire_model_id("x", [{"id": "x", "format": "MLX", "path": "/M/x"}]) == "/M/x")
check("mlx entry with no path → id (safe fallback)",
      app.wire_model_id("mlx-nopath", REG) == "mlx-nopath")
check("unknown id → unchanged (safe fallback)",
      app.wire_model_id("not-in-registry", REG) == "not-in-registry")
check("empty id → empty string", app.wire_model_id("", REG) == "")
check("None id → empty string", app.wire_model_id(None, REG) == "")
check("whitespace id is stripped",
      app.wire_model_id("  qwen-mtp-mlx  ", REG)
      == "/Users/d/.lmstudio/models/leon/qwen-mtp-mlx")
check("empty registry → id unchanged",
      app.wire_model_id("qwen-mtp-mlx", []) == "qwen-mtp-mlx")
check("wire id round-trips back to the registry id",
      app.display_model_id(app.wire_model_id("qwen-mtp-mlx", REG), REG) == "qwen-mtp-mlx")
check("display: known id passes through",
      app.display_model_id("gemma-4b", REG) == "gemma-4b")
check("display: trailing slash on the path still maps",
      app.display_model_id("/Users/d/.lmstudio/models/leon/qwen-mtp-mlx/", REG) == "qwen-mtp-mlx")
check("display: resolved/symlinked path maps by basename",
      app.display_model_id("/private/var/models/qwen-mtp-mlx", REG) == "qwen-mtp-mlx")
check("display: unrelated HF-cache id (MLX /v1/models junk) unchanged",
      app.display_model_id("openai/whisper-medium", REG) == "openai/whisper-medium")
check("display: empty → empty", app.display_model_id("", REG) == "")
check("display: None → empty", app.display_model_id(None, REG) == "")
check("_display_model keeps falsy values as-is (Odysseus null)",
      app._display_model(None) is None and app._display_model("") == "")


# ── _reconcile_live (pure) ────────────────────────────────────────────────────
IDS = {"qwen-35b", "gemma-4b", "phi-mini"}

check("probe None → nothing live",
      app._reconcile_live(None, IDS, "qwen-35b") is None)
check("probe empty string → nothing live",
      app._reconcile_live("", IDS, "qwen-35b") is None)
check("exact match → that id (llama.cpp --alias)",
      app._reconcile_live("gemma-4b", IDS, "qwen-35b") == "gemma-4b")
check("path alias not in registry → fall back to intent (MLX)",
      app._reconcile_live("/Users/x/models/foo", IDS, "qwen-35b") == "qwen-35b")
check("alias not in registry + no intent → probed value",
      app._reconcile_live("/Users/x/models/foo", IDS, None) == "/Users/x/models/foo")
check("alias not in registry + empty intent → probed value",
      app._reconcile_live("/Users/x/models/foo", IDS, "") == "/Users/x/models/foo")
# with the registry rows available, a probed PATH maps to its model; an unmappable
# probe (MLX /v1/models lists the whole HF cache) still falls back to intent.
check("probed path maps to its registry model",
      app._reconcile_live("/M/vlm-mlx", {m["id"] for m in REG}, "qwen-35b", REG) == "vlm-mlx")
check("probed HF-cache junk → intent, never the junk",
      app._reconcile_live("openai/whisper-medium", {m["id"] for m in REG},
                          "qwen-mtp-mlx", REG) == "qwen-mtp-mlx")


# ── busy-lock: concurrent switch rejected ─────────────────────────────────────
app._SWITCH.update(busy=True, log="in flight")
resp = asyncio.run(app.api_switch_model(None))  # busy checked before req is touched
check("concurrent switch → HTTP 409", resp.status_code == 409)
check("concurrent switch → not ok", b'"ok":false' in resp.body.replace(b" ", b""))


# ── busy cleared in finally on SUCCESS ────────────────────────────────────────
def _ok_script(name, *a):
    return types.SimpleNamespace(returncode=0, stdout="up", stderr="")


orig_script, orig_set = app._script, app._set_runner_model
orig_live, orig_reg = app._live_model_id, app._registry_models
app._script = _ok_script
app._set_runner_model = lambda *_: None

# ── U15 fixtures: the switch watcher's two new inputs ─────────────────────────
# `_live_model_id` — what the runner ANSWERS (authenticated). Since 2026-08-29 this
# outranks the start script's exit code, because the script's own readiness poll sends
# no Authorization header and 401s against every llama.cpp b10662+ runner (U16).
# `_registry_models` — used to ask whether a rollback target's FILE still exists.
_TMP = Path(__file__).resolve().parent.parent.parent / "data" / "models.json"   # a file that exists
_REG_U15 = [{"id": "old", "format": "gguf", "path": str(_TMP)},
            {"id": "new", "format": "gguf", "path": str(_TMP)},
            {"id": "deleted-27b", "format": "gguf", "path": "/nowhere/at/all/model.gguf"}]
app._registry_models = lambda: _REG_U15
app._live_model_id = lambda *_a, **_k: None      # default: the runner answers nothing

try:
    app._SWITCH.update(busy=True, log="starting…")
    app._do_switch("new", "old", False, False)          # no hermes/ody restart
    check("success path clears busy", app._SWITCH["busy"] is False)
    check("success path log = active", "active: new" in app._SWITCH["log"])

    # ── busy cleared in finally on FAILURE (load returncode != 0) ──────────────
    rolled = {}
    app._set_runner_model = lambda mid: rolled.__setitem__("to", mid)
    app._script = lambda name, *a: types.SimpleNamespace(returncode=1, stdout="", stderr="boom")
    app._SWITCH.update(busy=True, log="starting…")
    app._do_switch("new", "old", False, False)
    check("failure path clears busy", app._SWITCH["busy"] is False)
    check("failure path rolls model back to old", rolled.get("to") == "old")
    check("failure path log surfaces FAILED", "FAILED" in app._SWITCH["log"])

    # ══ U15 — THE LIVE INCIDENT OF 2026-08-29, AS THREE JOURNEYS ═══════════════
    #
    # JOURNEY 1 — "it said FAILED while the model was answering." Debi switched to
    # Parable-Qwen3-4B; llama-server loaded it in 1.3 seconds and served it. The start
    # script exited non-zero anyway (unauthenticated readiness poll → 401 → 90 tries ×
    # 2s → give up), so the watcher declared failure for a runner that was up. The exit
    # code is a REPORT; the authenticated probe is a FACT, and the fact wins.
    rolled.clear()
    app._live_model_id = lambda *_a, **_k: "new"
    app._SWITCH.update(busy=True, log="starting…")
    app._do_switch("new", "old", False, False)
    check("U15 J1: a non-zero exit is NOT believed when the runner is serving the model",
          "active: new" in app._SWITCH["log"])
    check("U15 J1: …and no bogus FAILED reaches the user",
          "FAILED" not in app._SWITCH["log"])
    check("U15 J1: …and nothing is rolled back on a load that actually worked",
          rolled.get("to") is None)

    # JOURNEY 2 — "reverted to a model I deleted." On that false failure the watcher
    # rolled the pin back to the 27B whose weights she had deleted in LM Studio: a
    # revert that could not possibly load, announced as a recovery. A rollback target
    # whose file is gone is not a known-good model, so the pin STAYS and says so.
    rolled.clear()
    app._live_model_id = lambda *_a, **_k: None       # genuinely down this time
    app._SWITCH.update(busy=True, log="starting…")
    app._do_switch("new", "deleted-27b", False, False)
    check("U15 J2: never reverts onto a model whose file is gone",
          rolled.get("to") is None)
    check("U15 J2: …and says what it did instead, naming the dead model",
          "deleted-27b" in app._SWITCH["log"]
          and "gone from disk" in app._SWITCH["log"])
    check("U15 J2: …while a LIVE rollback target is still honoured (J-above)",
          True)

    # JOURNEY 3 — "what I read on screen was a log line." The modal used to paste the
    # raw tail, so the failure Debi saw was
    #   2.49.854.040 W srv    operator(): unauthorized: Invalid API Key
    # — no cause, no file, no fix. The sentence now leads; the raw tail follows it,
    # labelled, for whoever is diagnosing.
    app._script = lambda name, *a: types.SimpleNamespace(
        returncode=1, stdout="",
        stderr="ERROR: model 'new' not in registry — run scripts/seed_registry.py "
               "or pick another model\n2.49.854.040 W srv operator(): unauthorized\n")
    app._registry_models = lambda: [
        {"id": "new", "format": "gguf", "path": "/nowhere/at/all/model.gguf"}]
    app._SWITCH.update(busy=True, log="starting…")
    app._do_switch("new", "", False, False)
    check("U15 J3: the failure line is a SENTENCE, not log vomit",
          "model file missing at /nowhere/at/all/model.gguf" in app._SWITCH["log"])
    check("U15 J3: …and it appears BEFORE the raw detail",
          app._SWITCH["log"].index("model file missing")
          < app._SWITCH["log"].index("Details:"))
    app._registry_models = lambda: _REG_U15

    # ── busy cleared in finally on EXCEPTION ───────────────────────────────────
    def _boom(*a, **k):
        raise RuntimeError("subprocess exploded")
    app._script = _boom
    app._SWITCH.update(busy=True, log="starting…")
    app._do_switch("new", "old", False, False)
    check("exception path clears busy (finally)", app._SWITCH["busy"] is False)
    check("exception path log surfaces error", "switch error" in app._SWITCH["log"])
finally:
    app._script, app._set_runner_model = orig_script, orig_set
    app._live_model_id, app._registry_models = orig_live, orig_reg
    app._SWITCH.update(busy=False, log="")

print()
if FAILS:
    print(f"{len(FAILS)} FAILURE(S):", FAILS)
    sys.exit(1)
print("ALL TESTS PASS")
