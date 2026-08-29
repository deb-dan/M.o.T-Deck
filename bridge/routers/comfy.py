"""ROUTER — the ComfyUI first-party GENERATE surface (S1: image + video).

Spec: docs/FABLE-COMFY-SURFACE-SPEC.md · research: docs/research/2026-08-29-comfyui-tab.md.
The page is bridge/panel/comfy.html at GET /comfy; everything below it is /api/comfy/*.

WHAT THIS LANE IS FOR (obligation 1). Type a sentence, get a picture or a short clip,
without learning node graphs — with honest numbers (disk, minutes, memory) BEFORE
committing, and the stock ComfyUI tab left intact as the power exit. Deliberately NOT a
workflow editor, a custom-node manager or an arbitrary-URL downloader.

⚠️ FIVE THINGS THE NEXT READER MUST NOT RE-DERIVE ────────────────────────────────────

1. THE PATHS ARE THE APP'S, NOT THE REPO'S. A repo checkout has no data/comfyui; the
   running instance belongs to the SHIPPED app. Everything resolves off ROOT.

2. THE CURATION IS GENERATED, NOT TYPED. The per-model FILE LIST is read at runtime out
   of the vendored `comfyui-workflow-templates` registry (loader nodes carry
   `properties.models[] = {name, url, directory}`). PICKS carries only what the registry
   does NOT know: the HEAD-verified size, the sha256 (HF's LFS metadata), the licence we
   READ, and which builder consumes it. If the two disagree after a pin bump the card
   says `registry_drift` rather than downloading yesterday's file.

3. SIZE AND SHA ARE CHECKED, AND A FAILED CHECK IS NOT A DOWNLOAD. A card claiming
   "downloaded" over a truncated file resurfaces hours later as an inscrutable ComfyUI
   error, so the .part is renamed only after BOTH the byte count and the sha256 match.

4. THE DISK VERDICT COMES FROM THE MODELS DIRECTORY ITSELF — not ROOT, not "/". Here
   "/" is the sealed system volume and the data volume is a different filesystem, so
   statvfs'ing the wrong one is a confidently wrong number (the LIE class).

5. EVERY GATE HERE IS ADVISORY (Debi's 2026-08-28 ruling): numbers and a
   recommendation, never a disabled button. The only refusals are for things that
   cannot work at all (a missing model file, ComfyUI down), each naming its own fix.

STOCK NODES ONLY (the supply-chain fence, research §4.1: the ComfyUI_LLMVISION and
Ultralytics incidents). Every class_type this file emits is in ALLOWED_NODES, all of
which ship with ComfyUI; `custom_nodes/` stays empty, and test_comfy_lane.py fails if
a builder ever emits a class outside that set.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from pathlib import Path

import httpx
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, Response

from ..core.appctx import PANEL, ROOT, app
from ..core.events import publish
from ..core.procs import cfg

# ── constants ────────────────────────────────────────────────────────────────
COMFY_DEFAULT_PORT = 8188       # harness.yaml components.comfyui.port overrides it
DL_TICK_S = 2.0                 # SSE progress cadence — the downloads lane's number
JOB_TICK_S = 1.0                # queue/progress poll cadence while a job is live
DISK_HEADROOM = 2 * 1024 ** 3   # "leaves ~X" is measured against this reserve
STARTER_CAP_BYTES = 14_000_000_000   # Debi's locked S1 budget, DECIMAL GB (the unit
                                     # HuggingFace, `df -h` and model cards all use)

# <output>/harness/ is ours; anything else there came from the ComfyUI tab, untouched.
OUT_PREFIX = "harness"

# ⚠️ THE STOCK-NODE FENCE: every class the builders may emit. Adding one is deliberate,
# and it must ship with ComfyUI rather than with a custom pack.
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


def comfy_port() -> int:
    try:
        c = (cfg().get("components") or {}).get("comfyui") or {}
        return int(c.get("port") or COMFY_DEFAULT_PORT)
    except Exception:                                            # noqa: BLE001
        return COMFY_DEFAULT_PORT


def comfy_url(path: str = "") -> str:
    return f"http://127.0.0.1:{comfy_port()}{path}"


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
    shared encoder twice and a naive read double-counts 6.7 GB."""
    d = templates_dir()
    if d is None:
        return None
    p = d / f"{name}.json"
    try:
        g = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
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


def comfy_pid() -> "int | None":
    try:
        v = int((ROOT / "data" / "comfyui.pid").read_text().strip())
    except (OSError, ValueError):
        return None
    return v if v > 0 else None


def _footprint(pid: "int | None") -> "int | None":
    """ComfyUI's phys_footprint right now, or None if we cannot see the process."""
    if not pid:
        return None
    try:
        from ..core import memory as _mem
        r = _mem.proc_footprint(int(pid))
    except Exception:                                            # noqa: BLE001
        return None
    return int(r["footprint"]) if r else None


def measure_note(pick_id: str, mode: str) -> str:
    m = (MEASURED.get(pick_id) or {}).get(mode)
    if not m:
        return "not measured on this Mac yet — the next run is the measurement"
    return (f"last run: {m['wall_s']:.0f}s · peaked {gb(m['peak_bytes'])}"
            + (f" · {m['label']}" if m.get("label") else ""))


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


