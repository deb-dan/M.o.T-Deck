# U79 — Aider contract must test parser behavior, not stale help prose

Decision-complete one-file contract correction.

The optional contract remains checkout-local: it inspects only
`data/aider-venv/bin/aider` beneath this repository. It must not fall back to the
installed snapshot, a global executable, or the archived Claude project. If the
repo-local executable is absent or unrunnable, the same four optional upstream tests
skip explicitly; the pin-format test still runs.

Replace only `test_edit_format_whole_is_still_offered`'s stale `"whole" in HELP`
predicate. Run the real parser twice with the repo-local executable:

1. `[BIN, "--edit-format", "whole", "--help"]` must exit 0 and return usage text;
2. `[BIN, "--edit-format", "__harness_invalid_format__", "--help"]` must exit nonzero
   and name the rejected sentinel in its output.

The invalid control is required: without it, a parser that silently ignores the option
would make the valid probe meaningless. Keep the timeout bounded and report subprocess
exceptions as an assertion failure for an installed/runnable binary, not as a silent
pass. Do not replace the other help predicates; they assert actual flag spellings and
remain valid. Do not install Aider into this checkout merely to remove skips.

Permanent verification:

- run `bridge/contract_tests/test_aider_contract.py` in the ordinary checkout and
  account for the exact pass/skip count;
- independently execute the corrected test file with `ROOT` rebound or from a temporary
  mirrored test root whose `data/aider-venv/bin/aider` is a tiny executable parser
  fixture, proving both the valid and invalid branches run rather than skip;
- prove an absent fixture produces the documented four skips plus the pin test;
- run `scripts/verify.sh` and `git diff --check`.

The builder is bound by `CLAUDE.md` and `docs/DOCTRINE-PROACTIVE-BUILD.md`. No install,
snapshot/live-state/process/port/vendor/archive mutation; no VERSION/docs/commit/push or
ship. Sol owns independent QA and ledger/release closure.
