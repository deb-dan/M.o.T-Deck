# DRAFT — STATE-ISOLATION SPEC for SPLIT CHAT (two chat columns)

> **STATUS: PLANNING DRAFT, NOT A BUILD SPEC. NO CODE WAS WRITTEN.**
> Authored by the Opus-5 planning lane on 2026-08-14 at Fable's request, to be
> reviewed/edited by **Fable 5** before any build. `FABLE-SPLITSCREEN-SPEC.md`
> §Phase 3 (lines 56-62) explicitly gates this work: *"Blocked on refactoring the
> chat singletons … Needs a Fable-authored state-isolation spec first. Anyone
> building this ahead of that spec is wrong."* This document is the **input** to
> that spec, not the spec itself: every judgement call is listed in §5 for Fable
> rather than decided here.
>
> Everything below was derived by reading `bridge/panel/index.html` (8 957 lines),
> `bridge/app.py`'s Hermes relay, `bridge/voice.py`'s render lock,
> `scripts/start_component.sh`'s runner argv, and `app/main.swift`'s webview
> hosting. Line numbers are as of the working tree on 2026-08-14 (with the
> uncommitted turn-lifecycle + clarify-card slices in place) and will drift.

---

## 0. The ask, restated precisely

Two chat **columns** inside `#view-chat`, LM-Studio style — each with its own lane
chips, its own session, its own stream. Split *tabs* (Phase 1/2) already shipped
in the shell; this is the panel-internal split, which is a different problem
entirely: Phase 1 moved **views** between panes, and every view was already a
singleton. Phase 3 needs the **same view twice**, and the chat view is the single
most stateful surface in MOT Deck.

The blunt summary of the finding: **the chat pane is not a component, it is the
document.** 13 module-level mutable globals, ~35 hard DOM ids, 8 localStorage
keys, and three separate side-effect machines (turn lifecycle, voice conv loop,
artifact viewer) all assume exactly one of everything. None of that is a mistake
— it was correct for one pane, and every one of those singletons is *load-bearing*
for a fix that already shipped (the 2026-08-14 wedge, the 2026-08-14b interrupt
regression, the feedback-loop gate). The refactor must therefore preserve each
fix's *invariant*, not just its code.

---

## 1. INVENTORY — what breaks with two instances

### 1.1 Module-level mutable globals (panel JS)