# ══ THE COMFYUI CLIENT ═══════════════════════════════════════════════════════
_CX = httpx.AsyncClient(timeout=httpx.Timeout(10, read=30))
_DL = httpx.AsyncClient(timeout=httpx.Timeout(30, read=120), follow_redirects=True)


async def _cget(path: str, timeout: float = 6.0):
    r = await _CX.get(comfy_url(path), timeout=timeout)
    r.raise_for_status()
    return r.json()


async def comfy_state() -> dict:
    """Reachable? version? pid? NEVER raises — the page must render regardless."""
    out = {"up": False, "port": comfy_port(), "url": comfy_url(), "pid": comfy_pid(),
           "version": None, "error": None, "custom_nodes": None}
    try:
        st = await _cget("/system_stats")
        sysd = st.get("system") or {}
        out.update(up=True, version=sysd.get("comfyui_version"),
                   templates_version=sysd.get("installed_templates_version"),
                   torch=sysd.get("pytorch_version"))
    except Exception as e:                                       # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"[:200]
    # The supply-chain fence, REPORTED rather than merely tested: S1–S3 ship with zero.
    try:
        cn = comfy_base() / "custom_nodes"
        out["custom_nodes"] = sorted(
            d.name for d in cn.iterdir()
            if d.is_dir() and not d.name.startswith((".", "__")))
    except OSError:
        out["custom_nodes"] = []
    return out


async def validate_pick(pick_id: str, mode: str) -> dict:
    """CONNECT-TIME VALIDATION — the Krita-plugin discipline, before submit.

    Three checks against the LIVE server, each failure named with its own fix: is
    ComfyUI up; does every node class exist in /object_info (the stock-node fence,
    verified against the running server rather than assumed); is every model file in
    /models/{folder} — the SERVER's view, not our stat(). ⚠️ WHY NOT JUST LET POST
    /prompt FAIL: it would (`node_errors` is authoritative and we surface it too) but
    AFTER the click, in a payload shaped for a graph editor, and it cannot say "press
    Download on the Wan card"."""
    spec = PICK_BY_ID.get(pick_id)
    if spec is None:
        return {"ok": False, "reason": "unknown model", "missing_models": [],
                "missing_nodes": []}
    graph = build_graph(pick_id, mode, {"seed": 0, "prompt": "x"})
    out = {"ok": False, "pick": pick_id, "mode": mode, "missing_nodes": [],
           "missing_models": [], "reason": None,
           "fence_violations": fence_violations(graph)}
    try:
        info = await _cget("/object_info", timeout=20.0)
    except Exception as e:                                       # noqa: BLE001
        out["reason"] = (f"ComfyUI is not answering on {comfy_url()} "
                         f"({type(e).__name__}). Start it from MOT Deck → Components.")
        return out
    have = set(info or {})
    out["missing_nodes"] = sorted(c for c in graph_classes(graph) if c not in have)
    # /models/{folder} is the server's own listing — an empty/500 answer is treated as
    # "cannot confirm", and we fall back to our own stat() rather than inventing a
    # refusal for a model that is sitting right there.
    _busy = cdl_inflight(pick_id)
    for f in spec["files"]:
        seen = None
        try:
            seen = await _cget(f"/models/{f['directory']}")
        except Exception:                                        # noqa: BLE001
            seen = None
        st = _file_state(f)
        if seen is not None:
            ok = f["name"] in (seen or [])
        else:
            ok = st["present"]
        if not ok or st["state"] == "corrupt":
            out["missing_models"].append({
                "directory": f["directory"], "name": f["name"],
                "bytes": f["bytes"], "size_h": gb(f["bytes"]),
                "state": st["state"], "pick": pick_id, "pick_title": spec["title"],
                # ⚠️ "PRESS DOWNLOAD" WHILE IT IS DOWNLOADING IS A SMALL LIE, and this is
                # the likeliest moment to hit the refusal. Say what is happening instead.
                "how": ((f"“{spec['title']}” is downloading right now "
                         f"({_cdl_json(_busy)['pct']}% of {_cdl_json(_busy)['total_h']}) "
                         f"— this will work as soon as it lands.") if _busy else
                        f"Download “{spec['title']}” on the Models card above — it puts "
                        f"{f['name']} in models/{f['directory']}/."),
            })
    if out["missing_nodes"]:
        out["reason"] = ("this ComfyUI is missing node classes this graph needs: "
                         + ", ".join(out["missing_nodes"])
                         + ". That should be impossible on a stock v0.34.x — check the "
                           "component install.")
    elif out["missing_models"]:
        names = ", ".join(m["name"] for m in out["missing_models"])
        out["reason"] = f"missing model file(s): {names}"
    elif out["fence_violations"]:
        out["reason"] = ("this graph would use non-stock nodes ("
                         + ", ".join(out["fence_violations"]) + ") — refused.")
    else:
        out["ok"] = True
    return out


# ══ DOWNLOADS — resumable, size- AND sha-verified ════════════════════════════
CDL: dict = {}
_CDL_SEQ = {"n": 0}


