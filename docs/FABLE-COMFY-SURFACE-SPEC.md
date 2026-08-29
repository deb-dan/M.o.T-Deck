# FABLE SPEC — ComfyUI first-party generate surface (S1: image + video)
(Debi's rulings, 2026-08-29 · research: docs/research/2026-08-29-comfyui-tab.md — BINDING source)

## Debi's locked answers
- **NO MiniMax H3 for now** — too big (smallest set ~39.6GB vs ~48GB free disk). Ledger row; revisit when disk allows.
- **Starter set: image AND video, ≤14 GB TOTAL file size.** Candidate families Debi named: LTX, Qwen, Wan — "either of those" — smallest viable. Licenses: Apache/MIT preferred ("maybe someday" commercial); a non-Apache pick (e.g. LTX custom) is allowed ONLY if no Apache option fits the budget, and its license terms are stated on the download card.
- **Gallery: keep everything**, total size visible in the disk strip; pruning is deliberate, never automatic.
- HunyuanVideo stays REFUSED (EU-void license, standing verdict).

## S1 shape (from the research's slice ladder, disk-first)
1. **Curation is GENERATED, not hand-typed**: read the vendored comfyui-workflow-templates registry (loader nodes carry {name,url,directory}); the builder HEAD-verifies every candidate's real size and picks the best image+video combo under the 14GB TOTAL cap — smallest viable quants, template-native (a model without a stock template is out of scope). Report the exact combo chosen with sizes + licenses; if no combo covering both fits 14GB, ship the best image pick + the smallest video pick that fits and SAY the overshoot honestly rather than silently dropping video.
2. **Acquisition surface**: curated cards (name · size · license · DISK verdict from free-space + RAM note from fit engine's measured-peaks pattern) → download into ComfyUI's models dirs via the existing downloads plumbing (bridge/routers/downloads.py pattern), progress surfaced, resumable/failed-state honest. Download never blocked; disk verdict advisory ("needs 12.2GB · 47.8GB free · leaves ~35GB").
3. **Generate form** (our panel, NOT the embedded ComfyUI tab): prompt / size / seed / steps / (video: duration) mapped onto the template's API-format JSON (SwarmUI's param→graph pattern; Krita plugin's connect-time validation discipline: check nodes+models exist BEFORE submit, name what's missing with its download card). Submit via POST /prompt, progress via WS (the new /api/jobs API at our pin for queue state), result via /view into the gallery.
4. **Gallery**: keep-everything, per-item size + running total in the strip; open-in-Finder; deep-link "open this graph in ComfyUI tab" for power use.
5. **Stock-nodes-only FENCE** + gate test (supply-chain ruling: LLMVISION/Ultralytics incidents class). Zero custom nodes in S1-S3.
6. **Measurement**: first generation of each curated model runs as a measured spike (measure_music.sh pattern) — record peak phys_footprint + wall time; surface both on the card afterward ("last run: 68s · peaked 21GB") — fit.py cannot price torch diffusion; measured truth only, advisory always.
7. Disk-first UX everywhere: free space in the surface header; every size cited; gallery total visible. All-designs rule; USER-EXPLAINERS section; journeys walked live (download→generate→gallery→re-open) per doctrine.

## Sequencing
index.html is contended (UI-polish → goose queued). S1 builder owns NEW files (bridge/panel/comfy.html or equivalent + bridge/routers/comfy.py, registered in _LANES/appsrc.FILES) — the sidebar/tab entry line in index.html is added by whoever owns index.html when S1 lands (one line, Fable coordinates). S2 (more video/upscalers incl. the H3 revisit) and S3 (audio: ACE-Step/Stable Audio) follow as their own slices with the same rules.

---

# SPEC v2 — the Generate page REDESIGN (Fable, 2026-08-29, after Debi's verdict on S1)

Debi's verdict on the shipped page: disaster-class ("worse than comfyui... essay for every
button"). The BINDING design source is docs/research/2026-08-29-generate-page-redesign.md —
§4's IA is the wireframe (its §4.0 traceability table is the argument), §5's honesty ledger
is the conservation law (all 17 mechanics survive, demoted never deleted), §1 is the sin
list that may not recur. Doctrine 8b applies: the design derives from our principles
(impeccable + Studio spec + the v1.5.34 chip grammar), corroborated by the 11-product survey.

## Debi's four fork answers (final)
1. Gallery = RECENT STRIP under the result stage + "All results ▸" expanding in place.
2. Disk chip = ALWAYS in the header (amends the contextual-only proposal; still ≤7 budget
   with it — the researcher counted it in).
3. Graph + Open-template = behind each item's ⋯ overflow. Kept, invisible at rest.
4. First run = the composer, with the two curated Get buttons (sizes shown) in the empty
   result stage. The product's face stays the product.

## Non-negotiables
- AT REST ≤7 elements per §4 (status chips · result stage · recent strip · prompt ·
  Image/Clip toggle · model chip · Generate) + the always-on disk chip per answer 2.
- The sentence rule: prose ships at rest ONLY as an action label, a live decision, or the
  first-run invitation. Everything else = chip + hover/tooltip (the v1.5.34 tipBind grammar,
  one verdict object) or Help. USER-EXPLAINERS carries the essays — the page never duplicates it.
- Models = a SHEET in the v1.5.34 row/chip grammar (state chips carry the exact cardAction
  states; license = a chip whose hover holds the link; file manifests/sha prose = hover;
  Wan colour-defect = one amber chip, same object echoed on the composer's model chip).
- Pixelmator write-back: a finished run's actual values land in the ordinary controls/caption
  chips (seed-reset behavior preserved).
- Toast pattern from v1.5.39 stays (alert() is banned — silent no-op in the shell).
- ALL-DESIGNS (six looks by computed values); copy-provenance; the honesty ledger §5 verified
  item-by-item in the report (a table: mechanic → new home → proven where).
- bridge/routers/comfy.py sits AT the 1500-line facade ceiling (ledger S8): if the redesign
  needs ANY router growth, first extract curation+graph builders to bridge/core/comfycur.py
  (registration rules per the facade manifest) — never squeeze under the ceiling by deleting
  comments.
- The Generate page redesign REPLACES the current comfy.html surface in place (same /comfy
  URL, same ❖ Generate entry) — Debi's scrap-or-keep fork applies to MUSIC, not here.

---

# SPEC v3 — Generate visual rebuild (Debi's GO, 2026-08-29): "Patchbay" (generate-j)

BINDING design source: docs/mockups/2026-08-29/generate-j.html + visual-craft.md §3c.
Structure (Debi's spec, round 3): compact left settings rail (Draw Things density,
Basic/Advanced gate), ONE center media stage with click-to-fullscreen, prompt + key
options in the center's lower region, slim right results rail (first ~2 rows visible,
click puts it on stage).
DEBI'S ADDITIONS AT GO: (1) the media stage is RESIZABLE (drag to make it smaller,
layout reflows) and SPLITTABLE into up to FOUR panes (1/2/4 layouts) — each pane holds a
result for side-by-side comparison; click any pane to promote/fullscreen; (2) THE
REAL-DATA RULE: the mockups carried invented depiction data — the build surfaces ONLY
real values from the real endpoints; every chip/number/thumbnail is live or absent, never
decorative. All v2 conservation (sentence rule, chips, honest mechanics) carries forward.
