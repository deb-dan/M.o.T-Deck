#!/usr/bin/env python3
"""Add repo manifest keys and named CAS migrations without rewriting live state."""
from __future__ import annotations

import datetime
import importlib.util
import os
import re
import shutil
import sys
from pathlib import Path

import yaml


KEY = re.compile(r"^(?P<indent> *)(?P<key>[A-Za-z0-9_-]+):")


def _yamlfile_module():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                        "bridge", "yamlfile.py")
    spec = importlib.util.spec_from_file_location("harness_yamlfile", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("shared harness.yaml transaction helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _spans(lines, indent):
    starts = []
    for index, line in enumerate(lines):
        match = KEY.match(line)
        if match and len(match.group("indent")) == indent:
            starts.append((match.group("key"), index))
    result = {}
    for position, (key, start) in enumerate(starts):
        end = starts[position + 1][1] if position + 1 < len(starts) else len(lines)
        result[key] = (start, end)
    return result


def _force_component_off(block):
    """A newly introduced component is present but never silently installed/enabled."""
    out, found = [], set()
    for line in block:
        match = re.match(r"^(    (installed|enabled):)[ \t]*[^#\r\n]*(.*)$", line.rstrip("\n"))
        if match:
            newline = "\n" if line.endswith("\n") else ""
            suffix = match.group(3)
            out.append(f"{match.group(1)} false{suffix}{newline}")
            found.add(match.group(2))
        else:
            out.append(line)
    for key in ("installed", "enabled"):
        if key not in found:
            if out and not out[-1].endswith("\n"):
                out[-1] += "\n"
            out.append(f"    {key}: false\n")
    return out


def _whole_components_off(block):
    lines = list(block)
    spans = _spans(lines[1:], 2)
    for _, (start, end) in sorted(spans.items(), key=lambda item: item[1][0], reverse=True):
        start += 1; end += 1
        lines[start:end] = _force_component_off(lines[start:end])
    return lines


def merge_text(source, destination):
    """Return `(merged, added)` while preserving every pre-existing destination byte."""
    src_parsed = yaml.safe_load(source)
    dst_parsed = yaml.safe_load(destination)
    for label, parsed in (("repo", src_parsed), ("live", dst_parsed)):
        if not isinstance(parsed, dict):
            raise ValueError(f"{label} harness.yaml must be a YAML mapping")
    src_lines = source.splitlines(keepends=True)
    dst_lines = destination.splitlines(keepends=True)
    src_top, dst_top = _spans(src_lines, 0), _spans(dst_lines, 0)
    added = []

    for key, (start, end) in src_top.items():
        if key in dst_top:
            continue
        block = src_lines[start:end]
        if key == "components":
            block = _whole_components_off(block)
        if dst_lines and not dst_lines[-1].endswith("\n"):
            dst_lines[-1] += "\n"
        dst_lines.extend(block)
        added.append(key)
        dst_top = _spans(dst_lines, 0)

    for section in ("components", "build"):
        src_top, dst_top = _spans(src_lines, 0), _spans(dst_lines, 0)
        if section not in src_top or section not in dst_top:
            continue
        ss, se = src_top[section]; ds, de = dst_top[section]
        src_children = _spans(src_lines[ss + 1:se], 2)
        dst_children = _spans(dst_lines[ds + 1:de], 2)
        for name, (start, end) in src_children.items():
            if name in dst_children:
                continue
            block = src_lines[ss + 1 + start:ss + 1 + end]
            if section == "components":
                block = _force_component_off(block)
            dst_top = _spans(dst_lines, 0)
            ds, de = dst_top[section]
            dst_lines[de:de] = block
            added.append(f"{section}.{name}")
            dst_children[name] = (0, 0)

    # A11 migration: `components.searxng.pin: main` was the repo's historical
    # floating DEFAULT, not user install state. The strict installer now requires the
    # exact audited commit. Move only that one known old value to the repo's exact SHA;
    # any other live value is an operator choice and remains byte-for-byte untouched.
    # This is deliberately a compare-and-swap migration, not a general "sync pins"
    # exception to the live-state rule.
    src_searx = ((src_parsed.get("components") or {}).get("searxng") or {})
    dst_searx = ((dst_parsed.get("components") or {}).get("searxng") or {})
    src_pin = str(src_searx.get("pin") or "")
    if dst_searx.get("pin") == "main" and re.fullmatch(r"[0-9a-f]{40}", src_pin):
        src_top, dst_top = _spans(src_lines, 0), _spans(dst_lines, 0)
        ss, se = src_top["components"]; ds, de = dst_top["components"]
        src_children = _spans(src_lines[ss + 1:se], 2)
        dst_children = _spans(dst_lines[ds + 1:de], 2)
        if "searxng" not in src_children or "searxng" not in dst_children:
            raise ValueError("searxng pin migration could not locate the component block")
        srs, sre = src_children["searxng"]
        drs, dre = dst_children["searxng"]
        src_start, src_end = ss + 1 + srs, ss + 1 + sre
        dst_start, dst_end = ds + 1 + drs, ds + 1 + dre
        src_fields = _spans(src_lines[src_start:src_end], 4)
        dst_fields = _spans(dst_lines[dst_start:dst_end], 4)
        if "pin" not in src_fields or "pin" not in dst_fields:
            raise ValueError("searxng pin migration could not locate the pin field")
        src_pin_line = src_start + src_fields["pin"][0]
        dst_pin_line = dst_start + dst_fields["pin"][0]
        dst_lines[dst_pin_line] = src_lines[src_pin_line]
        added.append(f"components.searxng.pin(main→{src_pin[:12]})")
    merged = "".join(dst_lines)
    if not isinstance(yaml.safe_load(merged), dict):
        raise ValueError("merged harness.yaml is not a YAML mapping")
    return merged, added


def main(argv):
    if len(argv) != 3:
        print("usage: merge_manifest.py <repo-harness.yaml> <live-harness.yaml>", file=sys.stderr)
        return 2
    source_path, destination_path = map(os.path.abspath, argv[1:])
    try:
        with open(source_path, encoding="utf-8") as fh:
            source = fh.read()
        txn = _yamlfile_module()
        backup = ""
        def edit(old):
            nonlocal backup
            merged, added = merge_text(source, old)
            if added:
                stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
                backup = destination_path + ".bak-" + stamp
                shutil.copy2(destination_path, backup)
                for prior in sorted(Path(destination_path).parent.glob(
                        Path(destination_path).name + ".bak-*"))[:-5]:
                    try:
                        prior.unlink()
                    except OSError:
                        pass
            return merged, added
        added = txn.transform_file(destination_path, edit)
        if added:
            print("[ship] manifest: added " + ", ".join(added) + " (snapshot backed up)")
        else:
            count = len(_spans(source.splitlines(keepends=True), 0))
            print(f"[ship] manifest: up to date ({count} top-level sections checked)")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[ship] ERROR: manifest merge failed safely: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
