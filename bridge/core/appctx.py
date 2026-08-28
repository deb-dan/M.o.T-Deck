"""THE APP CONTEXT — the paths, the satellite handles and the ONE FastAPI instance.

Everything in bridge/routers/ and bridge/core/ reaches its surroundings through this
module, and it is deliberately the only file that anybody imports unconditionally: it
holds ROOT and PANEL, the nine DEFENSIVE satellite imports, and `app` itself.

⚠️ WHY `app` LIVES HERE AND NOT IN app.py. The routers register their routes with the
literal decorator they have always used — `@app.get("/api/…")` — because ~78 assertions
across the suite read those decorator lines as TEXT (see bridge/appsrc.py). Keeping the
decorator meant the routers need the FastAPI object at module scope, and app.py imports
the routers, so `app` could not stay in app.py without a cycle. It moved down here; the
alternative (an APIRouter per module) would have rewritten every one of those lines and
changed what the gate is actually checking.

⚠️ ROOT IS `parents[2]`, NOT `parent.parent`. This file is one directory deeper than
app.py was, and ROOT must keep resolving to the repo/snapshot root or every data path in
the harness moves. The value is unchanged; only the arithmetic is.
"""
from __future__ import annotations



import asyncio
import base64
import functools
import os
import random
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

# ⚠️ parents[2] AND parents[1] — NOT parent.parent AND parent. This file is one
# directory deeper than app.py was (bridge/core/ rather than bridge/), and these two
# paths are the harness's entire idea of where it lives: ROOT is the repo/snapshot
# root that every data/, scripts/ and harness.yaml path hangs off, PANEL is
# bridge/panel. The VALUES are unchanged; only the arithmetic moved with the file.
#
# Getting this wrong does not fail loudly, which is why it is spelled out here: the
# first draft of the split kept `parent.parent`, ROOT became bridge/, and the bridge
# still imported and still served — it just read bridge/harness.yaml, found nothing,
# and answered every route as though nothing were installed.
ROOT = Path(__file__).resolve().parents[2]
PANEL = Path(__file__).resolve().parents[1] / "panel"

# Harness-native voice capability (Phase B). Imported DEFENSIVELY: ship.sh has
# historically copied only bridge/app.py into the fat snapshot, so a snapshot that
# predates voice.py must still boot a working bridge — it just loses /api/voice/tts
# (which reports the import error) and treats every registry entry as a chat model,
# i.e. exactly today's behaviour. ship.sh now copies every bridge/*.py.
_VOICE_ERR = ""
try:
    from .. import voice as _voice           # normal: loaded as part of the bridge pkg
except Exception:                            # noqa: BLE001
    try:
        from bridge import voice as _voice   # loaded as a top-level module
    except Exception as _e:                  # noqa: BLE001
        _voice, _VOICE_ERR = None, str(_e)[:200]
        print(f"[voice] module unavailable — TTS disabled ({_VOICE_ERR})", flush=True)

# Harness-native MUSIC lane (FABLE-MUSIC-LANE-SPEC). Same defensive import as voice,
# for the same reason: a snapshot missing this file must still boot a bridge that
# works, minus /api/music/*.
_MUSIC_ERR = ""
try:
    from .. import music as _music
except Exception:                                # noqa: BLE001
    try:
        from bridge import music as _music
    except Exception as _e:                      # noqa: BLE001
        _music, _MUSIC_ERR = None, str(_e)[:200]
        print(f"[music] module unavailable — music lane disabled ({_MUSIC_ERR})", flush=True)

# The AIDER coding-agent lane (PTY over a websocket). Same defensive import for the
# same reason: a snapshot missing this file must still boot a bridge that works, minus
# /aider and /api/pty/aider.
_PTY_ERR = ""
try:
    from .. import pty_aider as _pty
except Exception:                                # noqa: BLE001
    try:
        from bridge import pty_aider as _pty
    except Exception as _e:                      # noqa: BLE001
        _pty, _PTY_ERR = None, str(_e)[:200]
        print(f"[aider] module unavailable — the aider tab is disabled ({_PTY_ERR})",
              flush=True)