| Name | Kind | Declared | Read/written by | Collision consequence with two columns |
|---|---|---|---|---|
| `chatSid` | Odysseus session id | :1608 (21 refs) | `sendChat`, `selectSession`, `doMsgDelete`, `msgEdit`, `msgFork`, `stampLiveTurn`, `dropSidecarAttachment` | **Fatal.** Both columns address one session; turn B's persist/edit/delete/fork lands in A's transcript. Also breaks `stampLiveTurn`'s matching (see §6.2). |
| `hermesSid` | live gateway sid | :1612 (12) | `sendChat`, `hermesStop`, `approveHermes`, `answerHermes`, `doDelete` | **Fatal + security-adjacent.** An approval card rendered in column B posts `{session_id: hermesSid}` — the *global* — so a "Once" click can approve a dangerous shell command in the OTHER column's session. See §6.1. |
| `hermesStoredSid` | durable Hermes id | :1616 (13) | rail selection, `sendChat` body, `doDelete` | Rail highlights the wrong row; `selectHermesSession`'s same-session no-op guard (:4829) mis-fires across columns. |
| `chatMode` | lane | :1608 (39) | ~everything: `sendChat` url/body, `addMsg` lane stamp, `renderSessions`, `loadSessions`, `applyVisionUi`, both lane guards, `msgActs` | **Fatal.** The lane guards added by the 2026-08-14b regression fix (`if (chatMode !== 'hermes') return;`) become cross-column: column A in Agent mode makes column B's Hermes rail click a silent no-op. |
| `chatBusy` | one-turn flag | :1608 (23) | `sendChat` (entry + finally), all 4 escape hatches, `convSend`, `initChat`, `msgFork` | **Fatal.** A turn in A blocks Send in B; `initChat`'s `if (chatBusy) return` (:2977) makes entering the view skip B's setup while A streams. |
| `curTurn` | turn record | :7580 (15) | `turnArm`, `forceEndTurn`, `turnHardRelease`, `stopTurnNow`, `hermesStop`, `sendChat` | **Fatal.** Starting a turn in B overwrites A's `curTurn`; A's watchdog then bails via `if (curTurn !== t) return` (:7596) and A can never be force-ended → the exact wedge class the lifecycle slice was built to kill. |
| `chatModel` | display label | :1608 (5) | `addMsg`'s `who`, `model_info` handler | Cosmetic but confusing: B's model name labels A's bubbles. |
| `chatSessions` / `hermesSessions` | rail data | :2925 / :1617 | `renderSessions`, `beginRename`, `duplicateSession`, `doDelete` | One rail, two selections — needs a decision (§5.1), not just isolation. |
| `sessionsReqSeq` | race token | :1623 | both rail loaders | Two columns loading rails concurrently make each other's response "stale" → rails render empty intermittently. A *shared* monotonic token is precisely wrong for two independent loaders. |
| `convSt`, `convGraceTimer`, `convWrap` | conv state machine | :4576-4578 | `convEvent`, `convSend`, `convSpeak`, `convTurnEnd`, `stopConv` | Conv is inherently single-instance (§3). Must be *owned* by one column, not duplicated. |
| `autoVad` | live mic session | :4016 (26) | `startAuto`, `autoFrame`, `autoDrain`, `stopAuto`, `renderAutoBtn/ConvBtn` | ONE mic exists. Two columns must not each hold a capture graph. |
| `currentAudio` | the one playing clip | :3619 (13) | `msgSpeak`, `stopSpeaking`, `ensureSpeakBtn`, `speakFlash` | One-clip-app-wide is a deliberate rule; keep it global but make `ensureSpeakBtn`'s re-adopt (`currentAudio.wrap === wrap`) column-safe. |
| `talkRec` | manual dictation | :3740 (15) | `startTalk`/`stopTalk`/`finishTalk`, exclusivity checks | Same mic. `appendTranscript` writes to *the* composer — must target the column that started it. |
| `attachedImage`, `liveVision` | attach state | :3003 | `sendChat`, `applyVisionUi`, drop/paste handlers, `motdeckNativeDrop` | An image staged in A is consumed by whichever column sends first. `liveVision` is genuinely global (a runner property). |
| `pendingAttachDrop` | live-✕ intent | :7211 | `sendChat` finally, `liveAttachDrop` | Wrong column's sidecar row deleted. |
| `_delArm`, `_msgDelArm` | 2-step confirm | :4981 / :7020 | rail ✕, message delete | A single armed button across columns; arming in B disarms A. Low severity, real. |
| `_stampSessionModel` | header memo | :2947 | `stampFor`, `refresh()` :1246 | Header of both columns shows one model. |
| `artifactState`, `_artContent/_artKind/_artFilename`, `_canvas`, `artPinned`, `_artFrac` | artifact viewer | :8463-8530, :1818 | `openArtifact`, `renderArtifact`, canvas editor | One viewer, two producers. Needs a decision (§5.3): shared viewer, or per-column. |
| `dlSeenDone`, `modelEntries`, `modelLiveId`, `voiceCfg`, `capsSnap` | shared read-caches | various | model/audio popovers, caps strip | Genuinely global (machine state). Safe to share; only their *renderers* are per-column. |

### 1.2 DOM-id dependencies (the hard part)

Every one of these is a bare `document.getElementById(...)` / CSS `#id` and would
become a duplicate-id document with two columns. HTML duplicate ids do not throw
— `getElementById` silently returns **the first match in document order**, i.e.
column A. That is the worst possible failure mode: silent, correct-looking, and
always wrong for the right-hand column.

