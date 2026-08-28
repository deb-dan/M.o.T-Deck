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
