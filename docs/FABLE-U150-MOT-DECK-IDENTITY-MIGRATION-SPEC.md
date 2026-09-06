# U150 — MOT Deck identity migration

Status: approved for implementation by Debi, 2026-09-07.

Exhaustive surface/file inventory: `docs/U150-IDENTITY-CHANGE-INVENTORY.md`.

## Destination

The product has one public identity and one machine identity. The logo artwork remains
`M.O.T`; every active first-party product identifier becomes:

| Surface | Canonical value |
|---|---|
| Visible product/app | `MOT Deck` |
| App bundle | `MOT Deck.app` |
| Installer and mounted volume | `MOT Deck.dmg` / `MOT Deck` |
| Machine slug | `motdeck` |
| Bundle identifier | `local.motdeck.app` |
| Executable | `MOTDeck` |
| Manifest | `motdeck.yaml` |
| Environment prefix | `MOT_DECK_*` |
| Live root | `~/Library/Application Support/MOT Deck` |
| Canonical repository folder | `.../New Harness/MOT Deck` |
| GitHub repository | `Debkbas/mot-deck` |

The old Claude project is an archive and is neither a migration source nor a target.
Vendored upstream source is not edited. `DeepSeek Harness` remains that upstream
product's proper name; ordinary phrases such as “test harness” remain ordinary English.

## User-visible counterexample

Before this slice, mounting the FAT installer showed a volume and app named `Harness`
even though the icon said `M.O.T` and the shell said `MOT Deck`. The same stale name
also owned the bundle ID, executable, manifest, environment namespace, persistent root,
and repository path. A Finder-label-only patch would preserve the split identity and is
therefore rejected.

## Authorities

- The table above is the approved identity authority.
- `motdeck.yaml` remains the configuration template in source and live state in the
  installed root. No second manifest or registry is introduced.
- The existing live root is the authority for installed flags, protected secrets,
  registries, sessions, model bindings, component homes, and user state. Migration moves
  it; it never seeds over it from the repository template.
- Bundle identity is `CFBundleIdentifier + CFBundleExecutable`, not a Finder filename.
- Process ownership remains launch-provenance (`pid + kernel birth`), never name, CWD,
  executable path, or port alone.

## Migration contract

1. Stop only the installed app, bridge, and components whose provenance records prove
   MOT Deck ownership, while the old root and old code still exist.
2. Refuse if both old and new live roots contain state. Never merge or overwrite them.
3. Move the old live root atomically on the same filesystem, then rename the live
   manifest and its rotated backups.
4. Repair only explicitly enumerated generated launchers/configuration records. Every
   rewrite is validated and journalled; historical logs and retained forensic evidence
   are not rewritten merely to erase a word.
5. Migrate only whitelisted app preferences/WebKit state when the new bundle identity
   has no state. Active local-storage/UserDefaults keys migrate once from `harness.*` /
   `harness-*` to `motdeck.*` / `motdeck-*`; new values always win.
6. Replace the app-owned Hermes path-guard plugin ID in place, deduplicate it, and
   remove its retired generated copy only after the Hermes config transaction verifies
   the new ID is active. A foreign/symlink-shaped lookalike is reported and preserved.
7. Synchronize the FAT snapshot's repo-owned authoring surface through an explicit
   six-file allowlist. Remove only `app/Harness.icns`, `docs/HARNESS-INTERNALS.md`, and
   `docs/harness-architecture.md`, and the verified generated
   `guards/harness-path-guard/` copy, and only after each replacement is verified.
   Never recursively mirror `app/`, `docs/`, or `skills/`; generated, historical, and
   user-created neighbors remain outside this cleanup's authority.
8. Replace `/Applications/M.O.T.app` or another uniquely resolved old bundle only after
   the new `MOT Deck.app` has been built and identity-verified. Preserve a rollback copy
   until the complete real-stack journey passes.
9. A failure restores the old bundle/root/preferences and leaves a readable journal.
   No recovery step copies the repository template over live state.

Legacy literals are permitted only inside the migration implementation, migration
tests, and explicitly labelled historical documentation. Runtime code after migration
must not fall back to the old root, manifest, environment namespace, or bundle identity.

## Preservation contract

This is an identity migration, not a redesign or feature cut. All tabs, sidebar rows,
hover/drag/focus affordances, shortcuts, themes, layouts, stored sessions, models,
component configuration, install flags, local secrets, and third-party state must remain.
The M.O.T icon artwork remains byte-identical. No model file or user-created provider is
deleted. No third-party upstream code is changed.

## Permanent gates

- Source inventory classifies every remaining case-insensitive `harness` occurrence as
  either a third-party proper name, generic engineering term, historical evidence, or a
  deliberate old-identity migration literal.
- Build contract verifies the app/dmg/volume/bundle ID/executable/icon/manifest names.
- Resolver fixtures accept only `local.motdeck.app` + `MOTDeck`, canonicalize aliases,
  and fail closed on zero/ambiguous candidates.
- Migration fixtures cover fresh installs, old-only installs, new-only idempotence,
  old+new refusal, spaces, symlinks, interrupted migration, manifest backups, protected
  secrets, generated launchers, local preferences, path-guard deduplication/retirement,
  foreign-plugin preservation, allowlisted snapshot cleanup, symlink refusal, and
  rollback.
- Existing contract, JavaScript, standalone, Python, shell-hygiene, Bash 3.2, Swift
  parse, byte-ceiling, router-ceiling, and design/theme gates remain unchanged and green.

## Real-stack acceptance

From the installed shell, not merely source fixtures:

1. Existing live state is backed up and migrated; installed-component and model counts,
   pins, protected-secret fingerprints, sessions, and user layout/theme values match.
2. `./scripts/ship.sh` resolves `/Applications/MOT Deck.app`, passes the gate, restarts
   the bridge, and does not copy `motdeck.yaml` or `data/` from the repository.
3. App, bridge, and all previously running components return healthy from the new root;
   a real authenticated runner response and affected embedded-entry smoke journeys pass.
4. App quit/open works by `local.motdeck.app`; no active process/config/symlink depends
   on the old canonical source folder or old live root.
5. A clean committed FAT build produces `dist/MOT Deck.dmg`; mounting it shows volume
   `MOT Deck` containing `MOT Deck.app`, whose executable and bundle identity match this
   contract. The seed records `dirty_files=0`.

Only after all five pass may `VERSION` advance from 1.5.83 and the release be called
shipped.

## Honest limits

Historical prose, Git history, old rollback artifacts, and external/upstream names are
not rewritten. macOS may retain old Launch Services history until its cache refresh,
but the installed and newly built bundle must report only the new identity. The parent
folders named `New Harness` and `September 3rd new check harness` are outside the
approved rename boundary and remain unchanged.
