# THE FULL PROACTIVE BUILD DOCTRINE (Debi's standing order, 2026-08-28)

**Binding on every slice, every topic, every builder and every QA pass — spreadsheets
today, voice or video or ops tomorrow. This file is the reusable prompt: paste it (or
bind by reference: "you are bound by docs/DOCTRINE-PROACTIVE-BUILD.md") into any build
task, on any subject, and it means the same thing.**

## The principle

The request is one sentence. The deliverable is the whole capability a reasonable
person believes they asked for — including the parts they never thought to say.
"It does what the ticket said" is not done. Done means: a real user, doing the real
thing this feature is FOR, over real data, across real sessions, hits no lie, no dead
end, and no surprise — including on paths they improvise.

## The seven obligations

1. **Build the destination, not the request.** Before building, write down (briefly, in
   the report) what the user is ultimately trying to DO with this — then build toward
   that, flagging anything you deliberately leave out as an explicit honest limit. A
   feature that works only for the demo phrasing of the request is a defect.

2. **Walk the journeys, end to end, on the real stack, before reporting done.**
   Enumerate the realistic journeys through the thing: first-ever use · daily use ·
   the error path · the recovery path · the interleaving with the features around it
   (switching away and back, another actor touching the same data, restarting).
   EXECUTE each one — really, not by reading code. A journey no one has run is a
   journey that does not work.

3. **Adversarial self-pass before handoff.** Spend a bounded pass genuinely trying to
   make your own work lie or fail: hostile and boundary inputs, weird-but-legal data
   shapes, state races, absent dependencies (thing not installed, model down, file
   renamed mid-flow), repeated/cancelled/stale actions. Rank findings: a LIE-TO-USER
   (silently wrong result, false success, fake data shown as real) outranks a crash;
   a crash outranks a refusal; a refusal outranks cosmetics. Fix or report every one.

4. **Unarticulated expectations are requirements.** The conventions of the product
   category ARE the spec the user never wrote: a spreadsheet behaves like Excel, a
   chat like a chat, an editor never loses typed work silently. Consistency with the
   rest of this product is a requirement. Graceful absence is a requirement (every
   state the user can reach lands on something usable — the standing empty-state
   lesson, generalized). If category convention and the ticket conflict, surface it;
   never silently ship the surprising behavior.

5. **Intelligence over rules; decisions never dumped on the user.** When behavior
   depends on intent, prefer context-aware inference (the model in the loop, or the
   surrounding data) over hard-coded rule lists — rules exist only as floors and
   guards under the inference. And do not resolve ambiguity by interrupting the user
   with questions a competent product would answer itself (the autocorrect standard):
   infer from context, act, and keep the outcome visible and reversible.

6. **Journeys become permanent tests.** Every journey walked and every adversarial
   finding fixed is pinned into the suite as an executable test before the slice
   ships. The test unit is the user story, not the code seam. The suite grows a
   library of whole journeys; the gate runs them forever.

7. **Report like an adult.** "Works" means journey-proven, with evidence. The report
   ends with an HONEST LIMITS section (what was not walked, what is inferred, what a
   human should still eyeball) and, per the reporting doctrine, the exact commands to
   see/try the result. Claiming more than was proven is itself a LIE-TO-USER.

## Adherence (how this stops recurring)

- This doctrine is bound by reference into EVERY builder dispatch and every Fable QA
  pass. A builder report that lacks the journey evidence or the honest-limits section
  is rejected, not merged.
- Lessons must be generalized at write-time: when an incident produces a rule, the
  rule is recorded in its GENERAL form with the incident as the example — never only
  in incident-shaped words. (This doctrine exists because "every lane must land on
  something usable" was written narrowly and therefore got applied narrowly.)
- The QA question at every gate is not "does it pass the tests" but "which journeys
  did we walk, and what did the adversarial pass find."

## 8. RESEARCH BEFORE BUILD (Debi, 2026-08-28 — general form)

When a topic is technical and sensitive to get wrong, the user's points are the BRIEF,
not the SPEC. Nothing we build is without prior art: the field has shipped apps solving
the same problem, and our own vendored components often already contain the solution.
Before designing, Fable runs a proactive research pass over BOTH — external references
(open-source code as source of truth; closed-source as behavioral evidence only, per the
copy-provenance rule) and our own tree (grep the vendored components: the answer may
already be installed). The spec then cites its sources and states where it corrects the
user's initial framing — correcting the brief with evidence is the job, not disloyalty.

**The incident (example, not the rule):** the RAM fit advisor. Debi's points were right
in shape; the deep-research pass they then demanded found the naive KV formula 4.1× wrong
on our own resident models (hybrid-Mamba), llama.cpp's own fit oracle already sitting in
data/llamacpp/build/bin, and the field's hard-won lesson (Ollama abandoned precise
prediction). Building from the brief alone would have shipped confidently wrong verdicts —
the LIES-TO-USER class, the worst class. The lesson is general: it applies to ANY
technical topic (memory, formats, protocols, licensing, security), not to RAM math.

