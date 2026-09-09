"""ROUTER — the leftovers that belong to no lane: /api/open, artifact save, ody stop."""
from __future__ import annotations

import subprocess
from fastapi import Request
from fastapi.responses import JSONResponse
from ..core.appctx import app
from .ody import _ody_req


@app.post("/api/open")
async def open_external(req: Request) -> JSONResponse:
    """Open an http(s) URL in the default browser, OR open/reveal a local file.

    Two modes:
      {"url": "https://…"}                       → open in default browser (http(s) only).
      {"path": "~/…", "action": "open"|"reveal"} → open a local FILE with the default app,
                                                    or reveal it in Finder (`open -R`).

    File path-allowlist (Fable-authored §F gate): the resolved realpath must EXIST and live
    UNDER $HOME — nothing outside the user's home is ever opened. `file://` is never accepted
    in the url field. Rejections are logged.
    """
    import os
    data = await req.json()
    path = data.get("path", "")
    url = data.get("url", "")

    if path:
        action = (data.get("action") or "open").lower()
        real = os.path.realpath(os.path.expanduser(path))
        home = os.path.expanduser("~") + os.sep
        if not os.path.exists(real):
            print(f"[open] reject (missing): {real}", flush=True)
            return JSONResponse({"ok": False, "log": "path does not exist"}, status_code=400)
        if not real.startswith(home):
            print(f"[open] reject (outside $HOME): {real}", flush=True)
            return JSONResponse({"ok": False, "log": "path must be under your home folder"}, status_code=403)
        args = ["open", "-R", real] if action == "reveal" else ["open", real]
        subprocess.run(args, check=False)
        return JSONResponse({"ok": True})

    # url mode — http(s) only; never `file://` (that would bypass the path gate above).
    if not (url.startswith("http://") or url.startswith("https://")):
        return JSONResponse({"ok": False, "log": "only http(s) urls"}, status_code=400)
    subprocess.run(["open", url], check=False)
    return JSONResponse({"ok": True})


# ── Canvas: save an edited artifact to disk (Fable canvas spec, 2026-07-31) ──
# Extensions the artifact viewer holds as TEXT (mirrors the panel's artifactKind
# EXT map minus the binary kinds image/pdf, plus txt). Anything else → reject.
_ARTIFACT_SAVE_EXTS = {
    "html", "htm", "svg", "jsx", "tsx", "js", "mjs", "cjs",
    "md", "markdown", "mdown", "mmd", "mermaid", "csv", "tsv", "json",
    "py", "ts", "go", "rs", "sh", "bash", "zsh", "yaml", "yml", "toml", "ini",
    "xml", "env", "c", "h", "cpp", "cc", "hpp", "cs", "java", "rb", "php",
    "css", "scss", "sql", "swift", "kt", "lua", "r", "pl", "txt",
}
_ARTIFACT_SAVE_MAX = 5 * 1024 * 1024   # ~5MB content cap (spec)


def sanitize_artifact_filename(name) -> str | None:
    """PURE (unit-tested: bridge/tests/test_artifact_save.py).

    Reduce an UNTRUSTED filename to a safe basename, or return None (reject).
    Guarantees: no path separators / traversal, printable ASCII-safe charset,
    no leading dot (no dotfiles), non-empty bounded stem, whitelisted extension.
    The caller builds the path server-side as SAVE_DIR/<returned basename> —
    NEVER from raw client input.
    """
    import re
    s = str(name or "")
    if len(s) > 512:                                    # absurd input → reject outright
        return None
    s = s.replace("\\", "/").rsplit("/", 1)[-1]         # basename only (both separators)
    s = "".join(ch for ch in s if ch.isprintable())     # drop control/format chars (NUL, \n, RLO…)
    s = re.sub(r"[^A-Za-z0-9._ -]+", "_", s)            # ASCII-safe charset; unicode → _
    s = re.sub(r"\.{2,}", ".", s)                       # collapse dot runs ('..' remnants)
    s = re.sub(r"\s+", " ", s).strip(" .")              # tidy spaces; no edge dots (no dotfiles)
    m = re.fullmatch(r"(.+)\.([A-Za-z0-9]+)", s)
    if not m:
        return None                                     # empty / no extension
    stem, ext = m.group(1)[:80].strip(" ."), m.group(2).lower()   # overlong → cap stem
    if not stem or ext not in _ARTIFACT_SAVE_EXTS:
        return None
    return f"{stem}.{ext}"


