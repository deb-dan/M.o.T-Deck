# v1.5.89 local lifecycle and reproducibility wave

Status: shipped and verified. The release section records the clean commit, installed
ship, real-stack health check, and read-only FAT archive audit.

## Scope and preservation boundary

- Repair only MOT Deck's exact post-rename Goose session-working-directory residue.
- Prove the two separate Goose reload questions: restoring the visible session and
  surviving an in-flight ACP disconnect.
- Give Compose and Generate one bounded, truthful lifecycle for a connected request
  that never settles, without creating an unsafe automatic retry.
- Replace DeepSeek's background native folder chooser with its supported in-page
  directory-picker composition and walk the real installed lane through a prompt.
- Make DeepSeek's very first npm installation use the same reviewed lock as every
  later installation.
- Audit the two retained Git worktrees without removing, merging, rebasing, or editing
  either archived checkout.
- Preserve layouts, drag/resize affordances, themes, outputs, models, registry rows,
  credentials, third-party source, and the archived original project. No screenshots
  are taken during this wave.

## U166 — exact Goose session-root migration

Four real Goose sessions retained the retired working directory
`~/Library/Application Support/Harness/data/goose-workspace`. Opening the newest row
through the current UI reproduced `Failed to Load Session / invalid directory path`.
This was not a renderer or database-corruption guess: Goose's supported ACP session-info
operation reported that exact stored path for all four rows.

MOT Deck now performs one narrow, fail-closed migration before serving Goose UI:

- enumerate sessions through Goose ACP, with bounded pagination and repeated-cursor
  rejection;
- match only the exact historical MOT Deck directory, never a prefix or similar name;
- require the historical directory to be absent and the canonical target to exist as a
  real, non-symlink directory;
- update through Goose's own `_goose/unstable/session/working-dir/update` operation;
- read each row back through `_goose/unstable/session/info` before reporting success;
- never edit Goose's private SQLite database and never manufacture a compatibility
  symlink.

The live migration updated the four exact rows, produced zero errors, and left neighboring
paths untouched. The formerly broken session opened with its prior prompt and response,
and a reload returned to the same route and visible conversation. A transient migration
failure is retried; only a verified success is memoized for the bridge process.

## U34 — two reload contracts, only one locally closable

The same-session **view** question now passes: the hash route, selected session, and
rendered history survive a reload after U166's path repair.

The in-flight **generation** question fails for a separate upstream reason. A fresh real
prompt was submitted, the Goose UI was reloaded while it ran, and the user prompt remained
but no assistant response completed. The pinned Goose v1.48.0 source makes the lifecycle
explicit: the ACP `on_prompt` request future owns the active run, and
`ActiveRunDropGuard` cancels it when that connection/request is dropped. Therefore a
browser/ACP disconnect cannot currently be recovered by a MOT Deck page-only change.

MOT Deck does not hide this result beneath the session-view pass and does not fork Goose
or build an unreviewed second conversation proxy. U34 remains open and upstream-blocked
until Goose provides a durable run detached from one ACP request, or a deliberately
specified MOT Deck ownership layer is approved.

## U42 — stalled Compose and Generate requests

Both first-party media pages now use byte-identical inline `MOTActionLifecycle` logic.
The helper stays inline because both pages deliberately reject external scripts and are
designed to remain self-contained; an executable test enforces identity so the two copies
cannot silently diverge.

If a submission connects but never settles, MOT Deck aborts only its browser wait,
reports that the upstream outcome is unknown, clears the visible busy latch, and blocks a
duplicate submission behind `Check queue…`. The next successful authoritative status
load reconciles the unknown state. There is no automatic retry and therefore no hidden
double generation.

The deadlines follow each route's real work rather than sharing an arbitrary number:
Compose uses 25 seconds; Generate uses 90 seconds because its valid path can spend up to
20 seconds fetching object metadata, multiple six-second model listings, and 30 seconds
submitting the prompt before ordinary overhead. The change does not modify page layout,
drag/drop, resize, theme, waveform, gallery, model/type selection, or visual styling.

## U67 — DeepSeek in-page workspace picker

The first candidate used the right upstream composition but the wrong CLI grammar:
`dsh web --patch ...` was rejected because `--patch` is a parent option, not a `web`
subcommand option. Production was not declared healthy. The installed CLI's own help was
then used to derive and test the supported form:

`dsh --profile web --patch <policy> --host 127.0.0.1 --port 3080 --no-open`

