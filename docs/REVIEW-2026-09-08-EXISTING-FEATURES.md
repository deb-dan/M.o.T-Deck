# Existing-feature reliability review — 2026-09-08

Local candidate based on `5ee008f` (v1.5.90), reviewed and implemented solo.
The destination is to make the existing application more reliable without spending
its features, themes, controls, state, or upstream compatibility. This is not a
release announcement or a completed exhaustive audit. U170 in UNFORGET is the
authoritative remaining-assurance record.

## Scope and architecture understood

MOT Deck is a native Swift/WebKit shell around a first-party FastAPI bridge and
panel, coordinating a shared model runner and independently managed upstream tools.
The installed FAT app uses its Application Support snapshot, not this checkout.
The bridge facade deliberately propagates test monkeypatches to extracted modules;
the source-view manifest and contract gates are part of that architecture.

The history, architecture, release records, standing doctrine, roadmap and current
ledger were consulted before choosing changes. In particular: no downstream vendor
patches, no second model registry, no guessed process ownership, no copying the
repository's template YAML over live state, no disposal of unknown/shared files,
and no removal of intentional product affordances. The user explicitly requested
solo work; no delegation occurred. No pending roadmap feature was implemented.

The initial tracked first-party code/test inventory contained approximately 181,000
lines in 356 files. Inspection concentrated on the bridge facade and context,
streaming/history/turn ownership, downloads, storage and deletion, process ownership,
secret/state helpers, model settings, native navigation and shipping boundaries.
Source-wide syntax checks are separate evidence, not evidence that every line was
manually reviewed. Vendor internals and all historical prose were not exhaustively
read, and the requested whole-code line-by-line review remains incomplete.

## Reproduced defects and candidate corrections

| Existing user journey | Reproduced failure | Correction and permanent evidence |
|---|---|---|
| Direct chat with inline reasoning | Tags split across runner deltas appeared in visible text; reasoning and answer in the same event lost the answer | Incremental delimiter parsing and separate handling of both fields. Actual producer → TurnStore → history/sidecar tests cover five chunk widths and combined fields. |
| Runner disconnects or emits an error | Clean EOF without a completion frame looked successful; malformed events or proxy errors could be superseded by DONE | Require explicit runner completion, retain partial output, and make producer errors/unreadable events win over completion. No-space SSE data is accepted. |
| Stop/close a Direct response | Generator cleanup yielded during `aclose()`, raised `async generator ignored GeneratorExit`, and could fail to save the partial reply | Flush held text into history while suppressing emissions to a closing consumer. Executed close regression covers partial-delimiter preservation. |
| Producer emits an unterminated frame | Parsed-event limits did not bound the accumulating incomplete frame | Bound the pending frame and fail with a reason. Ignore trailing partial data after a parsed DONE. Turn-buffer contract tests exercise both. |
| Pause/resume/cancel a model download | A stalled old stream could remain alive while resume spawned another writer; paused cancel could delete the partial beneath its writer | Serialize controls and await the exact old task before resuming or cleaning partials. A stalled-network test checks one writer, byte-exact 2 MiB output, resume offset and single registration; cancel checks ordering. |
| Preview/apply owned storage removal | Intermediate symlinks let an apparently app-owned path reach external storage; replaced parents could invalidate consent | Record configured-root/parent identity and refuse intermediate links. Tests preserve external bytes and refuse a changed preview before any component stop. Final-entry symlinks retain their existing move-as-link behavior. |
| Failed multi-entry storage move | Rollback errors were swallowed; restoration could overwrite a replacement at the original path | Refuse occupied recovery destinations and report the retained Trash batch on incomplete rollback. Tests preserve replacement bytes and locate the original in the recovery batch. |
| Clear several conversations with one failed service call | An exception discarded the successful-delete receipts; the panel hid partial results behind a generic error | Retain every per-session receipt and display confirmed count plus individual failure reasons on the existing 409 partial-result path. No third-party database edits. |
| Optional installation poll, then preview or close storage | Delayed reads/timers could replace a newer preview or repaint/reopen a dismissed dialog | Invalidate old views and cancel polling on navigation, explicit close and native dialog close. Full controller execution covers delayed reads, preview, Escape and partial receipts. |
| Save model A settings and select model B | A's delayed response rendered A's sampling/load fields beneath B's selection or displayed A's error there | Update A's cache but render only for the captured selection; preserve active editing. Deferred-response tests exercise success/failure and typing for both handlers. |
| Large removal previews while bridge is serving other work | Synchronous inventory/size work occupied the async route | Move runtime, Music, Generate and reset plan builders to the threadpool. An executed slow-preview test verifies event-loop progress while inventory is blocked. This does not claim all storage I/O is asynchronous. |

