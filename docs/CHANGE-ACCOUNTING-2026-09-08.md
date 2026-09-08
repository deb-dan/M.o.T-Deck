# Change accounting: last shipped batch and current review batch

2026-09-08. Written in response to the user's request for every change and a candid distinction between fixing a cause and containing a failure.

## Release boundary

- **Last shipped batch:** v1.5.91 and v1.5.92, starting from `5ee008f`, ending at `ea47eb1`. Installed v1.5.92 and previously pushed to the approved `Debkbas/mot-deck` repository. Release verification is recorded in RELEASE-v1.5.92-RELIABILITY.md.
- **Committed review batch:** the retained non-RAM changes after `ea47eb1` are committed as `2ebb3ae` (180 files) and pushed to the approved `Debkbas/mot-deck` `main`. The user explicitly approved retaining and committing this batch on 2026-09-08. At the earlier approval checkpoint Git reported 175 changed paths (121 modified and 54 untracked); final-gate corrections and documentation brought the committed checkpoint to 180 paths. It remains **unshipped and not release-accepted**. The complete repository gate passed; native and packaging acceptance remain outstanding.
- The whole-code review is still in progress. A file being read, a unit test passing, and an installed user journey passing are three different claims. None substitutes for another.
- No intended feature, theme, or design removal; no upstream source fork or second model registry. No pending roadmap feature is claimed as implemented.
- Third-party names in this inventory identify MOT Deck-owned adapters, launchers, installers, embedding pages and contracts. The retained batch does not modify the tracked source of Hermes, Odysseus, Goose, OpenCode, Aider, ONLYOFFICE, ComfyUI or the Music engines; those integrations remain updateable through their normal pinned upstream paths.

## Classification

**Cause:** the implementation changes the mechanism responsible for the identified defect. This is not a promise that the entire subsystem has no other defects.

**Safeguard:** it preserves data, refuses an invalid transition, bounds a wait, or reports failure accurately. It does not repair whatever caused an external failure or invalid input.

**Partial:** a safeguard or bounded improvement whose broader underlying problem remains unresolved or insufficiently checked. These must not be described as fully fixed.

## Corrections to earlier review reporting

1. **RAM, the memory ledger, and fit calculations — REVERTED AND OUT OF SCOPE.** The review briefly changed the MLX unreadable-configuration result, ledger zero handling, fit/GGUF parsing, preference/measurement readers and related tests. The user rejected that direction and instructed the review to leave this area alone. Those changes were removed. `bridge/core/fit.py`, `bridge/core/ggufhdr.py`, `bridge/core/memory.py`, `bridge/core/memoryprefs.py`, `bridge/core/runnermeasure.py`, and `bridge/tests/test_fit_advisor.py` match `ea47eb1` exactly. RAM-specific edits were also removed from the shared panel/tests, and the two new RAM test files were removed. This accounting preserves the incident but creates no instruction to resume it.
2. **Unreadable state preservation — SAFEGUARD.** OpenCode, Hermes, DeepSeek, Goose provider files, download registration, migration and secrets now refuse or preserve unknown state instead of overwriting it. This fixes our data-destruction behavior; it does not repair a user's malformed JSON/YAML, filesystem permissions, or an inaccessible disk. No claim that those external causes were repaired is justified.
3. **Network/worker failure handling — SAFEGUARD, sometimes paired with a cause fix.** HTTP/response validation, honest failed-turn/job receipts, timeouts and last-good UI state prevent false success, lost state or a permanently wedged control. They do not make an unavailable upstream service work. Retryable CSS loading and request ownership are concrete mechanism fixes; a generic error receipt is not.
4. **Office mismatched-document save refusal — PARTIAL.** Rejecting a save when the embedded editor and destination disagree protects another document. Many stale-document producers have also been fixed with captured document/generation checks, but complete producer coverage has not been established. The refusal alone is not complete resolution of that flow.
5. **Auxiliary/Goose stop refusal — SAFEGUARD plus lifecycle correction.** Waiting on the owned process and retaining its handle until exit fixes premature completion. Refusing to replace an unverified or still-running process is necessary preservation, not a repair of every reason a process refuses to stop. Pending auxiliary credential rotation remains outside this task.
6. **Storage responsiveness — PARTIAL.** Preview builders and more runtime apply/stop/verification work run off the async event loop. Generate's final artifact apply and Music's corresponding apply still need examination; this is not a claim that all storage I/O is nonblocking.
7. **RAM/fit observations are not a continuation item for this batch.** The original `ea47eb1` behavior is preserved by explicit user direction. No calculation, fallback, fit verdict, ledger sample or advisor preference is represented as fixed by this review.
8. **Test size ceiling — USER-APPROVED POLICY EXCEPTION, not an app fix.** The panel source-size ceiling changed from 877,700 to 885,000 bytes; the current file is 880,942 bytes. The user approved retaining the higher ceiling and required a future-investigation record. It does not improve runtime performance and must not be counted as such. U171 records the old ceiling, new ceiling, current size and the requirement to investigate the growth instead of treating this exception as a precedent for another increase.
9. **No assertion that these are the only remaining gaps.** The inventories below state what was changed. The audit for symptom-only changes and the exhaustive review are unfinished. The review therefore does not claim everything is fixed or that all remaining root causes are unfixable. Missing/corrupt information cannot safely be reconstructed by guessing; valid supported formats that MOT Deck misreads remain MOT Deck's responsibility to fix.

