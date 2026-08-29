"""CORE — the Generate surface's CURATION, CATALOG and GRAPH layer.

Extracted out of bridge/routers/comfy.py (ledger S8) when that file hit the 1,500-line
facade ceiling. NOTHING here talks to the network or to FastAPI: this module is paths,
disk arithmetic, the vendored template registry, the model catalog and the graph
builders — all pure enough that bridge/tests/test_comfy_lane.py can pin every branch
without a GPU, a download or a running ComfyUI. The router keeps the routes, the
ComfyUI client, the download engine, the job follower and the gallery.

⚠️ THIS MODULE IS IN bridge/app.py's `_LANES` EVEN THOUGH IT OWNS NO ROUTE, and that is
   deliberate rather than sloppy. The facade's `__setattr__` only reaches modules in
   `_FACADE_MODULES` (built from `_LANES`), so `A.ROOT = tmpdir` — which four suites and
   the whole gallery/file-state group of test_comfy_lane.py depend on — would NOT rebind
   this module's `ROOT` if it were left out. The result would not be a red test; it
   would be a green one measuring the REAL app directory. Registration is also required
   in bridge/appsrc.py's FILES (the contract seam test enforces it both ways).

═══ THE FOUR THINGS THE NEXT READER MUST NOT RE-DERIVE ═══════════════════════════════

1. THE PATHS ARE THE APP'S, NOT THE REPO'S. A repo checkout has no data/comfyui; the
   running instance belongs to the SHIPPED app. Everything resolves off ROOT.

2. CURATION IS GENERATED, NOT TYPED, AND THE CATALOG IS DISCOVERED. `PICKS` is the
   RECOMMENDED SUBSET — two models with HEAD-verified sizes, sha256 pins and licences we
   read. The CATALOG below is the superset: every template-native model the vendored
   registry knows, cross-checked against what is actually on disk right now. Delete a
   model and it drops off; download one and its workflows appear. Neither list is typed
   into this file.

3. A WORKFLOW'S REQUIRED FILES COME FROM THE GRAPH, NOT FROM `properties.models`.
   ⚠️ THIS IS A LIE-CLASS FINDING, FOUND BY READING THE REAL REGISTRY. `properties.models`
   is a DOWNLOAD MENU and it lists ALTERNATIVES: `video_wan_vace_14B_t2v` carries seven
   entries — the 1.3B *and* the 14B diffusion model, two rival LoRAs, two rival text
   encoders — of which the graph's own loaders name exactly four. Treating the registry
   as the requirement would have told the user they were missing 33 GB of files the
   workflow never loads. So the requirement is read off the ACTIVE loader nodes'
   widget values, and `properties.models` is used only to attach the download URL.

4. UPSTREAM'S OWN index.json IS THE HUMAN LAYER, AND WE DO NOT INVENT ONE. Titles
   ("Wan 2.1 Image to Video"), the model NAME a workflow belongs to (["Wan2.1", "Wan"]),
   the tags that say text-to-video vs video-to-video, the total download size and the
   io.inputs list are all authored upstream and shipped in the vendored package. A
   workflow with no index row is not renamed by us — it keeps its file name.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .appctx import ROOT

# ── constants ────────────────────────────────────────────────────────────────
DISK_HEADROOM = 2 * 1024 ** 3   # "leaves ~X" is measured against this reserve
STARTER_CAP_BYTES = 14_000_000_000   # Debi's locked S1 budget, DECIMAL GB (the unit
                                     # HuggingFace, `df -h` and model cards all use)

# <output>/harness/ is ours; anything else there came from the ComfyUI tab, untouched.
OUT_PREFIX = "harness"

# ⚠️ THE STOCK-NODE FENCE, STATIC HALF: every class the CURATED builders may emit.
# Adding one is deliberate, and it must ship with ComfyUI rather than with a custom pack.
# The DYNAMIC half (`stock_class`, below) answers the same question for a discovered
# template, where a hand-written allow-list would either be wrong or be the whole of
# ComfyUI retyped.
ALLOWED_NODES = frozenset({
    "UNETLoader", "CLIPLoader", "VAELoader", "CheckpointLoaderSimple",
    "CLIPTextEncode", "ModelSamplingSD3", "EmptyHunyuanLatentVideo",
    "EmptyLatentImage", "KSampler", "VAEDecode", "CreateVideo",
    "SaveVideo", "SaveImage",
})


# ══ THE CURATION ═════════════════════════════════════════════════════════════
#
# HOW THIS SET WAS CHOSEN (Debi's constraint: image AND video, ≤14 GB TOTAL, smallest
# viable from the LTX / Wan / Qwen families, Apache preferred, licence READ not tagged).
#
# The candidate space is not "every model on HuggingFace" — it is "every model a STOCK,
# VENDORED template can already drive". Of the 517 templates in our pinned
# comfyui-workflow-templates 0.11.48 only 78 still carry the `properties.models`
# registry (the newest have moved to the asset system, DISABLED at our pin —
# `GET /features` → `"assets": false`). Within those 78:
#
#   · smallest VIDEO set with a usable registry … Wan 2.1 T2V 1.3B  →  9.83 GB
#   · smallest IMAGE set with a usable registry … SDXL base 1.0     →  6.94 GB
#   · the pair → 16.77 GB, which does not fit 14 GB, and there is no smaller pair.
#
# ⚠️ THE ONE-MODEL ANSWER WAS TRIED FIRST, AND MEASURED, NOT ASSUMED. Wan's t2v graph is
# nominally also an image generator (`EmptyHunyuanLatentVideo` length=1 → SaveImage),
# covering both in one 9.83 GB Apache-2.0 download, 4.17 GB inside the cap. It WAS
# shipped that way and generated live here on 2026-08-29 — 832×480, 20 steps, 59.6 s,
# peak 7.6 GB — and the PNG was two flat bands of colour; a five-frame retry was no
# better. Keeping that as the image half would have been the LIE class, so the evidence
# changed the curation to image → SDXL base 1.0 + video → Wan 2.1, a 16.77 GB starter
# set, 2.77 GB OVER the cap. That is the spec's own fallback — ship the pair and SAY the
# overshoot rather than silently dropping video — and `cap_statement()` puts the number
# and the reason on the page. Wan keeps its `image` mode (the graph really does it, and
# a better torch may make it good) carrying the measured verdict.
#
# LICENCES WERE READ, NOT TRUSTED FROM THE TAG (the twice-learned lesson):
#   · Wan 2.1 → Wan-AI/Wan2.1-T2V-1.3B/LICENSE.txt is verbatim Apache-2.0.
#   · SDXL base → its LICENSE.md is CreativeML Open RAIL++-M (use restrictions, no cap).
#   · ⚠️ SDXL **TURBO** IS NOT CURATED, AND THE RESEARCH BRIEF IMPLIED IT WOULD BE. Its
#     HF tag is `other`; its `license_name` is `sai-nc-community` — Stability's
#     NON-COMMERCIAL research licence. Same size, same template shape, red licence.
#   · HunyuanVideo stays REFUSED regardless of fit (no EU grant); not in this file.
#
# Sizes and sha256s are HEAD/LFS-verified against HuggingFace on 2026-08-29.
PICKS: tuple = (
    {
        "id": "wan21_t2v_1_3b",
        "title": "Wan 2.1 T2V 1.3B",
        "vendor": "Alibaba Wan-AI · Comfy-Org repackage",
        "template": "text_to_video_wan",
        "graph": "wan",
        "modes": ("image", "video"),
        "starter": True,
        "license": "Apache-2.0",
        "license_badge": "green",
        "license_note": ("Apache-2.0, read from Wan-AI/Wan2.1-T2V-1.3B/LICENSE.txt "
                         "(not from the HF tag). Commercial use permitted."),
        "license_url": "https://huggingface.co/Wan-AI/Wan2.1-T2V-1.3B/blob/main/LICENSE.txt",
        "role": "video",
        "note": ("The video half of the starter set. The same stock graph can also emit "
                 "a single frame, but see the measured verdict on that below."),
        # MEASURED ON THIS MAC, 2026-08-29 — no line here is a prediction. Surfaced on
        # the card and in the form, per mode, BEFORE the button is pressed.
        "health": {
            "video": ("⚠️ this model's OUTPUT is wrong on this Mac. Measured 2026-08-29: "
                      "17 frames · 832×480 · 20 steps → 2m56s, peak 28.9 GB, washed-out "
                      "blur; 33 frames · 30 steps → 12m38s, recognisable shapes but the "
                      "COLOURS are wrong. SDXL renders perfectly on the same ComfyUI, "
                      "the same MPS torch nightly, minutes apart — so this is Wan-"
                      "specific (its fp16 weights on MPS are the first suspect), not a "
                      "broken engine. The graph, queue, progress and gallery all work; "
                      "the pictures do not. Kept so the fix can be A/B'd against these "
                      "numbers rather than re-derived."),
            "image": ("measured 2026-08-29: a single frame (length = 1) took 59.6 s, "
                      "peaked 7.6 GB, and came out as two flat bands of colour. Use "
                      "SDXL for stills; this mode is kept because the graph really does "
                      "it and a fixed model would make it worth having."),
        },
        "files": (
            {"directory": "diffusion_models",
             "name": "wan2.1_t2v_1.3B_fp16.safetensors",
             "bytes": 2_838_303_560,
             "sha256": "be531024cd9018cb5b48c40cfbb6a6191645b1c792eb8bf4f8c1c6e10f924dc5"},
            {"directory": "text_encoders",
             "name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
             "bytes": 6_735_906_897,
             "sha256": "c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68",
             "shared": "serves every Wan variant — a later Wan pick reuses this file"},
            {"directory": "vae",
             "name": "wan_2.1_vae.safetensors",
             "bytes": 253_815_318,
             "sha256": "2fc39d31359a4b0a64f55876d8ff7fa8d780956ae2cb13463b0223e15148976b"},
        ),
        # Defaults per mode. Video length must be 4n+1 (the latent temporal stride);
        # _wan_length() enforces that rather than letting a user pick an invalid 30.
        "defaults": {
            "image": {"width": 832, "height": 480, "steps": 25, "cfg": 6.0},
            "video": {"width": 832, "height": 480, "steps": 25, "cfg": 6.0,
                      "frames": 33, "fps": 16},
        },
        "negative_default": (
            "色调艳丽，过曝，静态，"
            "细节模糊不清，字幕，风格"
            "，作品，画作，画面，静止"
            "，整体发灰，最差质量，"
            "低质量，JPEG压缩残留，丑陋"
            "的，残缺的，多余的手指"),
    },
    {
        "id": "sdxl_base_1_0",
        "title": "SDXL base 1.0",
        "vendor": "Stability AI",
        "template": "image_sdxl_simple",
        "graph": "sdxl",
        "modes": ("image",),
        "starter": True,
        "role": "image",
        "license": "CreativeML Open RAIL++-M",
        "license_badge": "amber",
        "license_note": ("Open RAIL++-M, read from the repo's LICENSE.md. Permissive on "
                         "commerce, but it carries USE RESTRICTIONS you agree to."),
        "license_url": ("https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0"
                        "/blob/main/LICENSE.md"),
        "note": ("The image half of the starter set. A dedicated image model, because "
                 "the one-frame trick on the video model was tried here and did not "
                 "produce a usable picture."),
        # No health note: measured 2026-08-29 at 1024×1024 · 25 steps → 38.3 s, peak
        # 12.4 GB, and the picture was a photograph. A warning that fires on everything
        # says nothing, so this pick says nothing.
        "files": (
            {"directory": "checkpoints",
             "name": "sd_xl_base_1.0.safetensors",
             "bytes": 6_938_078_334,
             "sha256": "31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b"},
        ),
        "defaults": {
            "image": {"width": 1024, "height": 1024, "steps": 25, "cfg": 7.0},
        },
        "negative_default": ("lowres, blurry, out of focus, deformed, bad anatomy, "
                             "extra limbs, mutated, watermark, text, logo, signature"),
    },
)

PICK_BY_ID = {p["id"]: p for p in PICKS}


# ══ PATHS — all off ROOT, never off the repo ═════════════════════════════════
def comfy_base() -> Path:
    """ComfyUI's --base-directory: models/, output/, input/, user/ live under it."""
    return ROOT / "data" / "comfyui"


