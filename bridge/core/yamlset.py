"""CORE — the surgical harness.yaml writers (line-level, comment-preserving)."""
from __future__ import annotations

from .appctx import ROOT
from ..yamlfile import transform_file


# ── Models pane (M2) — list installed from OUR registry, switch the runner ──
def _set_yaml_model(block: str, new_id: str) -> None:
    """Rewrite <block>.model in harness.yaml (line-scan, preserves everything else)."""
    import re
    p = ROOT / "harness.yaml"
    def edit(text):
        lines = text.split("\n")
        inside = False
        for i, ln in enumerate(lines):
            if re.match(rf'^{re.escape(block)}:\s*$', ln):
                inside = True; continue
            if inside and re.match(r'^\S', ln):
                inside = False
            if inside and re.match(r'^  model:', ln):
                lines[i] = f"  model: {new_id}"
                break
        return "\n".join(lines)
    transform_file(p, edit)


def _set_runner_model(new_id: str) -> None:
    _set_yaml_model("runner", new_id)


def _set_yaml_scalar(block: str, key: str, value: str) -> None:
    """Rewrite <block>.<key> in harness.yaml IN PLACE (same line-scan idiom as
    _set_yaml_model, so every comment / ordering in the file survives — a full yaml
    round-trip would strip them, which we only ever accept for ~/.hermes/config.yaml).
    An empty value writes a bare `key:` (= null = off). If the block or the key is
    missing (e.g. an older snapshot manifest that ship.sh's merge hasn't touched yet)
    they are appended rather than silently dropped."""
    import re
    p = ROOT / "harness.yaml"
    def edit(text):
        lines = text.split("\n")
        inside, block_at, last_in_block = False, -1, -1
        for i, ln in enumerate(lines):
            if re.match(rf'^{re.escape(block)}:\s*$', ln):
                inside, block_at = True, i
                continue
            if inside and re.match(r'^\S', ln):
                inside = False
            if inside:
                if ln.strip():
                    last_in_block = i
                if re.match(rf'^  {re.escape(key)}:', ln):
                    suffix = ""
                    m = re.search(r'\s(#.*)$', ln)
                    if m:
                        suffix = "  " + m.group(1)
                    lines[i] = (f"  {key}: {value}" if value else f"  {key}:") + suffix
                    return "\n".join(lines)
        new_line = f"  {key}: {value}" if value else f"  {key}:"
        if block_at < 0:
            lines.append(f"{block}:")
            lines.append(new_line)
        else:
            lines.insert((last_in_block if last_in_block >= 0 else block_at) + 1, new_line)
        return "\n".join(lines)
    transform_file(p, edit)
