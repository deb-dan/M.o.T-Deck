"""Safety and reversible persistence boundary for app-owned model deletion."""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from pathlib import Path
from typing import Callable

from .modelreg import registry_lock, write_registry

DELETABLE_SOURCES = ("download", "local")
DELETE_JOURNAL = ".mot-delete-journal.json"
Assignment = tuple[str, str, Callable[[], None], Callable[[], None]]
AssignmentResolver = Callable[[str, str], tuple[Callable[[], None], Callable[[], None]]]


def deletable_target(entry: dict, models_root: str) -> tuple[str | None, str | None]:
    """Resolve the one top-level app-owned target, or return a refusal reason.

    Both lexical and resolved containment matter. Lexical containment rejects
    traversal before resolution; resolved containment rejects escapes; and every
    existing component below the models root is checked explicitly so an in-root
    symlink cannot redirect deletion into another app-owned folder.
    """
    source = (entry or {}).get("source")
    if source not in DELETABLE_SOURCES:
        return None, (f"'{source or 'unknown'}' models are read-only imports MOT Deck "
                      "does not own — remove them in the app that manages them")
    path = (entry or {}).get("path")
    if not path:
        return None, "no file path on record for this model"

    lexical_root = os.path.abspath(os.path.expanduser(str(models_root)))
    lexical_path = os.path.abspath(os.path.expanduser(str(path)))
    if lexical_path != lexical_root and not lexical_path.startswith(lexical_root + os.sep):
        return None, "model path is outside MOT Deck models directory"
    relative = os.path.relpath(lexical_path, lexical_root)
    current = lexical_root
    for part in relative.split(os.sep):
        current = os.path.join(current, part)
        if os.path.lexists(current) and os.path.islink(current):
            return None, ("model path contains a symbolic link; deletion requires a "
                          "direct app-owned path")

    real_root = os.path.realpath(lexical_root)
    real_path = os.path.realpath(lexical_path)
    if real_path != real_root and not real_path.startswith(real_root + os.sep):
        return None, "model path is outside MOT Deck models directory"
    first = os.path.relpath(real_path, real_root).split(os.sep)[0]
    if first in ("", ".", ".."):
        return None, "could not resolve a model target under the models directory"
    return os.path.join(real_root, first), None


def delete_target_collisions(models: list, mid: str, target: str) -> list[str]:
    """Return every other registry ID whose recorded path overlaps ``target``."""
    real_target = os.path.realpath(target)
    collisions = []
    for other in models or []:
        if not isinstance(other, dict) or other.get("id") == mid or not other.get("path"):
            continue
        other_path = os.path.realpath(os.path.expanduser(str(other["path"])))
        if (other_path == real_target
                or other_path.startswith(real_target + os.sep)
                or real_target.startswith(other_path + os.sep)):
            collisions.append(str(other.get("id") or "<unnamed>"))
    return sorted(set(collisions))


def _fsync_directory(path: str) -> None:
    """Best-effort persistence barrier for folder rename/delete metadata."""
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _require_regular(path: Path, *, absent_ok: bool = False) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        if absent_ok:
            return
        raise
    if not stat.S_ISREG(mode):
        raise ValueError(f"refusing non-regular model deletion journal: {path}")


def _read_journal(path: Path) -> dict | None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 16 * 1024 * 1024:
            raise ValueError(f"invalid model deletion journal: {path}")
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            value = json.load(handle)
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(value, dict):
        raise ValueError(f"invalid model deletion journal: {path}")
    return value


def _write_journal(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":")) + "\n").encode("utf-8")
    fd, raw = tempfile.mkstemp(prefix=".mot-delete-", suffix=".tmp", dir=path.parent)
    temporary: Path | None = Path(raw)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _require_regular(path, absent_ok=True)
        os.replace(temporary, path)
        temporary = None
        _fsync_directory(str(path.parent))
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _remove_journal(path: Path) -> None:
    _require_regular(path)
    path.unlink()
    _fsync_directory(str(path.parent))


def _direct_child(models_root: str, value: object, *, quarantine: bool) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("model deletion journal has an invalid path")
    root = os.path.realpath(models_root)
    path = os.path.abspath(value)
    if os.path.dirname(path) != root:
        raise ValueError("model deletion journal path escaped the models directory")
    name = os.path.basename(path)
    if quarantine and not name.startswith(".deleting-"):
        raise ValueError("model deletion journal has an invalid quarantine path")
    if not quarantine and name.startswith(".deleting-"):
        raise ValueError("model deletion journal has an invalid target path")
    return path


