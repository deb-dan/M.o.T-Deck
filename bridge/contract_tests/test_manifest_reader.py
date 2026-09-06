"""U88: the shell launcher consumes YAML semantics, not awk-shaped text."""

from pathlib import Path
import os
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
READER = ROOT / "scripts" / "read_manifest.py"


def _read(tmp_path, text, path="runner.value", kind="str"):
    (tmp_path / "motdeck.yaml").write_text(text)
    return subprocess.run([sys.executable, str(READER), str(tmp_path), path, kind],
                          text=True, capture_output=True)


def test_null_and_empty_are_empty_but_quoted_null_is_text(tmp_path):
    for token in ("null", "Null", "NULL", "~", ""):
        p = _read(tmp_path, f"runner:\n  value: {token}\n")
        assert p.returncode == 0 and p.stdout == ""
    for token in ('"null"', "'null'"):
        p = _read(tmp_path, f"runner:\n  value: {token}\n")
        assert p.returncode == 0 and p.stdout == "null"


def test_strings_keep_hash_spaces_colons_and_escapes(tmp_path):
    p = _read(tmp_path, 'runner:\n  value: "https://host/a:b # literal\\nnext"\n')
    assert p.returncode == 0
    assert p.stdout == "https://host/a:b # literal\nnext"


def test_types_are_exact_and_errors_never_echo_secret_values(tmp_path):
    assert _read(tmp_path, "runner:\n  value: 6767\n", kind="int").stdout == "6767"
    assert _read(tmp_path, "runner:\n  value: true\n", kind="bool").stdout == "true"
    bad = _read(tmp_path, "runner:\n  value: super-secret-value\n", kind="int")
    assert bad.returncode == 2 and "super-secret-value" not in bad.stderr


def test_symlink_manifest_is_refused(tmp_path):
    real = tmp_path / "real.yaml"
    real.write_text("runner:\n  value: safe\n")
    os.symlink(real, tmp_path / "motdeck.yaml")
    p = subprocess.run([sys.executable, str(READER), str(tmp_path),
                        "runner.value", "str"], text=True, capture_output=True)
    assert p.returncode == 2 and p.stdout == ""


def test_start_script_has_one_semantic_reader_boundary():
    src = (ROOT / "scripts" / "start_component.sh").read_text()
    assert "_manifest_value" in src and "scripts/read_manifest.py" in src
    production = src.split("# ── PORT OWNERSHIP", 1)[1]
    assert "_normalize_yaml_scalar" not in production, (
        "a typed YAML value was sent back through the legacy text normalizer; "
        "that collapses the explicit string 'null' and creates a second parser boundary"
    )
