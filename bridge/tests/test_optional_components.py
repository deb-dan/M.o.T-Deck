"""Start-script pins for the two optional creative/training components.

These are OUR side of the seam (contract_tests/test_seam.py pins upstream's). Both facts
here came from a live failure on Debi's Mac:

  * ComfyUI crashed with FileNotFoundError on <base>/custom_nodes the first time it was
    started against a fresh --base-directory, because upstream's prestartup lists that
    directory without creating it.
  * Unsloth's upstream default port 8888 is also the port of a SEPARATE, user-installed
    Unsloth app — and every start clears its port listener-scoped, i.e. it killed that
    other app. Our port must therefore never be 8888 anywhere.

Run: data/bridge-venv/bin/python -m pytest bridge/tests/test_optional_components.py -q
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
START = (ROOT / "scripts" / "start_component.sh").read_text(errors="replace")


def _comfy_branch() -> str:
    start = START.index("\n  comfyui)")
    end = START.index("\n  unsloth)", start)
    return START[start:end]


def test_comfyui_creates_the_base_tree_before_launch():
    """custom_nodes is the load-bearing one (the crash); user is required for the sqlite
    db we point --database-url at, since sqlalchemy will not create a missing parent."""
    b = _comfy_branch()
    assert "for d in custom_nodes user models models/checkpoints input output; do" in b, (
        "the pre-create loop moved or changed shape")
    assert 'mkdir -p "$ROOT/data/comfyui/${d}"' in b, (
        "the mkdir must brace ${d} (bash 3.2 nounset + the glued-token rule) and stay "
        "under our own data dir")
    # ...and it must happen BEFORE the launch, not after.
    assert b.index("mkdir -p") < b.index("CU_CMD=("), (
        "the tree is created after the argv is built — ordering is the whole fix")


def test_comfyui_keeps_every_write_out_of_vendor():
    b = _comfy_branch()
    assert '--base-directory "$ROOT/data/comfyui"' in b
    assert '--database-url "sqlite:///$ROOT/data/comfyui/user/comfyui.db"' in b, (
        "--database-url is NOT covered by --base-directory upstream (its default is "
        "computed from cli_args.py's own __file__), so without this the db lands in "
        "vendor/comfyui/user/")
    assert "cd vendor/comfyui" in b, "main.py still resolves its imports from the repo root"


def test_unsloth_port_is_never_8888():
    """8888 belongs to Debi's standalone Unsloth app; our listener-scoped port clear
    would kill it on every start."""
    manifest = yaml.safe_load((ROOT / "harness.yaml").read_text())
    assert manifest["components"]["unsloth"]["port"] == 8899
    assert "US_PORT=8899" in START, "the awk fallback must mirror the manifest"
    for rel in ("scripts/start_component.sh", "scripts/install_component.sh",
                "bridge/app.py", "app/main.swift"):
        src = (ROOT / rel).read_text(errors="replace")
        for line in src.splitlines():
            if "8888" in line and not line.lstrip().startswith(("#", "//")):
                raise AssertionError(f"{rel} still carries 8888 outside a comment: {line.strip()}")


def test_port_is_read_from_the_manifest_not_hardcoded():
    for name, fallback in (("comfyui", "CU_PORT=8188"), ("unsloth", "US_PORT=8899")):
        var = "CU_PORT" if name == "comfyui" else "US_PORT"
        assert f"{var}=$(_manifest_value components.{name}.port int)" in START, \
            f"{name}'s port is no longer read through the typed harness.yaml boundary"
        assert fallback in START