## Last shipped batch — complete behavioral inventory

| ID | Change | Classification / limit |
|---|---|---|
| L01 | Parse reasoning delimiters across streaming chunk boundaries; preserve both reasoning and answer when one event contains both. | Cause: incremental parser and independent field handling. |
| L02 | Require actual runner completion; do not turn EOF, malformed events or proxy errors into successful completion; preserve partial output and accept SSE without a space after `data:`. | Cause for false completion; safeguard for external transport failure. Does not repair the external connection. |
| L03 | During generator close, persist held partial text without yielding into a closing consumer. | Cause: fixes `async generator ignored GeneratorExit`. |
| L04 | Bound unfinished stream frames and ignore trailing fragments after DONE. | Safeguard for oversized/malformed producer output; prevents unbounded accumulation. |
| L05 | Serialize download pause/resume/cancel; wait for the exact old transfer before a new writer or partial-file cleanup. | Cause: removes concurrent writers and deletion beneath a writer. Real disposable HTTP transfer test included. |
| L06 | Bind storage removal preview to root/parent identity and reject intermediate symlinks or changed parents before stopping/removing anything. | Cause for ownership escape; refusal is the necessary response to changed consent evidence. |
| L07 | Preserve occupied restoration destinations; surface incomplete storage rollback and retained recovery location. | Cause for overwrite during rollback; safeguard when restoration itself fails. No claim to repair a failed filesystem. |
| L08 | Keep individual conversation-clear receipts when some upstream deletes fail; display confirmed count and failures. | Cause for lost receipts; safeguard for refused deletes. Does not force upstream deletion. |
| L09 | Invalidate delayed storage dialog reads and poll timers on preview/navigation/close/Escape. | Cause: older responses cannot repaint a newer or dismissed dialog. |
| L10 | Capture the model owning each settings response; avoid rendering A's result or error under B; preserve active editing. | Cause: fixes wrong-selection writes/rendering. |
| L11 | Serialize settings writes per model so an older save cannot overtake Reset. | Cause: ordering of mutations. |
| L12 | Disable Install selected when no eligible optional tool is selected. | Cause: correct eligibility, not removal of the installation feature. |
| L13 | Run runtime/Music/Generate/reset preview inventory work in the threadpool. | Cause for those blocking previews; explicitly incomplete for all storage I/O. |
| L14 | Only remove Odysseus attachment/reasoning sidecars after successful conversation deletion; preserve neighbors and refused targets. | Cause: stops local data loss after upstream refusal. It does not change upstream protection/star behavior. |
| L15 | Interpret Odysseus offset-free timestamps as UTC in its adapter. | Cause: stops fresh conversations showing hours-old locally. |
| L16 | Correct architecture and deployment documentation; remove obsolete copy-only-app.py and erase-state refresh instructions. | Documentation correction. |
| L17 | Add regression coverage, version/release receipts, FAT build/signature/seed verification, native checks and rollback evidence. | Validation/release work, not additional product features. Git and installed release establish the checkpoint. |

The last batch's largest scope failure was its narrowed scope: a focused review did not fulfill the requested exhaustive review. Its report acknowledges this, but that acknowledgement did not complete the work.

## Current batch — complete behavioral inventory at this snapshot

Changes are grouped by user behavior rather than by every edited line. The exact file inventory follows below. Each numbered row can include closely related changes made together.

