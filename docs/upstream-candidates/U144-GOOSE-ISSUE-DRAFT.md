# Proposed title

Deleting a custom provider leaves its provider configuration stanza behind

# Human-submission boundary

Goose's contribution guide asks the reporter—not their agent—to write the issue and
requires the issue to reach **Ready** before an external PR is opened. This draft is
therefore preparation only. It must not be posted automatically or presented as an
accepted design.

# Suggested issue body

## Problem

Deleting a custom provider through Goose Desktop removes its custom-provider definition
and generated provider-owned secret, but can leave the corresponding
`providers.<provider_id>` enabled/model stanza in `config.yaml`. The orphan is inert once
the definition disappears, but the user-visible Delete Provider action has not removed
all state that provider creation added.

## Reproduction

1. In Goose Desktop, create a temporary custom provider and select a model.
2. Confirm that the definition, generated owned secret, and
   `providers.<provider_id>` configuration exist.
3. Use Goose Desktop's confirmed Delete Provider action.
4. Restart Goose and inspect/re-list provider configuration.
5. The definition and generated secret are gone, while the provider's configuration
   stanza remains.

## Expected behavior

Goose's own provider-delete operation should remove the exact provider definition, only
the secret Goose generated for that provider, and that provider's exact config stanza as
one crash-recoverable operation. It must preserve user-supplied secrets and unrelated
configuration, remain idempotent after a lost response, and refuse a delayed retry if a
new provider has reused the old ID.

## Why a UI cleanup is insufficient

A renderer-side follow-up or directory watcher recreates a split transaction if either
side crashes and has no authority to distinguish user-retained configuration from the
state owned by the exact delete action. The convergence belongs in Goose's provider
owner.

## Verification requested

- interruption before and after every destructive write;
- definition/config/secret already missing in each combination;
- generated versus user-supplied secret references;
- concurrent edit/delete and delayed retry after ID reuse;
- unrelated configuration byte-for-byte preserved; and
- real Desktop delete → restart → re-list journey.

I reproduced the orphaned stanza and explored a current-main transaction candidate, but
adversarial review rejected that implementation: it inferred secret ownership from a
generated-looking environment-variable name, and its lock did not cover every Goose
configuration writer. Those are exactly the kinds of partial fix this issue should avoid.

The design needs explicit persisted provenance for provider-generated secrets (legacy or
unknown provenance must preserve the secret), plus one stable mutation lock/recovery
protocol shared by every writer of the affected configuration. I am seeking agreement on
that ownership and transaction boundary before proposing code.
