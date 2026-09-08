# MOT Deck — Roadmap

Reader-facing status: what the product now does, what's actively being worked on, and
what's next. This is not a changelog — for line-by-line history read `git log`; for the
full deferred-work backlog (every paused plan, audit finding, and user-reported quirk,
each with a status and a verify-still-open command) read **`docs/UNFORGET.md`**, the one
source of truth for deferred work. This doc summarizes themes and points there rather
than restating rows.

Current shipped release: **v1.5.92** (see `VERSION`). Written 2026-09-08.

<!-- current-status:start
in-progress: U170
next: P6 P3 P5 S4 S7 U3
later: U2 U9 U14 U26 U28 U29 U44 U45 U47 U57 U58 U168 U169 U171
someday: S2 U4 U5 U6 U8 U43 U46 U68
blocked-later: P1 U1 U34 U72 U91 U139 U142 U144
blocked-someday: P2
withdrawn: U147
current-status:end -->

---

## Done

**Existing-feature reliability (v1.5.91–v1.5.92).** Direct streaming preserves split
reasoning and partial answers, download controls await the previous writer, storage
previews and rollback receipts preserve ownership and partial results, model-setting
saves remain ordered and bound to their selected model, refused conversation deletion
preserves local media/reasoning, and Odysseus recency has explicit UTC. Full gates,
installed native checks, state conservation and recoverable bundles are recorded in
`docs/RELEASE-v1.5.92-RELIABILITY.md`. U170 stays open for exhaustive review coverage.

Grouped by theme, with the version range where the shape landed. "Done" means shipped,
gated by tests, and walked live on the real stack — not merely coded.

**Ownership-safe removal, reset and optional setup (v1.5.90).** Mission Control now
offers an Uninstall preview for every optional runtime; Music can remove either engine's
exact model/integration payload; Generate can remove one workflow's or one model family's
currently downloaded files while naming every other workflow that shares them; and the
Chat/Agent plus Hermes lanes each expose a counted clear-all preview. Apply operations
consume short-lived evidence-bound tokens, stop only launch-provenance-owned children,
revalidate after preview, and move exact targets to Trash with rollback rather than
recursively deleting guessed directories. Normal runtime removal preserves sessions,
settings, workspaces, documents, outputs and model weights. Full uninstall moves only the
verified app bundle and canonical support root; Factory reset additionally requires an
embedded FAT seed whose version exactly matches the running release before it can enable.
Fresh core setup can then add allowlisted optional tools through their existing pinned
installers. The API catalogue distinguishes configured routes from a runner that is
actually available, and the Chat composer keeps its attach, textarea, microphone, Send
and audio-mode controls inside one field across design axes. The installed preview/cancel
walk caught and removed one whole-root byte scan that had blocked the bridge for roughly
30 seconds; destructive previews now omit that presentation-only total truthfully and
remain responsive. U168/U169 preserve the two intentionally narrower follow-ups: shared
third-party data erasure and manifest-proven source-tree cleanup.

The final clean FAT artifact is bound to release commit `78cb0c1` with no dirty files.
Both the built and mounted app identify as `local.motdeck.app` / `MOTDeck` / `1.5.90` and
pass deep strict signature checks. Replacing the installed bundle preserved byte-identical
live manifest, secret, model-registry and navigation files. The matching embedded seed
enabled Factory reset only after the real v1.5.90 app was installed; its human preview was
then walked and cancelled with the typed-confirmation Apply control still disabled.

Music memory remains deliberately separate at the presentation layer. MOT Main's compact
`Memory for a model` tile continues to describe resident chat/runner capacity and current
system pressure; Music owns its engine planning, fit warning, and measured render peak.
An active Music job may still affect the truthful global pressure/free-memory reading.
S4 will unify the underlying Voice/Music spawn advice with the shared fit engine without
turning MOT Main into a combined Music dashboard.

