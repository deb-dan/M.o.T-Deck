"""Runner-reported allocation measurements, kept distinct from process footprint.

S5 closes a truth gap in the RAM advisor.  Before a load, ``core.fit`` predicts the
allocation llama.cpp will request.  After a load, ``core.memory`` can read the
process's physical footprint.  Those values answer different questions: mmap-backed
weights can be allocated by llama.cpp without all of their pages contributing to the
current physical footprint.  This module records the third fact—the allocation lines
the pinned runner itself printed at successful startup—and never substitutes it for
either of the other two.

Only an exact, still-live ``runner.active.json`` ownership record can name a sample.
Only the latest completed llama.cpp startup segment is parsed.  Partial/failed starts,
older log segments and MLX servers therefore cannot be mislabeled as a measurement of
the current model.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
import time

from .appctx import ROOT
from .modelid import _runner_launch_record


LOG_TAIL_BYTES = 4 * 1024 * 1024
MAX_MODELS = 128
STORE_VERSION = 1
STORE_NAME = "runner_measurements.json"

_LOCK = threading.RLock()

_START = re.compile(r"load_model:\s+loading model\s+")
_DONE = re.compile(r"llama_server:\s+model loaded\s*$")
_BUFFER = re.compile(
    r"(?P<label>[A-Za-z0-9_ -]+?\b(?:model|KV|RS|compute|output) buffer size)\s*=\s*"
    r"(?P<value>[0-9]+(?:\.[0-9]+)?)\s*(?P<unit>KiB|MiB|GiB)\b",
    re.IGNORECASE,
)
_CTX = re.compile(r"llama_context:\s+n_ctx\s*=\s*(\d+)\s*$")
_KV_TYPES = re.compile(r"\bK \(([^)]+)\):.*\bV \(([^)]+)\):")


def _store_path(root: Path = ROOT) -> Path:
    return Path(root) / "data" / STORE_NAME


def _log_path(root: Path = ROOT) -> Path:
    return Path(root) / "data" / "logs" / "runner.log"


def _read_regular_tail(path: Path, limit: int = LOG_TAIL_BYTES) -> tuple[str, tuple]:
    """Read a bounded tail without following a symlink; return text + file signature."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("runner log is not a regular file")
        start = max(0, int(info.st_size) - int(limit))
        os.lseek(fd, start, os.SEEK_SET)
        remaining = min(int(limit), int(info.st_size) - start)
        chunks = []
        while remaining > 0:
            chunk = os.read(fd, min(remaining, 256 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        signature = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    finally:
        os.close(fd)
    # A bounded read can begin midway through a UTF-8 codepoint or log line.  Drop the
    # partial first line; all allocation tokens are ASCII and later complete lines.
    text = raw.decode("utf-8", errors="replace")
    if start and "\n" in text:
        text = text.split("\n", 1)[1]
    return text, signature


def _bytes(value: str, unit: str) -> int:
    scale = {"kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3}[unit.lower()]
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("invalid allocation size")
    return int(round(number * scale))


def parse_latest(text: str) -> dict | None:
    """Parse the latest *successful* llama.cpp startup segment from ``text``.

    The last start marker wins even when it failed.  We do not walk backwards to an
    older success, because that would assign the previous process's buffers to the
    current launch after a failed reload—the exact stale-truth class S5 must avoid.
    """
    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines()
    starts = [i for i, line in enumerate(lines) if _START.search(line)]
    if not starts:
        return None
    segment = lines[starts[-1]:]
    done_at = next((i for i, line in enumerate(segment) if _DONE.search(line)), None)
    if done_at is None:
        return None
    # Ignore shutdown output and any subsequent text.  A completed-start measurement
    # describes the buffers that existed when readiness was declared.
    segment = segment[:done_at + 1]
    rows: list[dict] = []
    ctx = 0
    kv_k = kv_v = ""
    for line in segment:
        match = _BUFFER.search(line)
        if match:
            label = " ".join(match.group("label").split())
            rows.append({"label": label,
                         "bytes": _bytes(match.group("value"), match.group("unit"))})
        context = _CTX.search(line)
        if context:
            ctx = int(context.group(1))
        kinds = _KV_TYPES.search(line)
        if kinds:
            kv_k, kv_v = kinds.group(1).strip(), kinds.group(2).strip()
    if not rows:
        return None

    def total(word: str) -> int:
        return sum(row["bytes"] for row in rows if word in row["label"].lower())

    model = total("model buffer")
    context = total("kv buffer") + total("rs buffer")
    working = total("compute buffer") + total("output buffer")
    overall = model + context + working
    if overall <= 0:
        return None
    return {"allocation_bytes": overall, "model_bytes": model,
            "context_bytes": context, "working_bytes": working,
            "ctx": ctx, "kv_k": kv_k, "kv_v": kv_v, "buffers": rows}


def _read_store(root: Path = ROOT) -> dict:
    path = _store_path(root)
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 2 * 1024 * 1024:
                raise ValueError("runner measurement store is invalid")
            with os.fdopen(fd, encoding="utf-8") as handle:
                fd = -1
                value = json.load(handle)
        finally:
            if fd >= 0:
                os.close(fd)
    except FileNotFoundError:
        return {"version": STORE_VERSION, "models": {}}
    except (OSError, ValueError, json.JSONDecodeError):
        return {"version": STORE_VERSION, "models": {}}
    if not isinstance(value, dict) or value.get("version") != STORE_VERSION:
        return {"version": STORE_VERSION, "models": {}}
    models = value.get("models")
    return {"version": STORE_VERSION, "models": models if isinstance(models, dict) else {}}


def _write_store(value: dict, root: Path = ROOT) -> None:
    path = _store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode):
            raise ValueError("refusing to replace a non-regular measurement store")
    except FileNotFoundError:
        pass
    fd, raw = tempfile.mkstemp(prefix=".runner-measurements-", suffix=".tmp",
                               dir=path.parent)
    temporary = Path(raw)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            fd = -1
            json.dump(value, handle, indent=1, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        try:
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            pass
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _prediction(entry: dict, parsed: dict) -> dict:
    """Re-price at the runner's observed context, preserving honest provenance."""
    try:
        from . import fit
        override = {}
        if parsed.get("ctx"):
            override["ctx"] = parsed["ctx"]
        if parsed.get("kv_k"):
            override["kv_quant"] = parsed["kv_k"]
        settings = fit.settings_for(entry, override or None)
        estimated = fit.estimate(entry, settings)
    except Exception:                                            # noqa: BLE001
        return {}
    if not estimated.get("known"):
        return {"known": False, "reason": str(estimated.get("reason") or "")[:160]}
    predicted = int(estimated.get("total_bytes") or 0)
    actual = int(parsed.get("allocation_bytes") or 0)
    return {"known": True, "total_bytes": predicted,
            "model_bytes": int(estimated.get("weights_bytes") or 0),
            "context_bytes": int(estimated.get("kv_bytes") or 0),
            "working_bytes": int(estimated.get("compute_bytes") or 0),
            "source": "oracle" if estimated.get("oracle") else estimated.get("source"),
            "delta_bytes": actual - predicted,
            "delta_pct": round(100.0 * (actual - predicted) / predicted, 1)
                         if predicted else None}


def capture(entry: dict, root: Path = ROOT) -> dict | None:
    """Capture/return the current exact runner sample, or ``None`` when unprovable."""
    launch = _runner_launch_record()
    if (not launch or launch.get("engine") != "llamacpp"
            or not isinstance(entry, dict) or entry.get("id") != launch.get("model")):
        return None
    with _LOCK:
        store = _read_store(root)
        existing = (store.get("models") or {}).get(launch["model"])
        # The exact PID + kernel birth stamp identifies one launch.  Runtime trace
        # lines make runner.log grow after every request; keying the cache to log size
        # would rewrite this measurement on every Models refresh even though the
        # allocation did not change.
        if (isinstance(existing, dict)
                and existing.get("pid") == int(launch["pid"])
                and existing.get("birth") == launch.get("birth")):
            return existing
        try:
            text, _file_signature = _read_regular_tail(_log_path(root))
        except (OSError, ValueError):
            return None
        parsed = parse_latest(text)
        if not parsed:
            return None
        row = dict(parsed)
        row.update({"model": launch["model"], "engine": "llama.cpp",
                    "pid": int(launch["pid"]), "birth": launch["birth"],
                    "at": int(time.time()), "provenance": "runner-startup-log",
                    "prediction": _prediction(entry, parsed)})
        models = store.setdefault("models", {})
        models[launch["model"]] = row
        if len(models) > MAX_MODELS:
            for old_id, _old in sorted(models.items(),
                                       key=lambda item: int(item[1].get("at") or 0))[
                                           :len(models) - MAX_MODELS]:
                models.pop(old_id, None)
        _write_store(store, root)
        return row


def recorded(model_id: str, root: Path = ROOT) -> dict | None:
    """Most recent historical sample for one model, without claiming it is live."""
    with _LOCK:
        row = (_read_store(root).get("models") or {}).get(str(model_id or ""))
    return row if isinstance(row, dict) else None