| ID | Change | Classification / remaining limit |
|---|---|---|
| C01 | Analytics cache-hit percentage includes cache misses in its denominator. | Cause: correct aggregation. |
| C02 | Memory-ledger zero/key changes were attempted during review. | **Reverted.** No retained behavior change. |
| C03 | Comfy disk verdict distinguishes zero free bytes from an unavailable reading. The separate zero-RAM-budget edits were removed. | Cause for disk-capacity truth; **RAM portion reverted.** |
| C04 | Memory-preference reader widening was attempted during review. | **Reverted.** No retained behavior change. |
| C05 | GGUF/fit shape and context guards were attempted during review. | **Reverted.** No retained behavior change. |
| C06 | The MLX unknown-cache “No estimate” behavior and subsequent architecture experiments were attempted during review. | **Reverted.** No retained behavior change and no follow-up authorization. |
| C07 | Artifact saves validate UTF-8/size, use exclusive collision-safe names, reject invalid destinations and report filesystem failure. | Cause for overwrite/races; safeguards for invalid files/full disks. |
| C08 | API-key mutations are serialized and atomically persisted with private permissions; rollback maintains agreement between key state and configuration; validate labels/numeric fields. | Cause for inconsistent state and conflicting writes; cannot repair an unavailable disk. |
| C09 | Regular-file reads use nonblocking open before type checks in retained secret, YAML, ownership/journal, model-metadata, guard and seeder paths. | Cause for FIFO-open hangs in these paths; special files are refused, not converted. Does not claim every file reader was covered. RAM preference and runner-measure reader changes were reverted. |
| C10 | Launch receipts include stronger identity/key evidence; use distinct staging files and retain ownership until the exact child has exited. | Cause for stale receipt/premature retirement. |
| C11 | Model deletion handles already-missing artifacts and keeps restoration inside the registry transaction lock. | Cause for erroneous deletion failure and rollback overwriting concurrent registry edits. |
| C12 | Close turn producers before terminal completion is published. | Cause: completion cannot overtake cleanup. |
| C13 | Stop retries remain attached to their own turn; late timers cannot stop another turn. | Cause: request/turn identity. |
| C14 | Hermes completion follows cleanup; errors remain failed; cancellation records interruption; close nested generators and release RPC resources. | Cause for incorrect ordering/leaks; safeguard for upstream error outcomes. |
| C15 | Native shell avoids stale split-tab routing and duplicate/focused reload mistakes; bound dropped-file reads and clean up cancelled/crashed navigation. | Cause in routing/lifecycle; file limits are safeguards. Native acceptance still pending. |
| C16 | Aider/Goose PTY socket setup and relay failures clean up resources; grace timers use stable owner identity and locking. | Cause: lifecycle and timer races. |
| C17 | Aider/Goose page events, takeover, End and history updates remain bound to the owning connection and armed selection. | Cause: stale socket responses and false End completion. |
| C18 | Goose history distinguishes unknown count from zero; handles failed/non-JSON listing without fabricating an empty store; removal runs off-thread. | Safeguard for unavailable history; cause for blocking route and false empty state. |
| C19 | Goose UI validates runtime adoption records; Stop retains the process/claim until verified exit; refused stop prevents duplicate replacement. | Cause for orphaned ownership; safeguard where process identity/exit cannot be verified. |
| C20 | Goose named-provider seeding preserves malformed/non-object/invalid-UTF-8 files, refuses FIFOs, and uses private unique atomic publication. | Cause for overwriting user settings and FIFO hangs; does not repair malformed user data. Added and tested in the retained post-v1.5.92 batch. |
| C21 | Odysseus vision setup preserves unreadable settings/endpoint lists and deliberately disabled endpoints. | Safeguard; no claim to repair the upstream API failure. |
| C22 | Rename the owned Odysseus vision endpoint with verified PATCH instead of delete/recreate; stale cleanup recognizes exact loopback hostnames. | Cause for lost endpoint identity/references and unsafe substring matching. |
| C23 | Audio search distinguishes a valid empty result from failed requests, skips malformed rows and prioritizes STT configuration over a shared mlx-audio tag. | Cause for wrong model classification and false failure; safeguards for invalid responses. |
| C24 | Completed downloads merge into existing registry data under the shared writer and preserve user fields/metadata; corrupt registry is not overwritten. | Cause for clobbering; safeguard for corrupt input. |
| C25 | Registry local discovery compares complete artifact identity, not only model names; stable collision IDs cannot steal another artifact's saved settings on subsequent scans. | Cause: identity/collision handling across GGUF, projectors, MLX and audio. |
| C26 | Comfy workflow dependency checks enumerate every weight widget, including multiple text encoders and mapping-shaped widgets. The extracted `core.comfyfiles` module is registered in the facade propagation list so test/runtime root overrides reach the file logic that consumes them. | Cause: incomplete workflow incorrectly marked ready; facade registration prevents a moved module from silently reading the wrong tree. |
| C27 | Comfy output publication uses collision-safe exclusive destinations and moves staging off-thread; cancellation avoids unrelated global interrupts; download cleanup waits for its own writer. | Cause: output collisions, blocking work and wrong-owner cancellation. |
| C28 | Generate page preserves drafts, last good status and selected gallery through polls; coalesces updates, fences stale replies and accepts valid keyboard actions; library remains usable without an engine. | Cause for redraw/state races; safeguard for failed responses. |
| C29 | Compose page preserves form drafts, output-directory selection and gallery/playback identity; fences stale status, armed Stop, layout/engine/template changes; corrects Unicode and even-count timing median handling. | Cause for state loss, stale operations and arithmetic. |
| C30 | Music generation uses a private working directory, owned-process cancellation and exclusive output/sidecar publication. | Cause: cross-job filename collisions and premature publication. |
| C31 | Music Classic preserves every form field through structural redraws; newest status/library request owns the result; audio element/playback position survives refresh. | Cause: draft/playback loss and stale repaint. |
| C32 | Voice worker parsing handles line-oriented output and response deadlines; model-stop synchronization and reference/source identity prevent stale reuse. | Cause for protocol/ownership/cache defects; deadline is containment, not a diagnosis of every stalled worker. |
| C33 | TTS response cache keys include request parameters and reference identity rather than incorrectly reusing another response. | Cause: incomplete cache identity. |
| C34 | Voice configuration changes validate first, write scalar changes together and unload only after persistence succeeds. | Cause: partial configuration and memory/disk disagreement. |
| C35 | Voice reference/heal operations compare the full expected registry entry after awaits before changing it. | Cause: stale asynchronous operation replacing a newer user selection. |
| C36 | Voice trim uses unique staging, actual subprocess success/nonempty output and unchanged-source evidence; cache names include source path/stat identity. | Cause for collisions/stale/invalid published clips; refusal preserves a changed source. |
| C37 | Voice library saves use exclusive names and durable writes; delete handles all pinned assignments transactionally and restores them on failure. Final-gate follow-up now executes deletion across every assignment while requiring unrelated metadata to survive. | Cause: collisions and dangling assignments/data loss. |
| C38 | Main panel refresh coalesces concurrent work, handles null/invalid SSE, parallelizes independent reads and retains valid state on failed requests. | Cause for redundant work/races; safeguards for external failure. Performance not yet benchmarked for this batch. |
| C39 | Navigation preferences save serially with revision ownership and restore only the correct confirmed state after failure. | Cause: out-of-order optimistic saves/rollback. |
| C40 | Inline control arguments use JavaScript serialization plus HTML attribute escaping across navigation, Help, capabilities, MCP, Hermes, skills, search, music and session actions. The Hermes toolset contract now checks the escaped production call shape rather than accepting the old raw-quote marker. | Cause: quote/ampersand-containing IDs and labels broke controls; the corrected contract prevents a test from pinning the unsafe form. |
| C41 | Design loading shares pending work, rejects stale selections and retries failed loads; Studio Office removes failed CSS links so later selection can load them. | Cause for stuck loading and wrong-design application. Themes retained. |
| C42 | Voice playback, manual microphone and automatic voice mode bind permission, recording, transcription, playback and worklet callbacks to the current operation. Leaving a view/session cancels that ownership and releases late streams. | Cause: late permission/output reviving or contaminating another session; errors still reported. |
| C43 | Clip saving retains pending content on failure; clears only the saved clip; reference text/path and external pin identity stay together. | Cause: failed-save data loss and stale source mismatch. |
| C44 | Command palette handles quoted arguments, escaped icons, empty selection, invalid indices and IME composition. | Cause: broken invocation/navigation while typing. |
| C45 | Artifact rendering/saving uses request and document identity; late renderer/save cannot replace a newer canvas or clear newer edits. | Cause: stale asynchronous ownership. |
| C46 | Artifact HTML CSP is inserted in the actual document prologue; quote-aware parsing avoids fake head tags in content. | Cause for ineffective/misplaced policy; a policy still is a containment boundary. |
| C47 | CSV artifact parsing handles BOMs, ragged rows, wider later records and delimiters outside quoted fields. | Cause: real parsing/data-shape defects. |
| C48 | JSON artifact trees expand lazily with bounds; React preparation recognizes single-expression default arrow exports at the proper syntax boundary. | Cause: excessive rendering and broken valid artifact parsing; limits remain safeguards. |
| C49 | Chat open/resume/new/duplicate actions have selection tokens; preserve the prior view until the new session is valid; reconcile Odysseus parallel reads safely. | Cause: old requests replacing another chat. Does not implement pending exactly-once history work. |
| C50 | Hermes first-send preparation is single-owner; attachment/draft context cannot be duplicated or overwrite later typing. | Cause: double preparation and draft loss. |
| C51 | Chat rename/delete use captured session identity, validate responses, prevent duplicate deletion and stop voice for the correct session. | Cause for wrong-session effects; safeguards for refusal. |
| C52 | Image FileReader callbacks, pending drop/session selection and attachment sidecar cleanup retain their own identity; remove unrelated-attachment fallback. | Cause: wrong image or sidecar attached to another conversation. |
| C53 | Model search/probes keep only the newest matching query/repository result; expanded stale probes cannot repaint another search. | Cause: stale search/result mismatch. |
| C54 | Model Apply waits for the latest queued save, validates the model receipt and prevents duplicate or wrong-selection reload. | Cause: loading before requested settings persisted. |
| C55 | Office snapshot I/O preserves literal formula-like and forced-text values; writes sparse cells safely and refuses destructive saves of truncated reads; creates exact backups. | Cause for coercion/truncation data loss; refusing incomplete readback is a safeguard, not full support for larger documents. |
| C56 | Office asset responses honor Brotli quality-zero, plain/range behavior and `Vary`; compressed siblings use the same containment checks. | Cause: incorrect encoding/cache selection and boundary escape. |
| C57 | Office server preview/verification compares type as well as displayed text, captures staging mtime before reading and refuses create-over-existing races. | Cause: false unchanged/verified results and stale preview overwrite. |
| C58 | Office undo publishes a fully written checkpoint atomically; preserves filesystem failure details. | Cause: partially overwritten workbook on failed undo; does not repair a failed disk. |
| C59 | Office style handling accepts explicit off/zero values, records the full permitted styled-cell set and verifies it; date-write guidance preserves numeric date semantics. | Cause: inability to remove formatting, incomplete verification and advice that broke date arithmetic. |
| C60 | Office numeric-text coercion retains values exceeding spreadsheet precision; aggregate warnings inspect sparse stored cells instead of every coordinate in a huge formula range. | Cause: rounding/data loss and enormous empty-grid loops. |
| C61 | Office grid duplicate sheet names fit the 31-character limit; one-row/one-column merges survive structural edits; ragged writes and visible merge clipping are handled correctly. | Cause: invalid names, lost merges and incorrect writes/display. |
| C62 | Office structural edits and sort remap offscreen sparse cells and their formatting; sheet switches commit the prior edit, respect IME and reject stale cell context. | Cause: misplaced/lost cells and edits applied to another sheet. |
| C63 | Office undo/dirty tracking compares actual saved content, excluding incidental mtime/dimension changes; asynchronous saves retain newer typing. | Cause: false clean/dirty state and lost edits. |
| C64 | Office open/create/import/remove/rename/template operations capture request/document identity; newest file-list request owns the response; failed reads keep the previous list. | Cause for cross-document races; safeguard for failed reads. |
| C65 | Office editor start/refresh/save/PDF/reload and parent/child messages carry document identity; pending actions cancel or ignore stale completion; external reload requires matching clean state. Final-gate follow-up executes parent-owned save identity and failure propagation instead of accepting the older direct-save predicate. | Cause for wrong-document actions; native/editor acceptance still pending. |
| C66 | Office embedded saves return actual success/failure; mismatched source/destination refuses instead of saving another workbook. | **Partial:** refusal protects data; all mismatch producers are not yet proven eliminated. |
| C67 | Office approval/changeset controls serialize apply/undo and track pending/done/expired states; only matching receipts update the intended document; uncertainty remains visible. | Cause for duplicate/stale actions; safeguard where the server outcome is unverified. |
| C68 | Office Agent history restoration, session creation/naming, send finalization, clear and changeset reads are sequence/session/document-bound; refused sends retain proposed changes. | Cause: competing history and send actions lost or mixed state. |
| C69 | Office computed results qualify sheet references and preserve missing/blank information; quick/agent SSE readers handle terminal markers, null frames and cancellation cleanup. | Cause for cross-sheet confusion and stream leaks; missing results are still missing. |
| C70 | Office external-change checks capture document/request generation, only claim reload after success, restore dirty state on failure and keep retry baselines valid. | Cause for stale banners, false reload success and lost dirty state. |
| C71 | Office Close/discard flows use document-scoped confirmation and actual save success; deleted-cell/context-menu and home-keyboard handling respect current state. | Cause: accidental discard/wrong-document close and invalid UI actions. |
| C72 | Office AI input cap handles supported small contexts; malformed/nonfinite runner fields are handled without invalid probes or crashes. | Cause for the 4,096-token minimum exceeding smaller contexts; **partial** because effective per-model runtime context versus manifest context still needs resolution. |
| C73 | Optional-tool worker exceptions produce failed receipts and release the job; failed thread startup does not leave an eternal running flag. | Cause for permanently wedged queue; exception receipt does not resolve arbitrary installer failure. |
| C74 | Runtime storage verification/stop/apply and Generate verification/stop move off the event loop, with busy-state recheck after waits. | Cause for these blocking paths; **partial**, remaining apply paths noted above. |
| C75 | Goose and OpenCode installers validate private candidates before publication, clean up failures/signals and confine version probes; Goose UI stages a fresh destination. | Cause: failed repair replacing a working installation or probes writing to user profiles. |
| C76 | Office AI plugin installer validates archive/SDK/layout/GUID before publication; stages all files and restores the previous installation on ordinary publication failure; final stamp follows successful publication. Its executable fixture now checks that no receipt can appear at any intermediate asset rename and that publication happens only after the complete asset set exists. | Cause for mixed/half-installed plugin. **Limit:** abrupt SIGKILL can leave its install lock/staging area; automatic crash recovery not established. |
| C77 | FAT setup/build handles BSD file checks and seed receipts, includes MLX pins, preserves wheelhouse/local setup and existing Searx configuration. | Cause in packaging/setup preservation; full new FAT acceptance pending. |
| C78 | Manifest reader, launcher and migration paths reject invalid/special-file state; identity migration recognizes assignment names with the optional `_B64` suffix while preserving values, comments and custom suffixes; WhatsApp reconciliation journals before mutation and avoids exposing secrets in output. | Cause for specific ordering/key/reading defects; refusal is a safeguard where input cannot be read. The `_B64` omission was exposed by the final-gate baseline comparison and corrected in the retained batch. |
| C79 | OpenCode, Hermes and DeepSeek seeders validate existing configuration, preserve unknown structures/metadata, make private atomic/no-op writes and avoid logging honored secrets. | Cause for configuration loss/leak; does not reconstruct corrupt configuration. |
| C80 | Tests execute actual panel implementations instead of copied parsing/rendering models in multiple artifact/chat suites; update asynchronous fixtures and clean up loops/temp runtime/process setup. The Office-plugin installer contract now asserts the staged publication mechanism instead of pinning the retired destructive `rm`/`unzip` sequence. | Validation improvement. Does not itself fix production behavior. |
| C81 | Optional runtime contracts use explicit skips for missing dependencies, stricter help/exit checks and isolated homes; detached-process checks use finite child lifetimes and identity-based cleanup. | Validation correctness; skipped runtime paths are not passed coverage. Some process/socket tests require their normal OS permissions. |
| C82 | Navigation standalone runner now executes its two previously omitted migration tests; correct malformed-version fixture precedence and expectations for existing later layout changes. | Validation improvement; 373 standalone checks passed. |
| C83 | Add the file/range coverage record and current accounting report; expand regression suites for all affected areas. | Evidence/communication, not product functionality. Coverage remains incomplete. |

