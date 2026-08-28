"""bridge.core — the bottom of the app layer: no routes, no router imports.

Config and paths (appctx, procs), the process/port primitives, the component health
verdict, model identity, usage analytics, the harness.yaml writers, Hermes config
generation, the shared HTTP clients, the office logger.

⚠️ THE ONE RULE: nothing in here may import bridge.routers.*, and nothing may import
bridge.app. Both are enforced by bridge/tests/test_app_facade.py, because the way this
gets broken is one import line added while fixing something unrelated. When a core
module finds it needs something router-side, the answer is that the thing is not core.
"""
