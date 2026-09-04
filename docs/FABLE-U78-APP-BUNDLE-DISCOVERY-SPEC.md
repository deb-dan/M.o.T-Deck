# FABLE SPEC — U78 installed app bundle discovery

**Authority:** Debi's reported 2026-09-05 ship failure and standing repair permission.
**Orchestrator:** GPT-5.6 Sol (Fable role).
**Builder:** GPT-5.6 Terra, from this decision-complete brief only.
**Binding:** `CLAUDE.md`, `docs/DOCTRINE-PROACTIVE-BUILD.md`, the live-state rule,
the process-kill rule, and the delegation doctrine preserved in the archive.

## 0. Proven failure

`scripts/ship.sh` assigns `APP="/Applications/Harness.app"` and refuses before its
gate when that exact directory is absent. On Debi's machine the installed bundle is
`/Applications/M.O.T.app`; its `Info.plist` still carries the expected internal identity:

- `CFBundleIdentifier = local.harness.app`
- `CFBundleExecutable = Harness`
- `CFBundleName = M.O.T`
- `CFBundleDisplayName = M.O.T`

The expected live snapshot exists at `~/Library/Application Support/Harness`, and the
repo build artifact remains `dist/Harness.app`. Finder can therefore install the same
bundle under its localized display name even though the build output retains its legacy
filename. Treating the filename as identity is the defect.

This slice changes the repository only. Do not move, rename, copy, sign, open, quit, or
otherwise modify either installed bundle or the snapshot while building/testing. Do not
run `ship.sh`, component scripts, or app lifecycle commands. Never touch `vendor/`.

## 1. Installed-bundle resolver

Add one pure/read-only resolver to `scripts/ship.sh`, before any gate or copy:

1. If `HARNESS_APP_PATH` is non-empty, consider only that explicit path.
2. Otherwise consider these exact paths:
   - `/Applications/Harness.app`
   - `/Applications/M.O.T.app`
   - `$HOME/Applications/Harness.app`
   - `$HOME/Applications/M.O.T.app`
3. A candidate is valid only when all are true:
   - it is a directory;
   - `Contents/Info.plist` exists;
   - `CFBundleIdentifier` read from that plist is exactly `local.harness.app`;
   - `CFBundleExecutable` is exactly `Harness` and `Contents/MacOS/Harness` is
     executable (the later incremental-compile path targets that same executable).
4. Zero valid candidates: fail before the gate with an actionable sentence listing the
   accepted locations and the `HARNESS_APP_PATH` override.
5. More than one valid candidate without an override: fail closed, list the paths, and
   ask for an explicit `HARNESS_APP_PATH`. Never guess which installed copy owns the
   user's running app.
6. Exactly one valid candidate: canonicalize the existing bundle directory to a full
   physical path, assign that path to `APP`, and print one selection line before the
   gate. This applies to relative explicit overrides too, so `open` and the survivor
   process check use the same absolute path truth.
7. An invalid explicit override fails with its path and the identity requirement. It
   must never fall through to another bundle.

Paths are always quoted and preserved as one argv item. The resolver may use
`/usr/libexec/PlistBuddy`, already used later in `ship.sh`. It must have fixture-only
CLI seams so tests can pass temporary candidate roots without probing live applications.

## 2. Lifecycle identity

Replace the filename/display-name AppleScript quit request with the stable bundle id:

```sh
osascript -e 'tell application id "local.harness.app" to quit'
```

Keep `_ship_app_pids` as the post-request survivor check; because `APP` is now the
resolved bundle path, its executable-path evidence remains exact. Do not add `pkill`,
`killall`, name matching, or blind port termination.

The canonical app-only commands in `CLAUDE.md` become:

```sh
osascript -e 'tell application id "local.harness.app" to quit'
open -b local.harness.app
```

`ship.sh` itself must continue to open the exact resolved `APP`, not use Launch Services
bundle-id selection, so multiple registered copies cannot redirect the post-ship launch.

## 3. Same-class echo

`scripts/install_component.sh` searches installed FAT-app wheelhouses under only
`Harness.app`. Extend that read-only candidate list to the same four filename/location
forms so reinstall/bootstrap behavior does not fail later for the identical reason. Do
not change candidate precedence outside adding the corresponding M.O.T forms.

Audit all first-party executable shell/Python code for `/Applications/Harness.app` and
name-based app lifecycle calls. Fix only operational reads/actions in this slice;
historical prose and build-output paths (`dist/Harness.app`) remain valid. Report every
operational hit and disposition.

## 4. Permanent gates

Update `bridge/contract_tests/test_app_identity_contract.py` so it pins the new truth:

- build output remains `dist/Harness.app` with visible name M.O.T;
- ship accepts either installed filename only after bundle-id/executable validation;
- a spaced temporary candidate path is preserved;
- wrong bundle id, missing/alternate/slash-containing executable declarations, and a
  non-executable `Contents/MacOS/Harness` are rejected;
- zero candidates and ambiguous candidates fail closed;
- explicit override selects only the requested valid candidate and rejects an invalid
  override without fallback;
- quit uses `local.harness.app`, not the strings `Harness` or `M.O.T` as process identity;
- ship opens the exact resolved path;
- install-component wheelhouse discovery includes both installed filenames.

Update `bridge/contract_tests/test_no_name_kills_contract.py` to accept and require the
bundle-id Apple Event while preserving every existing no-name-kill fence.

Tests must exercise temporary app fixtures only. A fixture Info.plist may be minimal,
but must be read by the real resolver. No `/Applications` or snapshot reads/writes in the
test path.

Run:

- the focused resolver/identity tests;
- `test_no_name_kills_contract.py`;
- `test_installers_contract.py`;
- `test_u74_recovery_hardening.py` (ship-health echo);
- `test_script_hygiene.py` and `test_ops_hardening.py`;
- the full `bridge/contract_tests/` gate;
- Bash 3.2 syntax and `git diff --check`.

## 5. Documentation, versioning, and acceptance

- Add U78 to `docs/UNFORGET.md` only after Sol verification, with the observed failure
  and accepted filenames.
- Correct the naming note in `README.md` and the operational app-path text in
  `docs/HARNESS-INTERNALS.md`; preserve the internal codename/snapshot conventions.
- `VERSION` remains `1.5.76`. This is still an unshipped candidate: doctrine requires a
  successful `ship.sh` and real-stack walk before the release may become v1.5.77.
- Builder must not edit docs, version, commit, push, or touch live paths. Sol owns those.

Acceptance states:

- **repository slice verified:** all affected and full contract gates pass against
  temporary fixtures;
- **shipped:** only after Debi runs/authorizes the corrected command and final
  authenticated `/api/status`, selected model, catalogs, and component states are
  observed.

## 6. Builder report

Return the exact files changed, operational hard-coded-path audit, tests/counts/exit
codes, and honest limits. Make no commit, push, version bump, live app action, or
snapshot action.
