# v1.5.87 upstream update wave — decision and evidence contract

Status: shipped and verified. A manifest pin was not treated as a release claim; the
accepted candidates below earned the release only after their affected installed and
human-entry journeys passed on the real stack.

## Non-negotiable boundaries

- Canonical repository only; the retained Claude-era project is never read as runtime
  authority and is never modified.
- Third-party sources stay unmodified. Submodule/git-checkout pins and first-party
  adapters may move only when the supported upstream seam survives.
- Live `motdeck.yaml`, data, sessions, models, credentials and generated outputs are
  conserved. No whole-file parity copy is permitted.
- FAT-seeded vendor trees have no `.git`, so they are never updated with a blind
  `rsync --delete`. `scripts/update_seeded_vendor.py` derives ownership from the exact
  old/new Git trees, preflights collisions, preserves every untracked path, backs up
  every replaced byte, and verifies the post-write tree. Its check mode passed against
  the real Odysseus (32 changed paths) and SearXNG (143 changed paths) snapshot trees.
- Live release pins move through named, grouped compare-and-swap migrations. OpenCode's
  version and both platform digests are one group; llama.cpp's tag and digest are one
  group, including the known historical live shape where the digest field was absent.
  Mixed old/new state is a hard refusal; operator-custom values are preserved.
- Each candidate has its own rollback point and affected journey. One green component
  cannot launder another candidate's missing evidence.
- No Docker is introduced. Docker-only upstream tests are classified as unexecuted and
  disjoint where that is true; they are never counted as passes.

## Candidate ledger

### OpenCode 1.18.23 → 1.18.29

- Exact macOS npm artifacts independently hashed:
  - arm64 `1fc08fee8b4984c1306c826b8c0e2c367fd9eeb4d4c3707469194e3fea047e72`
  - x64 `d9e2270b9040d7ce140df629773c68f15222c7a6c882f16921d36aa4c9200ae2`
- npm SHA-512 remains a second authority, not a replacement for the recorded SHA-256.
- Isolated arm64 binary reports 1.18.29; `serve` preserves explicit loopback host/port,
  mdns/cors controls and the XDG-contained runtime. `/global/health` and `/provider`
  exposed the expected local llama.cpp provider and eight registry models with
  autoupdate disabled; shared OpenCode homes were unchanged.
- Release gate: install through the pinned installer, actual native tab, provider/model
  catalogue, PTY/tool turn, and requested→served disclosure.

### Odysseus dev c9dd68d → 934d23c

- Six commits; 32 files. Adds owner/tool authority work and changes PostgreSQL install
  dependency to `psycopg2-binary`.
- 303 focused upstream checks passed. One Docker-image test skipped because the expected
  image was absent; the no-Docker product does not exercise that path.
- Isolated setup, human credential API login and authenticated root passed with a new
  temporary data directory.
- The app contract initially caught a source-shape change around message metadata.
  Investigation proved the metadata is now passed through a sanitizer that removes only
  server-owned approval authority; executed evidence confirms Direct timing/model keys
  survive. The contract follows the behavior rather than the old one-line spelling.
- This pin does **not** supply or close U72, U139 or U142.
- Release gate: rebuilt venv; managed native login handoff; Direct persistence metadata;
  Agent, attachments, session/history actions, managed endpoint and restart journeys.

### SearXNG 9fea412 → c7f3080

- 139 changed files and a networking migration from httpx to `curl_cffi`.
- Exact-source isolated Python 3.13 install succeeded with `curl_cffi==0.16.1`; a real
  JSON query returned 40 results from multiple engines.
- Release gate: rebuild the managed venv, private loopback search through SearXNG,
  bridge web-search, Odysseus search, restart, and FAT dependency review.

### VoiceStudio 0.5.0 → 0.5.1

- Although semver calls it a patch, the diff is 467 files and approximately 65k added
  lines: startup/worker/readiness changes are high blast.
- The candidate preserves the OMNIVOICE bind/data/API variables, `/health`,
  `/startup/progress`, MCP mount and translation-provider seams. Isolated source boot
  answered health and readiness using the existing venv; that did not prove installed
  package metadata or a rebuilt lock, so it is only preflight evidence.
