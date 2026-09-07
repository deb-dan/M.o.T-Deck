"""THE HF/VOICE/MUSIC GET LANE'S VERIFY GATE — ledger A10, walked and pinned.

Run: python3 bridge/tests/test_download_verify.py   (from the repo root)

═══ WHAT THIS FILE IS ═══════════════════════════════════════════════════════════
`bridge/routers/downloads.py::_run_download` is the ONE lane behind every Get button
in the app: the Models browser's GGUF Get, the whole-MLX-repo Get, and the Audio
tab's voice/TTS Gets (`voice_format`). Until 2026-08-29 it renamed `.part`→dest
UNCONDITIONALLY and then wrote the model into data/models.json. A stream that ended
early *cleanly* — a CDN truncation, a proxy closing a chunked transfer at 40% —
therefore registered a corrupt model as "complete — in your library". That is the
LIE class, and the comfy downloader had already fixed exactly it ("renamed only
after BOTH the byte count and the sha256 match") without the rule reaching here.

Doctrine 2b says the failure modes are WALKED, not reasoned about, so the three
corruption journeys below run against a REAL local HTTP shim serving REAL bad
bytes over a REAL socket — chunked truncation, byte tampering, and a lying
Content-Length. No network, no HuggingFace, ~1 second.

The groups:

  1. THE TREE'S DIGESTS SURVIVE. `lfs.oid` (sha256) is kept, the top-level `oid`
     (a git blob sha1) is NEVER mistaken for one, and a non-LFS file is honestly
     recorded as having no digest upstream.

  2. THE VERDICT IS PURE AND HONEST. `_verify_verdict` names what mismatched, and
     `verified` never claims a stronger check than the one that ran.

  3. THE JOURNEYS, EXECUTED (a local shim, real sockets):
       J1  happy path        → dest exists, registry entry written, "size+sha256"
       J2  clean truncation  → NO dest, NO registry entry, .part gone, error names
                               the byte gap  (THE ORIGINAL BUG)
       J3  tampered bytes    → right length, wrong sha256 → same refusal
       J4  no digest upstream→ size-only, and the state SAYS only size was checked
       J5  resume (Range)    → the FULL assembled file is verified, not the tail
       J6  poisoned resume   → a .part whose first half is from another revision
                               resumes to the right LENGTH and is still caught
       J7  already on disk   → NOT re-hashed, NOT distrusted (no rescan storm)

  4. THE WIRING. dl_start keeps the oids for both modes; the lane is in the
     appsrc view (a lane missing from it makes every `not in` pass vacuously).
"""
import asyncio
import hashlib
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from bridge.appsrc import APP_SOURCE as _APP_SOURCE       # noqa: E402
from bridge.routers import downloads as D                 # noqa: E402

fails = []


def check(name, ok, detail=""):
    if not ok:
        fails.append(f"{name}{(' — ' + str(detail)) if detail else ''}")


# ══ 1. THE TREE'S DIGESTS SURVIVE ════════════════════════════════════════════
TREE = [
    {"type": "file", "path": ".gitattributes", "oid": "f15b49c2e62c6e52121f7b4", "size": 1562},
    {"type": "file", "path": "config.json", "oid": "cc375d92d7061b465042e9a", "size": 700},
    {"type": "file", "path": "m-Q8_0.gguf", "oid": "819f7b481f6ecdf1d14e989",
     "size": 291543744,
     "lfs": {"oid": "e00cf79514204dfe2f4d6943f277ffea7fd8a4c8e955b4b7a869cfc157694881",
             "size": 291543744, "pointerSize": 134}},
    {"type": "directory", "path": "sub"},
]
oids = D._tree_sha256(TREE)
check("lfs.oid is kept as the file's sha256",
      oids.get("m-Q8_0.gguf")
      == "e00cf79514204dfe2f4d6943f277ffea7fd8a4c8e955b4b7a869cfc157694881")
