# Correction comment for Odysseus issue #6255

**Posted:** 2026-09-06 at
https://github.com/odysseus-dev/odysseus/issues/6255#issuecomment-5559271598

**Current boundary:** the corrected candidate is evidence for discussing the API, not an
accepted upstream change. Do not offer its patch as a PR until maintainers agree on the
API direction. Shipped Direct history remains at-least-once meanwhile.

Correction to the implementation evidence I mentioned above: adversarial review found
four holes in the first candidate and its tests. It allowed assistant-first storage; its
response-loss test actually failed before the write rather than after commit; an
identical replay advanced the session's `updated_at`; and ownership was checked outside
the insertion transaction.

The isolated U139 candidate now rejects assistant-first insertion, tests a genuine
commit-before-response-loss replay, leaves replay counters/timestamps unchanged, and
locks then revalidates the authenticated owner inside the database transaction. It also
adds pair/partial concurrency and attachment-replay cases. The controlled sibling
comparison is now 5,909 passed / 7 failed / 4 skipped on untouched `934d23c0…`, versus
5,933 passed / the same 7 failed / the same 4 skipped with U139: all 24 added cases pass.
Seven high-risk race/response/owner cases also pass ten consecutive repetitions.

This supersedes—not validates—the earlier 5,927/10-failure statement, which mixed an
older candidate and a path-with-spaces environment. The API problem and expected
contract remain unchanged. I still will not offer a PR until the API direction is
accepted.
