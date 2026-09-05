#!/usr/bin/env python3
"""Repair generated venv pointers after this checkout is copied to a new root.

Only exact ``ROOT/data/<name>`` directories explicitly named by the caller participate.
The repair never follows a link while deciding what it may rewrite, delete, or import.
"""
from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


class RepairError(RuntimeError):
    """A refusal that leaves every planned source untouched or restored."""


# The start delimiter admits shebangs, shell assignments, and quoted Python maps while
# allowing spaces in a checkout name.  The matched path stops exactly at /data/*-venv.
_VENV_PATH = re.compile(
    r"(?P<lead>(?:^|[\s'\"=(:,#!]))(?P<path>/(?:[^\n'\"\x00]*?)/data/"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*-venv))(?=$|[/\s'\",:)])", re.MULTILINE)
_VENDOR_PATH = re.compile(
    r"(?P<lead>(?:^|['\"]))(?P<path>/(?:[^\n'\"\x00]*?)/vendor/"
    r"(?P<suffix>[A-Za-z0-9_.@+-]+(?:/[A-Za-z0-9_.@+-]+)*))(?=$|['\",:)])")
_STANDARD_PYTHON_LINK = re.compile(r"python(?:3(?:\.\d+)?)?$")


@dataclass
class Change:
    path: str
    original: bytes
    replacement: bytes
    mode: int
    kind: str


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def _regular(path: str, what: str) -> os.stat_result:
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise RepairError(f"refusing symlink {what}: {path}")
    if not stat.S_ISREG(info.st_mode):
        raise RepairError(f"refusing non-regular {what}: {path}")
    return info


def _text(path: str, what: str) -> Tuple[str, bytes, os.stat_result]:
    info = _regular(path, what)
    raw = open(path, "rb").read()
    if b"\0" in raw:
        raise RepairError(f"refusing binary {what}: {path}")
    try:
        return raw.decode("utf-8"), raw, info
    except UnicodeDecodeError as exc:
        raise RepairError(f"refusing non-UTF-8 {what}: {path}") from exc


def _venvs(root: str, owned_names: Iterable[str]) -> List[Tuple[str, str]]:
    """Return only explicitly declared, direct app-owned venv directories."""
    data = os.path.join(root, "data")
    if os.path.islink(data) or not os.path.isdir(data):
        raise RepairError(f"root has no direct, non-symlink data directory: {data}")
    found: List[Tuple[str, str]] = []
    for name in sorted(set(owned_names)):
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*-venv", name)
                or os.path.basename(name) != name):
            raise RepairError(f"invalid owned venv name: {name!r}")
        path = os.path.join(data, name)
        try:
            mode = os.lstat(path).st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise RepairError(f"refusing symlink venv directory: {path}")
        if not stat.S_ISDIR(mode):
            raise RepairError(f"owned venv path is not a directory: {path}")
        cfg = os.path.join(path, "pyvenv.cfg")
        if not os.path.isfile(cfg) or os.path.islink(cfg):
            raise RepairError(f"owned venv has no direct pyvenv.cfg: {path}")
        found.append((name, path))
    return sorted(found)


def _generated_console_line(line: str, match: re.Match[str]) -> bool:
    """Recognize only virtualenv/uv launcher and activation assignment shapes.

    An explicitly owned venv is necessary but not sufficient authority to rewrite an
    arbitrary string in ``bin``.  The stale root must occupy one of the exact generated
    positions we have observed and fixture: an interpreter launcher, uv's polyglot exec
    line, or a shell activation variable.  A comment, Python literal, or unrelated
    setting containing the same path is an ambiguity and makes the whole repair refuse.
    """
    old = re.escape(match.group("path"))
    shapes = (
        rf"^#!{old}/bin/python(?:3(?:\.\d+)?)?\s*$",
        rf"^'''exec'\s+['\"]{old}/bin/python(?:3(?:\.\d+)?)?['\"]\s+\"\$0\"\s+\"\$@\"\s*$",
        rf"^\s*VIRTUAL_ENV\s*=\s*(['\"]){old}\1\s*$",
        rf"^\s*setenv\s+VIRTUAL_ENV\s+(['\"]){old}\1\s*$",
        rf"^\s*set\s+-gx\s+VIRTUAL_ENV\s+(['\"]){old}\1\s*$",
        rf"^\s*let\s+virtual_env\s*=\s*(['\"]){old}\1\s*$",
        rf'^\s*@for\s+%%i\s+in\s+\(["\']' + old
        + rf'["\']\)\s+do\s+@set\s+"VIRTUAL_ENV=%%~fi"\s*$',
    )
    return any(re.fullmatch(shape, line) for shape in shapes)


def _replace_console(text: str, venv_name: str, venv_path: str) -> str:
    rewritten: List[str] = []
    for line_number, line in enumerate(text.splitlines(keepends=True), 1):
        body = line.rstrip("\r\n")
        matches = list(_VENV_PATH.finditer(body))
        if not matches:
            rewritten.append(line)
            continue
        if len(matches) != 1:
            raise RepairError(
                f"ambiguous generated console line {line_number} names multiple venv paths")
        match = matches[0]
        named = match.group("name")
        old = match.group("path")
        if named != venv_name:
            raise RepairError(
                f"console script names another venv ({named}, not {venv_name}): {old}")
        suffix = "/data/" + venv_name
        if not old.endswith(suffix) or not old[:-len(suffix)].startswith("/"):
            raise RepairError(f"cannot prove exact venv suffix for console path: {old}")
        if not _generated_console_line(body, match):
            raise RepairError(
                f"stale venv path is not in a recognized generated launcher shape "
                f"(line {line_number})")
        start, end = match.span("path")
        rewritten.append(body[:start] + venv_path + body[end:] + line[len(body):])
    return "".join(rewritten)


def _mapped_destination(destination: str, vendor_real: str) -> str:
    """Accept an in-tree package/namespace directory, or exact ``.py`` module stem."""
    # PEP 660's finder probes the exact package candidate before its `.py` sibling.
    # A lexical exact entry therefore cannot be bypassed by an unrelated safe stem.
    if os.path.lexists(destination):
        try:
            destination_mode = os.lstat(destination).st_mode
        except FileNotFoundError:
            destination_mode = 0
        if (not stat.S_ISDIR(destination_mode)
                or stat.S_ISLNK(destination_mode)
                or not _inside(os.path.realpath(destination), vendor_real)):
            raise RepairError(
                f"editable map target is absent or outside this checkout vendor tree: {destination}")
        return destination
    module = destination + ".py"
    try:
        mode = os.lstat(module).st_mode
    except FileNotFoundError:
        mode = 0
    if (stat.S_ISREG(mode) and not stat.S_ISLNK(mode)
            and _inside(os.path.realpath(module), vendor_real)):
        return module
    raise RepairError(
        f"editable map target is absent or outside this checkout vendor tree: {destination}")


def _replace_editable(text: str, vendor: str) -> str:
    vendor_real = os.path.realpath(vendor)

    def replace(match: re.Match[str]) -> str:
        suffix = match.group("suffix")
        destination = os.path.join(vendor, suffix)
        _mapped_destination(destination, vendor_real)
        return match.group("lead") + destination

    return _VENDOR_PATH.sub(replace, text)


def _console_changes(name: str, venv: str) -> List[Change]:
    bindir = os.path.join(venv, "bin")
    if not os.path.isdir(bindir) or os.path.islink(bindir):
        raise RepairError(f"venv bin is absent or a symlink: {bindir}")
    changes: List[Change] = []
    with os.scandir(bindir) as entries:
        for entry in entries:
            mode = entry.stat(follow_symlinks=False).st_mode
            if stat.S_ISLNK(mode):
                # venv's interpreter aliases are expected links.  Any other direct bin
                # link could hide a launch script outside this venv, so it is a refusal.
                if not _STANDARD_PYTHON_LINK.fullmatch(entry.name):
                    raise RepairError(f"refusing symlink console entry: {entry.path}")
                continue
            if stat.S_ISDIR(mode):
                # Some venvs keep __pycache__ directly in bin. It is not a console
                # script and this repair is deliberately non-recursive there.
                continue
            if not stat.S_ISREG(mode):
                raise RepairError(f"refusing non-regular console entry: {entry.path}")
            text, raw, info = _text(entry.path, "console script")
            rewritten = _replace_console(text, name, venv)
            if rewritten != text:
                changes.append(Change(entry.path, raw, rewritten.encode("utf-8"),
                                      stat.S_IMODE(info.st_mode), "console"))
    return changes


def _finder_paths(venv: str) -> Iterable[str]:
    lib = os.path.join(venv, "lib")
    if not os.path.isdir(lib) or os.path.islink(lib):
        return []
    paths: List[str] = []
    with os.scandir(lib) as versions:
        for version in versions:
            if not stat.S_ISDIR(version.stat(follow_symlinks=False).st_mode):
                continue
            site = os.path.join(version.path, "site-packages")
            if not os.path.isdir(site) or os.path.islink(site):
                continue
            with os.scandir(site) as entries:
                for entry in entries:
                    if (entry.name.startswith("__editable__")
                            and entry.name.endswith("_finder.py")):
                        paths.append(entry.path)
    return sorted(paths)


def _finder_changes(venv: str, vendor: str) -> List[Change]:
    changes: List[Change] = []
    for path in _finder_paths(venv):
        text, raw, info = _text(path, "editable finder")
        rewritten = _replace_editable(text, vendor)
        if rewritten != text:
            changes.append(Change(path, raw, rewritten.encode("utf-8"),
                                  stat.S_IMODE(info.st_mode), "finder"))
    return changes


def _atomic_write(path: str, data: bytes, mode: int) -> None:
    fd, temporary = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".u81-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _postverify(changes: Iterable[Change], vendor: str) -> None:
    vendor_real = os.path.realpath(vendor)
    for change in changes:
        text, _raw, _info = _text(change.path, "rewritten generated file")
        if change.kind == "console":
            name = os.path.basename(os.path.dirname(os.path.dirname(change.path)))
            venv = os.path.dirname(os.path.dirname(change.path))
            for match in _VENV_PATH.finditer(text):
                if match.group("name") != name or match.group("path") != venv:
                    raise RepairError(f"foreign console path remains after repair: {change.path}")
        else:
            for match in _VENDOR_PATH.finditer(text):
                destination = match.group("path")
                try:
                    _mapped_destination(destination, vendor_real)
                except RepairError as exc:
                    raise RepairError(
                        f"editable map remains outside vendor after repair: {change.path}") from exc


def _prove_import(venv: str, package: str, expected_root: str) -> None:
    python = os.path.join(venv, "bin", "python")
    if not os.path.isfile(python) or not os.access(python, os.X_OK):
        raise RepairError(f"venv python is unavailable for {package} proof: {python}")
    program = ("import importlib, pathlib, sys; "
               "m=importlib.import_module(sys.argv[1]); "
               "print(pathlib.Path(m.__file__).resolve())")
    run = subprocess.run([python, "-c", program, package], text=True,
                         capture_output=True, check=False, timeout=30)
    if run.returncode:
        raise RepairError(f"{package} import proof failed in {venv}: "
                          f"{(run.stderr or run.stdout).strip()[-240:]}")
    origin = run.stdout.strip()
    if not origin or not os.path.exists(origin) or not _inside(os.path.realpath(origin),
                                                               os.path.realpath(expected_root)):
        raise RepairError(f"{package} imported outside canonical vendor root: {origin or 'no origin'}")


def repair(root_argument: str, owned_names: Iterable[str]) -> int:
    root = os.path.realpath(os.path.abspath(root_argument))
    vendor = os.path.join(root, "vendor")
    if os.path.islink(vendor) or not os.path.isdir(vendor):
        raise RepairError(f"root has no direct, non-symlink vendor directory: {vendor}")
    names = list(owned_names)
    if not names:
        raise RepairError("no app-owned venv names were supplied")
    venvs = _venvs(root, names)
    changes: List[Change] = []
    for name, venv in venvs:
        changes.extend(_console_changes(name, venv))
        changes.extend(_finder_changes(venv, vendor))

    changed: List[Change] = []
    try:
        for change in changes:
            _atomic_write(change.path, change.replacement, change.mode)
            changed.append(change)
        _postverify(changed, vendor)
        for name, venv in venvs:
            if name == "hermes-venv":
                _prove_import(venv, "hermes_cli", os.path.join(vendor, "hermes"))
            elif name == "searxng-venv":
                _prove_import(venv, "searx", os.path.join(vendor, "searxng"))
    except Exception as exc:
        rollback_error: Optional[Exception] = None
        for change in reversed(changed):
            try:
                _atomic_write(change.path, change.original, change.mode)
            except Exception as restore_exc:
                rollback_error = restore_exc
                break
        if rollback_error is not None:
            raise RepairError(f"venv relocation repair failed ({exc}); rollback failed ({rollback_error})") from rollback_error
        if isinstance(exc, RepairError):
            raise
        raise RepairError(f"venv relocation repair failed and originals were restored: {exc}") from exc
    return len(changes)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--owned-venv", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        count = repair(args.root, args.owned_venv)
    except RepairError as exc:
        print(f"[venv-repair] ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"[venv-repair] repaired {count} generated venv pointer file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