### 8b. An example is not the spec (Debi, 2026-08-29)

When the user NAMES an example ("like Draw Things", "like LM Studio"), that example is
one member of the reference set and the floor of quality — never the boundary of the
search and never the design to imitate. The research pass still sweeps the field
broadly, the governing lens stays our own principles (impeccable, the design specs,
the shipped grammar), and the answer is DERIVED from converging evidence, not copied
from the named app. Anchoring on the example is the same shortcut obligation 8 bans,
wearing a compliment.

## 9. SHAPE IS SCOPE (Debi, 2026-08-29 — general form)

A "shape decision" that changes what the user SEES OR GETS — UI vs terminal, embedded
vs external app, page vs dialog, automatic vs manual — is not an implementation detail.
It is a SCOPE decision, and scope belongs to Debi. When research or building surfaces a
fact that forces the deliverable into a different shape than the user's evident
expectation, the slice STOPS and the fork is surfaced BEFORE building — not argued
brilliantly in the report after. Evident expectations count as requirements: a
preference the user has stated anywhere (even about a different component) binds the
analogous decision everywhere. Fable's QA must check every builder "shape decision"
section against the user's recorded expectations, not merely against internal
consistency — a beautifully argued wrong destination still fails.

**The incident (example, not the rule):** goose. Debi wanted goose embedded like
Unsloth because of its UI — and had earlier said Aider having no UI defied their
expectations (the recorded signal). Research checked only the CLI artifact, concluded
"no browser UI", and a PTY lane was built and QA-passed on rigor while being the wrong
destination. Hours spent; the fork ("CLI has no UI; the project ships a desktop UI;
terminal lane or embed work?") was never put to them. The backend work (pins, telemetry
kill, isolation, runner wiring) survives; the shape didn't.

## 10. PROVE THE PREMISE, NOT THE PATCH (Debi, 2026-09-05 — anti-shortcut rule)

A green test suite is evidence only for what its tests actually challenge. It is never
permission to accept the implementation's chosen abstraction, vocabulary, authority, or
source of truth without proving each of them independently. Before a fix is accepted,
Fable and the builder must write the original user-visible failure as a falsifiable
counterexample, identify every plausible authority for the state involved, and attempt
to disprove the proposed design with neighboring integrations and failure paths. Tests
must not merely construct the weak artifact or state that the new predicate accepts and
then call that acceptance proof.

For every fix, the permanent gate and report must answer all of these:

1. **What exact user counterexample now fails before the fix and passes after it?** A
   source-string assertion, a fixture copied from the implementation, or a happy-path
   status code does not answer this.
2. **Why is this source authoritative?** Filesystem, manager catalog, live process,
   persisted registry, and UI state are different truths. If ownership is plural, use
   explicit source adapters and reconciliation semantics; do not crown the first source
   inspected or create a second registry as a convenience.
3. **What would make this predicate lie?** Use minimally realistic artifacts and hostile
   controls. A one-byte file proves only presence, not GGUF or safetensors integrity; a
   directory scan proves bytes exist, not that a manager still lists the model.
4. **Which adjacent consumers and alternate entry points were exercised?** Trace and
   test the full fan-out, including reload, restart, interleaving, missing dependencies,
   external managers, and existing live state.
5. **Is the claim no broader than the evidence?** Names in code, docs, ledger rows,
   release notes, and UI must state the narrow truth. Structural completeness must not
   be called artifact integrity; filesystem availability must not be called deletion
   detection unless logical deletion is proven too.

QA rejects the slice when any answer is missing, even if every existing gate is green.
The response is a broader investigation and corrected specification before more code —
never a ceiling bump, exception, duplicate cache, symptom-specific deletion, or test
relaxation whose main virtue is making the current gate pass.

**The incident (example, not the rule):** U75 accepted one-byte GGUF/safetensors fixtures
while reporting unified artifact integrity; U76 distinguished missing bytes on an
available mount from an unavailable source, but its release wording implied that it
also distinguished models removed from LM Studio while their files remained. The first
post-screenshot proposal then elevated one `lms` catalog comparison into a design and
introduced a second persisted catalog before surveying other model managers or the
installed Unsloth inventory. Debi's challenge exposed the mismatch. This rule exists so
that the builder and QA must expose it first next time.

## 11. A FIX MAY NOT SPEND EXISTING PRODUCT INTENT (Debi, 2026-09-05)

Fixing reliability, security, maintainability, or a test ceiling is not permission to
remove or weaken an intentional feature, interaction, visual affordance, label,
shortcut, layout decision, fallback, or user-owned state. Existing behavior is part of
the specification even when the current task does not mention it. Refactoring and file
extraction carry the same obligation: code that moved must remain reachable, and a new
asset or service boundary must preserve the old boundary's failure behavior or replace
it with an explicit fail-closed experience before any action occurs.

