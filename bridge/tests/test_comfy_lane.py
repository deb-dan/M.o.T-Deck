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
     BUDGET, not a boolean: whether the starter set is inside sample's 14 GB or over it,
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
import asyncio
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
         "job": "j1", "pick_title": "T", "mode": "image", "at": 3,
         "graph": {"1": {"class_type": "CheckpointLoaderSimple"}}},
        {"filename": "grew.png", "subfolder": C.OUT_PREFIX, "bytes_at_ingest": 999,
         "job": "j2", "pick_title": "T", "mode": "image", "at": 2},
        {"filename": "gone.png", "subfolder": C.OUT_PREFIX, "bytes_at_ingest": 10,
         "job": "j3", "pick_title": "T", "mode": "image", "at": 1},
    ])
    g = C.gallery()
    by = {i["filename"]: i for i in g["items"]}
    ok(by["kept.png"]["state"] == "ok", "an intact item is ok")
    ok(by["kept.png"]["graph_available"] is True and "graph" not in by["kept.png"],
       "a persisted graph is advertised without bloating the gallery payload")
    ok(by["gone.png"]["graph_available"] is False,
       "a legacy row without a graph does not advertise a dead Graph action")
    C.JOBS.pop("j1", None)
    graph_response = asyncio.run(C.api_comfy_graph("j1"))
    graph_body = json.loads(graph_response.body)
    ok(graph_response.status_code == 200 and graph_body["graph"]["1"]["class_type"]
       == "CheckpointLoaderSimple",
       "a persisted exact graph remains retrievable after its in-memory job is gone")
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
# ⚠️ THE LANE IS TWO FILES SINCE THE S8 EXTRACTION (v1.5.49), AND EACH SOURCE ASSERTION
# NAMES THE ONE IT MEANS. Concatenating them and asserting against the blob would have
# been one line shorter and would have made every check below unable to notice a symbol
# moving to the wrong side of the seam — the same vacuity the appsrc view exists to
# prevent, one scale down. `router` is the routes/client/downloads/jobs/gallery half;
# `core` is curation/catalog/graphs. `src` stays the whole lane for the checks that are
# genuinely about the lane rather than about a file.
router = (ROOT / "bridge" / "routers" / "comfy.py").read_text()
core = (ROOT / "bridge" / "core" / "comfycur.py").read_text()
src = router + "\n" + core
ok("relative_to(root)" in router,
   "A-5: the file/reveal routes contain the resolve+relative_to containment check")
ok(router.count("relative_to(root)") >= 2,
   "…on BOTH routes that take a filename off the wire")
ok("os.urandom" in router and "seed = int.from_bytes" in router,
   "A-6: a blank seed becomes a real random number…")
ok(router.count("int.from_bytes(os.urandom(6)") >= 2,
   "…on the curated path AND on the discovered-workflow path, so neither can ship the "
   "silent-zero seed the other was fixed for")
ok('"seed": seed' in router or '"seed": used.get("seed", seed)' in router,
   "…which is written into the job record and returned, so the run is reproducible")
ok("registry_drift" in core and "no download URL for" in router,
   "A-7: a template whose registry entry is gone is drift + a refusal, not a silent "
   "zero-file 'success'")
ok("def cdl_inflight" in router and "joined" in router,
   "A-8: a second Download click joins the first rather than racing it")
ok("def foreign_writer" in router and "LIVE_PART_S" in router,
   "A-10: a .part another PROCESS is still writing (bridge restarted mid-download — "
   "found by walking it) blocks a second writer that cdl_inflight cannot see")
ok("_sha256" in router and "asyncio.to_thread" in router,
   "hashing a multi-GB file goes to a thread — the bridge must not freeze mid-download")
ok("node_errors" in router,
   "ComfyUI's node_errors is surfaced verbatim, never swallowed into a generic failure")
ok("phys_footprint" in src,
   "the measurement is phys_footprint (core/memory.py's rule), not RSS")
ok("not measured on this Mac yet" in core,
   "an unmeasured model SAYS SO instead of showing an invented ETA")