**Structural:** `view-chat`, `chat-body`, `chat-sessions`, `cs-list`, `cs-new`,
`cs-collapse`, `cs-resize`, `chat-main`, `chat-scroll`, `chat-msgs`, `chat-bar`.
**Composer:** `chat-input`, `chat-send`, `chat-attach`, `chat-file`,
`chat-attachstrip`, `chat-inputrow`, `chat-talk`, `chat-auto`, `chat-conv`.
**Chips/header:** `chat-modes`, `mode-agent`, `mode-chat`, `mode-hermes`,
`mode-browse`, `mode-tools`, `chat-model-btn`, `chat-audio-btn`, `cap-vision`,
`chat-note`, `caps-strip`, `chat-stamp`, `chat-head-compact`, `chat-compact-info`.
**Popovers/overlays:** `model-pop`, `audio-pop`, `imglightbox`.
**Artifact:** `artifact-viewer`, `art-divider`, `art-body`, `art-title`,
`art-kind`, `art-copy/pin/edit/expand/close`, `art-canvas*`, `art-editor`,
`art-console*`.
**Transient:** `thinking` — created per turn as `think.id = 'thinking'` (:7732)
and removed by id in `turnHardRelease` (:7624). **Two live turns create two
elements with the same id and the hard-release removes the wrong one.**

Also global-selector reaches that cross column boundaries:
- `refreshSpeakChips()` :3728 — `document.querySelectorAll('#chat-msgs > .cmsg:not(.user)')`
- `sendChat`'s finally and `turnHardRelease` — `getElementById('chat-send')`
- `appendTranscript` / `convSend` / `growInput` default — `getElementById('chat-input')`
- `scrollChat` — `getElementById('chat-scroll')`
- `showView`'s chat-mode class toggle + `body.chat-mode`-scoped CSS

**CSS cost, measured:** the `<style>` block contains **87 occurrences of
`#chat-*` / `#cs-*` / `#mode-*` / `#art*` / `#model-pop` / `#audio-pop` id
selectors** across ~35 distinct ids, out of ~495 total rule braces. The tracked
"CSS balance 500/500, zero new rules" invariant survives a *selector rewrite*
(rule count unchanged) but not silently — see §5.5 for the specificity hazard.

### 1.3 localStorage keys (all single-valued)

`motdeck-chat-sid`, `motdeck-hermes-sid`, `motdeck-hermes-stored`,
`motdeck-chat-rail`, `motdeck-sessions-rail`, `motdeck-sessions-width`,
`motdeck-artifact-split`, `motdeck-canvas-split`.

The first three are **per-column state stored in a global key**. Two columns
reading `motdeck-chat-sid` at boot both restore the same session — which violates
the invariant in §4.3 *before the user has clicked anything*. Layout keys
(rail/width/splits) are legitimately shared; a per-column artifact split is a
Fable decision (§5.3).

### 1.4 Server-side / bridge singletons (the ones no panel refactor can fix)

| Seam | Where | Behaviour with two concurrent turns |
|---|---|---|
| `_HermesWS._queues` keyed by `session_id` | `bridge/app.py:4042`, `open_queue` :4129 | Two turns on **different** sids fan out correctly (this is the good news). Two turns on the **same** sid: `open_queue` **overwrites the dict entry**, so the first turn's queue is orphaned and that turn goes deaf until the 600 s hard guard. Since `hermesSid` is one localStorage key today, "same sid" is the *default* state of two columns. |
| `POST /api/hermes/stop` / `approve` / `answer` | :4334/:4362/:4393 | Addressed by `session_id`. Approvals carry **no request id on the wire** (gateway FIFO, per-session) — safe only if the two columns hold genuinely distinct sessions. |
| Runner `--parallel 1` | `scripts/start_component.sh:98` | **llama-server serves one slot.** Two simultaneous generations *serialize*: column B's first token waits for column A to finish. Raising `--parallel` splits the KV cache (halves usable ctx per slot) — a real trade-off, and a Fable decision (§5.6). |
| Odysseus in-process `_LOCAL_MODEL_LOCK` + aux calls | vendored | Two Agent-lane turns serialize inside Odysseus, on top of the runner slot. |
| `voice._RENDER_LOCK` (global, non-blocking) | `bridge/voice.py:1203`, `VoiceBusy`→409 | Two ▶ speak clicks → the second gets **409 "a render is already in progress"**. Also `/api/voice/stt` shares this lock, so a conv-mode STT call and a speak render still contend. |
| `data/thinking.db` / `attachments.db` sidecars | keyed by `(sid, user_key=hash(text))` | Two columns in one session sending the same text (e.g. "test") rehydrate each other's thinking/image. Fixed only by the never-share-a-session invariant. |

