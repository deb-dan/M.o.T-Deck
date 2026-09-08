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

5. **THE PROCESS OUTLIVES THE SOCKET — A DROPPED SOCKET IS NOT AN ENDED SESSION.**
   ⚠️ THIS REVERSES v1'S RULE, AND THE REASON IS THE COMPLAINT THAT PRODUCED IT (Debi,
   2026-08-29): "every refresh wipes off the current session. That shouldn't be the
   case." v1 said a dropped socket ENDS the session and the page said so honestly — but
   a ⌘R is not a drop, it is the most ordinary thing a person does to a tab, and it was
   killing a running agent mid-turn. The lifetime is now the PROCESS's, not the
   socket's:

     · `start_relay()` gives the master fd to a thread owned by the SESSION, so bytes
       keep being read (and buffered) while nobody is attached — without it the child
       blocks on a full pty buffer and a long turn stalls behind a closed tab.
     · `attach()/detach()` swap the one subscriber. Attach REPLAYS the ring buffer, so
       a reattached terminal is not blank.
     · detach arms a GRACE TIMER (`DETACH_GRACE_S`, 10 min). Reattach cancels it;
       expiry closes the process through our OWN child handle and calls `on_reap` so
       the lane can clear its pidfile. Nothing is ever killed by name or by port.
     · The DELIBERATE end stays explicit and is distinguishable BY CONSTRUCTION rather
       than by a flag on the wire: the End button kills the PROCESS, so the socket then
       closes because the child is gone. Hence the router's rule — child alive at
       socket close ⇒ a drop (grace); child dead ⇒ an ending (reap now).

   Hermes needed a whole resume-sanitizer module because an unterminated CSI must never
   reach xterm. We do not inherit that bug class either, and not by luck: the ring
   buffer is only ever trimmed at an ESCAPE-SAFE BOUNDARY (`esc_safe_cut`), so the
   replay can never BEGIN in the middle of a control sequence. It is a bounded buffer,
   not a transcript — `SCROLLBACK_BYTES` of tail, and the page says so.

6. **THE LOCKDOWN ARGV IS A DECISION TABLE, NOT A STRING.** `--analytics-disable`
   (mixpanel + posthog are CORE deps), `--disable-playwright` (else aider can block on
   stdin asking to install it, inside our tab), `--no-auto-commits` — while git stays
   ON, because git is the only undo aider has. `--yes-always` is NEVER passed: aider's
   per-edit confirmation prompt IS the approval flow, and it renders in the PTY.