# A-9: the fence is enforced at SUBMIT, not only at build time.
ok(src.count("fence_violations(") >= 5,
   "the fence is checked when building, when validating and before POST /prompt — on "
   "the curated path AND on the discovered one")

# ── 7. WIRING ────────────────────────────────────────────────────────────────
print("\n7. wiring")
paths = {getattr(r, "path", "") for r in A.app.routes}
for p in ("/comfy", "/api/comfy/state", "/api/comfy/download", "/api/comfy/generate",
          "/api/comfy/jobs", "/api/comfy/gallery", "/api/comfy/file",
          "/api/comfy/validate"):
    ok(p in paths, f"{p} is on the route table")
for p in ("/api/comfy/catalog", "/api/comfy/sources"):
    ok(p in paths, f"{p} is on the route table (the dynamic catalogue, v1.5.49)")
ok("routers.comfy" in A._LANES, "routers.comfy is in bridge/app.py's _LANES")
ok("routers/comfy.py" in appsrc.FILES,
   "…and in bridge/appsrc.py's FILES, so a source assertion about it cannot pass vacuously")
ok("bridge/routers/comfy.py" in appsrc.APP_SOURCE,
   "…which the concatenated source view proves by carrying its boundary marker")
# THE S8 EXTRACTION'S OWN WIRING. core/comfycur.py owns no route, and both lists still
# need it: FILES because the contract seam test compares the view against the directory
# both ways, and _LANES because `A.ROOT = tmp` only reaches modules the facade knows —
# without it the gallery group above would measure the REAL app tree and pass anyway.
ok("core.comfycur" in A._LANES,
   "core.comfycur is in _LANES, so A.ROOT = tmp reaches the module that resolves paths")
ok("core/comfycur.py" in appsrc.FILES, "…and in bridge/appsrc.py's FILES")
ok("bridge/core/comfycur.py" in appsrc.APP_SOURCE,
   "…which the source view proves by carrying its boundary marker")
ok(len(router.splitlines()) < 1500 and len(core.splitlines()) < 1500,
   f"both halves are under the 1,500-line ceiling (router {len(router.splitlines())}, "
   f"core {len(core.splitlines())}) — the S8 extraction is why router growth was legal")
ok("from ..core.comfycur import" in router and "PICK_BY_ID" in router.split(
       "from ..core.comfycur import")[1].split(")")[0],
   "…and the router RE-EXPORTS the moved surface, so `bridge.routers.comfy.PICKS` and "
   "every symbol the suite names through the facade still resolves at its old address")
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


# ── 8. THE DYNAMIC CATALOGUE (sample, 2026-08-29) ──────────────────────────────
# "if one deletes models, it should be dynamic. if one downloads other models, it
# should be dynamic and cater to them, e.g. minimax h3, the wan models, ltx and the
# distilled." Everything below runs against a SYNTHETIC template registry in a temp
# ROOT, because the repo has no ComfyUI install and a test that only passes on the one
# Mac with the weights on it is not a gate. The live catalogue was walked separately
# (26 models / 78 workflows / 71 converting) and the numbers are in the report.
print("\n8. the catalogue is discovered from disk, not typed into this repo")
from bridge.core import comfycur as CUR                              # noqa: E402