The reviewed policy disables only the native `directory-picker` service and inserts
DeepSeek's own browse host and client UI services. In the installed MOT Deck tab, Add
workspace opened the in-page `Select Workspace Directory` dialog; the canonical
`data/deepseek-workspace` directory was selected, the workspace registered, the composer
enabled, and a real prompt returned exactly `U67-DEEPSEEK-PICKER-OK`. The old background
`osascript` chooser and its focus ambiguity are no longer on this lane.

## U70 — deterministic first DeepSeek npm installation

The repository now carries a minimal package manifest and npm lock for exact DSH
`0.1.1-rc.2`. The installer validates the package name, exact top-level pin, lockfile
version, root metadata, and integrity-bearing dependency entries before copying the pair
into the managed prefix and running `npm ci`. The first-install `npm install` path is
gone; initial and repeat installs now resolve the same reviewed dependency graph.

The lock contains 513 package entries, 512 with integrity records, and has SHA-256
`d8eb8e9b96905e8f3b8db887e85cc1af25a028dac2cf668415c772c453fedb18`.
A fresh scratch `npm ci` installed 455 packages and the resulting binary reported the
exact DSH version. Upstream lifecycle scripts remain enabled deliberately; this work
removes date-dependent resolution, not the existing package-script behavior.

## U58 — retained worktree audit, no deletion

Both registered worktrees live inside the archived original project, so this wave is
strictly read-only there:

- `confident-mcnulty-f06af0` at `9fc2332` is fully contained in current `main`.
- `musing-williamson-7736a5` at `709eca2` is not an ancestor of `main`, but its
  ONLYOFFICE intent was superseded by the shipped v1.5.25 implementation and current
  custom-function, fail-closed history, recalculation, and regression contracts.

There is no remaining commit to merge. Removal would still mutate the archived original
repository and destroy registered worktrees, so it requires an explicit future decision
that changes that boundary. Neither worktree nor branch was removed here.

## Verification before the release commit

- 577 contract checks passed; the four skips are the declared checkout-local Aider
  cases, not skipped U34/U42/U67/U70 coverage.
- 720 repository tests passed; the only output was two FastAPI/httpx deprecation
  warnings.
- Every JavaScript suite passed, including ten executable shared-lifecycle checks.
- Focused Goose UI coverage passed 313 checks; DeepSeek passed 63; installer/DeepSeek
  coverage passed 91.
- The candidate ship restarted DeepSeek with the corrected supported CLI form and kept
  it healthy on port 3080.
- User-facing verification used the live DOM, routes, logs, and real prompts. No
  screenshot API or system screenshot command was used.

## Release acceptance — v1.5.89

- The release commit is `0095b95`; local `HEAD` and GitHub `main` matched before the
  installed ship and FAT build, and the seed recorded that exact SHA with
  `dirty_files=0`.
- The clean-tree ship reran the complete gate: 577 contract checks with only the four
  declared checkout-local Aider skips; 720 repository checks with two dependency
  deprecation warnings; and every JavaScript suite, including U42's ten executable
  lifecycle checks.
- The installed bundle reports identifier `local.motdeck.app`, executable `MOTDeck`,
  and both version fields as 1.5.89. Its bridge came up with API fingerprint `981998f7`
  and snapshot app-layer fingerprint `9ffe0595`.
- All ten components were running and healthy. The runner's configured and served IDs
  both named the same Qwen3.8 27B model. DeepSeek's live listener command used the exact
  supported `--profile web --patch .../deepseek-directory-picker.yaml` form. Music and
  Generate each returned HTTP 200 with `ok:true`.
- The FAT build contains a 445 MB app payload and a 112 MB compressed seed. The mounted
  DMG passed deep strict code-signature verification and repeated the exact bundle
  identifier, executable, and 1.5.89 versions. Its SHA-256 is
  `a095ce27e0b6650804b157881e8d4cdb44522f9c44fedcf66a9eda0bc25020c9`.
- All 12,536 entries in `SEED_FILES.json` were independently streamed from the archive
  and SHA-256 verified: zero missing, zero extra, zero mismatches. MOT Deck's own
  `bridge/tests` and `bridge/contract_tests` authoring suites are absent. Test-named
  directories that remain are part of the unchanged upstream Hermes, Odysseus, and
  SearXNG vendor seeds; they are not the retired first-party runtime-test residue.
- The final installer is `dist/MOT Deck.dmg`. No screenshot was taken during the build,
  human-entry verification, installed ship, or archive audit.
