# v1.5.88 media relocation, selector truth and fit calibration

Status: shipped and verified. The release section records the clean repository gate,
installed affected journeys, exact-state restoration, version commit, push, and FAT
archive audit.

## Scope and preservation boundary

- Repair the Generate model/type selector as one visible transaction.
- Repair ACE-Step's stale post-rename Mach-O runtime path and prevent recurrence in both
  production installation and the A/B research tool.
- Prove fresh MiniMax Music, ACE-Step, SDXL and Wan output from the renamed live root.
- Calibrate A6 with real MLA, non-Gemma SWA, MLX and vision/projector loads.
- Compare Wan 2.1 and Wan 2.2 under the same local workflow and make a licence/size
  decision for MiniMax H3 without downloading its enormous repository.
- Preserve every user layout, output, model, registry row, credential and optional
  component. No third-party source file is edited and the archived original project is
  untouched.

## U159 — Generate selector transaction

The reported screenshot was reproduced: changing the Model select from SDXL to Wan
updated the model badge but could leave the focused native Type select showing the old
SDXL workflow. The renderer's focus-preservation rule was correct for an open native
menu but wrong after that menu had committed `change`.

The model handler now ends only that completed select interaction before rendering, and
the deferred-paint flush includes the picker. It does not alter layout, drag, resize,
theme, gallery or workflow-conversion behavior. Executable JavaScript contracts pin the
focus case and the required Model+Type update. In the installed WKWebView, SDXL showed
five SDXL workflows, Wan 2.1 showed 17 Wan workflows with a Wan Type, and switching back
restored SDXL's type list.

## U160 — ACE-Step relocation and music/Generate real outputs

The first direct ACE-Step launch after the product rename failed before inference. Both
native executables still carried an absolute `LC_RPATH` to the retired
`Application Support/Harness` build directory, so dyld could not find the co-located
ggml libraries. A generic executable bit or component-green check could not prove this
native launch seam.

The installer now requires the only stable relationship: `ace-lm`, `ace-synth` and the
libraries move together in `build/`, so the binaries must carry only `@loader_path`.
Rebuild is transactional: preserve the previous build, create a genuinely empty CMake
build, configure with install rpath, validate both binaries' exact rpath and `--help`
launch, then remove the backup; any failure restores the prior directory. On a pin move,
tracked source must be clean and a failed replacement restores both the prior source SHA
and prior build, so an old binary can never be mislabeled as the new pin. The A/B research
entry point enforces the same relocation contract rather than reusing a stale build.

Live repair found 70 Mach-O artifacts, zero remaining old-root rpaths, and both ACE
entry points launched directly. Fresh renamed-root outputs:

- ACE-Step: 10.0 s, stereo 48 kHz, 24-bit WAV, SHA-256
  `edbc035717bdb92450f476321653af4fce5051a3f93a8d667d420f076f2c3284`.
- MiniMax Music3: 14.988 s, stereo 44.1 kHz WAV, SHA-256
  `7c885b17fd57d85d822e3c5eacafc0998c54a44860201e784e1def9c67c28917`.
- SDXL: 512×512, 12 steps, 13.1 s, measured 13.06 GiB peak, SHA-256
  `3c184bfd97222ba9163e35fb9e6cd889baa451e2001c23ef7d9bf70d9929c238`.
- Wan 2.1 smoke video: a non-empty MP4, SHA-256
  `c535a79ce0aee9454a94fcccd3cbefee63b3f78f622043bab2ec2e607e72c744`.

The exact output files live in the sibling `outputs/` workspace root. Release QA
re-hashes each file rather than trusting the recorded digest.

The current `9761469` and candidate `c9045e2` ACE builds were compared with the same
15-second prompt, seed 20260907, 8 turbo steps and WAV24 output. Current took 24.00 s;
candidate took 26.87 s, about 12% slower. Both audio files are surfaced for human
listening. Because the candidate rebases the entire ggml layer and has no demonstrated
quality win, the production pin remains `9761469`.

## U161 — model eject must not fail after stopping

The A6 setup exposed `NameError: time is not defined` after the public eject operation
had already stopped the owned runner. `bridge/routers/models.py` now imports `time`, and
an executable regression drives the actual `_eject_runner()` wait/clear-state seam. The
installed API returned success, the runner stopped with port 6767 free and blank live/pin
state, and Switch restored the exact prior Qwen3.8 27B. Every protected live-state file
returned to its pre-test SHA-256.

## U162 — A6 real-load calibration

The full method, receipt table, architecture inspection and honest limits are in
`docs/research/2026-09-07-a6-real-fit-validation.md`.

Measured evidence supports the existing MLA and non-Gemma SWA calculations on the exact
test models at 16k and 64k, with engine-allocation error between -0.40% and +0.02%.
Vision/projector measurement proves the engine log omits most projector residency; the
existing vision allowance is safely conservative on the measured Qwen3.5 pair. The
installed MLX 27B exposed a real bug: its decoder config is nested and mixes 16 full
attention layers with 48 stateful linear layers, while the old formula priced zero
cache/state. The fit engine now reads the pinned runtime's real shape and 2,048-token
prefill chunk. Short and 4,148-token runs bracketed measured physical footprint within
about +10.3% and -1.5%.

