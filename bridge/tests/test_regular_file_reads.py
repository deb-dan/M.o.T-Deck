"""A special state-file entry must be refused without waiting for a FIFO writer."""
import subprocess
import sys

import pytest


@pytest.mark.parametrize("module,call,filename", [
    ("bridge.core.ownership", "M._read(path)", "state"),
    ("scripts.reconcile_hermes_whatsapp", "M._read_optional(path)", "state"),
    ("scripts.read_manifest", "M._read_regular(path)", "state"),
    ("bridge.core.localsecrets", "M._read_regular(path)", "state"),
    ("bridge.yamlfile", "M._read_regular(str(path))", "state"),
    ("bridge.core.modelid", "M._read_regular_json(path)", "state"),
    ("bridge.core.modelreg", "M._read_registry_text(path)", "state"),
    ("bridge.core.modeldelete", "M._read_journal(path)", "state"),
    ("bridge.routers.gooseui", "(setattr(M, 'ROOT', root), M._read_runtime_unlocked())[1]",
     "data/goose-ui.runtime.json"),
])
def test_nonregular_state_does_not_block(tmp_path, module, call, filename):
    code = '''
import importlib, os, sys
from pathlib import Path
M = importlib.import_module(sys.argv[1])
root = Path(sys.argv[2]); path = root / sys.argv[3]
path.parent.mkdir(parents=True, exist_ok=True)
os.mkfifo(path)
try:
    result = eval(sys.argv[4])
except (OSError, ValueError):
    pass
else:
    assert result is None or isinstance(result, dict), result
'''
    # subprocess.run reaps only its own child if the regression wedges this read.
    result = subprocess.run([sys.executable, "-c", code, module, str(tmp_path), filename, call],
                            capture_output=True, text=True, timeout=2)
    assert result.returncode == 0, result.stderr
