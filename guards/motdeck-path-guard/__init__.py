"""motdeck-path-guard — fence Hermes file writes behind the human approval gate.

Upstream Hermes gates *dangerous shell commands* with a human approval prompt, but
``write_file`` / ``patch`` are ungated BY DESIGN: the agent can write anywhere the
process can reach without a card ever appearing. This plugin closes that gap using
upstream's own first-class seam — the ``pre_tool_call`` hook (hermes_cli/plugins.py
``_get_pre_tool_call_directive_details`` / ``resolve_pre_tool_block``) — whose
``{"action": "approve"}`` directive escalates ANY tool call into the SAME approval
gate (``tools.approval.request_tool_approval``) that dangerous commands use. On the
MOT Deck panel that surfaces as the existing Phase-2 approval card with zero UI work.

Policy (``policy.yaml`` beside this file, re-read on every gated call so edits apply
without a restart):

* target inside a **deny** root → ``{"action": "block"}`` — hard veto, not approvable.
* target inside an **allow** root → ``None`` — proceed, zero further overhead.
* anything else → ``{"action": "approve", ...}`` — human card, per-directory
  ``rule_key`` so an "Always" answer is scoped to that directory.

Matching is containment-based: ``os.path.commonpath([target, root]) == root`` on
``os.path.realpath``-resolved absolute paths. String prefixes are FORBIDDEN here —
``/Users/testuserEvil`` must never match ``/Users/testuser``.

Fail-CLOSED everywhere: an unresolvable target (a V4A multi-file patch whose paths
live only inside the patch body), a missing/unparseable policy, or ANY exception in
the hook escalates to the approval gate. The hook never returns ``None`` by accident.

HONEST LIMITS (also recorded in CLAUDE.md):
* Gates ``write_file`` and ``patch`` only. Arbitrary writes performed by a shell
  command (``terminal`` redirects, ``execute_code``) are NOT covered here — those
  ride upstream's dangerous-pattern gating. Full shell coverage would need an OS
  sandbox (sandbox-exec), a deliberately deferred option.
* Reads and exfiltration are out of scope.
* The bridge's audit tier (``guard_flag`` frames) independently flags out-of-allowlist
  writes after the fact, so a disabled/misconfigured plugin is still visible.
"""

from __future__ import annotations

import logging
import json
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# Only these two tools carry "write a file to this path" semantics. Everything
# else short-circuits to None immediately (the hook fires on EVERY tool call).
GATED_TOOLS = ("write_file", "patch")

POLICY_FILENAME = "policy.yaml"

# Fallback policy used only when policy.yaml is missing/unreadable: no allow roots
# at all, so every write escalates to a human. Noisy but never silently permissive.
_EMPTY_POLICY: Dict[str, List[str]] = {"allow": [], "deny": []}


# ---------------------------------------------------------------------------
# Policy loading (pure w.r.t. its text input)
# ---------------------------------------------------------------------------

def parse_policy_text(text: str) -> Dict[str, List[str]]:
    """Parse the flat ``allow:``/``deny:`` list-of-strings policy document.

    PyYAML is used when importable; otherwise a deliberately tiny line parser
    handles this exact two-key shape so the guard never depends on an optional
    import to stay enforcing.
    """
    data: Any = None
    try:
        import yaml  # type: ignore
    except ImportError:
        data = _mini_parse(text)
    else:
        try:
            data = yaml.safe_load(text)
        except Exception:
            # A parse failure is not permission to salvage half a policy: its deny
            # section may be the part that failed while a broad allow survived.
            return {'allow': [], 'deny': []}
    out: Dict[str, List[str]] = {"allow": [], "deny": []}
    if not isinstance(data, dict):
        return out
    for key in ("allow", "deny"):
        vals = data.get(key, [])
        if not isinstance(vals, list) or any(not isinstance(v, str) or not v.strip() for v in vals):
            return {'allow': [], 'deny': []}
        out[key] = [v.strip() for v in vals]
    return out