@app.post("/api/artifact/save")
async def artifact_save(req: Request) -> JSONResponse:
    """Save an edited artifact buffer to ~/Downloads/motdeck-artifacts/ (canvas Save).

    SECURITY (Fable spec, non-negotiable): the client sends {filename, content}
    ONLY — never a path. The filename is reduced to a sanitized, extension-
    whitelisted basename; the path is constructed server-side under the fixed
    save dir; content is size-capped (~5MB). Existing files are never clobbered
    (' (n)' suffix). Writes and rejections are logged.
    """
    import os
    data = await req.json()
    if not isinstance(data, dict):
        return JSONResponse({"ok": False, "log": "expected an artifact object"}, status_code=400)
    content = data.get("content")
    if not isinstance(content, str):
        return JSONResponse({"ok": False, "log": "content must be a string"},
                            status_code=400)
    try:
        encoded = content.encode("utf-8")
    except UnicodeEncodeError:
        return JSONResponse({"ok": False, "log": "content must be valid Unicode"}, status_code=400)
    if len(encoded) > _ARTIFACT_SAVE_MAX:
        print("[artifact] reject save: content over the 5MB cap", flush=True)
        return JSONResponse({"ok": False, "log": "content exceeds the 5MB cap"},
                            status_code=413)
    name = sanitize_artifact_filename(data.get("filename", ""))
    if not name:
        print(f"[artifact] reject save: bad filename {data.get('filename')!r}", flush=True)
        return JSONResponse({"ok": False, "log": "invalid or non-whitelisted filename"},
                            status_code=400)
    save_dir = os.path.join(os.path.expanduser("~"), "Downloads", "motdeck-artifacts")
    stem, ext = name.rsplit(".", 1)
    try:
        os.makedirs(save_dir, exist_ok=True)
        for n in range(100):
            path = os.path.join(save_dir, name if n == 0 else f"{stem} ({n}).{ext}")
            try:
                # Exclusive creation also treats dangling links and concurrent
                # exports as collisions, without ever opening an existing file.
                f = open(path, "xb")
            except FileExistsError:
                continue
            with f:
                f.write(encoded)
            break
        else:
            return JSONResponse({"ok": False, "log": "all export names are in use; choose another filename"},
                                status_code=409)
    except OSError as exc:
        print(f"[artifact] save failed: {exc}", flush=True)
        return JSONResponse({"ok": False, "log": "could not write the artifact to Downloads"},
                            status_code=500)
    print(f"[artifact] saved {len(content)} chars → {path}", flush=True)
    return JSONResponse({"ok": True, "path": path})


@app.post("/api/ody/stop/{sid}")
async def ody_stop(sid: str) -> JSONResponse:
    try:
        r = await _ody_req("POST", f"/api/chat/stop/{sid}")
        return JSONResponse({"ok": r.status_code == 200})
    except Exception:
        return JSONResponse({"ok": False})


# ── Browse: register the stdio Browser MCP (browsermcp.io) in Odysseus so the
# chat's agent mode gains browser control. The user installs the Chrome extension
# once; the MCP shows "connected" after they connect a tab. (Hermes + the http
# jan-browser-mcp are follow-up slices — see CLAUDE.md.)
_BROWSERMCP = {"name": "browsermcp", "transport": "stdio",
               "command": "npx", "args": '["@browsermcp/mcp"]'}


async def _ody_mcp_list() -> list:
    """Odysseus's registered MCP servers. Raises when Odysseus is unreachable (the
    callers distinguish 'not registered' from 'we couldn't ask')."""
    r = await _ody_req("GET", "/api/mcp/servers")
    lst = r.json() if r.status_code == 200 else []
    return lst if isinstance(lst, list) else []


async def _ody_find_mcp(name: str):
    return next((s for s in await _ody_mcp_list() if s.get("name") == name), None)
