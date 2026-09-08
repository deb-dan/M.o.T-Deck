"""Ownership-safe runtime removal plans for MOT Deck.

This module deliberately owns *runtime* removal only.  User state, workspaces,
documents, outputs, model weights, and shared homes are not inferred from an install
directory and are never included in a normal component uninstall.

The transaction is recoverable: exact lexical targets are renamed into one batch in
the user's Trash, and a failure rolls already-moved entries back.  We do not copy and
delete across filesystems.  A preview fingerprint must still match immediately before
the first rename.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time
from typing import Iterable

from ..yamlfile import transform_file


PLAN_TTL_S = 10 * 60


@dataclass(frozen=True)
class RuntimeSpec:
    label: str
    paths: tuple[str, ...]
    preserve: tuple[str, ...]
    manifest_component: str = ""
    stop_component: str = ""
    depends_on: tuple[str, ...] = ()
    note: str = ""


# Exact, code-audited installer outputs.  Do not broaden these entries to parent
# directories merely because a future installer happens to place another file nearby.
RUNTIME_SPECS: dict[str, RuntimeSpec] = {
    "hermes": RuntimeSpec("Hermes", ("data/hermes-venv",),
        ("~/.hermes (shared standalone home)",), "hermes", "hermes"),
    "odysseus": RuntimeSpec("Odysseus", ("data/odysseus-venv",),
        ("vendor/odysseus/data (sessions, uploads and settings)",),
        "odysseus", "odysseus"),
    "searxng": RuntimeSpec("SearXNG", ("data/searxng-venv",),
        ("data/searxng/settings.yml",), "searxng", "searxng"),
    "voicestudio": RuntimeSpec("VoiceStudio", ("data/voicestudio-venv",),
        ("vendor/voicestudio source/build tree",
         "~/Library/Application Support/OmniVoice (profiles, outputs and settings)",
         "shared Hugging Face model cache", "shared data/bun", "shared data/ffmpeg"),
        "voicestudio", "voicestudio"),
    "voicebox": RuntimeSpec("Voicebox", ("data/voicebox-venv",),
        ("vendor/voicebox source/build tree", "data/voicebox (profiles, outputs and settings)",
         "shared Hugging Face model cache", "shared data/bun", "shared data/ffmpeg"),
        "voicebox", "voicebox"),
    "comfyui": RuntimeSpec("ComfyUI", ("data/comfyui-venv",),
        ("vendor/comfyui source/build tree and custom nodes", "data/comfyui/models",
         "data/comfyui/input", "data/comfyui/output", "user workflows"),
        "comfyui", "comfyui"),
    "unsloth": RuntimeSpec("Unsloth", ("data/unsloth-home/unsloth_studio",),
        ("vendor/unsloth source/build tree",
         "the rest of data/unsloth-home (models, runs and settings)"),
        "unsloth", "unsloth"),
    "opencode": RuntimeSpec("OpenCode", ("data/opencode/bin/opencode",),
        ("data/opencode/xdg", "data/opencode-workspace"),
        "opencode", "opencode"),
    "deepseek": RuntimeSpec("DeepSeek", ("data/deepseek/npm",),
        ("data/deepseek/home", "data/deepseek-workspace"),
        "deepseek", "deepseek"),
    "aider": RuntimeSpec("Aider", ("data/aider-venv",),
        ("vendor/aider source checkout", "data/aider-workspace"),
        note="Aider has no persistent component daemon."),
    "gooseui": RuntimeSpec("Goose UI", (
        "data/goose/ui", "data/goose/ui.sha256", "data/goose/UI-SOURCES.txt",
        "data/goose/UI-INSTALLED"),
        ("data/goose/ui-home", "shared data/goose/bin/goose", "data/goose/home",
         "data/goose-workspace")),
    "goose": RuntimeSpec("Goose CLI", (
        "data/goose/bin/goose", "data/goose/INSTALLED", "data/goose/SOURCES.txt"),
        ("data/goose/home", "data/goose-workspace", "data/goose/ui-home"),
        depends_on=("gooseui",),
        note="Goose UI depends on the same binary; remove Goose UI first."),
    "loffice": RuntimeSpec("LOffice rich editor", (
        "data/onlyoffice", "data/onlyoffice-plugins"),
        ("data/office", "LOffice documents, backups and exports")),
    "acestep": RuntimeSpec("ACE-Step integration", ("data/acestep",),
        ("shared Hugging Face cache weights", "Music library and outputs"),
        note="This removes the local build/integration, not shared cached weights."),
}


class StorageRefusal(RuntimeError):
    """A deletion plan or transaction could not prove its authority."""


def _lexical_under(root: Path, rel: str) -> Path:
    """Join a literal repo-relative target without following its final component."""
    if not isinstance(rel, str) or not rel or os.path.isabs(rel):
        raise StorageRefusal("runtime target is not a non-empty relative path")
    root = Path(os.path.abspath(root))
    target = Path(os.path.abspath(root / rel))
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise StorageRefusal(f"runtime target escapes the MOT Deck root: {rel}") from exc
    if target == root:
        raise StorageRefusal("the MOT Deck root is not a component runtime target")
    return target


def _entry_evidence(path: Path) -> dict:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return {"path": str(path), "state": "absent"}
    kind = "symlink" if stat.S_ISLNK(st.st_mode) else (
        "directory" if stat.S_ISDIR(st.st_mode) else "file")
    row = {"path": str(path), "state": "present", "kind": kind,
            "dev": int(st.st_dev), "ino": int(st.st_ino),
            "size": int(st.st_size), "mtime_ns": int(st.st_mtime_ns)}
    if kind == "symlink":
        row["link"] = os.readlink(path)
    elif kind == "directory":
        row["tree"] = _tree_signature(path)
    return row


def _tree_signature(path: Path) -> str:
    """Bind a preview to every entry without hashing multi-gigabyte payload bytes.

    Relative path + no-follow type/size/mtime/inode is enough to detect the tree
    changing between a human preview and the immediately following apply. It is not
    advertised as a content-integrity digest.
    """
    rows: list[tuple] = []
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            entries = sorted(os.scandir(cur), key=lambda ent: ent.name)
        except OSError as exc:
            raise StorageRefusal(f"cannot inventory runtime directory {cur}: {exc}") from exc
        for ent in entries:
            try:
                est = ent.stat(follow_symlinks=False)
            except OSError as exc:
                raise StorageRefusal(f"cannot inspect runtime entry {ent.path}: {exc}") from exc
            mode = stat.S_IFMT(est.st_mode)
            rel = os.path.relpath(ent.path, path)
            link = os.readlink(ent.path) if stat.S_ISLNK(est.st_mode) else ""
            rows.append((rel, mode, int(est.st_size), int(est.st_mtime_ns),
                         int(est.st_dev), int(est.st_ino), link))
            if stat.S_ISDIR(est.st_mode) and not stat.S_ISLNK(est.st_mode):
                stack.append(Path(ent.path))
    raw = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _tree_bytes(path: Path) -> int:
    """Best-effort allocated payload size without following any symlink."""
    try:
        st = os.lstat(path)
    except OSError:
        return 0
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        return int(st.st_size)
    total = 0
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for ent in it:
                    try:
                        est = ent.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    total += int(est.st_size)
                    if stat.S_ISDIR(est.st_mode) and not stat.S_ISLNK(est.st_mode):
                        stack.append(Path(ent.path))
        except OSError:
            continue
    return total


def _fingerprint(operation: str, target: str, evidence: Iterable[dict]) -> str:
    payload = {"operation": operation, "target": target,
               "evidence": list(evidence)}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _absolute_child(parent: Path, child: Path) -> Path:
    """Return one lexical child of ``parent`` without resolving symlinks.

    Removal authority is about the directory entry named in the preview. Resolving the
    final component would turn a symlink into authority over its destination, which is
    precisely the escape this module must avoid.
    """
    parent = Path(os.path.abspath(parent))
    child = Path(os.path.abspath(child))
    try:
        child.relative_to(parent)
    except ValueError as exc:
        raise StorageRefusal(f"removal target escapes its owned root: {child}") from exc
    if child == parent:
        raise StorageRefusal(f"an owned root itself is not an artifact target: {parent}")
    return child


def _is_absolute_child(parent: Path, child: Path) -> bool:
    try:
        _absolute_child(parent, child)
        return True
    except StorageRefusal:
        return False


def artifact_plan(operation: str, target: str, label: str,
                  paths: Iterable[Path], *, owned_roots: Iterable[Path],
                  preserve: Iterable[str] = (), note: str = "",
                  impact: Iterable[dict] = ()) -> dict:
    """Build a removal plan for exact files/directories under explicit owned roots.

    Unlike component runtimes, media artifacts may live in ComfyUI's model tree or a
    shared Hugging Face repository cache outside the MOT Deck root. The caller must
    therefore provide the exact roots whose ownership it has proved; no home-directory
    or cache-wide fallback is accepted.
    """
    roots = tuple(Path(os.path.abspath(p)) for p in owned_roots)
    if not roots or any(p == Path(p.anchor) or p == Path.home() for p in roots):
        raise StorageRefusal("artifact removal has no narrow owned root")
    exact: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        candidate = Path(os.path.abspath(raw))
        if candidate in roots:
            raise StorageRefusal(f"an owned root itself is not an artifact target: {candidate}")
        if not any(_is_absolute_child(root, candidate) for root in roots):
            raise StorageRefusal(f"artifact is outside every owned root: {candidate}")
        key = str(candidate)
        if key not in seen:
            exact.append(candidate)
            seen.add(key)
    evidence = [_entry_evidence(path) for path in exact]
    present = [row for row in evidence if row["state"] == "present"]
    return {
        "operation": operation, "target": target, "label": label,
        "paths": evidence, "owned_roots": [str(p) for p in roots],
        "bytes": sum(_tree_bytes(Path(row["path"])) for row in present),
        "preserve": list(preserve), "note": note, "impact": list(impact),
        "fingerprint": _fingerprint(operation, target, evidence),
        "reversible": True, "space_reclaimed_after_trash_empty": True,
    }


def verify_artifact_plan(plan: dict) -> None:
    roots = [Path(p) for p in plan.get("owned_roots") or []]
    paths = [Path(row["path"]) for row in plan.get("paths") or []]
    fresh = artifact_plan(
        str(plan.get("operation") or ""), str(plan.get("target") or ""),
        str(plan.get("label") or ""), paths, owned_roots=roots,
        preserve=plan.get("preserve") or (), note=str(plan.get("note") or ""),
        impact=plan.get("impact") or (),
    )
    if fresh["fingerprint"] != plan.get("fingerprint"):
        raise StorageRefusal("the artifacts changed after preview; review a fresh plan")


def apply_artifact_plan(plan: dict, *, trash_root: Path | None = None) -> dict:
    """Move exact artifact entries to one Trash batch, rolling back every rename."""
    verify_artifact_plan(plan)
    present = [Path(row["path"]) for row in plan["paths"] if row["state"] == "present"]
    trash_root = Path(trash_root) if trash_root is not None else Path.home() / ".Trash"
    batch = _safe_batch_dir(trash_root, plan.get("target") or "artifacts")
    moved: list[tuple[Path, Path]] = []
    try:
        for idx, src in enumerate(present):
            dst = batch / f"{idx:02d}-{src.name}"
            os.replace(src, dst)
            moved.append((src, dst))
    except Exception:
        for src, dst in reversed(moved):
            try:
                src.parent.mkdir(parents=True, exist_ok=True)
                os.replace(dst, src)
            except Exception:
                pass
        try:
            batch.rmdir()
        except OSError:
            pass
        raise
    if not moved:
        try:
            batch.rmdir()
        except OSError:
            pass
    return {"ok": True, "operation": plan["operation"], "target": plan["target"],
            "moved": len(moved), "trash": str(batch) if moved else "",
            "preserved": list(plan.get("preserve") or []),
            "impact": list(plan.get("impact") or []), "space_reclaimed": False}


def runtime_installed(root: Path, target: str) -> bool:
    spec = RUNTIME_SPECS.get(target)
    if spec is None:
        return False
    return any(os.path.lexists(_lexical_under(root, rel)) for rel in spec.paths)


def runtime_plan(root: Path, target: str) -> dict:
    spec = RUNTIME_SPECS.get(str(target or "").strip().lower())
    if spec is None:
        raise StorageRefusal("unknown runtime target")
    target = str(target).strip().lower()
    if target == "goose" and runtime_installed(root, "gooseui"):
        raise StorageRefusal(spec.note)
    evidence = [_entry_evidence(_lexical_under(root, rel)) for rel in spec.paths]
    present = [row for row in evidence if row["state"] == "present"]
    return {
        "operation": "uninstall-runtime", "target": target, "label": spec.label,
        "paths": evidence, "bytes": sum(_tree_bytes(Path(r["path"])) for r in present),
        "preserve": list(spec.preserve), "manifest_component": spec.manifest_component,
        "stop_component": spec.stop_component, "note": spec.note,
        "fingerprint": _fingerprint("uninstall-runtime", target, evidence),
        "reversible": True, "space_reclaimed_after_trash_empty": True,
    }


def verify_runtime_plan(root: Path, plan: dict) -> None:
    fresh = runtime_plan(root, plan.get("target") or "")
    if fresh["fingerprint"] != plan.get("fingerprint"):
        raise StorageRefusal("the runtime changed after preview; review a fresh plan")


def _safe_batch_dir(trash_root: Path, label: str) -> Path:
    trash_root = Path(trash_root)
    if not trash_root.is_dir() or trash_root.is_symlink():
        raise StorageRefusal("the current user's Trash directory is unavailable")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-") or "runtime"
    for _ in range(10):
        out = trash_root / f"MOT-Deck-{slug}-{stamp}-{secrets.token_hex(3)}"
        try:
            out.mkdir(mode=0o700)
            return out
        except FileExistsError:
            continue
    raise StorageRefusal("could not reserve a unique recovery folder in Trash")


def _replace_installed(text: str, component: str, value: bool) -> str:
    """Line-preserving update of one `components.<name>.installed` scalar."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines)
                  if re.match(rf"^  {re.escape(component)}:\s*(?:#.*)?$", line.rstrip("\n"))), -1)
    if start < 0:
        raise StorageRefusal(f"motdeck.yaml has no components.{component} block")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^(?:  [A-Za-z0-9_-]+:|\S)", lines[i]) and not lines[i].startswith("    "):
            end = i
            break
    for i in range(start + 1, end):
        m = re.match(r"^(\s{4}installed:\s*)(?:true|false)(.*)$", lines[i].rstrip("\n"))
        if m:
            nl = "\n" if lines[i].endswith("\n") else ""
            lines[i] = m.group(1) + ("true" if value else "false") + m.group(2) + nl
            return "".join(lines)
    raise StorageRefusal(f"components.{component}.installed is missing")


