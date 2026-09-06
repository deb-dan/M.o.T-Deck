# ComfyUI → first-party "Video/Audio" surface — research for the MOT Deck spec

**Date:** 2026-08-29 · **Author:** research agent (Fable brief) · **Status:** findings only, no code changed
**Doctrine:** this is the obligation-8 (RESEARCH BEFORE BUILD) pass for the queued milestone. Every
number below was either probed against OUR running instance, read out of OUR vendored tree, or
HEAD-requested from HuggingFace today. Where a claim is inherited from prior research it is cited.

**Prior research this builds on (do not re-derive):**
- `docs/research/(done) 2026-08-20-music-video-gen.md` — the music/video field survey. Its verdicts
  (HunyuanVideo EU-void, Wan 14B too slow, ACE-Step licenses, the MusicGen/YuE refusals) carry over.
- `docs/research/2026-08-28-fit-math-oss.md` + `bridge/core/fit.py` — why we do not hand-derive
  memory math, and the measured-peaks pattern this surface must reuse.

---

## 0. TL;DR for Fable

1. **Our ComfyUI is v0.34.1, stock, empty**: zero custom nodes, zero models, 899 stock node classes
   that already cover every model family we would curate (LTXV, Wan 2.1/2.2, ACE-Step 1/1.5,
   Stable Audio, Z-Image, Flux, SD3.5, SDXL, SaveVideo/SaveAudio). **S1–S3 need NO custom nodes.**
2. **The curated-model registry is already on disk**: the `comfyui-workflow-templates` pip package
   in the comfyui venv ships ~hundreds of workflow JSONs whose nodes carry
   `properties.models[] = {name, url, directory}` — exact HF URLs and target model dirs, versioned
   with our pin. Our "starter models" list should be *generated from* (or at minimum verified
   against) these files, not hand-typed.
3. **The binding constraint is DISK, not RAM**: the Mac has **~48 GB free of 926 GB (95 % full)**.
   Models are 5–21 GB per set. The acquisition surface must be disk-first.
4. **Video is now honestly possible where the 2026-08-20 report refused it as a *component***,
   because ComfyUI is already installed for other reasons and the two realistic models are small:
   LTX-Video 2B (6.3 GB) and Wan 2.2 5B (10 GB, Apache-2.0). Speed on this Mac is still unmeasured
   — S2 must open with a measurement spike (the `measure_music.sh` pattern), not a promise.
5. **`fit.py` does not price diffusion models** (it is a GGUF/llama.cpp oracle). The correct
   pattern is the one the doctrine already names: **measured peaks**, advisory-only
   (ADVISORY-GATES RULING 2026-08-28), using the same ledger `_within_budget` gate shape as
   `bridge/routers/models.py::_voice_spawn_guard`.

---

## 1. Our install (all verified live 2026-08-29)

### 1.1 Where it actually lives — a trap for the builder

The **repo checkout has no ComfyUI**: `vendor/comfyui` and `data/comfyui*` do not exist under
the then-active checkout (now the retained read-only Claude archive). The running instance belongs to the
**shipped app**: `~/Library/Application Support/MOT Deck/{vendor/comfyui, data/comfyui,
data/comfyui-venv}`, launched by that deployment's `scripts/start_component.sh` (`comfyui` case,
lines ~684–756). Any S1 code must resolve the ComfyUI base dir from the same ROOT the supervisor
uses — never from the repo path.

Process (live, pid on :8188):

```
data/comfyui-venv/bin/python main.py --listen 127.0.0.1 --port 8188
  --base-directory <ROOT>/data/comfyui
  --database-url sqlite:///<ROOT>/data/comfyui/user/comfyui.db
  --disable-auto-launch
```

`start_component.sh` documents the three startup traps (pre-created `custom_nodes/ user/ models/
input/ output/`; `--database-url` NOT covered by `--base-directory`; listener-scoped port clear).
Port comes from `motdeck.yaml` (`components.comfyui.port: 8188`, default 8188). **Loopback only,
NO auth** — the startup banner says so explicitly. Any process on this Mac can submit jobs; our
bridge proxy must not widen that.

