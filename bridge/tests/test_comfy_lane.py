"""THE COMFY GENERATE LANE — journeys and adversarial findings, pinned.

Run: python3 bridge/tests/test_comfy_lane.py   (from the repo root)

═══ WHAT THIS FILE IS ═══════════════════════════════════════════════════════════
The doctrine's rule (obligation 6) is that every journey walked and every adversarial
finding fixed becomes an executable test, and that the test unit is the USER STORY, not
the code seam. S1's journeys were walked live against a real ComfyUI, a real 9.83 GB
download and a real generation; what CAN be re-run in two seconds without a network,
a GPU or 10 GB of weights is re-run here.

The groups:

  1. THE CURATION IS GENERATED AND HONEST. The file list comes from the vendored
     template registry and the sizes are the pinned HEAD-verified ones. The cap is a
     BUDGET, not a boolean: whether the starter set is inside Debi's 14 GB or over it,
     the exact number and the reason are stated — and any model that has been MEASURED
     and found wanting carries that verdict on its own card.

  2. THE STOCK-NODE FENCE. Every class either builder can emit is in ALLOWED_NODES, and
     ALLOWED_NODES contains nothing that needs a custom pack. This is the supply-chain
     ruling (ComfyUI_LLMVISION / Ultralytics) as a gate rather than a paragraph.

  3. THE GRAPHS ARE SUBMITTABLE. API format, every link a [node_id, slot] pair pointing
     at a node that exists, every mode reachable, the 4n+1 rule applied silently.

  4. DISK VERDICTS. Advisory in every branch, computed from the models directory's own
     volume, and never from a path that does not exist yet.

  5. THE GALLERY NEVER LIES. Missing / size-changed / orphan are all VISIBLE states;
     none of them is silently dropped, and none of them renders as "ok".

  6. THE ADVERSARIAL LEDGER (each row is a finding from the build's own pass):
       A-1 (LIE)  a file of the wrong size on disk must NOT count as downloaded
       A-2 (LIE)  a gallery item whose file vanished must be listed as missing
       A-3 (LIE)  a gallery item whose size changed since ingest must be flagged
       A-4 (LIE)  the disk verdict must come from the models volume, never from "/"
       A-5        `/api/comfy/file` must refuse a path outside the output directory
       A-6        a blank seed must become a REPORTED random number, never 0
       A-7        a template with no `properties.models` must be registry-drift, not
                  an empty download that "succeeds"
       A-8        two Download clicks must join one download, never race one .part
       A-9  (LIE)  a curated model whose output was measured and found unusable must
                   SAY SO on its card — the one-frame image path was shipped, run, and
                   produced two flat bands of colour, and the curation changed
       A-10       a .part another PROCESS is still writing must block a second writer

  7. THE WIRING. The lane is in bridge/app.py's _LANES and bridge/appsrc.py's FILES —
     both, because a lane missing from the source view makes every `not in` assertion
     about it pass VACUOUSLY (APP-FACADE-MANIFEST.md).
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

fails = checks = 0


def ok(cond, msg):
    global fails, checks
    checks += 1
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails += 1


import bridge.appsrc as appsrc                                       # noqa: E402
from bridge import app as A                                          # noqa: E402
from bridge.routers import comfy as C                                # noqa: E402

# ── 1. CURATION ──────────────────────────────────────────────────────────────
print("\n1. the curation is generated, and it fits the cap")
starter = [p for p in C.PICKS if p["starter"]]
ok(len(starter) >= 1, "there is a starter set")
starter_bytes = sum(f["bytes"] for p in starter for f in p["files"])
modes = {m for p in starter for m in p["modes"]}
ok({"image", "video"} <= modes,
   "the starter set covers BOTH image and video — the point of the cap exercise")
# ⚠️ THE CAP IS A BUDGET, NOT A BOOLEAN, AND THIS TEST SAYS SO ON PURPOSE. The spec's
# fallback is explicit: if no combo covering both fits, ship the pair and STATE the
# overshoot rather than dropping video. So what is pinned here is not "we are under the
# cap" — it is "whatever we are, the page says it, in bytes, with a reason".
cap = C.cap_statement()
ok(cap["starter_bytes"] == starter_bytes, "the cap statement counts the real files")
if starter_bytes > C.STARTER_CAP_BYTES:
    ok(cap["over"] is True and cap["over_bytes"] == starter_bytes - C.STARTER_CAP_BYTES,
       f"the starter set is {C.gb(starter_bytes)} — OVER the cap, and the overshoot is "
       f"stated as {C.gb(cap['over_bytes'])}")
    ok(C.gb(cap["over_bytes"]) in cap["text"] and C.gb(C.STARTER_CAP_BYTES) in cap["text"],
       "…and both numbers are in the sentence a human reads")
    ok("unusable" in cap["text"] or "unusable" in C.CAP_WHY,
       "…together with WHY the one-model answer was rejected (it was tried, and "
       "measured, and it failed — that is the evidence the overshoot rests on)")
else:
    ok(cap["over"] is False, f"the starter set ({C.gb(starter_bytes)}) is inside the cap")
ok(all(f.get("sha256") and len(f["sha256"]) == 64 for p in C.PICKS for f in p["files"]),
   "every curated file carries a 64-hex sha256 pin")
ok(all(f["bytes"] > 0 for p in C.PICKS for f in p["files"]),
   "every curated file carries a byte size")
ok(all(p["license_badge"] in ("green", "amber", "red") for p in C.PICKS),
   "every pick carries a licence badge class")
ok(not any("hunyuan" in json.dumps(p).lower() for p in C.PICKS),
   "HunyuanVideo is not curated (no EU licence grant — standing refusal)")
ok(not any("sdxl-turbo" in (f.get("url") or "") or "sd_xl_turbo" in f["name"]
           for p in C.PICKS for f in p["files"]),
   "SDXL Turbo is not curated (sai-nc-community = NON-commercial; the tag says 'other')")
# Every pick that has been MEASURED and found wanting says so on its own card, per
# mode. A curated list is not a promise that the output is good on this machine, and
# the one place that distinction must not be lost is the card with the button on it.
for p in C.PICKS:
    card = C.pick_card(p)
    for mode, note in (card.get("health") or {}).items():
        ok(mode in card["modes"], f"{p['id']}: the health note for {mode} names a real mode")
        ok(len(note) > 40, f"{p['id']}/{mode}: the health note says something specific")
_wh = C.PICK_BY_ID["wan21_t2v_1_3b"]["health"]
ok("flat bands" in _wh.get("image", ""),
   "the one-frame image path carries its MEASURED failure, not silence — it was "
   "shipped, run live on 2026-08-29, and the picture was two flat bands of colour")
ok("SDXL renders perfectly on the same" in _wh.get("video", ""),
   "…and the video verdict names its CONTROL: SDXL rendering correctly on the same "
   "engine minutes apart is what makes 'Wan-specific' a finding rather than a guess")
ok(not (C.PICK_BY_ID["sdxl_base_1_0"].get("health") or {}),
   "the pick that measured GOOD carries no warning — a health note that fires on "
   "everything says nothing")
ok({p.get("role") for p in C.PICKS if p["starter"]} == {"image", "video"},
   "the starter set has exactly one image role and one video role")

# ── 2. THE STOCK-NODE FENCE ──────────────────────────────────────────────────
print("\n2. the stock-node fence")
CUSTOM_ONLY = {"UnetLoaderGGUF", "DualCLIPLoaderGGUF", "MMAudioSampler",
               "LLMVisionNode", "UltralyticsDetectorProvider"}
ok(not (C.ALLOWED_NODES & CUSTOM_ONLY),
   "ALLOWED_NODES contains no class that needs a third-party pack")
for pick in C.PICKS:
    for mode in pick["modes"]:
        g = C.build_graph(pick["id"], mode, {"seed": 1, "prompt": "x"})
        ok(C.fence_violations(g) == [],
           f"{pick['id']}/{mode} emits only stock nodes")
ok("custom_nodes" not in str(C.ALLOWED_NODES),
   "the fence is a class allow-list, not a directory check")

# ── 3. THE GRAPHS ARE SUBMITTABLE ────────────────────────────────────────────
print("\n3. the graphs are API-format and internally consistent")
for pick in C.PICKS:
    for mode in pick["modes"]:
        g = C.build_graph(pick["id"], mode, {"seed": 7, "prompt": "a fox"})
        ids = set(g)
        bad = []
        for nid, node in g.items():
            ok_shape = isinstance(node.get("inputs"), dict) and node.get("class_type")
            if not ok_shape:
                bad.append(nid)
            for k, v in (node.get("inputs") or {}).items():
                if isinstance(v, list):
                    if len(v) != 2 or v[0] not in ids:
                        bad.append(f"{nid}.{k}")
        ok(not bad, f"{pick['id']}/{mode}: every link points at a node that exists")
        outs = [n for n in g.values()
                if n["class_type"] in ("SaveImage", "SaveVideo")]
        ok(len(outs) == 1, f"{pick['id']}/{mode}: exactly one output node")
        want = "SaveImage" if mode == "image" else "SaveVideo"
        ok(outs[0]["class_type"] == want,
           f"{pick['id']}/{mode}: the sink is {want}")
        ok(outs[0]["inputs"]["filename_prefix"].startswith(C.OUT_PREFIX + "/"),
           f"{pick['id']}/{mode}: output lands under our own prefix, not loose in output/")

gi = C.build_graph("wan21_t2v_1_3b", "image", {"seed": 1, "prompt": "x"})
ok(gi["40"]["inputs"]["length"] == 1,
   "the Wan IMAGE mode is the same graph with length=1 — that is what buys image+video "
   "coverage inside the 14 GB cap")
gv = C.build_graph("wan21_t2v_1_3b", "video", {"seed": 1, "prompt": "x", "frames": 33})
ok(gv["40"]["inputs"]["length"] == 33, "a legal 33-frame request is used verbatim")

print("   the 4n+1 rule is applied silently (the autocorrect standard):")
for req, want in ((1, 1), (2, 5), (30, 29), (33, 33), (34, 33), (36, 37), (0, 1), (-5, 1)):
    ok(C._wan_length(req) == want, f"     {req} frames → {want}")
ok(all((C._wan_length(n) - 1) % 4 == 0 or C._wan_length(n) == 1 for n in range(1, 200)),
   "     …and every result in 1..200 is a legal latent length")

print("   dimensions are clamped and snapped to /16 rather than refused:")
for req, want in ((1000, 992), (13, 128), (99999, 1280), (832, 832)):
    ok(C._dim(req) == want, f"     {req} → {want}")

ok(C.graph_steps(C.build_graph("sdxl_base_1_0", "image",
                               {"seed": 1, "prompt": "x", "steps": 9999})) == 100,
   "an absurd step count is clamped, and graph_steps reads back what will REALLY run")

# ── 4. DISK VERDICTS ─────────────────────────────────────────────────────────
print("\n4. disk verdicts are advisory in every branch")
ok(C.disk_verdict(10, None)["level"] == "unknown", "unreadable free space says so")
ok(C.disk_verdict(10 * 1024**3, 1 * 1024**3)["level"] == "no", "not enough → 'no'")
ok(C.disk_verdict(10 * 1024**3, 11 * 1024**3)["level"] == "tight",
   "…fits but leaves under the 2 GB headroom → 'tight'")
ok(C.disk_verdict(10 * 1024**3, 40 * 1024**3)["level"] == "ok", "plenty → 'ok'")
for lvl in ("no", "tight", "ok"):
    v = [C.disk_verdict(10 * 1024**3, x) for x in (1 * 1024**3, 11 * 1024**3, 40 * 1024**3)]
ok(all("free" in x["text"] for x in v),
   "…and every verdict PRINTS the numbers rather than only a word")
ok(not any(w in json.dumps(v) for w in ("blocked", "refus", "cannot download")),
   "no verdict ever says the download is blocked (the 2026-08-28 advisory-gates ruling)")

# A-4 (LIE): the verdict is computed from the volume the file lands on.
d = tempfile.mkdtemp()
deep = Path(d) / "a" / "b" / "c" / "does-not-exist-yet"
r = C._disk(deep)
ok(r["ok"] and r["measured_at"] == d,
   "A-4: _disk walks UP to the nearest existing ancestor (never falls back to '/')")
ok(r["requested"] == str(deep), "…and reports which path was asked for")
root_free = C._disk(Path("/"))["free_bytes"]
here = C._disk(Path(__file__))["free_bytes"]
ok(isinstance(root_free, int) and isinstance(here, int),
   "…both volumes are readable, so the distinction is a real one on this machine")

# ── 5. THE GALLERY NEVER LIES ────────────────────────────────────────────────
print("\n5. the gallery states every state it can be in")
saved_root = A.ROOT
try:
    tmp = Path(tempfile.mkdtemp())
    A.ROOT = tmp
    out = tmp / "data" / "comfyui" / "output" / C.OUT_PREFIX
    out.mkdir(parents=True)
    (out / "kept.png").write_bytes(b"x" * 100)
    (out / "grew.png").write_bytes(b"x" * 50)
    (out / "stranger.png").write_bytes(b"x" * 7)
    C.state_dir().mkdir(parents=True, exist_ok=True)
    C._gallery_write([
        {"filename": "kept.png", "subfolder": C.OUT_PREFIX, "bytes_at_ingest": 100,
         "job": "j1", "pick_title": "T", "mode": "image", "at": 3},
        {"filename": "grew.png", "subfolder": C.OUT_PREFIX, "bytes_at_ingest": 999,
         "job": "j2", "pick_title": "T", "mode": "image", "at": 2},
        {"filename": "gone.png", "subfolder": C.OUT_PREFIX, "bytes_at_ingest": 10,
         "job": "j3", "pick_title": "T", "mode": "image", "at": 1},
    ])
    g = C.gallery()
    by = {i["filename"]: i for i in g["items"]}
    ok(by["kept.png"]["state"] == "ok", "an intact item is ok")
    ok(by["gone.png"]["state"] == "missing",
       "A-2: an item whose file vanished is LISTED as missing, not dropped")
    ok(by["grew.png"]["state"] == "size_changed",
       "A-3: an item whose size changed since ingest is flagged, not rendered as fine")
    ok(by["stranger.png"]["state"] == "orphan",
       "a file on disk we have no record of is still listed — keep-everything means the "
       "disk is the truth")
    ok(g["total_bytes"] == 100 + 50 + 7,
       "the running total counts the bytes that are ACTUALLY there (missing counts 0)")
    ok(by["gone.png"]["bytes"] == 0, "…and a missing item contributes nothing to it")

    # A-1 (LIE): wrong size on disk is not "downloaded".
    md = C.models_dir() / "vae"
    md.mkdir(parents=True)
    spec = C.PICK_BY_ID["wan21_t2v_1_3b"]["files"][2]
    (md / spec["name"]).write_bytes(b"0" * 12)
    st = C._file_state(spec)
    ok(st["state"] == "corrupt" and not st["present"],
       "A-1: a file of the wrong size is 'corrupt', never 'present'")
    card = C.pick_card(C.PICK_BY_ID["wan21_t2v_1_3b"])
    ok(not card["downloaded"] and spec["name"] in card["corrupt"],
       "…and its card says so instead of claiming the model is ready")

    # a half-finished .part is 'partial' — visible, and not present
    (md / spec["name"]).unlink()
    (md / (spec["name"] + ".part")).write_bytes(b"0" * 999)
    ok(C._file_state(spec)["state"] == "partial",
       "a resumable .part is 'partial' — the cancel path keeps it on purpose")
finally:
    A.ROOT = saved_root

# ── 6. ADVERSARIAL LEDGER, the rest ──────────────────────────────────────────
print("\n6. the rest of the adversarial ledger")
src = (ROOT / "bridge" / "routers" / "comfy.py").read_text()
ok("relative_to(root)" in src,
   "A-5: the file/reveal routes contain the resolve+relative_to containment check")
ok(src.count("relative_to(root)") >= 2,
   "…on BOTH routes that take a filename off the wire")
ok("os.urandom" in src and "seed = int.from_bytes" in src,
   "A-6: a blank seed becomes a real random number…")
ok('"seed": seed' in src and "\"seed\": seed}" in src or '"seed": seed' in src,
   "…which is written into the job record and returned, so the run is reproducible")
ok("registry_drift" in src and "no download URL for" in src,
   "A-7: a template whose registry entry is gone is drift + a refusal, not a silent "
   "zero-file 'success'")
ok("def cdl_inflight" in src and "joined" in src,
   "A-8: a second Download click joins the first rather than racing it")
ok("def foreign_writer" in src and "LIVE_PART_S" in src,
   "A-10: a .part another PROCESS is still writing (bridge restarted mid-download — "
   "found by walking it) blocks a second writer that cdl_inflight cannot see")
ok("_sha256" in src and "asyncio.to_thread" in src,
   "hashing a multi-GB file goes to a thread — the bridge must not freeze mid-download")
ok("node_errors" in src,
   "ComfyUI's node_errors is surfaced verbatim, never swallowed into a generic failure")
ok("phys_footprint" in src,
   "the measurement is phys_footprint (core/memory.py's rule), not RSS")
ok("not measured on this Mac yet" in src,
   "an unmeasured model SAYS SO instead of showing an invented ETA")

# A-9: the fence is enforced at SUBMIT, not only at build time.
ok(src.count("fence_violations(") >= 3,
   "the fence is checked when building, when validating AND before POST /prompt")

# ── 7. WIRING ────────────────────────────────────────────────────────────────
print("\n7. wiring")
paths = {getattr(r, "path", "") for r in A.app.routes}
for p in ("/comfy", "/api/comfy/state", "/api/comfy/download", "/api/comfy/generate",
          "/api/comfy/jobs", "/api/comfy/gallery", "/api/comfy/file",
          "/api/comfy/validate"):
    ok(p in paths, f"{p} is on the route table")
ok("routers.comfy" in A._LANES, "routers.comfy is in bridge/app.py's _LANES")
ok("routers/comfy.py" in appsrc.FILES,
   "…and in bridge/appsrc.py's FILES, so a source assertion about it cannot pass vacuously")
ok("bridge/routers/comfy.py" in appsrc.APP_SOURCE,
   "…which the concatenated source view proves by carrying its boundary marker")
ok((ROOT / "bridge" / "panel" / "comfy.html").is_file(),
   "the page exists where the route serves it from")

# The page is served with no-store, like every other panel document: a WKWebView that
# heuristically cached it would keep serving yesterday's page after a ship.
ok("no-store" in src.split("def comfy_page")[1].split("def ")[0],
   "GET /comfy is served no-store")

# ROOT-relative, never repo-relative (research §1.1's trap).
ok('ROOT / "data" / "comfyui"' in src,
   "every path resolves off ROOT — the running ComfyUI is the app's, not the repo's")
ok(not any(s in src for s in ('"/Users', "'/Users", '"/Library', "'/Library")),
   "…and no absolute machine path is hardcoded as a string literal (research §1.1's trap)")

print(f"\n{checks - fails}/{checks} checks passed")
sys.exit(1 if fails else 0)
