# v1.5.93 FAT candidate build record

2026-09-08. This records a candidate artifact built from the existing-feature review.
It is a build receipt, not a shipped-release or installed-native acceptance report.

## Boundary

- **Candidate source:** `0ae3d87`, version `1.5.93`.
- **Seed state:** `git_sha=0ae3d87`, `dirty_files=0`, nine components.
- **Output directory:** `/Users/debik/GemiAntigravity/September 3rd new check harness/outputs/motdeck-fat-v1.5.93-20260908-204957`.
- **Candidate DMG:** `MOT Deck.dmg`, 638,587,539 bytes, SHA-256 `121f9d1b1bf98e26861c388c8803f4629752d4a084d2917406234bee35cccfd8`.
- **Verification receipt:** `bundle-verification.json` beside the candidate DMG.
- **Status:** built and artifact-verified; not installed, shipped, or accepted through the affected native journeys.

The builder gained `--output-dir <new-directory>`. It refuses an existing output
directory before changing artifacts, and routes its app, DMG, icon and temporary seed
through that new root. Omitting the option retains the established `dist` default and
exact `MOT Deck.app` name. The preservation test executes the real builder with inert
compiler and disk-packager seams, proves an existing DMG/app/staging tree remains
byte-identical, checks repeat-output refusal, and exercises both supported flag orders.

## Artifact verification completed

The built app and the app on a read-only mounted DMG both reported version `1.5.93`,
the same clean seed stamp and seed digest
`cd04e5db556f73aa73e5ca4681843c7444991f4165718b2e51c84040dc37871d`.
Deep signature verification passed for both copies. The verifier hashed all 12,549
seed-manifest-owned files and inventoried 219 wheelhouse files in each copy.
The verification mount was detached afterward. A separate check validated every
wheel's complete ZIP CRCs and presence of its `.dist-info/WHEEL` metadata; its receipt
is `wheel-archive-verification.json` beside the DMG. Offline installation and dependency
resolution have not been exercised.

The prior default image was preserved rather than replaced:

- `/Users/debik/GemiAntigravity/September 3rd new check harness/New Harness/MOT Deck/dist/MOT Deck.dmg`
- 458,482,571 bytes
- SHA-256 `25d67bd1cee3ce890c5c285c291e96c91b5bbda26824416c0dfd943e70a00fe0`

The source gate before the FAT build passed 565 contract tests with 24 explicit skips,
1,015 repository Python tests with two warnings, and all 72 discovered JavaScript test
files. A later user-run `./scripts/ship.sh` stopped in its test gate before deployment:
one Goose resumed-session journey shared the canonical runtime ownership record with a
simultaneous fresh bridge import, which swept the journey's child. The failure reproduced
on clean `0ae3d87`. The test-only correction is committed as `217ce4d`. The harness now
establishes a private runtime before importing
the router and propagates/restores that root through the facade; production Goose code,
the candidate payload, vendor sources, and RAM/memory-ledger code are unchanged. Focused
validation passed 34 tests. The complete post-correction gate passed 565 contract tests
with 24 explicit skips, 1,016 repository Python tests with two existing deprecation
warnings, and all 72 JavaScript test files. The standalone Goose runner also passed all
427 checks while that full gate was running, and the permanent regression passed two
complete simultaneous journeys plus competing fresh-start imports. These later changes
are test isolation and evidence only; tests are excluded from the FAT payload, so the
artifact remains the clean `0ae3d87` build recorded above. Reproduction, focused,
standalone and final-gate logs are retained in the candidate output's `validation/`
directory.

## Acceptance still open

This evidence proves the contents and signatures of the FAT artifact and that the old
default DMG was not overwritten. It does not prove an offline first run, installation
over the current app, restart, component launch, native UI behavior, affected end-to-end
journeys, or release shipment. The failed `ship.sh` attempt did not deploy the candidate.
The canonical doctrine-driven refresh/restart command remains:

```bash
./scripts/ship.sh
```

That command must pass its own current gate before it snapshots Application Support,
installs, signs, restarts and verifies the installed app. No manual runtime copy is a
substitute for that path. U170 remains open for the exhaustive existing-feature review
and native/all-design acceptance; U171 remains the separate approved panel-size
investigation. The RAM ledger, fit calculations and their implementation remain frozen
at the exact `ea47eb1` behavior by user direction.