New behavioral suites are `test_direct_stream_integrity.py`,
`test_download_controls.py`, `test_model_settings_races.js` and
`test_storage_dialog_lifecycle.js`. Existing turn-buffer, storage-uninstall and
chat-clear suites gained adversarial cases. Tests were executed red before their
corresponding fixes, including the additional close defect discovered in the final
self-review. The initial combined chat/storage reproduction had 13 failures; the
download reproduction had two. The close regression independently failed before its
correction.

Documentation also corrects the broken architecture link and retires obsolete
instructions to copy only `app.py` or erase Application Support/browser state as a
refresh procedure. The supported ship/reset paths are now named accurately.

## Verification evidence

Baseline `5ee008f`: 580 contract tests passed, four skipped; 753 repository Python
tests passed; every existing JavaScript program passed. The first sandboxed baseline
attempt had five environment-denied failures, listed below. The same unchanged
baseline passed those tests with the process/socket permissions they require.

Final candidate: 583 contract tests passed, four skipped; 774 repository Python
tests passed; all 53 JavaScript programs passed through `./scripts/verify.sh`.
All newly added affected tests executed; none was skipped.

Additional checks passed: Python AST parsing, shell syntax, external and inline
JavaScript syntax across the tracked first-party inventory; Swift frontend parsing;
`git diff --check`. The panel retained every baseline ID, aria-label and titled
affordance, with byte-identical inline style blocks. No vendor, dependency pin,
manifest template, version, native-shell source or theme stylesheet changed.

Browser evidence used the actual candidate HTML/assets served on an isolated local
origin. Fixture writes could not save real settings or delete real chats/files. The
delayed A→B settings journey retained B's MLX-specific fields. Storage preview and
its Close/Back/Apply controls were visually checked in Editorial, Warm Paper,
Luxury Gold, Cyber, Studio dark and Studio light. The partial-clear result displayed
its count and failed-session reason. This is browser evidence, not an installed
native WebKit acceptance claim. The temporary browser and server were closed.

The four unchanged skips in `test_aider_contract.py` are:

- `test_launch_flags_still_exist`
- `test_edit_format_whole_is_still_offered`
- `test_the_two_flags_we_refuse_still_exist`
- `test_our_argv_is_a_subset_of_the_real_parser`

Their stated reason is “aider not installed (or not runnable here)”; the dependency
fixture and pin checks ran. This is a runtime-coverage gap, not a passed parser check.

The initial sandbox-denied failures were
`test_detached_spawn_contract.py::test_live_detached_process_survives_a_group_kill`,
`test_detached_spawn_contract.py::test_a_missing_perl_refuses_instead_of_recreating_the_unsafe_group`,
`test_installers_contract.py::test_goose_truncated_download_refusal_executed`, and
`test_pidfile_port_contract.py::{test_the_exact_recorded_child_is_verified_without_rewriting_ownership,test_a_different_listener_is_never_adopted_or_signalled}`.
They encountered denied `ps`, socket or `/dev/fd` operations, and subsequently passed
at the unchanged baseline and candidate with the required permissions.
Two non-failing deprecation warnings remain: Starlette's legacy httpx TestClient
integration and an httpx raw-body upload call in the tests. Dependencies were not
upgraded merely to remove warnings.

## Reversibility and release boundary

The changes are separated into local commits by subsystem, followed by a report and
ledger commit. The companion output bundle contains the forward and reverse binary
patches, exact base/head IDs, commit list, full gate logs and rollback instructions.
The reverse patch is checked against the final checkout without applying it.
Use Git revert for history-preserving rollback after later development; do not use
a hard reset. No schema migration, user-data rewrite, live-settings copy, runtime
uninstall, dependency update or upstream fork was introduced.

The installed app remains v1.5.90. `VERSION` was deliberately not bumped for an
unshipped candidate. A versioned release must preserve a matching Factory reset
FAT seed and a recoverable installed bundle, then run the sanctioned ship gate and
affected native journeys. Copying these files manually into the live snapshot is
not the deployment procedure.

## Honest limits and recommendations

U170 records incomplete exhaustive coverage, the optional Aider parser gap and the
remaining installed native release acceptance. Browser checks did not execute real
runtime removal/reset, a real remote download interruption, or every model-settings
interaction in every design. Passing mock/disposable-data tests does not prove those
installed journeys. Existing U139 history idempotency limitations are untouched;
these streaming fixes do not claim exactly-once persistence.

The most useful continuation is to finish that assurance work before broadening the
product: verify candidate behavior at the native entry points, with disposable
owned resources and recovery receipts, then release from a recoverable versioned
checkpoint. Continue the file-level review with an explicit coverage record so
syntax scans cannot be mistaken for semantic review. The sole deferral authority
remains UNFORGET; this report does not create a second backlog.

To rerun the candidate gate from the canonical repository:

```sh
cd '/Users/debik/GemiAntigravity/September 3rd new check harness/New Harness/MOT Deck'
./scripts/verify.sh
```

The installed app will show this candidate only after a versioned release through
`./scripts/ship.sh` and the native checks above. No restart is needed for the current
local-only changes; refreshing the installed app still runs v1.5.90.