_UI = {
    "nodes": [
        {"id": 1, "type": "UNETLoader", "mode": 0,
         "widgets_values": ["famous_5B.safetensors", "default"],
         "properties": {"models": [
             {"name": "famous_5B.safetensors", "directory": "diffusion_models",
              "url": "https://example.invalid/famous_5B.safetensors"},
             # ⚠️ THE ALTERNATIVE. `properties.models` is a DOWNLOAD MENU: this 14B is
             # offered by the same template and loaded by nothing. A catalogue that
             # read the registry as the requirement would tell the user they are
             # missing it.
             {"name": "famous_14B.safetensors", "directory": "diffusion_models",
              "url": "https://example.invalid/famous_14B.safetensors"}]},
         "outputs": [{"name": "MODEL", "type": "MODEL", "links": [10]}], "inputs": []},
        {"id": 2, "type": "CLIPLoader", "mode": 0,
         "widgets_values": ["enc.safetensors", "wan", "default"],
         "properties": {"models": [
             {"name": "enc.safetensors", "directory": "text_encoders",
              "url": "https://example.invalid/enc.safetensors"}]},
         "outputs": [{"name": "CLIP", "type": "CLIP", "links": [11, 12]}], "inputs": []},
        {"id": 3, "type": "CLIPTextEncode", "mode": 0, "widgets_values": ["a fox"],
         "inputs": [{"name": "clip", "type": "CLIP", "link": 11}],
         "outputs": [{"name": "CONDITIONING", "type": "CONDITIONING", "links": [13]}]},
        {"id": 4, "type": "CLIPTextEncode", "mode": 0, "widgets_values": ["ugly"],
         "inputs": [{"name": "clip", "type": "CLIP", "link": 12}],
         "outputs": [{"name": "CONDITIONING", "type": "CONDITIONING", "links": [14]}]},
        # BYPASSED (mode 4): ComfyUI routes MODEL straight through it.
        {"id": 5, "type": "LoraLoaderModelOnly", "mode": 4,
         "widgets_values": ["speedup.safetensors", 1.0],
         "properties": {"models": [
             {"name": "speedup.safetensors", "directory": "loras",
              "url": "https://example.invalid/speedup.safetensors"}]},
         "inputs": [{"name": "model", "type": "MODEL", "link": 10}],
         "outputs": [{"name": "MODEL", "type": "MODEL", "links": [15]}]},
        # A PrimitiveNode supplying a widget value from outside the node.
        {"id": 6, "type": "PrimitiveNode", "mode": 0, "widgets_values": [12, "fixed"],
         "outputs": [{"name": "INT", "type": "INT", "links": [16]}], "inputs": []},
        {"id": 7, "type": "KSampler", "mode": 0,
         "widgets_values": [999, "randomize", 20, 6.0, "uni_pc", "simple", 1.0],
         "inputs": [{"name": "model", "type": "MODEL", "link": 15},
                    {"name": "positive", "type": "CONDITIONING", "link": 13},
                    {"name": "negative", "type": "CONDITIONING", "link": 14},
                    {"name": "steps", "type": "INT", "link": 16}],
         "outputs": [{"name": "LATENT", "type": "LATENT", "links": []}]},
        {"id": 8, "type": "SaveImage", "mode": 0, "widgets_values": ["ComfyUI"],
         "inputs": [], "outputs": []},
        {"id": 9, "type": "MarkdownNote", "mode": 0, "widgets_values": ["read me"],
         "inputs": [], "outputs": []},
    ],
    "links": [[10, 1, 0, 5, 0, "MODEL"], [11, 2, 0, 3, 0, "CLIP"],
              [12, 2, 0, 4, 0, "CLIP"], [13, 3, 0, 7, 1, "CONDITIONING"],
              [14, 4, 0, 7, 2, "CONDITIONING"], [15, 5, 0, 7, 0, "MODEL"],
              [16, 6, 0, 7, 3, "INT"]],
}
_INFO = {
    "UNETLoader": {"input": {"required": {"unet_name": [["famous_5B.safetensors"], {}],
                                          "weight_dtype": [["default"], {}]}},
                   "python_module": "nodes"},
    "CLIPLoader": {"input": {"required": {"clip_name": [["enc.safetensors"], {}],
                                          "type": [["wan"], {}],
                                          "device": [["default"], {}]}},
                   "python_module": "nodes"},
    "CLIPTextEncode": {"input": {"required": {"text": ["STRING", {}],
                                              "clip": ["CLIP", {}]}},
                       "python_module": "nodes"},
    "LoraLoaderModelOnly": {"input": {"required": {
        "model": ["MODEL", {}], "lora_name": [["speedup.safetensors"], {}],
        "strength_model": ["FLOAT", {}]}}, "python_module": "nodes"},
    "KSampler": {"input": {"required": {
        "model": ["MODEL", {}], "seed": ["INT", {"control_after_generate": True}],
        "steps": ["INT", {}], "cfg": ["FLOAT", {}], "sampler_name": [["uni_pc"], {}],
        "scheduler": [["simple"], {}], "denoise": ["FLOAT", {}],
        "positive": ["CONDITIONING", {}], "negative": ["CONDITIONING", {}]}},
        "python_module": "nodes"},
    "SaveImage": {"input": {"required": {"images": ["IMAGE", {}],
                                         "filename_prefix": ["STRING", {}]}},
                  "python_module": "nodes"},
    "EvilNode": {"input": {"required": {}}, "python_module": "custom_nodes.evil_pack"},
    "HostedByFlag": {"input": {"required": {}}, "python_module": "nodes",
                     "api_node": True},
    "HostedByModule": {"input": {"required": {}},
                       "python_module": "comfy_api_nodes.nodes_example",
                       "api_node": False},
}
_IDX = [{"title": "Video", "type": "video", "templates": [
    {"name": "famous_t2v", "title": "Famous 5B Text to Video",
     "models": ["Famous", "FamousCo"], "size": 9_000_000_000,
     "tags": ["Text to Video", "Video"]},
    {"name": "famous_i2v", "title": "Famous 5B Image to Video",
     "models": ["Famous"], "size": 9_500_000_000, "tags": ["Image to Video", "Video"]},
    {"name": "hunyuanvideo_t2v", "title": "HunyuanVideo Text to Video",
     "models": ["Hunyuan Video"], "size": 40_000_000_000, "tags": ["Video"]},
]}]

