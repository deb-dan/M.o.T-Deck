#!/usr/bin/env python3
"""Keep UNFORGET's visible targets synchronized with its authoritative index."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import tempfile


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs" / "UNFORGET.md"
ROADMAP = ROOT / "docs" / "ROADMAP.md"
START = "<!-- current-status:start"
END = "current-status:end -->"
ROW_RE = re.compile(r"^(\| ([PSAU]\d+) \| )([^|]+)( \|.*)$")

ACTIVE_GROUPS = (
    "in-progress", "next", "later", "someday",
    "blocked-later", "blocked-someday", "withdrawn",
)


def current_groups(text: str) -> dict[str, tuple[str, ...]]:
    if text.count(START) != 1 or text.count(END) != 1:
        raise ValueError("expected exactly one current-status block")
    body = text.split(START, 1)[1].split(END, 1)[0]
    groups: dict[str, tuple[str, ...]] = {}
    for raw in body.splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key not in ACTIVE_GROUPS:
            raise ValueError(f"unknown current-status group: {key}")
        groups[key] = tuple(value.split())
    missing = set(ACTIVE_GROUPS) - set(groups)
    if missing:
        raise ValueError("missing current-status groups: " + ", ".join(sorted(missing)))
    return groups


def row_ids(text: str) -> tuple[str, ...]:
    return tuple(m.group(2) for line in text.splitlines() if (m := ROW_RE.match(line)))


def validate(ledger: str, roadmap: str) -> dict[str, tuple[str, ...]]:
    groups = current_groups(ledger)
    if groups != current_groups(roadmap):
        raise ValueError("ROADMAP and UNFORGET current-status blocks disagree")
    rows = row_ids(ledger)
    if len(rows) != len(set(rows)):
        duplicates = sorted({item for item in rows if rows.count(item) > 1})
        raise ValueError("duplicate ledger rows: " + ", ".join(duplicates))
    active = [item for group in groups.values() for item in group]
    if len(active) != len(set(active)):
        duplicates = sorted({item for item in active if active.count(item) > 1})
        raise ValueError("IDs in multiple current-status groups: " + ", ".join(duplicates))
    unknown = sorted(set(active) - set(rows))
    if unknown:
        raise ValueError("current-status IDs missing from ledger: " + ", ".join(unknown))
    return groups


def target_map(ledger: str, roadmap: str) -> dict[str, str]:
    groups = validate(ledger, roadmap)
    targets: dict[str, str] = {}
    for item in row_ids(ledger):
        targets[item] = "✅ CLOSED"
    for item in groups["in-progress"]:
        targets[item] = "🔴 THIS"
    for item in groups["next"]:
        targets[item] = "🔵 NEXT"
    for item in groups["later"] + groups["blocked-later"]:
        targets[item] = "🟡 LATER"
    for item in groups["someday"] + groups["blocked-someday"]:
        targets[item] = "⚪ SOMEDAY"
    for item in groups["withdrawn"]:
        targets[item] = "⚪ WITHDRAWN"
    return targets


def normalized(ledger: str, roadmap: str) -> str:
    targets = target_map(ledger, roadmap)
    out = []
    for line in ledger.splitlines(keepends=True):
        ending = "\n" if line.endswith("\n") else ""
        content = line[:-1] if ending else line
        match = ROW_RE.match(content)
        if match:
            content = match.group(1) + targets[match.group(2)] + match.group(4)
        out.append(content + ending)
    return "".join(out)


def atomic_write(path: Path, text: str) -> None:
    fd, raw = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    temp = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="apply the synchronized targets")
    args = parser.parse_args()
    ledger = LEDGER.read_text(encoding="utf-8")
    roadmap = ROADMAP.read_text(encoding="utf-8")
    wanted = normalized(ledger, roadmap)
    if wanted == ledger:
        print(f"ledger targets current ({len(row_ids(ledger))} rows)")
        return 0
    if not args.write:
        print("ledger targets drifted; run scripts/normalize_ledger.py --write")
        return 1
    atomic_write(LEDGER, wanted)
    print(f"ledger targets synchronized ({len(row_ids(wanted))} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