check("a non-LFS file has NO digest (its top-level oid is a git blob sha1, "
      "not a content hash)", "config.json" not in oids and ".gitattributes" not in oids)
check("the git blob sha1 is never smuggled in as a sha256",
      all(len(v) == 64 for v in oids.values()), oids)
check("garbage tree entries do not raise", D._tree_sha256([None, 3, {"path": ""}]) == {})
check("a missing tree (failed/redirected fetch) is empty, not an exception",
      D._tree_sha256([]) == {} and D._tree_sha256(None) == {})

# ══ 2. THE VERDICT IS PURE AND HONEST ════════════════════════════════════════
SHA = "a" * 64
v = D._verify_verdict("m.gguf", 900, 1000, SHA, SHA)
check("short file is refused even when the digest would match", not v["ok"])
check("the refusal names the byte gap", "100 bytes short" in v["error"], v["error"])
check("the refusal says the partial file is gone", "deleted" in v["error"])
check("the refusal offers a retry", "Get again" in v["error"])

v = D._verify_verdict("m.gguf", 1000, 1000, SHA, "b" * 64)
check("right length + wrong bytes is refused", not v["ok"])
check("the sha refusal names both digests", "aaaaaaaaaaaa" in v["error"]
      and "bbbbbbbbbbbb" in v["error"], v["error"])

v = D._verify_verdict("m.gguf", 1000, 1000, SHA, SHA)
check("both facts matching passes", v["ok"] and v["verified"] == "size+sha256")

v = D._verify_verdict("config.json", 700, 700, None, None)
check("no digest upstream → passes on size, and SAYS size only",
      v["ok"] and v["verified"] == "size")

v = D._verify_verdict("x", 700, None, None, None)
check("nothing knowable → passes but is labelled unverified, never 'size+sha256'",
      v["ok"] and v["verified"] == "unverified")

check("summary is honest when everything was fully verified",
      D._verify_summary([{"name": "a", "verified": "size+sha256"}])
      == "byte count and sha256 both verified against HuggingFace")
s = D._verify_summary([{"name": "a.gguf", "verified": "size+sha256"},
                       {"name": "config.json", "verified": "size"}])
check("summary names the size-only files rather than implying a full check",
      "size-only" in s and "config.json" in s and "sha256" in s, s)
s = D._verify_summary([{"name": "z", "verified": "unverified"}])
check("summary shouts when nothing could be verified", "NOT VERIFIED" in s, s)
s = D._verify_summary([{"name": "old.gguf", "verified": "pre-existing"}])
check("summary says already-on-disk files were not re-checked",
      "not re-checked" in s, s)


# ══ 3. THE JOURNEYS, EXECUTED AGAINST A REAL SOCKET ══════════════════════════
# The shim serves one of four bodies per path, all with Range support, so the
# corruption modes are produced by an actual server rather than by monkeypatching
# our own function's return value.
GOOD = bytes((i * 37 + 11) % 251 for i in range(200_000))
GOOD_SHA = hashlib.sha256(GOOD).hexdigest()
TAMPERED = GOOD[:100_000] + b"\x00" * 8 + GOOD[100_008:]      # same length, wrong bytes
assert len(TAMPERED) == len(GOOD) and TAMPERED != GOOD


class _Shim(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):            # silence
        pass

    def do_GET(self):                     # noqa: N802
        mode = self.path.strip("/").split("/")[0]
        body = TAMPERED if mode == "tampered" else GOOD
        start = 0
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            try:
                start = int(rng.split("=", 1)[1].split("-", 1)[0])
            except ValueError:
                start = 0
        if mode == "cut":
            # ⚠️ THE ORIGINAL BUG'S SHAPE: chunked, so there is no Content-Length
            # to disagree with, and the transfer is CLOSED PROPERLY at 40%. httpx
            # sees a complete, well-formed response; the read loop simply ends.
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            part = body[start:start + 80_000]
            self.wfile.write(b"%X\r\n" % len(part) + part + b"\r\n0\r\n\r\n")
            return
        if mode == "lying":
            # A proxy that declares a size smaller than the real file and delivers
            # exactly that: caught BEFORE a byte is written (the size pin).
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", "80000")
            self.end_headers()
            self.wfile.write(body[:80_000])
            return
        seg = body[start:]
        self.send_response(206 if start else 200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(seg)))
        if start:
            self.send_header("Content-Range",
                             f"bytes {start}-{len(body) - 1}/{len(body)}")
        self.end_headers()
        self.wfile.write(seg)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = _free_port()
