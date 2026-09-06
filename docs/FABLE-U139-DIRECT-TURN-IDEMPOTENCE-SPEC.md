# U139 — exactly-once Direct Chat transcript insertion

**Date:** 2026-09-05; upstream rechecked 2026-09-06
**Status:** isolated current-main upstream candidate passes the controlled baseline,
focused, neighboring and repeated-race lanes; not accepted, released, pinned or shipped.

## Proven premise

U31 retries a Direct Chat history write after an ambiguous network result. Odysseus's
current `POST /api/session/{session_id}/message` and bulk-inject routes append a newly
generated database id on every accepted request. They accept metadata but expose no
idempotency key, uniqueness constraint, or receipt query guaranteed to be atomic with
the insert.

This was rechecked against upstream Odysseus main at `934d23c0…` on 2026-09-06, not
only against M.O.T's older pin. The latest `POST /session/{sid}/inject_messages` and
`POST /api/session/{session_id}/message` implementations still append ordinary
`ChatMessage` rows and expose no idempotency key, unique request constraint or stable
already-committed receipt. An upstream update therefore does not yet unblock U139.

The bridge reads back `mot_direct_request_id` before retrying, which prevents ordinary
duplicates. One unavoidable race remains: Odysseus can commit after the bridge's
read-back but before the fallback POST. The fallback then creates a second row. Calling
that exactly-once would be false.

## Rejected shortcuts

- Do not write directly to Odysseus SQLite from the bridge. That bypasses its owner,
  attachment, FTS, message-count, timestamp, event, and in-memory-session invariants.
- Do not infer uniqueness by matching text, timestamp, role, or the last row.
- Do not hold a bridge lock and claim it covers an independently committing Odysseus
  process or requests from another M.O.T process.
- Do not delete a suspected duplicate after the fact; identical messages can be
  intentional and delete is not an insertion transaction.
- Do not fork the pinned vendor locally to make a release claim. The zero-fork doctrine
  requires this seam upstream or an explicitly accepted maintained fork.

## Required upstream contract

Odysseus should expose an owner-scoped endpoint such as
`PUT /api/session/{sid}/direct-turn/{request_id}` whose transaction:

1. verifies session ownership and attachment reservations;
2. inserts the marked user/assistant pair, or returns the previously committed pair;
3. verifies the owner-scoped session, then enforces uniqueness on
   `(session_id, request_id, direct_role)` in the database;
4. updates in-memory history, message count, timestamps, FTS and other normal side
   effects exactly once;
5. returns stable message ids and an `inserted|already_present` receipt;
6. rejects the same request id with different content/metadata as a conflict.

Crash controls must cover before transaction, between pair rows, after commit before
response, concurrent identical requests, concurrent conflicting requests, process
restart, session deletion, and database retry.

## Current honest behavior

Direct Chat remains **at-least-once with marker read-back and visible uncertainty**.
That is materially safer than blind retry but is not mathematically exactly-once. U139
must stay open until the upstream transaction exists and M.O.T pins/tests it. No local
code change in this wave can honestly close it.

## Current-main candidate under renewed review

An isolated patch against Odysseus main `934d23c0…` now implements the required
`PUT /api/session/{sid}/direct-turn/{request_id}` primitive. It adds a database-enforced
unique receipt per session/request/role, validates the owner and exact user→assistant
grammar, preserves attachment reservation and normal message persistence, returns stable
message IDs, supports partial pair completion, and rejects same-key/different-payload
retries with HTTP 409. The transaction commits the pair and denormalized session counters
together; SQLite and non-SQLite migrations create the same uniqueness constraint.

Adversarial review found four gaps that the first suite missed:

- an assistant-only request could create the first receipt, allowing a later pair retry
  to store the user after the assistant;
- the response-loss test accidentally raised during the pre-write cache load rather than
  after commit, so it did not test the named failure boundary;
- an identical replay entered `get_session()`, whose access touch advanced
  `sessions.updated_at`, making the replay observably non-idempotent; and
- ownership was checked in a separate route transaction, leaving a rename race before
  insertion.

