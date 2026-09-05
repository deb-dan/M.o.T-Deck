# U139 — exactly-once Direct Chat transcript insertion

**Date:** 2026-09-05  
**Status:** upstream primitive required; no local implementation is permitted yet.

## Proven premise

U31 retries a Direct Chat history write after an ambiguous network result. Odysseus's
current `POST /api/session/{session_id}/message` and bulk-inject routes append a newly
generated database id on every accepted request. They accept metadata but expose no
idempotency key, uniqueness constraint, or receipt query guaranteed to be atomic with
the insert.

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
3. enforces uniqueness on `(session_id, owner, request_id, direct_role)` in the database;
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