### 1.2 Versions (from `GET /system_stats` on the live instance)

| Thing | Value |
|---|---|
| ComfyUI | **0.34.1** (motdeck.yaml pin `v0.34.1`, bumped from v0.33.3 on 2026-08-28) |
| Frontend | comfyui-frontend-package **1.49.6** (pip, no npm build) |
| Workflow templates | comfyui-workflow-templates **0.11.48** (+ split pkgs: `_json` 0.1.57, `_core` 0.3.322, media pkgs) |
| Python / torch | 3.12.11 / **2.15.0.dev20260820** (deliberately-floating MPS nightly — see motdeck.yaml:221–231; a torch refresh is its own pass with a real generation A/B) |
| Device | `mps`, `vram_total` = full 64 GB unified (68 719 476 736 B) |

### 1.3 State: empty on purpose

- `custom_nodes/`: **empty** (0 packs).
- `models/`: 27 empty subdirs (`GET /models` lists: checkpoints, loras, vae, text_encoders,
  diffusion_models, clip_vision, latent_upscale_models, audio_encoders, …). `GET /models/checkpoints` → `[]`.
- Queue empty, history empty. Debi has downloaded **no models** — matches the brief.

### 1.4 The API we build against (routes read from vendored `server.py` + probed)

- `POST /prompt` — body `{"prompt": <API-format graph>, "client_id": "<uuid>"}` → `{prompt_id, number, node_errors}`.
  **API format** = flat dict keyed by node id: `{"3": {"class_type": "KSampler", "inputs": {"seed": 5, "model": ["4", 0], …}}}`.
  Server-side validation against `/object_info` happens here; missing model files come back as
  `node_errors` **before** anything runs — this is our free "missing model" detector at submit time.
- `WS /ws?clientId=<uuid>` — push events: `status` (queue depth), `execution_start`, `executing`
  (node-by-node), `progress` (sampler step k/N), `executed` (per-output-node, carries filenames),
  `execution_error`, `execution_cached`. This is the progress feed for our form.