**Consequence for the spec:** split chat is a **UI** feature, not a throughput
feature. Two columns give you two conversations you can *watch*, not two models
generating at once. That must be said in the UI copy, or the first thing Debi
reports is "the right column is frozen."

---

## 2. ARCHITECTURE OPTIONS — honest evaluation

### (a) Parameterised in-document component — `ChatPane` instances

One `ChatPane(paneId, rootEl)` factory holding a state object; every current
global becomes a field; every `getElementById('chat-x')` becomes
`pane.$('.chat-x')` (element-scoped `querySelector` on the pane's root subtree);
CSS id selectors become class selectors so both subtrees are styled by the same
rules; the markup is cloned from a `<template>`.

**Pros.** One document, one JS context → the genuinely-global rules (§3) stay
enforceable *by construction*: one `autoVad`, one `currentAudio`, one mic
teardown path, one `convSt` — exactly the invariants three separate shipped fixes
depend on. Debugging stays possible (one console, one `feed()`, one activity
log). No new IPC, no new origin, no new webview. The existing js test harness
(functions extracted from the panel by name and run under `node`) keeps working,
and the pure functions (`convStep`, `vadStep`, `statsLine`, `artifactKind`,
`stripAttachMarker`) need **no change at all** — they were already written pure.
The diff is large but *mechanical and greppable*, which is the kind of diff this
codebase's test style (wiring greps + decision tables) is actually good at
pinning.

**Cons / risk.** The biggest single-file diff in the project's history: ~13
globals, ~35 ids, ~87 CSS selectors, ~40 functions rethreaded. Specificity
changes when `#id` → `.class` (1,0,0 → 0,1,0) can silently alter the cascade —
the one place where "mechanical" stops being safe (§5.5). And any function missed
in the rethread fails *silently* on column B via first-match `getElementById`.

**Migration risk: HIGH but BOUNDED and TESTABLE.** Crucially it can be de-risked
by shipping the refactor with **exactly one instance first** (Phase 1 below):
behaviour must be byte-identical, all 15 js + 23 py suites green, and only then
is a second instance created. That converts one terrifying change into two
reviewable ones.

### (b) One `<iframe>` per column (same origin, `/`?)

**Pros.** True state isolation for free — separate JS contexts, separate `window`,
duplicate ids become legal, zero refactor of the chat code.

**Cons.** Same-origin iframes share `localStorage` (so §1.3 collides anyway
unless keys are namespaced *through* the parent), and everything that must stay
single-instance now needs a coordination protocol: one mic, one clip, one conv
machine, one artifact viewer, one activity feed, one ⌘K palette, one
`/api/status` poller. You would be *building* the cross-frame bus that option (a)
gets for nothing. Two frames also load the panel twice: two `/api/status` +
`/api/models` + `/api/voice/config` polling loops, two copies of the artifact
vendor bundle, two `refresh()` timers. The panel is one 9 k-line document with an
inline `<style>` and two inline `<script>` blocks — it is not built to be embedded
in itself. Add the WKWebView-specific footguns already documented in this repo
(drag events, file pickers, mic permission, `about:srcdoc` base resolution) and
each of them now has a frame boundary in the middle of it.

**Migration risk: LOW to write, HIGH to operate.** Rejected as the primary path;
worth recording as the escape hatch if (a) proves intractable.

### (c) Two panel instances via the SHELL (second `WKWebView` on `?pane=chat`)

The shell already hosts two panes and can reparent webviews
(`app/main.swift`: `tabTitles` :23, `panelWV` :367, `buildPane` :699).

**Pros.** Almost no panel refactor: `?pane=chat` could hide the rail/nav and show
only the chat column. Real process-level isolation. Reuses shipped, Mac-verified
pane machinery.

**Cons — and one is fatal.** No custom `websiteDataStore` is set anywhere in
`main.swift`, so both webviews use the **default persistent store and therefore
share `localStorage`**: both instances restore `motdeck-chat-sid` and fight over
the same session (namespacing by pane param is possible but must then be threaded
through all 8 keys). Worse, the two documents cannot coordinate the
single-instance rules at all: **two independent `getUserMedia` capture graphs on
one mic**, two `currentAudio` clips playing over each other, two conv loops each
gating only its own VAD — i.e. the feedback-loop invariant that the entire conv
design rests on ("the mic must never hear the assistant") becomes *unenforceable*,
because column A's speaker output is column B's microphone input and B knows
nothing about it. Add: `DropOverlay` is panel-pane-specific, the activity feed and
Mission Control would double, and every cross-column feature (drag a message
across, "compare these two replies") needs a bridge round-trip. Also note the
current pane model is *one webview per pane, borrowed* — two instances of the
*same* URL is a new concept for that code, not a configuration of it.

**Migration risk: LOW upfront, UNACCEPTABLE for voice.** Only viable if split
chat ships with voice disabled in split mode — which throws away MOT Deck's
most distinctive feature to gain a layout.

### RECOMMENDATION

**Option (a), staged, with one instance shipped before the second exists.**

It is the only option under which the three shipped invariants that matter most
— one mic / one clip / one conv machine, panel-owns-the-end-of-its-turn, and
never-interrupt-a-healthy-turn — remain enforceable in code rather than by
convention across a boundary. (b) and (c) both buy an easy first commit by moving
the hard problem into a coordination layer that does not exist yet.

---

## 3. WHAT STAYS GLOBAL BY DESIGN (not a compromise — a requirement)

These must be *singletons owned by the document*, with an explicit **owner
column** where one is needed. Fable should treat "is this global?" as answered
here and only rule on the ownership UX.

1. **The microphone.** One `autoVad`. `startAuto(mode)` gains an owner (`pane`);
   starting capture in column B while A holds it must **stop A's** (with a visible
   reason) or refuse — never run two graphs. `stopAuto` stays the ONE teardown.