_saved_root = A.ROOT
try:
    _tmp = Path(tempfile.mkdtemp())
    A.ROOT = _tmp
    _tpl = (_tmp / "data" / "comfyui-venv" / "lib" / "python3.12" / "site-packages"
            / "comfyui_workflow_templates_json" / "templates")
    _tpl.mkdir(parents=True)
    (_tpl / "index.json").write_text(json.dumps(_IDX))
    (_tpl / "famous_t2v.json").write_text(json.dumps(_UI))
    # a SECOND workflow on the SAME model — sample's "one model can carry several
    # workflows (t2v, i2v, v2v, image)". It takes a starting picture, so it also
    # exercises the needs-a-source path.
    _i2v = json.loads(json.dumps(_UI))
    # …on its OWN weight file, so it stays incomplete while the t2v one is ready. That
    # is the state sample's picker has to draw: one model, two workflows, one works.
    _i2v["nodes"][0]["widgets_values"] = ["famous_i2v_5B.safetensors", "default"]
    _i2v["nodes"][0]["properties"]["models"].append(
        {"name": "famous_i2v_5B.safetensors", "directory": "diffusion_models",
         "url": "https://example.invalid/famous_i2v_5B.safetensors"})
    _i2v["nodes"].append({"id": 20, "type": "LoadImage", "mode": 0,
                          "widgets_values": ["x.png", "image"],
                          "inputs": [], "outputs": []})
    (_tpl / "famous_i2v.json").write_text(json.dumps(_i2v))
    _hy = json.loads(json.dumps(_UI))
    _hy["nodes"][0]["widgets_values"] = ["hunyuan_video_720.safetensors", "default"]
    _hy["nodes"][0]["properties"]["models"] = [
        {"name": "hunyuan_video_720.safetensors", "directory": "diffusion_models",
         "url": "https://example.invalid/hy.safetensors"}]
    (_tpl / "hunyuanvideo_t2v.json").write_text(json.dumps(_hy))

    ok(CUR.templates_dir() == _tpl, "the vendored registry is FOUND by globbing the venv")
    cat = CUR.catalog()
    by = {m["title"]: m for m in cat["models"]}
    ok(cat["ok"] and "Famous" in by,
       "a model nobody typed into this repo appears, named by upstream's own index.json")
    fam = by["Famous"]
    ok(fam["workflow_count"] == 2,
       "…carrying BOTH of its workflows (sample's t2v / i2v / v2v shape)")
    wt = next(w for w in fam["workflows"] if w["id"] == "famous_t2v")
    ok(wt["title"] == "Famous 5B Text to Video" and wt["kind"] == "video",
       "…each with upstream's own human title and kind, not a name we invented")
    names = sorted(f["name"] for f in wt["files"])
    ok(names == ["enc.safetensors", "famous_5B.safetensors"],
       "⚠️ THE REQUIREMENT IS THE GRAPH, NOT THE REGISTRY: the 14B ALTERNATIVE and the "
       "BYPASSED LoRA are both in properties.models and neither is required")
    ok(all(not f["present"] for f in wt["files"]) and not wt["complete"],
       "with nothing on disk the workflow is incomplete, and says which files are missing")
    ok(wt["missing_bytes"] is None and wt["missing_h"] is None,
       "…and a size nobody has HEAD-verified is NOTHING, never a plausible number")
    ok(not fam["installed"], "…so the model is not 'installed'")
    ok(by["Hunyuan Video"]["refused"] and "EU" in by["Hunyuan Video"]["refused"],
       "HunyuanVideo is listed and REFUSED with its reason — an absent row would read "
       "as a bug in the scan")

    # DOWNLOAD ONE → IT APPEARS. DELETE IT → IT DROPS OFF. sample's sentence, executed.
    for d, n, size in (("diffusion_models", "famous_5B.safetensors", 5000),
                       ("text_encoders", "enc.safetensors", 700)):
        p = CUR.models_dir() / d / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"0" * size)
    cat2 = CUR.catalog()
    fam2 = next(m for m in cat2["models"] if m["title"] == "Famous")
    wt2 = next(w for w in fam2["workflows"] if w["id"] == "famous_t2v")
    ok(wt2["complete"] and fam2["installed"],
       "the moment the files are on disk the workflow is complete and the model is "
       "installed — no list edited, no cache invalidated")
    ok(wt2["files"][0]["bytes"] == 5000 and wt2["files"][0]["size_source"] == "on disk",
       "…and its size is the size on disk, which is the only size we can be sure of")
    ok(fam2["ready"] == 1 and fam2["workflow_count"] == 2,
       "…while the workflow that needs more is still listed, still incomplete")
    (CUR.models_dir() / "diffusion_models" / "famous_5B.safetensors").unlink()
    fam3 = next(m for m in CUR.catalog()["models"] if m["title"] == "Famous")
    ok(not fam3["installed"],
       "DELETE THE MODEL AND IT DROPS OFF, on the next read, with nothing to invalidate")
    (CUR.models_dir() / "diffusion_models" / "famous_5B.safetensors").write_bytes(b"0" * 5000)

    # ── the converter ────────────────────────────────────────────────────────
    conv = CUR.ui_to_api(_UI, _INFO)
    ok(conv["ok"], f"the vendored UI graph converts to API format ({conv['reason']})")
    api = conv["graph"]
    ok("9" not in api, "MarkdownNote is dropped — the frontend owns it, not the engine")
    ok("5" not in api, "a BYPASSED node is not submitted…")
    ok(api["7"]["inputs"]["model"] == ["1", 0],
       "…and its MODEL input is routed straight through to the sampler, which is what "
       "ComfyUI itself does with mode 4 — reading bypass as 'muted' refused four stock "
       "Wan/SDXL templates that run perfectly in the editor")
    ok(api["7"]["inputs"]["steps"] == 12,
       "a PrimitiveNode feeding a widget resolves to its LITERAL value")
    ok(api["7"]["inputs"]["cfg"] == 6.0 and api["7"]["inputs"]["sampler_name"] == "uni_pc",
       "⚠️ control_after_generate IS ACCOUNTED FOR: the hidden 'randomize' slot sits in "
       "widgets_values, and ignoring it shifts every later widget by one — silently "
       "sampling with cfg where steps was meant")
    ok(api["7"]["inputs"]["positive"] == ["3", 0]
       and api["7"]["inputs"]["negative"] == ["4", 0],
       "links become [node, slot] pairs pointing at nodes that exist")
    ctl = CUR.workflow_controls(api, conv["widgets"])
    ok(ctl["prompt"]["node"] == "3" and ctl["negative"]["node"] == "4",
       "the prompt and the negative prompt are FOUND by walking back from the sampler, "
       "not assumed from graph shape")
    ok("width" not in ctl,
       "a template with no size widget shows no size control — the page draws the "
       "knobs this workflow really has")
    used = CUR.apply_controls(api, ctl, {"prompt": "a red fox", "steps": 9999,
                                         "seed": 7, "width": 512})
    ok(api["3"]["inputs"]["text"] == "a red fox", "the typed prompt lands in its node")
    ok(used["steps"] == 200 and api["7"]["inputs"]["steps"] == 200,
       "…an absurd step count is clamped and the clamped value is REPORTED back")
    ok("width" not in used,
       "…and a value for a knob this workflow does not have is dropped, never injected")
    ok(CUR.retarget_outputs(api) == 1
       and api["8"]["inputs"]["filename_prefix"] == "motdeck/image",
       "every Save node is retargeted under <output>/motdeck/ — otherwise the run "
       "succeeds and the gallery, which only looks there, shows nothing")

    # ── THE WALKED CONVERTER BUG (2026-08-29, LIE class) ─────────────────────
    # A real discovered workflow — Wan 2.1 Fun Camera, downloaded live through the new
    # lane — was submitted with `speed` = 81 against a max of 10, because
    # WanCameraEmbedding's `camera_pose` is a combo spelled `"COMBO"` (the newer
    # /object_info schema) rather than a LIST of options (the legacy one). Only the list
    # form counted as a widget, so camera_pose fell out of the slot list and every later
    # value shifted by one: width took "Zoom In", height took the width, speed took the
    # frame count. ComfyUI's validator caught THIS one because a number was out of
    # range. A template whose types happened to line up would have rendered the wrong
    # picture in silence. Both halves of the fix are pinned: the spelling, and the
    # invariant that makes the whole class a refusal instead of a wrong graph.
    _COMBO = {
        "NewSchema": {"python_module": "nodes", "input": {"required": {
            "camera_pose": ["COMBO", {"default": "Static",
                                      "options": ["Static", "Zoom In"]}],
            "width": ["INT", {"default": 832}], "height": ["INT", {"default": 480}],
            "length": ["INT", {"default": 81}]},
            "optional": {"speed": ["FLOAT", {"default": 1.0}]}}},
        # …and the THIRD spelling, found on the SAME walk one node further down the
        # graph: SaveVideo's `format` and `codec` are "COMFY_DYNAMICCOMBO_V3". Missing
        # them submitted SaveVideo with no format, and the run died sixty seconds in —
        # AFTER the sampling had been paid for. Hence a predicate over the type NAME
        # rather than a third entry in a list of spellings.
        "Saver": {"python_module": "nodes", "input": {
            "required": {"video": ["VIDEO", {}],
                         "filename_prefix": ["STRING", {"default": "video/ComfyUI"}],
                         "format": ["COMFY_DYNAMICCOMBO_V3", {"default": "auto"}]},
            "optional": {"codec": ["COMFY_DYNAMICCOMBO_V3", {"default": "auto"}]}}},
    }
    _g = {"nodes": [{"id": 1, "type": "NewSchema", "mode": 0,
                     "widgets_values": ["Zoom In", 512, 512, 81, 1],
                     "inputs": [], "outputs": [],
                     "properties": {"models": []}}], "links": []}
    _c = CUR.ui_to_api(_g, _COMBO)
    ok(_c["ok"], "a node whose combo is spelled \"COMBO\" converts at all")
    ok(_c["graph"]["1"]["inputs"]["camera_pose"] == "Zoom In"
       and _c["graph"]["1"]["inputs"]["width"] == 512
       and _c["graph"]["1"]["inputs"]["length"] == 81
       and _c["graph"]["1"]["inputs"]["speed"] == 1,
       "…with EVERY value in its own slot — the shipped bug put the frame count in "
       "`speed` and the words 'Zoom In' in `width`")
    _sv = {"nodes": [{"id": 1, "type": "Saver", "mode": 0,
                      "widgets_values": ["video/ComfyUI", "auto", "auto"],
                      "inputs": [{"name": "video", "type": "VIDEO", "link": None}],
                      "outputs": [], "properties": {"models": []}}], "links": []}
    _svr = CUR.ui_to_api(_sv, _COMBO)
    ok(_svr["ok"] and _svr["graph"]["1"]["inputs"]["format"] == "auto"
       and _svr["graph"]["1"]["inputs"]["codec"] == "auto",
       "…and so does the DYNAMIC combo spelling — the third one in a single "
       "/object_info, and the one that cost a 60s render before it errored")
    ok(CUR.retarget_outputs(_svr["graph"]) == 0,
       "(a Save node this surface does not know the kind of is left alone rather than "
       "retargeted into a folder it never writes to)")

    _bad = {"Shifted": {"python_module": "nodes", "input": {"required": {
        "width": ["INT", {"default": 8}], "mystery": [["a", "b"], {}]}}}}
    _bg = {"nodes": [{"id": 1, "type": "Shifted", "mode": 0, "widgets_values": [512],
                      "inputs": [], "outputs": [], "properties": {"models": []}}],
           "links": []}
    _br = CUR.ui_to_api(_bg, _bad)
    ok(not _br["ok"] and "wrong slots" in (_br["reason"] or ""),
       "THE ALIGNMENT GUARD: a node that would be submitted missing a REQUIRED widget "
       "is refused by name — a workflow we cannot convert faithfully is never submitted "
       "with values in the wrong slots (it caught five more stock templates on the "
       "live tree the moment it was added)")
    _tail = {"Grew": {"python_module": "nodes", "input": {"required": {
        "a": ["INT", {"default": 1}], "b": ["INT", {"default": 7}]}}}}
    _tg = {"nodes": [{"id": 1, "type": "Grew", "mode": 0, "widgets_values": [5],
                      "inputs": [], "outputs": [], "properties": {"models": []}}],
           "links": []}
    _tr = CUR.ui_to_api(_tg, _tail)
    ok(_tr["ok"] and _tr["graph"]["1"]["inputs"] == {"a": 5, "b": 7},
       "…while a template authored BEFORE the node grew a parameter takes the node's "
       "own default for the tail, which is exactly what ComfyUI's editor does — the "
       "distinction is tail-vs-middle, so the guard above still bites")

    # A SHAPE STATED TWICE MUST BE CHANGED TWICE (same walk, same workflow).
    _two = {"A": {"python_module": "nodes", "input": {"required": {
                "length": ["INT", {"default": 81}]}}},
            "B": {"python_module": "nodes", "input": {"required": {
                "length": ["INT", {"default": 81}], "width": ["INT", {"default": 8}]}}}}
    _tg2 = {"nodes": [
        {"id": 1, "type": "A", "mode": 0, "widgets_values": [81], "inputs": [],
         "outputs": [], "properties": {"models": []}},
        {"id": 2, "type": "B", "mode": 0, "widgets_values": [81, 832], "inputs": [],
         "outputs": [], "properties": {"models": []}}], "links": []}
    _r2 = CUR.ui_to_api(_tg2, _two)
    _ctl2 = CUR.workflow_controls(_r2["graph"], _r2["widgets"])
    CUR.apply_controls(_r2["graph"], _ctl2, {"length": 21})
    ok(_r2["graph"]["1"]["inputs"]["length"] == 21
       and _r2["graph"]["2"]["inputs"]["length"] == 21,
       "a frame count the graph states TWICE is changed in BOTH places — Wan's camera "
       "workflow embeds a camera path whose length must match the video's, and setting "
       "only the first is how '21 frames' becomes a graph that disagrees with itself")

    # THE DYNAMIC FENCE — the supply-chain ruling against evidence, not a name list.
    ok(CUR.stock_class("KSampler", _INFO) and not CUR.stock_class("EvilNode", _INFO),
       "a class whose /object_info python_module is custom_nodes.* is NOT stock")
    ok(not CUR.stock_class("NeverHeardOf", _INFO),
       "…and a class the server does not have at all is not stock either")
    _evil = dict(api)
    _evil["99"] = {"class_type": "EvilNode", "inputs": {}}
    ok(CUR.dynamic_fence_violations(_evil, _INFO) == ["EvilNode"],
       "a graph carrying a third-party class is refused BY NAME (LLMVISION / "
       "Ultralytics, as a gate rather than a paragraph)")
    ok(CUR.dynamic_fence_violations(api, _INFO) == [],
       "…and a stock template passes it, which is what makes the fence usable at all")
    _hosted = {"1": {"class_type": "HostedByFlag", "inputs": {}},
               "2": {"class_type": "HostedByModule", "inputs": {}},
               "3": {"class_type": "KSampler", "inputs": {}}}
    ok(CUR.hosted_api_nodes(CUR.graph_classes(_hosted), _INFO)
       == ["HostedByFlag", "HostedByModule"],
       "the local-only fence follows ComfyUI's api_node/module authority and never "
       "classifies an ordinary stock node by its marketing name")
    _hosted_ui = {"nodes": [
        {"id": 1, "type": "HostedByFlag", "mode": 0},
        {"id": 2, "type": "HostedByModule", "mode": 0},
        {"id": 3, "type": "KSampler", "mode": 0},
        {"id": 4, "type": "HostedByFlag", "mode": 4},
    ], "links": []}
    ok(CUR.hosted_api_nodes(CUR.ui_graph_classes(_hosted_ui), _INFO)
       == ["HostedByFlag", "HostedByModule"],
       "the same local-only predicate reads catalogue UI graphs, ignores bypassed "
       "nodes, and does not crash by treating UI nodes as API-map values")

    # A SIZE WE HAVE HEAD-VERIFIED IS USED; ONE WE HAVE NOT IS ABSENT.
    CUR.SIZES["https://example.invalid/enc.safetensors"] = 700_000_000
    (CUR.models_dir() / "text_encoders" / "enc.safetensors").unlink()
    w = next(w for w in CUR.catalog()["models"][0]["workflows"] if w["id"] == "famous_t2v")
    f = next(f for f in w["files"] if f["name"] == "enc.safetensors")
    ok(f["bytes"] == 700_000_000 and f["size_source"] == "HEAD",
       "a HEAD-verified size is used and SAYS it came from a HEAD")
    ok(w["missing_bytes"] == 700_000_000,
       "…and the workflow's missing total is real arithmetic over known sizes only")
    CUR.SIZES["https://huggingface.co/acme/model/resolve/main/enc.safetensors"] = {
        "bytes": 700_000_000, "sha256": "a" * 64, "source": "huggingface-lfs",
    }
    ok(CUR.digest_known("https://huggingface.co/acme/model/resolve/main/enc.safetensors")
       == "a" * 64,
       "…and an authoritative Hugging Face LFS digest shares that same cache record")
