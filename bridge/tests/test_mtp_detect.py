"""MTP speculative-decoding detection + repo persistence.

Two things are pinned here:

1. `_gguf_registry_entry` / `_mlx_registry_entry` persist the SOURCE REPO. MTP
   models are published as "<org>/…-MTP-GGUF" while the per-file registry id
   often carries no MTP marker (e.g. Qwen3.5-9B-Q4_0). Without the repo the
   runner's gate can't see that the model is MTP, and you silently get
   MTP-without-acceleration (found live 2026-08-06).

2. The shell gate's decision table, mirrored here as a pure function so the
   conservative behaviour is testable: spec flags must NEVER be added to a model
   with no MTP evidence (they fail the load on a model without MTP heads), and
   an explicit runner.spec_mtp must win over detection.

Run: python3 bridge/tests/test_mtp_detect.py
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = []


def check(name, got, want):
    if got != want:
        fails.append(f"{name}: got {got!r}, want {want!r}")


# ── 1. registry entries persist `repo` ───────────────────────────────────────
# Load the two pure builders out of app.py without importing the whole module
# (it opens network clients at import time).
src = open(os.path.join(ROOT, "bridge", "app.py")).read()
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


# ── 2. the detection decision table (mirrors start_component.sh) ─────────────
def spec_enabled(model_id: str, repo: str, override: str = "auto") -> bool:
    """Pure mirror of the shell gate: on/off win outright; auto matches MTP
    case-insensitively in the id OR the repo; anything else → no flags."""
    ov = (override or "auto").strip().lower()
    if ov in ("on", "true", "yes", "1"):
        return True
    if ov in ("off", "false", "no", "0"):
        return False
    hay = f"{model_id or ''}\n{repo or ''}".lower()
    return "mtp" in hay


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
    ("spec_mtp:", "runner.spec_mtp override must be read"),
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
