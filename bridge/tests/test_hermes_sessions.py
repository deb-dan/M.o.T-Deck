"""Unit tests for the PURE Hermes Phase-3 rail normalizers (bridge/app.py
hermes_sessions_normalize + hermes_messages_to_panel).
Run directly: python3 bridge/tests/test_hermes_sessions.py

Both functions are extracted by source (ast) so the test needs neither fastapi
nor websockets installed — it exercises only the pure logic.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# ⚠️ THE APP LAYER IS NO LONGER ONE FILE (router/core split, 2026-08-28).
# bridge/app.py is a FACADE over bridge/core/*.py + bridge/routers/*.py, so the
# source-text assertions below read bridge/appsrc.py's assembled view of the whole
# app layer instead of one file. Read bridge/appsrc.py's header for why the
# assertions are source-text in the first place and why order is part of it.
import sys as _sys                                          # noqa: E402
_sys.path.insert(0, str(ROOT))                              # noqa: E402
from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402


def _load(name):
    src = _APP_SOURCE
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == name)
    mod = ast.Module(body=[fn], type_ignores=[])
    # The production function now performs A3 attachment projection through a
    # package-relative import.  Source extraction must give Python the same
    # package identity the function has in bridge.routers.hermes; an empty
    # globals mapping makes the import machinery raise before any transcript
    # row is examined and therefore tests the harness, not the product.
    ns: dict = {
        "__name__": "bridge.routers._hermes_sessions_extract",
        "__package__": "bridge.routers",
    }
    exec(compile(mod, name, "exec"), ns)
    return ns[name]


NORM = _load("hermes_sessions_normalize")
MSGS = _load("hermes_messages_to_panel")
PASS = 0


def check(name, cond):
    global PASS
    assert cond, name
    PASS += 1
    print(f"  ok  {name}")


# ── hermes_sessions_normalize ────────────────────────────────────────────────
row = {"id": "abc123", "title": "My chat", "preview": "hello there",
       "started_at": 1753900000, "message_count": 7, "source": "motdeck"}
out = NORM([row])
check("row id kept", out[0]["id"] == "abc123")
check("title wins over preview", out[0]["name"] == "My chat")
check("message_count int", out[0]["message_count"] == 7)
check("source forwarded", out[0]["source"] == "motdeck")
check("epoch seconds → ISO UTC", out[0]["updated_at"].startswith("2025")
      or out[0]["updated_at"].startswith("2026"))
check("ISO carries tz offset", "+00:00" in out[0]["updated_at"])

# untitled falls back to preview, then Untitled
out = NORM([{"id": "x", "title": "", "preview": "first user words"}])
check("untitled → preview", out[0]["name"] == "first user words")
out = NORM([{"id": "x", "title": " ", "preview": ""}])
check("no title/preview → Untitled", out[0]["name"] == "Untitled")

# milliseconds epoch normalized the same as seconds
sec = NORM([{"id": "a", "started_at": 1753900000}])[0]["updated_at"]
ms = NORM([{"id": "a", "started_at": 1753900000000}])[0]["updated_at"]
check("ms epoch == s epoch", sec == ms and sec != "")

# absent/zero/garbage timestamps → empty string, never raise
check("started_at 0 → ''", NORM([{"id": "a"}])[0]["updated_at"] == "")
check("garbage ts → ''", NORM([{"id": "a", "started_at": "nope"}])[0]["updated_at"] == "")

# malformed rows dropped; non-list input → []
out = NORM([{"id": ""}, "junk", None, {"title": "no id"}, {"id": "ok"}])
check("malformed rows dropped", len(out) == 1 and out[0]["id"] == "ok")
check("non-list → []", NORM(None) == [] and NORM("x") == [])

# message_count garbage → 0
check("bad count → 0", NORM([{"id": "a", "message_count": "many"}])[0]["message_count"] == 0)

# ── hermes_messages_to_panel (upstream-aligned: reasoning rehydration) ──────
msgs = [
    {"role": "user", "text": "make a file"},
    {"role": "assistant", "text": "done — created it"},
    {"role": "tool", "name": "shell", "context": "touch x"},        # dropped
    {"role": "assistant", "text": "", "reasoning_content": "hmm"},  # reasoning-only → KEPT (#44022 parity)
    {"role": "system", "text": "scaffolding"},                      # dropped
    {"role": "user", "text": "   "},                                # blank, no reasoning → dropped
    "junk", None,
]
out = MSGS(msgs)
check("visible + reasoning-only kept", len(out) == 3)
check("panel shape role/content",
      out[0] == {"role": "user", "content": "make a file"}
      and out[1] == {"role": "assistant", "content": "done — created it"})
check("reasoning-only turn kept with empty content",
      out[2] == {"role": "assistant", "content": "", "reasoning": "hmm"})
check("non-list → []", MSGS(None) == [] and MSGS({"role": "user"}) == [])
check("non-string text, no reasoning → dropped", MSGS([{"role": "user", "text": 42}]) == [])

# reasoning carried on a normal answering turn
out = MSGS([{"role": "assistant", "text": "answer", "reasoning": "step 1\nstep 2"}])
check("reasoning attached to answer",
      out == [{"role": "assistant", "content": "answer", "reasoning": "step 1\nstep 2"}])

# upstream's STRUCTURED keys flatten defensively (reasoning_details: list of dicts)
out = MSGS([{"role": "assistant", "text": "ok",
             "reasoning_details": [{"type": "x", "text": "part a"}, "part b", {"nope": 1}]}])
check("reasoning_details flattened", out[0].get("reasoning") == "part a\npart b")

# key precedence: first non-empty of upstream's exact key set wins
out = MSGS([{"role": "assistant", "text": "ok",
             "reasoning": "primary", "reasoning_content": "secondary"}])
check("reasoning key precedence", out[0]["reasoning"] == "primary")

# surprise types can never break a transcript
out = MSGS([{"role": "assistant", "text": "ok", "reasoning": {"weird": "dict"}},
            {"role": "assistant", "text": "ok2", "reasoning_details": 42}])
check("surprise reasoning types → plain rows",
      out == [{"role": "assistant", "content": "ok"},
              {"role": "assistant", "content": "ok2"}])

print(f"PASS ({PASS} checks)")