# The OFFICE lane (spreadsheets over vendored Univer). Same defensive import for the
# same reason: a snapshot missing this file — or a bridge venv without openpyxl —
# must still boot a bridge that works, minus /office and /api/office/*.
_OFFICE_ERR = ""
try:
    from .. import office as _office
except Exception:                                # noqa: BLE001
    try:
        from bridge import office as _office
    except Exception as _e:                      # noqa: BLE001
        _office, _OFFICE_ERR = None, str(_e)[:200]
        print(f"[office] module unavailable — the Office tab is disabled ({_OFFICE_ERR})",
              flush=True)

# The OFFICE AGENT LANE — the six LOffice tools Hermes calls over MCP
# (bridge/office_ops.py = every decision, bridge/office_mcp.py = the wire). Same
# defensive import for the same reason, one step further: a snapshot that predates these
# files must still boot a bridge with a working Office TAB. It simply has no
# /mcp/office, and the Capabilities pane then shows the loffice toolset as absent
# instead of the bridge failing to start.
_OFFICE_MCP_ERR = ""
try:
    from .. import office_ops as _office_ops
    from .. import office_mcp as _office_mcp
except Exception:                                # noqa: BLE001
    try:
        from bridge import office_ops as _office_ops       # type: ignore
        from bridge import office_mcp as _office_mcp       # type: ignore
    except Exception as _e:                      # noqa: BLE001
        _office_ops = _office_mcp = None         # type: ignore
        _OFFICE_MCP_ERR = str(_e)[:200]
        print("[office] agent-lane modules unavailable — the LOffice MCP server is off "
              f"({_OFFICE_MCP_ERR})", flush=True)

# LOffice TIER 2 — the vendored ONLYOFFICE static editors (bridge/oo.py). Same
# defensive import, same reason: a snapshot that predates this file must still boot,
# it just loses /oo/*, /oo-edit and the rich-editor button — which then SAYS so
# instead of being a dead click.
_OO_ERR = ""
try:
    from .. import oo as _oo
except Exception:                                # noqa: BLE001
    try:
        from bridge import oo as _oo
    except Exception as _e:                      # noqa: BLE001
        _oo, _OO_ERR = None, str(_e)[:200]
        print(f"[office] oo module unavailable — the rich editor is off ({_OO_ERR})",
              flush=True)

# NAV — the sidebar/tab-strip customization model (FABLE-STUDIO-PHASE2-SPEC §A). Same
# defensive import for the same reason: without it the panel falls back to its own
# default layout and the shell keeps its built-in tab order, i.e. exactly the
# behaviour before this slice.
_NAV_ERR = ""
try:
    from .. import nav as _nav
except Exception:                                # noqa: BLE001
    try:
        from bridge import nav as _nav
    except Exception as _e:                      # noqa: BLE001
        _nav, _NAV_ERR = None, str(_e)[:200]
        print(f"[nav] module unavailable — default layout only ({_NAV_ERR})", flush=True)

# MODELTOOLS — the per-model tool-calling verdict (the OpenCode slice). Same
# defensive import for the same reason: without it every model simply reports
# `tools: null`, i.e. no pill and no warning — never a broken Models pane.
# scripts/seed_registry.py loads the SAME file by path, so there is one implementation.
_MODELTOOLS_ERR = ""
try:
    from .. import modeltools as _modeltools
except Exception:                                # noqa: BLE001
    try:
        from bridge import modeltools as _modeltools
    except Exception as _e:                      # noqa: BLE001
        _modeltools, _MODELTOOLS_ERR = None, str(_e)[:200]
        print(f"[models] modeltools unavailable — no tool-calling pills "
              f"({_MODELTOOLS_ERR})", flush=True)

app = FastAPI(title="AI Harness Bridge")

# Serve the panel's self-hosted assets (Phase 2 artifact renderer: babel/react/prism/
# markdown-it/dompurify) same-origin at /assets/vendor/*. Fully offline — no runtime CDN.
# The vendor dir is gitignored + fetched by scripts/fetch_vendor_assets.sh (run once on
# the Mac / at FAT build). Ensure the mount point exists so startup never errors when the
# libs haven't been fetched yet (the renderer degrades gracefully in that case).
(PANEL / "assets" / "vendor").mkdir(parents=True, exist_ok=True)