def _cdl_json(e: dict) -> dict:
    out = {k: v for k, v in e.items() if k != "task"}
    done = sum(int(f.get("done") or 0) for f in e["files"])
    total = sum(int(f["bytes"]) for f in e["files"])
    out["done_bytes"], out["total_bytes"] = done, total
    out["pct"] = round(100.0 * done / total, 1) if total else 0.0
    out["done_h"], out["total_h"] = gb(done), gb(total)
    return out


async def _sha256(path: Path) -> str:
    """Hash a multi-GB file WITHOUT blocking the event loop.

    ⚠️ NOT INLINE: hashing 6.7 GB on the loop would freeze every other bridge route for
    the duration, which reads as "the app hung mid-download"."""
    def _run() -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 22), b""):
                h.update(chunk)
        return h.hexdigest()
    return await asyncio.to_thread(_run)


async def _run_cdl(dl_id: str) -> None:
    e = CDL.get(dl_id)
    if not e:
        return
    last_push = 0.0
    try:
        for f in e["files"]:
            dest = Path(f["dest"])
            part = Path(str(dest) + ".part")
            want = int(f["bytes"])
            if dest.exists() and dest.stat().st_size == want:
                f["done"], f["state"] = want, "present"
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            have = part.stat().st_size if part.exists() else 0
            if have > want:                    # a stale .part from another pin
                part.unlink()
                have = 0
            f["done"] = have
            headers = {"Range": f"bytes={have}-"} if have else {}
            async with _DL.stream("GET", f["url"], headers=headers) as resp:
                if resp.status_code not in (200, 206):
                    body = ""
                    try:
                        body = (await resp.aread())[:200].decode("utf-8", "replace")
                    except Exception:                            # noqa: BLE001
                        pass
                    e.update(state="error",
                             error=f"HTTP {resp.status_code} fetching {f['name']}: {body}"[:300])
                    publish("comfy", what="download", id=dl_id, state="error")
                    return
                # A 200 answering a Range request means the range was ignored:
                # appending would splice the head into the middle. Restart the file.
                mode = "ab" if (have and resp.status_code == 206) else "wb"
                if mode == "wb":
                    f["done"] = have = 0
                # THE SIZE PIN, BEFORE A BYTE IS WRITTEN. content-length on a 206 is
                # the REMAINDER, so the whole-file size is have + length.
                try:
                    clen = int(resp.headers.get("content-length") or 0)
                except ValueError:
                    clen = 0
                if clen and (have + clen) != want:
                    e.update(state="error",
                             error=(f"{f['name']}: upstream says {gb(have + clen)} "
                                    f"({have + clen} B) but our pin is {gb(want)} "
                                    f"({want} B). The model file changed upstream — "
                                    f"refusing to download something we cannot verify. "
                                    f"Re-run the curation pass."))
                    publish("comfy", what="download", id=dl_id, state="error")
                    return
                with open(part, mode) as out:
                    async for chunk in resp.aiter_bytes(1 << 20):
                        if e["state"] == "cancelled":
                            break
                        if e["state"] == "paused":
                            return                       # .part survives; resume re-streams
                        out.write(chunk)
                        f["done"] += len(chunk)
                        now = time.time()
                        if now - last_push >= DL_TICK_S:
                            last_push = now
                            publish("comfy", what="download", id=dl_id, state="downloading")
            if e["state"] == "cancelled":
                break
            # ⚠️ THE VERIFY GATE: until BOTH pass the file keeps its .part name, so the
            # card never says "downloaded" and ComfyUI never sees a bad file.
            got = part.stat().st_size
            if got != want:
                e.update(state="error",
                         error=(f"{f['name']}: got {gb(got)} ({got} B), expected "
                                f"{gb(want)} ({want} B). Left as .part — press Retry."))
                publish("comfy", what="download", id=dl_id, state="error")
                return
            f["state"] = "verifying"
            publish("comfy", what="download", id=dl_id, state="verifying")
            digest = await _sha256(part)
            if digest != f["sha256"]:
                e.update(state="error",
                         error=(f"{f['name']}: sha256 {digest[:12]}… does not match the "
                                f"pinned {f['sha256'][:12]}…. The bytes are not the file "
                                f"we curated. Left as .part; delete it and retry."))
                publish("comfy", what="download", id=dl_id, state="error")
                return
            os.replace(part, dest)
            f["state"] = "present"
        if e["state"] == "cancelled":
            publish("comfy", what="download", id=dl_id, state="cancelled")
            return
        e["state"] = "done"
        publish("comfy", what="download", id=dl_id, state="done")
    except Exception as ex:                                      # noqa: BLE001
        e.update(state="error", error=f"{type(ex).__name__}: {ex}"[:300])
        publish("comfy", what="download", id=dl_id, state="error")


def cdl_inflight(pick_id: str):
    for e in CDL.values():
        if e.get("pick") == pick_id and e.get("state") in ("downloading", "paused"):
            return e
    return None


# A .part written within this many seconds is being written BY SOMEBODY, and CDL is not
# who. 30s is generous against a slow CDN stall and short enough that a genuinely
# abandoned .part is resumable within a minute.
LIVE_PART_S = 30.0


