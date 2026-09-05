# U31 — bridge-owned Chat/Agent turns

**Date:** 2026-09-05

**Owner:** GPT-5.6 Sol, implemented and reviewed directly

**Binding:** `CLAUDE.md`, `docs/DOCTRINE-PROACTIVE-BUILD.md`, and especially
“PROVE THE PREMISE, NOT THE PATCH.”

## Proven premise

Debi started a Direct Chat turn, switched to Hermes, completed a Hermes turn, then
returned to Chat. The original prompt, thought stream, and answer had disappeared.

That happens because the WebView response owns the producer. `setMode()` aborts it,
and Direct Chat persists the exchange only from the response generator's final path.
Odysseus history contains completed messages; it cannot reconnect to an active bridge
stream which has no independent owner.

## Authority and honest boundary

- The bridge process owns first-party Chat/Agent producer tasks and bounded replay.
- Odysseus remains the durable Chat/Agent transcript authority.
- Hermes remains the durable Hermes session authority.
- No second transcript database or catalog is introduced.
- A lane change, session change, view change, or WebView reload detaches one
  subscriber. It does not mean “Stop.”
- Explicit Stop cancels the bridge-owned producer.
- A bridge process crash/restart interrupts its network task. This slice does not
  claim generation can survive the process that owns it.
- Tool, approval, source, vision, prompt, image, and hidden-system payloads are not
  copied to a new on-disk journal.

The in-memory replay limit is 20,000 events or 8 MiB per turn. Terminal records are
retained for no more than the newest 500 and seven days while the same bridge process
continues to run. Overflow is a visible failed terminal state, never silent eviction.

## API and lifecycle

`bridge/core/turns.py` owns all task handles, state, sequence assignment, replay
buffers, subscriber notification, stop, and continuous pruning. It uses an
`asyncio.Condition`: subscribers wait on independent cursors and `notify_all`, so one
subscriber cannot consume another's wake-up.

`bridge/routers/turns.py` exposes:

- `POST /api/turns` — exact `chat|agent` lane, non-empty session/message, opaque
  request id; retrying the same `(request_id,lane,session)` is idempotent.
- `GET /api/turns/active?lane=&session=` — active discovery without localStorage.
- `GET /api/turns/{id}` — prompt-free metadata.
- `GET /api/turns/{id}/events?after=N` — committed replay plus live follow.
- `POST /api/turns/{id}/stop` — scoped, idempotent cancellation.

Only one turn may run per `(lane,session)`; other lanes and sessions remain
independent. Disconnecting an event response closes only that subscriber.

The historical `/api/chat/direct` and `/api/ody/chat` routes remain request-compatible.
This matters for LOffice Quick AI, which legitimately calls Direct Chat with an empty
session. Only the M.O.T panel uses `/api/turns` and therefore requires a session.

Direct Chat builds history first, then best-effort persists the user message before
waiting on the runner. If Odysseus is unavailable, Direct Chat still degrades as it did
before and cannot honestly claim durable transcript storage. Assistant text, reasoning,
metrics, image sidecar behavior, title generation, and final persistence keep their
existing owners.

## One renderer, live and replay

`bridge/panel/assets/turn-stream.js` is loaded before the main inline panel program.
Its `consume()` function is the only SSE grammar for both initial delivery and replay:

- text and thinking deltas;
- actual/model identity;
- Hermes session/status frames;
- approvals, questions, and expiry;
- tool starts, outputs, error cards, and Agent steps;
- produced-file and path-guard provenance;
- web sources and vision provenance;
- proxy and terminal errors.

The former inline parser is removed, not retained as a fallback. This extraction lowers
`index.html` by roughly 12 KiB instead of raising or gaming its byte ceiling.

Every local subscription has an identity. Its `catch`/`finally` may release controls
only if it still owns the current pane, so a detached old subscription cannot clear or
paint over a newer Hermes/Chat/Agent turn.

Session recovery snapshots the active turn before loading durable history, then checks
fresh metadata. If the turn completed during the history fetch, history is authoritative
and no duplicate assistant bubble is created. If it remains active, replay starts at the
committed sequence stream.

## Hostile controls and permanent evidence

The backend contract suite executes:

- disconnect after the first frame while the producer continues;
- two simultaneous subscribers receiving identical ordered frames;
- replay after a sequence cursor;
- idempotent retry and active-turn conflict;
- independent lane/session concurrency;
- scoped, idempotent Stop;
- malformed producer events and bounded overflow;
- continuous terminal pruning;
- proof that the store creates no disk artifacts.

The JavaScript suites execute the complete renderer grammar through the same
`consume()` entry point and retain all existing lifecycle/watchdog/card-addressing
assertions. Full repository gates and the real-stack switch-away/reload journeys remain
required before versioning or shipping.

## Release claim ceiling

Before real-stack acceptance, the only permitted claim is: focused in-memory
ownership, replay, event-grammar, and lane-isolation contracts pass. A version may call
U31 complete only after Direct Chat and Agent are each exercised mid-generation across
lane change and panel reload, explicit Stop is walked, LOffice Quick AI still works,
and a bridge restart is shown as an honest interruption.