def _mini_parse(text: str) -> Dict[str, List[str]]:
    """Minimal `key:` + `  - "value"` reader for the policy shape above."""
    out: Dict[str, List[str]] = {"allow": [], "deny": []}
    current: Optional[str] = None
    seen = set()
    for raw in (text or "").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith('#'):
            continue
        header = re.fullmatch(r'(allow|deny):\s*(?:\[\]\s*)?(?:#.*)?', stripped)
        if header and not raw[:1].isspace():
            current = header.group(1)
            # Duplicate headers are ambiguous in this deliberately narrow reader.
            if current in seen:
                return {'allow': [], 'deny': []}
            seen.add(current)
            continue
        if not current or not raw[:1].isspace() or not stripped.startswith('- '):
            return {'allow': [], 'deny': []}
        value = stripped[2:].strip()
        try:
            if value.startswith('"'):
                val, end = json.JSONDecoder().raw_decode(value)
                rest = value[end:].strip()
                if rest and not rest.startswith('#'):
                    raise ValueError('invalid trailing policy text')
            elif value.startswith("'"):
                match = re.fullmatch(r"'((?:[^']|'')*)'\s*(?:#.*)?", value)
                if match is None:
                    raise ValueError('invalid quoted policy path')
                val = match.group(1).replace("''", "'")
            else:
                val = re.split(r'\s+#', value, maxsplit=1)[0].strip()
                if any(c in val for c in '[]"\'') or ': ' in val:
                    raise ValueError('unsupported policy syntax')
            if not isinstance(val, str) or not val.strip():
                raise ValueError('empty policy path')
        except (ValueError, TypeError):
            return {'allow': [], 'deny': []}
        out[current].append(val)
    return out


def load_policy(policy_path: str) -> Dict[str, List[str]]:
    """Read + parse the policy file; on ANY failure return the empty (escalate-all)
    policy rather than an implicitly permissive one."""
    try:
        with open(policy_path, "r", encoding="utf-8") as fh:
            return parse_policy_text(fh.read())
    except Exception as exc:  # missing, unreadable, malformed
        logger.warning("motdeck-path-guard: cannot read policy %s (%s) — "
                       "escalating every write", policy_path, exc)
        return dict(_EMPTY_POLICY)


# ---------------------------------------------------------------------------
# Pure matcher
# ---------------------------------------------------------------------------

def resolve_roots(raw_roots: Sequence[str], *, cwd: str, motdeck_root: str = "",
                  tmpdir: str = "", home: str = "") -> List[str]:
    """Expand ``{HERMES_CWD}`` / ``{MOT_DECK_ROOT}`` / ``{TMPDIR}`` + ``~`` and
    realpath each root. Roots whose placeholder resolves empty are dropped (an
    unset $TMPDIR must NOT collapse to "/" and allow the whole filesystem)."""
    home = home or os.path.expanduser("~")
    out: List[str] = []
    for raw in raw_roots or []:
        r = str(raw or "").strip()
        if not r:
            continue
        subs = (("{HERMES_CWD}", cwd), ("{MOT_DECK_ROOT}", motdeck_root),
                ("{TMPDIR}", tmpdir))
        bad = False
        for token, value in subs:
            if token in r:
                if not value:
                    bad = True
                    break
                r = r.replace(token, value)
        if bad or "{" in r:
            continue
        if r.startswith("~"):
            r = home + r[1:] if r == "~" or r.startswith("~/") else os.path.expanduser(r)
        if not os.path.isabs(r):
            continue
        try:
            out.append(os.path.realpath(r).rstrip(os.sep) or os.sep)
        except Exception:
            continue
    return out


def path_inside(target: str, root: str) -> bool:
    """True iff *target* is *root* or lives beneath it.

    Containment via ``os.path.commonpath`` — NOT ``startswith`` (which would make
    ``/Users/testuserEvil/x`` "inside" ``/Users/testuser``).
    """
    try:
        if not target or not root:
            return False
        if not (os.path.isabs(target) and os.path.isabs(root)):
            return False
        t = target.rstrip(os.sep) or os.sep
        r = root.rstrip(os.sep) or os.sep
        return os.path.commonpath([t, r]) == r
    except Exception:
        return False


def classify_path(target: str, allow_roots: Sequence[str],
                  deny_roots: Sequence[str]) -> Tuple[str, str]:
    """Return ``("deny"|"allow"|"escalate", matched_root)``. deny wins over allow."""
    for r in deny_roots or []:
        if path_inside(target, r):
            return ("deny", r)
    for r in allow_roots or []:
        if path_inside(target, r):
            return ("allow", r)
    return ("escalate", "")


