"""goose EMBED lane — the decisions behind serving goose Desktop's own UI in a tab.

SPIKE, 2026-08-29. Built to docs/research/2026-08-29-goose-desktop-ui.md §2a/§3/§5, which
is the BINDING source for every claim below. Read that first; this file is the executed
half of it.

⚠️ WHAT THIS LANE IS, IN ONE PARAGRAPH. goose Desktop's renderer is an ordinary Vite/React
static bundle that talks to `goosed` over a PLAIN BROWSER WEBSOCKET (ACP). goosed serves
no UI of its own and there is no `goose web`. So the embed is: (1) we serve the pinned,
UNMODIFIED renderer bundle (data/goose/ui, extracted from the v1.48.0 app.asar by
scripts/install_goose_ui.sh, from a sha-pinned upstream release artifact — NEVER from
a Goose.app installed on this Mac); (2) we supervise our own `goose serve --platform desktop`
and hand the page its ws:// URL; (3) we supply the ONE thing a browser does not have —
Electron's `window.electron` / `window.appConfig` preload objects — from a script of OUR
OWN, served alongside. Nothing in the vendored bundle is edited, ever.

⚠️ THIS LANE IS NOT THE PTY LANE AND MUST NEVER SHARE ITS STATE. bridge/pty_goose.py runs
`goose session` in a terminal under HOME=data/goose/home. This one runs `goose serve`
under GOOSE_PATH_ROOT=data/goose/ui-home/goose. Two homes, two session stores, two
pidfiles, two claims — so a terminal session and an embedded session can be open at the
same time without either seeing or clobbering the other's sessions. That separation is
walked by bridge/tests/test_gooseui_lane.py, not merely intended.

⚠️ THE ONE CONNECTION-CRITICAL SHIM IS `getAcpUrl()`. acpConnection.ts has NO fallback:
without it the renderer throws "ACP URL is not available" and nothing else in the app
runs. Everything else on the seam either shims to a browser primitive or degrades. The
three catalogues below (SHIMMED / STUBBED / DEGRADED) are the full 57-method census of
what the v1.48.0 renderer actually calls, and bridge/contract_tests/test_gooseui_contract.py
pins them: a goose bump that adds a method the renderer calls and we do not define is a
red gate rather than a `TypeError` in somebody's tab.

⚠️ SECRETS: the ACP token is a per-process secret we generate. It is handed to the page
over the SAME loopback origin the page came from, on a route the origin gate protects.
For cross-bridge adoption it is also retained in a private atomic mode-0600 runtime
record bound to the exact PID + kernel-birth owner claim; metadata alone never grants
ownership or signal authority. This is necessary because a WebSocket is not subject to
CORS, so loopback binding alone is not a boundary.
"""
from __future__ import annotations

import json
import os
import re
import secrets

# The NAMED PROVIDER, shared with the PTY lane. Its module docstring carries the whole
# empirical census — the file goose's OWN "Add custom provider" form wrote in THIS very
# fenced home, driven through this very page. Read it before changing anything
# provider-shaped here; every one of its facts was measured, none guessed.
from . import gooseprov as _prov

# ── constants ────────────────────────────────────────────────────────────────
UI_REL = "data/goose/ui"                    # the vendored renderer bundle
MANIFEST_REL = "data/goose/ui.sha256"       # its sha manifest (BUNDLE line + per file)
SOURCES_REL = "data/goose/UI-SOURCES.txt"   # provenance stamp
STAMP_REL = "data/goose/UI-INSTALLED"       # machine-readable install stamp
INSTALLER = "install_goose_ui.sh"           # OUR self-provisioning installer
BIN_INSTALLER = "install_goose.sh"          # the goose binary's, reused unchanged
HOME_REL = "data/goose/ui-home"             # ⚠️ NOT data/goose/home — see the header
PATH_ROOT_SUB = "goose"                     # GOOSE_PATH_ROOT = <HOME_REL>/goose
PIDFILE_REL = "data/goose-ui.pid"           # → the memory ledger's own row
WORKSPACE_DIR = "data/goose-workspace"      # SHARED with the PTY lane, deliberately:
#   the workspace is the user's project dir, not lane state. Two lanes editing one
#   directory is the same situation as two terminals, and pretending otherwise would
#   give the user two different "my files" for one product.

ENTRY_HTML = "index.html"                   # the vendored entry document
PRELOAD_NAME = "motdeck-preload.js"         # OUR shim — never a file in the bundle
ROUTE_PREFIX = "/gooseui"

# The pin, mirrored from scripts/install_goose_ui.sh so the status route can SAY what is
# vendored without shelling out. A drift between the two is a red contract test.
PIN_APP_VERSION = "1.48.0"
PIN_ASAR_SHA256 = "9f9f9db4a0d47a1774c86a109f19a2fd0257401726eabc0237dcb0e9b2ad9903"
# The UPSTREAM ARTIFACT the bundle is provisioned from — `Goose.zip`, the whole signed
# .app, which is the only macOS desktop asset goose publishes at this tag (there is no
# separate renderer artifact and no latest-mac.yml: both checked, 404). We keep ONE
# member of it. The size is quoted to the user BEFORE they press Install, because "this
# will download 209MB to keep 6.6MB" is a fact they are entitled to before it happens.
PIN_ASSET = "Goose.zip"
PIN_ASSET_SIZE = 219010697
PIN_ASSET_SHA256 = "98d7b09c9e57949e0dc2c8889fc05934bffb3159ae1a0c26ae0d78f397db5041"
PIN_BUNDLE_SHA256 = "342d291ddc8c41d923e15760e56164ef8e331a2dcde0769b0c476e6907d8acd0"

# `goose serve`'s own default port is 3284 and Desktop picks a free one per window. We
# pick a fixed one OUTSIDE every port motdeck.yaml already claims, because a fixed port
# is what makes "is it up?" answerable from a shell.
DEFAULT_ACP_PORT = 3287

NO_CACHE = "no-store, no-cache, must-revalidate"
# The bundle's asset names are content-hashed by Vite (assets/App-DERRs_Zf.js), so they
# are safe to cache hard. index.html is not served from disk at all (see page_html).
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"

FORCE_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".txt": "text/plain; charset=utf-8",
    ".wasm": "application/wasm",
}


# ══ THE PRELOAD CENSUS ═══════════════════════════════════════════════════════
# Measured, not guessed: every `window.electron.<name>` in the v1.48.0 renderer bundle
# (57 distinct methods) plus the `window.appConfig` keys it reads. Each name lands in
# exactly ONE of the three buckets, and PRELOAD_METHODS below is their union — which is
# the property the contract test checks against the shipped shim source.