def foreign_writer(spec: dict) -> "str | None":
    """Is another PROCESS writing this model's .part right now?

    ⚠️ FOUND BY WALKING, NOT BY THINKING — the corruption case `cdl_inflight` cannot see.
    A bridge restart mid-download leaves the OLD process's task alive and still
    appending while the NEW one starts with an empty CDL whose duplicate guard says
    "nothing in flight"; both append, and only the sha catches it, an hour later. The
    .part's MTIME is the evidence, and it needs no cross-process bookkeeping."""
    for f in spec["files"]:
        part = models_dir() / f["directory"] / (f["name"] + ".part")
        try:
            age = time.time() - part.stat().st_mtime
        except OSError:
            continue
        if age < LIVE_PART_S:
            return (f"{f['name']} is being written right now (its .part was touched "
                    f"{age:.0f}s ago) — most likely by a bridge that was restarted "
                    f"mid-download. Wait a moment and press Refresh; if nothing moves "
                    f"for a minute the .part is stale and this will resume it.")
    return None


@app.get("/comfy")
def comfy_page() -> FileResponse:
    """The Generate tab's own document — not the panel (the /aider + /office
    precedent): it must not carry the panel's poll loops."""
    return FileResponse(
        PANEL / "comfy.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate",
                 "Pragma": "no-cache"})


@app.get("/api/comfy/state")
async def api_comfy_state() -> JSONResponse:
    """Everything the page needs for a full render, in ONE request — the empty state,
    the cards, the disk strip and the gallery total all have to agree, and independent
    fetches can disagree mid-download."""
    st = await comfy_state()
    cur = curation()
    gal = gallery()
    return JSONResponse({
        "ok": True, "comfy": st, "curation": cur,
        "downloads": [_cdl_json(e) for e in CDL.values()],
        "jobs": [_job_json(j) for j in JOBS.values()],
        "gallery_total_bytes": gal["total_bytes"],
        "gallery_total_h": gb(gal["total_bytes"]),
        "gallery_count": len(gal["items"]),
        "output_dir": str(output_dir()),
        "measure": MEASURED,
        "fence": {"allowed_nodes": sorted(ALLOWED_NODES),
                  "custom_nodes": st.get("custom_nodes") or []},
    })


@app.post("/api/comfy/download")
async def api_comfy_download(req: Request) -> JSONResponse:
    body = await req.json()
    pick_id = str((body or {}).get("pick") or "")
    spec = PICK_BY_ID.get(pick_id)
    if spec is None:
        return JSONResponse({"ok": False, "error": "unknown model"}, status_code=400)
    dup = cdl_inflight(pick_id)
    if dup:
        # Two clicks must not become two writers on one .part: the second JOINS.
        return JSONResponse({"ok": True, "download": _cdl_json(dup), "joined": True})
    busy = foreign_writer(spec)
    if busy:
        return JSONResponse({"ok": False, "error": busy}, status_code=409)
    card = pick_card(spec)
    files = []
    for f, state in zip(spec["files"], card["files"]):
        if state["present"]:
            continue
        url = state.get("url")
        if not url:
            return JSONResponse(
                {"ok": False, "error": (
                    f"no download URL for {f['name']}: the vendored workflow-templates "
                    f"registry did not list it. This is the registry-drift case — the "
                    f"curation pass must be re-run against this pin.")}, status_code=409)
        files.append({"directory": f["directory"], "name": f["name"],
                      "bytes": int(f["bytes"]), "sha256": f["sha256"], "url": url,
                      "dest": str(models_dir() / f["directory"] / f["name"]),
                      "done": 0, "state": "queued"})
    if not files:
        return JSONResponse({"ok": True, "download": None,
                             "note": "every file is already on disk"})
    _CDL_SEQ["n"] += 1
    dl_id = f"c{_CDL_SEQ['n']}"
    e = {"id": dl_id, "pick": pick_id, "title": spec["title"], "files": files,
         "state": "downloading", "error": None, "started": time.time(), "task": None}
    CDL[dl_id] = e
    e["task"] = asyncio.create_task(_run_cdl(dl_id))
    publish("comfy", what="download", id=dl_id, state="downloading")
    return JSONResponse({"ok": True, "download": _cdl_json(e)})


@app.post("/api/comfy/download/{dl_id}/cancel")
async def api_comfy_download_cancel(dl_id: str) -> JSONResponse:
    e = CDL.get(dl_id)
    if not e:
        return JSONResponse({"ok": False, "error": "no such download"}, status_code=404)
    e["state"] = "cancelled"
    # The .part is DELIBERATELY KEPT — a cancelled 9 GB download resumed tomorrow must
    # not start from zero — and `_file_state` reports it as `partial`, not present.
    publish("comfy", what="download", id=dl_id, state="cancelled")
    return JSONResponse({"ok": True, "download": _cdl_json(e)})


@app.get("/api/comfy/downloads")
async def api_comfy_downloads() -> JSONResponse:
    return JSONResponse({"ok": True, "downloads": [_cdl_json(e) for e in CDL.values()]})


@app.post("/api/comfy/validate")
async def api_comfy_validate(req: Request) -> JSONResponse:
    body = await req.json()
    v = await validate_pick(str((body or {}).get("pick") or ""),
                            str((body or {}).get("mode") or "image"))
    return JSONResponse({"ok": True, "validation": v})


# ══ JOBS — submit, follow, recover ═══════════════════════════════════════════
JOBS: dict = {}