## Evidence and unresolved verification

The last shipped release report records the full v1.5.92 gates and native acceptance. The retained batch now has one complete repository-gate result, but remains unshipped and lacks native acceptance. Earlier focused runs included 100 Hermes-provider/DeepSeek tests, 39 Goose-provider/UI tests, 373 navigation checks, the Office AI standalone suite, and voice/Office/installer/frontend regressions.

The first new full-gate attempt reported 563 contract passes, 24 explicit skips and two failures. The second reported 565 contract passes and the same 24 skips, followed by 976 repository Python passes and four failures. Each failing test passed unchanged at exact baseline `ea47eb1`, so none was waived as baseline debt. One exposed a real facade omission: extracted `core.comfyfiles` was in `appsrc.FILES` but absent from `bridge.app._LANES`, so facade root overrides did not propagate. The other three assertions pinned superseded implementation shapes for escaped Hermes toolset arguments, editor-owned Office saves and all-assignment voice deletion. The facade was corrected; the assertions were updated and behavioral checks were added for quoted Hermes rendering/invocation, parent Office save ownership plus failure propagation, and voice deletion across all assignments with metadata preservation. A focused seven-file run then passed 23 tests.

The final repository gate passed with exit 0: **565 contract tests passed with 24 explicit skips; 981 repository Python tests passed with two warnings; all 72 discovered JavaScript files passed** (including the two shared helper files). The six whole-file RAM implementation/test sources still match `ea47eb1`, the shared panel remains 880,942 bytes, and the checked vendor Git trees have no source diff.

