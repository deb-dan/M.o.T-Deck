"""Unit tests for the direct-lane IMAGE sidecar (bridge/app.py).

The direct lane persists {role, content} strings to Odysseus, so an attached
image survives a reopen only as the "[image attached]" marker. The bytes are
kept locally in data/attachments.db keyed by (session id, user-text hash) and
re-attached as an {id, name} handle when the panel reopens the session.

Same test shape as test_thinking_sidecar.py: the helpers are ast-extracted from
bridge/app.py so neither fastapi nor websockets is required.

Run directly: python3 bridge/tests/test_image_sidecar.py
"""
import ast
import base64
import tempfile
import threading
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


def check(name, cond):
    global PASS
    assert cond, name
    PASS += 1
    print(f"  ok  {name}")


def _load(tmp_root):
    """Extract the sidecar functions and bind them to a throwaway data root."""
    tree = ast.parse(_APP_SOURCE)
    want = ("user_key", "parse_data_url", "_attach_conn", "log_attachment",
            "_attachment_rows", "_attachment_get", "_attachment_delete",
            "_attachment_forget", "attach_images")
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want]
    missing = set(want) - {n.name for n in body}
    assert not missing, f"missing in bridge/app.py: {sorted(missing)}"
    # The module constants the helpers close over, read from the real source so a
    # future retune of either value is picked up here rather than drifting.
    consts = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) \
                and n.targets[0].id in ("ATTACH_MAX_ROWS", "ATTACH_MARKER"):
            consts[n.targets[0].id] = ast.literal_eval(n.value)
    assert set(consts) == {"ATTACH_MAX_ROWS", "ATTACH_MARKER"}, consts
    ns = {"ROOT": Path(tmp_root), "threading": threading,
          "_attach_lock": threading.Lock(), **consts}
    exec(compile(ast.Module(body=body, type_ignores=[]), "sidecar", "exec"), ns)
    return ns


NS = _load(tempfile.mkdtemp())
user_key = NS["user_key"]
parse_data_url = NS["parse_data_url"]
log_attachment = NS["log_attachment"]
rows_for = NS["_attachment_rows"]
get_att = NS["_attachment_get"]
del_att = NS["_attachment_delete"]
forget = NS["_attachment_forget"]
attach = NS["attach_images"]
MARKER = NS["ATTACH_MARKER"]
CAP = NS["ATTACH_MAX_ROWS"]

PNG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + b"tiny-fake-png"


def durl(raw=PNG, mime="image/png"):
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


# ── user_key: stable, truncating, marker-normalizing, total ──────────────────
check("key is stable", user_key("hello") == user_key("hello"))
check("key differs for different text", user_key("a") != user_key("b"))
check("key is a sha1 hexdigest", len(user_key("x")) == 40)
check("key truncates at 2048 chars", user_key("z" * 2048) == user_key("z" * 2048 + "T"))
check("key below the cap still discriminates",
      user_key("z" * 2047) != user_key("z" * 2048))
check("the persisted [image attached] marker is normalized away",
      user_key("look at this") == user_key("look at this" + MARKER))
check("only a TRAILING marker is stripped",
      user_key("a" + MARKER + "b") != user_key("ab"))
check("empty text keys without raising", isinstance(user_key(""), str))
check("None keys without raising", isinstance(user_key(None), str))
check("non-ascii keys without raising", isinstance(user_key("café ✳ 日本"), str))
check("lone surrogate never raises (replace)",
      isinstance(user_key("bad \ud800 char"), str))

# ── parse_data_url: total, mime+bytes out, garbage in → (None, None) ─────────
mime, raw = parse_data_url(durl(), 10_000_000)
check("good dataURL → mime", mime == "image/png")
check("good dataURL → exact bytes round-trip", raw == PNG)
check("jpeg mime preserved", parse_data_url(durl(PNG, "image/jpeg"), 10**7)[0] == "image/jpeg")
check("mime is lowercased", parse_data_url(durl(PNG, "IMAGE/WEBP"), 10**7)[0] == "image/webp")
check("oversize → (None, None)", parse_data_url(durl(), 10) == (None, None))
check("cap of 0/None disables the length check", parse_data_url(durl(), 0)[1] == PNG)
check("garbage string → (None, None)", parse_data_url("not a url", 10**7) == (None, None))
check("empty string → (None, None)", parse_data_url("", 10**7) == (None, None))
check("None → (None, None)", parse_data_url(None, 10**7) == (None, None))
check("bytes input → (None, None)", parse_data_url(b"data:image/png;base64,AA", 10**7)
      == (None, None))
check("non-image mime rejected",
      parse_data_url("data:text/html;base64," + base64.b64encode(b"<b>").decode(), 10**7)
      == (None, None))
check("non-base64 dataURL rejected",
      parse_data_url("data:image/png,rawtext", 10**7) == (None, None))
check("truncated (no comma) rejected",
      parse_data_url("data:image/png;base64", 10**7) == (None, None))
check("empty payload rejected", parse_data_url("data:image/png;base64,", 10**7)
      == (None, None))
check("invalid base64 payload rejected",
      parse_data_url("data:image/png;base64,!!!not-b64!!!", 10**7) == (None, None))
check("payload decoding to empty rejected",
      parse_data_url("data:image/png;base64,", 10**7) == (None, None))

