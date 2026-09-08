# MOT Deck v1.5.90 — ownership-safe uninstall, reset, and optional setup

Status: shipped and release-accepted for v1.5.90. The complete repository gate, clean FAT
package, installed-bundle replacement, and non-destructive installed preview/cancel
journeys all passed. No destructive Apply path was used against personal data.

## User-visible problem

MOT Deck can install and start integrations but offers no matching uninstall action.
Music and Generate can acquire large local artifacts but cannot remove a selected engine
or workflow dependency from their own surfaces. Chat and Hermes expose individual
sessions but not an explicit clear-all operation. There is also no supported way to reset
MOT Deck's state or remove the app. Finally, first-run installs the offline core without
letting the user choose which online optional integrations to add afterward.

The answer is not one generic recursive delete. These integrations have different owners,
shared dependencies, and independent user data. Every destructive operation therefore has
to name its authority, preview exact consequences, and refuse ambiguity.

## Binding product rules

1. **Preview before mutation.** Every operation returns exact targets, byte counts,
   preserved paths, shared-resource warnings, running-process consequences, and the
   operation's reversibility before an Apply control is enabled.
2. **Consent is bound to evidence.** Apply carries an opaque, short-lived token bound to
   operation, target, canonical paths, file identities/digests where available, and the
   current install-state revision. A changed preview is refused and must be reviewed again.
3. **Stop only proven children.** A running component is stopped only through the existing
   PID + kernel-birth launch-provenance transaction. A missing/foreign owner record refuses
   deletion; name, port, executable path, and CWD never establish kill authority.
4. **Recoverable removal.** Runtime and artifact removal moves exact targets into the
   current user's Trash. MOT Deck states that disk space is not reclaimed until Trash is
   emptied. Cross-device or unavailable Trash moves fail closed; there is no copy-and-delete
   fallback.
5. **Normal uninstall preserves user state.** Sessions, settings, workspaces, documents,
   outputs, credentials, and downloaded models are retained unless separately selected.
6. **Shared state is never silently erased.** In particular `~/.hermes` is shared with
   standalone Hermes, Hugging Face cache objects may serve other apps, Goose CLI/UI share a
   binary, and Generate files may serve multiple workflows.
7. **No database surgery.** Odysseus, Hermes, and Goose conversations are removed only
   through their supported session operations. A bulk operation is an itemized sequence
   with an honest partial-result receipt; it is not described as atomic when upstream has no
   atomic primitive.
8. **Live configuration is line-preserving and atomic.** Installed flags change through
   the canonical YAML transaction. Repository `motdeck.yaml` is a template and is never
   copied over the live manifest.
9. **No destructive release walk on personal data.** Tests use temporary roots and fake
   upstreams. The installed journey may exercise preview, refusal, cancel, and a temporary
   fixture created for the journey; it never removes the user's current integrations,
   histories, workspaces, models, or documents.
10. **Claims stay narrow.** “Uninstall runtime” is not “erase everything”. “Remove model
    files” is not “uninstall workflow metadata”. “Reset MOT Deck” is not “erase shared
    standalone Hermes”.

## Ownership matrix