def _job_json(j: dict) -> dict:
    return {k: v for k, v in j.items() if k not in ("task", "graph")}


def _job_note(j: dict) -> str:
    if j["state"] == "running":
        if j.get("step") and j.get("step_max"):
            return f"step {j['step']}/{j['step_max']}"
        return "running"
    return j["state"]


async def _follow(job_id: str) -> None:
    """Follow one job: the websocket for step-granular progress, /history as the truth
    about what came out, and a footprint sample every tick. ⚠️ THE WEBSOCKET IS THE
    NICE-TO-HAVE AND /history IS THE CONTRACT — a dropped ws costs the progress bar,
    never the RESULT, so /history is re-polled unconditionally and the ws read
    opportunistically ("ws drop degrades to polling, silently")."""
    j = JOBS.get(job_id)
    if not j:
        return
    pid = comfy_pid()
    peak = _footprint(pid) or 0
    t0 = time.time()
    ws = None
    try:
        import websockets                                        # declared in requirements
        ws = await asyncio.wait_for(
            websockets.connect(f"ws://127.0.0.1:{comfy_port()}/ws?clientId={j['client_id']}"),
            timeout=5)
    except Exception:                                            # noqa: BLE001
        j["ws"] = False
    else:
        j["ws"] = True
    try:
        while True:
            if j["state"] in ("done", "error", "cancelled"):
                break
            if time.time() - t0 > 3 * 3600:
                j.update(state="error", error="gave up following after 3 hours")
                break
            # 1) footprint sample — the measured peak this run is credited with.
            f = _footprint(pid)
            if f:
                peak = max(peak, f)
                j["peak_bytes"] = peak
            # 2) websocket drain (non-blocking-ish).
            if ws is not None:
                try:
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=JOB_TICK_S)
                        if isinstance(raw, (bytes, bytearray)):
                            continue                     # binary previews — ignored
                        m = json.loads(raw)
                        _ws_apply(j, m)
                        if j["state"] in ("done", "error", "cancelled"):
                            break
                except asyncio.TimeoutError:
                    pass
                except Exception:                                # noqa: BLE001
                    j["ws"] = False
                    try:
                        await ws.close()
                    except Exception:                            # noqa: BLE001
                        pass
                    ws = None
            else:
                await asyncio.sleep(JOB_TICK_S)
            # 3) /history — the authoritative answer, ws or no ws.
            try:
                hist = await _cget(f"/history/{job_id}", timeout=8.0)
            except Exception as e:                               # noqa: BLE001
                # ComfyUI died mid-run. Say so; do NOT report the job as finished.
                j.update(state="error",
                         error=(f"lost contact with ComfyUI ({type(e).__name__}). The "
                                f"job may or may not have finished — start ComfyUI from "
                                f"MOT Deck → Components and press Refresh; anything it "
                                f"produced will appear in the gallery."))
                break
            rec = (hist or {}).get(job_id)
            if rec:
                _history_apply(j, rec)
                if j["state"] in ("done", "error", "cancelled"):
                    break
            publish("comfy", what="job", id=job_id, state=j["state"])
    finally:
        if ws is not None:
            try:
                await ws.close()
            except Exception:                                    # noqa: BLE001
                pass
        j["wall_s"] = round(time.time() - t0, 1)
        j["peak_bytes"] = peak or None
        gallery_finalize(j)
        if j["state"] == "done" and peak:
            m = MEASURED.setdefault(j["pick"], {})
            m[j["mode"]] = {"wall_s": j["wall_s"], "peak_bytes": int(peak),
                            "at": time.time(), "label": j.get("shape") or "",
                            "metric": "phys_footprint"}
            _measure_save()
        publish("comfy", what="job", id=job_id, state=j["state"])


def _ws_apply(j: dict, m: dict) -> None:
    """Apply one websocket frame to our job record. Pure-ish, testable."""
    t, d = m.get("type"), (m.get("data") or {})
    if d.get("prompt_id") not in (None, j["id"]):
        return                                    # another client's job on a shared server
    if t == "progress_state":
        # ⚠️ `progress_state`, NOT `progress`, AND THAT IS A LIVE FINDING. Every
        # write-up of this websocket — our own research §1.4 included — says the sampler
        # sends `progress` with {value, max}. At OUR pin comfy_execution/progress.py
        # sends ONE `progress_state` frame carrying every non-pending node instead, so a
        # handler written from the documentation matches nothing and the bar never moves
        # (exactly what the first live run showed). Read the vendored source.
        # step_max is NOT `steps`: `steps` is what the USER asked for and stays put.
        for nid, ns in (d.get("nodes") or {}).items():
            if ns.get("state") == "running" and (ns.get("max") or 0) > 1:
                j["step"], j["step_max"], j["node"] = ns.get("value"), ns.get("max"), nid
                break
    elif t == "progress":            # older pins' shape; kept, costs nothing
        j["step"], j["step_max"] = d.get("value"), d.get("max")
    elif t == "executing":
        j["node"] = d.get("node")
        if d.get("node") is None and d.get("prompt_id") == j["id"]:
            j["state"] = "finishing"              # /history confirms; we never guess
    elif t == "execution_error":
        j["state"] = "error"
        j["error"] = (f"{d.get('node_type') or 'node'} {d.get('node_id') or ''}: "
                      f"{d.get('exception_message') or 'execution error'}")[:400]
    elif t == "execution_interrupted":
        j["state"] = "cancelled"
    elif t == "status":
        q = ((d.get("status") or {}).get("exec_info") or {}).get("queue_remaining")
        if q is not None:
            j["queue_remaining"] = q


