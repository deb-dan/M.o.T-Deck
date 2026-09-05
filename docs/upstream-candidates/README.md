# Unshipped upstream candidates

These patch files preserve reviewed work against exact upstream commits. They are not
vendored M.O.T changes, are not copied by `ship.sh`, and do not change the currently
installed application. This directory is evidence and handoff material, not a hidden
fork.

| Issues | Upstream baseline | Patch | Current boundary |
| --- | --- | --- | --- |
| U72 | Hermes `ee5b5ec21e576ccf9b941f9ff71330418415a5cb` | `U72-hermes-local-confinement.patch` | Direct-filesystem-write confinement candidate; upstream acceptance, release, pin bump and M.O.T real-lane validation still required. |
| U139/U142 | Odysseus `934d23c0be29c9721385f34565c0ae2cbd60da04` | `U139-U142-odysseus-idempotence-managed-endpoints.patch` | Upstream idempotent Direct-turn and managed-endpoint primitives; M.O.T callers intentionally do not exist before a released pin. |
| U144 | Goose `5e90925962f05acf8e255032de44d16c4a7768a2` | `U144-goose-provider-delete.patch` | Provider-owned transactional deletion candidate; upstream acceptance, release, pin bump and real Goose UI delete/restart/re-list still required. |

Each patch was generated with `git diff --binary --full-index --unified=0` from an
isolated clone and checked with `git apply --check --unidiff-zero` against a clean
checkout of the baseline above. Zero context avoids storing unified-diff blank-context
spaces that would weaken M.O.T's own trailing-whitespace gate; the full blob indices and
exact baseline commit keep the target identity explicit.
The issue specifications beside this directory record the threat model, rejected
shortcuts, test footprint, baseline failures, and remaining release work.

Do not apply these files directly to `vendor/`. The project's zero-fork doctrine
requires the corresponding upstream project to accept and release the behavior before
M.O.T changes its pin and performs the app-owned integration journey.