2. **Conversation mode.** One `convSt`/`convGraceTimer`/`convWrap`, bound to one
   owner column. The feedback gate (`convGated`, fail-closed) is unchanged; what
   changes is that `convSend`/`convSpeak`/`convTurnEnd` must target the owner's
   composer/holder, and `convTurnEnd` must fire **only for the owner's turn** (see
   §4.3 invariant I5). Switching lanes/sessions in the *other* column must not
   touch the conv loop.
3. **One playing clip app-wide** (`currentAudio`). Keep the rule verbatim.
   `ensureSpeakBtn`'s re-adopt already keys on `currentAudio.wrap === wrap`, which
   is node identity and therefore already column-correct — verify, don't rewrite.
4. **Manual dictation** (`talkRec`) — same mic, same exclusivity, owner-scoped
   `appendTranscript` target.
5. **Voice defaults / `voiceCfg` / `liveVision` / `modelEntries` / `capsSnap`** —
   machine state, one copy, many renderers.
6. **The activity feed, `feed()`, `esc()`/`escAttr()`, `showView`, ⌘K palette,
   `refresh()` polling, theme.** Pure or app-level; unchanged.
7. **The image lightbox** (`#imglightbox`) — a modal overlay; one is correct.
8. **The artifact viewer** — *probably* one (§5.3), but if shared it needs an
   owner label so column B's "⧉ Open" does not silently replace column A's pinned
   artifact.

---

## 4. PHASED BUILD PLAN

Each phase ends green on the full sweep (23 py + 15 js suites, contract, CSS
balance, `ast.parse`, `node --check` on both panel script blocks) and is
independently Mac-verifiable via `./scripts/ship.sh`.

### Phase 0 — mechanical de-globalisation of DOM access (no behaviour change)
Introduce `ChatPane` as a *thin* accessor object with a `root` and `$()`, create
exactly ONE instance wrapping today's `#view-chat`, convert every chat-subtree
`getElementById` to `pane.$('.x')`, convert the 87 CSS id selectors to classes
(elements keep both a unique id and the class), remove the transient `#thinking`
id in favour of a class + a per-turn node reference.
**Tests.** New `test_chat_pane_scope.js`: (a) grep-assert **zero**
`getElementById('chat-…'|'cs-…'|'mode-…'|'art…')` remain in the chat code path;
(b) grep-assert zero `#chat-`/`#cs-`/`#mode-`/`#art` id selectors remain in
`<style>`; (c) CSS rule count unchanged (500/500); (d) every existing js suite
unchanged and green. **Verify:** the panel is indistinguishable from today.