def _history_apply(j: dict, rec: dict) -> None:
    """The authoritative end-of-job read: status + the output file manifest."""
    st = (rec.get("status") or {})
    done = bool(st.get("completed"))
    sstr = str(st.get("status_str") or "")
    outs = []
    for _nid, node_out in (rec.get("outputs") or {}).items():
        for key in ("images", "gifs", "videos", "audio"):
            for it in (node_out.get(key) or []):
                if isinstance(it, dict) and it.get("filename"):
                    outs.append({"filename": it["filename"],
                                 "subfolder": it.get("subfolder") or "",
                                 "type": it.get("type") or "output"})
    if outs:
        j["outputs"] = outs
    if sstr == "error" or (not done and sstr and sstr != "success"):
        if j["state"] != "error":
            msgs = []
            for pair in (st.get("messages") or []):
                if isinstance(pair, (list, tuple)) and len(pair) == 2 and pair[0] == "execution_error":
                    msgs.append(str((pair[1] or {}).get("exception_message") or "")[:200])
            j.update(state="error", error=("; ".join(m for m in msgs if m)
                                           or f"ComfyUI reported {sstr!r}"))
        return
    if done:
        if outs:
            gallery_ingest(j)
            j["state"] = "done"
        else:
            j.update(state="error",
                     error="ComfyUI reported success but produced no output file")


@app.post("/api/comfy/generate")
async def api_comfy_generate(req: Request) -> JSONResponse:
    body = await req.json() or {}
    pick_id = str(body.get("pick") or "")
    mode = str(body.get("mode") or "image")
    spec = PICK_BY_ID.get(pick_id)
    if spec is None:
        return JSONResponse({"ok": False, "error": "unknown model"}, status_code=400)
    if mode not in spec["modes"]:
        return JSONResponse({"ok": False,
                             "error": f"{spec['title']} does not do {mode}"}, status_code=400)
    if not str(body.get("prompt") or "").strip():
        return JSONResponse({"ok": False, "error": "type a prompt first"}, status_code=400)

    # CONNECT-TIME VALIDATION, BEFORE SUBMIT — nodes and models both.
    v = await validate_pick(pick_id, mode)
    if not v["ok"]:
        return JSONResponse({"ok": False, "error": v["reason"], "validation": v},
                            status_code=409)

    # A blank seed means "surprise me" and the rolled number is REPORTED, so the result
    # stays reproducible. Never silently 0 (every default run would come out identical).
    seed = body.get("seed")
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        seed = int.from_bytes(os.urandom(6), "big")
    params = dict(body)
    params["seed"] = seed
    graph = build_graph(pick_id, mode, params)
    bad = fence_violations(graph)
    if bad:
        return JSONResponse({"ok": False,
                             "error": f"stock-node fence: refusing {', '.join(bad)}"},
                            status_code=500)

    job_id = str(uuid.uuid4())
    client_id = str(uuid.uuid4())
    try:
        r = await _CX.post(comfy_url("/prompt"), timeout=30.0,
                           json={"prompt": graph, "client_id": client_id,
                                 "prompt_id": job_id})
    except Exception as e:                                       # noqa: BLE001
        return JSONResponse({"ok": False, "error": (
            f"ComfyUI did not accept the job ({type(e).__name__}: {e}). Start it from "
            f"MOT Deck → Components, then try again.")}, status_code=502)
    try:
        payload = r.json()
    except ValueError:
        payload = {}
    if r.status_code >= 400:
        # node_errors IS the authoritative missing-model signal (research §4.5) —
        # surfaced verbatim, never swallowed into a generic failure.
        ne = payload.get("node_errors") or {}
        err = payload.get("error") or {}
        lines = []
        for nid, ent in ne.items():
            cls = ent.get("class_type") or nid
            for d in (ent.get("errors") or []):
                lines.append(f"{cls}: {d.get('message')} ({d.get('details')})")
        return JSONResponse({"ok": False, "error": (
            "; ".join(lines) or err.get("message") or f"ComfyUI refused the job "
                                                      f"(HTTP {r.status_code})"),
            "node_errors": ne}, status_code=409)

    shape = (f"{params.get('width') or spec['defaults'][mode]['width']}×"
             f"{params.get('height') or spec['defaults'][mode]['height']}")
    if mode == "video":
        shape += f" · {_wan_length(params.get('frames') or spec['defaults'][mode]['frames'])}f"
    j = {"id": job_id, "client_id": client_id, "pick": pick_id,
         "pick_title": spec["title"], "mode": mode, "state": "running",
         "prompt": params.get("prompt"), "negative": params.get("negative"),
         "seed": seed, "steps": graph_steps(graph), "shape": shape,
         "submitted": time.time(), "step": None, "step_max": None,
         "outputs": [], "error": None, "peak_bytes": None, "wall_s": None,
         "ws": None, "measured_before": measure_note(pick_id, mode),
         "graph": graph}
    JOBS[job_id] = j
    j["task"] = asyncio.create_task(_follow(job_id))
    publish("comfy", what="job", id=job_id, state="running")
    return JSONResponse({"ok": True, "job": _job_json(j), "seed": seed})


