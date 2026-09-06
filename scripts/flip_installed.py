#!/usr/bin/env python3
"""Flip `components.<name>.installed` to true in motdeck.yaml.

WHY THIS IS ITS OWN FILE. Mission Control decides whether a component's card says
"Not installed" from the MANIFEST FLAG, never from disk:

    bridge/app.py::status()  ->  "installed": bool(comp.get("installed"))

so an installer that lands every byte on disk and forgets this line produces exactly
the bug that shipped with OpenCode on 2026-08-21: install_opencode.sh printed
"installed: opencode 1.18.19" (twice, on the idempotent re-run) while the card still
offered an Install button. install_component.sh had carried the flip inline in its own
tail since M0, so only the STANDALONE installers were affected — and there were two of
them (opencode and searxng; searxng escaped notice solely because motdeck.yaml already
shipped it as installed: true).

One implementation, called by all of them. A second copy of a writer that can drift is
the defect class this project has been bitten by more than once.

    python3 scripts/flip_installed.py <component> [manifest]

The manifest defaults to <this script>/../motdeck.yaml, so it always edits the ROOT OF
THE INSTALL THAT IS RUNNING — the snapshot's copy when the bridge spawns it from
~/Library/Application Support/MOT Deck, the repo's when run from the repo. That matters:
ship.sh's manifest merge is ADDITIVE ONLY (it never changes an existing key's value), so
nothing downstream will ever flip this flag later on the user's behalf.

TEXT EDIT, NEVER A YAML ROUND-TRIP. `yaml.safe_dump` writes an empty key as the literal
string `null`, which the shell readers take as a path — that incident (2026-08-07) broke
every model load. This walks lines and replaces one token, so comments, ordering and
empty scalars all survive byte-for-byte.

Exit codes: 0 flipped or already true; 1 the component / its `installed:` key is missing
(a card that can never flip is the bug, so it is loud, not silent).
"""
import os
import re
import sys
import importlib.util

_NAME = re.compile(r"^  ([A-Za-z0-9_-]+):\s*(#.*)?$")
# group 1 = "    installed: ", group 2 = the value token, group 3 = any trailing comment
_INSTALLED = re.compile(r"^(    installed:[ \t]*)(\S+)(.*)$")


def _yamlfile_module():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                        "bridge", "yamlfile.py")
    spec = importlib.util.spec_from_file_location("motdeck_yamlfile", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("shared motdeck.yaml transaction helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def flip(text: str, name: str) -> "tuple[str, str]":
    """Pure. Returns (new_text, status) with status in {flipped, already, no-component,
    no-key}. new_text is byte-identical to text for every status but 'flipped'."""
    lines = text.splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        m = _NAME.match(line)
        if m and m.group(1) == name:
            start = i
            break
    if start is None:
        return text, "no-component"
    for i in range(start + 1, len(lines)):
        line = lines[i]
        # End of this component's block: any sibling 2-space key, or a top-level key.
        if _NAME.match(line) or (line[:1] not in (" ", "\t", "\n", "\r", "")
                                 and not line.startswith("#")):
            break
        m = _INSTALLED.match(line.rstrip("\n"))
        if m:
            if m.group(2) == "true":
                return text, "already"
            nl = "\n" if line.endswith("\n") else ""
            lines[i] = f"{m.group(1)}true{m.group(3)}{nl}"
            return "".join(lines), "flipped"
    return text, "no-key"


def main(argv: "list[str]") -> int:
    if not 2 <= len(argv) <= 3:
        print("usage: flip_installed.py <component> [manifest]", file=sys.stderr)
        return 2
    name = argv[1]
    path = argv[2] if len(argv) == 3 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), os.pardir, "motdeck.yaml")
    path = os.path.abspath(path)
    try:
        txn = _yamlfile_module()
        def edit(text):
            new, status = flip(text, name)
            if status in ("no-component", "no-key"):
                raise ValueError(status)
            try:
                import yaml  # noqa: PLC0415
                yaml.safe_load(new)
            except ImportError:
                pass
            return new, status
        status = txn.transform_file(path, edit)
    except ValueError as exc:
        if str(exc) == "no-component":
            print(f"[motdeck] ERROR: components.{name} is not in {path} — the Mission "
                  f"Control card reads that flag, so it would stay 'Not installed'.",
                  file=sys.stderr)
        elif str(exc) == "no-key":
            print(f"[motdeck] ERROR: components.{name} has no `installed:` key in {path} "
                  f"— add `installed: false` to the block.", file=sys.stderr)
        else:
            print(f"[motdeck] ERROR: the edit would break {path} ({exc}) — nothing written.",
                  file=sys.stderr)
        return 1
    except Exception as exc:                                      # noqa: BLE001
        print(f"[motdeck] ERROR: cannot safely update {path}: {exc}", file=sys.stderr)
        return 1
    if status == "already":
        print(f"[motdeck] {name}: installed flag already true.")
        return 0
    print(f"[motdeck] {name}: installed -> true in {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
