# v1.5.87 upstream update wave — decision and evidence contract

Status: candidate work in progress. A manifest pin is not a release claim.

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
