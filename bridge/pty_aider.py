"""aider coding-agent lane — the PTY seam (slice 1, 2026-08-21).

Built to docs/research/2026-08-20-aider-recon.md. aider is NOT a component: no port,
no manifest card, no daemon. It is a terminal program we run in a pseudo-terminal for
exactly as long as a browser tab holds a websocket open, in ONE chosen workspace dir.

What is load-bearing in here, and why:

1. **THE ORIGIN GATE.** WebSockets are NOT subject to CORS. Without an Origin check,
   any page in any browser on this Mac could open ws://127.0.0.1:8700/api/pty/aider and
   get a shell-capable process. Binding to loopback is NOT sufficient protection — this
   is the recon's §3.3 finding and it is the single most important line in the file.
   Hermes gates the same way (hermes_cli/web_server.py:16096, close code 4403).

2. **THE RESIZE ESCAPE IS CONSUMED, NEVER WRITTEN.** The wire is raw bytes both ways
   with exactly one control message, `\\x1b[RESIZE:<cols>;<rows>]` (Hermes's shape,
   web_server.py:14848). It is stripped server-side and turned into a TIOCSWINSZ ioctl.
   If it ever reached the PTY, aider's prompt_toolkit would render the escape as text.

3. **DIMENSIONS ARE CLAMPED.** A broken client can propose absurd sizes (Hermes clamps
   because WSL2 reports columns=131072); an unclamped ioctl is a wedged renderer.

4. **`start_new_session=True` IS NOT HYGIENE.** It gives the child its own process
   group, so a dropped socket kills aider AND everything aider spawned (`/run`
   subprocesses, linters). Without it an orphan keeps the workspace.

5. **NO BUFFER REPLAY ON RECONNECT.** Hermes needed a whole resume-sanitizer module
   because an unterminated CSI must never reach xterm. v1 does not inherit that bug
   class: a dropped socket ENDS the session, and the page says so.

6. **THE LOCKDOWN ARGV IS A DECISION TABLE, NOT A STRING.** `--analytics-disable`
   (mixpanel + posthog are CORE deps), `--disable-playwright` (else aider can block on
   stdin asking to install it, inside our tab), `--no-auto-commits` — while git stays
   ON, because git is the only undo aider has. `--yes-always` is NEVER passed: aider's
   per-edit confirmation prompt IS the approval flow, and it renders in the PTY.

⚠️ GUARDRAIL, said out loud: the harness path-guard fence does NOT cover aider (that is
a Hermes plugin on Hermes's own pre_tool_call hook). The WORKSPACE DIRECTORY is the
entire boundary — which is why it is never $HOME and never the harness repo.

Everything decision-shaped is a PURE function so it can be table-tested; the session
manager is exercised for real against /bin/cat in bridge/tests/test_aider_lane.py.
"""
from __future__ import annotations

import errno
import fcntl
import os
import re
import signal
import struct
import subprocess
import threading
import time

# ── constants ────────────────────────────────────────────────────────────────
VENV_DIR = "data/aider-venv"
VENDOR_DIR = "vendor/aider"
WORKSPACE_DIR = "data/aider-workspace"     # slice 2 adds a picker; slice 1 is one path
LOG_NAME = "aider"

# The one control message on the wire (Hermes's exact shape).
RESIZE_RE = re.compile(rb"\x1b\[RESIZE:(\d+);(\d+)\]")

MIN_COLS, MAX_COLS = 2, 2000
MIN_ROWS, MAX_ROWS = 1, 2000
DEFAULT_COLS, DEFAULT_ROWS = 100, 30

READ_CHUNK = 65536
KILL_GRACE_S = 3.0

# Close codes the page understands (4000-4999 = application-defined).
CLOSE_ORIGIN = 4403       # refused: the handshake did not come from our own page
CLOSE_BUSY = 4409         # one session at a time
CLOSE_PRECONDITION = 4412  # not installed / no model loaded
CLOSE_ENDED = 4000        # aider exited

# The lockdown flags, in the order they go on the line. EVERY one of these is in the
# recon's §2.4 table with its reason; the two flags that must NEVER appear here are
# asserted as negatives by the tests: --yes-always (removes the approval prompt that is
# the whole reason a PTY is the honest surface) and --no-git (removes /undo and /diff,
# i.e. the safety net, while keeping every bit of the write power).
LOCKDOWN_FLAGS = (
    "--analytics-disable",       # PERMANENT opt-out; --no-analytics is session-only
    "--no-check-update",         # no phone-home on launch
    "--no-show-release-notes",   # no blocking prompt on a version change
    "--no-auto-commits",         # edits stay uncommitted — the user commits
    "--no-dirty-commits",        # never commit the user's pre-existing WIP
    "--no-gitignore",            # never rewrite the user's .gitignore
    "--no-show-model-warnings",  # the runner is the authority on context, not litellm
    "--disable-playwright",      # else "Install playwright?" blocks on stdin in our tab
)
FORBIDDEN_FLAGS = ("--yes-always", "--no-git")