# REAL: a browser primitive does the same job. The user notices nothing.
SHIMMED = (
    "getAcpUrl",            # ⚠️ THE ONE WITH NO FALLBACK. Our supervised ws:// URL.
    "getSecretKey",         # the same token, for the code paths that want it raw
    "getSetting",           # → localStorage (the preload ALREADY does this for 5 keys)
    "setSetting",           # → localStorage
    "getConfig",            # → the appConfig blob we inject
    "platform", "arch",     # → "darwin"/"arm64" from the server, not navigator sniffing
    "getVersion",           # → the vendored app version
    "openExternal",         # → window.open(url, "_blank")
    "openInChrome",         # → window.open
    "logInfo",              # → console.info, prefixed
    "showMessageBox",       # → confirm() (returns {response: 0|1}, goose's own shape)
    "on", "off", "emit",    # → a real in-page event bus (main→renderer pushes only)
    "onMouseBackButtonClicked", "offMouseBackButtonClicked",
    "reloadApp",            # → location.reload()
    "getIsFullScreen", "isAnyWindowFocused",   # → document.fullscreenElement/hasFocus
    "broadcastThemeChange",                    # → our own bus, same tab
    "reactReady",                              # → no-op ack (main used it for the splash)
)

# STUBS: the capability is genuinely absent in a browser, but its ABSENCE is harmless —
# every one of these returns the "nothing happened / not available" value the renderer
# already handles, because the same code runs on Linux/Windows builds where several of
# them are no-ops anyway.
STUBBED = (
    "setMenuBarIcon", "getMenuBarIconState",   # macOS menu-bar item: no such thing here
    "setDockIcon", "getDockIconState",
    "setWakelock", "getWakelockState",
    "setSpellcheck", "getSpellcheckState",
    "openNotificationsSettings", "showNotification",
    "hideWindow", "closeWindow",
    "checkForOllama",
    "checkForUpdates", "downloadUpdate", "installUpdate", "restartApp",
    "onUpdaterEvent", "getUpdateState", "isUsingGitHubFallback",
    "getAutoDownloadDisabled",                 # → true: WE disable auto-download
    "getBinaryPath",
    "hasAcceptedRecipeBefore", "recordRecipeHash",
    "launchApp", "refreshApp", "closeApp",     # MCP-"apps" window control
    "addRecentDir", "listRecentDirs",
    "listGitWorktreeDirs", "getGitBranchInfo", "listGitBranches", "switchGitBranch",
    "getAllowedExtensions",
)

# ⚠️ LOSSY — these are the honest degradations, and each one is a SENTENCE the report
# owes Debi, not a silent stub. Mapping: method → what the user loses.
DEGRADED = {
    "createChatWindow": "opens in THIS tab instead of a second window (no multi-window)",
    "directoryChooser": "no native folder picker — the working dir is fixed to the "
                        "motdeck goose workspace",
    "selectFileOrDirectory": "no native file picker (attach-by-path); drag-and-drop of "
                             "text still works",
    "selectRecipeFile": "no native picker for recipe files",
    "selectImportSessionFile": "no native picker for session import",
    "showSaveDialog": "no native save dialog",
    "getPathForFile": "a dropped file has no filesystem path in a browser — returns ''",
    "readGoosehints": "the .goosehints editor reads nothing (no direct FS access)",
    "writeGoosehints": "the .goosehints editor cannot save",
    "writeFile": "no direct filesystem write from the renderer",
    "ensureDirectory": "no direct filesystem mkdir from the renderer",
    "listFiles": "no direct filesystem listing (file-mention autocomplete degrades)",
    "openDirectoryInExplorer": "no Reveal in Finder",
}

PRELOAD_METHODS = tuple(sorted(set(SHIMMED) | set(STUBBED) | set(DEGRADED)))

# The `window.appConfig` keys the renderer actually reads (census, same method).
APPCONFIG_KEYS = ("GOOSE_VERSION", "GOOSE_LOCALE", "GOOSE_WORKING_DIR",
                  "GOOSE_DEFAULT_PROVIDER", "GOOSE_DEFAULT_MODEL",
                  "GOOSE_PREDEFINED_MODELS", "REQUEST_DIR")

# ⚠️ DELIBERATELY ABSENT, NOT FORGOTTEN — and the distinction is the whole point of
# naming them. The renderer reads these, and the CORRECT value for us is "no value":
#   GOOSE_PREDEFINED_MODELS  read as `if (e && typeof e === 'string') JSON.parse(e)`,
#       falling back to []. An enterprise deployment sets it to pin a model menu; we
#       have one runner and one loaded model. Supplying "" or "[]" would be a value the
#       code then parses — absent is the branch upstream actually wrote for us.
# Anything ADDED to the renderer's census that is neither supplied nor listed here fails
# the contract test, so "we never noticed" stops being a possible answer.
APPCONFIG_DELIBERATELY_ABSENT = ("GOOSE_PREDEFINED_MODELS",)


# ── pure: paths ──────────────────────────────────────────────────────────────
def ui_dir(root) -> str:
    return os.path.join(str(root), UI_REL)


def ui_home(root) -> str:
    return os.path.join(str(root), HOME_REL)


def path_root(root) -> str:
    """GOOSE_PATH_ROOT — where config/data/state land. VERIFIED on the real binary:
    `goose info` under this env reports config <root>/config/config.yaml, sessions
    <root>/data/sessions/sessions.db, logs <root>/state/logs. (Note: config.yaml sits
    directly under config/, NOT config/goose/ — the HOME-fenced XDG layout the PTY lane
    uses is a DIFFERENT layout, which is a second reason the two cannot collide.)"""
    return os.path.join(ui_home(root), PATH_ROOT_SUB)


def config_dir(root) -> str:
    """THE EMBED LANE'S CONFIG DIR — `<ui-home>/goose/config`, the GOOSE_PATH_ROOT
    layout. ⚠️ A DIFFERENT SHAPE FROM THE CLI LANE'S XDG one
    (`data/goose/home/.config/goose`) — see path_root()'s note. Both were walked live
    with a real provider file before the seeder was written, because assuming one layout
    for both is exactly how one lane silently ends up with no provider at all."""
    return os.path.join(path_root(root), "config")


def config_path(root) -> str:
    return os.path.join(config_dir(root), "config.yaml")


def provider_path(root) -> str:
    return _prov.provider_path(config_dir(root))


def workspace_path(root) -> str:
    return os.path.join(str(root), WORKSPACE_DIR)


def legacy_workspace_paths(home=None) -> tuple:
    """Closed historical product roots whose Goose workspace we previously owned.

    This is migration evidence, not an aliasing mechanism.  Do not widen it to every
    directory under an old support root: users may have pointed Goose at their own
    projects there, and those rows are not ours to rewrite.
    """
    base = os.path.abspath(str(home or os.path.expanduser("~")))
    return (os.path.join(base, "Library", "Application Support", "Harness",
                         "data", "goose-workspace"),)


def pidfile_path(root) -> str:
    return os.path.join(str(root), PIDFILE_REL)


def goose_bin(root) -> str:
    """THE SAME BINARY THE PTY LANE RUNS. One pin, one sha, one install script — the
    embed adds a UI, not a second copy of goose."""
    return os.path.join(str(root), "data", "goose", "bin", "goose")


def has_binary(root) -> bool:
    p = goose_bin(root)
    return os.path.isfile(p) and os.access(p, os.X_OK)


def has_bundle(root) -> bool:
    return os.path.isfile(os.path.join(ui_dir(root), ENTRY_HTML))