- `GET /history/{prompt_id}` — outputs manifest after completion (poll fallback if the ws drops).
- `GET /view?filename=&subfolder=&type=output` — fetch the produced image/video/audio file.
- `GET /object_info[/class]` — **899 node classes at our pin**; per-class input schemas incl. the
  live enum of files in each model folder (how Krita's plugin validates models).
- `GET /models`, `GET /models/{folder}` — model-dir listings (our "is it downloaded" check).
- `POST /interrupt`, `POST /free` (unload models / free memory), `POST /queue` (delete pending),
  `GET /queue`, `GET /system_stats`, `POST /upload/image` (for i2v inputs).
- **New at this pin:** `GET /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/{id}/cancel`,
  `POST /api/jobs/cancel` — a first-class jobs view with status filters
  (pending/in_progress/completed/failed). Nicer primitive for our queue UX than stitching
  `/queue`+`/history` ourselves. Verified present in `server.py` route table.
- `GET /features` → `{"assets": false, …}` — the new sqlite-backed asset system exists in the tree
  (`app/assets/`) but is **disabled** at our pin/config (`/api/assets` → 503). Do not build on it.
- **There is no server-side model-download endpoint at our pin** (no `/internal/models/download`;
  `model_filemanager` is listing-only). The frontend's "missing models" dialog can hand the browser
  a download or route via the (disabled) asset importer — either way, **downloading is our job**,
  which is good: we already own a download manager (see §3.2).

### 1.5 Stock-node coverage per model family (grep of live `/object_info`)

| Family | Stock nodes present (sample) | Custom pack needed? |
|---|---|---|
| SDXL / SD1.5 | `CheckpointLoaderSimple, CLIPTextEncode, KSampler, EmptyLatentImage, VAEDecode, SaveImage` | No |
| SD3.5 | `EmptySD3LatentImage, CLIPTextEncodeSD3, TripleCLIPLoader` | No |
| Flux / Flux2 | `FluxGuidance, CLIPTextEncodeFlux, DualCLIPLoader, UNETLoader` | No |
| Z-Image | `EmptySD3LatentImage`-based template (single-stream DiT via `UNETLoader`+`CLIPLoader`) | No |
| LTX-Video / LTX-2 | `EmptyLTXVLatentVideo, LTXVConditioning, LTXVImgToVideo, LTXVScheduler, SaveVideo/CreateVideo` | No |
| Wan 2.1/2.2 | `Wan22ImageToVideoLatent, WanImageToVideo, …` | No |
| HunyuanVideo (1 & 1.5) | present (`EmptyHunyuanLatentVideo`, …) | No (but refused on license, §4.2) |
| Mochi | `EmptyMochiLatentVideo` | No (but refused, §4.2) |
| ACE-Step 1 / 1.5 | `TextEncodeAceStepAudio, EmptyAceStepLatentAudio, EmptyAceStep1.5LatentAudio, VAEDecodeAudio, SaveAudioMP3/Opus` | No |
| Stable Audio Open | `ConditioningStableAudio, EmptyLatentAudio` | No |
| GGUF-quantised checkpoints | **absent** — needs `city96/ComfyUI-GGUF` | Yes → out of scope for S1–S3 |
| MMAudio (video→foley) | absent — needs kijai's `ComfyUI-MMAudio` | Yes → deferred (§4.1) |

**Conclusion: the entire slice ladder runs on stock nodes.** That decision retires the custom-node
supply-chain risk for these slices (§4.1) and should be written into the spec as a fence.

### 1.6 Model picks for THIS machine (M-series, 64 GB unified, ~48 GB free disk)

Fit stance: `fit.py` prices GGUF/MLX LLMs via llama.cpp's oracle; it has **no honest model for
torch/MPS diffusion peaks**, and the 2026-08-28 fit research's core lesson (Ollama abandoned
precise prediction; measure, don't derive) applies. So: **RAM verdicts below are class-level and
advisory; each curated model gets a measured peak from a one-off spike run before its card claims
numbers** (the `measure_music.sh` → runbook → advisory-gate pipeline). 64 GB fits every model
listed as realistic; the honest unknown on video is *time*, not memory — except VAE-decode spikes
on video, which are exactly the "video gen peaks" the brief flags and what the spike must measure.

All file sizes verified by HEAD today; all URLs are the ones inside our vendored templates
(Comfy-Org repackages, single-file, no HF auth gate) unless noted.

**IMAGE — realistic, in recommended order**

| Model | Files (dir ← file) | Size | License | Template (on disk) |
|---|---|---|---|---|
| **Z-Image-Turbo** (Tongyi, 6B, 8-step turbo) | `diffusion_models` ← `Comfy-Org/z_image_turbo` `z_image_turbo_int8_convrot.safetensors` (or bf16 12.31 GB); `text_encoders` ← `qwen_3_4b_fp8_mixed.safetensors`; `vae` ← `ae.safetensors` | **6.2 + 5.63 + 0.34 ≈ 12.2 GB** | **Apache-2.0** (verified via HF API) | `image_z_image_turbo_int8` |
| **SDXL base 1.0** | `checkpoints` ← `stabilityai/stable-diffusion-xl-base-1.0/sd_xl_base_1.0.safetensors` | **6.94 GB** | CreativeML Open RAIL++-M | `image_sdxl_simple` |
| SD3.5 Large fp8 | `checkpoints` ← `Comfy-Org/stable-diffusion-3.5-fp8/sd3.5_large_fp8_scaled.safetensors` | 14.93 GB | Stability **Community** License (free < $1M rev) | `sd3.5_simple_example` |
| Flux.1 schnell fp8 | `checkpoints` ← `Comfy-Org/flux1-schnell/flux1-schnell-fp8.safetensors` | 17.24 GB | **Apache-2.0** | `flux_schnell` |
| Flux.1 dev fp8 | `Comfy-Org/flux1-dev/flux1-dev-fp8.safetensors` | 17.25 GB | ⚠️ **FLUX.1-dev NON-COMMERCIAL** | `flux_dev_checkpoint_example` |

Z-Image-Turbo first: best license + smallest + fastest (8 steps) + bilingual, and it is the
template browser's own most-used image template (`usage: 15689` in index.json). SDXL as the
cheap classic. Flux dev only with a red license badge; Flux2 (32B, 17–22 GB sets) and Qwen-Image
(20B) left out of the starter set on disk grounds.

**VIDEO — honest tiering**

| Model | Files | Size | License | Verdict on this Mac |
|---|---|---|---|---|
| **LTX-Video 2B v0.9.5** | `checkpoints` ← `Lightricks/LTX-Video/ltx-video-2b-v0.9.5.safetensors` + `text_encoders` ← `t5xxl_fp8_e4m3fn_scaled.safetensors` | **6.34 + 5.16 ≈ 11.5 GB** | LTX-Video **Open Weights License** (custom; HF tag `other`) | Realistic — the small/fast end of the field; the 2026-08-20 report's Mac datapoint (~2.5 min for 5 s @ 576×1024, ~34 GB peak) is THIS family. **Measure at S2 open.** |
| **Wan 2.2 TI2V 5B** (t2v *and* i2v in one) | `diffusion_models` ← `Comfy-Org/Wan_2.2_ComfyUI_Repackaged/…/wan2.2_ti2v_5B_fp16.safetensors` + `text_encoders` ← `umt5_xxl_fp8_e4m3fn_scaled.safetensors` + `vae` ← `wan2.2_vae.safetensors` | **10.0 + 6.74 + 1.41 ≈ 18.1 GB** | **Apache-2.0** (best license in video) | Plausible but slower class (dense DiT, 24 fps 720p target); the 1h22m/2s figure from prior research was the **14B** — the 5B is untested here. Measure before promising. |
| LTX-2 / LTX-2.3 | 38–47 GB template sets | — | LTX-2 Community ($10M cap, revocation clauses) | **No** — bigger than free disk, and prior research gated even the 21 GB int8. |
| HunyuanVideo (all, incl. 1.5) | — | — | **License grant void in the EU** — Debi is in Estonia | **REFUSE regardless of fit** (standing verdict, 2026-08-20 report; stated 4× in the license). |
| Mochi-1 | — | — | Apache-2.0 | **REFUSE** — abandoned, wants H100-class; only stock latent node exists anyway. |
| Wan 14B (t2v/i2v) | 2× ~16 GB | — | Apache-2.0 | **REFUSE on speed** (measured 1h22m/2s @ 480p on M1 Max 64 GB, prior report). |

**AUDIO — realistic, in recommended order**

| Model | Files | Size | License | Notes |
|---|---|---|---|---|
| **ACE-Step v1 3.5B** (text→song incl. vocals) | `checkpoints` ← `Comfy-Org/ACE-Step_ComfyUI_repackaged/all_in_one/ace_step_v1_3.5b.safetensors` | **7.70 GB** | **Apache-2.0** | Single-file, stock nodes (`TextEncodeAceStepAudio` takes tags + lyrics), template `audio_ace_step_1_t2a_song`. |
| ACE-Step 1.5 turbo (aio) | `checkpoints` ← `Comfy-Org/ace_step_1.5_ComfyUI_files/checkpoints/ace_step_1.5_turbo_aio.safetensors` | 10.03 GB | **MIT** (verified in prior report — v1 is Apache, 1.5 is MIT, do not conflate) | 8-step distilled; upgrade path from v1 if quality warrants +2.3 GB. |
| **Stable Audio Open 1.0** (SFX/instrumental, ≤47 s) | `checkpoints` ← `Comfy-Org/stable-audio-open-1.0_repackaged/stable-audio-open-1.0.safetensors` + `text_encoders` ← `ComfyUI-Wiki/t5-base` | **4.85 + 0.89 ≈ 5.7 GB** | Stability **Community** License (repackage ungated; original HF repo is gated) | No vocals — the SFX lane, per prior report. |
| MMAudio (video→foley) | — | — | — | Needs a custom node pack → deferred until the vendoring rule (§4.1) is exercised deliberately. |
| MiniMax-Music3 | 11.9 GB int8 | — | MiniMax Community | Already researched as an **MLX native lane**, not a ComfyUI job — keep it out of this surface. |

Note the **sharing win**: `umt5_xxl_fp8` serves all Wan variants; `t5xxl_fp8` serves LTXV *and*
Flux-split workflows. The registry must model shared files so the disk math and the "download"
button don't double-count.

---

## 2. Prior art — how the polished frontends do "workflows without the graph"

### 2.1 ComfyUI's own template browser (what we already ship)

Since ~v0.3.30 the frontend has a template browser fed by the `comfyui-workflow-templates` pip
package (ours: 0.11.48). Mechanics, read from the files in our venv
(`…/site-packages/comfyui_workflow_templates_json/templates/`):

- `index.json` = category list → template cards with `name, title, description, models[],
  size` (**total download bytes for the whole model set**), `usage` (popularity), `openSource`
  flag, `io` (declared input/output nodes), thumbnails.
- Each template is a **UI-format** workflow JSON. Loader nodes carry
  `properties.models: [{name, url, directory}]` — e.g. `sdxl_simple_example.json` points
  `sd_xl_base_1.0.safetensors → checkpoints` at the exact stabilityai URL. When the frontend loads
  a workflow whose named files are absent from `/models/{directory}`, it raises a **missing-models
  dialog** offering per-file downloads. (Newest templates are migrating to the asset system, which
  is off at our pin — the `properties.models` mechanism is the one to rely on.)
- **Steal this wholesale:** the template JSONs are a *versioned, pinned, first-party registry of
  known-good graphs + exact model URLs + byte sizes*, already inside our install. Our curation
  layer should read them (or vendor copies of the ~8 we bless) rather than invent a parallel format.

### 2.2 UI-format vs API-format (the minimal programmatic contract)

- **UI format** (what templates/editor save): `{nodes:[{id,type,pos,widgets_values,…}], links:[…],
  groups, extra, version}`. Contains layout junk; widget values are *positional arrays*; the
  UI→API conversion (`graphToPrompt`) lives in the frontend, not the server. **Do not submit this.**
- **API format** (what `POST /prompt` takes): `{"<node_id>": {"class_type": "...", "inputs":
  {name: value | ["<src_node>", slot]}}}`. Obtainable from the editor via *Export (API)*.
  Deterministic, diffable, and the format every automation frontend standardises on (Krita plugin
  docs explicitly recommend it).
- **Parameterisation pattern common to all prior art:** store the API-format graph as a template
  with a tiny slot map alongside it — `{prompt: ["6","inputs","text"], seed: ["3","inputs","seed"],
  width: ["5","inputs","width"], …}` — fill slots, POST, correlate by `prompt_id`, stream ws.

### 2.3 SwarmUI (closest to our target shape)

- A .NET "Generate tab" over ComfyUI backends. Its `ComfyUIBackendExtension` translates the flat
  parameter set (prompt/seed/steps/CFG/model/resolution/…) into a graph via a **step-composed
  workflow generator** — ordered generation steps each contribute nodes (base model → conditioning
  → sampler → VAE → saves), so features (refiner, LoRA, video frames) splice in without a
  hand-drawn graph per combination.
- **Custom workflows → form**: a power user builds a graph in its embedded Comfy editor, marks
  inputs with `SwarmInput*` primitive nodes (and `${variable}` substitution in its custom-workflow
  JSON), hits "Use This Workflow In Generate Tab" — the inputs become ordinary form fields.
  Bidirectional: it can also import a workflow and infer parameters. This is the graduation path
  we should copy in shape (our v1 needs only the fixed-template half).
- **Model downloader**: a Utilities tab where you paste a Civitai/HF URL; it picks the destination
  folder from model-type metadata and stores card metadata beside the weights. Known bug worth
  learning from (their issue #743): stale metadata from the previous URL bleeding into the next
  download — i.e. *reset acquisition-form state per URL*.
- Takeaway for us: SwarmUI proves the two-layer shape — **curated param-form for the 95 % case,
  full graph editor one click away** — and that the mapping layer is where all the complexity
  hides. We avoid most of it by shipping fixed blessed templates instead of a general generator.

### 2.4 Krita AI plugin (Acly/krita-ai-diffusion) — the discipline to copy

- Builds **API-format graphs client-side** from a high-level `WorkflowInput` (intent → graph), and
  on connect **validates the server**: required nodes checked against `/object_info`, required
  models against `/models/{folder}` listings, with a precise "missing: X, put it in folder Y"
  report. Ships a `download_models.py` that fetches everything required.
- Custom workflows: placeholder **Parameter nodes** wired to widget-converted inputs become
  auto-generated Krita form controls; ordering via `1.`-prefixes, grouping via `Group/Name`.
  Krita-specific sink/source nodes (`Krita Output`, `Krita Canvas`) mark IO.
- Takeaway: the **connect-time capability check** (nodes + models, exact names, exact folders) is
  what makes a frontend feel solid. Our `/object_info` + `/models` probes give it to us for free.

### 2.5 Others, briefly

- **ComfyBox** (form-builder over Comfy): abandoned — a warning that a generic form-builder is a
  bigger product than a curated set of journeys.
- **ViewComfy / ComfyUI-Deploy pattern**: template + declared exposed inputs → generated web form;
  same slot-map idea as §2.2, validating that our minimal contract is the industry-standard one.

---

## 3. The MOT Deck shape — proposed slice ladder

### 3.0 What the user is ultimately trying to DO (obligation 1)

Type a sentence, get an image/clip/track, without learning node graphs — with honest numbers
(disk, RAM, minutes) *before* committing, and the stock ComfyUI tab remaining the power exit.

### 3.1 Standing decisions the slices share

- **Backend access**: bridge-proxied. The panel talks to bridge routes; the bridge talks to
  `127.0.0.1:8188` (`/prompt`, ws relay → our existing SSE hub, `/view` passthrough into the
  gallery). Reuse the events pattern from `bridge/routers/downloads.py` (2 s tick, no idle wakeups).
- **Templates**: vendor the blessed workflow JSONs (API-format export + slot map) into the repo,
  sha-pinned, one per journey — sourced from the on-disk template package (§2.1) and verified once
  by hand in the ComfyUI tab. Never fetch templates at runtime.
- **Downloads**: extend `bridge/routers/downloads.py` (it already has pause/resume/cancel, SSE
  progress, registry writes) with a `kind: "comfy"` target that lands files in
  `<ROOT>/data/comfyui/models/<directory>/` per the registry entry. Show `df`-style free-disk in
  the surface *before* the button (48 GB free is one bad click from zero).
- **Gates**: advisory only (2026-08-28 ruling). Per-model measured peak (from the spike runbook)
  vs the same ledger budget `_voice_spawn_guard` uses; over-budget ⇒ show numbers + "proceed
  anyway", never block. A running generation gets its **measurement**, not a prediction
  (`fit.live_verdict` philosophy).
- **Absence**: ComfyUI not installed / not running ⇒ the surface renders with an Install/Start
  card (components lane already owns install+start), never a dead panel.

### 3.2 S1 — Image: acquisition + one-form generate + gallery (scope tight)

1. **Starter-model registry** (data, not UI): 4–5 image entries from §1.6 with exact
   files/sizes/licenses/dirs, license badge class (green Apache/MIT · amber community/RAIL ·
   red non-commercial), fit note, and which vendored template consumes them. Shared-file aware.
2. **Acquisition surface**: cards with size + license badge + disk-free header; Download via the
   existing manager; "downloaded" state = file exists in `/models/{dir}` (probe, don't trust
   registry). No Civitai, no arbitrary URLs in S1 (that is SwarmUI's downloader, a later slice).
3. **Generate form** (one, image-only): model picker (only downloaded models), prompt, negative
   (hidden for turbo models that ignore CFG), size preset, seed (blank = random, shown after),
   steps preset per model. Submit → API-format template with slots filled → `POST /prompt`.
4. **Progress + queue**: ws `progress`/`executing` relayed as SSE; queue strip driven by
   `/api/jobs`; cancel = job cancel/`/interrupt`. Panel stays usable; completion notifies.
5. **Gallery**: completed outputs listed from `/history` + fetched via `/view` proxy; persisted
   references in our own store (outputs live in `<base>/output/`); delete; "reveal file";
   **"Open in ComfyUI"** deep-link per item (see 3.5).
6. Journeys walked + adversarial pass per doctrine (model file deleted mid-queue, ComfyUI killed
   mid-run, two jobs queued, ws dropped → history fallback, disk fills during download …), each
   pinned as a gate test.

**Recommended S1 starter curation given 48 GB free: Z-Image-Turbo int8 set (~12.2 GB) + SDXL
(6.9 GB) ≈ 19 GB.** SD3.5/Flux stay listed-but-not-default with size warnings.

### 3.3 S2 — Video (opens with a measurement, not a feature)

- Spike first (`measure_media.sh`, throwaway, same shape as `measure_music.sh`): LTX-Video 2B and
  Wan 2.2 5B, fixed prompt/seed, on THIS Mac → seconds-per-second-of-video + **measured peak RSS
  (VAE decode is the expected spike)** → runbook + registry numbers. If both measure hopeless,
  S2 honestly reports that and stops — prior research half-expects it.
- Then: t2v/i2v form (duration/resolution presets capped at measured-sane values, i2v via
  `/upload/image`), `SaveVideo` output into the gallery, minutes-long-job UX (persistent queue
  chip, ETA from measured rate, notification).

### 3.4 S3 — Audio

- ACE-Step v1 (tags + lyrics boxes — the two-field convention its encoder expects) and Stable
  Audio Open (single prompt + seconds ≤ 47) forms; `SaveAudioMP3/Opus`; gallery grows an audio
  player. Smallest slice — both graphs are ~8 stock nodes.

### 3.5 Our panel vs the ComfyUI tab

- **Ours**: curated acquisition, the three forms, queue, gallery, license/disk/RAM honesty.
- **ComfyUI tab (power exit)**: everything else — LoRA, ControlNet, inpaint, exotic models,
  graph editing. Deep-link mechanics: write the item's UI-format workflow JSON into
  `<base>/user/default/workflows/` and open the tab (the frontend's workflow browser lists that
  dir) — no frontend patching. Both surfaces share the models dir by construction, so a model
  downloaded in ours serves both — say so in the UI.
- Explicitly NOT ours: workflow editing, custom-node management, arbitrary-URL model install.

---

## 4. Risks

### 4.1 Custom-node supply chain

Incidents on record: **ComfyUI_LLMVISION** (June 2024) — malicious node shipping fake
`openai`/`anthropic` pip packages that stole browser passwords/cards/crypto and exfiltrated to
Discord, discovered via victims' credential-stuffing alerts; **Ultralytics PyPI compromise**
(Dec 2024) hit ComfyUI users through node dependencies. Custom nodes are arbitrary code imported
into the server process at startup, and their *pip dependencies* are the actual attack surface.

**Rule for the spec:** S1–S3 ship with `custom_nodes/` **empty**, enforced by a gate test (the
dir stays empty; `/object_info` count sanity). If a future slice needs a pack (MMAudio, GGUF):
vendored at a pinned commit + sha256 via an installer script with its pip deps pinned and reviewed
— exactly the `install_oo_ai_plugin.sh` precedent — never ComfyUI-Manager, never registry-latest.

### 4.2 Model licenses (badge, don't hide — the standing rule)

- **Green** (Apache-2.0/MIT): Z-Image-Turbo, Flux schnell, Wan 2.2, ACE-Step v1 (Apache) & 1.5 (MIT).
- **Amber**: SDXL (Open RAIL++-M use-restrictions), SD3.5 + Stable Audio Open (Stability Community,
  $1M revenue cap), LTX-Video 0.9.5 (LTX-Video Open Weights License — custom; HF tag is literally
  `other`; must be read, not tag-trusted — the OmniVoice/Music3 mistag lesson).
- **Red**: Flux.1 dev (non-commercial). **Refused**: HunyuanVideo — no EU grant at all (Estonia).
- The tag cannot be trusted, only the LICENSE file can (twice-confirmed lesson) — registry entries
  carry the license *filename/URL we read*, not the HF tag.

### 4.3 Disk (the real constraint)

**~48 GB free / 926 GB, 95 % full** (df, 2026-08-29; CLAUDE.md already queues 3.2 GB probe-dir +
update-.bak deletions for Debi). Full curation (image 19 + video 18.1 + 11.5 + audio 7.7 + 5.7)
≈ **62 GB — does not fit**. Consequences: disk-free is a first-class number in the acquisition UI;
downloads pre-check `size + 2 GB headroom`; a per-model Delete exists from S1; shared encoders
dedupe; video curation is **pick one** (Wan-5B Apache vs LTXV faster) — Debi's call, below.

### 4.4 Queue UX when a generation takes minutes

Video is minutes-per-run at best. Requirements: submit never blocks the panel; progress is
node+step granular (ws `progress`), with ETA only after a measured rate exists (no invented ETAs —
LIES-TO-USER class); cancel always visible (job cancel + `/interrupt`); tab-switch/app-restart
recovers state from `/api/jobs` + `/history` (prompt_ids persisted our side); ws drop degrades to
polling, silently. One generation at a time is fine (ComfyUI serialises anyway) — but say so.

### 4.5 Smaller traps for the builder

- Repo-vs-app path split (§1.1) — resolve base dir from ROOT, never the repo.
- torch is a deliberately-floating MPS nightly; a torch bump invalidates measured peaks → re-run
  the spike on engine updates (note in the update-audit checklist).
- No auth on :8188 — keep it loopback; the bridge proxy must not forward it off-machine.
- `node_errors` from `POST /prompt` is the authoritative missing-model signal — surface it, never
  swallow it into a generic failure.

---

## 5. Open questions for Debi

1. **Disk**: OK to spend ~19 GB on the S1 image starters (Z-Image-Turbo + SDXL)? And for video,
   pick one: **Wan 2.2 5B** (Apache-2.0, 18.1 GB, slower class) or **LTX-Video 2B** (11.5 GB,
   faster, custom license)? Both only after the S2 speed spike.
2. **Commercial intent**: does anything generated here ever ship commercially? Decides whether
   amber (Stability/RAIL caps) models are curated by default and whether Flux dev is listed at all.
3. **HunyuanVideo EU refusal**: confirm as a standing rule (it will keep re-surfacing in model
   lists as "the best open video model").
4. **Audio first pick**: ACE-Step v1 (7.7 GB, Apache) or 1.5 turbo (10 GB, MIT, newer)? (Either
   way MiniMax-Music3 stays an MLX-lane candidate, not a ComfyUI one.)
5. **Gallery retention**: keep outputs forever in `<base>/output/` (disk!) or default-prune with
   pin-to-keep?
6. Is a later "paste a Civitai/HF URL" downloader (SwarmUI-style) wanted at all, or does curation
   + the ComfyUI tab cover it?

## Honest limits

- **No generation was run** (no models on disk) — every workflow named here is template-verified,
  not execution-verified; S1's first journey walk covers that by definition.
- Video/audio **speed and peak-RAM on this Mac are unmeasured**; §1.6's realism tiers rest on the
  2026-08-20 report's external datapoints. The S2 spike is the fix, and S3 should get a cheap
  timing note too.
- Flux.2 Klein's license was not primary-source-verified (excluded from curation anyway).
- SwarmUI internals were read from docs/search summaries, not its source; the shapes cited
  (step-composed generator, `${var}` injection, SwarmInput promotion, downloader) are
  well-corroborated but a builder copying details should read `src/BuiltinExtensions/ComfyUIBackend/`.
- The `properties.models` mechanism is being superseded upstream by the asset system (off at our
  pin) — re-check at the next ComfyUI pin bump.