The separate installed-runtime audit initially executed the 24 skipped contracts with 22 passes and two Voicebox failures. Both failures reproduced at exact baseline `ea47eb1` against the same installed pin, so the candidate did not introduce them; that baseline comparison was evidence, not an exemption. The stale tests searched only `*mcp*.py` names and missed `backend/mcp_server/server.py`; the installed implementation uses FastMCP's supported mounted HTTP application.

The first continuation after `2ebb3ae` corrects those two contracts without changing Voicebox or any vendor source. Discovery now includes the `backend/mcp_server` modules. The transport contract inspects the active `create_app` implementation and its `/mcp` mount; the tool contract executes the upstream `register_tools` body with a recording decorator, without invoking a tool, database or model, and verifies the four exact `voicebox.*` tool names. The installed-runtime audit now passes all **24 of 24** checks. A separate installed FastMCP probe registered the actual upstream tool body into a real FastMCP registry and found all four exact names; its actual `http_app(path="/", transport="http")` accepted an MCP initialize request through ASGI with HTTP 200. No Voicebox tool ran and no model or database loaded.

The continuation is limited to the unresolved non-RAM work below and the remaining whole-code review. The RAM/ledger/fit area stays at the exact `ea47eb1` implementation by the user's instruction. This accounting does not create new roadmap commitments or silently expand scope into pending features.