def _validated_journal(value: dict, models_root: str) -> dict:
    if value.get("version") != 1 or not isinstance(value.get("model_id"), str) \
            or not value["model_id"]:
        raise ValueError("model deletion journal has an invalid identity")
    target = _direct_child(models_root, value.get("target"), quarantine=False)
    quarantine = _direct_child(models_root, value.get("quarantine"), quarantine=True)
    if target == quarantine or not isinstance(value.get("artifact_existed"), bool):
        raise ValueError("model deletion journal has an invalid artifact state")
    registry_entry = value.get("registry_entry")
    if not isinstance(registry_entry, dict) \
            or registry_entry.get("id") != value["model_id"]:
        raise ValueError("model deletion journal has an invalid registry preimage")
    assignments = value.get("assignments")
    if not isinstance(assignments, list) or any(
            not isinstance(row, dict) or not isinstance(row.get("label"), str)
            or not row["label"] or not isinstance(row.get("old"), str)
            for row in assignments):
        raise ValueError("model deletion journal has invalid saved assignments")
    return {**value, "target": target, "quarantine": quarantine}


def _remove_quarantine(path: str) -> None:
    mode = os.lstat(path).st_mode
    if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
        raise ValueError(f"refusing unexpected quarantine object: {path}")
    if stat.S_ISDIR(mode):
        shutil.rmtree(path)
    else:
        os.unlink(path)


def recover_owned_model_transaction(*, root: Path,
                                    assignment_resolver: AssignmentResolver) -> str | None:
    """Resolve a crash-interrupted delete from durable filesystem/registry evidence.

    An atomic registry replacement is the commit boundary. If the old row remains, the
    artifact and assignments roll back. If the row is absent, assignments are cleared
    and quarantine cleanup rolls forward. The journal is removed only after the chosen
    state is complete and fsynced.
    """
    models_root = str(root / "data" / "models")
    registry_path = root / "data" / "models.json"
    journal_path = Path(models_root) / DELETE_JOURNAL
    try:
        with registry_lock(str(registry_path)):
            raw = _read_journal(journal_path)
            if raw is None:
                return None
            journal = _validated_journal(raw, models_root)
            try:
                registry = json.loads(registry_path.read_text())
            except Exception as exc:
                raise RuntimeError(f"model registry cannot be read during recovery: {exc}") from exc
            rows = registry.get("models") if isinstance(registry, dict) else None
            if not isinstance(rows, list):
                raise RuntimeError("model registry has an invalid shape during recovery")
            matching = [row for row in rows if isinstance(row, dict)
                        and row.get("id") == journal["model_id"]]
            if len(matching) > 1:
                raise RuntimeError("model registry contains duplicate deletion identities")
            if matching and matching[0] != journal["registry_entry"]:
                raise RuntimeError("model identity was reused with a different registry row")
            row_present = bool(matching)
            target, quarantine = journal["target"], journal["quarantine"]

            if row_present:
                if journal["artifact_existed"]:
                    if os.path.lexists(target):
                        if os.path.islink(target):
                            raise RuntimeError("model target became a symbolic link during recovery")
                        if os.path.lexists(quarantine):
                            raise RuntimeError("both model target and quarantine exist during recovery")
                    elif os.path.lexists(quarantine):
                        if os.path.islink(quarantine):
                            raise RuntimeError("model quarantine became a symbolic link during recovery")
                        os.replace(quarantine, target)
                        _fsync_directory(models_root)
                    else:
                        raise RuntimeError("model artifact and quarantine are both missing during rollback")
                elif os.path.lexists(quarantine):
                    raise RuntimeError("unexpected quarantine exists for an originally absent artifact")
                for saved in journal["assignments"]:
                    _clear, restore = assignment_resolver(saved["label"], saved["old"])
                    restore()
            else:
                for saved in journal["assignments"]:
                    clear, _restore = assignment_resolver(saved["label"], saved["old"])
                    clear()
                if os.path.lexists(quarantine):
                    _remove_quarantine(quarantine)
                    _fsync_directory(models_root)
            _remove_journal(journal_path)
    except Exception as exc:  # noqa: BLE001 -- journal must remain visible/retryable
        return f"model deletion recovery requires attention: {exc}"
    return None