finally:
    A.ROOT = _saved_root
    CUR.SIZES.pop("https://example.invalid/enc.safetensors", None)
    CUR.SIZES.pop("https://huggingface.co/acme/model/resolve/main/enc.safetensors", None)

# ⚠️ THE SOURCE-TEXT HALF OF THE SAME GROUP: discovered Hugging Face LFS files get
# source-qualified content verification, while every other source remains honestly
# size-only. CDN/Xet storage hashes must never be mistaken for file-content identity.
ok("X-Linked-ETag" in router and "size + Hugging Face LFS sha256" in router
   and "size declared by server" in router and "X-Xet-Hash" in router,
   "a discovered download states whether it got Hugging Face LFS content verification "
   "or only the source-declared size — and explicitly rejects the CDN/Xet hash shortcut")
ok('seen = {r["filename"] for r in out}' in router
   and "p.name not in seen" in router,
   "the Source list is DEDUPED on the file name — submitting a gallery picture copies "
   "it into input/, so the same still appeared twice with the identical label and no "
   "way to tell the two rows apart (walked 2026-08-29)")
ok("needs_source" in router and "pick one under Source" in router,
   "an image-to-video workflow that has been given no picture REFUSES with the fix, "
   "instead of letting ComfyUI fail on a filename that is not in input/")
ok("hosted_api_nodes(ui_graph_classes(graph), info)" in router
   and "hosted API node(s) are outside MOT Deck's local-only Generate surface" in router,
   "catalogue and submit paths share the metadata-backed local-only boundary")
ok(router.index("remote = hosted_api_nodes", router.index("async def _generate_workflow"))
   < router.index('if not wf["complete"]', router.index("async def _generate_workflow")),
   "direct workflow submission proves the local-only boundary BEFORE returning a "
   "missing-model/download response")
print(f"\n{checks - fails}/{checks} checks passed")
sys.exit(1 if fails else 0)
