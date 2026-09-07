#!/usr/bin/env python3
"""Pin and verify Voicebox's three Git-only dependencies without editing vendor/."""
from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
from pathlib import Path
import re


SHA = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_LINES = {
    "linacodec": "linacodec @ git+https://github.com/ysharma3501/LinaCodec.git",
    "Zipvoice": "Zipvoice @ git+https://github.com/ysharma3501/LuxTTS.git",
}


def _pins(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        name, separator, pin = value.partition("=")
        if not separator or name not in (*EXPECTED_LINES, "qwen-tts") or not SHA.fullmatch(pin):
            raise ValueError(f"invalid Voicebox pin argument: {value!r}")
        if name in result:
            raise ValueError(f"duplicate Voicebox pin argument: {name}")
        result[name] = pin
    return result


def rewrite(source: Path, target: Path, pins: dict[str, str]) -> None:
    expected = set(EXPECTED_LINES)
    if set(pins) != expected:
        raise ValueError(f"rewrite requires exactly these pins: {sorted(expected)}")
    text = source.read_text(encoding="utf-8")
    for name, old in EXPECTED_LINES.items():
        if text.count(old) != 1:
            raise ValueError(f"expected exactly one Voicebox requirement line: {old}")
        text = text.replace(old, f"{old}@{pins[name]}")
    active_git = [line.strip() for line in text.splitlines()
                  if "git+https://" in line and not line.lstrip().startswith("#")]
    wanted = [f"{line}@{pins[name]}" for name, line in EXPECTED_LINES.items()]
    if active_git != wanted:
        raise ValueError(f"unreviewed floating or reordered Git requirement: {active_git!r}")
    target.write_text(text, encoding="utf-8")


def verify(pins: dict[str, str]) -> None:
    expected = {*EXPECTED_LINES, "qwen-tts"}
    if set(pins) != expected:
        raise ValueError(f"verify requires exactly these pins: {sorted(expected)}")
    for dist_name, pin in pins.items():
        dist = metadata.distribution(dist_name)
        raw = dist.read_text("direct_url.json")
        if not raw:
            raise ValueError(
                f"{dist_name} has no direct_url.json; pinned Git bytes were not installed")
        record = json.loads(raw)
        got = str((record.get("vcs_info") or {}).get("commit_id") or "")
        if got != pin:
            raise ValueError(f"{dist_name} provenance is {got or 'missing'}, expected {pin}")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    rewrite_parser = sub.add_parser("rewrite")
    rewrite_parser.add_argument("source", type=Path)
    rewrite_parser.add_argument("target", type=Path)
    rewrite_parser.add_argument("--pin", action="append", default=[])
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--pin", action="append", default=[])
    args = parser.parse_args()
    pins = _pins(args.pin)
    if args.command == "rewrite":
        rewrite(args.source, args.target, pins)
    else:
        verify(pins)
        print("[motdeck] Voicebox Git provenance verified (LinaCodec, LuxTTS, Qwen3-TTS).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
