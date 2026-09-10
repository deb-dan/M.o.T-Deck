"""User-owned RAM-advisor speaking policy (S6).

The fit arithmetic is unchanged by Quiet/Advise/Advise early.  Those modes decide
only when the app pauses to explain a risky load.  Custom headroom additionally
reserves an explicit amount from the otherwise identical live budget.  No preference
can remove the Load-anyway path or override the separate Metal kernel-panic refusal.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import stat
import tempfile
import threading

from .appctx import ROOT


def default_headroom_gb() -> float:
    """Hardware-adaptive headroom: ~12% of RAM, clamped between 1.0 and 4.0 GB."""
    try:
        from . import memory as _mem
        sysv = _mem.system_view()
        total_gb = (sysv.get("total_bytes") or 0) / (1024 ** 3)
        if total_gb > 0:
            return round(min(4.0, max(1.0, total_gb * 0.12)), 1)
    except Exception:
        pass
    return 4.0


STORE_NAME = "memory_advisor.json"
STORE_VERSION = 1
MODES = ("quiet", "advise", "early", "custom")
DEFAULTS = {"mode": "advise", "custom_headroom_gb": default_headroom_gb(),
            "remember_overrides": True, "overridden_models": []}
MAX_BYTES = 16 * 1024
MAX_OVERRIDES = 128
_LOCK = threading.RLock()


def _path(root: Path = ROOT) -> Path:
    return Path(root) / "data" / STORE_NAME


def normalize(value) -> dict:
    raw = value if isinstance(value, dict) else {}
    mode = str(raw.get("mode") or DEFAULTS["mode"]).strip().lower()
    if mode not in MODES:
        raise ValueError("mode must be quiet, advise, early, or custom")
    try:
        headroom = float(raw.get("custom_headroom_gb", DEFAULTS["custom_headroom_gb"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("custom headroom must be a number") from exc
    if not math.isfinite(headroom) or headroom < 0 or headroom > 256:
        raise ValueError("custom headroom must be between 0 and 256 GB")
    remember = raw.get("remember_overrides", DEFAULTS["remember_overrides"])
    if not isinstance(remember, bool):
        raise ValueError("remember_overrides must be true or false")
    model_ids = raw.get("overridden_models", [])
    if not isinstance(model_ids, list):
        raise ValueError("overridden_models must be a list")
    clean_ids = []
    for value in model_ids:
        if not isinstance(value, str) or not value.strip() or len(value) > 512:
            raise ValueError("overridden model ids must be non-empty strings")
        model_id = value.strip()
        if model_id not in clean_ids:
            clean_ids.append(model_id)
        if len(clean_ids) > MAX_OVERRIDES:
            raise ValueError(f"at most {MAX_OVERRIDES} overridden models may be remembered")
    return {"mode": mode, "custom_headroom_gb": round(headroom, 2),
            "remember_overrides": remember, "overridden_models": clean_ids}


def read(root: Path = ROOT) -> dict:
    with _LOCK:
        path = _path(root)
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                    raise ValueError("memory advisor preferences are not a small regular file")
                with os.fdopen(fd, encoding="utf-8") as handle:
                    fd = -1
                    value = json.load(handle)
            finally:
                if fd >= 0:
                    os.close(fd)
        except FileNotFoundError:
            return normalize(DEFAULTS)
        except (OSError, ValueError, json.JSONDecodeError):
            # A corrupt preference cannot turn advice into a wall.  The documented
            # default is the safest behavior; the next explicit save repairs it.
            return normalize(DEFAULTS)
        if not isinstance(value, dict) or value.get("version") != STORE_VERSION:
            return normalize(DEFAULTS)
        try:
            return normalize(value)
        except ValueError:
            return normalize(DEFAULTS)


def write(value, root: Path = ROOT) -> dict:
    prefs = normalize(value)
    with _LOCK:
        path = _path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            mode = path.lstat().st_mode
            if not stat.S_ISREG(mode):
                raise ValueError("refusing to replace a non-regular memory advisor file")
        except FileNotFoundError:
            pass
        payload = {"version": STORE_VERSION, **prefs}
        fd, raw = tempfile.mkstemp(prefix=".memory-advisor-", suffix=".tmp",
                                   dir=path.parent)
        temporary = Path(raw)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                fd = -1
                json.dump(payload, handle, indent=1, sort_keys=True)
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
    return prefs


def update(patch: dict, root: Path = ROOT, *, clear_overrides: bool = False) -> dict:
    """Atomically merge one UI preference update with any concurrent acknowledgement."""
    if not isinstance(patch, dict):
        raise ValueError("advisor settings must be an object")
    with _LOCK:
        current = read(root)
        merged = {**current, **patch}
        if clear_overrides or merged.get("remember_overrides") is False:
            merged["overridden_models"] = []
        return write(merged, root)


def acknowledge(model_id: str, root: Path = ROOT) -> dict:
    """Remember one explicit Load-anyway decision when that user policy is enabled."""
    model_id = str(model_id or "").strip()
    if not model_id or len(model_id) > 512:
        raise ValueError("model id is invalid")
    with _LOCK:
        current = read(root)
        if not current.get("remember_overrides"):
            return current
        rows = [value for value in current.get("overridden_models", [])
                if value != model_id]
        rows.append(model_id)
        current["overridden_models"] = rows[-MAX_OVERRIDES:]
        return write(current, root)


def apply_headroom(budget: dict, prefs: dict | None = None) -> dict:
    out = dict(budget or {})
    policy = prefs or read()
    base = max(0, int(out.get("budget_bytes") or 0))
    reserved = (int(float(policy.get("custom_headroom_gb") or 0) * 1024 ** 3)
                if policy.get("mode") == "custom" else 0)
    out["base_budget_bytes"] = base
    out["custom_headroom_bytes"] = min(base, max(0, reserved))
    out["budget_bytes"] = max(0, base - reserved)
    out["advisor_mode"] = policy.get("mode") or DEFAULTS["mode"]
    return out


def needs_confirmation(verdict: str, model_id: str = "",
                       prefs: dict | None = None) -> bool:
    policy = prefs or read()
    if (model_id and policy.get("remember_overrides")
            and model_id in policy.get("overridden_models", [])):
        return False
    mode = policy.get("mode")
    if mode == "quiet":
        return False
    if mode == "early":
        return verdict in ("tight", "over")
    return verdict == "over"             # Advise and Custom headroom