def is_installed(root) -> tuple:
    """(ok, reason). Read from disk every time — never a stored flag, so a deleted
    bundle or binary reads as not-installed immediately instead of offering a page that
    cannot work (the music lane's rule)."""
    if not has_binary(root):
        return False, ("the goose binary is not installed yet "
                       f"(./scripts/{BIN_INSTALLER})")
    if not has_bundle(root):
        return False, ("the goose UI bundle is not installed yet "
                       f"(./scripts/{INSTALLER})")
    return True, ""


def install_state(root) -> dict:
    """Everything the EMPTY STATE needs to render an honest Install button.

    ⚠️ TWO SEPARATE ARTIFACTS, NAMED SEPARATELY. The binary (270MB extracted, pinned by
    install_goose.sh and SHARED with the terminal lane) and the renderer bundle (6.6MB
    kept from a 209MB download, pinned by install_goose_ui.sh). A user who already ran
    the terminal lane's install must not be told to download the binary again, and a
    single "install everything" button would do exactly that.
    """
    binary, bundle = has_binary(root), has_bundle(root)
    return {
        "binary": binary,
        "bundle": bundle,
        "ready": binary and bundle,
        "app_version": PIN_APP_VERSION,
        "asset": PIN_ASSET,
        "asset_size": PIN_ASSET_SIZE,
        "asset_sha256": PIN_ASSET_SHA256,
        "asset_mb": round(PIN_ASSET_SIZE / (1024 * 1024)),
        "kept_mb": 7,
        "bundle_sha256": bundle_sha(root),
        "pin_bundle_sha256": PIN_BUNDLE_SHA256,
        "installer": f"scripts/{INSTALLER}",
        "bin_installer": f"scripts/{BIN_INSTALLER}",
    }


def bundle_sha(root) -> str:
    """The one number that identifies the vendored bundle. '' when unreadable — an
    UNKNOWN provenance is its own answer and never a fabricated one."""
    try:
        with open(os.path.join(str(root), MANIFEST_REL), encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("BUNDLE "):
                    return line.split(None, 1)[1].strip()
    except OSError:
        pass
    return ""


def bundle_target(root, rel):
    """(abs_path, None) or (None, reason) for a /gooseui/<rel> request.

    Identical rule to oo.bundle_target and office.doc_target, for its reason: the path
    comes off the wire, so realpath containment strictly under data/goose/ui is what
    makes `..` and a planted symlink both unreachable. Directories are refused; there is
    no index and no listing.
    """
    if not isinstance(rel, str) or not rel.strip():
        return None, "no file requested"
    if "\x00" in rel:
        return None, "refused: that is not a file name"
    base = os.path.realpath(ui_dir(root))
    target = os.path.realpath(os.path.join(base, rel.lstrip("/")))
    if target != base and not target.startswith(base + os.sep):
        return None, "refused: that path is outside the goose UI bundle"
    if not os.path.isfile(target):
        return None, "no such file in the goose UI bundle"
    return target, None


def media_type_for(path) -> str:
    return FORCE_TYPES.get(os.path.splitext(str(path))[1].lower(),
                           "application/octet-stream")


# ── pure: the ACP endpoint ───────────────────────────────────────────────────
def acp_url(port, token) -> str:
    """ws://127.0.0.1:<port>/acp?token=<secret>.

    ⚠️ NOT INVENTED — this is main.js's own builder, read out of the pinned app.asar:
    `he(port, secret, scheme)` composes `${scheme}://127.0.0.1:${port}`, flips the
    protocol to ws:/wss:, sets pathname `/acp` and searchParams `token`. We serve the
    non-TLS loopback shape on purpose: `--tls` uses a self-signed cert whose fingerprint
    Electron pins at the app level, which a WKWebView tab has no way to accept.
    """
    try:
        p = int(port)
    except (TypeError, ValueError):
        p = DEFAULT_ACP_PORT
    return f"ws://127.0.0.1:{p}/acp?token={token or ''}"


def status_url(port) -> str:
    try:
        p = int(port)
    except (TypeError, ValueError):
        p = DEFAULT_ACP_PORT
    return f"http://127.0.0.1:{p}/status"


def new_token() -> str:
    """A fresh GOOSE_SERVER__SECRET_KEY per supervised process. `goose serve` REFUSES to
    start without one unless `--dangerously-unauthenticated` is passed, and that flag is
    exactly the thing not to pass on a machine where any local page can open a socket."""
    return secrets.token_urlsafe(32)


# ══ ACP, THE ONE CALL WE MAKE OURSELVES: session/delete ══════════════════════
#
# WHY THIS EXISTS (Debi, asked twice): the sidebar's CHATS list has NO per-item delete
# upstream. Its row component renders a name, a rename field and three status dots and
# nothing else — deletion lives only on the Session History page, behind a hover-revealed
# trash on a card. So a user looking at six rows called "New Chat" in the sidebar has no
# way to remove one from where they are looking. app/main.swift injects a hover ✕ on
# those rows (fenced, zero vendored bytes) and it calls the route that calls THIS.
#
# ⚠️ WHY A SECOND ACP CONNECTION AND NOT THEIR OWN FUNCTION. Measured in the pinned
# v1.48.0 bundle: the delete the trash performs is `v(id)` — a MODULE-SCOPE import inside
# their Vite chunk, reachable from no global, no window object and no React context. The
# Sessions page's confirm dialog is mounted only on that page. So an injected script
# cannot call their function; what it CAN do is speak the same protocol to the same
# goosed we supervise. The method is theirs (`session/delete`, ACP), the server doing the
# deleting is theirs, the store is theirs. Nothing writes into the sqlite by hand.
#
# ⚠️ MEASURED ON THE PINNED BINARY (2026-08-29, live goosed, a session WE created for the
# purpose and then removed):
#   A1  A SECOND ACP websocket is accepted while the tab's own connection is open, and
#       neither disturbs the other. `initialize` must come first on each connection;
#       `agentCapabilities.sessionCapabilities.delete` is advertised in its result.
#   A2  `session/delete` answers `{"result": {}}` — an EMPTY OBJECT. It is not a receipt:
#       it says nothing about what went. So the confirmation here is a re-LIST, exactly
#       as the PTY lane refuses to read "exit 0" as evidence (pty_goose.remove_session).
#   A3  `session/list` returns `sessions[].sessionId` + `title`; that title is what the
#       receipt quotes back, so the user is told WHICH chat went, not just that one did.
#   A4  goosed exposes only /health, /status and /acp over HTTP — there is no REST
#       deletion endpoint to prefer over this (all four probed, 404).
ACP_PROTOCOL_VERSION = 1
ACP_TIMEOUT_S = 20.0
# goose's own session id shape. The id crosses a process boundary; nothing else may.
_SESSION_ID_RE = re.compile(r"\d{8}_\d+")


def valid_session_id(sid) -> bool:
    """PURE."""
    return bool(_SESSION_ID_RE.fullmatch((sid or "").strip()))


async def acp_calls(url: str, origin: str, calls, timeout=ACP_TIMEOUT_S) -> tuple:
    """(results, error). ONE connection: `initialize`, then each (method, params) in
    order. Notifications and other ids are skipped, never mistaken for our answer.

    Total by construction: every failure — no websockets module, a refused socket, a
    timeout, a JSON-RPC error object — comes back as a SENTENCE in `error` and an empty
    result list. Nothing here raises into a route handler.
    """
    try:
        import websockets                                    # noqa: PLC0415
    except Exception as e:                                   # noqa: BLE001
        return [], f"this bridge has no websocket client installed ({e})"
    import asyncio                                           # noqa: PLC0415
    out = []
    try:
        async with websockets.connect(url, origin=origin,
                                      open_timeout=timeout,
                                      max_size=8 * 1024 * 1024) as ws:
            seq = 0
            todo = [("initialize", {"protocolVersion": ACP_PROTOCOL_VERSION,
                                    "clientCapabilities": {}})] + list(calls)
            for method, params in todo:
                seq += 1
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": seq,
                                          "method": method, "params": params}))
                answer = None
                # A bounded read loop: goosed pushes session/update notifications on the
                # same socket, and an unbounded `while True` here would hang a request
                # thread on a chatty agent.
                for _ in range(64):
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    try:
                        msg = json.loads(raw)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(msg, dict) and msg.get("id") == seq:
                        answer = msg
                        break
                if answer is None:
                    return out, f"goose did not answer {method} in time"
                if "error" in answer:
                    err = answer.get("error") or {}
                    return out, (str(err.get("message") or err)[:200]
                                 + f" (goose refused {method})")
                if method != "initialize":
                    out.append(answer.get("result") or {})
    except asyncio.TimeoutError:
        return out, "goose did not answer in time"
    except Exception as e:                                   # noqa: BLE001
        return out, f"could not talk to goose: {type(e).__name__}: {e}"[:200]
    return out, ""


