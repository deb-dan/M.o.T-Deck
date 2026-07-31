"""Isolated unit tests for the app-owned-model delete guard (_deletable_target).

Run: python3 bridge/tests/test_model_delete.py   (from repo root)

Covers the PURE safety predicate that decides whether a registry entry may have its
files deleted:
  * source in {download, local} whose path is UNDER data/models/  → deletable (target
    = the model's own folder, whether path is a file or the dir itself).
  * source = lmstudio-import / jan-import / unknown                → REFUSED (imports
    the harness does not own).
  * path traversal / a path resolving OUTSIDE data/models/         → REFUSED.
  * missing path                                                    → REFUSED.
The live-model / aux interaction (eject-before-delete) is exercised by the endpoint,
not this pure predicate — see the ⚠️ note in the handoff.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
# Neutralize any SOCKS proxy env so importing the app's httpx client succeeds.
for _v in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
    os.environ.pop(_v, None)
from bridge import app  # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


ROOT = "/tmp/harnesstest"
MODELS = os.path.join(ROOT, "data", "models")


def entry(source, relpath):
    """relpath is under MODELS unless it starts with '/' (absolute, for escape tests)."""
    p = relpath if relpath.startswith("/") else os.path.join(MODELS, relpath)
    return {"id": "m", "source": source, "path": p}


# ── deletable: app-owned under data/models/ ──────────────────────────────────
t, why = app._deletable_target(entry("download", "my-model/model-Q4.gguf"), MODELS)
check("download gguf file → target is its folder",
      t == os.path.realpath(os.path.join(MODELS, "my-model")) and why is None)

t, why = app._deletable_target(entry("local", "qwen-35b/model.gguf"), MODELS)
check("local gguf file → target is its folder",
      t == os.path.realpath(os.path.join(MODELS, "qwen-35b")) and why is None)

t, why = app._deletable_target(entry("download", "mlx-repo-leaf"), MODELS)
check("download mlx DIR → target is the dir itself",
      t == os.path.realpath(os.path.join(MODELS, "mlx-repo-leaf")) and why is None)

t, why = app._deletable_target(entry("download", "leaf/sub/model.gguf"), MODELS)
check("nested file → target is the FIRST folder under models_root",
      t == os.path.realpath(os.path.join(MODELS, "leaf")) and why is None)

# ── refused: read-only imports ───────────────────────────────────────────────
t, why = app._deletable_target(
    {"id": "x", "source": "lmstudio-import", "path": "/Users/me/.lmstudio/models/a/b.gguf"}, MODELS)
check("lmstudio-import → refused", t is None and "read-only" in why)

t, why = app._deletable_target(
    {"id": "x", "source": "jan-import", "path": os.path.join(MODELS, "j/model.gguf")}, MODELS)
check("jan-import → refused even if path is under models_root", t is None and why)

t, why = app._deletable_target({"id": "x", "source": None, "path": "p"}, MODELS)
check("unknown/None source → refused", t is None and why)

# ── refused: path escapes / traversal / missing ──────────────────────────────
t, why = app._deletable_target(entry("download", "../../etc/passwd"), MODELS)
check("traversal above models_root → refused", t is None and "outside" in why)

t, why = app._deletable_target(entry("local", "/etc/passwd"), MODELS)
check("absolute path outside models_root → refused", t is None and "outside" in why)

t, why = app._deletable_target({"id": "x", "source": "download", "path": MODELS}, MODELS)
check("path == models_root itself (no folder) → refused", t is None and why)

t, why = app._deletable_target({"id": "x", "source": "download", "path": ""}, MODELS)
check("empty path → refused", t is None and "path" in why)

t, why = app._deletable_target({"id": "x", "source": "download"}, MODELS)
check("missing path key → refused", t is None and why)

# ── target is always strictly under models_root ──────────────────────────────
t, _ = app._deletable_target(entry("local", "safe/model.gguf"), MODELS)
real_root = os.path.realpath(MODELS)
check("deletable target is strictly under models_root",
      t is not None and t.startswith(real_root + os.sep) and t != real_root)

print()
if FAILS:
    print(f"{len(FAILS)} FAILED:", *FAILS)
    sys.exit(1)
print("all model-delete guard tests passed")