def models_dir() -> Path:
    return comfy_base() / "models"


def output_dir() -> Path:
    return comfy_base() / "output"


def input_dir() -> Path:
    """ComfyUI's own input/ — where LoadImage and LoadVideo read from."""
    return comfy_base() / "input"


def state_dir() -> Path:
    """OUR store — gallery + measurements. Outside ComfyUI's tree, so a reinstall
    cannot take the gallery's memory with it."""
    return ROOT / "data" / "comfy"


def templates_dir() -> "Path | None":
    """The vendored comfyui-workflow-templates JSON dir, or None. GLOBBED, not
    hard-coded: the venv's pythonX.Y moves with every interpreter bump, and a curation
    that silently empties itself is worse than one that says the registry is gone."""
    venv = ROOT / "data" / "comfyui-venv" / "lib"
    try:
        for py in sorted(venv.glob("python*")):
            for pkg in ("comfyui_workflow_templates_json", "comfyui_workflow_templates"):
                d = py / "site-packages" / pkg / "templates"
                if d.is_dir():
                    return d
    except OSError:
        pass
    return None


# ══ DISK — from the right volume, and it says which ══════════════════════════
def _disk(path: Path) -> dict:
    """statvfs the nearest EXISTING ancestor of `path`, reporting where it landed.

    ⚠️ THE ANCESTOR WALK IS THE POINT: <base>/models/vae does not exist before the first
    download, statvfs raises, and the tempting fix (ROOT, or "/") is the wrong-volume
    bug. Walking UP stays on the volume the file will land on."""
    p = Path(path)
    tried = str(p)
    while True:
        try:
            st = os.statvfs(str(p))
            return {"free_bytes": int(st.f_bavail) * int(st.f_frsize),
                    "total_bytes": int(st.f_blocks) * int(st.f_frsize),
                    "measured_at": str(p), "requested": tried, "ok": True}
        except OSError:
            if p.parent == p:
                return {"free_bytes": None, "total_bytes": None,
                        "measured_at": None, "requested": tried, "ok": False}
            p = p.parent


def disk_verdict(need: int, free: "int | None") -> dict:
    """ADVISORY, always. Numbers + a recommendation; never a veto.

    Pure (no I/O) so bridge/tests/test_comfy_lane.py can pin every branch."""
    if not free:
        return {"level": "unknown", "text": "free space could not be read on this volume"}
    leaves = free - need
    if need > free:
        return {"level": "no",
                "text": (f"needs {gb(need)} · {gb(free)} free — {gb(need - free)} short. "
                         f"Free space first; the download would fail part-way.")}
    if leaves < DISK_HEADROOM:
        return {"level": "tight",
                "text": (f"needs {gb(need)} · {gb(free)} free · would leave {gb(leaves)}. "
                         f"That is under the {gb(DISK_HEADROOM)} the OS wants for swap "
                         f"and temp files — expect the Mac to feel unwell.")}
    return {"level": "ok",
            "text": f"needs {gb(need)} · {gb(free)} free · leaves ~{gb(leaves)}"}


def gb(n: "int | None") -> str:
    """Decimal GB — the unit HuggingFace, `df -h` and model cards all use."""
    if n is None:
        return "?"
    n = int(n)
    if n == 0:
        return "nothing"
    if n < 1_000_000:
        return f"{n / 1000:.0f} kB"
    if n < 1_000_000_000:
        return f"{n / 1e6:.0f} MB"
    return f"{n / 1e9:.2f} GB"