### Phase 1 — state object (still ONE instance)
Move the §1.1 per-column globals into `pane.state` (`sid`, `hermesSid`,
`hermesStoredSid`, `mode`, `busy`, `model`, `curTurn`, `sessions`, `reqSeq`,
`attachedImage`, `pendingAttachDrop`, `delArm`, `msgDelArm`). `sendChat`,
`setMode`, `initChat`, `loadSessions`, `renderSessions`, `select*Session`,
`newSession`, `duplicateSession`, `beginRename`, `doDelete`, `addMsg`, `msgActs`,
`stampLiveTurn`, `msgEdit/Delete/Fork`, the turn-lifecycle block and the
approval/ask handlers all take `pane` (or read it off the holder node).
Compatibility shims (`let chatSid` → getter onto pane 0) are **forbidden**: a
shim is exactly how a missed call site stays silently wrong.
**Tests.** `test_turn_lifecycle.js` extended: every assertion re-expressed
against `pane.state`; new assertions that `forceEndTurn`/`turnHardRelease` touch
**only** their own pane's composer, and that `approveHermes`/`answerHermes` read
the session id **off the card's pane**, never a module global (§6.1).

### Phase 2 — second instance, layout only, one lane
Clone the template into a second column behind a `⫽` chat-split toggle
(persist `motdeck-chat-split`). **Agent/Chat lanes only; Hermes disabled in the
second column** (§5.4). Enforce distinct sessions at creation: column B always
opens a **new** session (never restores `motdeck-chat-sid`), and per-column
storage keys become `motdeck-chat-sid.<pane>`.
**Tests.** New `test_chat_split.js`: two-pane construction produces two distinct
roots; the invariants in §4.3 as greps/decision tables; per-column storage key
scheme; `motdeck-chat-sid` (unsuffixed) is no longer read by the chat code.

### Phase 3 — Hermes lane in both columns
Only after the bridge side is settled: a *distinct* `hermesSid` per column
(column B calls `session.create`), and `_HermesWS.open_queue` hardened to
**refuse or fan out** rather than silently overwrite an existing queue for a sid
(§6.3). Approvals/asks addressed per pane.
**Tests.** Python: `open_queue` on an already-open sid does not orphan the first
queue (unit test with two queues + a fake event). Contract: unchanged RPC names.
`test_hermes_sse_map.py` unchanged (the mapper is pure and per-stream).

### Phase 4 — voice + artifact ownership
Owner-column semantics for mic/conv (§3), owner label on the artifact viewer,
and the honest UI copy about runner serialization (§1.4).
**Tests.** `test_conv_mode.js` extended: conv actions target the OWNER pane's
composer; a turn ending in the NON-owner pane fires **no** `turn_end`; starting
capture in B while A owns it produces exactly one live `autoVad`.

### 4.3 INVARIANTS TO PIN (these are the spec's teeth)

- **I1 — No shared session.** Two columns never hold the same `sid`, and never the
  same `hermesSid`. Enforced at creation (B always mints), asserted on every
  select (a click that would duplicate the other column's session is refused with
  a visible reason, not silently allowed).
- **I2 — A turn stamps only its own column.** `stampLiveTurn`, `chatStatus`,
  `chatInspect`, `chatSummary`, `expireApprovals`, `fileCard`, `guard_flag` all
  write through the turn's `holder` node (already true) *and* the holder's pane —
  never `document.getElementById`.
- **I3 — A force-end releases only its own composer.** `forceEndTurn` /
  `turnHardRelease` touch `pane.$('.chat-send')` and the turn's own thinking node.
  Asserted by index (the existing test style), because "present" is not enough.
- **I4 — An approval/ask answers its own session.** The card carries the pane (and
  therefore the sid) it was created for; the POST body's `session_id` comes from
  the card, never a global. **Security-relevant — see §6.1.**