def _session_titles(result) -> dict:
    """PURE. A `session/list` result → {id: title}. Total: any odd shape costs that row."""
    out = {}
    rows = (result or {}).get("sessions") if isinstance(result, dict) else None
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        sid = str(r.get("sessionId") or "").strip()
        if sid:
            out[sid] = str(r.get("title") or "").strip()
    return out


async def migrate_legacy_session_workdirs(url: str, origin: str,
                                          canonical: str,
                                          legacy_paths) -> dict:
    """Repair product-owned session cwd rows through Goose's own ACP API.

    U34's native journey found sessions that could be listed but not opened after the
    product-support root was renamed: their cwd still named the former, now-absent
    ``data/goose-workspace``.  This is deliberately *not* a general path migration.
    The caller supplies the closed set of historical product-owned paths; a row is
    eligible only on an exact string match, only while that old path is absent, and
    only when the canonical workspace is a real directory rather than a symlink.

    Goose owns its session database, so the update goes through its published unstable
    ACP method and is independently verified with ``session/info``.  An empty update
    response, a basename match, or successful transport is never called proof.
    """
    target = os.path.abspath(str(canonical or ""))
    report = {"ok": True, "migrated": [], "untouched": 0, "errors": []}
    if (not target or not os.path.isdir(target) or os.path.islink(target)
            or os.path.realpath(target) != target):
        report["ok"] = False
        report["errors"].append("the canonical Goose workspace is not a real directory")
        return report

    eligible = set()
    for raw in legacy_paths or ():
        old = str(raw or "")
        if (old and os.path.isabs(old) and old != target
                and not os.path.lexists(old)):
            eligible.add(old)
    if not eligible:
        return report

    rows = []
    cursor = ""
    seen_cursors = set()
    for _ in range(100):
        params = {"cursor": cursor} if cursor else {}
        result, err = await acp_calls(url, origin, [("session/list", params)])
        if err:
            report["ok"] = False
            report["errors"].append(err)
            return report
        page = result[0] if result and isinstance(result[0], dict) else {}
        page_rows = page.get("sessions") or []
        rows.extend(r for r in page_rows if isinstance(r, dict))
        nxt = str(page.get("nextCursor") or "")
        if not nxt:
            break
        if nxt in seen_cursors:
            report["ok"] = False
            report["errors"].append("Goose repeated a session-list cursor")
            return report
        seen_cursors.add(nxt)
        cursor = nxt
    else:
        report["ok"] = False
        report["errors"].append("Goose session listing exceeded 100 pages")
        return report

    handled = set()
    for row in rows:
        sid = str(row.get("sessionId") or "").strip()
        cwd = str(row.get("cwd") or "")
        if sid in handled:
            continue
        handled.add(sid)
        if cwd not in eligible or not valid_session_id(sid):
            report["untouched"] += 1
            continue
        result, err = await acp_calls(
            url, origin,
            [("_goose/unstable/session/working-dir/update",
              {"sessionId": sid, "workingDir": target}),
             ("_goose/unstable/session/info", {"sessionId": sid})])
        if err:
            report["ok"] = False
            report["errors"].append(f"{sid}: {err}")
            continue
        info = result[1] if len(result) > 1 and isinstance(result[1], dict) else {}
        session = info.get("session") if isinstance(info.get("session"), dict) else {}
        if str(session.get("cwd") or "") != target:
            report["ok"] = False
            report["errors"].append(
                f"{sid}: Goose did not verify the canonical working directory")
            continue
        report["migrated"].append(sid)
    return report


async def delete_session(url: str, origin: str, sid: str) -> tuple:
    """(ok, message). goose's OWN `session/delete`, confirmed by goose's OWN list.

    The four honest answers, in order: a malformed id; a chat goose does not have; a
    delete goose refused (its words); and a delete goose accepted but that did not
    change its list — which is reported as a FAILURE, because "it returned {}" is not
    evidence (A2). Only the last case's opposite says deleted.
    """
    sid = (sid or "").strip()
    if not valid_session_id(sid):
        return False, f"{sid!r} is not a goose chat id"
    res, err = await acp_calls(url, origin, [("session/list", {})])
    if err:
        return False, err
    before = _session_titles(res[0] if res else {})
    if sid not in before:
        return False, ("goose does not have that chat any more — the list you clicked "
                       "is out of date")
    title = before.get(sid) or sid
    res, err = await acp_calls(url, origin,
                               [("session/delete", {"sessionId": sid}),
                                ("session/list", {})])
    if err:
        return False, err
    after = _session_titles(res[1] if len(res) > 1 else {})
    if sid in after:
        return False, ("goose reported no error but the chat is still in its list — "
                       "nothing is assumed; try again or delete it from Session History")
    return True, f"“{title}” deleted"


# ── pure: the launch line and the fence ──────────────────────────────────────
def serve_argv(root, port) -> list:
    """`goose serve --platform desktop --enable-scheduler --host 127.0.0.1 --port N`
    plus `--allowed-origin <our bridge origin>`.

    ⚠️ `--platform desktop` IS LOAD-BEARING, not decoration: it is what the Desktop's own
    main process passes (main.js, verbatim), and the renderer is built against that
    platform's ACP surface. `cli` would answer a different shape.
    """
    try:
        p = int(port)
    except (TypeError, ValueError):
        p = DEFAULT_ACP_PORT
    return [goose_bin(root), "serve", "--platform", "desktop", "--enable-scheduler",
            "--host", "127.0.0.1", "--port", str(p)]


