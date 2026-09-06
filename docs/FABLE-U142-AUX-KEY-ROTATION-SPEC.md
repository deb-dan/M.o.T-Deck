# U142 — owner-aware auxiliary key rotation

**Date:** 2026-09-06
**Status:** first current-main ownership candidate rejected by adversarial writer-path
review; upstream contract remains open and M.O.T rotation remains blocked.

## Proven premise

Aux is an optional second runner. No selected Aux model, no listener and no Odysseus
task/utility binding is a valid steady state. Rotation must therefore be a no-op when
there is no explicitly M.O.T-managed binding; it must never select a model, start Aux,
or create/adopt an endpoint merely to make a release journey possible.

Odysseus currently stores user-created and integration-created model endpoints in the
same table. Its endpoint ID, display name, base URL, selected task model and API-key
fingerprint describe a row, but none proves who created or controls it. In particular,
POSTing the Aux URL is unsafe: Odysseus may deduplicate onto an existing empty-key row
and fill its key. That would silently adopt a user-owned endpoint.

## Required upstream ownership contract

Odysseus must provide a manager-scoped endpoint primitive before M.O.T rotates Aux:

1. M.O.T generates a high-entropy management token and sends it with a stable manager
   ID (`mot`) and resource ID (`aux`) during explicit Aux provisioning.
2. Initial managed creation is non-adopting. It fails if the requested normalized base
   URL already belongs to an unclaimed or differently managed row; it never deduplicates
   onto or fills that existing row. After creation, the manager's authority remains
   bound to the exact managed endpoint ID plus token—not to permanent global ownership of
   a URL that another user may legitimately configure later.
3. The manager/resource pair is unique. Retrying creation with the same token returns
   the original receipt; a different token conflicts. Odysseus stores only a token
   hash, while M.O.T stores the token in its protected local secret store.
4. Resolve and key-update operations require the token and return endpoint ID, base URL,
   current key fingerprint and a stable revision. Public names and URLs are not
   authentication factors.
5. Key update is compare-and-swap against the prior fingerprint/revision. An identical
   retry returns the committed receipt; a different current value conflicts. The API
   never returns either plaintext key.
6. An explicit operator-visible claim operation is required for installations that
   predate these fields. Automatic migration by name, URL, blank key, task selection,
   process state or “only matching row” is forbidden.

## M.O.T rotation transaction

For a positively managed, currently configured Aux binding:

1. Read and validate the protected current Aux key and management token without logging
   either value.
2. Resolve the managed endpoint through the token-authenticated upstream operation and
   require its manager/resource, endpoint ID, normalized URL and old key fingerprint to
   match M.O.T's durable receipt.
3. Record a non-secret rotation intent containing endpoint ID, revisions and old/new
   fingerprints. Generate and stage the new Aux key in protected storage without
   changing the live launch value.
4. Compare-and-swap Odysseus from the old key to the new key.
5. Atomically promote the staged local key. If Aux was already running, restart that
   exact M.O.T-owned process through launch provenance; if it was stopped, leave it
   stopped.
6. When Aux was running, verify a new-key request succeeds and an old-key request is
   rejected. When it was stopped, verify stored fingerprints and defer network proof
   visibly until the next explicit start; do not manufacture lifecycle state.
7. On any conclusive failure, compare-and-swap Odysseus back, restore the protected old
   key, and restore only the pre-existing running state. On an inconclusive response,
   resolve the committed revision before deciding roll-forward or rollback.
8. Clear the intent only after both stores and any required live verification agree.
   Restart recovery must resume the same transaction idempotently.

## Hostile counterexamples

- A user endpoint has the same `127.0.0.1:6768/v1` URL.
- A stale row is named “MOT Deck Aux” but has no valid manager token.
- Two rows share the URL under different users.
- The update commits but its response is lost.
- Another actor rotates the endpoint between resolve and update.
- Aux is intentionally stopped, has no selected model, or is mid-load.
- The bridge crashes after either secret store changes but before the other.
- The previous key remains accepted because an old Aux process survived.

Every one must fail closed or converge through the recorded transaction without
touching a user-owned endpoint or starting intentionally stopped work.

## Release boundary

Repository tests and an upstream patch do not close U142. Closure requires a released,
pinned Odysseus ownership primitive, M.O.T feature detection, an explicit legacy claim
journey where applicable, crash/response-loss tests, and a live rotation of an already
managed Aux binding. This installation currently has no Aux binding, so its release
acceptance is the exact no-op path; a live rotation must be walked on a deliberately
provisioned test binding without changing the user's optional state.

## Rejected current-main candidate