def set_manifest_installed(manifest: Path, component: str, value: bool) -> None:
    transform_file(manifest, lambda text: _replace_installed(text, component, value))


def apply_runtime_plan(root: Path, plan: dict, *, trash_root: Path | None = None) -> dict:
    """Move the exact previewed runtime targets to Trash, rolling back on failure."""
    verify_runtime_plan(root, plan)
    present = [Path(row["path"]) for row in plan["paths"] if row["state"] == "present"]
    trash_root = Path(trash_root) if trash_root is not None else Path.home() / ".Trash"
    batch = _safe_batch_dir(trash_root, plan.get("target") or "runtime")
    moved: list[tuple[Path, Path]] = []
    try:
        for idx, src in enumerate(present):
            dst = batch / f"{idx:02d}-{src.name}"
            os.replace(src, dst)  # fails closed on cross-device moves
            moved.append((src, dst))
        component = str(plan.get("manifest_component") or "")
        if component:
            set_manifest_installed(Path(root) / "motdeck.yaml", component, False)
    except Exception:
        for src, dst in reversed(moved):
            try:
                src.parent.mkdir(parents=True, exist_ok=True)
                os.replace(dst, src)
            except Exception:
                pass
        try:
            batch.rmdir()
        except OSError:
            pass
        raise
    if not moved:
        try:
            batch.rmdir()
        except OSError:
            pass
        batch_out = ""
    else:
        batch_out = str(batch)
    return {"ok": True, "target": plan["target"], "moved": len(moved),
            "trash": batch_out, "preserved": list(plan.get("preserve") or []),
            "space_reclaimed": False}
