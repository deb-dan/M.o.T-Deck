"""CORE — THE LIVE MEMORY LEDGER (macOS/Apple-Silicon, read-only).

The "have" half of the RAM fit advisor (docs/FABLE-RAM-FIT-ADVISOR-SPEC.md §2b +
V2-2). Everything here was measured on this machine before it was written; the
receipts are docs/research/2026-08-28-macos-memory-accounting.md.

⚠️ THE ONE RULE: PER-PROCESS MEMORY IS `phys_footprint`, NEVER RSS. Measured on our
own runner: RSS 7,214 MB vs footprint 13,040 MB — RSS understates a swapped/
compressed process by ~8.5 GB because compressed and swapped pages leave the
resident set but stay in the footprint. An advisor built on RSS would say "the 16 GB
model is using 5 GB", which is the LIE-TO-USER class this project ranks worst. It is
also what Activity Monitor's "Memory" column shows, so our numbers and the user's
other window agree. We call it "memory footprint" in the UI for the same reason.

⚠️ THE SECOND RULE: RAW FREE MEMORY IS MEANINGLESS ON macOS. The pager keeps free
near zero by design (measured: 0.9 GB free with 18 GB swapped — at NORMAL pressure,
machine fine). The headline is the kernel's own composite: `kern.memorystatus_level`
(a free PERCENTAGE) and `kern.memorystatus_vm_pressure_level` (1 normal / 2 warn /
4 critical). Swap-in-use is a secondary, neutrally-styled fact, not an alarm.

⚠️ CTYPES HYGIENE (a field report from 2026-08-28, and it cost a user-visible crash
dialog). Two probe scripts run under Apple's CLT python3.9 segfaulted at interpreter
SHUTDOWN — EXC_BAD_ACCESS in PyObject_ClearWeakRefs with _ctypes on the stack, after
the work had completed. The defensive shape adopted here, and required of anything
that copies this file:
  * the dylib handles are MODULE-LEVEL and loaded exactly once (never per call), so
    a foreign function can never outlive its library;
  * every foreign function gets an explicit `argtypes` AND `restype` before first
    use — an implicitly-typed call truncates pointers to 32 bits on arm64;
  * buffers are created inside the call frame and are dead before it returns —
    nothing ctypes-shaped is stored on a long-lived object, and no weakrefs, no
    callbacks, no `byref` result is retained anywhere;
  * every foreign call is wrapped: a missing symbol degrades to a labelled "not
    attributable" row, never to an exception in a sampling thread.
bridge/tests/test_fit_advisor.py runs this module in a SUBPROCESS and asserts a
clean exit-0 for exactly that reason.

WHAT IT IS NOT: not a process manager. We NAME external processes and we never
touch them — there is no code here that can signal, suspend or kill anything.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import plistlib
import struct
import subprocess
import threading
import time
from pathlib import Path

from .appctx import ROOT

# ── the foreign-function surface, loaded ONCE, typed explicitly ──────────────
# Module-level and never reloaded: see CTYPES HYGIENE above.
_LIBSYS = None
_LIBMETAL = None
_LIBOBJC = None
try:                                                             # pragma: no cover
    _LIBSYS = ctypes.CDLL(ctypes.util.find_library("System") or "libSystem.dylib",
                          use_errno=True)
    _LIBSYS.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    _LIBSYS.proc_pid_rusage.restype = ctypes.c_int
    _LIBSYS.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
    _LIBSYS.proc_listallpids.restype = ctypes.c_int
    _LIBSYS.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    _LIBSYS.proc_pidpath.restype = ctypes.c_int
except OSError:
    _LIBSYS = None

# `responsibility_get_pid_responsible_for_pid` is PRIVATE-but-stable (it is the
# mechanism Activity Monitor and exelban/stats both use to group an app's XPC
# helpers under the app). Feature-detected, never assumed: without it, MOT Deck.app's
# WebKit helpers — whose ppid is launchd, so no ppid walk can find them — would go
# missing, and the measured gap is 20× (shell 36 MB, its main WebContent 730 MB).
_RESPONSIBLE = None
if _LIBSYS is not None:                                          # pragma: no cover
    try:
        _RESPONSIBLE = _LIBSYS.responsibility_get_pid_responsible_for_pid
        _RESPONSIBLE.argtypes = [ctypes.c_int]
        _RESPONSIBLE.restype = ctypes.c_int
    except AttributeError:
        _RESPONSIBLE = None

# rusage_info_v4 field offsets, in 64-bit words AFTER the 16-byte uuid. Verified by
# reading real pids on this machine (runner footprint matched `footprint(1)` and
# Activity Monitor to the megabyte).
RUSAGE_INFO_V4 = 4
_RU_RESIDENT = 6
_RU_FOOTPRINT = 7
_RU_PEAK = 28
_RU_WORDS = 29


def proc_footprint(pid: int) -> "dict | None":
    """{'rss','footprint','peak'} in BYTES for one pid, or None.

    None means "we cannot see this process": it exited between the pid list and
    here, or it belongs to another user / a hardened system daemon. Treat it as
    'component gone', resample — never as zero, which would silently shrink the
    ledger."""
    if _LIBSYS is None:
        return None
    try:
        buf = ctypes.create_string_buffer(512)
        if _LIBSYS.proc_pid_rusage(int(pid), RUSAGE_INFO_V4, ctypes.byref(buf)) != 0:
            return None
        u = struct.unpack_from("<" + "Q" * _RU_WORDS, buf.raw, 16)
    except Exception:                                            # noqa: BLE001
        return None
    return {"rss": int(u[_RU_RESIDENT]), "footprint": int(u[_RU_FOOTPRINT]),
            "peak": int(u[_RU_PEAK])}


def responsible_pid(pid: int) -> "int | None":
    """The pid macOS holds RESPONSIBLE for this one (an app, for its XPC helpers)."""
    if _RESPONSIBLE is None:
        return None
    try:
        v = int(_RESPONSIBLE(int(pid)))
    except Exception:                                            # noqa: BLE001
        return None
    return v if v > 0 else None


def proc_path(pid: int) -> str:
    """Executable path for a pid ('' when unknowable)."""
    if _LIBSYS is None:
        return ""
    try:
        buf = ctypes.create_string_buffer(4096)
        n = _LIBSYS.proc_pidpath(int(pid), buf, 4096)
        if n <= 0:
            return ""
        return buf.raw[:n].decode("utf-8", errors="replace")
    except Exception:                                            # noqa: BLE001
        return ""


def all_pids() -> list:
    """Every pid on the machine (empty list when the syscall is unavailable)."""
    if _LIBSYS is None:
        return []
    # ⚠️ THE RETURN VALUE IS NOT PORTABLE BETWEEN "COUNT" AND "BYTES" — measured, and
    # it silently cost 75% of the machine's processes in the first draft. The man page
    # says the call returns the number of BYTES written; on macOS 26.6 it returns the
    # number of PIDS (716 entries → 716), so dividing by sizeof(int) kept 179 of them
    # and lost the runner. A ledger that quietly drops the biggest process on the box
    # is the LIE-TO-USER class. So we do not interpret the return value at all: the
    # buffer is zero-initialised and generously sized, and we read every non-zero slot.
    try:
        n = _LIBSYS.proc_listallpids(None, 0)
        cap = max(8192, (int(n) if n and n > 0 else 0) * 2 + 1024)
        buf = (ctypes.c_int * cap)()
        if _LIBSYS.proc_listallpids(ctypes.byref(buf), ctypes.sizeof(buf)) <= 0:
            return []
        seen, out = set(), []
        for p in buf:
            p = int(p)
            if p > 0 and p not in seen:
                seen.add(p)
                out.append(p)
        return out
    except Exception:                                            # noqa: BLE001
        return []


# ── Metal's working-set ceiling — READ LIVE, never hardcoded ─────────────────
# 55,662,788,608 B (51.84 GiB) = 81% of 64 GiB on this machine. The folk "75%" is
# wrong here, which is exactly why it is measured. This is the bound that matters on
# Apple Silicon: Metal allocations beyond it FAIL (the kernel does not swap wired GPU
# memory), so it is the fit advisor's hard ceiling, not hw.memsize.
_CEILING_CACHE: dict = {}


def metal_ceiling_bytes() -> "int | None":
    """MTLDevice.recommendedMaxWorkingSetSize, or None if Metal is unreachable."""
    if "v" in _CEILING_CACHE:
        return _CEILING_CACHE["v"]
    v = None
    global _LIBMETAL, _LIBOBJC
    try:                                                         # pragma: no cover
        if _LIBOBJC is None:
            _LIBOBJC = ctypes.CDLL(ctypes.util.find_library("objc"))
            _LIBOBJC.sel_registerName.argtypes = [ctypes.c_char_p]
            _LIBOBJC.sel_registerName.restype = ctypes.c_void_p
        if _LIBMETAL is None:
            _LIBMETAL = ctypes.CDLL(ctypes.util.find_library("Metal"))
            _LIBMETAL.MTLCreateSystemDefaultDevice.argtypes = []
            _LIBMETAL.MTLCreateSystemDefaultDevice.restype = ctypes.c_void_p
        dev = _LIBMETAL.MTLCreateSystemDefaultDevice()
        if dev:
            # objc_msgSend is variadic in C; on arm64 it MUST be called through a
            # prototype whose argtypes match the call site exactly.
            send = _LIBOBJC.objc_msgSend
            send.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            send.restype = ctypes.c_ulonglong
            sel = _LIBOBJC.sel_registerName(b"recommendedMaxWorkingSetSize")
            got = int(send(ctypes.c_void_p(dev), ctypes.c_void_p(sel)))
            v = got if got > 0 else None
    except Exception:                                            # noqa: BLE001
        v = None
    _CEILING_CACHE["v"] = v
    return v


# ── sysctls + host_statistics64 ──────────────────────────────────────────────
def _sysctl(name: str) -> str:
    try:
        out = subprocess.run(["sysctl", "-n", name], capture_output=True, text=True,
                             timeout=2)
        return (out.stdout or "").strip() if out.returncode == 0 else ""
    except Exception:                                            # noqa: BLE001
        return ""


def _sysctl_int(name: str) -> "int | None":
    s = _sysctl(name)
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


PRESSURE_WORDS = {1: "normal", 2: "warn", 4: "critical"}

# The system view costs four short subprocesses (~13 ms). A models list asks for a
# verdict per row, so without this the same second's numbers would be re-shelled a
# dozen times — and, worse, ROWS WOULD DISAGREE WITH EACH OTHER because the
# denominator moved between them. One second of cache makes a page of verdicts
# internally consistent, which matters more than the milliseconds.
_SYS_TTL_S = 1.0
_SYS_CACHE: dict = {"at": 0.0, "v": None}


def _swap() -> dict:
    """vm.swapusage → {'total','used'} bytes. {} when unreadable."""
    s = _sysctl("vm.swapusage")
    if not s:
        return {}
    out = {}
    for key, field in (("total", "total"), ("used", "used")):
        try:
            part = s.split(field + " = ")[1].split()[0]
            out[key] = int(float(part.rstrip("M")) * 1024 * 1024)
        except (IndexError, ValueError):
            pass
    return out


def _vm_stat() -> dict:
    """vm_stat's page counters, as bytes. Same numbers as host_statistics64 — taken
    through the CLI deliberately: it is a few milliseconds, it needs no second
    hand-typed struct layout, and a failure here must never be able to crash the
    sampling thread (see CTYPES HYGIENE)."""
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=3)
        if out.returncode != 0:
            return {}
        txt = out.stdout or ""
    except Exception:                                            # noqa: BLE001
        return {}
    page = 4096
    first = txt.splitlines()[0] if txt else ""
    if "page size of" in first:
        try:
            page = int(first.split("page size of")[1].split()[0])
        except (IndexError, ValueError):
            page = 4096
    vals = {}
    for line in txt.splitlines()[1:]:
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        try:
            vals[k.strip().lower()] = int(v.strip().rstrip(".")) * page
        except ValueError:
            continue
    return {"page_size": page, **vals}


def system_view() -> dict:
    """The machine's honest memory headline.

    ⚠️ TWO "AVAILABLE" NUMBERS EXIST AND THEY DISAGREE BY ~27 GB. Measured here, on
    the same second: `kern.memorystatus_level` says 76% free (48.6 GB), while Activity
    Monitor's own arithmetic (active + inactive + speculative + wired + compressor −
    purgeable − file-backed) says 42.8 GB used, i.e. 21.2 GB free. They are not the
    same question: memorystatus_level is the JETSAM trigger — how much the kernel
    believes it could reclaim under duress, counting compressible pages as
    recoverable — and Activity Monitor reports what is actually spoken for right now.

    We take the MINIMUM, and the direction of that choice is deliberate. Sizing a
    model load against the optimistic figure would produce a confident "fits" for a
    load that then swaps the machine to a crawl — a LIE-TO-USER, the class this
    project ranks above crashes. Being pessimistic costs the user a "tight" chip and
    a proceed-anyway button that always works. Both figures are returned so the
    ledger can show its work rather than assert a number."""
    now = time.time()
    if _SYS_CACHE["v"] is not None and (now - _SYS_CACHE["at"]) < _SYS_TTL_S:
        return dict(_SYS_CACHE["v"])
    total = _sysctl_int("hw.memsize") or 0
    level = _sysctl_int("kern.memorystatus_level")
    plevel = _sysctl_int("kern.memorystatus_vm_pressure_level")
    vm = _vm_stat()
    swap = _swap()
    occupied = vm.get("pages occupied by compressor", 0)
    stored = vm.get("pages stored in compressor", 0)
    wired = vm.get("pages wired down", 0)
    ratio = round(stored / occupied, 2) if occupied else None
    kernel_avail = int(total * level / 100.0) if (total and level is not None) else None
    used_am = (vm.get("pages active", 0) + vm.get("pages inactive", 0)
               + vm.get("pages speculative", 0) + wired + occupied
               - vm.get("pages purgeable", 0) - vm.get("file-backed pages", 0))
    am_avail = max(0, total - used_am) if (total and used_am) else None
    cands = [v for v in (kernel_avail, am_avail) if v]
    avail = min(cands) if cands else None
    ceiling = metal_ceiling_bytes()
    out = {
        "total_bytes": total,
        "available_pct": level,
        "available_bytes": avail,
        "available_kernel_bytes": kernel_avail,
        "available_activity_bytes": am_avail,
        "used_bytes": used_am if used_am else None,
        "pressure": PRESSURE_WORDS.get(plevel or 1, "normal"),
        "pressure_level": plevel,
        "wired_bytes": wired,
        "compressed_bytes": occupied,
        "compression_ratio": ratio,
        "cached_bytes": vm.get("file-backed pages", 0) + vm.get("purgeable pages", 0),
        "swap_used_bytes": swap.get("used"),
        "swap_total_bytes": swap.get("total"),
        "metal_ceiling_bytes": ceiling,
        "metal_ceiling_pct": (round(100.0 * ceiling / total, 1)
                              if (ceiling and total) else None),
        "wired_limit_override_mb": (_sysctl_int("iogpu.wired_limit_mb") or 0) or None,
    }
    _SYS_CACHE.update(at=now, v=dict(out))
    return out


# ── our stack: which pid is which component ──────────────────────────────────
# Every supervised component writes data/<name>.pid; the runner is the headline. The
# bridge is us. The app shell (and its WebKit helpers) is found by responsibility.
APP_EXECUTABLE_SUFFIX = "/Contents/MacOS/MOTDeck"
APP_BUNDLE_ID = "local.motdeck.app"


def _is_motdeck_shell(path: str) -> bool:
    """Recognize the shell by bundle metadata, independent of Finder renames."""
    if not path.endswith(APP_EXECUTABLE_SUFFIX):
        return False
    bundle = Path(path[:-len(APP_EXECUTABLE_SUFFIX)])
    plist = bundle / "Contents/Info.plist"
    try:
        if plist.is_symlink() or not plist.is_file():
            return False
        with plist.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return False
    return (info.get("CFBundleIdentifier") == APP_BUNDLE_ID
            and info.get("CFBundleExecutable") == "MOTDeck")


def _pidfile_pids() -> dict:
    out = {}
    d = ROOT / "data"
    try:
        names = [p for p in d.glob("*.pid")]
    except OSError:
        return out
    for p in names:
        try:
            pid = int(p.read_text().strip())
        except (OSError, ValueError):
            continue
        if pid > 0:
            out[p.stem] = pid
    return out


def _label(name: str) -> str:
    return {"runner": "Model runner", "hermes": "Hermes", "odysseus": "Odysseus",
            "searxng": "SearXNG", "voicestudio": "VoiceStudio", "voicebox": "Voicebox",
            "comfyui": "ComfyUI", "unsloth": "Unsloth", "opencode": "OpenCode",
            "deepseek": "DeepSeek",
            # ⚠️ goose is NOT a supervised component — it is a PTY lane. It appears here
            # anyway, and legitimately: bridge/routers/goose.py writes data/goose.pid for
            # exactly the lifetime of a session, so the row exists while the process does
            # and vanishes with it. A tab holding a 27B-driven agent is a real tenant of
            # this machine's RAM and the ledger would be lying by omission without it.
            #
            # ⚠️ THE LABEL IS "Goose CLI", NOT "Goose", AND THE KEY IS STILL `goose`.
            # There are two goose lanes since v1.5.40 and each writes its own pidfile, so
            # a row labelled plainly "Goose" beside one labelled "Goose UI" would leave
            # the user guessing which process a number belongs to. The KEY is the pidfile
            # STEM (data/goose.pid) and does not churn with a display name.
            "goose": "Goose CLI",
            # …and the EMBEDDED lane, whose pidfile is data/goose-ui.pid (the stem is the
            # key, hyphen and all — bridge/gooseui.py PIDFILE_REL). That pid is the goosed
            # WE supervise for /gooseui/: our own child, started by that page and stopped
            # with it. It is claimed here for goose's exact reason, and it is kept OUT of
            # the Bridge row by the own-pidfile exclusion below — which is what makes this
            # line matter. Without it the row still appears, labelled with the bare stem
            # `goose-ui`: a filename, not a name for the thing holding gigabytes of the
            # user's RAM. v1.5.40 shipped the pidfile and named this as its honest limit.
            "goose-ui": "Goose UI",
            "bridge": "Bridge", "app": "App UI"}.get(name, name)


_SCAN: dict = {"at": 0.0, "shell": None, "kids": {}, "all": [], "ppid": {}}
SCAN_EVERY_S = 30.0


def _ppid_map() -> dict:
    """pid → ppid for the whole machine, in ONE `ps` call.

    ⚠️ Deliberately not one `ps` per pid: an earlier draft did that and would have
    spawned ~600 processes per rescan. The whole ledger is supposed to cost under a
    millisecond of syscalls; a fork storm inside it would be the feature paying for
    itself in the exact resource it reports on."""
    out = {}
    try:
        res = subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True,
                             text=True, timeout=5)
        for line in (res.stdout or "").splitlines():
            parts = line.split()
            if len(parts) == 2:
                try:
                    out[int(parts[0])] = int(parts[1])
                except ValueError:
                    continue
    except Exception:                                            # noqa: BLE001
        return {}
    return out


def _rescan_tree(force: bool = False) -> None:
    """The only O(all-pids) step: find the app shell and everything macOS holds it
    responsible for, plus a snapshot of external processes. Every 30s."""
    now = time.time()
    if not force and (now - _SCAN["at"]) < SCAN_EVERY_S and _SCAN["all"]:
        return
    pids = all_pids()
    shell = None
    for pid in pids:
        if _is_motdeck_shell(proc_path(pid)):
            shell = pid
            break
    kids = {}
    if shell is not None:
        for pid in pids:
            if pid != shell and responsible_pid(pid) == shell:
                kids[pid] = os.path.basename(proc_path(pid)) or str(pid)
    _SCAN.update(at=now, shell=shell, kids=kids, all=pids, ppid=_ppid_map())


def component_rows() -> list:
    """One row per thing WE run, footprint-summed over its tree, newest sample.

    Summing footprints is honest: footprint excludes clean shared pages, so shared
    libraries and clean mmap'd files are not double-counted across the sum. The one
    residual double-count risk is genuinely shared DIRTY memory (explicit shm),
    which our stack does not use."""
    _rescan_tree()
    rows = []
    seen = set()

    def add(name: str, pids: list, kind: str = "component", note: str = "") -> None:
        foot = peak = 0
        live = []
        for pid in pids:
            if pid in seen:
                continue
            r = proc_footprint(pid)
            if r is None:
                continue
            seen.add(pid)
            live.append(pid)
            foot += r["footprint"]
            peak = max(peak, r["peak"])
        if not live:
            return
        rows.append({"name": name, "label": _label(name), "pids": live,
                     "footprint_bytes": foot, "peak_bytes": peak,
                     "kind": kind, "note": note})

    pf = _pidfile_pids()
    # The runner first: it is the headline everywhere in the UI.
    if "runner" in pf:
        add("runner", [pf.pop("runner")])
    # The bridge: this process, plus the children it spawns (aider ptys, workers).
    #
    # ⚠️ MINUS ANY CHILD THAT HAS A PIDFILE OF ITS OWN, and that exclusion is a MEASURED
    # fix, not tidiness. `add` claims pids into `seen` in call order, so a child that is
    # BOTH a direct child of this process AND the subject of data/<name>.pid was folded
    # into the Bridge row here and its own row — added below — came out empty and was
    # dropped. Measured 2026-08-29 on the goose lane: /api/memory listed only
    # ['bridge','app'] with a live goose session, i.e. the ledger silently attributed an
    # agent's whole footprint to "Bridge". Named rows outrank the catch-all: if a thing
    # is worth a pidfile it is worth its own line, and the sum is unchanged either way.
    #
    # The general rule: whenever one accounting pass can claim the same pid as another,
    # the MORE SPECIFIC claimant must run first or be excluded from the general one.
    me = os.getpid()
    owned = {p for p in pf.values()}
    bridge_pids = [me] + [p for p in _SCAN["all"]
                          if _ppid(p) == me and p not in owned]
    add("bridge", bridge_pids)
    for name in sorted(pf):
        add(name, [pf[name]])
    shell = _SCAN["shell"]
    if shell is not None:
        add("app", [shell] + sorted(_SCAN["kids"]), note=(
            "the window and its WebKit helpers"))
    elif _RESPONSIBLE is None:
        rows.append({"name": "app", "label": "App UI", "pids": [],
                     "footprint_bytes": 0, "peak_bytes": 0, "kind": "unattributable",
                     "note": "not attributable on this system"})
    return rows


def _ppid(pid: int) -> int:
    return int((_SCAN.get("ppid") or {}).get(int(pid)) or 0)


def external_rows(limit: int = 8) -> list:
    """The top external memory consumers, by name. READ-ONLY: we name them so "why
    is it tight" is answerable without leaving the app. Nothing here can act on
    them. Costs a full pid sweep, so it is only computed when asked for."""
    _rescan_tree(force=True)
    ours = set()
    for row in component_rows():
        ours.update(row.get("pids") or [])
    out = []
    for pid in _SCAN["all"]:
        if pid in ours:
            continue
        r = proc_footprint(pid)
        if r is None or r["footprint"] < 128 * 1024 * 1024:
            continue
        name = os.path.basename(proc_path(pid)) or str(pid)
        out.append({"name": name, "pid": pid, "footprint_bytes": r["footprint"]})
    out.sort(key=lambda x: -x["footprint_bytes"])
    return out[:limit]


def snapshot(external: bool = False) -> dict:
    """The whole ledger. `other_bytes` is the residual the ledger cannot attribute
    (other users' processes, kernel/driver wired, shared file cache) — it is ALWAYS
    shown so the itemisation visibly sums to the system view instead of quietly
    losing gigabytes."""
    sysv = system_view()
    rows = component_rows()
    ours = sum(int(r.get("footprint_bytes") or 0) for r in rows)
    total = sysv.get("total_bytes") or 0
    avail = sysv.get("available_bytes")
    other = None
    if total and avail is not None:
        other = max(0, total - avail - ours)
    out = {"system": sysv, "components": rows, "ours_bytes": ours,
           "other_bytes": other, "at": time.time(),
           "metric": "phys_footprint",
           "metric_note": ("Memory footprint — what Activity Monitor's Memory column "
                           "shows. Counts compressed and swapped pages; does not "
                           "count clean memory-mapped model files."),
           "responsibility_api": _RESPONSIBLE is not None}
    if external:
        out["external"] = external_rows()
    return out


# ── sampling + delta-suppressed push ─────────────────────────────────────────
# Cadence per the research: 2s while somebody is watching, 15s while merely idle,
# and NOTHING at all with no SSE subscriber — an unwatched dashboard must not wake
# a sleeping CPU. `watch()` is called by the ledger routes; it decays on its own.
WATCH_S = 2.0
IDLE_S = 15.0
WATCH_TTL_S = 30.0
DELTA_BYTES = 32 * 1024 * 1024
DELTA_FRAC = 0.02

_STATE: dict = {"watch_until": 0.0, "last": None, "thread": None, "stop": False}
_LOCK = threading.Lock()


def watch() -> None:
    """Somebody is looking at the ledger: sample fast for the next TTL."""
    _STATE["watch_until"] = time.time() + WATCH_TTL_S


def watching() -> bool:
    return time.time() < _STATE["watch_until"]


def _changed(prev: "dict | None", cur: dict) -> bool:
    """Delta-suppression: emit only on something a human would notice."""
    if prev is None:
        return True
    ps, cs = prev.get("system") or {}, cur.get("system") or {}
    for k in ("pressure", "available_pct", "swap_used_bytes"):
        if ps.get(k) != cs.get(k):
            return True
    pc = {r["name"]: r["footprint_bytes"] for r in (prev.get("components") or [])}
    cc = {r["name"]: r["footprint_bytes"] for r in (cur.get("components") or [])}
    if set(pc) != set(cc):
        return True
    for name, val in cc.items():
        old = pc.get(name, 0)
        if abs(val - old) > DELTA_BYTES and abs(val - old) > DELTA_FRAC * max(old, 1):
            return True
    return False


def _loop() -> None:                                             # pragma: no cover
    from .events import HUB, publish
    last_emit = 0.0
    while not _STATE["stop"]:
        # ⚠️ `HUB.subscribers`, and the name matters: an earlier draft read
        # `getattr(HUB, "subs", ())`, which does not exist — so the count was always 0,
        # the loop always took the idle branch, and the ledger NEVER pushed. It looked
        # exactly like a working feature (the panel repaints on its own poll), which is
        # why it survived until an SSE stream was actually read in the walk. A typo'd
        # attribute behind a getattr default is a silent off switch.
        try:
            subs = int(getattr(HUB, "subscribers", 0) or 0)
        except Exception:                                        # noqa: BLE001
            subs = 0
        if subs <= 0:
            time.sleep(IDLE_S)
            continue
        try:
            snap = snapshot()
            now = time.time()
            if _changed(_STATE["last"], snap) or (now - last_emit) > 60:
                _STATE["last"] = snap
                last_emit = now
                publish("memory", pressure=(snap["system"] or {}).get("pressure"))
        except Exception:                                        # noqa: BLE001
            pass
        time.sleep(WATCH_S if watching() else IDLE_S)


def start_sampler() -> None:
    """Idempotent. A daemon thread, so a wedged sampler can never hold a shutdown."""
    with _LOCK:
        t = _STATE.get("thread")
        if t is not None and t.is_alive():
            return
        _STATE["stop"] = False
        t = threading.Thread(target=_loop, name="memledger", daemon=True)
        _STATE["thread"] = t
        t.start()


if __name__ == "__main__":                                       # pragma: no cover
    import json
    print(json.dumps(snapshot(external=True), indent=1, default=str))