DEFAULT_EDIT_FORMAT = "whole"   # what a 4B can actually produce (recon §2.1)


# ── pure: the origin gate ────────────────────────────────────────────────────
def allowed_origins(port: int) -> tuple:
    """The only two origins our own page can be served from. Built from the bridge
    port so a re-ported bridge cannot silently lock its own terminal out."""
    p = int(port)
    return (f"http://127.0.0.1:{p}", f"http://localhost:{p}")


def origin_allowed(origin, port: int) -> bool:
    """PURE. True only for an exact match on one of our own origins.

    A MISSING Origin header is REFUSED. ⚠️ deliberate: a browser always sends one for a
    WebSocket handshake from a page with a real origin (which is what our tab is), so
    "absent" means "not a browser page" — a CLI client, a proxy that stripped it, or
    something we cannot identify. Refusing costs us nothing and removes the one hole a
    permissive default would leave. `null` (a sandboxed/opaque origin) is refused too.
    """
    if not isinstance(origin, str) or not origin:
        return False
    return origin.strip().rstrip("/") in allowed_origins(port)


# ── pure: the resize control message ─────────────────────────────────────────
def clamp_dim(value, lo: int, hi: int, fallback: int) -> int:
    """PURE. A dimension off the wire is data, not a promise."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return fallback
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def split_resize(data: bytes) -> tuple:
    """PURE. (bytes_for_the_pty, [(cols, rows), ...]).

    Every RESIZE escape found anywhere in the message is removed and returned as a
    clamped (cols, rows) pair; everything else passes through byte-for-byte.

    ⚠️ Deliberate limit (Hermes's too): an escape SPLIT ACROSS two websocket messages is
    not reassembled. It cannot happen with our client — the page sends each resize as
    its own message and websocket message boundaries are preserved — and a tail buffer
    would have to hold back real keystrokes that merely LOOK like a prefix.
    """
    if not data:
        return b"", []
    sizes = []
    for m in RESIZE_RE.finditer(data):
        sizes.append((clamp_dim(m.group(1), MIN_COLS, MAX_COLS, DEFAULT_COLS),
                      clamp_dim(m.group(2), MIN_ROWS, MAX_ROWS, DEFAULT_ROWS)))
    return RESIZE_RE.sub(b"", data), sizes


# ── pure: install detection + the launch line ────────────────────────────────
def aider_bin(root) -> str:
    return os.path.join(str(root), VENV_DIR, "bin", "aider")


def workspace_path(root) -> str:
    return os.path.join(str(root), WORKSPACE_DIR)


def is_installed(root) -> tuple:
    """(ok, path, reason). Read FROM DISK every time — never a stored flag, so a
    deleted venv reads as not-installed immediately instead of offering a Start that
    cannot work (the music lane's rule)."""
    p = aider_bin(root)
    if os.path.isfile(p) and os.access(p, os.X_OK):
        return True, p, ""
    return False, "", "aider is not installed yet"


def aider_argv(root, wire_model: str, edit_format: str = DEFAULT_EDIT_FORMAT) -> list:
    """PURE (given root). The full launch line.

    `wire_model` is the WIRE identifier, i.e. the output of bridge.app.wire_model_id:
    the registry id for a gguf model (llama-server is launched with `--alias <id>`) but
    the local PATH for an MLX model (mlx_lm.server resolves the request's `model` field
    as a model to LOAD — a registry id 404s on huggingface.co and the runner answers
    400). Reinventing that rule here is how the lane would silently break on MLX.
    """
    fmt = (edit_format or DEFAULT_EDIT_FORMAT).strip() or DEFAULT_EDIT_FORMAT
    return [aider_bin(root),
            "--model", f"openai/{(wire_model or '').strip()}",
            "--edit-format", fmt,
            *LOCKDOWN_FLAGS]


def aider_env(base_env: dict, endpoint: str, api_key: str) -> dict:
    """PURE. The child's environment.

    ⚠️ A DUMMY KEY IS MANDATORY even though our runner accepts anything: upstream states
    it for the LM Studio lane (same client, same failure) — with an empty value the
    OpenAI client sends an empty `Bearer` token and the request fails before it reaches
    us. COLUMNS/LINES are deliberately REMOVED: the winsize ioctl owns the size, and a
    stale inherited COLUMNS would fight it.
    """
    env = dict(base_env or {})
    env["OPENAI_API_BASE"] = (endpoint or "").strip()
    env["OPENAI_API_KEY"] = (api_key or "").strip() or "harness-local"
    env["TERM"] = "xterm-256color"
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("COLUMNS", None)
    env.pop("LINES", None)
    return env


# ── the single session ───────────────────────────────────────────────────────
_LOCK = threading.Lock()
_SESSION = None            # the one live PtySession, or None


class PtySession:
    """One aider process on one pseudo-terminal. Not thread-safe by itself; the module
    lock below is what makes "one at a time" true."""

    def __init__(self, argv, cwd, env):
        self.argv = list(argv)
        self.cwd = str(cwd)
        self.env = dict(env)
        self.master = -1
        self.proc = None
        self.started = 0.0
        self._closed = False

    # -- lifecycle --
    def start(self, cols=DEFAULT_COLS, rows=DEFAULT_ROWS, popen=subprocess.Popen):
        import pty
        master, slave = pty.openpty()
        try:
            set_winsize(master, cols, rows)
            self.proc = popen(self.argv, cwd=self.cwd, env=self.env,
                              stdin=slave, stdout=slave, stderr=slave,
                              close_fds=True, start_new_session=True)
        except Exception:
            os.close(master)
            os.close(slave)
            raise
        finally:
            # The parent must drop its copy of the slave, or read() on the master never
            # sees EOF when the child exits — the session would hang open forever.
            try:
                if self.proc is not None:
                    os.close(slave)
            except OSError:
                pass
        self.master = master
        self.started = time.time()
        return self

    def read(self, size=READ_CHUNK) -> bytes:
        """Blocking read of whatever the terminal produced. b"" = the child is gone
        (EIO is what a master fd reports when the last slave closes on macOS/Linux)."""
        try:
            return os.read(self.master, size)
        except OSError as e:
            if e.errno in (errno.EIO, errno.EBADF):
                return b""
            raise
        except ValueError:
            return b""

    def write(self, data: bytes) -> None:
        if not data or self.master < 0:
            return
        try:
            os.write(self.master, data)
        except OSError:
            pass       # the child died between the client's keystroke and this write

    def resize(self, cols: int, rows: int) -> None:
        if self.master >= 0:
            set_winsize(self.master, cols, rows)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def close(self) -> str:
        """Kill the process GROUP, then drop the fd. Idempotent."""
        if self._closed:
            return "gone"
        self._closed = True
        how = kill_process_group(self.proc)
        if self.master >= 0:
            try:
                os.close(self.master)
            except OSError:
                pass
            self.master = -1
        return how


def set_winsize(fd: int, cols: int, rows: int) -> None:
    """TIOCSWINSZ. Values are clamped here too, so no caller can be the one that forgets."""
    c = clamp_dim(cols, MIN_COLS, MAX_COLS, DEFAULT_COLS)
    r = clamp_dim(rows, MIN_ROWS, MAX_ROWS, DEFAULT_ROWS)
    try:
        import termios
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", r, c, 0, 0))
    except (OSError, ImportError, AttributeError):
        pass


def kill_process_group(proc, grace=KILL_GRACE_S, sleep=time.sleep) -> str:
    """SIGTERM the whole group, escalate to SIGKILL after `grace`. Returns what ended it
    ('term' | 'kill' | 'gone' | 'error'). Same shape as the music lane's — duplicated
    rather than imported because this module must work in a snapshot where music.py is
    missing (the defensive-import rule that voice.py established)."""
    if proc is None or proc.poll() is not None:
        return "gone"
    grp = None
    if hasattr(os, "killpg") and hasattr(os, "getpgid"):
        try:
            grp = os.getpgid(proc.pid)
        except OSError:
            grp = None

    def _signal(sig):
        try:
            if grp is not None:
                os.killpg(grp, sig)
            elif sig == signal.SIGKILL:
                proc.kill()
            else:
                proc.terminate()
            return True
        except (OSError, ProcessLookupError):
            return False

    if not _signal(signal.SIGTERM):
        return "gone" if proc.poll() is not None else "error"
    waited = 0.0
    while waited < grace:
        if proc.poll() is not None:
            return "term"
        sleep(0.1)
        waited += 0.1
    _signal(signal.SIGKILL)
    return "kill"


# ── the one-at-a-time claim ──────────────────────────────────────────────────
def claim(session) -> bool:
    """Become THE session, or refuse. A second PTY would be a second claimant on one
    workspace directory — the VoiceBusy precedent, not a queue."""
    global _SESSION
    with _LOCK:
        if _SESSION is not None and _SESSION.alive():
            return False
        _SESSION = session
        return True


def release(session) -> None:
    global _SESSION
    with _LOCK:
        if _SESSION is session:
            _SESSION = None


def current():
    with _LOCK:
        return _SESSION


def busy() -> bool:
    s = current()
    return bool(s is not None and s.alive())


def kill_current() -> str:
    """Used by the status/teardown paths; harmless when nothing runs."""
    s = current()
    if s is None:
        return "gone"
    how = s.close()
    release(s)
    return how
