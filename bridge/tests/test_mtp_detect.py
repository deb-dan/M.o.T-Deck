"""MTP speculative-decoding detection + repo persistence.

Two things are pinned here:

1. `_gguf_registry_entry` / `_mlx_registry_entry` persist the SOURCE REPO. MTP
   models are published as "<org>/…-MTP-GGUF" while the per-file registry id
   often carries no MTP marker (e.g. Qwen3.5-9B-Q4_0). Without the repo the
   runner's gate can't see that the model is MTP, and you silently get
   MTP-without-acceleration (found live 2026-08-06).

2. The shell gate's decision table, executed from production Bash so the
   conservative behaviour is testable: spec flags must NEVER be added to a model
   with no MTP evidence (they fail the load on a model without MTP heads), and
   an explicit runner.spec_mtp must win over detection.

Run: python3 bridge/tests/test_mtp_detect.py
"""
import ast
import os
import subprocess
from pathlib import Path
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ⚠️ THE APP LAYER IS NO LONGER ONE FILE (router/core split, 2026-08-28).
# bridge/app.py is a FACADE over bridge/core/*.py + bridge/routers/*.py, so the
# source-text assertions below read bridge/appsrc.py's assembled view of the whole
# app layer instead of one file. Read bridge/appsrc.py's header for why the
# assertions are source-text in the first place and why order is part of it.
import sys as _sys                                          # noqa: E402
_sys.path.insert(0, str(ROOT))                              # noqa: E402
from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402

fails = []


def check(name, got, want):
    if got != want:
        fails.append(f"{name}: got {got!r}, want {want!r}")


# ── 1. registry entries persist `repo` ───────────────────────────────────────
# Load the two pure builders out of app.py without importing the whole module
# (it opens network clients at import time).
src = _APP_SOURCE
tree = ast.parse(src)
ns = {}
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in (
            "_gguf_registry_entry", "_mlx_registry_entry"):
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<app>", "exec"), ns)

assert "_gguf_registry_entry" in ns, "could not extract _gguf_registry_entry"

gguf_entry = ns["_gguf_registry_entry"]({
    "model_id": "Qwen3.5-9B-Q4_0",
    "repo": "unsloth/Qwen3.5-9B-MTP-GGUF",
    "files": [{"dest": "/models/Qwen3.5-9B-Q4_0/Qwen3.5-9B-Q4_0.gguf", "total": 5_200_000_000}],
})
check("gguf repo persisted", gguf_entry["repo"], "unsloth/Qwen3.5-9B-MTP-GGUF")
check("gguf id unchanged", gguf_entry["id"], "Qwen3.5-9B-Q4_0")
check("gguf source", gguf_entry["source"], "download")

# a download without repo metadata must yield None, never a crash or ""
no_repo = ns["_gguf_registry_entry"]({
    "model_id": "plain-Q4_K_M", "files": [{"dest": "/m/plain.gguf", "total": 1}]})
check("missing repo → None", no_repo["repo"], None)
check("empty repo → None", ns["_gguf_registry_entry"](
    {"model_id": "x", "repo": "", "files": [{"dest": "/m/x.gguf", "total": 1}]})["repo"], None)


# ── 2. the production detection decision table ─────────────
sh = Path(ROOT, "scripts", "start_component.sh").read_text()
start = sh.index('    SPEC_ARGS=()')
end = sh.index('    if [[ "$MTP_HIT" == "1" ]]', start)
detection = sh[start:end]


def spec_enabled(model_id: str, repo: str, override: str = "auto") -> bool:
    """Execute the actual launcher decision without its process-launching branches."""
    script = '_manifest_value() { printf "%s" "$TEST_OVERRIDE"; }\n' + detection + '\nprintf "%s" "$MTP_HIT"\n'
    result = subprocess.run(['/bin/bash', '-c', script], capture_output=True,
        text=True, timeout=5, env=dict(os.environ, R_MODEL=model_id or '',
                                     MODEL_REPO=repo or '', TEST_OVERRIDE=override or ''))
    assert result.returncode == 0, result.stderr
    assert result.stdout in ('0', '1'), result.stdout
    return result.stdout == '1'


# the live case that failed: MTP only in the repo name
check("repo-only MTP detected", spec_enabled("Qwen3.5-9B-Q4_0", "unsloth/Qwen3.5-9B-MTP-GGUF"), True)
# id-based detection still works (the original behaviour)
check("id MTP detected", spec_enabled("Qwen3.6-35B-oQ4e-mtp-XL-mlx", ""), True)
check("id MTP uppercase", spec_enabled("SOME-MTP-MODEL", ""), True)
# CONSERVATIVE: no MTP evidence anywhere → never add the flags
check("plain model → no flags", spec_enabled("gemma-4-31B-it-uncensored-biproj-q4_k_m", ""), False)
check("plain model, plain repo", spec_enabled("Qwen3.5-9B-Q4_0", "unsloth/Qwen3.5-9B-GGUF"), False)
check("no repo metadata", spec_enabled("plain-Q4_K_M", None), False)
# overrides beat detection in both directions
check("override on, no evidence", spec_enabled("plain", "", "on"), True)
check("override off, MTP repo", spec_enabled("x", "org/Y-MTP-GGUF", "off"), False)
check("override true/false words", (spec_enabled("p", "", "true"), spec_enabled("p", "org/MTP", "false")), (True, False))
check("unknown override → auto", spec_enabled("p", "org/z-MTP-GGUF", "banana"), True)
check("empty override → auto", spec_enabled("p", "", ""), False)


# ── 3. the shell script actually reads/uses both signals ────────────────────
sh = open(os.path.join(ROOT, "scripts", "start_component.sh")).read()
for needle, why in [
    ('print(m.get("repo") or "")', "PYRESOLVE must emit the repo"),
    ("MODEL_REPO=", "the repo must be captured into a shell var"),
    ('MODEL_REPO" =~ [Mm][Tt][Pp]', "the gate must match MTP in the repo"),
    ('R_MODEL" =~ [Mm][Tt][Pp]', "the gate must still match MTP in the id"),
    ("_manifest_value runner.spec_mtp str", "runner.spec_mtp override must be read"),
    ("SPEC_ARGS=()", "spec flags must live in a separate array (retry-able)"),
    ("--spec-type draft-mtp", "the MTP flag set must be present"),
    ("Retrying without them", "a failed spec launch must self-heal"),
]:
    if needle not in sh:
        fails.append(f"start_component.sh: {why} (missing {needle!r})")

if fails:
    print("FAIL")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_mtp_detect: ALL PASS")
