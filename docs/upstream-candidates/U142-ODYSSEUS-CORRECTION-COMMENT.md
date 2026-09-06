# Correction comment for Odysseus issue #6256

**Posted:** 2026-09-06 at
https://github.com/odysseus-dev/odysseus/issues/6256#issuecomment-5559273438

**Current boundary:** the public correction rejects the existing patch; it does not put
U142 into a wait-for-release state. A replacement upstream design must first establish
one ownership boundary shared by every endpoint writer. No M.O.T caller exists yet.

Correction to the implementation-evidence paragraph: the first candidate is rejected.
It fenced only selected generic HTTP routes, but endpoint mutation also occurs through
the agent `manage_endpoints` tool, Cookbook auto-registration, and subscription/provider
provisioners. A managed row therefore was not protected at one shared ownership boundary.

Review also corrected the URL premise. Provisioning must refuse to adopt an existing row,
but after a managed endpoint exists, another user may legitimately configure the same
service URL. Authority must stay bound to the exact managed endpoint ID plus management
token; URL equality is neither ownership nor authentication.

The issue's need for explicit ownership, compare-and-swap rotation, retry receipts, and
no implicit legacy adoption remains valid. I will not submit the current patch. A
replacement first needs one authorization boundary used by every endpoint create,
update, enable/disable, adoption, and delete path, with permanent bypass tests.