Before accepting a change to a user-facing surface, QA compares it with the last shipped
baseline and the relevant introducing commit, accounting for moves rather than treating
raw deleted lines as removals. It inventories controls, labels, keyboard/pointer paths,
hover/focus/disabled states, stored preferences, event grammar, and reload/restart
behavior. Every intentional difference names the user outcome that authorized it;
anything unexplained is a regression or is recorded in UNFORGET as an unresolved risk,
never silently absorbed into the fix. Browser-level interaction and computed-state
checks are required where source equality cannot prove what a user sees.

**The incident (example, not the rule):** while checking the U31 extraction, Debi
reported that the sessions divider's left/right resize cursor appeared to be gone. The
divider itself proved byte-identical to its Claude-era implementation and the live page
still computed `col-resize`, but the wider audit found a different preservation failure:
if the newly external turn-stream asset failed to load, the panel could post a prompt
and then lose its renderer. A green normal-path stream suite had not tested the new
boundary's failure mode. The correction is both the code fix and this standing audit.

## 12. BACKEND TRUTH AND HUMAN REACHABILITY ARE TWO SEPARATE CONTRACTS (Debi, 2026-09-06)

A backend accepting a credential, a component answering its health probe, a route
returning HTTP 200, or a stored value matching the intended value does not prove that a
person can reach and use the capability from M.O.T. Every change to credentials,
sessions, routes, ownership, configuration, or lifecycle state must prove both sides:
the state transition is correct at its authority **and** every affected product entry
point carries the user into the usable post-transition state.

Before release, the slice owns a written journey matrix whose rows are the affected
human surfaces (native tab, sidebar page, overlay, menu/shortcut and recovery entry),
not merely the modified functions. Each row names and executes:

1. the real entry action from the installed M.O.T shell;
2. the first meaningful user action after entry, not just page load;
3. the credential/session/config handoff the user cannot perform manually;
4. reload, app restart and component restart behavior where state persists; and
5. the visible refusal/recovery path when the downstream authority is unavailable.

An HTTP/title smoke matrix is useful but cannot close a row. A login API test does not
close a native login journey; a green component card does not close a prompt, generate,
train, edit or delete journey; a DMG that mounts does not close clean-machine first run.
Anything not executed is named as an unwalked assurance gap in UNFORGET and the release
report. It is never silently promoted to “works” by test volume.

**The incident (example, not the rule):** v1.5.81 correctly generated, stored, rotated
and backend-verified Odysseus's protected admin password. The native tab still opened
upstream's ordinary login form, where the remembered weak password had stopped working
and the protected replacement was intentionally unavailable. The missing test was not
another credential unit test; it was “open Odysseus from the installed tab and reach the
authenticated workspace.” v1.5.82 added the server-side cookie handoff and walked that
exact human journey. This rule makes the same echo mandatory for every future state or
credential migration.

### 2b. The install path is a journey too (Debi, 2026-08-29)

Self-provisioning is a golden journey, not plumbing: every installer/provisioner must be
WALKED FROM SCRATCH on the real network against the pinned upstream — a clean target dir,
the actual download, the digest verification firing — and its FAILURE MODES exercised:
corrupted digest → refusal (never a half-install), interrupted transfer → honest
resume/restart state, upstream 404/moved → a readable error naming the pin. "The files are
already on disk" is NEVER evidence the install path works — sourcing an artifact from a
local copy (the user's Downloads, a cached bundle) is a spike convenience that must be
retired before shipping, because it silently exempts the install journey from testing.
Incidents: the goose UI spike read Debi's ~/Downloads/Goose.app (install path untested);
suspicion raised on the ONLYOFFICE bundle's install history — audited 2026-08-29.

### 6b. Bug classes ECHO automatically (Debi, 2026-08-29)

When a bug CLASS is identified anywhere (a lie pattern, a silent no-op, an untested path,
a kill-by-name), the response is never just the local fix: the bug-echo discipline
(installed skill; house precedent docs/research/2026-08-28-bug-echo-sweep.md +
test_bug_echo_ledger.py) fires AS PART OF THE SAME response — sweep every analogous site
in the app, record each verdict in the ledger format, pin the class with a gate test.
Fable's QA rejects a fix that arrives without its echo sweep when the finding is plainly
a class ("this could exist elsewhere" is the trigger, and it almost always could).
Incidents that each cost a re-visit because the echo didn't fire with the fix: alert()
silent no-op (fixed in comfy.html, class ledgered only later as S12), install-path
shortcut (goose UI spike, then discovered to need checking on goose CLI + ONLYOFFICE +
every provisioner — the sweep Debi had to demand).