@app.get("/api/comfy/jobs")
async def api_comfy_jobs() -> JSONResponse:
    """Our jobs + ComfyUI's OWN queue view (`/api/jobs`, new at our pin). Different
    questions: ours knows what THIS surface submitted and measured; the server's knows
    what it is actually doing — including work queued from the ComfyUI tab, which would
    otherwise look like our job hanging for no reason."""
    server = {"ok": False, "jobs": [], "error": None}
    try:
        server_raw = await _cget("/api/jobs?limit=25", timeout=8.0)
        server = {"ok": True, "error": None,
                  "jobs": [{"id": x.get("id") or x.get("prompt_id"),
                            "status": x.get("status"),
                            "mine": (x.get("id") or x.get("prompt_id")) in JOBS}
                           for x in (server_raw.get("jobs") or [])]}
    except Exception as e:                                       # noqa: BLE001
        server["error"] = f"{type(e).__name__}: {e}"[:160]
    return JSONResponse({"ok": True, "jobs": [_job_json(j) for j in JOBS.values()],
                         "server": server})


@app.post("/api/comfy/jobs/{job_id}/cancel")
async def api_comfy_job_cancel(job_id: str) -> JSONResponse:
    j = JOBS.get(job_id)
    err = None
    try:
        r = await _CX.post(comfy_url(f"/api/jobs/{job_id}/cancel"), timeout=8.0, json={})
        if r.status_code >= 400:
            await _CX.post(comfy_url("/interrupt"), timeout=8.0)
    except Exception as e:                                       # noqa: BLE001
        err = f"{type(e).__name__}: {e}"[:160]
    if j:
        j["state"] = "cancelled"
    publish("comfy", what="job", id=job_id, state="cancelled")
    return JSONResponse({"ok": err is None, "error": err,
                         "job": _job_json(j) if j else None})


@app.get("/api/comfy/graph/{job_id}")
async def api_comfy_graph(job_id: str) -> JSONResponse:
    """The EXACT API-format graph we submitted — the only honest answer to "what did it
    actually run": not the template, the graph."""
    j = JOBS.get(job_id)
    if not j:
        it = next((x for x in gallery()["items"] if x.get("job") == job_id), None)
        if it and it.get("graph"):
            return JSONResponse({"ok": True, "graph": it["graph"]})
        return JSONResponse({"ok": False, "error": "no such job"}, status_code=404)
    return JSONResponse({"ok": True, "graph": j["graph"]})


@app.post("/api/comfy/open-template")
async def api_comfy_open_template(req: Request) -> JSONResponse:
    """Copy the STOCK template into ComfyUI's workflow browser directory.

    ⚠️ IT IS THE TEMPLATE, NOT YOUR PARAMETERS, AND THE UI SAYS SO: the browser reads
    UI-format graphs, we submit API format, and a hand-rolled conversion that lost a
    setting would be the lie. The exact graph is offered as JSON instead."""
    body = await req.json() or {}
    spec = PICK_BY_ID.get(str(body.get("pick") or ""))
    if spec is None:
        return JSONResponse({"ok": False, "error": "unknown model"}, status_code=400)
    d = templates_dir()
    if d is None:
        return JSONResponse({"ok": False, "error": (
            "the vendored workflow-templates package is not in this install")},
            status_code=404)
    src = d / f"{spec['template']}.json"
    dst = comfy_base() / "user" / "default" / "workflows" / f"harness-{spec['template']}.json"
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError as e:
        return JSONResponse({"ok": False, "error": f"could not write {dst}: {e}"},
                            status_code=500)
    return JSONResponse({"ok": True, "path": str(dst), "name": dst.stem,
                         "url": comfy_url("/"),
                         "note": (f"Open the ComfyUI tab → Workflows → {dst.stem}. It is "
                                  f"upstream's stock template, not your parameters.")})


# ══ GALLERY — keep everything, and never claim a file it cannot see ══════════
def _gallery_path() -> Path:
    return state_dir() / "gallery.json"


def _gallery_load() -> list:
    try:
        d = json.loads(_gallery_path().read_text(encoding="utf-8"))
        return list(d.get("items") or [])
    except (OSError, ValueError):
        return []


def _gallery_write(items: list) -> None:
    try:
        state_dir().mkdir(parents=True, exist_ok=True)
        tmp = str(_gallery_path()) + ".harness-tmp"
        with open(tmp, "w") as f:
            json.dump({"items": items}, f, indent=2)
        os.replace(tmp, _gallery_path())
    except OSError:
        pass


