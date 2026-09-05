# U106 — bridge-owned Hermes turns without a second transcript

**Date:** 2026-09-05  
**Status:** implementation candidate; not shipped or versioned.

## Proven premise

Debi sent a request in a M.O.T lane, switched lanes while it was generating, and found
the prompt, thought stream, and result gone on return. U31 fixed that ownership failure
for Chat/Agent only. Hermes still tied the upstream websocket relay to the browser
request, so switching lanes or reloading could end the relay.

## Authorities and claim boundary

- Hermes remains the durable session/transcript authority.
- The M.O.T bridge owns only the in-flight producer task, bounded reconnect frames,
  subscriber cursors, and Stop handle for a Hermes request it started.
- No disk journal and no second Hermes transcript are introduced.
- A lane change or browser reload detaches a subscriber; it does not mean Stop.
- Explicit Stop requests upstream cancellation and terminates the bridge relay.
- A bridge restart may reconnect to an upstream-active Hermes session and then repaint
  durable transcript/current state. It cannot honestly reconstruct every earlier
  ephemeral approval, tool-progress, file, or thinking card that Hermes did not store.
  The UI must state that boundary rather than fabricate those cards.

## Identity and reconnect

The client generates one request id before its first POST and reuses that exact body on
one pre-response network retry. The bridge indexes duplicates to the same turn. A new
session is accepted only when Hermes returns both a live gateway session id and a
durable stored session id.

If a saved live id is stale, the producer resumes from the stored id, requires the new
response to preserve both identities, and atomically rebinds all live-id aliases to the
same turn. Stop and recovery therefore cannot target the dead alias. On bridge restart,
the follower adopts only an upstream session Hermes reports as active; otherwise the
durable transcript is shown with an honest interrupted/finished state.

## Bounded delivery

Every subscriber has an independent sequence cursor and condition notification; one
subscriber cannot consume another's wake-up. Raw upstream websocket replay is redacted
to the display-safe event grammar before retention. Unknown fields, strings, lists,
nested objects, user-label metadata, projected restart state, per-session replay bytes,
active turns, finished turns, and total retained bytes all have explicit limits. The
frame budget is at most 64 MiB (8 active plus 8 recently finished turns at 4 MiB each);
each turn additionally permits at most 64 KiB of its user label and 512 KiB of
already-projected restart state. Overflow fails or truncates visibly; it never grows
without bound or silently drops the terminal state.

The external renderer is available before recovery runs. Hermes-only helpers are
required only in Hermes mode, so an asset mismatch cannot regress Chat/Agent. A missing
renderer/recovery API is a visible compatibility error, never an empty catch.

## Permanent evidence

- actual Hermes route: start, duplicate POST, disconnect, lane return, replay cursor;
- two simultaneous subscribers receive identical ordered frames;
- stale live id resumes by stored id and rebinds Stop/recovery aliases;
- missing live or stored identity fails closed;
- Stop works both before and after a restart-follow adoption and preserves guard audit;
- approval, clarification, source, file, tool, text, thinking, model, error, and terminal
  frames either replay truthfully or are named as non-reconstructable after bridge death;
- hostile nested payloads and many sessions stay below measured byte/turn limits;
- bridge restart while Hermes is upstream-active, plus inactive and unknown controls;
- browser journey: Hermes send -> Chat/Agent -> Hermes, then reload mid-turn.

## Release ceiling

Focused tests may claim only bounded in-memory detach/reconnect behavior. U106 closes
only after the real installed Hermes journey completes without duplicate submission,
the prompt and eventual answer survive lane switches, explicit Stop still works, and a
bridge restart displays the exact stated persistence boundary.