The isolated candidate now rejects assistant-first insertion while allowing assistant
completion after an existing user receipt, performs no side-effecting cache touch before
receipt lookup, exercises a genuine commit-before-response-loss replay, and carries the
authenticated owner into the insertion transaction. SQLite acquires `BEGIN IMMEDIATE`
before the owner read; databases with row locking use `SELECT ... FOR UPDATE`. A
concurrent owner change is therefore serialized behind the receipt commit, while a
wrong-owner request fails without evicting the legitimate session cache.

The permanent isolated suite now contains **24 passing cases** covering identical replay,
partial completion, user/assistant ordering, conflicting content/metadata, concurrent
single and pair writers, user-only versus pair races, true commit-before-response-loss,
stable replay timestamps/counters, authenticated-owner revalidation and concurrent
rename serialization, deleted sessions, valid/missing/conflicting attachments, migration
idempotence and route behavior. The attachment lane proves a successful replay neither
re-reserves nor changes the stored metadata. The 41-case focused-plus-neighboring
attachment run passes, and the seven highest-risk concurrency/response/owner cases pass
ten consecutive repetitions (70 checks).

The controlled full comparison uses sibling no-space worktrees at the same upstream
baseline and the same interpreter with explicit `PYTHONPATH` isolation:

- untouched `934d23c0…`: **5,909 passed, 7 failed, 4 skipped**;
- isolated U139 candidate: **5,933 passed, 7 failed, 4 skipped**.

The same seven nodes fail on both sides; all 24 additional candidate cases execute and
pass. An earlier alleged baseline run imported the mixed candidate through an editable
virtualenv link and is discarded as contaminated evidence, not averaged into these
totals.

### Exact baseline failure and skip classification

The seven failures are **not fixed**. They reproduce on untouched Odysseus main and are
disjoint from the Direct-turn/managed-endpoint changes, so they are not candidate
regressions. They remain upstream macOS/test-environment debt:

- four Unix-socket fixture failures—
  `test_container_opt_in_with_unix_socket_is_allowed`, both parameterizations of
  `test_socket_without_explicit_opt_in_is_disabled`, and
  `test_explicit_opt_in_with_unix_socket_is_enabled`—because the generated AF_UNIX path
  exceeds macOS's socket-path limit under the deep temporary checkout;
- `test_real_socket_falls_back_from_dead_first_to_live_second`, where the first dead
  loopback address times out on this host instead of reaching the fallback promptly;
- `test_rewrites_loopback_when_in_docker`, whose Docker-host assumption is absent here;
- `test_glob_confined_e2e`, whose assertion does not account for macOS's lexical
  `/var`→`/private/var` alias and the echoed caller-supplied relative pattern.

Three additional `test_run_focus.py` failures seen in the earlier project-path run are
not part of the controlled seven: both sibling comparison roots intentionally contain no
spaces, so those assertions pass. Their path-with-spaces expectation remains separately
recorded upstream portability debt, but it is not reported as a failure in this final
comparison.

The four skips also do not cover U139/U142 code: the Windows-only Ollama CLI startup
guard; a Docker test requiring the unavailable `odysseus-odysseus:latest` image; an
optional MarkItDown runtime test when `markitdown` is absent; and a content-detection
test when `python-magic`/`libmagic` is absent. They are unexecuted optional/platform
coverage, not passes. None is a U139 case.

This does not change the shipped M.O.T claim. The bridge cannot call an unreleased API,
and adding dead feature detection before a pin exists would be speculative. Closure still
requires upstream acceptance/release, an Odysseus pin bump, bridge integration, response-
loss testing through the real network seam, and the human Direct Chat history journey.
The isolated candidate is preserved as the normal-context, exact-base-checked
`docs/upstream-candidates/U139-odysseus-idempotent-direct-turn.patch` (SHA-256
`1c74973fe7e220842121f770ad3f41ff0b30b38b3f8091434664617637bdbe5f`). The older
combined U139/U142 patch is superseded forensic evidence and must not be submitted.

Odysseus's contribution rules require an issue before an agent-assisted PR, one focused
change per PR, and `dev` as the target branch. No matching idempotent-message issue/PR
was found in the upstream search. The issue-first report is now upstream issue
[#6255](https://github.com/odysseus-dev/odysseus/issues/6255), with the submitted text
preserved at `docs/upstream-candidates/U139-ODYSSEUS-ISSUE.md`. The currently combined
evidence patch must be split from U142 only after the API direction is accepted; it is
not ready to submit as one broad PR.
