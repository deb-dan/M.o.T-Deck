# Unshipped upstream candidates

These patch files preserve reviewed work against exact upstream commits. They are not
vendored M.O.T changes, are not copied by `ship.sh`, and do not change the currently
installed application. This directory is evidence and handoff material, not a hidden
fork.

| Issues | Upstream baseline | Patch | Current boundary |
| --- | --- | --- | --- |
| U72 | Hermes `ee5b5ec21e576ccf9b941f9ff71330418415a5cb` | `U72-hermes-local-confinement.patch` | **Rejected forensic artifact:** a pre-existing hard link under an allowed root writes the same inode outside it. Do not submit or apply. |
| U139 | Odysseus `934d23c0be29c9721385f34565c0ae2cbd60da04` | `U139-odysseus-idempotent-direct-turn.patch` | **Verified upstream candidate, not accepted:** 24/24 focused cases plus the controlled full comparison pass; normal-context patch applies cleanly to the exact baseline; wait for maintainer agreement before offering a PR. |
| U139/U142 historical | Odysseus `934d23c0be29c9721385f34565c0ae2cbd60da04` | `U139-U142-odysseus-idempotence-managed-endpoints.patch` | **Mixed forensic artifact:** superseded U139 plus rejected U142. Do not submit or apply. |
| U144 | Goose `5e90925962f05acf8e255032de44d16c4a7768a2` | `U144-goose-provider-delete.patch` | **Rejected forensic artifact:** generated-looking secret names are not ownership, and its lock does not cover every config writer. Do not submit or apply. |

Submission preparation is also preserved here:

- U72 has an existing issue/PR, so `U72-HERMES-PR-COMMENT.md` records the submitted
  maintainer-direction request instead of a competing PR. That comment predates the
  adversarial hard-link finding; the correction was posted publicly on 2026-09-06. The
  rejected patch remains forensic-only, and Docker support upstream does not silently
  become native macOS confinement.
- U139 and U142 are now separate Odysseus issues #6255 and #6256. U139 has been isolated
  from rejected U142 and passes the exact sibling-worktree comparison. Both public
  evidence corrections were posted on 2026-09-06. U139 now waits for maintainer agreement
  on the API before any PR; U142 does not wait for a pin bump and instead needs a
  replacement design covering every endpoint writer.
- U144 has a human-submission issue draft because Goose explicitly requires the reporter
  to write the issue and reach **Ready** before code is submitted. The draft states the
  required behavior but no longer promotes the rejected implementation. Its rejected
  patch is not a release candidate; explicit secret provenance plus a shared mutation and
  recovery boundary must be designed before upstream submission.

The original artifacts were generated with `git diff --binary --full-index --unified=0`.
A 2026-09-06 rehydration audit found that the three zero-context files do not apply with
ordinary `git apply --check` even though their surviving isolated worktree diffs do apply
cleanly to the exact recorded HEADs. U72 remains untouched as rejected forensic evidence;
any future viable candidate must be regenerated with normal context and rechecked before
submission. Reproducibility is part of the candidate, not clerical polish.

Normal-context patch syntax represents an unchanged blank source line as one literal
context-marker space. `.gitattributes` therefore disables only Git's plain-file
`blank-at-eol` diagnostic for patch artifacts in this directory; otherwise
`git diff --check` reports valid patch grammar as whitespace damage. This is not the
source-code check. Every viable patch must still pass
`git apply --whitespace=error-all --check <patch>` from its exact recorded upstream base,
which validates the whitespace in the code the patch would actually add.
The issue specifications beside this directory record the threat model, rejected
shortcuts, test footprint, baseline failures, and remaining release work.

The evidence is deliberately not summarized as “baseline-equivalent, therefore green.”
U72's exact ten macOS failures and seven opposite-platform skips, U139's final controlled
seven baseline failures and four optional/platform skips, U139/U142's historical
ten-failure mixed run, and U144's historical
Goose-supported **495/495** provider lane are enumerated in their issue specifications.
Those classifications prove attribution only; they do not validate the rejected
predicates or replace the required post-correction runs.

Do not apply these files directly to `vendor/`. The project's zero-fork doctrine
requires the corresponding upstream project to accept and release the behavior before
M.O.T changes its pin and performs the app-owned integration journey.