- **I5 — Exactly one mic, one clip, one conv machine.** At most one live
  `autoVad`; `convTurnEnd` fires only for the owner pane's turn; every conv exit
  still funnels through the single `stopConv`/`stopAuto`.
- **I6 — Nothing may auto-answer or auto-send on the user's behalf.** The existing
  negative tests (no `sendChat`/`convSend`/`setTimeout` in the ask path) must
  still hold per column.
- **I7 — Re-entering the view never touches a live turn** (the 2026-08-14b fix)
  — and now: never touches the *other* column's live turn either.
- **I8 — One rail selection per column** (or one shared rail with two
  highlights — §5.1), and a rail load in one column can never invalidate the
  other's (per-pane `reqSeq`, not a shared counter).

---

## 5. OPEN FABLE DECISIONS

1. **Session rail topology.** One shared rail with two active-row highlights (and
   a click target ambiguity: which column does a click open?), or one rail per
   column (doubles the horizontal cost in a pane that is already ~420 px min)?
   Recommend: **one shared rail, click opens the FOCUSED column**, with focus
   modelled the way the shell's pane focus already is (gold marker).
2. **Lane chips per column or one lane for both?** Per-column is the literal ask
   and the honest answer, but it means the `mode-*` chips (and `chat-note`,
   `caps-strip`, model chip, audio chip) duplicate — a visibly busier composer.
3. **Artifact viewer: shared, per-column, or split-suppressed?** Three columns of
   content in one window at 900 px min width is probably untenable; recommend
   **shared viewer with an owner label**, or artifacts suppressed while chat-split
   is on.
4. **Hermes lane in the second column: v1 or v2?** It is the lane with a
   server-side singleton hazard (§6.3) and the only lane with approvals. Recommend
   **deferring to Phase 3** and disabling it in column B for v1.
5. **CSS: id→class conversion and specificity.** ~87 selectors change from
   (1,0,0) to (0,1,0). Options: plain class (cleanest, needs a one-pass cascade
   audit), doubled class `.chat-input.chat-input` (restores some weight, ugly), or
   `[id^=…]` attribute selectors (preserves nothing useful). Recommend **plain
   class + a documented audit pass + a grep test forbidding chat id selectors from
   returning.**
