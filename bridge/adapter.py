"""Hermes <-> Odysseus adapter (M0/M1).

Registers Hermes's MCP server (port 8721) inside Odysseus's MCP settings, so
Odysseus chat can delegate agentic work to Hermes. All upstream-coupling logic
lives here and only here — when an update breaks the seam, this file absorbs it.

Stub: manual wiring first (add http://127.0.0.1:8721 in Odysseus Settings → MCP),
automated registration lands with M1 contract tests.
"""