def delete_owned_model_transaction(*, root: Path, mid: str, expected_target: str,
                                   assignments: list[Assignment],
                                   crash_hook: Callable[[str], None] | None = None) -> str | None:
    """Remove one owned target plus its row and assignments, with rollback.

    ``assignments`` contains ``(label, clear, restore)`` callbacks. Returns ``None``
    only after the artifact, registry row, and assignments have all committed; every
    failure returns an honest diagnostic after attempting to restore each changed
    persistence object.

    POSIX has no atomic recursive-directory deletion. The target is first renamed on
    the same filesystem, making all earlier operations reversible. If recursive
    cleanup fails part-way, the remaining tree is restored but must be revalidated.
    """
    models_root = str(root / "data" / "models")
    real_root = os.path.realpath(models_root)
    registry_path = root / "data" / "models.json"
    journal_path = Path(models_root) / DELETE_JOURNAL
    quarantine = ""
    registry_before = None
    registry_changed = False
    changed_assignments: list[Assignment] = []
    cleanup_started = False
    journal_written = False
    crash_hook = crash_hook or (lambda _stage: None)
    try:
        with registry_lock(str(registry_path)):
            # Keep the preimage restoration inside the same transaction as removal.
            # Releasing this lock before rollback could erase a concurrent writer.
            try:
                try:
                    registry_before = json.loads(registry_path.read_text())
                except Exception as exc:
                    raise RuntimeError(f"model registry cannot be read: {exc}") from exc
                if (not isinstance(registry_before, dict)
                        or not isinstance(registry_before.get("models"), list)):
                    raise RuntimeError("model registry has an invalid shape")
                entry = next((row for row in registry_before["models"]
                              if isinstance(row, dict) and row.get("id") == mid), None)
                if entry is None:
                    raise RuntimeError(f"model '{mid}' changed or disappeared during deletion")
                target, reason = deletable_target(entry, models_root)
                if target != expected_target:
                    raise RuntimeError(reason or "model path changed during deletion")
                collisions = delete_target_collisions(registry_before["models"], mid, target)
                if collisions:
                    raise RuntimeError("filesystem target became shared by: "
                                       + ", ".join(collisions))

                if _read_journal(journal_path) is not None:
                    raise RuntimeError("a prior model deletion requires recovery before another can start")
                artifact_existed = os.path.lexists(target)
                safe_id = re.sub(r"[^A-Za-z0-9._-]", "-", mid)[:48] or "model"
                quarantine = os.path.join(
                    real_root, f".deleting-{safe_id}-{uuid.uuid4().hex}")
                journal = {
                    "version": 1,
                    "model_id": mid,
                    "registry_entry": entry,
                    "target": target,
                    "quarantine": quarantine,
                    "artifact_existed": artifact_existed,
                    "assignments": [{"label": label, "old": old}
                                    for label, old, _clear, _restore in assignments],
                }
                _write_journal(journal_path, journal)
                journal_written = True
                crash_hook("journal")

                if artifact_existed:
                    os.replace(target, quarantine)
                    _fsync_directory(real_root)
                crash_hook("quarantine")

                registry_after = dict(registry_before)
                registry_after["models"] = [row for row in registry_before["models"]
                                            if not (isinstance(row, dict)
                                                    and row.get("id") == mid)]
                write_registry(str(registry_path), registry_after)
                registry_changed = True
                crash_hook("registry")

                for assignment in assignments:
                    # Record before invoking so rollback is attempted even if a writer
                    # replaces its file and then raises during a durability barrier.
                    changed_assignments.append(assignment)
                    assignment[2]()
                crash_hook("assignments")

                if artifact_existed and quarantine:
                    cleanup_started = True
                    if os.path.isdir(quarantine) and not os.path.islink(quarantine):
                        shutil.rmtree(quarantine)
                    else:
                        os.unlink(quarantine)
                    quarantine = ""
                    _fsync_directory(real_root)
                crash_hook("cleanup")
                _remove_journal(journal_path)
                journal_written = False
            except Exception as exc:  # noqa: BLE001 - persistence failures must rollback/report
                rollback_errors = []
                if quarantine and os.path.lexists(quarantine) and not os.path.lexists(expected_target):
                    try:
                        os.replace(quarantine, expected_target)
                        quarantine = ""
                        _fsync_directory(real_root)
                    except Exception as rollback_exc:  # noqa: BLE001
                        rollback_errors.append(f"artifact restore failed: {rollback_exc}")
                if registry_changed and registry_before is not None:
                    try:
                        write_registry(str(registry_path), registry_before)
                    except Exception as rollback_exc:  # noqa: BLE001
                        rollback_errors.append(f"registry restore failed: {rollback_exc}")
                for label, _old, _clear, restore in reversed(changed_assignments):
                    try:
                        restore()
                    except Exception as rollback_exc:  # noqa: BLE001
                        rollback_errors.append(f"{label} restore failed: {rollback_exc}")
                if journal_written and not rollback_errors:
                    try:
                        _remove_journal(journal_path)
                        journal_written = False
                    except Exception as rollback_exc:  # noqa: BLE001
                        rollback_errors.append(f"journal retirement failed: {rollback_exc}")
                detail = f"delete failed; registry and saved assignments were restored: {exc}"
                if cleanup_started:
                    detail += ("; physical cleanup had begun, so the restored artifact path "
                               "must be revalidated before loading")
                if rollback_errors:
                    detail += "; ATTENTION — " + "; ".join(rollback_errors)
                return detail
    except Exception as exc:  # lock acquisition failed before any state was changed
        return f"delete could not acquire the model registry transaction: {exc}"
    return None