# ── store: insert, read back, serve, per-session isolation ───────────────────
log_attachment("s1", user_key("first"), "cat.png", "image/png", PNG)
r = rows_for("s1")
check("stored row reads back", len(r) == 1 and r[0][0] == user_key("first"))
check("stored row carries the name", r[0][2] == "cat.png")
check("row id is an int", isinstance(r[0][1], int))
check("other sessions see nothing", rows_for("s2") == [])
check("empty sid → empty list", rows_for("") == [])

got = get_att(r[0][1])
check("blob round-trips byte-identical", got and got[2] == PNG)
check("mime round-trips", got[1] == "image/png")
check("name round-trips", got[0] == "cat.png")
check("unknown id → None", get_att(999999) is None)
check("garbage id → None (never raises)", get_att("nope") is None)

log_attachment("s1", user_key("x"), "", "image/png", PNG)
check("blank name falls back to 'image'", rows_for("s1")[-1][2] == "image")
log_attachment("", user_key("x"), "n", "image/png", PNG)
log_attachment("s1", "", "n", "image/png", PNG)
log_attachment("s1", user_key("x"), "n", "", PNG)
log_attachment("s1", user_key("x"), "n", "image/png", b"")
check("blank sid/key/mime/bytes are not stored", len(rows_for("s1")) == 2)

# ── attach_images: order-consuming join on USER messages ─────────────────────
hist = [{"role": "user", "content": "first" + MARKER},
        {"role": "assistant", "content": "ok"}]
attach(hist, rows_for("s1"))
check("match attaches an {id,name} handle",
      hist[0].get("attachment", {}).get("name") == "cat.png")
check("assistant messages are never touched", "attachment" not in hist[1])

forget("s1")
check("forget removes that session's rows", rows_for("s1") == [])

log_attachment("dup", user_key("test"), "one.png", "image/png", b"A")
log_attachment("dup", user_key("test"), "two.png", "image/png", b"B")
hist = [{"role": "user", "content": "test"}, {"role": "user", "content": "test" + MARKER}]
attach(hist, rows_for("dup"))
check("duplicate user texts consume rows IN ORDER",
      hist[0]["attachment"]["name"] == "one.png"
      and hist[1]["attachment"]["name"] == "two.png")

hist = [{"role": "user", "content": "test"}, {"role": "user", "content": "test"}]
attach(hist, [rows_for("dup")[0]])
check("a single row is used at most once",
      hist[0].get("attachment") and "attachment" not in hist[1])

hist = [{"role": "user", "content": "unrelated"}]
attach(hist, rows_for("dup"))
check("no match → passthrough, no attachment key", "attachment" not in hist[0])

hist = [{"role": "user", "content": "test", "attachment": {"id": 1, "name": "keep"}}]
attach(hist, rows_for("dup"))
check("an existing .attachment is never overwritten",
      hist[0]["attachment"]["name"] == "keep")

check("no rows → history returned unchanged",
      attach([{"role": "user", "content": "test"}], []) == [
          {"role": "user", "content": "test"}])
check("None history never raises", attach(None, rows_for("dup")) is None)
check("None rows never raises", attach([], None) == [])

hist = [None, "nonsense", 42, {"role": "user"}, {"role": "user", "content": None},
        {"role": "user", "content": ""}, {"role": "user", "content": "test"}]
attach(hist, [None, (), ("onlykey",), (None, 1, "n"), ("", 2, "n"),
              rows_for("dup")[0]])
check("malformed rows/messages skipped, real match still lands",
      hist[-1].get("attachment", {}).get("name") == "one.png")

# ── delete: 'remove from the app', row-only ──────────────────────────────────
aid = rows_for("dup")[0][1]
check("delete reports success", del_att(aid) is True)
check("deleted row is gone", get_att(aid) is None)
check("delete left the sibling alone", len(rows_for("dup")) == 1)
check("deleting a missing id → False", del_att(aid) is False)
check("garbage id → False (never raises)", del_att("nope") is False)

# ── prune: global cap on the newest ATTACH_MAX_ROWS ──────────────────────────
forget("dup")
for i in range(CAP + 20):
    log_attachment("big", user_key(f"m{i}"), f"{i}.png", "image/png",
                   str(i).encode())
rows = rows_for("big")
check(f"global prune caps at {CAP} rows", len(rows) == CAP)
check("prune drops the OLDEST rows", rows[-1][2] == f"{CAP + 19}.png")
check("prune kept the newest contiguous window", rows[0][2] == "20.png")
log_attachment("other", user_key("q"), "q.png", "image/png", b"Q")
check("a later write prunes across sessions (global cap holds)",
      len(rows_for("big")) + len(rows_for("other")) == CAP)

# ── unwritable data root must degrade silently, never raise ──────────────────
BAD = _load("/proc/nonexistent-harness-root")
BAD["log_attachment"]("s", "k", "n", "image/png", PNG)
check("unwritable store: log_attachment never raises", True)
check("unwritable store: rows → []", BAD["_attachment_rows"]("s") == [])
check("unwritable store: get → None", BAD["_attachment_get"](1) is None)
check("unwritable store: delete → False", BAD["_attachment_delete"](1) is False)
BAD["_attachment_forget"]("s")
check("unwritable store: forget never raises", True)

print(f"\n{PASS}/{PASS} image-sidecar checks passed")
