"""Isolated unit tests for the Load/Switch unification + live-state reconciliation
(Fable PART 0.2). Run: python3 bridge/tests/test_load_switch.py  (from repo root).

Covers:
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


# ── busy-lock: concurrent switch rejected ─────────────────────────────────────
app._SWITCH.update(busy=True, log="in flight")
resp = asyncio.run(app.api_switch_model(None))  # busy checked before req is touched
check("concurrent switch → HTTP 409", resp.status_code == 409)
check("concurrent switch → not ok", b'"ok":false' in resp.body.replace(b" ", b""))


# ── busy cleared in finally on SUCCESS ────────────────────────────────────────
def _ok_script(name, *a):
    return types.SimpleNamespace(returncode=0, stdout="up", stderr="")


orig_script, orig_set = app._script, app._set_runner_model
app._script = _ok_script
app._set_runner_model = lambda *_: None
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
    app._SWITCH.update(busy=False, log="")

print()
if FAILS:
    print(f"{len(FAILS)} FAILURE(S):", FAILS)
    sys.exit(1)
print("ALL TESTS PASS")