## Batch sequence and continuation boundary

1. **Shipped batch, v1.5.91–v1.5.92:** L01–L17 above. This is committed, installed and pushed through `ea47eb1`; its release evidence is final for that release.
2. **Committed review batch, `ea47eb1` → `2ebb3ae`:** C01–C83 above, with C02/C04/C05/C06 and the RAM portion of C03/C09 explicitly reverted. The user approved the remaining batch and it was committed as an unshipped 180-file checkpoint. Ship and final acceptance evidence must be added only after they actually occur.
3. **Current continuation inside U170:** finish the non-RAM cause analysis and verification listed below. This is existing-feature work, not authority to begin P6/P3/P5/S4/S7/U3 or any other roadmap feature.
4. **Continuation batch after `2ebb3ae`, in progress:** the first item repaired and executed the two stale Voicebox installed-contract tests; all 24 installed checks now pass. The Office AI plugin process-crash cause is now resolved by a first-party publication helper, an inherited kernel lock and a durable journal written before mutation. At the `2ebb3ae` baseline, killing the shell after the first candidate asset publication exited `-9`, stranded `.install-lock`, and made the next install exit 1 with “another plugin install is active.” The new full-shell fixture kills the publisher and parent installer at that same point; the next invocation recovers and then completes successfully.

Recovery is idempotent after SIGKILL and preserves conflicting external replacements instead of overwriting them. Executed cases cover fresh and replacement installs; death at journal creation, every rename, commit and cleanup; death during recovery; concurrent lock refusal; lock release after process death; and a surviving child retaining the inherited lock until it exits. The combined normal-host suite passed **65 tests**. A clean real-network install into an isolated target succeeded with 666 files: all 663 archive payload files were byte-identical to the downloaded ZIP and all three SDK files matched their exact SHA pins. The shell remains responsible for downloading and verifying those upstream pins; no upstream source is changed. The helper is included by the existing `scripts/` copy in both ordinary shipping and the FAT seed. Process-crash recovery does not claim power-loss durability, full FAT acceptance or native installed acceptance.

The continuation's complete repository gate passed: **565 contract tests passed with 24 explicit skips; 1,013 repository Python tests passed with two warnings; all 72 JavaScript files passed**. The separate installed-runtime audit passed all 24 checks. This is repository and focused installed-contract evidence, not native or packaging acceptance.

At this evidence checkpoint the continuation changes are confined to `bridge/contract_tests/test_voicebox_contract.py`, `bridge/contract_tests/test_installers_contract.py`, `bridge/tests/test_office_plugin_publication.py`, new `bridge/tests/test_office_plugin_crash_recovery.py`, `scripts/install_oo_ai_plugin.sh`, new `scripts/oo_plugin_install.py`, and the accounting/roadmap/ledger documents. This list must be refreshed if later U170 fixes join the same commit.

