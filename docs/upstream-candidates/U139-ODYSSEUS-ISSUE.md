# Proposed title

API: make owner-scoped Direct-turn insertion idempotent under retries

**Submitted:** https://github.com/odysseus-dev/odysseus/issues/6255

**Historical submitted body:** the implementation-evidence numbers below were withdrawn
after adversarial review. The prepared correction is
`U139-ODYSSEUS-CORRECTION-COMMENT.md`; use the post-correction isolated evidence in the
Fable spec, never silently rewrite this record of what was posted.

# Issue body

## Problem

An external client that stores a completed user/assistant Direct turn can receive an
ambiguous network result after Odysseus commits the message. The current append routes
generate new database IDs for each accepted request and expose no idempotency key or
stable receipt. A read-before-retry reduces ordinary duplicates but cannot close the
race where the first request commits after the read and before the retry.

This is a general API reliability gap for clients that must retry after response loss.
It cannot be solved correctly by matching message text/timestamps or by writing directly
to Odysseus's database, because those approaches either conflate legitimate repeated
messages or bypass session, attachment, FTS, counter, timestamp, event, and ownership
invariants.

## Reproduction

1. Send a user/assistant pair to an owned session.
2. Let the server commit, but interrupt or discard the HTTP response.
3. Observe that the client cannot distinguish “not committed” from “committed but
   response lost.”
4. Retry the current append route with the same logical request.
5. The retry can append a second pair because no database uniqueness constraint binds
   the logical request.

## Expected contract

Add an owner-scoped idempotent operation keyed by an opaque client request ID. In one
database transaction it should verify ownership/attachments, insert the exact
user→assistant pair or return the already-committed receipt, preserve normal persistence
side effects, and reject reuse of the key with different content or metadata.

Acceptance should cover concurrent identical/conflicting requests, partial completion,
commit-before-response-loss, process restart, deleted sessions, attachment conflicts,
and migration idempotence. Stable receipts should return message IDs and distinguish
`inserted` from `already_present` without relying on text equality.

## Current implementation evidence

I have an isolated candidate against current upstream that adds a PUT primitive,
database uniqueness, stable receipts, partial-pair completion, conflict handling, and
SQLite/non-SQLite migrations. Its affected tests all execute and pass. The full local
comparison is 5,927 passes with ten clean-upstream macOS/environment failures and four
optional/platform skips; the exact unrelated nodes are available for review. I am
opening the issue first as required and will not submit code until the intended API
shape is accepted.

## Environment

- upstream commit inspected: `934d23c0be29c9721385f34565c0ae2cbd60da04`
- macOS native Python test environment
- no UI changes
