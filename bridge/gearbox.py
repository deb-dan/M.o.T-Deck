"""Model gearbox (M2) — OpenAI-compatible proxy that routes local vs cloud by policy.

Planned behavior (docs §7):
- Reads policies/routing.yaml: privacy globs → local-only; task prefs; escalation; budget.
- Exposes /v1/chat/completions on the gearbox port; Hermes and Odysseus point here.
- Escalates local → cloud on repeated tool-call failure or context overflow.

Stub: not wired yet.
"""
