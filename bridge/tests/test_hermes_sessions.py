"""Unit tests for the PURE Hermes Phase-3 rail normalizers (bridge/app.py
hermes_sessions_normalize + hermes_messages_to_panel).
Run directly: python3 bridge/tests/test_hermes_sessions.py

Both functions are extracted by source (ast) so the test needs neither fastapi
nor websockets installed — it exercises only the pure logic.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    src = (ROOT / "bridge" / "app.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == name)
    mod = ast.Module(body=[fn], type_ignores=[])
    ns: dict = {}
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
       "started_at": 1753900000, "message_count": 7, "source": "harness"}
out = NORM([row])
check("row id kept", out[0]["id"] == "abc123")
check("title wins over preview", out[0]["name"] == "My chat")
check("message_count int", out[0]["message_count"] == 7)
check("source forwarded", out[0]["source"] == "harness")
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

# ── hermes_messages_to_panel ────────────────────────────────────────────────
msgs = [
    {"role": "user", "text": "make a file"},
    {"role": "assistant", "text": "done — created it"},
    {"role": "tool", "name": "shell", "context": "touch x"},        # dropped
    {"role": "assistant", "text": "", "reasoning_content": "hmm"},  # reasoning-only → dropped
    {"role": "system", "text": "scaffolding"},                      # dropped
    {"role": "user", "text": "   "},                                # blank → dropped
    "junk", None,
]
out = MSGS(msgs)
check("only visible user/assistant kept", len(out) == 2)
check("panel shape role/content",
      out[0] == {"role": "user", "content": "make a file"}
      and out[1] == {"role": "assistant", "content": "done — created it"})
check("non-list → []", MSGS(None) == [] and MSGS({"role": "user"}) == [])
check("non-string text dropped", MSGS([{"role": "user", "text": 42}]) == [])

print(f"PASS ({PASS} checks)")
