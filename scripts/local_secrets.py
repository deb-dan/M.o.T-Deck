#!/usr/bin/env python3
"""Operator-visible interface to M.O.T's local launch-secret store."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("ensure", "get", "inspect"))
    parser.add_argument("root", type=Path)
    parser.add_argument("name", nargs="?")
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(args.root))
    from bridge.core.localsecrets import (SECRET_PATHS, WEAK_DEFAULTS, ensure, read)
    try:
        values = ensure(args.root, fresh=args.fresh) if args.command == "ensure" else read(args.root)
        if args.command == "get":
            if args.name not in SECRET_PATHS.values():
                raise ValueError("unknown secret name")
            value = values.get(args.name, "")
            if not value:
                raise ValueError("secret is not provisioned")
            sys.stdout.write(value)
        elif args.command == "inspect":
            for key in SECRET_PATHS.values():
                state = "missing" if not values.get(key) else (
                    "weak-repository-default" if values[key] == WEAK_DEFAULTS[key] else "provisioned")
                print(f"{key}: {state}")
            print("values: redacted")
        else:
            print("local launch secrets are provisioned (values redacted)")
        return 0
    except Exception as exc:  # never echo a secret value
        print(f"ERROR: local secret operation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