- Release gate: `uv sync --frozen` rebuild, version/readiness truth, native tab, real TTS,
  real STT where a profile/input exists, MCP discovery/call, data-root conservation and
  restart. If any prerequisite is user-owned, the unwalked boundary is named rather than
  faked.

### Voicebox 0.5.0 retained; dependency graph hardened

- Upstream release remains v0.5.0. Three Git sources were floating independently of that
  tag: LinaCodec, LuxTTS/Zipvoice and Qwen3-TTS.
- Exact commits are now manifest-owned. A temporary requirements copy rewrites exactly
  the two expected upstream lines and refuses any changed/additional Git source.
  Qwen3-TTS is force-reinstalled with `--no-deps`, then PEP 610 `direct_url.json` for all
  three distributions must name the recorded commit.
- Release gate: executed hostile rewrite/provenance tests and installed component
  provenance. No third-party source file is edited.

### ComfyUI 0.34.1 → 0.34.5

- 30 changed files plus workflow-template updates; CLI and server seams remain.
- A genuinely clean `--base-directory` exposed a v0.34.5 first-launch assumption:
  `custom_nodes/` is enumerated before upstream creates it. An already-populated install
  hides the failure. The installer now creates `custom_nodes`, `models`, `output`,
  `input`, `user` and `temp` before first launch.
- With the installer-guaranteed shape, isolated MPS startup reported v0.34.5 and 916
  nodes including the core nodes required by Generate.
- Release gate: clean-base fence, managed upgrade without touching model/output data,
  native Comfy tab, Generate catalogue, one real image and one real video journey using
  already-installed prerequisites, gallery/graph persistence and restart.

### llama.cpp b10662 → b10827

- This is a dedicated high-blast runner wave: 431 changed files, including Metal,
  KV-cache, multimodal and server code.
- Exact macOS-arm64 asset SHA-256:
  `28550b2304a138e72fb5700132917052138aa47895dfa92dfd26a820dd905658`.
- Every launch flag MOT Deck emits is present. An isolated 4B load proved loopback bind,
  API-key-file 401/200 behavior, `/v1/models`, metrics and authenticated inference.
- Release gate: install through the digest gate; start the current 27B with its real
  projector and saved load settings; model/status truth; Direct, Agent and Hermes turns;
  vision input; named-key behavior; measured allocation log; restart and rollback.

### Unsloth 0.1.804-beta → 0.1.806-beta

- 1,386 changed files and approximately 176k additions; this is not a safe patch-sized
  bump despite the tag number. The isolated home override, update-disable and current
  server CLI flags remain, and the candidate help path runs in the current managed venv.
- Hold unless a rebuilt editable Studio install, SPA, isolated-home startup, version
  truth, native login and a meaningful model/train/inference action can be proven without
  touching standalone Unsloth. A help screen is not sufficient evidence.

### acestep.cpp 9761469 → c9045e2

- The requested short commit resolves to
  `c9045e270c3145a288579fee4f298286e03aa881` (not the initially inferred full suffix).
  Its only top-level change rebases the entire ggml submodule from c044c6f to d5152bf.
- Because Metal behavior is inside that submodule, source shape alone cannot authorize
  the bump. Keep the measured pin until the same prompts/settings/weights produce an
  audio A/B with runtime, peak memory, format and subjective artifact comparison.

## Product decisions clarified alongside the wave

- **P5:** Image and video already ship in Generate. The remaining specification is an
  Audio/SFX/foley/ambient decision plus measured video-family expansion; songs remain
  Music and separation remains P6.
- **A6:** S5 supplies the measurement mechanism, not the missing data. Real MLA,
  non-Gemma SWA, MLX and projector-bearing loads must each compare prediction with
  engine allocation truth before their formulas can be called validated.
- **U2:** Shared `~/.hermes` maximizes standalone continuity but lets MOT Deck reconcile
  shared state. Isolation gives clean ownership but separates history/channels. The
  recommended future shape is an isolated home plus explicit optional import; no silent
  migration occurs without the user's ruling.

## Release evidence — v1.5.87

### Accepted updates

- **OpenCode 1.18.29:** the installed managed route opened its own workspace composer,
  preserved the local llama.cpp provider and eight-model catalogue, and completed a real
  human-surface turn with the exact response `OPENCODE-1.18.29-REAL-OK`. Its upstream UI
  still displays its selected Parable alias while the single resident runner served the
  loaded Qwen3.8 27B; MOT Deck's existing mismatch evidence names that truth and routes
  to Models. No user project was added or changed.