A deeper installer echo read found the same crash class in **Goose UI**. Its `STAGE="$DEST/.ui-install"` directory is also its exclusion mechanism, so SIGKILL can strand the directory; publication also moves the current `ui` to `.ui-old` and then moves the candidate into place without a durable journal. The first narrow search missed it because the directory is named `STAGE`, not `LOCKDIR`. This remains open under U170 and means the Office correction does not close the installer echo. Goose CLI and OpenCode publish one validated binary with one final rename; their possible staging debris is a distinct cleanup question rather than Goose UI's multi-item/stranded-lock transaction.

Each later U170 batch must extend this sequence with its exact base/head commit, retained/reverted changes, gate and installed-journey evidence, and unresolved limits. A batch is called shipped only after its versioned commit and installed release evidence exist; planned work is never backfilled into a completed batch.

The open non-RAM work is: repair and prove Goose UI's same-class stranded lock/non-journaled publication; trace every Office document-mismatch producer; establish configured versus effective Office AI context authority; support complete large-workbook fallback rather than relying only on a truncated-save refusal; finish the Music and Generate final-apply responsiveness audit; retain the Office plugin's power-loss/FAT/native boundaries; keep unreadable configuration preservation distinct from repair; distinguish bounded timeout/failure receipts from diagnosis of upstream worker failures; and complete clean packaging plus affected native/all-design journeys. U171 separately records the approved panel-size ceiling investigation.

## Exact changed-file inventory

This lists the tracked changes and new source/test files committed in `2ebb3ae`. It makes test-only edits and documentation visible alongside application changes. The full `ea47eb1..2ebb3ae` Git diff remains the authoritative line-level description.

### Modified tracked files

- `bridge/app.py`
- `app/main.swift`
- `bridge/appsrc.py`
- `bridge/contract_tests/test_attach_lanes_contract.py`
- `bridge/contract_tests/test_detached_spawn_contract.py`
- `bridge/contract_tests/test_installers_contract.py`
- `bridge/contract_tests/test_llama_server_contract.py`
- `bridge/contract_tests/test_llama_tts_contract.py`
- `bridge/contract_tests/test_manifest_reader.py`
- `bridge/contract_tests/test_mlx_audio_stt_contract.py`
- `bridge/contract_tests/test_mlx_whisper_contract.py`
- `bridge/contract_tests/test_no_name_kills_contract.py`
- `bridge/contract_tests/test_odysseus_msg_contract.py`
- `bridge/contract_tests/test_odysseus_seed_contract.py`
- `bridge/contract_tests/test_opencode_contract.py`
- `bridge/contract_tests/test_pidfile_port_contract.py`
- `bridge/contract_tests/test_voicebox_contract.py`
- `bridge/contract_tests/test_voicestudio_contract.py`
- `bridge/core/analytics.py`
- `bridge/core/comfycur.py`
- `bridge/core/hermesattachments.py`
- `bridge/core/hermesturn.py`
- `bridge/core/localsecrets.py`
- `bridge/core/modeldelete.py`
- `bridge/core/modelid.py`
- `bridge/core/modelreg.py`
- `bridge/core/ownership.py`
- `bridge/core/procs.py`
- `bridge/core/turns.py`
- `bridge/core/yamlset.py`
- `bridge/gooseprov.py`
- `bridge/music.py`
- `bridge/office.py`
- `bridge/office_ops.py`
- `bridge/oo.py`
- `bridge/ooai.py`
- `bridge/panel/aider.html`
- `bridge/panel/assets/turn-stream.js`
- `bridge/panel/comfy.html`
- `bridge/panel/compose.html`
- `bridge/panel/goose.html`
- `bridge/panel/index.html`
- `bridge/panel/office.html`
- `bridge/panel/oo.html`
- `bridge/pty_aider.py`
- `bridge/pty_goose.py`
- `bridge/routers/aider.py`
- `bridge/routers/apikeys.py`
- `bridge/routers/aux.py`
- `bridge/routers/comfy.py`
- `bridge/routers/downloads.py`
- `bridge/routers/goose.py`
- `bridge/routers/gooseui.py`
- `bridge/routers/hermes.py`
- `bridge/routers/hf.py`
- `bridge/routers/misc.py`
- `bridge/routers/ody.py`
- `bridge/routers/odyvision.py`
- `bridge/routers/oo.py`
- `bridge/routers/storage.py`
- `bridge/routers/turns.py`
- `bridge/routers/voice.py`
- `bridge/tests/test_api_view.js`
- `bridge/tests/test_app_facade.py`
- `bridge/tests/test_artifact_kind_v2.js`
- `bridge/tests/test_attach_marker.js`
- `bridge/tests/test_audio_drop.js`
- `bridge/tests/test_audio_registry.py`
- `bridge/tests/test_audio_switch.js`
- `bridge/tests/test_canvas_logic.js`
- `bridge/tests/test_chat_toolerr.js`
- `bridge/tests/test_conv_mode.js`
- `bridge/tests/test_csv_parse.js`
- `bridge/tests/test_events_hub.py`
- `bridge/tests/test_fence_classify.js`
- `bridge/tests/test_goose_lane.py`
- `bridge/tests/test_gooseui_lane.py`
- `bridge/tests/test_gooseui_runtime_adoption.py`
- `bridge/tests/test_hermes_skills.js`
- `bridge/tests/test_hermes_toolsets.js`
- `bridge/tests/test_hermes_toolsets.py`
- `bridge/tests/test_hermes_turn_durability.py`
- `bridge/tests/test_model_load.py`
- `bridge/tests/test_model_settings_races.js`
- `bridge/tests/test_model_source_availability.py`
- `bridge/tests/test_mtp_detect.py`
- `bridge/tests/test_nav_model.py`
- `bridge/tests/test_nav_panel.js`
- `bridge/tests/test_office_ai.js`
- `bridge/tests/test_office_grid.js`
- `bridge/tests/test_oo_ai_lane.py`
- `bridge/tests/test_oo_lane.py`
- `bridge/tests/test_opencode_lane.py`
- `bridge/tests/test_react_prep.js`
- `bridge/tests/test_rewrite_cdns.js`
- `bridge/tests/test_sse_hybrid.js`
- `bridge/tests/test_starter_voices.py`
- `bridge/tests/test_storage_optional_install.py`
- `bridge/tests/test_studio_design.js`
- `bridge/tests/test_studio_office.js`
- `bridge/tests/test_turn_lifecycle.js`
- `bridge/tests/test_vad_segmenter.js`
- `bridge/tests/test_voice_ref.py`
- `bridge/tests/test_voice_tts.py`
- `bridge/tests/test_voice_worker.py`
- `bridge/voice.py`
- `bridge/yamlfile.py`
- `guards/motdeck-path-guard/__init__.py`
- `scripts/build_app.sh`
- `scripts/firstrun_fat.sh`
- `scripts/install_goose.sh`
- `scripts/install_goose_ui.sh`
- `scripts/install_oo_ai_plugin.sh`
- `scripts/install_opencode.sh`
- `scripts/install_searxng.sh`
- `scripts/migrate_local_secrets.py`
- `scripts/migrate_motdeck_identity.py`
- `scripts/read_manifest.py`
- `scripts/reconcile_hermes_whatsapp.py`
- `scripts/seed_deepseek_config.py`
- `scripts/seed_hermes_provider.py`
- `scripts/seed_opencode_config.py`
- `scripts/seed_registry.py`
- `scripts/start_component.sh`
- `docs/ROADMAP.md`
- `docs/UNFORGET.md`