def allowed_origins(bridge_port=8700) -> list:
    """The exact Origin values our page can arrive with.

    ⚠️ `--allowed-origin` REPLACES the default loopback set (AcpOriginPolicy::exact), so
    if we pass ANY we must pass ALL of ours — including the WKWebView tab's, which is the
    same bridge origin, and both spellings of loopback, because 127.0.0.1 and localhost
    are different Origins to a browser and a user typing either must not get a socket
    that silently refuses.
    """
    try:
        b = int(bridge_port)
    except (TypeError, ValueError):
        b = 8700
    return [f"http://127.0.0.1:{b}", f"http://localhost:{b}"]


def serve_env(base_env: dict, root, token: str, endpoint: str = "",
              api_key: str = "", wire_model: str = "", runner_port=6767,
              config_text: str = "") -> dict:
    """The supervised goosed's environment: the fence, the kill switches, the runner.

    ⚠️ THE FENCE IS GOOSE_PATH_ROOT *AND* HOME *AND* THE FOUR XDG DIRS — belt and braces
    on purpose, and the reason is not symmetry. GOOSE_PATH_ROOT redirects goose's own
    config/data/state (verified with `goose info` on the pinned binary). It does NOT
    redirect what the SUBPROCESSES goose spawns read: an MCP extension shelling out
    inherits HOME, and the HuggingFace cache is HF_HOME's business. So HOME is fenced
    too, and HF_HOME with it, which is the one leak §5 of the research names.

    ⚠️ AND IT IS A DIFFERENT HOME FROM THE PTY LANE'S. data/goose/ui-home vs
    data/goose/home. That is the whole no-collision guarantee, stated as a fence rather
    than as a hope.
    """
    home = ui_home(root)
    env = dict(base_env or {})
    env["GOOSE_PATH_ROOT"] = path_root(root)
    env["HOME"] = home
    env["XDG_CONFIG_HOME"] = os.path.join(home, ".config")
    env["XDG_DATA_HOME"] = os.path.join(home, ".local", "share")
    env["XDG_STATE_HOME"] = os.path.join(home, ".local", "state")
    env["XDG_CACHE_HOME"] = os.path.join(home, ".cache")
    env["HF_HOME"] = os.path.join(home, ".cache", "huggingface")
    # ── the kill switches, both mechanisms, exactly as the PTY lane does them ──
    env["GOOSE_TELEMETRY_OFF"] = "1"
    env["GOOSE_TELEMETRY_ENABLED"] = "false"
    env["GOOSE_DISABLE_KEYRING"] = "true"
    env["GOOSE_DISABLE_SESSION_NAMING"] = "true"
    # ⚠️ NOT a preference: the Desktop app auto-updates itself against
    # github:aaif-goose/goose. A supervised copy that replaces its own binary under us
    # would silently un-pin the sha we ship a contract test for.
    env["GOOSE_DISABLE_AUTO_DOWNLOAD"] = "1"
    # ⚠️ THE APPROVAL PROMPT — SET, NOT LEFT ALONE, AND THE SPIKE MEASURED WHY.
    #
    # THE FINDING (walked 2026-08-29, in WKWebView, on the real stack): with GOOSE_MODE
    # unset the embedded agent was asked to "create a file named GOOSEUI-WROTE-THIS.txt"
    # and DID — no card, no prompt, no trace in the UI beyond a tool result. At this pin
    # `GooseMode` DEFAULTS TO `auto`, so an embedded agent that can also run shell
    # commands acts on the user's disk with no consent step at all. bridge/pty_goose.py
    # recorded exactly this for the terminal lane; inheriting the same default here
    # would have shipped the same defect twice, which is what "the lesson is recorded in
    # its GENERAL form" exists to prevent.
    #
    # `smart_approve` is upstream's own middle ground. ⚠️ AND IT WORKS HERE FOR A
    # DIFFERENT REASON THAN IN THE PTY LANE: there it needs an interactive terminal
    # (headless `goose run` refuses outright under it). On the DESKTOP platform the
    # approval travels over ACP as `session/request_permission` and the renderer draws
    # the card — `request_permission` and `alwaysAllow` are both in the vendored bundle.
    # So the embed gets a real, clickable consent step; PROVEN by re-walking the same
    # write and getting a permission card instead of a file.
    env["GOOSE_MODE"] = GOOSE_MODE
    # ── the ACP secret `goose serve` refuses to start without ──
    env["GOOSE_SERVER__SECRET_KEY"] = token or ""
    # ── the runner (same wiring as the PTY lane; see pty_goose.openai_host) ──
    #
    # ⚠️ THE NAMED PROVIDER, AND THE OVERRIDE WE STOPPED DOING (v1.5.49). goose's own
    # provider picker now carries a row called "MOT Deck (local)" with every registry
    # model under it, because gooseprov.seed_provider() writes the declarative file
    # goose's own form writes. WALKED IN THIS UI: the row appears, the models list,
    # switching to it says "using … from MOT Deck (local)", and the turn answers.
    #
    # ⚠️ SEEDED, NOT ENFORCED. Measured on the pinned binary: env `GOOSE_PROVIDER`
    # OVERRIDES the config's `active_provider`. The old unconditional `= "openai"`
    # therefore undid, at every spawn, whatever provider the user had picked inside the
    # UI — after the UI had told them "Successfully switched models". provider_choice()
    # returns "" when the choice is theirs, and the MODEL travels with the provider.
    key = (api_key or "").strip()
    if not key:
        raise ValueError("runner API key is not provisioned — run scripts/local_secrets.py ensure")
    chosen, _migrate = _prov.provider_choice(config_text)
    if chosen:
        env["GOOSE_PROVIDER"] = chosen
        if wire_model:
            env["GOOSE_MODEL"] = wire_model
    else:
        for k in ("GOOSE_PROVIDER", "GOOSE_MODEL"):
            env.pop(k, None)
    # ⚠️ THE STOCK openai WIRING STAYS — it is not redundancy. A session recorded before
    # this slice carries `provider_name: openai` and goose resolves it at replay time;
    # dropping these three would break exactly the histories the migration promises not
    # to touch.
    env["OPENAI_HOST"] = _openai_host(endpoint, runner_port)
    env["OPENAI_BASE_PATH"] = "v1/chat/completions"
    env["OPENAI_API_KEY"] = key
    # The env var the NAMED provider's `api_key_env` actually points at. MEASURED: the
    # process environment BEATS `secrets.yaml` (a right key in the file and a wrong one
    # here produced 401 Invalid API Key), which is precisely why we can supply the key
    # this way and never write the user's secret store.
    env[_prov.api_key_env()] = key
    # …and the older, honestly-wrong guess at that name, kept because it costs one line
    # and because a provider a user hand-made against it before this slice still works.
    env[CUSTOM_PROVIDER_KEY_ENV] = key
    for k in ("COLUMNS", "LINES", "GOOSE_TOOLSHIM"):
        env.pop(k, None)
    return env


