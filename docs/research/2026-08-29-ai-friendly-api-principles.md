# AI-friendly API principles (Debi's sources, 2026-08-29) — the house checklist

Sources: Chipiga, "7 Practical Guidelines for Designing AI-Friendly APIs" (Medium,
read via browser 2026-08-29) · Gravitee, "Designing APIs for LLM apps". Binding as a
CHECKLIST for every API surface an LLM consumes (MCP tools, lane routes, provider
endpoints) and for the S32 keys/API-page slice.

## Chipiga's 7 (LLMs are language predictors, not execution engines)
1. **Conditional APIs** — encapsulate conditions in the tool, not the orchestration:
   `set_thermostat(22, threshold=21)` beats the LLM resolving `if temp < 21`.
   Delegate WHAT, not HOW; fewer branches = fewer hallucinations, fewer tokens.
2. **Vectorized APIs** — batch, never loop: `delete_groups(user, groups)`; empty list
   = graceful no-op, single element seamless, bulk feedback in one return; optional
   list arg defaulting to "all" keeps huge intermediates out of the context window.
3. **Rich tool arguments** — pass objects, not plucked primitives; the TOOL extracts
   `user.id`, not the model.
4. **Counting APIs** — LLMs can't count or paginate-to-count: responses carry
   `totalCount` hints (`withCount`/`countOnly` params).
5. **Tools, not prompts** — user-facing content comes from tool OUTPUTS; system
   prompts orchestrate only (prompt guidance suppresses tool usage).
6. **Rich descriptions** — every tool: description, argument types+constraints,
   example uses, related tools/sequencing.
7. **Zero-trust prompting** — minimal public-safe system prompt; TOOLS enforce
   permission and policy; behavior observable and auditable.

## Gravitee's 10
Semantic field names (temperature_celsius not temp) · contextual/session awareness ·
granularity balanced for composability · ACTIONABLE error messages ("Invalid date
format: use YYYY-MM-DD", never bare 400) · async + streaming for variable-latency ·
design for LLM consumption first · strong typing/JSON Schema · semantic documentation
(meaning + intended use, not just spec) · performance (serialization, caching) ·
security-first (real auth, prompt-injection awareness).

## Where the house already complies (verified in passing)
Actionable sentence-errors are standing doctrine (the log-vomit ban); the office MCP
catalog is schema'd with readOnlyHint honesty; office_stage_changes is batched;
advisory-gates = policy in the tool. Full adherence AUDIT of every LLM-facing surface
is its own pass (S33).