srv = ThreadingHTTPServer(("127.0.0.1", PORT), _Shim)
threading.Thread(target=srv.serve_forever, daemon=True).start()

TMP = Path(tempfile.mkdtemp(prefix="dlverify-"))
(TMP / "data").mkdir(parents=True, exist_ok=True)
_real_root, _real_base = D.ROOT, D._DL_BASE
D.ROOT = TMP                                  # _registry_add writes under here
D._DL_BASE = f"http://127.0.0.1:{PORT}"


def _entry(dl_id, mode, name, *, total, sha, prefill=None, dest_prefill=None):
    """Build a DOWNLOADS entry the way _mk_download does, minus the task."""
    ddir = TMP / "data" / "models" / name
    ddir.mkdir(parents=True, exist_ok=True)
    dest = str(ddir / (name + ".gguf"))
    if prefill is not None:
        with open(dest + ".part", "wb") as fh:
            fh.write(prefill)
    if dest_prefill is not None:
        with open(dest, "wb") as fh:
            fh.write(dest_prefill)
    e = {"id": dl_id, "repo": "shim/" + name,
         "files": [{"name": name + ".gguf", "url": f"/{mode}/{name}.gguf",
                    "dest": dest, "total": total, "done": 0,
                    "sha256": sha, "verified": None}],
         "state": "downloading", "error": None, "rate": 0.0, "model_id": name,
         "kind": "gguf", "model_dir": None, "voice_format": None, "task": None,
         "corrupt": False, "phase": None, "verified": None}
    D.DOWNLOADS[dl_id] = e
    return e, dest


def _registry_ids():
    p = TMP / "data" / "models.json"
    if not p.exists():
        return []
    return [m.get("id") for m in json.loads(p.read_text()).get("models", [])]