def gallery_ingest(j: dict) -> None:
    """Record a finished job's outputs; called once, from the history read."""
    items = _gallery_load()
    known = {(i.get("subfolder"), i.get("filename")) for i in items}
    for o in j.get("outputs") or []:
        if (o["subfolder"], o["filename"]) in known:
            continue
        path = output_dir() / (o["subfolder"] or "") / o["filename"]
        try:
            size = path.stat().st_size
        except OSError:
            size = None
        items.append({
            "filename": o["filename"], "subfolder": o["subfolder"],
            "job": j["id"], "pick": j["pick"], "pick_title": j["pick_title"],
            "mode": j["mode"], "prompt": j.get("prompt"), "seed": j.get("seed"),
            "steps": j.get("steps"), "shape": j.get("shape"),
            "at": time.time(), "bytes_at_ingest": size,
            "wall_s": j.get("wall_s"), "peak_bytes": j.get("peak_bytes"),
            "graph": j.get("graph"),
        })
    _gallery_write(items)


def gallery_finalize(j: dict) -> None:
    """Write the run's MEASURED numbers onto the items it produced.

    ⚠️ WHY A SECOND PASS: ingest happens when /history says complete — BEFORE the
    follower's `finally` stops the clock, which left the first live run's gallery card
    blank while the queue strip above it read 59.6s."""
    items = _gallery_load()
    touched = False
    for it in items:
        if it.get("job") == j["id"]:
            it["wall_s"], it["peak_bytes"] = j.get("wall_s"), j.get("peak_bytes")
            touched = True
    if touched:
        _gallery_write(items)


def gallery() -> dict:
    """Registry ∪ what is on disk under <output>/harness/, re-stat'd every time.

    ⚠️ THREE LIES THIS REFUSES TO TELL: an item whose file is GONE is listed `missing`,
    never hidden; one whose size CHANGED since ingest is flagged `size_changed` rather
    than drawn as if nothing happened; and a file under our prefix the registry never
    saw is still LISTED (`orphan`) — keep-everything means the DISK is the truth, which
    is also what makes the gallery survive a lost registry."""
    items, out, seen = _gallery_load(), [], set()
    for it in items:
        p = output_dir() / (it.get("subfolder") or "") / it["filename"]
        seen.add(str(p))
        row = dict(it)
        row.pop("graph", None)                    # too big for a list payload
        try:
            sz = p.stat().st_size
            row["bytes"] = sz
            row["size_h"] = gb(sz)
            row["state"] = ("size_changed"
                            if (it.get("bytes_at_ingest") and sz != it["bytes_at_ingest"])
                            else "ok")
        except OSError:
            row["bytes"], row["size_h"], row["state"] = 0, "—", "missing"
        row["path"] = str(p)
        row["kind"] = _kind(it["filename"])
        out.append(row)
    root = output_dir() / OUT_PREFIX
    try:
        for p in sorted(root.rglob("*")):
            if not p.is_file() or str(p) in seen:
                continue
            st = p.stat()
            out.append({"filename": p.name,
                        "subfolder": str(p.parent.relative_to(output_dir())),
                        "bytes": st.st_size, "size_h": gb(st.st_size),
                        "at": st.st_mtime, "state": "orphan", "path": str(p),
                        "kind": _kind(p.name),
                        "note": "found on disk; this surface has no record of making it"})
    except OSError:
        pass
    out.sort(key=lambda r: -(r.get("at") or 0))
    return {"items": out, "total_bytes": sum(int(r.get("bytes") or 0) for r in out)}


def _kind(name: str) -> str:
    n = name.lower()
    if n.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return "image"
    if n.endswith((".mp4", ".webm", ".mkv", ".gif")):
        return "video"
    if n.endswith((".flac", ".mp3", ".wav", ".opus", ".ogg")):
        return "audio"
    return "file"


@app.get("/api/comfy/gallery")
async def api_comfy_gallery() -> JSONResponse:
    g = gallery()
    return JSONResponse({"ok": True, "items": g["items"],
                         "total_bytes": g["total_bytes"],
                         "total_h": gb(g["total_bytes"]),
                         "output_dir": str(output_dir()),
                         "disk": _disk(output_dir())})


@app.get("/api/comfy/file")
async def api_comfy_file(filename: str, subfolder: str = "") -> Response:
    """Serve one gallery file from ComfyUI's output dir.

    ⚠️ CONTAINMENT, THE OFFICE LANE'S RULE: resolve, then compare against the root."""
    root = output_dir().resolve()
    try:
        p = (root / (subfolder or "") / filename).resolve()
        p.relative_to(root)
    except (ValueError, OSError):
        return JSONResponse({"ok": False, "error": "path outside the output directory"},
                            status_code=400)
    if not p.is_file():
        return JSONResponse({"ok": False, "error": "no such file"}, status_code=404)
    return FileResponse(str(p), headers={"Cache-Control": "no-store"})


@app.post("/api/comfy/reveal")
async def api_comfy_reveal(req: Request) -> JSONResponse:
    """Reveal one gallery file in Finder. Same containment rule as the file route."""
    import subprocess
    body = await req.json() or {}
    root = output_dir().resolve()
    try:
        p = (root / (body.get("subfolder") or "") / str(body.get("filename") or "")).resolve()
        p.relative_to(root)
    except (ValueError, OSError):
        return JSONResponse({"ok": False, "error": "path outside the output directory"},
                            status_code=400)
    target = p if p.exists() else root
    try:
        subprocess.run(["/usr/bin/open", "-R", str(target)], timeout=10,
                       capture_output=True)
    except Exception as e:                                       # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"},
                            status_code=500)
    return JSONResponse({"ok": True, "revealed": str(target)})


_measure_load()