An isolated Odysseus-main patch attempted the upstream half without inferring any
legacy ownership. Managed endpoints carry a unique manager/resource claim, a domain-
separated management-token hash and monotonic revision. Provisioning refuses to adopt an
existing URL, resolve is token-authenticated, and key updates use revision plus a full,
domain-separated SHA-256 key fingerprint as compare-and-swap evidence. Generic endpoint
create/update/delete routes cannot bypass a managed claim. Identical lost-response retries
return the committed result; a different key or token conflicts without exposing either
secret.

That last claim was too narrow and is rejected. Odysseus has endpoint writers outside
the three generic HTTP routes: the agent-facing `manage_endpoints` tool can delete,
enable or disable a managed row by ID; Cookbook auto-registration can update a row found
by URL; and subscription/Copilot provisioners have their own create/update paths. The
candidate guarded only selected routes, so a managed row was not actually protected at
the ownership boundary. A separate regression also proved that an unmanaged row could
be PATCHed onto the managed URL; that does not by itself transfer token authority, but
it disproved the candidate's broader permanent-URL-exclusivity story and exposed the
partial nature of the guard.

The replacement must put mutation authorization at one shared database/service boundary
used by every writer, with an explicit capability for the managed API rather than route-
local conditionals. It must preserve ordinary user ability to configure a duplicate
service URL after the managed row exists, because endpoint identity and settings bind by
endpoint ID; URL spelling is neither ownership nor authentication. Every creation,
update, enable/disable, adoption and delete seam must be enumerated and tested before a
new candidate is described as owner-aware.

The current `dev` writer graph was re-enumerated at `934d23c0be29…`, not inferred from
the generic endpoint routes. `ModelEndpoint` is mutated by `routes/model_routes.py`,
Cookbook registration and watchdog cleanup, ChatGPT-subscription provisioning, Copilot
provisioning, chat-time cache refresh, and `src/agent_tools/admin_tools.py`. Those paths
write different field classes: credentials and lifecycle state, but also legitimate live
metadata such as `cached_models`. A blanket rule that rejects every write to a managed
row would therefore break ordinary discovery and health behavior.

The replacement boundary must be field- and actor-aware:

1. manager/resource claim, management-token hash, credential, credential fingerprint and
   management revision are protected fields;
2. the exact manager capability may rotate those fields through the managed API only;
3. an authenticated human owner keeps an explicit, separately specified administration
   path—management does not silently become ownership of all row behavior;
4. system probes may update an allow-listed set of non-secret observations such as model
   cache/refresh metadata, but cannot change claim, endpoint identity, URL, credential or
   enabled/deleted state; and
5. every direct ORM writer, flush, migration and bulk-update route must pass one mutation
   service or a database-level enforcement hook. Route checks alone are insufficient.

The adversarial test oracle must attempt the protected mutations through every writer
above while proving allowed cache refresh still works. It must also prove that a user can
create a distinct endpoint for the same URL without acquiring the manager capability.
The exact allowed-field matrix must be accepted upstream before another patch is written;
inventing it locally would be another partial policy disguised as an ownership boundary.

The rejected candidate tests cover exclusive creation, token non-storage, collision-resistant
fingerprints, wrong-token indistinguishability, generic-route bypasses, concurrent
provisioning, lost-response replay, rollback CAS and legacy SQLite migration/uniqueness.
They do not cover the complete writer graph above. The earlier 5,927-pass full Odysseus
comparison described in U139 therefore cannot rescue the invalid ownership premise.

M.O.T-side rotation is intentionally not added yet. Until the primitive is released and
pinned, a local caller would be dead code or would have to fall back to the unsafe URL/name
inference this issue forbids. This installation has no Aux binding; unset therefore remains
the correct no-op state, not a missing component to manufacture for QA.
The rejected candidate and its failing counterexample are preserved with U139 in
`docs/upstream-candidates/U139-U142-odysseus-idempotence-managed-endpoints.patch`.

Odysseus's issue-first and one-change-per-PR rules make the combined patch evidence, not
a submission unit. No matching managed-endpoint ownership/rotation issue or PR was found
in the upstream search. The separate report is now upstream issue
[#6256](https://github.com/odysseus-dev/odysseus/issues/6256), with the submitted text
preserved at `docs/upstream-candidates/U142-ODYSSEUS-ISSUE.md`. The issue's statement
that generic routes must not bypass a claim remains correct, but the posted
"implementation evidence" required a public correction because the first implementation
did not cover every writer. That correction is now public at
[#6256 comment 5559273438](https://github.com/odysseus-dev/odysseus/issues/6256#issuecomment-5559273438).
There is no maintainer response or API agreement yet. No code will be split or submitted
until the shared, field-aware authorization boundary survives this review.