async def _journeys():
    N = len(GOOD)

    # ── J1 happy path ────────────────────────────────────────────────────────
    e, dest = _entry("j1", "ok", "good", total=N, sha=GOOD_SHA)
    await D._run_download("j1")
    check("J1 happy path: state done", e["state"] == "done", e.get("error"))
    check("J1 the file landed at dest with the right bytes",
          os.path.exists(dest) and open(dest, "rb").read() == GOOD)
    check("J1 no .part is left behind", not os.path.exists(dest + ".part"))
    check("J1 the model is in the registry", "good" in _registry_ids())
    check("J1 the state records BOTH checks",
          e["files"][0]["verified"] == "size+sha256"
          and "sha256" in (e["verified"] or ""), e.get("verified"))
    check("J1 corrupt flag stays false", e["corrupt"] is False)

    # ── J2 clean truncation — THE ORIGINAL BUG ───────────────────────────────
    e, dest = _entry("j2", "cut", "cutshort", total=N, sha=GOOD_SHA)
    await D._run_download("j2")
    check("J2 truncated stream does NOT report done", e["state"] != "done", e["state"])
    check("J2 it is flagged corrupt", e["corrupt"] is True)
    check("J2 NOTHING was renamed onto dest", not os.path.exists(dest))
    check("J2 the .part was removed", not os.path.exists(dest + ".part"))
    check("J2 the model is NOT in the library", "cutshort" not in _registry_ids())
    check("J2 the error names the file, the gap and the retry",
          "cutshort.gguf" in (e["error"] or "") and "bytes short" in (e["error"] or "")
          and "Get again" in (e["error"] or ""), e["error"])
    check("J2 says CORRUPT, not a vague failure",
          (e["error"] or "").startswith("CORRUPT"), e["error"])

    # ── J3 tampered bytes, right length ──────────────────────────────────────
    e, dest = _entry("j3", "tampered", "tampered", total=N, sha=GOOD_SHA)
    await D._run_download("j3")
    check("J3 tampered file does NOT report done", e["state"] != "done")
    check("J3 it is flagged corrupt", e["corrupt"] is True)
    check("J3 nothing at dest", not os.path.exists(dest))
    check("J3 the .part was removed", not os.path.exists(dest + ".part"))
    check("J3 not in the library", "tampered" not in _registry_ids())
    check("J3 the error blames the digest, not the size",
          "sha256" in (e["error"] or "") and "bytes short" not in (e["error"] or ""),
          e["error"])

    # ── J4 upstream publishes no digest (non-LFS) ────────────────────────────
    e, dest = _entry("j4", "ok", "nodigest", total=N, sha=None)
    await D._run_download("j4")
    check("J4 size-only download completes", e["state"] == "done", e.get("error"))
    check("J4 the file landed", os.path.exists(dest))
    check("J4 the state SAYS only size was checked",
          e["files"][0]["verified"] == "size", e["files"][0]["verified"])
    check("J4 the summary does not claim a digest match",
          "sha256" not in (e["verified"] or ""), e["verified"])

    # ── J4b a lying Content-Length is caught before a byte is written ────────
    e, dest = _entry("j4b", "lying", "lying", total=N, sha=GOOD_SHA)
    await D._run_download("j4b")
    check("J4b a short declared length is refused", e["state"] == "error")
    check("J4b nothing at dest", not os.path.exists(dest))
    check("J4b the error names both numbers",
          str(N) in (e["error"] or "") and "80000" in (e["error"] or ""), e["error"])

    # ── J5 resume: the FULL assembled file is verified ───────────────────────
    e, dest = _entry("j5", "ok", "resumed", total=N, sha=GOOD_SHA,
                     prefill=GOOD[:60_000])
    await D._run_download("j5")
    check("J5 a resumed download completes", e["state"] == "done", e.get("error"))
    check("J5 the assembled file is byte-identical to the original",
          open(dest, "rb").read() == GOOD)
    check("J5 the resumed file was fully verified",
          e["files"][0]["verified"] == "size+sha256")

    # ── J6 poisoned resume: right LENGTH, wrong first half ───────────────────
    # The corruption a tail-only check would wave through, and the reason the gate
    # hashes the whole assembled file rather than the newly-arrived bytes.
    e, dest = _entry("j6", "ok", "poisoned", total=N, sha=GOOD_SHA,
                     prefill=b"\x00" * 60_000)
    await D._run_download("j6")
    check("J6 a poisoned prefix is caught", e["state"] == "error" and e["corrupt"])
    check("J6 the length was right, so it is the DIGEST that fired",
          "sha256" in (e["error"] or ""), e.get("error"))
    check("J6 nothing at dest", not os.path.exists(dest))
    check("J6 not in the library", "poisoned" not in _registry_ids())

    # ── J7 already on disk: not re-hashed, not distrusted ────────────────────
    # A model downloaded before this gate existed must not be re-verified into a
    # "corrupt" verdict — the check applies at completion, not retroactively.
    e, dest = _entry("j7", "ok", "existing", total=N, sha="f" * 64,
                     dest_prefill=GOOD)
    await D._run_download("j7")
    check("J7 an already-complete file is accepted without re-hashing",
          e["state"] == "done", e.get("error"))
    check("J7 it is labelled pre-existing rather than verified",
          e["files"][0]["verified"] == "pre-existing")
    check("J7 the summary admits it was not re-checked",
          "not re-checked" in (e["verified"] or ""), e["verified"])
    check("J7 the file was left exactly as it was",
          open(dest, "rb").read() == GOOD)


