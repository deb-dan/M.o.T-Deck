# U144 — Goose provider deletion must be one owner transaction

**Date:** 2026-09-06
**Status:** upstream deletion seam required; no local heuristic cleanup is permitted.

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
3. restore the preimage if any write fails before commit;
4. return an exact receipt naming which resources were removed or already absent;
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
