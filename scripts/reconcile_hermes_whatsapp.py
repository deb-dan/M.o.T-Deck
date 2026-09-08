#!/usr/bin/env python3
"""Keep Hermes's WhatsApp enablement authorities in one recoverable transaction.

Hermes reads both ``config.yaml: platforms.whatsapp.enabled`` and
``.env: WHATSAPP_ENABLED``; an explicit env value wins. Its dashboard toggle currently
writes only YAML, so an onboarding-created ``WHATSAPP_ENABLED=true`` can resurrect a
channel the user disabled. An explicit M.O.T action aligns the two values without
touching pairing credentials or session files. Startup only rolls forward a journaled
interrupted action; it never guesses which mismatched authority expresses newer user
intent. A tiny desired-state journal makes a process crash between the two atomic
replacements recoverable on the next Hermes start.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

import yaml


JOURNAL = ".mot-whatsapp-state.json"
LOCK = ".mot-whatsapp-state.lock"


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _atomic_write(path: Path, payload: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _require_replaceable(path)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(raw)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # Recheck immediately before replacement. The process-local lock coordinates
        # every M.O.T writer; this second check also refuses a state-file symlink or
        # special file introduced after the initial read.
        _require_replaceable(path)
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        tmp.unlink(missing_ok=True)
        raise


@contextmanager
def _locked(home: Path):
    home.mkdir(parents=True, exist_ok=True)
    lock = home / LOCK
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError(f"WhatsApp state lock is not a regular file: {lock}")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _require_replaceable(path: Path) -> None:
    """Refuse links and special files at every M.O.T-owned state destination."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if not stat.S_ISREG(mode):
        raise ValueError(f"refusing non-regular WhatsApp state file: {path}")