### New files

- `bridge/core/comfyfiles.py`
- `bridge/tests/_panel_source.js`
- `bridge/tests/test_analytics_accuracy.py`
- `bridge/tests/test_api_key_transactions.py`
- `bridge/tests/test_artifact_request_ownership.js`
- `bridge/tests/test_artifact_review_regressions.js`
- `bridge/tests/test_artifact_save_files.py`
- `bridge/tests/test_audio_discovery_truth.py`
- `bridge/tests/test_capacity_truth.py`
- `bridge/tests/test_comfy_operation_truth.py`
- `bridge/tests/test_comfy_required_weights.py`
- `bridge/tests/test_comfy_view_state.js`
- `bridge/tests/test_compose_view_state.js`
- `bridge/tests/test_download_registry_preservation.py`
- `bridge/tests/test_editor_write_truth.js`
- `bridge/tests/test_goose_history_truth.py`
- `bridge/tests/test_gooseui_stop_truth.py`
- `bridge/tests/test_guard_policy_truth.py`
- `bridge/tests/test_hermes_completion_truth.py`
- `bridge/tests/test_inline_control_arguments.js`
- `bridge/tests/test_installer_candidate_preservation.py`
- `bridge/tests/test_launch_completion.py`
- `bridge/tests/test_migration_state_truth.py`
- `bridge/tests/test_model_delete_consistency.py`
- `bridge/tests/test_model_reload_order.js`
- `bridge/tests/test_model_search_order.js`
- `bridge/tests/test_music_classic_state.js`
- `bridge/tests/test_music_publication.py`
- `bridge/tests/test_native_pane_routing.py`
- `bridge/tests/test_office_changeset_truth.py`
- `bridge/tests/test_office_file_truth.py`
- `bridge/tests/test_office_plugin_publication.py`
- `bridge/tests/test_office_review_regressions.js`
- `bridge/tests/test_panel_attachment_selection.js`
- `bridge/tests/test_panel_clip_truth.js`
- `bridge/tests/test_panel_preferences_truth.js`
- `bridge/tests/test_panel_refresh_truth.js`
- `bridge/tests/test_panel_session_ownership.js`
- `bridge/tests/test_panel_voice_ownership.js`
- `bridge/tests/test_pty_grace_races.py`
- `bridge/tests/test_pty_socket_cleanup.py`
- `bridge/tests/test_registry_local_identity.py`
- `bridge/tests/test_regular_file_reads.py`
- `bridge/tests/test_runner_start_receipts.py`
- `bridge/tests/test_seeder_preservation.py`
- `bridge/tests/test_setup_preservation.py`
- `bridge/tests/test_terminal_connections.js`
- `bridge/tests/test_turn_producer_cleanup.py`
- `bridge/tests/test_turn_stop_ownership.js`
- `bridge/tests/test_vision_config_preservation.py`
- `bridge/tests/test_voice_response_truth.py`
- `bridge/tests/test_voice_state_updates.py`
- `docs/CHANGE-ACCOUNTING-2026-09-08.md`
- `docs/WHOLE-CODE-REVIEW-COVERAGE.json`