try:
    asyncio.run(_journeys())
finally:
    srv.shutdown()
    D.ROOT, D._DL_BASE = _real_root, _real_base
    shutil.rmtree(TMP, ignore_errors=True)

# ══ 4. THE WIRING (source-pinned over the whole app layer) ═══════════════════
src = _APP_SOURCE
check("the lane IS in the appsrc view (else every 'not in' below passes vacuously)",
      "_run_download" in src and "_verify_verdict" in src)
check("dl_start keeps the tree's LFS digests", "oids = _tree_sha256(tree)" in src)
check("the MLX repo mode carries a per-file sha256",
      '"sha256": oids.get(relpath)' in src)
check("the GGUF mode carries a per-file sha256",
      '"sha256": sha_by_base.get(base)' in src)
check("the rename is gated: no os.replace before the verdict",
      src.index("v = _verify_verdict(fname") < src.index("_os.replace(part, dest)"))
check("a failed verdict returns instead of renaming",
      'if not v["ok"]:' in src)
check("the pre-write size pin skips content-encoded responses (gzipped config.json "
      "would otherwise fail honestly-downloaded files)",
      'resp.headers.get("content-encoding")' in src)
check("the already-on-disk branch does not hash", '"pre-existing"' in src)

# ══ 5. THE BUG-ECHO FENCE (doctrine 6b) ══════════════════════════════════════
# The class is "a streamed download is renamed onto its destination without both
# facts checked". The sweep of 2026-08-29 found exactly TWO sites in the bridge —
# comfy's `_run_cdl` (fixed v1.5.36) and this lane (fixed here). This check is the
# mechanical version of that verdict: the DAY a third streaming downloader appears,
# this fails and its author has to bring it to the same floor or say why it is out
# of class. Counted over the real files, not over the appsrc view, because a new
# router can be written before it is added to appsrc.FILES.
_sites = []
for _p in sorted((ROOT / "bridge").rglob("*.py")):
    if "__pycache__" in _p.parts or "tests" in _p.parts or "contract_tests" in _p.parts:
        continue
    _t = _p.read_text(errors="replace")
    if "replace(part, dest)" in _t:
        _sites.append(str(_p.relative_to(ROOT)))
check("exactly two streaming download→rename sites exist in the bridge",
      _sites == ["bridge/routers/comfy.py", "bridge/routers/downloads.py"],
      f"found {_sites} — a NEW one must gate size+digest before the rename "
      f"(or be argued out of class) before this test is updated")
_comfy = (ROOT / "bridge" / "routers" / "comfy.py").read_text()
_rename = _comfy.index("os.replace(part, dest)")
check("CONTROL: the comfy sibling still verifies size before its rename",
      _comfy.index("if want and got != want:") < _rename)
# ⚠️ THE SHA GATE IS NOW CONDITIONAL THERE, AND THAT IS THE HONEST SHAPE RATHER THAN A
# WEAKENING (v1.5.49). The comfy lane has two download paths. Curated files always carry
# their pinned sha256. Discovered files ask the source adapter for an authoritative
# digest; Hugging Face LFS can now provide one, while a source with no authoritative
# content digest remains honestly size-only. The gate is therefore conditional on the
# exact file row carrying a digest, never on whether the row happened to be curated.
check("CONTROL: the comfy sibling still verifies sha256 before its rename",
      _comfy.index('if digest != f["sha256"]:') < _rename)
check("CONTROL: …and it skips that check only where no sha256 is pinned at all "
      "or authoritatively discovered, never for a curated pick",
      _comfy.index('if f.get("sha256"):') < _comfy.index('if digest != f["sha256"]:')
      and '"sha256": f["sha256"]' in _comfy
      and '"sha256": digest_known(f["url"])' in _comfy
      and 'else "size declared by server"' in _comfy
      and '"verify": "size + sha256"' in _comfy)

if fails:
    print(f"FAIL ({len(fails)}):")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_download_verify.py: all checks passed")
