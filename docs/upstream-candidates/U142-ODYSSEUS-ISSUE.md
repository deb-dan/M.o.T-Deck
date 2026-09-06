# Proposed title

API: add explicit manager ownership and retry-safe key rotation for model endpoints

**Submitted:** https://github.com/odysseus-dev/odysseus/issues/6256

# Issue body

## Problem

Integrations that provision a model endpoint cannot later rotate its API key safely.
User-created and integration-created endpoints share the same rows, while an endpoint
name, base URL, selected task model, or empty key does not establish who owns the row.
Creating by URL can deduplicate onto a pre-existing user row, and updating by public row
identity risks adopting or mutating user-owned configuration.

This also makes response-loss recovery unsafe: after an ambiguous key update, a manager
needs to discover whether its exact update committed without reading either plaintext
key back from the server.

## Expected contract

Provide an explicit manager/resource claim established only during deliberate
provisioning:

- creation is exclusive and refuses an existing unclaimed/differently managed URL;
- a high-entropy management token authenticates resolve/update operations, with only a
  domain-separated token hash stored server-side;
- manager/resource identity is unique and legacy rows are never adopted implicitly;
- key updates use compare-and-swap over a monotonic revision and full key fingerprint;
- identical retries return the committed receipt, conflicting retries fail closed;
- generic create/update/delete routes cannot bypass a managed claim; and
- legacy installations require an explicit operator-visible claim operation.

The API must not return plaintext endpoint keys. Tests should cover concurrent
provisioning, wrong tokens without row-existence disclosure, lost responses, rollback
CAS, generic-route bypasses, and legacy migration/uniqueness.

## Current implementation evidence

I have an isolated current-upstream candidate implementing the server-side ownership
primitive without inferring legacy ownership. Its affected tests all execute and pass
inside the same 5,927-pass comparison described in the separate idempotent Direct-turn
issue. I am opening the issue first and will split the implementation into one focused
PR only if this ownership/API direction is accepted.

## Environment

- upstream commit inspected: `934d23c0be29c9721385f34565c0ae2cbd60da04`
- macOS native Python test environment
- no UI changes
