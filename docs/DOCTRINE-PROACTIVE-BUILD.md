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