⚠️ GUARDRAIL, said out loud: MOT Deck path-guard fence does NOT cover aider (that is
a Hermes plugin on Hermes's own pre_tool_call hook). The WORKSPACE DIRECTORY is the
entire boundary — which is why it is never $HOME and never MOT Deck repo.

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

# ── THE DETACH CONTRACT (2026-08-29) ─────────────────────────────────────────
# How long a live child keeps running with NOBODY attached, before it is reaped.
#
# ⚠️ WHY TEN MINUTES AND NOT THIRTY SECONDS. The window has to cover the whole realistic
# gap between "the page went away" and "the page came back", and the slowest ordinary
# case is not a ⌘R (sub-second) — it is the user closing the tab, doing something else,
# and re-opening it. Too short and the fix does not fix the complaint; too long and a
# forgotten tab leaves an agent holding the workspace all afternoon. Ten minutes is the
# stated default and it is CONFIGURABLE per lane (motdeck.yaml `goose.detach_grace_s`),
# clamped by the two bounds below so a typo cannot mean "forever" or "immediately".
DETACH_GRACE_S = 600.0
MIN_GRACE_S, MAX_GRACE_S = 5.0, 3600.0

# The bounded scrollback replayed to a reattaching page. 256 KiB is roughly a
# 100×2000-cell terminal's worth of dense output — enough that a reattached tab shows
# the turn you were reading, small enough that an agent looping on `find /` cannot make
# the bridge's memory a function of how long you left it running. IT IS A TAIL, NOT A
# TRANSCRIPT, and the page says so rather than letting the user infer completeness.
SCROLLBACK_BYTES = 256 * 1024

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


# ── pure: the escape-safe ring-buffer cut ────────────────────────────────────
# ⚠️ THE BUG THIS EXISTS TO PREVENT, stated before the code so nobody "simplifies" it
# back: a ring buffer trimmed at an arbitrary byte offset will eventually be cut IN THE
# MIDDLE of an escape sequence, and the first thing the reattached xterm then receives
# is a truncated CSI — which it renders as garbage text, or (worse) whose parameters it
# swallows the following real output into. Hermes shipped an entire resume-sanitizer
# module for this class. Cutting only at a boundary where the parser is idle removes the
# class instead of cleaning up after it.
ESC = 0x1B
# How far back a cut looks for an unterminated sequence. Real terminal escapes are far
# shorter than this (the longest thing goose emits is an OSC title, ~80 bytes); the
# bound is what keeps the scan O(1) instead of O(buffer).
ESC_SCAN_BACK = 256


def esc_end(buf, i: int) -> int:
    """PURE. Given `i` = the index of an ESC byte, return the index ONE PAST the end of
    the sequence it starts, or len(buf) if the sequence is still unterminated.

    Only the three shapes a pty actually produces are modelled — CSI (`ESC [ … final`,
    final in 0x40–0x7E), OSC (`ESC ] … BEL` or `… ESC \\`), and everything else, which
    is ESC plus exactly one byte (or two for the `ESC ( B` charset selects). A shape we
    do not model degrades to "two bytes", which is a cut one byte later than ideal — a
    cosmetic loss, never a truncated sequence, because the NEXT cut candidate is tried.
    """
    n = len(buf)
    if i >= n:
        return n
    j = i + 1
    if j >= n:
        return n
    b = buf[j]
    if b == 0x5B:                                   # '[' → CSI
        j += 1
        while j < n and not (0x40 <= buf[j] <= 0x7E):
            j += 1
        return j + 1 if j < n else n
    if b in (0x5D, 0x50, 0x5E, 0x5F):               # ']' OSC, 'P' DCS, '^' PM, '_' APC
        j += 1
        while j < n:
            if buf[j] == 0x07:                      # BEL terminates
                return j + 1
            if buf[j] == ESC and j + 1 < n and buf[j + 1] == 0x5C:   # ESC \
                return j + 2
            j += 1
        return n
    if b in (0x28, 0x29, 0x2A, 0x2B, 0x25, 0x23):   # charset / DEC selects: ESC x y
        return min(j + 2, n)
    return j + 1


def esc_safe_cut(buf, want: int) -> int:
    """PURE. The nearest cut index >= `want` at which the buffer does NOT begin inside
    an escape sequence. Total: any input returns a valid index into `buf`.

    Look back at most ESC_SCAN_BACK bytes for an ESC; if the sequence it opens has not
    finished by `want`, the cut moves to just past that sequence instead."""
    n = len(buf)
    if want <= 0:
        return 0
    if want >= n:
        return n
    lo = max(0, want - ESC_SCAN_BACK)
    for i in range(want - 1, lo - 1, -1):
        if buf[i] == ESC:
            end = esc_end(buf, i)
            return min(end, n) if end > want else want
    return want


# ── pure: what a connecting page should get ──────────────────────────────────
def attach_verdict(alive: bool, attached: bool, requested_id: str = "",
                   live_id: str = "") -> str:
    """PURE. 'new' | 'reattach' | 'takeover' | 'conflict'.

    The whole reload story is this table, and it is a pure function so every answer can
    be proven without a browser:

      · nothing running                    → new       (spawn)
      · running, nobody attached           → reattach  ← THE ⌘R CASE
      · running AND another page attached  → takeover  ← Debi's repro, see below
      · running, a DIFFERENT session
        asked for by id                    → conflict  (never silently drop a live one)

    ⚠️ THERE IS NO 'busy' ANY MORE, AND REMOVING IT IS THE POINT. It used to be the
    answer whenever another page held the session, and it produced Debi's screenshot
    (2026-08-29, ledger U10): a tab reading "aider is already running in another window"
    UNDER a NOT CONNECTED chip, beside a Start button whose only possible outcome was
    that same refusal. Every control on the page was a dead end. The old rule was right
    about the PROCESS — there is exactly one — and wrong about the WINDOW: a window that
    asks for the one session should get it, and the window that had it should be told
    plainly and be one click from taking it back. See PtySession.attach.

    ⚠️ A CONFLICT STILL OUTRANKS A TAKEOVER. Taking over a session is recoverable — the
    other tab presses one button. Resuming a DIFFERENT conversation over a running one
    is not, so an id that does not match is still refused however few pages are
    attached. And an unknown `live_id` with an id REQUESTED is a conflict rather than a
    reattach: we would be guessing that the running session is the one asked for, and
    answering a resume request with somebody else's conversation is the LIE class.
    """
    if not alive:
        return "new"
    rid = (requested_id or "").strip()
    if rid and rid != (live_id or "").strip():
        return "conflict"
    return "takeover" if attached else "reattach"


def clamp_grace(value, fallback=DETACH_GRACE_S) -> float:
    """PURE. A grace window read off a hand-edited manifest is data, not a promise."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    if v != v or v in (float("inf"), float("-inf")):    # NaN / inf
        return float(fallback)
    return max(MIN_GRACE_S, min(MAX_GRACE_S, v))


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
    key = (api_key or "").strip()
    if not key:
        raise ValueError("runner API key is not provisioned — run scripts/local_secrets.py ensure")
    env["OPENAI_API_KEY"] = key
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
        # ── the detach/reattach state (see header §5) ──
        self._blk = threading.Lock()
        self._buf = bytearray()      # the bounded scrollback ring
        self._sub = None             # the ONE subscriber, or None while detached
        self._relay = None           # the thread that owns the master fd
        self._timer = None           # the armed grace timer
        self._reaping = False        # latched the instant the grace timer commits
        self.eof = False             # the child is gone and the relay has said so
        self.detached_at = None      # when the last subscriber went away
        self.grace_s = DETACH_GRACE_S
        self.on_reap = None          # lane callback: clear the pidfile, log, release
        self.on_chunk = None         # optional sniffer, called in the relay thread
        # Lane metadata the routers hang here so the STATUS route can be honest about
        # what is running without a second registry. '' = we do not know, which the
        # attach verdict reads as "never claim a resume request is this session".
        self.session_id = ""
        self.resumed_from = ""

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

    # -- the relay: the master fd belongs to the SESSION, not to a socket --
    def start_relay(self):
        """Own the master fd for the LIFE OF THE PROCESS. Idempotent.

        ⚠️ NOT OPTIONAL ONCE A SESSION MAY OUTLIVE ITS SOCKET, and not merely so we have
        a buffer to replay: a pty's kernel buffer is small, and a child writing into one
        that nobody drains BLOCKS. A detached agent mid-turn would silently stall — the
        exact "it looks broken" shape this lane already learned to refuse.

        ⚠️ AND IT IS OPT-IN. `read()` stays the raw primitive so a caller that wants the
        bytes itself (the lane tests drive /bin/cat that way) is not fighting a thread
        for them. Exactly one of the two may be used on a given session.
        """
        with self._blk:
            if self._relay is not None:
                return self._relay
            t = threading.Thread(target=self._relay_loop, daemon=True)
            self._relay = t
        t.start()
        return t

    def _relay_loop(self) -> None:
        while True:
            data = self.read()
            with self._blk:
                if data:
                    self._buf.extend(data)
                    # Trim lazily (at 2× the bound) and only at an escape-safe boundary
                    # — a cut inside a CSI is what makes a replayed terminal garbage.
                    if len(self._buf) > SCROLLBACK_BYTES * 2:
                        cut = esc_safe_cut(self._buf,
                                           len(self._buf) - SCROLLBACK_BYTES)
                        del self._buf[:cut]
                else:
                    self.eof = True
                sub, sniff = self._sub, self.on_chunk
            if sniff and data:
                try:
                    sniff(self, bytes(data))
                except Exception:                                # noqa: BLE001
                    pass
            if sub is not None:
                try:
                    sub(bytes(data))
                except Exception:                                # noqa: BLE001
                    pass
            if not data:
                return

    def scrollback(self) -> bytes:
        with self._blk:
            return bytes(self._buf)

    def attached(self) -> bool:
        with self._blk:
            return self._sub is not None

    def attach(self, cb):
        """Become THE subscriber — TAKING OVER from whoever held it. Returns
        (replay_bytes, eof), or None when this session is already committed to being
        reaped, in which case the caller must treat it as gone and spawn a new one.

        ⚠️ THE `None` IS THE RACE FIX, not defensiveness. The grace timer and a
        reconnecting page can fire in the same millisecond; `_reaping` is latched under
        the same lock the subscriber lives under, so exactly one of the two wins and the
        page is never handed a terminal that is about to be killed underneath it.

        ⚠️ AND ATTACH IS A TAKEOVER, NOT A QUEUE — Debi's live repro, 2026-08-29, which
        is ledger U10 reproduced. Her Aider tab showed BOTH "aider is already running in
        another window" AND a NOT CONNECTED chip with a Start button: a control whose
        only outcome was the same refusal. A dead end. The old rule ("one at a time")
        was right about the PROCESS and wrong about the WINDOW: there is exactly one
        aider, and any window that asks for it should GET it. So a second page displaces
        the first, and the first is TOLD — it gets `cb(None)`, the displace sentinel, so
        it can close with a sentence and a button that takes the session straight back.
        Reversible in one click in both directions; nobody is ever stranded.
        """
        with self._blk:
            if self._reaping or self._closed:
                return None
            old, self._sub = self._sub, cb
            replay, eof = bytes(self._buf), self.eof
            timer, self._timer = self._timer, None
            self.detached_at = None
        if timer is not None:
            timer.cancel()
        if old is not None and old is not cb:
            try:
                old(None)              # the displace sentinel — never b"", which is eof
            except Exception:                                    # noqa: BLE001
                pass
        return replay, eof

    def detach(self, cb, grace=None, on_reap=None) -> bool:
        """Give up the subscription and arm the grace window. False when `cb` was not
        the current subscriber — a stale socket must not disarm a live one's claim, and
        an ALREADY-detached session must not have its grace window silently restarted
        by a late caller (`detach(None)` on a detached session would otherwise match,
        because None is None: the bug that hides behind an identity test)."""
        with self._blk:
            if self._sub is None or self._sub is not cb:
                return False
            self._sub = None
            if on_reap is not None:
                self.on_reap = on_reap
            self.grace_s = clamp_grace(self.grace_s if grace is None else grace)
            self.detached_at = time.time()
            if not self.alive():
                return True             # nothing to reap; the child is already gone
            # Publish the timer in the same transition as releasing the subscriber.
            # A reconnect can cancel it even before start(), and a callback already
            # waiting for the lock must prove it still owns this grace window.
            t = threading.Timer(self.grace_s, lambda: self._reap(t))
            t.daemon = True             # never hold the bridge open on a shutdown
            self._timer = t
        t.start()
        return True

    def grace_left(self) -> float:
        """Seconds until the reap, 0.0 when attached or already gone. For the STATUS
        route: a page that says 'detached' without saying for how long is telling half
        the truth about a process that is going to be killed."""
        at = self.detached_at
        if at is None or not self.alive():
            return 0.0
        return max(0.0, self.grace_s - (time.time() - at))

    def _reap(self, timer) -> None:
        """The grace window expired. PROCESS-KILL RULE: this closes OUR OWN child
        handle — the one this object spawned — never a pid found by name or by port."""
        with self._blk:
            if (self._timer is not timer or self._sub is not None
                    or self._closed or self._reaping):
                return
            self._reaping = True
        self.close()
        cb = self.on_reap
        if cb is not None:
            try:
                cb(self)
            except Exception:                                    # noqa: BLE001
                pass

    def close(self) -> str:
        """Kill the process GROUP, then drop the fd. Idempotent."""
        with self._blk:
            if self._closed:
                return "gone"
            self._closed = True
            timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()
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
    # U65-class lifecycle rule: signalling an exact child is not the same as reaping
    # it. PtySession.close has no later communicate()/wait(), so poll until Popen's
    # waitpid(WNOHANG) consumes the exit rather than leaving one zombie per forced End.
    for _ in range(20):
        if proc.poll() is not None:
            break
        sleep(0.05)
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