# ⚠️ THE OLD GUESS, KEPT AND LABELLED AS ONE. v1.5.40 assumed a custom provider created
# in goose's own UI could be told to read its key from a name WE chose. The empirical
# pass (gooseprov.py, F3) found that goose DERIVES the name from the provider's own:
# `CUSTOM_MOT_DECK__LOCAL_API_KEY`. That is what gooseprov.api_key_env() returns and what
# the child's env now carries. This one stays set beside it — one line, and it keeps a
# provider a user hand-made against it before this slice working.
CUSTOM_PROVIDER_KEY_ENV = "MOT_DECK_RUNNER_API_KEY"

# The consent mode, shared by the env and the seeded config so neither can be the only
# place it is set. See the block in serve_env for the measured finding behind it.
GOOSE_MODE = "smart_approve"
# …and the value that must NEVER be on the line, in either direction — inherited from
# the operator's shell or set by us. `auto` is what produced the finding.
FORBIDDEN_MODE = "auto"


def _openai_host(endpoint, port=6767) -> str:
    """PURE. Same rule as pty_goose.openai_host and the same trap: goose composes
    OPENAI_HOST + '/' + OPENAI_BASE_PATH, so handing it the runner's `…/v1` base
    produces /v1/v1/chat/completions — a 404 that reads as "the model is broken"."""
    s = (endpoint if isinstance(endpoint, str) else "").strip().rstrip("/")
    if s.endswith("/v1"):
        s = s[: -len("/v1")]
    if not s.startswith("http://") and not s.startswith("https://"):
        try:
            return f"http://127.0.0.1:{int(port)}"
        except (TypeError, ValueError):
            return "http://127.0.0.1:6767"
    return s


# ── pure: the seeded config ──────────────────────────────────────────────────
def config_pairs(endpoint: str, wire_model: str, port=6767,
                 active: str = "") -> tuple:
    """The keys we own in the EMBED lane's config.yaml, in a stable order.

    Seeding these is what makes the DoD's "arrives pre-configured" true: goose's
    onboarding screen appears only while it has no provider it can use, so a seeded
    provider+model means the user lands in a chat box, not in a provider picker asking
    for an OpenAI key they do not have.

    ⚠️ `active_provider` REPLACED THE TOP-LEVEL `GOOSE_PROVIDER`/`GOOSE_MODEL` PAIR, and
    that is goose's own doing, not a preference: the moment a user switches provider in
    the UI, goose rewrites this file as `providers:` + `active_provider:` and DELETES
    those two keys (measured). Re-adding them would leave two sources of truth for one
    setting, one of them ours and stale — so seed_config drops them when it migrates.
    `active` is '' when the user has a choice of their own, and then this tuple carries
    no opinion about the main model at all.
    """
    pairs = [("GOOSE_DISABLE_KEYRING", "true"),
             ("GOOSE_TELEMETRY_ENABLED", "false"),
             ("GOOSE_MODE", GOOSE_MODE),
             ("OPENAI_HOST", _openai_host(endpoint, port)),
             ("OPENAI_BASE_PATH", "v1/chat/completions")]
    if active:
        pairs.append(("active_provider", active))
    return tuple(pairs)


def upsert_config(text: str, pairs, drop=()) -> str:
    """PURE. Set each top-level `key: value`, preserving every other line byte-for-byte.
    A TEXT EDIT, NEVER A YAML ROUND-TRIP — the same rule (and reason) as
    pty_goose.upsert_config: a round-trip through a dumper eats comments and would
    silently drop the extensions the user added from inside the UI (this lane's config
    carries all 20 of them, written by goose itself).

    `drop` removes top-level keys outright, for exactly one job: the legacy
    GOOSE_PROVIDER/GOOSE_MODEL lines our own older seeding wrote."""
    out = (text or "").splitlines()
    if drop:
        want_gone = tuple(f"{k}:" for k in drop)
        out = [ln for ln in out if not ln.startswith(want_gone)]
    for key, value in pairs:
        want = f"{key}: {value}"
        for i, line in enumerate(out):
            if line.startswith(f"{key}:"):
                out[i] = want
                break
        else:
            out.append(want)
    return "\n".join(out).strip("\n") + "\n"


