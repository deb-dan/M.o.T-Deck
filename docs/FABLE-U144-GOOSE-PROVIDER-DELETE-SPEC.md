# U144 — Goose provider deletion must be one owner transaction

**Date:** 2026-09-06
**Status:** first current-main transaction candidate rejected after adversarial
ownership/concurrency review; not released, pinned or shipped.

## Proven premise

The real U51 journey deleted a temporary provider through Goose's own UI. Goose removed
the custom-provider definition and its owned secret, but left the corresponding
`providers.<id>` enabled/model stanza in Goose's `config.yaml`. The row was inert after
the definition disappeared, but “Delete Provider” did not remove the full provider
state it had created.

M.O.T pins Goose 1.48.0. Goose 1.49.0 and current upstream main were re-read on
2026-09-06: `remove_custom_provider` still removes the provider JSON file and generated
secret but not the config stanza, and the ACP `on_delete_custom_provider` path still
calls that operation directly. Updating Goose therefore does not fix U144.

## Rejected shortcuts

- Do not watch the config directory and remove any stanza whose provider file vanished.
  A human can intentionally preserve or recreate configuration, and a watcher has no
  transaction or exact delete intent.
- Do not sweep provider ids that look M.O.T-like. The temporary U51 provider was created
  through Goose's UI and belonged to the user once created; names are not ownership.
- Do not inject a post-delete cleanup script into the renderer. A crash between Goose's
  delete and the cleanup recreates the same split state, and renderer internals are not
  a deletion receipt.
- Do not edit Goose's config before its deletion succeeds. If Goose refuses or crashes,
  that would destroy live configuration while retaining the provider.
- Do not fork the vendored Goose release and describe it as an upstream fix.

## Required upstream contract

Goose's own delete operation should transact over the exact provider id and:

1. capture the provider definition, owned secret reference and provider config stanza;
2. remove all three only after revalidating that the secret belongs to that provider;
3. durably commit an exact deletion intent before the first destructive write, then
   roll forward after any post-commit interruption (or leave every resource unchanged if
   intent persistence fails);
4. retain an idempotency receipt so a delayed retry cannot target a newly reused id;
5. preserve unrelated providers, secrets and configuration byte-for-byte; and
6. remain idempotent across retry after an ambiguous response.

If Goose instead exposes a supported pre/post-delete extension hook with a stable
transaction id and rollback API, M.O.T may participate through that seam. The current
direct WebSocket renderer connection offers neither interception nor commit authority.
A new local ACP proxy would be a substantial protocol-ownership decision, not a small
patch, and must be justified against an upstream contribution first.

## Hostile acceptance matrix

- definition missing, config present; config missing, definition present;
- secret absent, user-supplied env secret, and provider-generated secret;
- failure before each write and crash after commit before the response;
- concurrent provider edit, rename and delete;
- identical provider display names with distinct ids;
- retry of the same deletion and conflicting reuse of the id;
- every unrelated config byte and secret fingerprint unchanged;
- real Goose UI Delete Provider journey followed by restart and a clean re-list.

## Current decision

U144 remains open. M.O.T 1.5.81 cleaned the one temporary QA provider exactly and left
no residue on this installation, but that one named cleanup is not a general product
fix. Neither Goose 1.49.0 nor current main closes the upstream gap, so no upgrade or
local watcher is shipped under this issue.

## Rejected current-main candidate

An isolated Goose-main patch attempted to make the provider's own delete operation converge the
definition, generated provider-owned secret and exact `providers.<id>` stanza under an
in-process mutex plus cross-process file lock. Before deleting anything it atomically
persists a private, fsynced intent. Startup rolls incomplete intents forward; completed
receipts remain as tombstones so generated IDs are never reused and a delayed explicit
retry fails closed if a legacy/manual definition reuses the old ID. Recovery skips completed
tombstones—they are receipts, not delayed delete commands. User-supplied secret references
and unrelated providers/secrets are preserved. Already-clean config and secret files are not
rewritten during recovery.

The first candidate was rejected during review because deleting the journal after success
made a late retry capable of deleting a new provider with the same ID. The tombstone design
replaces it. Focused deletion/config tests now pass 33 checks; the broader provider run is
**495 passed, 0 failed** under Goose's supported CI shape:
`cargo test -p goose --no-default-features --features rustls-tls,code-mode providers --lib`.
Strict Rust clippy also passes with warnings denied.

The earlier **491 passed, 4 failed** total came from an incomplete ad-hoc invocation using
the crate's empty default feature set. Without `rustls-tls` or `native-tls`, no
process-level `jsonwebtoken` crypto provider is installed, so
`test_parse_jwt_claims_verified_with_issuer`, `test_service_account_jwt_creation`,
`test_token_expiration`, and `test_token_refresh_race_condition` panic before exercising
provider deletion. Clean upstream produces the same four failures under that unsupported
shape; they were neither U144 regressions nor product failures. Goose's own CI matrix
explicitly runs both TLS feature lanes, which is why the corrected supported result is
authoritative.

One repeated default-feature parallel diagnostic also produced a fifth, transient
`unconfigure_provider_clears_structured_entry` missing-temp-file failure. It passed alone,
passed serially, did not reproduce on clean-main broad parallel, and is green in the
supported feature lane. It remains recorded as an upstream parallel test-isolation signal,
not silently counted as a pass and not attributed to U144.

Adversarial review then found two premise failures, so the candidate is rejected despite
those green lanes:

- It inferred ownership of a secret from
  `api_key_env == generate_api_key_name(provider_id)`. A hand-authored provider may
  legitimately reference that same environment-variable name. A permanent test creates
  exactly that provider, stores a user-owned secret, deletes the provider, and currently
  fails because the candidate deletes the user's secret. Generated-looking spelling is
  not provenance.
- Its deletion lock coordinates the new provider create/update/delete paths, but Goose
  has other configuration writers using a different per-process mutex and temp-file
  replacement. Locking a temporary output file is not a stable cross-process mutation
  lock. Concurrent unrelated config changes can still be lost, so the transaction is
  not yet over the complete writer graph.

A replacement needs explicit persisted secret-origin metadata at provider creation
(legacy/unknown origin must never authorize secret deletion), plus one stable mutation
lock and recovery protocol shared by every writer of the affected configuration. Corrupt
configuration must fail closed rather than marking an intent complete before the stanza
can be examined. Only after those predicates are implemented can the earlier interruption,
ID-reuse and byte-preservation tests support a transaction claim.

Goose's existing ACP response schema returns the exact provider ID but not per-file
deletion details, so M.O.T cannot repair this from the renderer. Upstream acceptance,
release, a pin bump, and the real Goose UI delete→restart→re-list journey remain required
before U144 can close. The rejected candidate and failing ownership test are preserved at
`docs/upstream-candidates/U144-goose-provider-delete.patch`.

Goose's contribution process is stricter than patch readiness: the reporter must write
the issue, the issue must reach **Ready** on the public board, and only then may an
external PR implement the agreed design. The duplicate search found related UI/cache
deletion reports but no issue for the exact orphaned `providers.<id>` stanza transaction.
The human-submission draft is preserved at
`docs/upstream-candidates/U144-GOOSE-ISSUE-DRAFT.md`. It has been corrected so it no
longer advertises this rejected implementation. No code will be posted ahead of that
process.