def _read_optional(path: Path) -> bytes | None:
    """Read one regular file without following its final path component."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError(f"refusing non-regular WhatsApp state file: {path}")
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            return handle.read()
    finally:
        if fd >= 0:
            os.close(fd)


def _bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return None


def _config(raw: bytes | None) -> dict:
    if raw is None:
        return {}
    value = yaml.safe_load(raw.decode("utf-8"))
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Hermes config.yaml must contain a mapping")
    return value


def _config_enabled(data: dict) -> bool | None:
    platforms = data.get("platforms")
    whatsapp = platforms.get("whatsapp") if isinstance(platforms, dict) else None
    return _bool(whatsapp.get("enabled")) if isinstance(whatsapp, dict) else None


def _set_config_enabled(raw: bytes | None, enabled: bool) -> bytes:
    """Change only ``platforms.whatsapp.enabled`` without reserializing YAML.

    This is deliberately a narrow block editor, not a general YAML writer. Hermes's
    config is user-owned and a safe_dump round trip would reorder/retag unrelated
    values. Inline/aliased shapes are refused rather than silently expanded because
    preserving those faithfully needs a YAML round-trip dependency which the runtime
    does not guarantee.
    """
    text = (raw or b"").decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    value = "true" if enabled else "false"

    def indent(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def block_end(start: int, level: int) -> int:
        for idx in range(start + 1, len(lines)):
            stripped = lines[idx].strip()
            if stripped and not stripped.startswith("#") and indent(lines[idx]) <= level:
                return idx
        return len(lines)

    platform_rows = [i for i, line in enumerate(lines)
                     if re.match(r"^platforms:\s*(?:#.*)?(?:\r?\n)?$", line)]
    if len(platform_rows) > 1:
        raise ValueError("duplicate top-level platforms blocks are ambiguous")
    platform_at = platform_rows[0] if platform_rows else None
    if platform_at is None:
        # Refuse a non-block spelling such as ``platforms: {whatsapp: ...}`` instead
        # of appending a duplicate top-level key which PyYAML would resolve ambiguously.
        if any(re.match(r"^platforms\s*:", line) for line in lines):
            raise ValueError("platforms must use block YAML before WhatsApp can be reconciled")
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += newline
        lines.extend([f"platforms:{newline}", f"  whatsapp:{newline}",
                      f"    enabled: {value}{newline}"])
        return "".join(lines).encode("utf-8")

    platform_end = block_end(platform_at, 0)
    whatsapp_rows = [i for i in range(platform_at + 1, platform_end)
                     if re.match(r"^  whatsapp:\s*(?:#.*)?(?:\r?\n)?$", lines[i])]
    if len(whatsapp_rows) > 1:
        raise ValueError("duplicate platforms.whatsapp blocks are ambiguous")
    whatsapp_at = whatsapp_rows[0] if whatsapp_rows else None
    if whatsapp_at is None:
        if any(re.match(r"^  whatsapp\s*:", lines[i])
               for i in range(platform_at + 1, platform_end)):
            raise ValueError("platforms.whatsapp must use block YAML before it can be reconciled")
        lines[platform_end:platform_end] = [f"  whatsapp:{newline}",
                                            f"    enabled: {value}{newline}"]
        return "".join(lines).encode("utf-8")

    whatsapp_end = block_end(whatsapp_at, 2)
    enabled_rows = []
    for i in range(whatsapp_at + 1, whatsapp_end):
        match = re.match(r"^(    enabled:)\s*[^#\r\n]*(\s+#.*)?(\r?\n)?$", lines[i])
        if match:
            enabled_rows.append((i, match))
    if len(enabled_rows) > 1:
        raise ValueError("duplicate platforms.whatsapp.enabled keys are ambiguous")
    if enabled_rows:
        i, match = enabled_rows[0]
        comment = match.group(2) or ""
        ending = match.group(3) or ""
        lines[i] = f"    enabled: {value}{comment}{ending}"
        return "".join(lines).encode("utf-8")
    lines[whatsapp_end:whatsapp_end] = [f"    enabled: {value}{newline}"]
    return "".join(lines).encode("utf-8")


def _env_enabled(raw: bytes | None) -> bool | None:
    if raw is None:
        return None
    found = None
    for line in raw.decode("utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == "WHATSAPP_ENABLED":
            found = _bool(value.strip().strip("'\""))
    return found


def _set_env_enabled(raw: bytes | None, enabled: bool) -> bytes:
    text = (raw or b"").decode("utf-8")
    lines = text.splitlines(keepends=True)
    replacement = f"WHATSAPP_ENABLED={'true' if enabled else 'false'}\n"
    out: list[str] = []
    replaced = False
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
        if not stripped.startswith("#") and key == "WHATSAPP_ENABLED":
            if not replaced:
                out.append(replacement)
                replaced = True
            continue
        out.append(line)
    if not replaced:
        if out and not out[-1].endswith(("\n", "\r")):
            out[-1] += "\n"
        out.append(replacement)
    return "".join(out).encode()


def _mode(path: Path, default: int) -> int:
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode):
            raise ValueError(f"refusing non-regular WhatsApp state file: {path}")
        return stat.S_IMODE(mode)
    except FileNotFoundError:
        return default


def _restore(path: Path, raw: bytes | None, mode: int) -> None:
    if raw is None:
        path.unlink(missing_ok=True)
        _fsync_dir(path.parent)
    else:
        _atomic_write(path, raw, mode)


def _commit(home: Path, enabled: bool,
            writer: Callable[[Path, bytes, int], None] = _atomic_write,
            recovery_pending: bool = False) -> dict:
    config_path, env_path, journal_path = home / "config.yaml", home / ".env", home / JOURNAL
    config_raw = _read_optional(config_path)
    env_raw = _read_optional(env_path)
    config_mode, env_mode = _mode(config_path, 0o600), _mode(env_path, 0o600)
    data = _config(config_raw)
    config_next = _set_config_enabled(config_raw, enabled)
    env_next = _set_env_enabled(env_raw, enabled)
    if (_config_enabled(data) is enabled and _env_enabled(env_raw) is enabled
            and _read_optional(journal_path) is None):
        return {"ok": True, "changed": False, "enabled": enabled}

    journal = json.dumps({"version": 1, "enabled": enabled}, separators=(",", ":")).encode()
    if not recovery_pending:
        writer(journal_path, journal, 0o600)
    try:
        writer(config_path, config_next, config_mode)
        writer(env_path, env_next, 0o600)
        if _config_enabled(_config(_read_optional(config_path))) is not enabled:
            raise RuntimeError("config.yaml verification failed")
        if _env_enabled(_read_optional(env_path)) is not enabled:
            raise RuntimeError(".env verification failed")
    except BaseException:
        # A new transaction can restore its captured originals. During crash recovery
        # those bytes may already be a partial prior write, so they are not a rollback
        # authority: retain the journal and retry the same desired state next start.
        if recovery_pending:
            _fsync_dir(home)
            raise
        try:
            _restore(config_path, config_raw, config_mode)
            _restore(env_path, env_raw, env_mode)
            journal_path.unlink(missing_ok=True)
            _fsync_dir(home)
        except BaseException:
            pass
        raise
    journal_path.unlink(missing_ok=True)
    _fsync_dir(home)
    return {"ok": True, "changed": True, "enabled": enabled}


def reconcile(home: Path, desired: bool,
              writer: Callable[[Path, bytes, int], None] = _atomic_write) -> dict:
    home = home.expanduser().resolve()
    with _locked(home):
        journal_path = home / JOURNAL
        journal_raw = _read_optional(journal_path)
        if journal_raw is not None:
            pending = json.loads(journal_raw.decode("utf-8"))
            if pending.get("version") != 1 or not isinstance(pending.get("enabled"), bool):
                raise ValueError(f"invalid WhatsApp recovery journal: {journal_path}")
            _commit(home, pending["enabled"], writer, recovery_pending=True)
        # Recovery completes the previous action; it must not consume the new
        # enable/disable request and report the opposite state as its success.
        return _commit(home, desired, writer)


def recover(home: Path,
            writer: Callable[[Path, bytes, int], None] = _atomic_write) -> dict:
    """Finish only a recorded M.O.T transaction; never infer intent from drift."""
    home = home.expanduser().resolve()
    with _locked(home):
        journal_path = home / JOURNAL
        journal_raw = _read_optional(journal_path)
        if journal_raw is None:
            return {"ok": True, "changed": False, "recovery_pending": False}
        pending = json.loads(journal_raw.decode("utf-8"))
        if pending.get("version") != 1 or not isinstance(pending.get("enabled"), bool):
            raise ValueError(f"invalid WhatsApp recovery journal: {journal_path}")
        return _commit(home, pending["enabled"], writer, recovery_pending=True)


def status(home: Path) -> dict:
    home = home.expanduser().resolve()
    with _locked(home):
        cp, ep = home / "config.yaml", home / ".env"
        yaml_value = _config_enabled(_config(_read_optional(cp)))
        env_value = _env_enabled(_read_optional(ep))
        return {"ok": True, "config_enabled": yaml_value, "env_enabled": env_value,
                "aligned": yaml_value is not None and yaml_value is env_value,
                "recovery_pending": _read_optional(home / JOURNAL) is not None}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, default=Path.home() / ".hermes")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--recover", action="store_true")
    group.add_argument("--set", choices=("enabled", "disabled"))
    group.add_argument("--status", action="store_true")
    args = parser.parse_args()
    if args.status:
        result = status(args.home)
    elif args.recover:
        result = recover(args.home)
    else:
        result = reconcile(args.home, args.set == "enabled")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