def extract_target(tool_name: str, args: Any) -> Tuple[Optional[str], str]:
    """Pull the write target out of the tool args.

    Returns ``(raw_path_or_None, unresolved_reason)``. ``write_file`` always
    carries ``path``; a single-file ``patch`` does too, but a V4A multi-file patch
    addresses its files only inside the patch body — that case is UNRESOLVED and
    must escalate, never pass.
    """
    if not isinstance(args, dict):
        return (None, "tool args missing — cannot verify the write target")
    raw = args.get("path")
    if isinstance(raw, str) and raw.strip():
        return (raw.strip(), "")
    if tool_name == "patch":
        return (None, "patch with embedded paths — cannot verify targets")
    return (None, "no path argument — cannot verify the write target")


def abs_target(raw_path: str, *, cwd: str, home: str = "") -> str:
    """Expand ``~``, make absolute against *cwd*, resolve symlinks."""
    home = home or os.path.expanduser("~")
    p = str(raw_path or "").strip()
    if p.startswith("~"):
        p = home + p[1:] if p == "~" or p.startswith("~/") else os.path.expanduser(p)
    if not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return os.path.realpath(p)


def escalate_directive(message: str, target: str = "") -> Dict[str, str]:
    """The one approve-directive builder (used by the normal path AND every
    fail-closed path, so they can never drift)."""
    # rule_key grain = the CONTAINING directory, so answering "Always" to a write
    # in ~/Desktop does not blanket-approve ~/.aws. ⚠ PENDING FABLE QA: the spec
    # said "<top-level dir>"; read as the target's directory (per-directory grain),
    # since a literal first path component (/Users) would be far too coarse.
    grain = ""
    try:
        if target:
            grain = os.path.dirname(target) or target
    except Exception:
        grain = ""
    return {"action": "approve", "message": message,
            "rule_key": "path-guard:" + (grain or "unresolved")}


def evaluate(tool_name: str, args: Any, *, allow_roots: Sequence[str],
             deny_roots: Sequence[str], cwd: str,
             home: str = "") -> Optional[Dict[str, str]]:
    """PURE policy decision (given already-resolved roots). Returns the
    pre_tool_call directive dict, or None to proceed untouched."""
    if tool_name not in GATED_TOOLS:
        return None
    raw, unresolved = extract_target(tool_name, args)
    if raw is None:
        return escalate_directive("path-guard: " + unresolved)
    target = abs_target(raw, cwd=cwd, home=home)
    verdict, root = classify_path(target, allow_roots, deny_roots)
    if verdict == "deny":
        return {"action": "block",
                "message": "path-guard: writes to {} are blocked".format(root)}
    if verdict == "allow":
        return None
    return escalate_directive(
        "path-guard: write outside workspace: {}".format(target), target)


# ---------------------------------------------------------------------------
# Hook wiring
# ---------------------------------------------------------------------------

def _policy_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), POLICY_FILENAME)


def _motdeck_root_hint() -> str:
    """{MOT_DECK_ROOT} is substituted with the repo root when start_component.sh
    seeds policy.yaml. MOT_DECK_ROOT env (if the launcher exports one) is honored
    as a fallback so an unsubstituted placeholder still resolves."""
    return os.environ.get("MOT_DECK_ROOT", "") or ""


def _on_pre_tool_call(tool_name: str = "", args: Any = None,
                      **_: Any) -> Optional[Dict[str, str]]:
    """pre_tool_call hook: gate write_file/patch by path policy. Fail-closed."""
    try:
        if tool_name not in GATED_TOOLS:
            return None
        policy = load_policy(_policy_path())
        cwd = os.getcwd()
        allow = resolve_roots(policy.get("allow", []), cwd=cwd,
                              motdeck_root=_motdeck_root_hint(),
                              tmpdir=os.environ.get("TMPDIR", ""))
        deny = resolve_roots(policy.get("deny", []), cwd=cwd,
                             motdeck_root=_motdeck_root_hint(),
                             tmpdir=os.environ.get("TMPDIR", ""))
        directive = evaluate(tool_name, args, allow_roots=allow, deny_roots=deny,
                             cwd=cwd)
        if directive:
            logger.info("motdeck-path-guard: %s on %s → %s", tool_name,
                        (args or {}).get("path") if isinstance(args, dict) else "?",
                        directive.get("action"))
        return directive
    except Exception as exc:
        # Fail-CLOSED: never let a guard bug turn into a silent allow.
        logger.warning("motdeck-path-guard: internal error (%s) — escalating", exc)
        return escalate_directive(
            "path-guard: guard error, human confirmation required for "
            "{}".format(tool_name))


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
