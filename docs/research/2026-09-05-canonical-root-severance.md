# U81 — Canonical-root severance

Decision-complete build brief for the project promotion Debi authorized on 2026-09-05.
The canonical source tree is now:

`/Users/debik/GemiAntigravity/September 3rd new check harness/New Harness/MOT Deck`

The older Claude project tree is an archive. It remains on disk, but no executable,
generated dependency tree, normal build, ship, or running process may depend on it.
Never edit, delete, repair, copy from, or prune that archive while closing this slice.

## Measured defects

1. The canonical checkout's generated DeepSeek profile contains 432 symlinks below
   `data/deepseek/home/profiles/node_modules` whose targets are in the archived tree.
   A DeepSeek start from this checkout therefore still executes packages through the
   archive. The currently running snapshot's corresponding links are already local to
   the snapshot and must not be touched.
2. Ignored `app/Config.swift`, the snapshot copy, and the installed M.O.T executable
   contain the archived root. The fallback is inert today because this is a provisioned
   fat build, but `ship.sh` reuses an existing Config.swift and recompiles only when
   `main.swift` is newer. That can preserve or rebake the wrong root indefinitely.
3. Git still registers two archived Claude worktrees. They are not runtime dependencies
   and may contain unmerged work. This slice records them but does not unregister or
   delete them; Git worktree retirement is a separate preservation-first decision.

## Required implementation

### A. Swift configuration must be derived, never reused

In `scripts/ship.sh`, construct the exact desired `app/Config.swift` from the current
canonical `$ROOT` and `fatBuild = true` on every run. Use a temporary file plus `cmp`
and an atomic rename so an unchanged config keeps its mtime. Set `config_changed=1`
only when the desired bytes differ. Recompile the installed shell when either
`main.swift` is newer than the installed binary **or** the config changed. Never use
an existing generated config as input merely because it exists.

Keep `scripts/build_app.sh`'s build-kind behavior: it also derives the root from its own
checkout and writes `fatBuild` according to `--fat`. Correct its stale prose that says
normal lifecycle recipes depend on the `MOT Deck.app` filename; bundle identity is
`local.motdeck.app`, and the installed filename may be `MOT Deck.app` or `M.O.T.app`.

Permanent fixture contracts must prove:

- a stale Config.swift cannot survive the ship preparation step;
- a changed generated config forces compilation even when `main.swift` is not newer;
- an already-correct config is not rewritten and does not force compilation;
- a path containing spaces remains one valid Swift string value;
- production still uses `fatBuild = true`, while `build_app.sh` retains its thin/fat
  distinction.

Add a test-only ship seam if necessary, but it must exit before snapshot copying,
installed-app mutation, process changes, or ports. Do not test against the live bundle.

### B. Repair only DeepSeek's generated profile links

Extend `scripts/install_deepseek.sh` with a safe, testable profile-link repair that runs
on the already-installed-at-pin path as well as after a fresh install, before success is
claimed. Scope is exactly `$DSH_HOME_DIR/profiles/node_modules`.

The repair must:

1. do nothing when the directory is absent or every symlink resolves within the current
   `$PREFIX/node_modules`;
2. detect any symlink target outside the current prefix, including dangling absolute
   links;
3. refuse rather than guess if that generated tree contains a regular file, FIFO,
   socket, device, or any non-directory/non-symlink entry;
4. move the generated directory to one explicit sibling backup, refusing if that backup
   already exists;
5. run the pinned current `$DSH` with `DSH_HOME="$DSH_HOME_DIR"` and
   `DSH_TELEMETRY_DISABLED=1` so upstream rematerializes the profile tree;
6. verify the rebuilt tree exists, contains at least one symlink, and every symlink's
   resolved target is within the current `$PREFIX/node_modules`;
7. remove the generated-only backup only after full verification;
8. on any rebuild or verification failure, remove only the newly generated tree after
   applying the same generated-entry safety fence, restore the backup atomically, and
   exit nonzero with the consequence and cure.

Do not follow symlinks while classifying or deleting. Do not use `rm -rf` on an
unvalidated path, a variable outside the exact generated directory/backup pair, or any
archive path. Do not touch the snapshot's DeepSeek home. A dedicated helper in
`scripts/` is acceptable if it keeps the operation testable and stdlib-only.

Permanent temporary-directory tests must cover: clean local links/no-op; stale external
absolute links/rebuild; dangling stale links; nested link directories; a regular-file
refusal with no mutation; backup collision refusal; failed materializer rollback; and a
materializer that creates an escaping link, also rolled back. Tests must prove no file
outside the fixture profile is changed.