# ══ THE REGISTRY READ — curation is GENERATED ════════════════════════════════
def template_models(name: str) -> "list | None":
    """`properties.models[]` out of one vendored template, or None if unreadable, as
    [{name, url, directory}] DEDUPED on (directory, name): several templates list one
    shared encoder twice and a naive read double-counts 6.7 GB.

    ⚠️ THIS IS THE DOWNLOAD MENU, NOT THE REQUIREMENT — see the module docstring's
    point 3. `workflow_files()` is what a workflow actually loads."""
    g = template_graph(name)
    if g is None:
        return None
    out, seen = [], set()
    for node in g.get("nodes") or []:
        for m in ((node.get("properties") or {}).get("models") or []):
            key = (m.get("directory"), m.get("name"))
            if key in seen or not all(key):
                continue
            seen.add(key)
            out.append({"name": m.get("name"), "url": m.get("url"),
                        "directory": m.get("directory")})
    return out


def template_graph(name: str) -> "dict | None":
    """One vendored template's UI-format graph, or None if it cannot be read."""
    d = templates_dir()
    if d is None:
        return None
    try:
        g = json.loads((d / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return g if isinstance(g, dict) else None


def _file_state(f: dict) -> dict:
    """Is this file on disk, and is it the RIGHT file? "present" = the destination
    exists AND its byte count matches the pin; a wrong-size file is `corrupt`, never
    present, because calling it present is how a card lies."""
    dest = models_dir() / f["directory"] / f["name"]
    out = {"directory": f["directory"], "name": f["name"], "bytes": f["bytes"],
           "shared": f.get("shared"), "present": False, "on_disk_bytes": None,
           "state": "absent"}
    try:
        sz = dest.stat().st_size
    except OSError:
        part = Path(str(dest) + ".part")
        try:
            out["partial_bytes"] = part.stat().st_size
            out["state"] = "partial"
        except OSError:
            pass
        return out
    out["on_disk_bytes"] = sz
    if sz == int(f["bytes"]):
        out["present"] = True
        out["state"] = "present"
    else:
        out["state"] = "corrupt"
    return out


def pick_card(p: dict) -> dict:
    """One acquisition card: registry files, pinned facts, verdicts."""
    reg = template_models(p["template"])
    files = [_file_state(f) for f in p["files"]]
    drift = None
    if reg is None:
        drift = (f"the vendored workflow-templates registry could not be read, so "
                 f"'{p['template']}' could not be cross-checked — the pinned file list "
                 f"below is what will be downloaded")
    else:
        want = {(f["directory"], f["name"]) for f in p["files"]}
        have = {(m["directory"], m["name"]) for m in reg}
        if want != have:
            miss = sorted(f"{d}/{n}" for d, n in (want - have))
            extra = sorted(f"{d}/{n}" for d, n in (have - want))
            drift = ("this pin's template no longer matches our curation — "
                     + (f"we expect {', '.join(miss)}; " if miss else "")
                     + (f"the template now names {', '.join(extra)}" if extra else "")
                     + ". Re-run the curation pass before trusting these sizes.")
    # URLs come from the REGISTRY where it agrees, so the download follows upstream's
    # own link rather than a URL retyped into this file.
    urls = {(m["directory"], m["name"]): m["url"] for m in (reg or [])}
    for f, spec in zip(files, p["files"]):
        f["url"] = urls.get((spec["directory"], spec["name"]))
    total = sum(int(f["bytes"]) for f in p["files"])
    # ⚠️ PARTIAL BYTES COUNT AS ALREADY SPENT. A bridge restart mid-download loses the
    # in-memory record but NOT the .part (walked live here, at 2.4 GB of 9.8), and a
    # card that then re-quoted the full size would over-count the disk AND hide the
    # fact that the button now RESUMES.
    partial = sum(int(f.get("partial_bytes") or 0) for f in files)
    need = max(0, sum(int(f["bytes"]) for f in files if not f["present"]) - partial)
    dk = _disk(models_dir())
    card = dict(
        id=p["id"], title=p["title"], vendor=p["vendor"], template=p["template"],
        modes=list(p["modes"]), starter=bool(p["starter"]), note=p["note"],
        license=p["license"], license_badge=p["license_badge"],
        license_note=p["license_note"], license_url=p["license_url"],
        files=files, total_bytes=total, need_bytes=need, partial_bytes=partial,
        total_h=gb(total), need_h=gb(need), partial_h=gb(partial),
        downloaded=all(f["present"] for f in files),
        corrupt=[f["name"] for f in files if f["state"] == "corrupt"],
        registry_drift=drift,
        disk=(disk_verdict(need, dk.get("free_bytes")) if need
              else {"level": "done", "text": f"{gb(total)} already on disk"}),
        defaults=p["defaults"], negative_default=p["negative_default"],
        role=p.get("role"), health=p.get("health") or {},
        measured=MEASURED.get(p["id"]) or {},
    )
    return card


# The sentence that has to be true, printed where the download buttons are. It is
# generated from the same bytes the cards use, so it can never drift from them.
CAP_WHY = (
    "One model cannot cover both here: the video model's single-frame image mode was "
    "generated on this Mac and came out unusable, so stills need a real image model. "
    "The smallest template-native pair is the one below."
)


def cap_statement() -> dict:
    total = sum(int(f["bytes"]) for p in PICKS if p["starter"] for f in p["files"])
    over = total - STARTER_CAP_BYTES
    if over <= 0:
        return {"over": False, "starter_bytes": total, "cap_bytes": STARTER_CAP_BYTES,
                "text": (f"The starter set is {gb(total)} — image and video, inside the "
                         f"{gb(STARTER_CAP_BYTES)} budget.")}
    return {"over": True, "starter_bytes": total, "cap_bytes": STARTER_CAP_BYTES,
            "over_bytes": over,
            "text": (f"The starter set is {gb(total)} — {gb(over)} OVER the "
                     f"{gb(STARTER_CAP_BYTES)} budget, and that is stated rather than "
                     f"fixed by dropping one of the two. {CAP_WHY}")}


def curation() -> dict:
    dk = _disk(models_dir())
    cards = [pick_card(p) for p in PICKS]
    starter = [c for c in cards if c["starter"]]
    return {
        "picks": cards,
        "cap": cap_statement(),
        "cap_bytes": STARTER_CAP_BYTES, "cap_h": gb(STARTER_CAP_BYTES),
        "starter_bytes": sum(c["total_bytes"] for c in starter),
        "starter_h": gb(sum(c["total_bytes"] for c in starter)),
        "disk": dk,
        "models_dir": str(models_dir()),
        "templates_dir": str(templates_dir() or ""),
    }


# ══ MEASUREMENTS — measured peaks, never predictions ═════════════════════════
# The measure_music.sh pattern, in-process: a generation is TIMED and the ComfyUI
# process SAMPLED for phys_footprint while it runs, per (pick, mode). fit.py cannot
# price a torch/MPS diffusion run, so there is nothing to predict FROM and the card says
# "not measured yet" until a real run. (core/memory.py: phys_footprint, never RSS.)
MEASURED: dict = {}


def _measure_path() -> Path:
    return state_dir() / "measurements.json"


def _measure_load() -> None:
    try:
        MEASURED.update(json.loads(_measure_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass


def _measure_save() -> None:
    try:
        state_dir().mkdir(parents=True, exist_ok=True)
        tmp = str(_measure_path()) + ".harness-tmp"
        with open(tmp, "w") as f:
            json.dump(MEASURED, f, indent=2)
        os.replace(tmp, _measure_path())
    except OSError:
        pass


def measure_note(pick_id: str, mode: str) -> str:
    m = (MEASURED.get(pick_id) or {}).get(mode)
    if not m:
        return "not measured on this Mac yet — the next run is the measurement"
    return (f"last run: {m['wall_s']:.0f}s · peaked {gb(m['peak_bytes'])}"
            + (f" · {m['label']}" if m.get("label") else ""))


# ══ THE SIZE CACHE — HEAD-verified, never guessed ════════════════════════════
# A file we have NOT downloaded has no size on disk, and the vendored registry does not
# carry one. The honest answers are therefore exactly two: the number a HEAD request
# gave us (cached here forever, keyed by URL), or NOTHING. There is no third branch
# where a plausible size is printed — a wrong size under a Get button is the LIE class
# at its most expensive. The router owns the HTTP; this half owns the memory.
SIZES: dict = {}


def _sizes_path() -> Path:
    return state_dir() / "sizes.json"


def sizes_load() -> None:
    try:
        d = json.loads(_sizes_path().read_text(encoding="utf-8"))
        if isinstance(d, dict):
            SIZES.update({k: v for k, v in d.items() if isinstance(v, int)})
    except (OSError, ValueError):
        pass


def sizes_save() -> None:
    try:
        state_dir().mkdir(parents=True, exist_ok=True)
        tmp = str(_sizes_path()) + ".harness-tmp"
        with open(tmp, "w") as f:
            json.dump(SIZES, f, indent=2, sort_keys=True)
        os.replace(tmp, _sizes_path())
    except OSError:
        pass


def size_known(url: "str | None") -> "int | None":
    return SIZES.get(url) if url else None


# ══ THE CATALOG — discovered, not typed ══════════════════════════════════════
#
# ⚠️ WHY A CATALOG AT ALL (Debi, 2026-08-29): "if one deletes models, it should be
# dynamic. if one downloads other models, it should be dynamic and cater to them."
# `PICKS` above is a RECOMMENDATION — two models, sha-pinned, licence read. It is not
# the world. The catalog is: everything the vendored registry can drive, measured
# against what is on this disk at this instant. Nothing is remembered between renders,
# so deleting a file is visible on the next poll with no cache to invalidate.

# The directory a loader class writes into, for the one case the registry cannot answer:
# a file the GRAPH names that `properties.models` never listed. Derived from ComfyUI's
# own folder_paths conventions; a class not here yields no directory and the file is
# reported as "cannot be placed" rather than guessed into the wrong folder.
LOADER_DIRS = {
    "UNETLoader": "diffusion_models", "UnetLoaderGGUF": "diffusion_models",
    "CheckpointLoaderSimple": "checkpoints", "CheckpointLoader": "checkpoints",
    "ImageOnlyCheckpointLoader": "checkpoints",
    "CLIPLoader": "text_encoders", "DualCLIPLoader": "text_encoders",
    "TripleCLIPLoader": "text_encoders", "QuadrupleCLIPLoader": "text_encoders",
    "VAELoader": "vae",
    "LoraLoader": "loras", "LoraLoaderModelOnly": "loras",
    "CLIPVisionLoader": "clip_vision",
    "ControlNetLoader": "controlnet", "DiffControlNetLoader": "controlnet",
    "StyleModelLoader": "style_models", "GLIGENLoader": "gligen",
    "UpscaleModelLoader": "upscale_models",
    "AudioEncoderLoader": "audio_encoders",
    "PhotoMakerLoader": "photomaker", "DiffusersLoader": "diffusers",
    "ModelPatchLoader": "model_patches",
}

# The classes whose widget value is a MODEL FILE. Any class in LOADER_DIRS qualifies;
# this set is the answer to "which widget", and it is always the first string widget
# that looks like a weight file, which is how ComfyUI's own loaders are shaped.
WEIGHT_SUFFIXES = (".safetensors", ".ckpt", ".sft", ".pt", ".pth", ".bin", ".gguf",
                   ".onnx", ".gguf")

# The directories that hold a model's OWN identity rather than a shared accessory.
# A text encoder serves nine families; a diffusion model IS the family.
PRIMARY_DIRS = ("diffusion_models", "checkpoints", "unet")

# Nodes the FRONTEND owns: they carry no execution and are not in /object_info. Dropping
# them is not a compromise — ComfyUI drops them too when it converts to API format.
FRONTEND_ONLY = frozenset({"MarkdownNote", "Note", "Reroute", "PrimitiveNode",
                           "PreviewAny", "easy showAnything"})

# ⚠️ THE STANDING REFUSAL, ENFORCED HERE RATHER THAN BY OMISSION. HunyuanVideo has no EU
# licence grant (spec §Debi's locked answers), so it is refused whatever the disk says —
# and the catalog SAYS it is refused instead of quietly not listing it, because a model
# that is simply absent looks like a bug in the scan.
REFUSED_MODELS = {
    "hunyuanvideo": ("no EU licence grant — MOT Deck refuses this family outright "
                     "(standing verdict, docs/FABLE-COMFY-SURFACE-SPEC.md)"),
}


def _index_rows() -> dict:
    """Upstream's own index.json, as {template name: row}.

    It carries the human title, the MODEL NAME the workflow belongs to, the tags that
    say text-to-video vs video-to-video, the total download size and the io.inputs
    list. We author none of that; a template with no row keeps its file name."""
    d = templates_dir()
    if d is None:
        return {}
    try:
        idx = json.loads((d / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for cat in (idx if isinstance(idx, list) else []):
        for t in (cat.get("templates") or []):
            if t.get("name"):
                row = dict(t)
                row["category"] = cat.get("title")
                row["category_type"] = cat.get("type")
                out[t["name"]] = row
    return out


def _links_map(g: dict) -> dict:
    """link id → (origin node id, origin slot). Both shipped shapes are handled: the
    array form [id, orig, slot, targ, slot, type] and the newer object form."""
    out = {}
    for ln in (g.get("links") or []):
        if isinstance(ln, (list, tuple)) and len(ln) >= 3:
            out[ln[0]] = (ln[1], ln[2])
        elif isinstance(ln, dict) and ln.get("id") is not None:
            out[ln["id"]] = (ln.get("origin_id"), ln.get("origin_slot"))
    return out


def _active_nodes(g: dict) -> list:
    """The nodes that will actually run. mode 2 (muted) and 4 (bypassed) are OFF in
    ComfyUI's own semantics, and a template that ships with its image-to-video branch
    muted is a TEXT-to-video workflow — reading the muted branch as a requirement is
    how `video_wan2_2_5B_ti2v` would have demanded an input image it never uses."""
    return [n for n in (g.get("nodes") or [])
            if n.get("mode") not in (2, 4) and n.get("type") not in FRONTEND_ONLY]


def graph_weight_files(g: dict) -> list:
    """[(node id, class, filename)] for every weight file an ACTIVE loader names."""
    out = []
    for n in _active_nodes(g):
        cls = n.get("type")
        if cls not in LOADER_DIRS:
            continue
        for w in (n.get("widgets_values") or []):
            if isinstance(w, str) and w.lower().endswith(WEIGHT_SUFFIXES):
                out.append((n.get("id"), cls, w))
                break
    return out


def workflow_files(name: str, g: "dict | None" = None) -> "list | None":
    """The files this workflow REALLY needs, with the registry's URL where it has one.

    Each row: {directory, name, url, present, state, bytes, size_source}. `bytes` is
    the size on disk when the file is here, the HEAD-cached size when it is not and we
    have asked, and None otherwise — never a guess."""
    g = g if g is not None else template_graph(name)
    if g is None:
        return None
    reg = {}
    for node in g.get("nodes") or []:
        for m in ((node.get("properties") or {}).get("models") or []):
            if m.get("name"):
                reg[m["name"]] = m
    out, seen = [], set()
    for _nid, cls, fn in graph_weight_files(g):
        m = reg.get(fn) or {}
        directory = m.get("directory") or LOADER_DIRS.get(cls)
        if not directory or (directory, fn) in seen:
            continue
        seen.add((directory, fn))
        url = m.get("url")
        dest = models_dir() / directory / fn
        row = {"directory": directory, "name": fn, "url": url,
               "present": False, "state": "absent", "bytes": None,
               "size_source": None, "loader": cls}
        try:
            row["bytes"] = dest.stat().st_size
            row["present"] = True
            row["state"] = "present"
            row["size_source"] = "on disk"
        except OSError:
            part = Path(str(dest) + ".part")
            try:
                row["partial_bytes"] = part.stat().st_size
                row["state"] = "partial"
            except OSError:
                pass
            known = size_known(url)
            if known:
                row["bytes"] = known
                row["size_source"] = "HEAD"
        out.append(row)
    return out


def _tags(row: dict) -> list:
    return [t for t in (row.get("tags") or []) if isinstance(t, str)]


def workflow_kind(row: dict, g: "dict | None") -> str:
    """image / video / audio / 3d — upstream's own category type, corroborated by the
    output node the graph actually ends on. Never inferred from the file name."""
    t = (row.get("category_type") or "").lower()
    if t in ("image", "video", "audio", "3d"):
        return t
    for n in (_active_nodes(g or {}) or []):
        c = str(n.get("type") or "")
        if c.startswith("SaveVideo") or c.startswith("SaveAnimated"):
            return "video"
        if c.startswith("SaveAudio"):
            return "audio"
        if c.startswith("SaveImage"):
            return "image"
    return "image"


def workflow_inputs(row: dict, g: "dict | None") -> list:
    """The MEDIA a workflow needs handed to it — read off the ACTIVE LoadImage /
    LoadVideo / LoadAudio nodes, not off upstream's io.inputs list.

    ⚠️ THE TWO SOURCES DISAGREE, AND THE GRAPH WINS. index.json's io.inputs for
    `video_wan2_2_5B_ti2v` names a LoadImage that the shipped graph ships MUTED — the
    workflow is a text-to-video one as it stands. Believing the index would have put an
    "add a picture first" gate in front of a workflow that needs no picture."""
    want = {"LoadImage": "image", "LoadImageMask": "image", "LoadVideo": "video",
            "LoadAudio": "audio"}
    out = []
    for n in _active_nodes(g or {}):
        k = want.get(str(n.get("type") or ""))
        if k:
            out.append({"node": n.get("id"), "kind": k, "class": n.get("type")})
    return out


def model_key(row: dict, files: list) -> tuple:
    """(id, title) of the MODEL a workflow belongs to.

    Upstream's index.json names it (`"models": ["Wan2.1", "Wan"]`) and that is the
    vocabulary Debi uses — "the wan models, ltx, minimax h3". When the row has no model
    name we fall back to the primary weight file's own stem, which is unambiguous and
    still real. We never invent a marketing name."""
    ms = [m for m in (row.get("models") or []) if isinstance(m, str) and m.strip()]
    if ms:
        t = ms[0].strip()
        return ("m:" + t.lower().replace(" ", "_"), t)
    prim = next((f for f in files if f["directory"] in PRIMARY_DIRS), None)
    if prim:
        stem = prim["name"].rsplit(".", 1)[0]
        return ("f:" + stem.lower(), stem)
    return ("unknown", "unknown model")


def refusal_for(model_id: str, title: str, files: list) -> "str | None":
    hay = (model_id + " " + title + " " + " ".join(f["name"] for f in files)).lower()
    hay = hay.replace("_", "").replace("-", "").replace(" ", "")
    for key, why in REFUSED_MODELS.items():
        if key in hay:
            return why
    return None


def catalog() -> dict:
    """The dynamic model catalog: every template-native model the vendored registry can
    drive, grouped by upstream's own model name, each carrying its workflows and each
    workflow carrying its OWN required files with their real state.

    Re-read on every call, deliberately: a deleted file must drop off on the next poll,
    and a cache is a promise this surface cannot keep."""
    d = templates_dir()
    if d is None:
        return {"ok": False, "models": [], "templates": 0,
                "reason": ("the vendored comfyui-workflow-templates package is not in "
                           "this install, so no catalogue can be built")}
    rows = _index_rows()
    curated_by_template = {p["template"]: p for p in PICKS}
    groups: dict = {}
    scanned = 0
    for p in sorted(d.glob("*.json")):
        if p.name == "index.json":
            continue
        g = template_graph(p.stem)
        if not g or not g.get("nodes"):
            continue
        # THE ENTRY CONDITION IS THE REGISTRY, NOT THE FILE LIST: a template with no
        # `properties.models` at all is one of the ~440 that moved to the asset system,
        # which is DISABLED at our pin. Offering it would be offering a download we
        # cannot perform.
        if not any((n.get("properties") or {}).get("models") for n in g["nodes"]):
            continue
        files = workflow_files(p.stem, g)
        if not files:
            continue
        scanned += 1
        row = rows.get(p.stem) or {}
        mid, mtitle = model_key(row, files)
        pick = curated_by_template.get(p.stem)
        present = [f for f in files if f["present"]]
        missing = [f for f in files if not f["present"]]
        # A size we do not have is None, and the total is then None as well. A total
        # that silently counted the known half would read as a complete number.
        known = [f["bytes"] for f in missing if f["bytes"] is not None]
        missing_bytes = sum(known) if len(known) == len(missing) else None
        wf = {
            "id": p.stem,
            "template": p.stem,
            "title": row.get("title") or p.stem,
            "tags": _tags(row),
            "kind": workflow_kind(row, g),
            "files": files,
            "present_count": len(present), "file_count": len(files),
            "missing": [f["name"] for f in missing],
            "missing_bytes": missing_bytes,
            "missing_h": gb(missing_bytes) if missing_bytes is not None else None,
            "unknown_sizes": [f["name"] for f in missing if f["bytes"] is None],
            "no_url": [f["name"] for f in missing if not f["url"]],
            "complete": not missing,
            "set_bytes": row.get("size") if isinstance(row.get("size"), int) else None,
            "inputs": workflow_inputs(row, g),
            "curated_pick": pick["id"] if pick else None,
            "description": row.get("description") or "",
        }
        gp = groups.setdefault(mid, {
            "id": mid, "title": mtitle, "workflows": [], "curated": False,
            "kinds": set(), "files": {}})
        gp["workflows"].append(wf)
        gp["curated"] = gp["curated"] or bool(pick)
        gp["kinds"].add(wf["kind"])
        for f in files:
            gp["files"][(f["directory"], f["name"])] = f
    models = []
    for gp in groups.values():
        files = list(gp["files"].values())
        refused = refusal_for(gp["id"], gp["title"], files)
        wfs = sorted(gp["workflows"],
                     key=lambda w: (not w["complete"], -w["present_count"], w["title"]))
        models.append({
            "id": gp["id"], "title": gp["title"], "curated": gp["curated"],
            "kinds": sorted(gp["kinds"]),
            "workflows": wfs,
            "ready": sum(1 for w in wfs if w["complete"]),
            "workflow_count": len(wfs),
            # A model is INSTALLED when at least one of its workflows is complete —
            # that is the only definition under which "installed" means "press Generate
            # and it runs", which is what the word has to mean here.
            "installed": any(w["complete"] for w in wfs),
            "on_disk_bytes": sum(int(f["bytes"] or 0) for f in files if f["present"]),
            "refused": refused,
        })
    models.sort(key=lambda m: (not m["installed"], not m["curated"], m["title"].lower()))
    return {"ok": True, "models": models, "templates": scanned,
            "reason": None, "models_dir": str(models_dir())}


# ══ GRAPH BUILDERS — API format, stock nodes only ════════════════════════════
def _wan_length(frames: int) -> int:
    """Wan's latent temporal stride means the frame count must be 4n+1.

    ⚠️ AND WE DO NOT ASK (the autocorrect standard): "30 frames" rounds to the nearest
    legal 29 and the number used is SHOWN, rather than a modal about latent strides."""
    n = max(1, int(frames))
    if n == 1:
        return 1
    return max(5, ((n - 1 + 2) // 4) * 4 + 1)


def _dim(v: int, lo: int = 128, hi: int = 1280) -> int:
    """Clamp and snap to /16 — every one of these samplers wants a multiple of 16 and
    a graph that fails validation five seconds after Generate is a worse teacher than
    a field that quietly lands on 832."""
    n = int(v)
    n = max(lo, min(hi, n))
    return (n // 16) * 16 or lo


def build_graph(pick_id: str, mode: str, p: dict) -> dict:
    """The API-format graph for one job. Pure — no I/O, no network, fully testable.
    The slot-map pattern every automation frontend converged on (research §2.2): a fixed
    blessed graph with the user-facing values in named slots. Deliberately NOT SwarmUI's
    step-composed generator — a bigger product than these journeys need."""
    spec = PICK_BY_ID[pick_id]
    if mode not in spec["modes"]:
        raise ValueError(f"{spec['title']} cannot do {mode}")
    d = dict(spec["defaults"][mode])
    w = _dim(p.get("width") or d["width"])
    h = _dim(p.get("height") or d["height"])
    steps = max(1, min(100, int(p.get("steps") or d["steps"])))
    cfg_v = float(p.get("cfg") if p.get("cfg") is not None else d["cfg"])
    seed = int(p.get("seed"))
    pos = str(p.get("prompt") or "")
    neg = str(p.get("negative") if p.get("negative") is not None else spec["negative_default"])

    if spec["graph"] == "wan":
        f = spec["files"]
        length = 1 if mode == "image" else _wan_length(p.get("frames") or d.get("frames") or 33)
        g = {
            "37": {"class_type": "UNETLoader",
                   "inputs": {"unet_name": f[0]["name"], "weight_dtype": "default"}},
            "38": {"class_type": "CLIPLoader",
                   "inputs": {"clip_name": f[1]["name"], "type": "wan", "device": "default"}},
            "39": {"class_type": "VAELoader", "inputs": {"vae_name": f[2]["name"]}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": ["38", 0]}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": ["38", 0]}},
            "48": {"class_type": "ModelSamplingSD3",
                   "inputs": {"shift": 8.0, "model": ["37", 0]}},
            "40": {"class_type": "EmptyHunyuanLatentVideo",
                   "inputs": {"width": w, "height": h, "length": length, "batch_size": 1}},
            "3": {"class_type": "KSampler",
                  "inputs": {"seed": seed, "steps": steps, "cfg": cfg_v,
                             "sampler_name": "uni_pc", "scheduler": "simple",
                             "denoise": 1.0, "model": ["48", 0], "positive": ["6", 0],
                             "negative": ["7", 0], "latent_image": ["40", 0]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["39", 0]}},
        }
        if mode == "image":
            g["9"] = {"class_type": "SaveImage",
                      "inputs": {"images": ["8", 0], "filename_prefix": f"{OUT_PREFIX}/image"}}
        else:
            fps = float(p.get("fps") or d.get("fps") or 16)
            g["49"] = {"class_type": "CreateVideo",
                       "inputs": {"images": ["8", 0], "fps": fps}}
            g["50"] = {"class_type": "SaveVideo",
                       "inputs": {"video": ["49", 0], "format": "auto", "codec": "auto",
                                  "filename_prefix": f"{OUT_PREFIX}/video"}}
        return g

    # SDXL: CheckpointLoaderSimple carries model + clip + vae in one file.
    ck = spec["files"][0]["name"]
    return {
        "15": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ck}},
        "10": {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": ["15", 1]}},
        "11": {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": ["15", 1]}},
        "13": {"class_type": "EmptyLatentImage",
               "inputs": {"width": w, "height": h, "batch_size": 1}},
        "12": {"class_type": "KSampler",
               "inputs": {"seed": seed, "steps": steps, "cfg": cfg_v,
                          "sampler_name": "dpmpp_2m", "scheduler": "karras",
                          "denoise": 1.0, "model": ["15", 0], "positive": ["10", 0],
                          "negative": ["11", 0], "latent_image": ["13", 0]}},
        "14": {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["15", 2]}},
        "7": {"class_type": "SaveImage",
              "inputs": {"images": ["14", 0], "filename_prefix": f"{OUT_PREFIX}/image"}},
    }


def graph_classes(g: dict) -> set:
    return {str(n.get("class_type")) for n in g.values()}


def graph_steps(g: dict) -> "int | None":
    """The steps the graph WILL run — read back out of the BUILT graph, not the request,
    because the form clamps and a clamped value that disagrees with the card is a lie."""
    for n in g.values():
        if n.get("class_type") == "KSampler":
            return n["inputs"].get("steps")
    return None


def fence_violations(g: dict) -> list:
    """Classes outside the stock-node fence. Empty is the only shippable answer."""
    return sorted(graph_classes(g) - ALLOWED_NODES)


def stock_class(cls: str, info: dict) -> bool:
    """THE FENCE, DYNAMIC HALF. A discovered template may legitimately use any node that
    SHIPS WITH ComfyUI — WanImageToVideo, LoadVideo, Canny — and retyping that set here
    would be a list that is wrong the day after a component bump. So the question is
    asked of the running server instead, and it is the RIGHT question: /object_info's
    `python_module` says where a class came from, and everything from a third-party pack
    answers `custom_nodes.<pack>`. That is the supply-chain ruling (LLMVISION /
    Ultralytics) enforced against evidence rather than against a name."""
    spec = (info or {}).get(cls)
    if not isinstance(spec, dict):
        return False
    mod = str(spec.get("python_module") or "")
    return not mod.startswith("custom_nodes")


def dynamic_fence_violations(g: dict, info: dict) -> list:
    """API-graph classes that are absent from the server or come from a custom pack."""
    return sorted(c for c in graph_classes(g) if not stock_class(c, info))


# ── UI-format → API-format ───────────────────────────────────────────────────
# ⚠️ WHY THIS EXISTS AND WHY IT REFUSES RATHER THAN IMPROVISES. The vendored templates
# are UI graphs (litegraph: positional `widgets_values`, integer link ids); POST /prompt
# takes API graphs (named inputs, [node, slot] pairs). The conversion is mechanical ONLY
# when the running server can tell us each class's input ORDER, so /object_info is a
# hard requirement, not an optimisation. Everything this converter cannot do faithfully
# is a REFUSAL that names itself — a workflow that runs the wrong graph is the LIE class,
# and "open it in the ComfyUI tab" is always still there.
def _widget_type(t) -> bool:
    """Does this input type occupy a slot in `widgets_values`?

    ⚠️ THIS PREDICATE HAS BEEN WRONG TWICE, EACH TIME BY BEING AN ALLOW-LIST OF SPELLINGS
    RATHER THAN A RULE, and each time the symptom was values landing one slot to the
    left. One /object_info carries THREE spellings of "dropdown": a bare LIST of options
    (legacy), the literal string "COMBO" (the newer schema — WanCameraEmbedding's
    camera_pose), and "COMFY_DYNAMICCOMBO_V3" (the dynamic kind — SaveVideo's `format`
    and `codec`). Missing the second put a frame count into `speed`; missing the third
    submitted SaveVideo with no format at all and the run died 60 s in, after the
    sampling. So the test is now "any type whose name CONTAINS COMBO", plus the four
    scalars, plus the list form. Everything else — MODEL, CLIP, LATENT, VIDEO, IMAGE,
    CONDITIONING — is an edge, and edges do not sit in widgets_values."""
    if isinstance(t, list):
        return True
    t = str(t)
    return "COMBO" in t or t in ("INT", "FLOAT", "STRING", "BOOLEAN")


def _widget_names(spec: dict) -> list:
    """The input names that occupy `widgets_values`, in order, with the frontend's own
    control_after_generate slots accounted for.

    ⚠️ control_after_generate IS THE TRAP. A seed widget is followed in the UI by a
    hidden 'randomize'/'fixed' control whose value SITS IN widgets_values. Ignoring it
    shifts every later widget by one — silently, producing a graph that samples with
    steps=20 where the template said cfg=20. There is no error; there is just a wrong
    picture."""
    out = []
    for sect in ("required", "optional"):
        for name, ent in ((spec.get("input") or {}).get(sect) or {}).items():
            if not isinstance(ent, (list, tuple)) or not ent:
                continue
            t, opts = ent[0], (ent[1] if len(ent) > 1 and isinstance(ent[1], dict) else {})
            # ⚠️ A COMBO HAS TWO SPELLINGS IN ONE /object_info, AND MISSING THE SECOND
            # ONE SILENTLY SHIFTED EVERY LATER WIDGET BY ONE. Legacy nodes describe a
            # dropdown as a LIST of options (`["euler", "heun", …]`); nodes ported to
            # the newer schema describe it as the literal string "COMBO" with the
            # options moved into the opts dict. Treating only the list form as a widget
            # dropped `camera_pose` out of WanCameraEmbedding's slot list, so width took
            # "Zoom In", height took the width, and `speed` took the FRAME COUNT — 81
            # against a max of 10. ComfyUI's own validator caught that one because the
            # numbers were out of range; a template whose types happened to line up
            # would have produced a wrong picture in silence, which is the LIE class.
            # Found by walking a real discovered workflow, not by reading.
            is_widget = _widget_type(t)
            if not is_widget:
                continue
            out.append((name, opts))
            if opts.get("control_after_generate"):
                out.append((None, {}))        # the hidden control slot
    return out


def _required_widgets(spec: dict) -> list:
    """The REQUIRED inputs that are widgets — the ones a converted node must end up
    holding a value for, or the graph is not the graph the template describes."""
    out = []
    for name, ent in ((spec.get("input") or {}).get("required") or {}).items():
        if not isinstance(ent, (list, tuple)) or not ent:
            continue
        if _widget_type(ent[0]):
            out.append(name)
    return out


def _required_names(spec: dict) -> set:
    return set(((spec.get("input") or {}).get("required") or {}).keys())


def ui_to_api(g: dict, info: dict) -> dict:
    """{ok, graph, reason, widgets} — one vendored UI graph as a submittable API graph.

    `widgets` maps (node id → {widget name: value}) so the caller can find the prompt,
    the size and the seed without re-walking the template."""
    if not isinstance(g, dict) or not g.get("nodes"):
        return {"ok": False, "graph": {}, "reason": "the template file is not a graph",
                "widgets": {}}
    if not info:
        return {"ok": False, "graph": {}, "widgets": {},
                "reason": ("ComfyUI is not answering, and converting a template needs "
                           "its node definitions — start the engine and try again")}
    links = _links_map(g)
    active = _active_nodes(g)
    keep = {n.get("id") for n in active}
    by_id = {n.get("id"): n for n in (g.get("nodes") or [])}
    unknown = sorted({str(n.get("type")) for n in active if str(n.get("type")) not in info})
    if unknown:
        # ⚠️ A UUID-SHAPED CLASS IS A SUBGRAPH, NOT A MISSING NODE, and saying "this
        # ComfyUI does not have 27eacb9f-…" would send the reader hunting for a node
        # pack that does not exist. Newer templates wrap whole sections in a subgraph
        # whose definition sits in the file's own `definitions.subgraphs`; expanding
        # those faithfully is a second converter, and until it exists the honest answer
        # names the reason and points at the editor that already understands them.
        subs = {str(d.get("id")) for d in
                ((g.get("definitions") or {}).get("subgraphs") or [])}
        if subs and any(u in subs for u in unknown):
            return {"ok": False, "graph": {}, "widgets": {},
                    "reason": ("this template is built out of SUBGRAPHS, which this "
                               "surface does not expand — open it in the ComfyUI tab, "
                               "where they run as they were authored")}
        return {"ok": False, "graph": {}, "widgets": {},
                "reason": ("this ComfyUI does not have " + ", ".join(unknown[:4])
                           + " — the template needs a node this engine cannot run")}

    def resolve(lid, depth=0):
        """Where does this edge REALLY come from?

        ⚠️ THREE FRONTEND CONSTRUCTS SIT BETWEEN THE ANSWER AND THE NAIVE READ, and each
        one is a different rule, not a variation of one rule. (1) A PrimitiveNode is not
        a node at all — it is a widget value drawn outside its node, so the edge
        resolves to a LITERAL and four stock SDXL templates depend on it. (2) mode 4 is
        BYPASS, not mute: ComfyUI routes the node's inputs to its outputs BY TYPE and
        carries on, which is the only reason `video_wan2.1_alpha_t2v_14B`'s sampler has
        a model at all once its optional LoRA is bypassed. (3) mode 2 is a real mute and
        resolves to nothing. Treating all three as "gone" refused four workflows that
        run perfectly in ComfyUI's own editor — found by converting all 78 and reading
        the refusals rather than by trusting the first two that worked."""
        if depth > 12:
            return None
        src = links.get(lid)
        if not src:
            return None
        oid, oslot = src
        if oid in keep:
            return ("link", str(oid), int(oslot or 0))
        node = by_id.get(oid)
        if not node:
            return None
        cls = str(node.get("type") or "")
        if cls in ("PrimitiveNode", "PrimitiveInt", "PrimitiveFloat", "PrimitiveString"):
            vals = node.get("widgets_values") or []
            return ("literal", vals[0], None) if vals else None
        if node.get("mode") == 4 or cls == "Reroute":
            outs = node.get("outputs") or []
            want = (outs[oslot] or {}).get("type") if oslot is not None and oslot < len(outs) else None
            for slot in (node.get("inputs") or []):
                if slot.get("link") is None:
                    continue
                if want in (None, slot.get("type")) or cls == "Reroute":
                    return resolve(slot["link"], depth + 1)
        return None

    out, widgets = {}, {}
    for n in active:
        cls = str(n.get("type"))
        spec = info[cls]
        names = _widget_names(spec)
        vals = list(n.get("widgets_values") or [])
        # A dict-shaped widgets_values (the newest frontend writes one for a few nodes)
        # is already keyed, so it needs no positional walk at all.
        wmap = {}
        if isinstance(n.get("widgets_values"), dict):
            wmap = {k: v for k, v in n["widgets_values"].items() if k in _required_names(spec)
                    or k in ((spec.get("input") or {}).get("optional") or {})}
        else:
            for i, (nm, opts) in enumerate(names):
                if nm is None:
                    continue
                if i < len(vals):
                    wmap[nm] = vals[i]
                elif "default" in opts:
                    # ⚠️ A TEMPLATE AUTHORED BEFORE THE NODE GREW A PARAMETER ends its
                    # widgets_values early, and ComfyUI's own editor fills the tail from
                    # the node's defaults — so we do too, or three stock templates
                    # (ImageScaleToTotalPixels, TextEncodeAceStepAudio1.5) would be
                    # refused for running exactly as upstream ships them. THE TAIL IS
                    # THE ONLY PLACE THIS APPLIES: a value missing from the MIDDLE of the
                    # list is a layout disagreement, and the guard below still refuses
                    # it rather than papering over it with a plausible default — that
                    # distinction is what keeps the WanCameraEmbedding bug caught.
                    wmap[nm] = opts["default"]
        inputs = dict(wmap)
        # links override widgets: a converted widget is fed by an edge, not by its value
        req = _required_names(spec)
        for slot in (n.get("inputs") or []):
            lid = slot.get("link")
            nm = slot.get("name")
            if lid is None or nm is None:
                continue
            r = resolve(lid)
            if r is None:
                # THE MUTED-UPSTREAM CASE. ComfyUI treats a muted node as not connected,
                # so an OPTIONAL input simply goes away — that is what makes the ti2v
                # template a text-to-video workflow as shipped. A REQUIRED input fed by
                # a muted node cannot be honestly resolved, so the workflow is refused.
                if nm in req:
                    return {"ok": False, "graph": {}, "widgets": {},
                            "reason": (f"the template feeds {cls}.{nm} from a node it "
                                       f"ships muted — that cannot be converted "
                                       f"faithfully; open it in the ComfyUI tab")}
                inputs.pop(nm, None)
                continue
            if r[0] == "literal":
                inputs[nm] = r[1]
                wmap[nm] = r[1]
            else:
                inputs[nm] = [r[1], r[2]]
        # ⚠️ THE ALIGNMENT GUARD, AND IT IS THE REASON THE BUG ABOVE CAN ONLY HAPPEN
        # ONCE. Positional widget mapping is only correct while our slot list and the
        # frontend's agree; when they drift, the failure is silent and the graph is
        # wrong. So the invariant is asserted rather than hoped for: every REQUIRED
        # widget of every node must come out of the walk holding a value (or a link).
        # A miss means the layouts disagree, and a workflow we cannot convert faithfully
        # is REFUSED by name — never submitted with values in the wrong slots.
        blank = [nm for nm in _required_widgets(spec) if nm not in inputs]
        if blank:
            return {"ok": False, "graph": {}, "widgets": {},
                    "reason": (f"{cls} would be submitted without {', '.join(blank[:3])} "
                               f"— this template's widget layout does not line up with "
                               f"this engine's definition of the node, so converting it "
                               f"would put values in the wrong slots. Open it in the "
                               f"ComfyUI tab.")}
        out[str(n.get("id"))] = {"class_type": cls, "inputs": inputs,
                                 "_meta": {"title": n.get("title") or cls}}
        widgets[str(n.get("id"))] = wmap
    if not out:
        return {"ok": False, "graph": {}, "widgets": {},
                "reason": "every node in this template is muted"}
    return {"ok": True, "graph": out, "widgets": widgets, "reason": None}


# The widgets a person actually turns, and where they live in the converted graph. Read
# off the graph itself: a control we cannot find is a control the page does not draw,
# which is why a template with no negative prompt shows no negative prompt field.
CONTROL_WIDGETS = {
    "width": "width", "height": "height", "length": "length", "steps": "steps",
    "cfg": "cfg", "seed": "seed", "noise_seed": "seed", "fps": "fps",
    "batch_size": "batch_size",
}
SAMPLER_CLASSES = ("KSampler", "KSamplerAdvanced", "SamplerCustom",
                   "SamplerCustomAdvanced")
# The controls a graph may state in more than one place, where the copies MUST agree.
SHARED_CONTROLS = ("width", "height", "length", "fps", "batch_size")


def _walk_back(api: dict, node_id: str, slot_name: str, want: str, depth: int = 6):
    """Follow one input backwards until a node of class `want` is found. The prompt is
    rarely wired straight into the sampler — Wan's control workflows put
    WanFunControlToVideo in between — so "the positive CLIPTextEncode" is a SEARCH, not
    an assumption about graph shape."""
    seen, frontier = set(), [(node_id, slot_name)]
    for _ in range(depth):
        nxt = []
        for nid, nm in frontier:
            node = api.get(nid)
            if not node:
                continue
            v = node["inputs"].get(nm) if nm else None
            cands = [v] if isinstance(v, list) else (
                [x for x in node["inputs"].values() if isinstance(x, list)] if nm is None else [])
            for c in cands:
                tgt = str(c[0])
                if tgt in seen:
                    continue
                seen.add(tgt)
                t = api.get(tgt)
                if not t:
                    continue
                if t["class_type"] == want:
                    return tgt
                nxt.append((tgt, None))
        frontier = nxt
        if not frontier:
            break
    return None


def workflow_controls(api: dict, widgets: dict) -> dict:
    """{control name: {node, widget}} for the knobs this workflow really takes."""
    out: dict = {}
    for nid, node in api.items():
        cls = node["class_type"]
        for w, val in (widgets.get(nid) or {}).items():
            key = CONTROL_WIDGETS.get(w)
            if not key:
                continue
            if key in out:
                # ⚠️ A SHAPE CONTROL BELONGS TO EVERY NODE THAT CARRIES IT, AND THIS IS
                # A CORRECTNESS RULE RATHER THAN A CONVENIENCE. Wan's camera workflow
                # states the frame count TWICE — once on WanCameraEmbedding and once on
                # the video node — and the two must agree or the run is wrong or
                # refused. Setting only the first is how "21 frames" becomes a graph
                # that embeds a camera path for 81. Seed / steps / cfg stay
                # single-owner: those genuinely belong to one sampler.
                if key in SHARED_CONTROLS:
                    out[key].setdefault("also", []).append({"node": nid, "widget": w})
                continue
            out[key] = {"node": nid, "widget": w, "class": cls, "default": val}
    sampler = next((nid for nid, n in api.items()
                    if n["class_type"] in SAMPLER_CLASSES), None)
    if sampler:
        pos = _walk_back(api, sampler, "positive", "CLIPTextEncode")
        neg = _walk_back(api, sampler, "negative", "CLIPTextEncode")
        if pos:
            out["prompt"] = {"node": pos, "widget": "text", "class": "CLIPTextEncode",
                             "default": (widgets.get(pos) or {}).get("text", "")}
        if neg and neg != pos:
            out["negative"] = {"node": neg, "widget": "text", "class": "CLIPTextEncode",
                               "default": (widgets.get(neg) or {}).get("text", "")}
    else:
        # No recognised sampler: the FIRST CLIPTextEncode is still the prompt, and a
        # second one is still the negative. Two encoders, in graph order, is the shape
        # every one of these templates has.
        encs = [nid for nid, n in api.items() if n["class_type"] == "CLIPTextEncode"]
        if encs:
            out["prompt"] = {"node": encs[0], "widget": "text", "class": "CLIPTextEncode",
                             "default": (widgets.get(encs[0]) or {}).get("text", "")}
        if len(encs) > 1:
            out["negative"] = {"node": encs[1], "widget": "text",
                               "class": "CLIPTextEncode",
                               "default": (widgets.get(encs[1]) or {}).get("text", "")}
    for nid, node in api.items():
        if node["class_type"] in ("LoadImage", "LoadImageMask") and "image" not in out:
            out["image"] = {"node": nid, "widget": "image", "class": node["class_type"],
                            "default": (widgets.get(nid) or {}).get("image", "")}
        if node["class_type"] == "LoadVideo" and "video" not in out:
            out["video"] = {"node": nid, "widget": "file", "class": "LoadVideo",
                            "default": (widgets.get(nid) or {}).get("file", "")}
        if node["class_type"] == "LoadAudio" and "audio" not in out:
            out["audio"] = {"node": nid, "widget": "audio", "class": "LoadAudio",
                            "default": (widgets.get(nid) or {}).get("audio", "")}
    return out


SAVE_PREFIX = {"SaveImage": "image", "SaveVideo": "video", "SaveAnimatedWEBP": "video",
               "SaveAnimatedPNG": "video", "SaveAudio": "audio", "SaveAudioMP3": "audio",
               "SaveAudioOpus": "audio", "SaveWEBM": "video", "SaveGLB": "model"}


def retarget_outputs(api: dict) -> int:
    """Every Save* node writes under <output>/harness/, like the curated builders do.

    Without this a discovered workflow's result lands loose in ComfyUI's output root,
    where our gallery deliberately does not look — the run would succeed and the page
    would show nothing, which reads as a failure that produced no error."""
    n = 0
    for node in api.values():
        kind = SAVE_PREFIX.get(node["class_type"])
        if kind and "filename_prefix" in node["inputs"]:
            node["inputs"]["filename_prefix"] = f"{OUT_PREFIX}/{kind}"
            n += 1
    return n


def apply_controls(api: dict, controls: dict, params: dict) -> dict:
    """Put the user's values into the converted graph, and REPORT what was used.

    Only controls the workflow actually has are applied — a value for a knob this
    template does not carry is dropped rather than injected into a node that would then
    fail validation five seconds after the click."""
    used = {}
    for key, spec in controls.items():
        if key in ("image", "video", "audio"):
            continue
        if key not in params or params[key] is None or params[key] == "":
            continue
        targets = [spec] + list(spec.get("also") or [])
        v = params[key]
        if key in ("width", "height"):
            v = _dim(v)
        elif key == "length":
            v = _wan_length(v)
        elif key == "steps":
            v = max(1, min(200, int(v)))
        elif key in ("cfg", "fps"):
            v = float(v)
        elif key == "seed":
            v = int(v)
        elif key in ("prompt", "negative"):
            v = str(v)
        wrote = False
        for t in targets:
            node = api.get(t["node"])
            if node is None:
                continue
            # A slot fed by a LINK is not ours to overwrite: replacing an edge with a
            # literal would quietly cut the graph in half.
            if isinstance(node["inputs"].get(t["widget"]), list):
                continue
            node["inputs"][t["widget"]] = v
            wrote = True
        if wrote:
            used[key] = v
    return used


_measure_load()
sizes_load()