6. **Runner `--parallel`.** Leave at 1 and *tell the truth in the UI* ("the other
   column is waiting for the runner"), or raise it and halve per-slot context?
   Recommend **leave at 1 + honest copy**; a context regression would be a far
   worse surprise than a queue.
7. **Focus model.** Which column receives a ⌘K "open chat", a dictated
   transcript, a rail click, `motdeckNativeDrop`? Recommend mirroring the shell's
   Phase-2 focus model exactly (click sets focus, gold marker, strip routes to
   focused) so there is ONE focus idiom in the product.
8. **Split persistence.** Does chat-split restore on relaunch, and do both
   columns restore their sessions? (The shell's v2 verdict was "reopening onto the
   remembered tab made the pane feel stuck" — the same argument may apply.)
9. **Voice in split mode.** Conv mode owned by the focused column, owned by an
   explicitly-pinned column, or disabled while split? Recommend **owned by the
   column that started it, with the chip visible only there.**
10. **Is `⫽` chat-split reachable inside a shell pane?** Two chat columns inside a
    420 px shell pane is unusable — should chat-split be refused (or auto-collapse)
    when the panel is in a split *pane*? The panel currently cannot see that.

---

## 6. THE NASTIEST COUPLINGS (adversarial pass)

### 6.1 An approval card answers whatever session the GLOBAL last pointed at
`approveHermes` (:7382) and `answerHermes` (:7505) both send
`{session_id: hermesSid}` — the module global — while the card itself carries only
`_rid` (and approvals carry *no* request id at all, resolved FIFO per session
gateway-side). With two columns, `hermesSid` is whichever column most recently
wrote it (a send, a `hermes_session` frame, a rail select, a resume). A user
clicking **"Always"** on a card in column B can therefore grant a persistent
approval rule for a dangerous shell command in column A's session, and the panel
would show a cheerful `✓ approved · always`. This is the one coupling in the
inventory with a security consequence rather than a cosmetic one, and it is
invisible in code review because the line reads correctly today. **I4 exists for
this.**

### 6.2 `stampLiveTurn` maps DOM to history by CONTENT, newest-first
`stampLiveTurn` (:7117-7143) refetches `/api/ody/history/{chatSid}` and finds the
**last** row whose marker-normalised content equals the DOM node's text. Two
columns in one session both sending `"test"` — the single most likely thing to
happen during the very first manual test of this feature — will map to the *same*
history row, so both columns stamp the same `_db_id`. Then `delete` in column B
removes column A's message server-side, `edit` rewrites it, and `fork` forks from
it. The same content-hash assumption is baked into the bridge's sidecars
(`thinking.db`, `attachments.db` keyed by `(sid, user_key)`), so the wrong
thinking disclosure and the wrong image can rehydrate too. There is no defence
inside the matcher — the *only* defence is invariant I1 (never share a session),
which is why I1 must be enforced at session creation and not left to the user's
good behaviour.

### 6.3 `_HermesWS.open_queue` silently overwrites — one turn goes deaf
`bridge/app.py:4129`: `self._queues[sid] = q`. The fan-out map is keyed by session
id, which is genuinely good design for concurrency — but the setter has no
occupancy check. Two columns starting Hermes turns on the same sid (the default,
since `motdeck-hermes-sid` is one key) means the second `open_queue` orphans the
first queue: the first turn's relay then waits on a queue nobody feeds, emits its
20 s `hermes_ping` heartbeats forever (so the panel's stall watchdog is *correctly*
reassured that the relay is alive), and only the **600 s hard guard** ends it. The
symptom is a turn that streams nothing for ten minutes while the UI insists
everything is fine — which is exactly the wedge signature Debi already reported
once, arriving by a completely different route. Bonus: `close_queue` in the
finally of the *second* turn deletes the key the *first* turn believes it owns.

### Honourable mentions
- **`#thinking` by id.** `turnHardRelease` (:7624) removes the first `#thinking`
  in the document — column A's — while trying to clean up column B.
- **Shared `sessionsReqSeq`.** A monotonic "drop stale responses" token shared by
  two independent loaders makes each column's load cancel the other's; rails blink
  empty and the bug is timing-dependent, i.e. unreproducible on demand.
- **`initChat`'s `if (chatBusy) return`.** Written to protect a live turn from a
  view re-entry (correct); with two columns it means a stream in A prevents B from
  ever initialising — a dead second column that recovers only after A finishes.
- **`refreshSpeakChips`'s document-wide selector.** Rebuilds `.msg-acts` on every
  assistant row in *both* columns whenever the TTS default changes — harmless
  today, but it runs while a user may be mid-edit in the other column (`msgEdit`
  owns that row) and the existing comment shows the author already worried about
  exactly this class of interference for user rows.
- **`_delArm`/`_msgDelArm` two-step confirm.** One armed button document-wide:
  arming a delete in B disarms the one in A, so a user who armed and then glanced
  away gets a no-op click. Cosmetic, but it is the kind of thing that reads as
  "the split is buggy."
- **`growInput`'s lazily-cached base height.** Cached on the element
  (`box._growBase`) — already per-element, so it survives the refactor. Noted
  because the default-argument path (`getElementById('chat-input')`) does not.

---

## 7. HONEST LIMITS OF THIS DRAFT

- **Nothing was built, run, or measured.** No behaviour was reproduced; every
  claim is read out of the source with file:line, and the concurrency claims
  (runner serialization, `open_queue` overwrite, Odysseus lock) are *reasoned from
  code*, not observed. The `--parallel 1` consequence in particular deserves a
  30-second live check before the UI copy is written around it.
- **The inventory is complete for the chat pane as it stands today**, including
  the two uncommitted 2026-08-14 slices (turn lifecycle + clarify/ask cards). Any
  further chat work before this lands adds rows to §1.
- **Effort is not estimated.** Phase 0+1 is a single very large mechanical diff to
  one file; the honest statement is that it is *reviewable* only if it ships with
  one instance and zero behaviour change, and that no phase should be merged with
  a "mostly green" sweep.
