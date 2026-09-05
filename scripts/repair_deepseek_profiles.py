#!/usr/bin/env python3
"""Repair only dsh's generated profile node_modules links for this npm prefix.

This is deliberately stdlib-only so install_deepseek.sh can run it with the same
interpreter it already uses for npm metadata. It never follows symlinks while deciding
what may be moved or deleted; resolving links is used only to verify their targets.
"""
from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
from typing import List, Optional, Tuple


class RepairError(RuntimeError):
    """A refusal that must leave the original generated tree recoverable."""


MATERIALIZER_TIMEOUT_SECONDS = 30


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def _scan_generated(root: str) -> List[str]:
    """Return symlinks under root, refusing anything but directories and links."""
    try:
        root_mode = os.lstat(root).st_mode
    except FileNotFoundError:
        return []
    if not stat.S_ISDIR(root_mode):
        raise RepairError(f"generated profile path is not a directory: {root}")

    links: List[str] = []

    def visit(directory: str) -> None:
        with os.scandir(directory) as entries:
            for entry in entries:
                mode = entry.stat(follow_symlinks=False).st_mode
                if stat.S_ISLNK(mode):
                    links.append(entry.path)
                elif stat.S_ISDIR(mode):
                    visit(entry.path)
                else:
                    raise RepairError(
                        f"refusing generated profile with non-link, non-directory entry: {entry.path}"
                    )

    visit(root)
    return links


def _remove_generated(root: str) -> None:
    """Remove a tree only after the same no-follow generated-entry validation."""
    _scan_generated(root)

    def remove(directory: str) -> None:
        with os.scandir(directory) as entries:
            for entry in entries:
                mode = entry.stat(follow_symlinks=False).st_mode
                if stat.S_ISLNK(mode):
                    os.unlink(entry.path)
                elif stat.S_ISDIR(mode):
                    remove(entry.path)
                else:  # _scan_generated already fenced this; retain fail-closed here.
                    raise RepairError(f"unsafe entry appeared during removal: {entry.path}")
        os.rmdir(directory)

    if os.path.lexists(root):
        remove(root)


def _verify_local(tree: str, prefix_modules: str) -> Tuple[List[str], List[str]]:
    links = _scan_generated(tree)
    escaped = [link for link in links
               if not os.path.exists(link)
               or not _inside(os.path.realpath(link), prefix_modules)]
    return links, escaped


HEALER_PROGRAM = """import { pathToFileURL } from 'node:url';
const bootModule = process.env.HARNESS_DSH_BOOT_MODULE;
const installAnchor = process.env.HARNESS_DSH_INSTALL_ANCHOR;
const profileHome = process.env.HARNESS_DSH_PROFILE_HOME;
const { healProfilesModuleFallback } = await import(pathToFileURL(bootModule).href);
healProfilesModuleFallback(installAnchor, profileHome);
"""


def _healer_paths(prefix: str) -> Tuple[str, str]:
    modules = os.path.join(prefix, "node_modules")
    return (os.path.join(modules, "@deepseek-ai", "dsh-app-boot", "lib", "index.js"),
            os.path.join(modules, "@deepseek-ai", "dsh", "package.json"))


def repair(prefix: str, home: str, node: str,
           timeout: float = MATERIALIZER_TIMEOUT_SECONDS) -> str:
    prefix_modules = os.path.realpath(os.path.join(prefix, "node_modules"))
    tree = os.path.join(home, "profiles", "node_modules")
    backup = tree + ".u81-backup"
    boot_module, install_anchor = _healer_paths(prefix)

    if not os.path.isfile(boot_module):
        raise RepairError(f"dsh boot healer is missing from this npm prefix: {boot_module}")
    if not os.path.isfile(install_anchor):
        raise RepairError(f"dsh install anchor is missing from this npm prefix: {install_anchor}")
    if not (os.path.isfile(node) and os.access(node, os.X_OK)):
        raise RepairError(f"resolved node is not executable: {node}")

    if not os.path.isdir(tree):
        if os.path.lexists(tree):
            raise RepairError(f"generated profile path is not a directory: {tree}")
        return "profile links absent — nothing to repair"

    _links, escaped = _verify_local(tree, prefix_modules)
    if not escaped:
        return "profile links are local — nothing to repair"
    if os.path.lexists(backup):
        raise RepairError(f"backup already exists; refusing to overwrite it: {backup}")

    # Same-parent rename is atomic. The source has passed the generated-entry fence.
    os.replace(tree, backup)
    try:
        # Do not call `dsh --version`: it does not boot a profile and therefore
        # produces no fallback links. Invoke the exported upstream healer directly;
        # the fixed program has no interpolated paths and receives exact paths only
        # through its environment.
        env = dict(os.environ,
                   HARNESS_DSH_BOOT_MODULE=boot_module,
                   HARNESS_DSH_INSTALL_ANCHOR=install_anchor,
                   HARNESS_DSH_PROFILE_HOME=home)
        run = subprocess.run([node, "--input-type=module", "--eval", HEALER_PROGRAM],
                             env=env, text=True,
                             capture_output=True, check=False, timeout=timeout)
        if run.returncode:
            raise RepairError(
                f"dsh profile healer failed (exit {run.returncode}): "
                f"{(run.stderr or run.stdout).strip()[-240:]}"
            )
        links, escaped = _verify_local(tree, prefix_modules)
        if not links:
            raise RepairError("dsh profile healer rebuilt no profile links; original profile was restored")
        if escaped:
            raise RepairError("dsh profile healer rebuilt a link outside this npm prefix; original profile was restored")
    except Exception as exc:
        try:
            if os.path.lexists(tree):
                _remove_generated(tree)
            os.replace(backup, tree)
        except Exception as rollback_exc:
            raise RepairError(
                f"repair failed ({exc}); rollback also failed ({rollback_exc}). "
                f"Original generated profile remains at {backup}; do not delete it."
            ) from rollback_exc
        if isinstance(exc, RepairError):
            raise
        raise RepairError(f"dsh profile rebuild failed: {exc}") from exc

    _remove_generated(backup)
    return "repaired stale generated profile links into this npm prefix"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--home", required=True)
    parser.add_argument("--node", required=True)
    parser.add_argument("--timeout-seconds", type=float,
                        default=MATERIALIZER_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    try:
        print(f"[deepseek] {repair(args.prefix, args.home, args.node, args.timeout_seconds)}")
    except RepairError as exc:
        print(f"[deepseek] ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