This is calibration, not universal MLX validation and not a new hard blocker. The
installed Models view also rendered the live 27B's measured footprint separately from
engine allocation and retained advisory fit arithmetic for every non-live row.

## U163 — Wan 2.2 and MiniMax H3 decisions

The official ComfyUI-repackaged Wan 2.2 files required for the tested workflow add
11.41 GB and total about 18.1 GB with the already-shared UMT5 encoder—below the user's
40 GB boundary. The official full repository is about 34.2 GB and Apache-2.0.

Wan 2.1 and Wan 2.2 received the identical prompt (a brass compass on walnut), seed
20260907, 320×192, 17 frames, 16 fps, 20 steps and CFG 6. Wan 2.1 took 30.6 s and peaked
at 19.60 GB; Wan 2.2 took 22.8 s and peaked at 19.77 GB. Both results were visibly
unusable on this Mac—blur/colour failure for 2.1 and block artifacts for 2.2. Speed alone
does not earn a starter slot. Wan 2.2 remains a discoverable workflow with no quality
claim; neither model is promoted as a recommended video starter.

The exact comparison-video SHA-256 values are
`5f5e0126a167010a708cbca107b71733c7f91779fa364aa51a1f2c9b78136e40`
(Wan 2.1) and
`570cb8e620b84a1cee4240f78a47f6739145915bafc53e915f4e87c35ce1c186`
(Wan 2.2). Contact sheets are retained beside them so the visual verdict does not depend
on a prose recollection.

MiniMax H3's current open-weight workflows are not eligible to become the requested
under-40 GB starter: Comfy's own index declares 44.45 GB for image/reference workflows
and 56.91 GB for text-to-video, while the official Hugging Face API reports about
354.02 GB for the complete repository. Its community licence also carries territorial
terms that a user must evaluate for their own use. Those facts do **not** authorize the
app to disable an optional discovered workflow or police a user-acquired model. No H3
bytes were acquired in this wave, no H3 starter was added, and optional local workflows
retain normal Comfy availability. Hosted-API workflows are governed by the separate
local-only boundary below, not by the H3 size/licence research.

## U2 decision, no implementation

The current shared `~/.hermes` behavior is retained for continuity. A future opt-in
isolated mode should use upstream Hermes profiles, distinguish product-state isolation
from strict tool-home isolation, preview and copy rather than move state, and allow a
clean return to Shared. See
`docs/research/2026-09-07-hermes-profile-boundary.md`. No profile or session was changed.

## U164 — local-only Generate boundary

ComfyUI v0.34.5's first-party catalogue includes hybrid templates that require local
weights and hosted partner nodes. Seven current rows have cloud-branded titles; the
decisive evidence is not those names but the running engine's own node metadata:
`api_node: true` and/or `python_module: comfy_api_nodes.*`. The former implementation
treated those nodes as stock—correct for supply-chain provenance, wrong for locality—and
could offer local weight downloads before discovering the hosted dependency.

The catalogue now classifies those workflows as **not local** before Download, and the
submission route independently checks the same metadata before either returning a
missing-model/download response or executing. When ComfyUI is offline, locality is
unknown and Download is withheld until the engine can answer; absence of evidence is
never treated as local. This adds no cloud provider, credential, model or network
execution. Local Comfy workflows, including optional user-acquired models, retain their
existing discovery and execution behavior.

## Release acceptance — v1.5.88

- The complete shipping gate passed: 576 contract checks with only the four declared
  checkout-local Aider skips; 716 repository tests with two upstream deprecation
  warnings; every JavaScript suite; Bash 3.2 syntax; Swift parse; line/byte ceilings;
  identity and canonical-root guards.
- The installed Generate journey proved SDXL (five image types) → Wan 2.1 (seventeen
  video types with a Wan default) → SDXL as one visible transaction. After an explicit
  page reload, a known hosted-node workflow rendered `not local`, exposed no download,
  and kept Generate disabled. The stale pre-reload tab retained old JavaScript exactly
  as documented by `ship.sh`; it was not mistaken for current served behavior.
- ACE-Step's 70 Mach-O artifacts contain no retired-root runtime path; both executables
  launch directly with only `@loader_path`. Fresh ACE-Step, MiniMax, SDXL and Wan files
  re-hashed to the exact values recorded above.
- The public Eject route stopped only the launch-owned runner, cleared live/pin state,
  and returned success. The exact prior 27B was restored; all ten components finished
  running and healthy.
- `motdeck.yaml`, `models.json`, `nav.json` and `.env.local` match their pre-journey
  digests byte-for-byte. No model file, layout, credential, third-party source file, or
  archived project was changed.
- The final release was committed and pushed before the clean FAT build. The mounted
  archive was checked against its seed ownership manifest and surfaced as
  `dist/MOT Deck.dmg`.