| Surface | Normal runtime removal | Preserved by default | Explicit deeper removal |
| --- | --- | --- | --- |
| Hermes | `data/hermes-venv` and MOT Deck-owned generated launch helpers | shared `~/.hermes`, sessions, channels, WhatsApp credentials | separate shared-Hermes consent; never part of factory reset by default |
| Odysseus | `data/odysseus-venv` | vendored `vendor/odysseus/data`, uploads, sessions, settings | supported session deletion; isolated app data only when specifically selected |
| SearXNG | `data/searxng-venv` | `data/searxng/settings.yml` | settings reset as a distinct data action |
| VoiceStudio | `data/voicestudio-venv` | `vendor/voicestudio`, `~/Library/Application Support/OmniVoice`, shared HF cache and Bun/FFmpeg helpers | exact owned data only after inventory; shared helpers require zero remaining consumers |
| Voicebox | `data/voicebox-venv` | `vendor/voicebox`, `data/voicebox`, shared HF cache and Bun/FFmpeg helpers | same shared-helper rule |
| ComfyUI | `data/comfyui-venv` | `vendor/comfyui` including possible custom nodes; `data/comfyui` models, inputs, outputs and user workflows | exact model files selected from the discovered catalogue; shared-workflow impact shown |
| Unsloth | `data/unsloth-home/unsloth_studio` venv only | `vendor/unsloth`; the rest of isolated `data/unsloth-home`, models, runs and settings | isolated home reset as a separate action |
| OpenCode | `data/opencode/bin/opencode` | `data/opencode/xdg`, sessions, config, `data/opencode-workspace` | isolated state reset; workspace never implied |
| DeepSeek | `data/deepseek/npm` | `data/deepseek/home`, profiles, sessions, `data/deepseek-workspace` | isolated state reset; workspace never implied |
| Aider | `data/aider-venv` | `vendor/aider`, `data/aider-workspace` | workspace removal is a separately named action |
| Goose UI | `data/goose/ui`, UI stamp/receipt files | `data/goose/ui-home`, shared Goose binary and CLI home | UI state reset; never remove shared binary while CLI remains installed |
| Goose CLI | shared `data/goose/bin/goose` plus CLI install receipts | `data/goose/home`, `data/goose-workspace`, UI runtime if installed | refuse or explicitly cascade when Goose UI still depends on the binary |
| LOffice | `data/onlyoffice`, `data/onlyoffice-plugins`, install stamps/receipts | documents, backups, exports, LOffice session bindings | document/data removal is separately selected and enumerated |
| Runner | MOT Deck-built runner runtime only | chat model registry and all model artifacts | app-owned model deletion keeps its existing journaled transaction; external-manager rows stay manager-owned |
| Music / ACE-Step | `data/acestep` integration/build | shared Hugging Face weight objects, Music library and outputs | exact cache revision only with shared-cache warning |
| Music / MiniMax | no independent local runtime beyond shared Music venv | pinned Hugging Face snapshot, Music library and outputs | exact snapshot only with shared-cache warning |
| Generate workflow | no installed workflow object; catalogue metadata is upstream-derived | catalogue and user workflows | remove selected exact required files, showing every other workflow that shares them |

Each row was checked against the current installer and start arm. Optional source/build
trees are deliberately retained: no historical install-time manifest proves every ignored
or untracked file in those directories is replaceable, and ComfyUI may contain user-added
custom nodes. A future source-cache cleanup may remove only paths whose install-time digest
still matches a seed-owned manifest.

## Reset tiers

### 1. Clear conversations

- `Chat / Agent`: list Odysseus sessions and delete them through the supported Odysseus
  session API, excluding any session the user did not select when scope is narrower.
- `Hermes`: list and delete through Hermes's supported session API; a live session is
  stopped/closed through the existing Hermes lifecycle first.
- `Goose`: use Goose's supported deletion flow. Never mutate its SQLite database.
- Each session produces a receipt (`deleted`, `already absent`, `refused`, or `failed`).
  Partial completion is visible and retryable.
- The UI uses a dropdown beside Refresh: Refresh; Delete this chat; Delete all chats in
  this lane. The destructive entries require a second confirmation with a count.

### 2. Selective data erasure (future per-owner adapters)

A single generic selective eraser is **not implemented** in this release. Different
integrations expose different supported deletion primitives, and some state is shared
with their standalone app. Future additions may remove isolated first-party preferences,
local sidecar data, generated caches, or one explicitly selected integration home only
after its owner supplies an authoritative inventory/deletion contract. There will be no
broad `data/**` glob and no direct surgery in third-party databases.

### 3. Factory reset while keeping the app installed

A detached helper stops exact owned children, quits the bridge/app, moves the canonical
MOT Deck support root to Trash, recreates no data itself, and reopens `MOT Deck.app` so its
normal first-run core provisioning owns the new root. Shared `~/.hermes` remains unless a
separate checkbox names it. The helper is passed resolved literal paths and an evidence
token; it refuses `/`, a home directory, a workspace root, or an unrecognized bundle.

### 4. Full uninstall

The same helper moves the verified `local.motdeck.app` bundle and canonical support root
to Trash after exact owned processes have stopped. Repository checkouts and the user's
workspaces are never targets. Shared Hermes data remains a separate explicit choice.

## Optional installation

The FAT image remains an offline, deterministic **core** installer: bridge, runner,
Hermes, Odysseus, SearXNG, and the shared MLX runtime needed by local runner choices.
Optional products can require the network and therefore cannot honestly be folded into
that offline guarantee.

After core setup, “Choose optional tools…” presents independent checkboxes with each
tool's current install note and dependencies. Selection queues the existing audited
installers; their own prompts, licences, pins, digests, disk checks, logs and third-party
onboarding remain authoritative. Failure of one optional item does not roll back or
mislabel the core. The same screen remains reachable later from Mission Control. Exact
download sizes are not duplicated in this selector when the underlying installer computes
them dynamically; the selector must not freeze another stale size catalogue.

