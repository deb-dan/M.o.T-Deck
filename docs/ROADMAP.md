# MOT Deck — Roadmap

Reader-facing status: what the product now does, what's actively being worked on, and
what's next. This is not a changelog — for line-by-line history read `git log`; for the
full deferred-work backlog (every paused plan, audit finding, and user-reported quirk,
each with a status and a verify-still-open command) read **`docs/UNFORGET.md`**, the one
source of truth for deferred work. This doc summarizes themes and points there rather
than restating rows.

Current version: **v1.5.78** (see `VERSION`). Written 2026-09-05.

---

## Done

Grouped by theme, with the version range where the shape landed. "Done" means shipped,
gated by tests, and walked live on the real stack — not merely coded.

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

**Local API access.** Mintable/revocable API keys apps' own Add-Provider forms can
consume (`--api-key-file`, unions with the built-in key) plus an Unsloth-style API page —
base URL, status, loaded model, route catalogue, honest request log split by lane — both
sidebar-only like Help (S32, v1.5.68). A Help/USER-EXPLAINERS §API section documents it
(v1.5.72).

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
identity-verified in shell scripts (U19, v1.5.58) — see Next below for the Python-side
half of that rule.

**Recovery and canonical-root independence.** v1.5.77 makes shipping resolve the app by
its stable bundle identity rather than assuming its Finder filename; protects live YAML
empty values from shell misinterpretation; extracts both oversized app-layer routers
below the 1,500-line ceiling without changing route ownership; repairs copied virtual
environment pointers and DeepSeek's generated profile links with validation and rollback;
and regenerates the native root config from the executing checkout. The real-stack walk
proved 10/10 components green, exact 11-model catalog parity across dependent apps, a
real authenticated runner turn, the installed Aider parser and pin, and zero active
runtime references to the retained Claude archive (U69/U74/U77–U81).

**API adherence and trust boundaries.** Every LLM-facing surface (office MCP catalog,
lane routes, vision captions) was audited against 17 AI-friendly-API principles; the two
content channels that relay untrusted transcribed/user text now carry an explicit trust
fence before the content they govern (S33/U47 partial, v1.5.67).

**Deferred-work discipline.** `docs/UNFORGET.md` adopted as the one ledger for paused
plans, session spillover, audit findings, and user-reported issues — replacing scattered
"queued" notes in CLAUDE.md (2026-08-29).

---

## In progress / Next

The v1.5.77 recovery wave and v1.5.78 U75 integrity slice are closed. The next
model-registry change remains a separate release because it changes what the app may
call an absent model:

- **U76** — retain the unplugged-volume guard while persisting enough source/device
  evidence to distinguish a missing mount from a deliberate mass deletion. Legacy
  all-missing evidence must ask for explicit confirmation rather than guessing.

The earlier U56/U64 work is closed in v1.5.74, U69/U74/U77–U81 are closed in
v1.5.77, and U75 is closed in v1.5.78; none of those remains in flight.

Everything else below is queued (🔵 NEXT in the ledger), grouped by theme — see
`docs/UNFORGET.md` for the full finding, evidence, and verify-still-open command on each:

- **API adherence, part 2 (S34):** generate the office `ops` JSON Schema from the
  validator's own tables; read-cap loop relief on paginated reads.
- **Copy demotion (S15–S18):** several surfaces (goose/aider intro paragraphs, the
  changeset-card policy text, Caps→Tools, the Audio tab's essay cards, the Office AI
  empty state) carry standing paragraphs that duplicate Help verbatim — demote to chips
  + a Help link.
- **Shell dialog trio (S12):** `main.swift` has no `WKUIDelegate` for
  `alert()`/`confirm()`/prompt — these are silent no-ops shell-wide today, a class that
  has already caused at least one "dead button" bug (comfy.html).
- **Partial-install honesty (S23):** a full sweep, one component removed at a time, of
  every surface that mentions it (Caps strip, ⌘K, Help, model pickers, tab placeholders)
  to confirm graceful degradation everywhere, not just per-lane folklore.
- **Paused plans (P-rows):** Voice Chat M3 (push-to-talk lane, additive, spec next then
  build); a ComfyUI Video/Audio first-party surface (research done, Fable spec next); a
  goose-lane P4 row from before Goose shipped that likely needs re-verification against
  the ladder now in place.
- **Small, contained fixes queued 🔵 NEXT:** the dependency banner's "open" action always
  lands on MOT Deck regardless of which pane actually fixes the problem (U22); OpenCode
  can't be rebound without a restart and the deps banner doesn't know it (U38); goose
  records an empty session on every launch (U27); LOffice's AI panel loses its visible
  transcript on reload though the conversation survives server-side (U30); Odysseus
  session records can point at a deleted model with no healing path (U35); two installers
  (`install_searxng.sh`, `install_music.sh`'s acestep weights) still float on an unpinned
  upstream HEAD (A11, A12); a couple of stale/red test fences that need re-pointing, not
  re-arguing (A7, U40, U49).

## Later

Lower urgency or larger blast radius, queued 🟡 LATER — themes only:

- **Music tools dock (P6):** first tool is a stem separator only (demucs/UVR-class);
  DAWs and Nightingale docking are explicitly deferred, kept only as the architecture
  argument for Compose's pluggable block grid.
- **The runner-substitution class (U13/U14/U20/U35):** llama.cpp ignores a request's
  `model` field and serves whatever's loaded — Odysseus labels the substitution honestly,
  Hermes and goose's pickers don't yet. One runner fact, four pickers, all queued
  together.
- **CSS/rendering classes found engine-wide:** a pseudo-element painted with `var(--x)`
  doesn't repaint on a live theme flip (S24); WebKit won't transition a property whose
  computed value came from `calc(var(...))` (S25) — both have known one-line fixes at
  the two remaining sighted call sites.
- **Contrast:** `studio-light` under a dark theme pack drops sidebar text to ~2.3-2.5:1
  (A9) — a reachable but rare combination.
- **Origin fencing (U63):** no mutating bridge route checks `Sec-Fetch-Site`/`Origin`,
  so any page open in the same browser could POST to `127.0.0.1:8700`. Not new, and
  deliberately not a login — a `Sec-Fetch-Site: cross-site` refusal is the cheap fix.
- Digest-pinning the remaining tag-only installers (A13); Hermes v0.20.x update retry,
  parked on two upstream bugs (P1); the ONLYOFFICE/Euro-Office bump, parked on upstream's
  next release (P2).

## Someday

Recorded, not scheduled: Odysseus vision's upstream root cause (U1, needs Debi's word to
file publicly); `~/.hermes` shared-home isolation ruling (U2); session-creation
unification across lanes (S2); MiniMax H3 video+audio, refused for now on disk space
(U8).

---

For anything not summarized above — exact evidence, file:line citations, closure
pointers, and the verify-still-open command for a specific row — read
`docs/UNFORGET.md` directly; it is kept current at ship time and this document is not a
substitute for it.