- **Odysseus dev `934d23c0`:** rebuilt environment, managed native authentication
  handoff, authenticated root, Direct Chat, Agent and durable history all passed. A real
  Agent turn returned `AGENT-B10827-OK`; requested and actually served model evidence
  remained distinct. Settings, sessions, uploads and protected key bytes were conserved.
  This upstream pin does not close U72, U139 or U142.
- **SearXNG `c7f3080a`:** rebuilt with `curl_cffi==0.16.1`; its private JSON search
  returned real multi-engine results and the bridge search seam remained live. Existing
  settings were not replaced.
- **VoiceStudio v0.5.1:** version/readiness, native Launchpad, seven MCP tools, voice
  catalogue and real OmniVoice synthesis passed. The produced 24 kHz WAV was then used
  as a real cross-component Voicebox transcription input.
- **ComfyUI v0.34.5:** clean-base directory preflight, 916-node discovery, native graph
  UI, a real 96×64 PNG, and a real 128×128 five-frame H.264 video passed. The video ran
  through MOT Deck's Generate API in 23.5 seconds, measured a 6.41 GB process peak, and
  was ingested as `motdeck/video_00001_.mp4`. Model, input, output and user roots were
  never replaced.
- **llama.cpp b10827:** the exact digest-gated Apple-Silicon archive reports build 10827.
  API-key-file 401/200 behavior, authenticated model/metrics, the current 27B plus its
  real projector, raw chat, Direct Chat, Agent, Hermes, basic vision input, status truth,
  stop/restart and same-model restoration passed. The harder OCR fixture's `5729` was
  misread as `5730`; that was not counted as a pass. An unambiguous large `MOT` fixture
  proved the multimodal path without inflating the OCR claim.

### Retained version, hardened graph

- **Voicebox stays v0.5.0.** Its three Git-only dependencies are now exact and their
  installed PEP 610 provenance is verified. The real Whisper journey exposed a separate
  upstream packaging hole: a freshly rebuilt server was green, but lazy model loading
  failed because `mlx_lm`, `sentencepiece` and `sounddevice` were not installed by the
  declared base graph. MOT Deck now pins and verifies `mlx-lm==0.31.1`,
  `sentencepiece==0.2.2` and `sounddevice==0.5.3`; `mlx-lm` is installed without
  dependency resolution so it cannot replace Voicebox's tested Transformers 4 line.
  A real cached Whisper Medium transcription then completed over the VoiceStudio WAV.
  Existing upstream resolver conflicts remain honestly documented; a green server is no
  longer accepted as proof of lazy STT readiness.

### Researched holds

- **Unsloth remains v0.1.804-beta.** The proposed beta changes 1,386 files and roughly
  176k added lines. A help path and compatible flags do not prove its SPA, isolated home,
  login and meaningful train/inference action; the blast radius therefore failed the
  update gate rather than being hidden beneath the release.
- **acestep.cpp remains `9761469`.** The candidate changes its entire ggml submodule.
  It remains held until the same prompts, settings and weights can be compared for audio
  quality, artifacts, runtime, peak memory and format. Source recency is not an audio A/B.

### Transaction and preservation evidence

- `scripts/update_seeded_vendor.py` updates only Git-owned paths between exact old/new
  trees, refuses local collisions, preserves untracked paths, backs up replaced bytes,
  and now rolls the whole planned set back if either a write or its final byte-for-byte
  postcondition fails. The postcondition failure is injected permanently in the suite.
- Grouped manifest migrations are compare-and-swap transactions; mixed or operator-
  customized old/new groups refuse rather than guess.
- Pre/post SHA-256 remained identical for `data/.env.local`, `data/models.json`, and
  `data/nav.json`. The current runner pin and served model returned to the same Qwen3.8
  27B after the Comfy video memory window. All ten components finished installed,
  running and healthy.
- Complete release gate: **570 contracts passed, four existing checkout-local Aider
  cases skipped; 716 repository tests passed with two deprecation warnings; every
  JavaScript suite passed.** The four skips are not candidate tests and no U157 test was
  skipped.