**The app shell (MOT Deck / MOT Main).** Ten live components on Mission Control —
Hermes, Odysseus, SearXNG, VoiceStudio, Voicebox, ComfyUI, Unsloth, OpenCode, DeepSeek,
and the runner — plus Goose CLI and Goose UI as a coexisting pair, LOffice (ONLYOFFICE), and the
Music/Compose surfaces. Sidebar and tab strip are customizable with saved layouts,
9 stable pins + a 3-slot MRU window (v1.5.49), and neighbour-append placement for new
rows so a customized machine doesn't dump new entries at the tail (A8, v1.5.49). Six
looks (Editorial, Warm Paper, Luxury Gold, Cyber, Studio dark, Studio light) verified by
computed value across the panel, not just by eye. The **M.O.T app icon** and
**⌥⌘Q "Quit Everything"** (stops every component through the same identity-verified path
the per-component Stop button uses, then the bridge, then the app — ⌘Q alone still
leaves the stack running so reopening is instant) shipped v1.5.71.

**Model runner and registry.** `core/modelreg.py` is the one `offerable()` definition
every seeder imports — chat, not hidden, not absent, file-still-on-disk — so Rescan is
both the prune and the fan-out (S29, v1.5.64: this is what killed the "dead models keep
appearing" complaint at the source, not per-app). The fit advisor prices context/KV/layer
costs against real GGUF headers, including per-layer head-count arrays and per-arch SWA
patterns (U23, v1.5.63). A model switch now rebinds every dependent lane automatically —
Hermes, Odysseus, both goose slugs — and a stable Pin-this-model action ends pin≠served
drift in one click (S28, v1.5.62, "the coherence wave"). RAM/resource gates warn and
recommend with measured numbers; they never hard-block (Debi's advisory-gates ruling,
2026-08-28). U75 (v1.5.78) replaces the old file/directory existence shortcut with one
cheap structured integrity verdict for GGUF, split GGUF, declared projections, and MLX
config/index/weight manifests. Discovery, every catalog, status, main/aux launch,
switching, and the panel now agree: incomplete artifacts are diagnosed and retained for
inspection, but never offered for a fresh load.
U76 (v1.5.79) keeps physical source availability as a separate evidence layer: an explicit
Rescan records the ready artifact's real path, device, mounted ancestor, and names-only
manifest. A later missing artifact on the same available source is removed per row;
an unavailable mount is retained; and a legacy missing row without trustworthy evidence
requires an exact, transactional second-step confirmation. Registry writers now share
one re-entrant cross-process lock and atomic deterministic serialization, so concurrent
Rescan/status/download work cannot lose an update. v1.5.80 corrects the claims that were
too broad: the original U75 probe is structural completeness, not proof of runnability,
and U76 alone cannot see a manager-level removal while bytes remain. Source adapters now
apply manager membership only to manager-owned rows (LM Studio today), preserve unmanaged
filesystem rows, and reconcile into the existing registry rather than creating a second
catalog. Format-aware GGUF/safetensors/MLX checks, row fingerprints for confirmation,
legacy audio dedupe, and crash-recoverable app-owned deletion close the demonstrated gaps.

**Local API access.** Mintable/revocable API keys apps' own Add-Provider forms can
consume (`--api-key-file`, unions with the built-in key) plus an Unsloth-style API page —
base URL, status, loaded model, route catalogue, honest request log split by lane — both
sidebar-only like Help (S32, v1.5.68). A Help/USER-EXPLAINERS §API section documents it
(v1.5.72).
v1.5.81 moves M.O.T-managed launch credentials into one strict, atomic `0600` local
secret store and blanks their live-YAML fields. Rotation is transactional across the
managed Odysseus endpoint and every installed consumer; the runner key is no longer
visible in process arguments. The real Goose Add Provider journey used one temporary
minted key for a real 27B prompt, then removed only that key/provider and restored the
original managed provider. Auxiliary-key rotation remains separate because its existing
Odysseus Background Tasks endpoint may be user-owned (U142).
v1.5.82 closes the human-workflow gap that release missed: the native Odysseus tab now
enters through M.O.T's bridge, reuses a valid browser session or logs in server-to-server
with the protected credential, transfers only Odysseus's HttpOnly session cookie, and
redirects into the unmodified upstream workspace. The weak repository password is not
restored, printed, placed in a URL, or injected into browser JavaScript.
The incident also made backend correctness and human reachability separate release
contracts. Every affected native/sidebar/overlay entry now requires an installed-shell
walk through its first meaningful action; health, HTTP 200, backend login and stored
configuration remain smoke evidence only for that affected handoff. Untouched
third-party workflows retain their own health/contracts and do not require a ceremonial
prompt, render, training job or user-owned login on every release. The current whole-app
boundary—including walked, unaffected, conditional and reproduced rows—is recorded in
`docs/research/2026-09-06-human-entry-journey-audit.md` (U146).

**Component isolation ladder.** Odysseus, Hermes, Goose (CLI + UI), and OpenCode each
gained a named local provider/config entry mirroring the full model registry, so picking
a model inside any of these apps survives restarts without being clobbered by our own
seeding (v1.5.49 – v1.5.58). Each seeder follows the same never-clobber shape: seed when
unset, replace only when the configured choice is provably stale, never re-enable a
disabled row.

**Goose.** Both lanes coexist — Goose CLI (PTY, terminal-shaped) and Goose UI (the
upstream desktop renderer served locally over ACP). Session continuity survives a reload
(the PTY's lifetime is the process's, not the socket's) with a sessions strip fed by
goose's own session list, resume/prune, and a per-chat delete via a hover ✕ (v1.5.40 –
v1.5.66).

**Media surfaces.** Generate was rebuilt onto the "Patchbay" layout — resizable/
splittable media stage (up to 4 panes), real-data-only chips, ComfyUI's 26-model/
78-workflow catalogue discovered live from upstream's own index (v1.5.41 – v1.5.53).
Compose was rebuilt onto "Spectrum" — a draggable block grid, section-coloured waveform
from measured loudness (never invented structure), and a Compose surface as an
alternative to Music that leaves Music byte-untouched (v1.5.43 – v1.5.47). LOffice
(ONLYOFFICE) is a one-editor app across all three file types with ONLYOFFICE's own AI
plugin wired into the ribbon, PDF export via x2t, and an agent changeset-consent lane
(human-only atomic apply + undo).

**Downloads.** Every model/voice download is verified by size + sha256 before being
registered — a cleanly truncated stream used to register a corrupt model as done (A10,
v1.5.44). The panel renders a first-class Corrupt state with Retry, and any state it
doesn't recognize names itself rather than borrowing the word "cancelled" (A14, v1.5.45).

**Reliability and process hygiene.** Components no longer die when MOT Deck quits —
`nohup` was never real detachment; every spawn now goes through `setsid` so a quit's
process-group kill can't reach through the bridge into a component (U52, v1.5.69). The
runner's pidfile now records the actual port listener rather than a `$!` that can name a
losing retry attempt (U54, v1.5.72). A stale Failed-card banner that kept naming an old
error after the runner recovered is fixed — a running-twice observation retracts the
sentence entirely (U60, v1.5.72). The whole family of kills is pidfile-scoped and
identity-verified in shell scripts (U19, v1.5.58). v1.5.80 replaces the remaining
name/path/port ownership guesses with no-follow launch-provenance claims bound to PID and
kernel birth, then re-verifies the claim immediately before signalling. PID files are
reports, not authority; known detachment failure stops the launch rather than falling
back into the unsafe process group. YAML and registry writes share locked atomic writers,
the bridge releases only its own PID claim, and cross-site mutating requests fail closed.

**Conversation continuity and embedded apps.** v1.5.80 keeps Chat and Agent producers
alive when the panel detaches, changes lane, or reloads. A bounded 32 MiB/8-active-turn
replay store preserves the complete event grammar and reconnects the persisted,
whitelist-validated selected lane (U31/U32); a
request marker verifies Odysseus history persistence and makes the remaining at-least-once
limit visible. LOffice reloads a read-only projection of its stored visible transcript,
never its hidden workbook grounding, and names its own stored session without overwriting
an older conflicting `loffice` history. Hermes WhatsApp disable now reconciles YAML,
environment and owned process state transactionally while keeping credential deletion a
separate explicit action. Goose empty-session cleanup, historical Odysseus unavailable-
model labels, live-model reporting, and OpenCode runtime-catalog drift are also closed.
v1.5.81 extends the same ownership principle to Hermes without creating another
transcript: Hermes remains durable-session authority while the bridge owns bounded,
redacted in-flight replay and Stop handles. Lane changes and page reloads detach viewers;
a bridge restart reattaches to Hermes's current transcript/state and names the transient
tool-card boundary. The installed journey recovered one live prompt/partial state across
a real `ship.sh` bridge replacement, preserved one submission, and kept post-restart
Stop honest.

**Recovery and canonical-root independence.** v1.5.77 makes shipping resolve the app by
its stable bundle identity rather than assuming its Finder filename; protects live YAML
empty values from shell misinterpretation; extracts both oversized app-layer routers
below the 1,500-line ceiling without changing route ownership; repairs copied virtual
environment pointers and DeepSeek's generated profile links with validation and rollback;
and regenerates the native root config from the executing checkout. The real-stack walk
proved 10/10 components green, exact 11-model catalog parity across dependent apps, a
real authenticated runner turn, the installed Aider parser and pin, and zero active
runtime references to the retained Claude archive (U69/U74/U77–U81).
v1.5.81 replaces the remaining four-name compatibility list with one shared bundle-
identity resolver used by shipping and VoiceBox wheelhouse discovery. It scans standard
application roots, accepts renamed/nested/symlinked bundles only after canonical
deduplication and id+executable validation, and fails closed on ambiguity. The launched
bridge is bound to a nonce/schema/fingerprint, nullable manifest values cross one typed
reader boundary, all registry writers use the same crash-durable transaction, installed
Aider is checked through its real parser, OpenCode keys are reversible and collision-
free, legacy standalone suites collect under pytest as suite-level cases, and the
pre-provenance migration command requires an operator-named PID rather than inferring
ownership.

**API adherence and trust boundaries.** Every LLM-facing surface (office MCP catalog,
lane routes, vision captions) was audited against 17 AI-friendly-API principles; the two
content channels that relay untrusted transcribed/user text now carry an explicit trust
fence before the content they govern (S33/U47 partial, v1.5.67).

**Deferred-work discipline.** `docs/UNFORGET.md` adopted as the one ledger for paused
plans, session spillover, audit findings, and user-reported issues — replacing scattered
"queued" notes in CLAUDE.md (2026-08-29).

---

## In progress / Next

U170 tracks the remaining exhaustive review and acceptance coverage after the v1.5.91
chat, download, storage and model-settings reliability release. The v1.5.92 session
corrections and installed evidence are in `docs/RELEASE-v1.5.92-RELIABILITY.md`; this work does not implement the
pending feature queue below. The retained post-v1.5.92 review batch is committed as
`2ebb3ae` and pushed to the approved repository, but remains unshipped and not
release-accepted at this document revision; its
RAM/ledger/fit experiments were reverted to the exact v1.5.92 implementation and are
not continuation work. The approved panel-source ceiling exception is tracked separately
as U171: 877,700 bytes previously, 885,000 bytes now, with the current page at 880,942
bytes and a future investigation required. Two narrower follow-ups are intentionally
not hidden beneath U167. U168 covers
integration-specific deletion of data in shared or third-party stores (for example the
standalone Hermes home); it requires one supported owner adapter per store, never a
generic “wipe everything” glob. U169 covers removal of retained optional source/build
trees; those trees remain preserved until a future installer records file-level
ownership digests that can distinguish replaceable seed files from user additions.

The corrective v1.5.80 wave is shipped. Its closure checkpoint is U140 in the ledger;
the U82–U138 rows remain the adversarial incident trail explaining why each first
candidate was rejected or narrowed, not unfinished release blockers.

U157 is shipped as v1.5.87, not active work. OpenCode, SearXNG, ComfyUI, VoiceStudio,
Odysseus and llama.cpp earned their pins independently; Voicebox retained its release
while its lazy runtime became exact; Unsloth and the newer acestep.cpp stayed held. The
complete release evidence is `docs/FABLE-v1.5.87-UPSTREAM-UPDATE-WAVE.md`.

v1.5.88 ships A6/U159–U164. It repairs the reported SDXL→Wan Model/Type
desynchronization, the ACE-Step post-rename native-library path, and the model-eject
post-stop 500; proves fresh MiniMax/ACE/SDXL/Wan output from the renamed root; measures
real MLA, non-Gemma SWA, MLX and vision/projector fit behavior; records evidence-based
Wan 2.2/MiniMax H3 decisions; and makes Comfy's own `api_node` metadata enforce the
Generate surface's local-only boundary before a hybrid template offers downloads. U165
also makes Finder/Get Info derive the native bundle version from the same `VERSION`
truth as the panel and FAT seed. It
does not adopt the slower ACE candidate, promote either broken Wan output, disable an
optional H3 workflow, add cloud execution, or change the current shared Hermes home. Release and measurement
evidence live in `docs/FABLE-v1.5.88-MEDIA-RELOCATION-FIT-WAVE.md` and
`docs/research/2026-09-07-a6-real-fit-validation.md`.

v1.5.89 closes the locally actionable lifecycle and reproducibility wave. The exact
post-rename Goose session roots migrate through Goose's supported ACP operations and
same-session view reload now passes; in-flight Goose generation still cancels when its
ACP request disconnects, so U34 moves to the upstream-blocked queue rather than being
hidden beneath that partial success. Compose and Generate share a tested unknown-outcome
lifecycle for connected requests that never settle, with route-derived deadlines and no
automatic retry. DeepSeek now uses its supported in-page workspace picker composition,
and the installed lane completed a real prompt after selecting the canonical workspace.
Its first and later npm installs both consume the same reviewed lock through `npm ci`.
The two archived worktrees were audited: one is fully merged and the other is superseded,
but neither was removed because the archived original remains outside mutation scope.
Complete evidence is in
`docs/FABLE-v1.5.89-LOCAL-LIFECYCLE-AND-REPRODUCIBILITY-WAVE.md`.

The v1.5.81 remaining-reliability wave and v1.5.82 Odysseus-login hotfix are shipped.
U143 records v1.5.81's full repository, installed-stack, Goose UI, and clean FAT evidence;
U145 records the missed human-login journey and its correction. No open item below is
concealed by either release claim.

v1.5.83 closes the local hardening wave without changing third-party source: dependency
actions deep-link to the named first-party remedy; SearXNG and ACE-Step weights are pinned
to exact source revisions; all remaining remote installer payloads are digest-verified
before use; repository Python and every JavaScript suite now block shipping; and the four
single-model runner consumers report requested-versus-served mismatches with an Open Models
handoff. The live-theme pseudo-element class is fenced without removing its hover/drag
affordances. The reported Studio-light contrast and remaining `calc(var(...))` transition
instances were re-proven absent in the current architecture rather than patched speculatively.
U149 carries the complete gate, installed journey, size/line and runtime evidence.

v1.5.84 is the shipped one-identity release. The public app, Finder/Dock label,
bundle, DMG, mounted volume, executable, manifest, environment namespace, live root,
repository folder, GitHub repository, first-party browser keys/handlers, and managed
Hermes path guard now follow the approved MOT Deck mapping while the M.O.T logo artwork
remains unchanged. Live-state conservation and the native Chat/Odysseus/Help/resize
journeys passed both before and after shipping. `ship.sh --restart hermes` passed the
full gate, updated the live snapshot, restarted Hermes through launch provenance, and
left all 10 components healthy. The manifest/navigation bytes, 11 model IDs, runner
pin/live model, optional empty Aux state, and four protected-secret fingerprints were
conserved. The final clean committed FAT build carries the exact new volume/bundle
identity with `dirty_files=0`. U150 is closed by the detailed ledger and identity
inventory evidence.

v1.5.85 closes the local usability and seed-ownership wave. Native WebKit JavaScript
dialogs now have explicit alert/accept/cancel/value-return paths; LOffice binds each
Agent session to a canonical tool-catalog hash and visibly rolls over only when that
catalog changes; Agent and Hermes accept bounded typed documents while Direct Chat
continues to refuse them honestly; and the capability strip now describes the selected
lane rather than leaking Odysseus claims into Chat or Hermes. Help covers the new
attachments, LOffice rollover, shortcuts, memory and fit meanings. Repeated prose was
demoted into chips, titles, disclosures and Help without deleting policy, diagnostics,
or the existing composer/session-divider interactions. The Office operation schema is
generated from the validator's tables, and paginated reads return exact bounded and
continuation ranges.

Partial-install behavior is now exercised as a manifest-derived matrix over every
optional component's real card, placeholder, navigation, Help, Capabilities, Models and
first-run contracts. This is intentionally a non-destructive matrix—not nine physical
uninstalls of a working machine. FAT runtime seeds now exclude tests and carry a
deterministic per-file SHA-256 ownership manifest. Upgrade cleanup deletes only an exact
path+digest from immutable prior release manifests; the live upgrade removed 48 proven
files on its first pass, preserved every modified/unknown remnant with a reason, and a
second pass removed zero. A clean mounted release artifact contained no test roots and
recorded `dirty_files=0`. A mounted-archive audit then caught macOS `tar` synthesizing
unmanifested AppleDouble metadata; both portable and FAT archive writers now suppress
that behavior, and the final audit requires the manifest paths and digests to equal the
archive's regular files exactly. U152 carries the full release evidence.

v1.5.86 is shipped. It implements the
measured-memory/advisory preference layer; restores theme, log, graph, attachment and
per-turn search affordances; makes Music updates event-led; adds exact child adoption
and reaping; gives LOffice visible Stop and shorter checkpoints; updates a provably
managed live Odysseus picker; expands stock ComfyUI subgraphs; and distinguishes
authoritative Hugging Face LFS digests from honest size-only downloads. Music Studio and
the navigation editor now each expose their own scoped default-restore action; resize-only
dividers remain independent and untouched. The full supported gate, affected installed
human-entry journeys, byte-identical live-state checks, 10/10 component health and clean
signed FAT archive/manifest audit passed. The exact premises, adversarial boundaries and
release evidence are in `docs/FABLE-v1.5.86-LOCAL-TRUTH-WAVE.md`; U153–U156 carry the
release and incident closures.

v1.5.87 is shipped. It advances six independently gated upstream seams: OpenCode
1.18.29, Odysseus dev@934d23c, SearXNG c7f3080, VoiceStudio 0.5.1, ComfyUI 0.34.5 and
llama.cpp b10827. Voicebox stays on 0.5.0 while its three Git sources and three lazy MLX
runtime dependencies become exact and installed-proven. Unsloth and acestep.cpp were
researched and deliberately held: their high-blast changes did not satisfy the required
meaningful-product/audio-A/B evidence. The installed journeys covered OpenCode, managed
Odysseus login plus Agent history, real search, native VoiceStudio plus TTS, Voicebox
MCP plus real Whisper STT, native Comfy plus fresh image/video, and Direct/Agent/Hermes/
vision turns on the new runner. Protected secrets, registry and navigation hashes stayed
identical, the current 27B was restored, and all ten components finished healthy. Exact
candidate, rejection and release evidence: `docs/FABLE-v1.5.87-UPSTREAM-UPDATE-WAVE.md`
(U157/U158).

The immediate queue is P6 stem separation (the next user-selected product slice),
then P3 Voice Chat, P5's remaining ComfyUI Audio/SFX and measured-video scope, S4 fit-engine spawn gates, S7's Wan bf16
colour A/B, and U3's still-unconfirmed token revocation. P4 is closed: Goose CLI and
Goose UI already ship. The machine-readable current-status block above is checked
against the authoritative index in `docs/UNFORGET.md` on every gate.

## Later

Lower urgency or larger blast radius, queued 🟡 LATER — themes only:

- **Music tools dock (P6):** first tool is stem separation only. Research must benchmark
  raw Demucs, several `python-audio-separator` model families, and
  `mlx-audio-separator` on identical inputs before selecting one multi-profile engine or
  two genuinely complementary engines. Moises is the simple-first workflow reference;
  the real engine, model, acceleration and resource facts remain available under
  Advanced. DAWs and Nightingale are explicitly deferred, kept only as the architecture
  argument for Compose's pluggable block grid.
- **Remaining model-label limit (U14):** requested-versus-served truth is now visible for
  Odysseus, Hermes, OpenCode and the current managed Goose provider. Goose still exposes
  only one model identifier field, so MLX filesystem paths remain ugly but correct in its
  upstream picker until Goose adds a distinct display alias.
- **Known reliability limit:** Direct Chat history persistence is at-least-once until
  Odysseus exposes an idempotent insertion primitive (U139). M.O.T's request marker and
  read-back close ordinary retries, but cannot make an independent database commit atomic.
- **Security and breadth:** extend the path guard to a real shell execution boundary
  rather than command-string parsing (U72); add a model-manager adapter only when M.O.T
  has both an authoritative inventory and a launch contract for it (U91); design an
  update/verify/rollback transaction before rotating a user-owned auxiliary endpoint key
  (U142); and make Goose provider deletion remove its inert config stanza through an
  upstream-supported transaction (U144).
- **Measured no-change:** the pinned runner retained two hostile, oversized prompt
  prefixes with four-token warm evaluations; adding parallel/cache slots would add
  memory/state without a reproduced benefit (U73). Re-measure on runner/cache-policy
  change, not by calendar.
- **Upstream coordination checkpoint (2026-09-06):** corrective evidence is public on
  Hermes #39004 and Odysseus #6255/#6256. U139 alone has a verified candidate and awaits
  agreement on its API before any PR; acceptance must then become a released Odysseus
  pin, an M.O.T caller, and real response-loss/replay/attachment/human-history journeys.
  U72, U142 and U144 have rejected candidates and require replacement upstream designs;
  they are not silently skipped and are not merely waiting for dependency versions.
- **Replacement-design checkpoint (2026-09-06):** Hermes's PR author confirmed that its
  policy, environment identity, callers and cleanup are intentionally one boundary, with
  Docker as the only current workspace adapter and other adapters possible separately.
  That is direction, not macOS acceptance; M.O.T remains Docker-free and no viable native
  confinement candidate exists yet. Odysseus's complete endpoint-writer graph requires a
  field/actor-aware mutation boundary rather than route checks or a whole-row freeze.
  Goose requires explicit secret provenance plus one cross-process transaction boundary
  shared by provider, config and secret writers. No runtime code follows from these
  findings until the relevant upstream contract survives adversarial review.
- Hermes v0.20.x update retry, parked on two upstream bugs (P1); the ONLYOFFICE/Euro-Office
  bump, parked on upstream's next release (P2).

## Someday

Recorded, not scheduled: Odysseus vision's upstream root cause (U1, needs Debi's word to
file publicly); `~/.hermes` shared-home isolation ruling (U2); session-creation
unification across lanes (S2); MiniMax H3 video+audio, which remains optional but does
not qualify as the requested under-40 GB starter (U8).

---

For anything not summarized above — exact evidence, file:line citations, closure
pointers, and the verify-still-open command for a specific row — read
`docs/UNFORGET.md` directly; it is kept current at ship time and this document is not a
substitute for it.