## API availability truth

The API page keeps the runner endpoint section. Any integration-specific examples/actions
must be derived from `/api/status`: installed and available, installed but stopped, or not
installed. Unavailable controls are visibly disabled with the exact component needed and a
deep link to Mission Control. A disabled row is not removed, because its discoverability is
part of the optional-install design.

## Composer visual contract

`#chat-inputrow` is the single visible field. The textarea is transparent and borderless
in every theme/chrome/design combination. Attach, mic, send, and audio mode remain inside
that shell and keep their existing handlers, accessibility labels, hidden states, keyboard
behavior, and lane behavior. Only Send is a persistent filled action; secondary controls
gain ground on hover/focus. Tests must inspect computed styles for all six looks so a late
selector cannot silently restore a nested textarea box.

## Acceptance journeys

1. Every installed component card offers `Uninstall…`; stopped/running states preview the
   same exact paths, and a running foreign/unowned listener is refused without signalling.
2. Cancel changes nothing. A stale evidence token changes nothing. A successful temporary
   runtime removal moves only the fixture-owned runtime to Trash, flips only that installed
   flag, preserves state/workspace fixtures, and leaves shared helpers intact.
3. Goose UI/CLI dependency cases and Voice shared-helper cases refuse or explain exactly.
4. Music removal distinguishes integration from shared cache weights. Generate shows file
   sharing across workflows and never calls catalogue metadata an installed workflow.
5. Clear-one and clear-all operate through fake supported upstream APIs, report partial
   failure honestly, and never open a database file.
6. Factory/full helpers refuse broad and mismatched paths in dry-run tests. The installed
   app exposes their previews, but the release walk does not apply them to user data.
7. Setup proves core offline semantics and selected optional online semantics separately.
8. API unavailable states are visibly disabled and recover via their exact install/open
   action.
9. The composer computed-style matrix proves one shell/no inner box; attachment, Enter,
   microphone, Send, audio switch, drag/resize arrows, theme switching, and durable-turn
   recovery retain their existing behavior.

## Release evidence

- Contract gate: 580 passed, with four documented checkout-local Aider skips.
- Repository Python: 753 passed; the two warnings are dependency deprecations, not failed
  or skipped product checks.
- Every JavaScript suite passed, including 19 storage/composer preservation checks.
- Installed previews named the exact OpenCode runtime, both Music engine payloads, one
  SDXL workflow file and all five workflows sharing it, 40 Odysseus sessions, 53 Hermes
  sessions, and the app/support-root full-uninstall pair. Every preview was cancelled.
- The full-uninstall Apply button remained disabled without the exact typed phrase.
- The first installed full-uninstall preview exposed a roughly 30-second bridge stall:
  it recursively sized the complete support root even though size was not safety evidence.
  That candidate did not release. The corrected preview explicitly omits the total and
  loaded in under one second while retaining path, identity, helper-digest and process
  evidence.
- The composer walk measured attach, textarea, microphone, Send and audio switch inside
  one bordered shell; the textarea computed transparent with no border.
- `motdeck.yaml`, `.env.local`, `models.json` and `nav.json` retained their exact pre-ship
  digests, all ten components retained install state, and the runner retained its live
  model.
- The clean committed FAT build embeds `VERSION=1.5.90` and a `SEED_STAMP` bound to
  `git_sha=78cb0c1` with `dirty_files=0`. `MOT Deck.app` and the copy mounted from
  `MOT Deck.dmg` both identify as `local.motdeck.app` / `MOTDeck` / `1.5.90`, carry the
  executable `firstrun_fat.sh` plus `motdeck-seed-fat.tar.gz`, and pass deep strict
  signature verification. SHA-256: DMG
  `e8f4a6a5f3481624e50488bb6896f1ac16f20d5c1f74970805e709ee7a355998`; embedded seed
  `7e248827cb97664c981dc40efa72f9fa45a283b765c8aa282d26ab65cfaa1330`.
- The installed v1.5.89 bundle was moved recoverably to Trash before the verified v1.5.90
  bundle took its place; the canonical support root was not moved. After `ship.sh`, the
  factory-reset capability changed from correctly unavailable (the old app lacked a
  matching seed) to available. Its installed preview named only the canonical support
  root, preserved every external/shared boundary, and kept `Reset and reopen` disabled
  until the exact confirmation phrase. The preview was left through Back without applying
  it.
- The post-ship state retained the same eight intentionally running components, the same
  intentionally stopped OpenCode and DeepSeek components, and the same live 27B runner
  model. All twelve optional selections were present and truthfully marked installed.
