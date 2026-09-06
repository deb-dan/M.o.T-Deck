"""Vision attachments on the direct lane — the pure content builder.

`build_user_content` decides what the runner sees for a user turn that carries an
attached image. It is the ONLY place MOT Deck turns a dataURL into OpenAI image
parts, and the only guard between an attachment and a model that can't see it, so
its decision table is pinned here. Extracted from bridge/app.py by ast so neither
fastapi nor websockets is required.

Run directly: python3 bridge/tests/test_vision_content.py
"""
import ast
import os
import sys
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
APP = ROOT / "bridge" / "appsrc.py"

PASS = 0
fails = []


def check(name, cond):
    global PASS
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        fails.append(name)
        print(f"  FAIL {name}")


def _load():
    tree = ast.parse(_APP_SOURCE)
    want = ("build_user_content",)
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want]
    missing = set(want) - {n.name for n in body}
    assert not missing, f"missing in bridge/app.py: {sorted(missing)}"
    cap = next((n for n in tree.body
                if isinstance(n, ast.Assign)
                and any(getattr(t, "id", "") == "IMAGE_MAX_CHARS" for t in n.targets)), None)
    assert cap is not None, "IMAGE_MAX_CHARS missing in bridge/app.py"
    ns = {}
    exec(compile(ast.Module(body=[cap] + body, type_ignores=[]), "vision", "exec"), ns)
    return ns


NS = _load()
build = NS["build_user_content"]
CAP = NS["IMAGE_MAX_CHARS"]

PNG = "data:image/png;base64,iVBORw0KGgo="
JPG = "data:image/jpeg;base64,/9j/4AAQ"

# ── no image: the legacy shape, untouched ────────────────────────────────────
c, e = build("hello", None, False)
check("no image → plain string content", c == "hello" and e is None)
c, e = build("hello", "", True)
check("empty image string → plain string content", c == "hello" and e is None)
c, e = build("hello", {}, True)
check("empty dict (falsy) is treated as no attachment", c == "hello" and e is None)
c, e = build("", None, True)
check("empty text with no image → empty string, no error", c == "" and e is None)

# ── image + vision model: OpenAI parts, image_url last ───────────────────────
c, e = build("what is this?", PNG, True)
check("vision + image → error is None", e is None)
check("vision + image → list of two parts", isinstance(c, list) and len(c) == 2)
check("part 0 is the text part",
      c[0] == {"type": "text", "text": "what is this?"})
check("part 1 is the image_url part carrying the dataURL verbatim",
      c[1] == {"type": "image_url", "image_url": {"url": PNG}})
c, _ = build("x", JPG, True)
check("jpeg dataURL accepted", isinstance(c, list) and c[1]["image_url"]["url"] == JPG)
c, _ = build("", PNG, True)
check("empty text + image still builds parts (text part present, empty)",
      isinstance(c, list) and c[0]["text"] == "")

# ── non-vision model: refused, never sent ───────────────────────────────────
c, e = build("hi", PNG, False)
check("non-vision + image → no content", c is None)
check("non-vision + image → 'no vision' reason", isinstance(e, str) and "vision" in e)

# ── malformed / oversize: refused with the specific reason, even on vision ──
for bad, label in ((123, "int"), ({"url": PNG}, "dict"), (["x"], "list"),
                   ("http://x/y.png", "plain url"),
                   ("data:text/plain;base64,AAA", "non-image dataURL"),
                   ("iVBORw0KGgo=", "bare base64")):
    c, e = build("hi", bad, True)
    check(f"malformed ({label}) refused with a data-URL reason",
          c is None and isinstance(e, str) and "data URL" in e)

big = "data:image/png;base64," + ("A" * (CAP + 1))
c, e = build("hi", big, True)
check("oversize dataURL refused", c is None and isinstance(e, str) and "too large" in e)
c, e = build("hi", big, False)
check("oversize is reported as oversize even on a non-vision model",
      c is None and "too large" in e)
c, e = build("hi", "data:image/png;base64," + ("A" * 64), True)
check("just-under-cap dataURL accepted", isinstance(c, list) and e is None)

# ── totality: never raises, never returns both ──────────────────────────────
for args in (("t", PNG, True), ("t", PNG, False), ("t", None, True),
             ("t", 5, True), ("t", big, True)):
    c, e = build(*args)
    check(f"exactly one of content/error for {args[1].__class__.__name__}"
          f"/vision={args[2]}", (c is None) != (e is None))

print(f"\n{PASS} checks passed" + (f", {len(fails)} FAILED: {fails}" if fails else ""))
sys.exit(1 if fails else 0)