After the implementation and gates pass, run the supported repair from this canonical
checkout only. Verify zero symlinks below its DeepSeek profile resolve outside the
canonical DeepSeek prefix. Do not restart the live component merely to repair ignored
repo-local generated state.

### B2. Repair copied virtual-environment launch and editable-source pointers

The first broad collection after the DeepSeek repair exposed another operational
dependency class. The copied checkout's five `data/*-venv` trees still contain
generated launch scripts whose embedded interpreter path names the archived checkout.
Hermes and SearXNG additionally have PEP 660 editable finder files whose module maps
name the archived `vendor/hermes` and `vendor/searxng` trees. A copied venv can therefore
look present while its console scripts and editable imports execute the archive. Log
text, cached traceback filenames, and Git history are not operational dependencies.

Add one stdlib-only, atomic, fail-closed helper and fixture tests:

1. CLI: `repair_relocated_venvs.py --root ROOT`. Discover only immediate
   `ROOT/data/*-venv` directories containing `pyvenv.cfg`; never traverse arbitrary
   data directories or accept a foreign data root.
2. For every regular, non-symlink text file directly below `venv/bin`, replace an
   embedded absolute path ending in that exact venv's relative suffix
   (`/data/<name>-venv`) with the actual venv path. Preserve mode and every byte outside
   the replacement. Refuse NUL/binary files, symlinks, a path naming another venv, or
   any inferred source that cannot be proven by the exact suffix. Use sibling temp +
   `os.replace`; retain originals and roll all changed files back if later validation
   fails.
3. Under that venv's `site-packages`, consider only regular
   `__editable__*_finder.py` files. Rewrite absolute mapped paths only when the suffix
   resolves beneath `ROOT/vendor`; accept either that exact existing directory
   (package or a `NAMESPACES` directory) or its exact existing regular `<stem>.py`
   module (the PEP 660 finder stores module stems without `.py`). The proven source
   must remain inside `ROOT/vendor`. Hermes
   must resolve to this checkout's `vendor/hermes`, SearXNG to this checkout's
   `vendor/searxng`. No generic site-packages replacement is allowed.
4. Post-verify every changed console script contains no foreign
   `/data/<same-venv>` prefix, and every editable mapped path exists inside
   `ROOT/vendor`. Prove the canonical `hermes-venv` imports `hermes_cli` from canonical
   `vendor/hermes`, and `searxng-venv` imports `searx` from canonical
   `vendor/searxng`, using each venv's own `bin/python` after repair.
5. Run the helper on the repository root before the ship gate and on the snapshot root
   after code copy but before restart. The snapshot pass should normally be a no-op,
   but makes the boundary durable for a copied install. Neither pass may touch live
   YAML, model registries, logs, package contents, or the archived tree.
6. Contracts must cover a relocated fixture venv, spaces in roots, Hermes/SearX-style
   editable maps, idempotence, binary/symlink refusal, missing-destination refusal,
   atomic rollback, narrow discovery, and ship ordering.

`data/models.json` also contains three dead paths into the archive. They are missing
model artifacts, not relocation candidates: U75/U76 own their classification and
rescan semantics. U81 must neither rebase them to equally missing files nor delete
them opportunistically.

### C. Doctrine and release truth

Add the canonical absolute root and archive boundary to `CLAUDE.md`. Add U80 for the
duplicate Parakeet audio registry observation and U81 for this severance to
`docs/UNFORGET.md`. Do not mark U81 done until the canonical link tree is repaired and
the installed executable has been rebuilt by the corrected ship path, then inspected
to prove the archived root is absent.

The release is v1.5.77 only after: full contract gate; canonical repair; `ship.sh`;
all components + runner green; model/catalog/Aider checks; a real runner response; and
installed-binary/root inspection. The version bump, roadmap/ledger closure, commit and
push follow that evidence. `vendor/hermes` remains out of scope and unstaged.

## Builder verification floor

- focused new fixture contracts;
- `bridge/tests/test_deepseek_lane.py`;
- `bridge/contract_tests/test_app_identity_contract.py`;
- `bridge/contract_tests/test_installers_contract.py`;
- `scripts/verify.sh`;
- `bash -n` under the system Bash 3.2 for every changed shell script;
- `git diff --check` and explicit proof that `vendor/hermes` is the only unrelated
  worktree state.

The builder does not run `ship.sh`, change `VERSION`, commit, push, mutate the installed
app/snapshot, or touch the archived tree. Those are Sol QA/release responsibilities.