def read_config(root) -> str:
    """The fenced config.yaml as text, '' when absent/unreadable. '' means NO OPINION,
    which provider_choice() reads as "nothing of the user's to preserve" — the correct
    first-run answer, and the safe one for a file we cannot see."""
    try:
        with open(config_path(root), encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def seed_config(root, endpoint: str, wire_model: str, port=6767, registry=None) -> str:
    """Write our keys into the FENCED config.yaml AND our declarative provider file,
    keeping whatever else is there.

    ⚠️ TWO WRITES, ONE CALL, AND NEITHER MAY CLOBBER:
      * `config/custom_providers/custom_mot_deck__local.json` — OUR file, by name,
        MERGED so a display name the user edited in goose's own form survives untouched
        (gooseprov.OWNED_KEYS is the whole list of what we take back).
      * `active_provider:` — set ONLY when there is no choice of theirs to overwrite.

    Best-effort by design: the env carries the same settings, so a read-only config dir
    degrades to "the env wins" rather than to a dead lane."""
    p = config_path(root)
    cur = read_config(root)
    chosen, migrate = _prov.provider_choice(cur)
    # ⚠️ THE PROVIDER FILE IS WRITTEN EVEN WHEN WE DO NOT MIGRATE. A user who picked a
    # different provider still gets "MOT Deck (local)" as an OPTION in their picker with
    # a current model list — not being their default is not a reason to be absent.
    _prov.seed_provider(config_dir(root), endpoint, registry or [], port)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        new = upsert_config(cur, config_pairs(endpoint, wire_model, port,
                                              chosen if migrate else ""),
                            _prov.LEGACY_CONFIG_KEYS if migrate else ())
        if new != cur:
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(new)
            os.replace(tmp, p)
    except OSError:                                                  # noqa: BLE001
        pass
    return p


# ── pure: the page and the shim ──────────────────────────────────────────────
INJECT_MARK = "<!-- motdeck: goose preload shim -->"

# ⚠️ THE NAME OF *OUR* SURFACE, NOT OF GOOSE (Debi's ruling, 2026-08-29). The embedded
# surface is "Goose UI"; the PTY terminal lane BECAME "Goose CLI" at the full slice
# (ledger S14 — its nav/index.html/main.swift/goose.html labels all say so now, while its
# id, its route /goose and its pty path never moved). This retitles
# only the document WE generate, so the two motdeck tabs are tellable apart in a tab
# strip and in a window title. Everything INSIDE the bundle — goose's own wordmark, the
# Block lockups, every self-reference in the UI — stays exactly as shipped: that is the
# nominative-use line the trademark note in data/goose/UI-SOURCES.txt draws.
SURFACE_NAME = "Goose UI"


def retitle(index_html: str, name: str = SURFACE_NAME) -> str:
    """PURE. Replace the vendored document's <title> with OUR surface name.

    Total: a bundle whose entry document has no <title> is returned untouched rather
    than guessed at — an absent title is a cosmetic loss, and a regex that "fixes" it by
    inserting markup into a document it did not parse is how a page stops loading.
    """
    lo, hi = index_html.find("<title>"), index_html.find("</title>")
    if lo < 0 or hi < lo:
        return index_html
    return index_html[:lo] + f"<title>{name}</title>" + index_html[hi + len("</title>"):]


def page_html(index_html: str, preload_src: str) -> str:
    """OUR entry document, generated from the vendored one by adding ONE tag.

    ⚠️ THE TAG MUST LAND BEFORE THE MODULE SCRIPT AND BE NON-MODULE. The bundle's entry
    is `<script type="module" crossorigin src="./assets/index-*.js">`; a classic script
    tag placed above it is guaranteed to execute first (module scripts are deferred by
    definition), and `window.electron` must exist before ANY renderer code runs. Using
    `type="module"` for the shim would defer it too, into the same queue, and the order
    would then depend on fetch timing — the kind of race that works on localhost and
    fails once.

    ⚠️ AND THE VENDORED FILE IS NOT EDITED. This is a transform applied to the bytes on
    the way out, so data/goose/ui stays byte-identical to the asar and its sha manifest
    keeps meaning something.

    Total: if the entry tag is not found (an upstream bundle reshuffle), the shim is put
    at the end of <head>, and if there is no <head> either, at the very top. A page that
    loads with the shim in a slightly odd place is recoverable; a page served without it
    is a blank screen and an "ACP URL is not available" in a console nobody opened.
    """
    index_html = retitle(index_html)
    tag = f'{INJECT_MARK}\n    <script src="{preload_src}"></script>\n'
    needle = '<script type="module"'
    i = index_html.find(needle)
    if i >= 0:
        return index_html[:i] + tag + "    " + index_html[i:]
    i = index_html.find("</head>")
    if i >= 0:
        return index_html[:i] + tag + index_html[i:]
    return tag + index_html


def preload_js(cfg: dict) -> str:
    """OUR `window.electron` + `window.appConfig`, as one classic script.

    `cfg` carries what only the server knows: {acp_url, secret, app_config, degraded}.
    Everything else is browser primitives. The three catalogues at the top of this module
    are the spec; this function is their implementation, and the contract test asserts
    that every name in PRELOAD_METHODS is actually defined in the string this returns.
    """
    blob = json.dumps({
        "acpUrl": cfg.get("acp_url") or "",
        "secret": cfg.get("secret") or "",
        "appConfig": cfg.get("app_config") or {},
        "degraded": dict(DEGRADED),
    }, ensure_ascii=False)
    return _PRELOAD_TEMPLATE.replace("__MOT_DECK_CFG__", blob)


# ⚠️ ONE STRING, NOT A FILE ON DISK, AND THAT IS DELIBERATE. The shim has to carry the
# ACP URL and the per-process token, which change every time we start goosed — a static
# asset would either be stale or need a second fetch before `window.electron` exists,
# and "before any renderer code runs" is the whole requirement. Generating it means the
# page and its seam are always one consistent pair.
_PRELOAD_TEMPLATE = r"""// MOT Deck — the browser stand-in for goose Desktop's Electron preload.
// Generated by bridge/gooseui.py. The goose renderer bundle itself is UNMODIFIED.
(function () {
  'use strict';
  var CFG = __MOT_DECK_CFG__;

  // ── the event bus ────────────────────────────────────────────────────────
  // Every channel the renderer subscribes to is a MAIN→RENDERER push (add-extension,
  // theme-changed, find-command, new-chat, set-view, fatal-error, …). With no main
  // process there is nobody to push, so a correct, empty bus is the honest shim: the
  // listeners register and simply never fire. `emit` is wired to the same bus so the
  // renderer's own internal emits still reach its own listeners.
  var bus = Object.create(null);
  function on(ch, fn) { (bus[ch] = bus[ch] || []).push(fn); }
  function off(ch, fn) {
    var a = bus[ch]; if (!a) return;
    var i = a.indexOf(fn); if (i >= 0) a.splice(i, 1);
  }
  function emit(ch) {
    var args = Array.prototype.slice.call(arguments, 1);
    (bus[ch] || []).slice().forEach(function (fn) {
      // Electron hands listeners an IpcRendererEvent first. The renderer's handlers are
      // written `(_event, payload) => …`, so dropping it would shift every argument.
      try { fn.apply(null, [{ sender: null }].concat(args)); } catch (e) { console.error(e); }
    });
  }

  // ── settings ─────────────────────────────────────────────────────────────
  // goose's OWN preload already reads five of these from localStorage before falling
  // back to IPC; we make localStorage the whole store. Keys and coercions are copied
  // from the preload so a value written by the real app is read identically here.
  var DEFAULTS = {
    showMenuBarIcon: true, disableAutoDownload: true, showDockIcon: true,
    enableWakelock: false, enableNotifications: false, spellcheckEnabled: true,
    keyboardShortcuts: {}, externalGoosed: { enabled: false, url: '', secret: '' },
    theme: 'light', useSystemTheme: true, language: 'system',
    responseStyle: 'concise', showPricing: true, seenAnnouncementIds: [], recentModels: []
  };
  var LS_KEY = 'motdeck.goose.settings';
  function readAll() {
    try { return JSON.parse(localStorage.getItem(LS_KEY) || '{}') || {}; }
    catch (e) { return {}; }
  }
  function writeAll(o) { try { localStorage.setItem(LS_KEY, JSON.stringify(o)); } catch (e) {} }
  function getSetting(k) {
    var all = readAll();
    return Promise.resolve(k in all ? all[k] : DEFAULTS[k]);
  }
  function setSetting(k, v) { var a = readAll(); a[k] = v; writeAll(a); return Promise.resolve(true); }

  function nope(v) { return function () { return Promise.resolve(v); }; }
  function loud(name) {
    // A DEGRADED call is NOT silent. It says, once per name, what the user just lost —
    // in the console and (for the ones a user can actually trigger) as the return value
    // the renderer already knows how to handle: empty / null / false.
    var said = false;
    return function () {
      if (!said) { said = true; console.warn('[goose-embed] ' + name + ': ' + (CFG.degraded[name] || 'not available in a browser tab')); }
      return null;
    };
  }

  var electron = {
    // ── connection-critical ────────────────────────────────────────────────
    getAcpUrl: function () { return Promise.resolve(CFG.acpUrl); },
    getSecretKey: function () { return Promise.resolve(CFG.secret); },

    // ── identity / config ──────────────────────────────────────────────────
    platform: 'darwin',
    arch: 'arm64',
    getConfig: function () { return CFG.appConfig; },
    getVersion: function () { return CFG.appConfig.GOOSE_VERSION || ''; },
    reactReady: function () {},

    // ── settings ───────────────────────────────────────────────────────────
    getSetting: getSetting,
    setSetting: setSetting,

    // ── events ─────────────────────────────────────────────────────────────
    on: on, off: off, emit: emit,
    onMouseBackButtonClicked: function (fn) { on('mouse-back-button-clicked', fn); return fn; },
    offMouseBackButtonClicked: function (fn) { off('mouse-back-button-clicked', fn); },
    broadcastThemeChange: function (t) { emit('theme-changed', t); },

    // ── browser primitives ─────────────────────────────────────────────────
    logInfo: function (m) { console.info('[goose]', m); },
    openExternal: function (u) { try { window.open(u, '_blank', 'noopener'); } catch (e) {} return Promise.resolve('opened'); },
    openInChrome: function (u) { try { window.open(u, '_blank', 'noopener'); } catch (e) {} },
    showMessageBox: function (opts) {
      // Electron resolves {response: <button index>}. goose's callers treat index 1 as
      // the affirmative (its dialogs are built [cancel, confirm]), so a confirm() maps
      // cleanly — and a cancelled confirm must be 0, never undefined.
      var msg = [(opts && opts.message) || '', (opts && opts.detail) || ''].filter(Boolean).join('\n\n');
      var yes = false;
      try { yes = window.confirm(msg || 'Continue?'); } catch (e) { yes = false; }
      return Promise.resolve({ response: yes ? 1 : 0, checkboxChecked: false });
    },
    reloadApp: function () { try { location.reload(); } catch (e) {} },
    getIsFullScreen: function () { return Promise.resolve(!!document.fullscreenElement); },
    isAnyWindowFocused: function () { return Promise.resolve(document.hasFocus()); },

    // ── stubs: capability absent, absence harmless ─────────────────────────
    setMenuBarIcon: nope(false), getMenuBarIconState: nope(false),
    setDockIcon: nope(false), getDockIconState: nope(false),
    setWakelock: nope(false), getWakelockState: nope(false),
    setSpellcheck: nope(true), getSpellcheckState: nope(true),
    openNotificationsSettings: nope(false),
    showNotification: function (o) {
      // Best effort, never a prompt: an unsolicited permission dialog raised behind a
      // WKWebView tab is the same hang the keyring fence exists to prevent.
      try {
        if (window.Notification && Notification.permission === 'granted') {
          new Notification((o && o.title) || 'Goose', { body: (o && o.body) || '' });
        }
      } catch (e) {}
    },
    hideWindow: function () {}, closeWindow: function () {},
    checkForOllama: nope(false),
    checkForUpdates: nope({ updateAvailable: false }),
    downloadUpdate: nope(false), installUpdate: function () {}, restartApp: function () {},
    onUpdaterEvent: function () {}, getUpdateState: nope({ available: false }),
    isUsingGitHubFallback: nope(false),
    getAutoDownloadDisabled: nope(true),
    getBinaryPath: nope(''),
    hasAcceptedRecipeBefore: nope(false), recordRecipeHash: nope(true),
    launchApp: nope(false), refreshApp: nope(false), closeApp: nope(false),
    addRecentDir: nope(true), listRecentDirs: nope([]),
    listGitWorktreeDirs: nope([]), getGitBranchInfo: nope(null), listGitBranches: nope([]),
    switchGitBranch: nope(false),
    getAllowedExtensions: nope([]),

    // ── degraded: says what was lost, returns the "nothing" the caller handles ──
    createChatWindow: function () { console.warn('[goose-embed] createChatWindow: ' + CFG.degraded.createChatWindow); },
    directoryChooser: function () { loud('directoryChooser')(); return Promise.resolve(null); },
    selectFileOrDirectory: function () { loud('selectFileOrDirectory')(); return Promise.resolve(null); },
    selectRecipeFile: function () { loud('selectRecipeFile')(); return Promise.resolve(null); },
    selectImportSessionFile: function () { loud('selectImportSessionFile')(); return Promise.resolve(null); },
    showSaveDialog: function () { loud('showSaveDialog')(); return Promise.resolve({ canceled: true, filePath: '' }); },
    getPathForFile: function () { loud('getPathForFile')(); return ''; },
    readGoosehints: function () { loud('readGoosehints')(); return Promise.resolve(''); },
    writeGoosehints: function () { loud('writeGoosehints')(); return Promise.resolve(false); },
    writeFile: function () { loud('writeFile')(); return Promise.resolve(false); },
    ensureDirectory: function () { loud('ensureDirectory')(); return Promise.resolve(false); },
    listFiles: function () { loud('listFiles')(); return Promise.resolve([]); },
    openDirectoryInExplorer: function () { loud('openDirectoryInExplorer')(); return Promise.resolve(false); }
  };

  Object.defineProperty(window, 'electron', { value: electron, writable: false, configurable: false });
  Object.defineProperty(window, 'appConfig', {
    value: {
      get: function (k) { return CFG.appConfig[k]; },
      getAll: function () { var o = {}; for (var k in CFG.appConfig) o[k] = CFG.appConfig[k]; return o; }
    },
    writable: false, configurable: false
  });

  // ⚠️ A MISSING METHOD MUST NOT BE A SILENT `undefined is not a function` IN A TAB.
  // goose bumps add preload methods; this names the gap in the console with the version
  // that opened it, which is the difference between a diagnosable report and "it broke".
  window.__motdeckGooseSeam = { version: CFG.appConfig.GOOSE_VERSION || '', acp: !!CFG.acpUrl };
  console.info('[goose-embed] preload shim installed for goose ' +
               (CFG.appConfig.GOOSE_VERSION || '?') + ' — ' +
               Object.keys(electron).length + ' methods');
})();
"""


def app_config(version: str, workspace: str, wire_model: str = "",
               provider: str = "openai") -> dict:
    """The `window.appConfig` blob, i.e. what Electron's main process injects through
    `additionalArguments`. Only the keys the renderer actually reads are set; a key we
    do not know is ABSENT rather than guessed, because `undefined` is what the renderer's
    `??` fallbacks are written against and a fabricated value would win over them."""
    return {
        "GOOSE_VERSION": version or PIN_APP_VERSION,
        # ⚠️ "en", NOT "en-US". Electron's main hands the renderer `app.getLocale()`,
        # which on this Mac is "en-US" — and the bundle ships its catalogue as `en`, so
        # the renderer logged `Locale "en-US" has no translations; falling back to "en"`
        # on every load. Harmless, but a warning that is always printed is a warning
        # nobody reads, and the honest value here is the one the bundle actually has.
        "GOOSE_LOCALE": "en",
        "GOOSE_WORKING_DIR": workspace or "",
        "REQUEST_DIR": workspace or "",
        "GOOSE_DEFAULT_PROVIDER": provider or "",
        "GOOSE_DEFAULT_MODEL": wire_model or "",
        # ⚠️ EXTERNAL BACKEND IS OFF. The renderer has a whole "point me at somebody
        # else's goosed" path; ours is supervised and its URL comes from getAcpUrl, so
        # leaving this true would give the user a second, conflicting connection story.
        "GOOSE_EXTERNAL_BACKEND": False,
        "GOOSE_EXTERNAL_BACKEND_URL": "",
        "GOOSE_EXTERNAL_BACKEND_SOURCE": "",
    }
