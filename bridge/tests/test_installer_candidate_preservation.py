"""Execute production extraction/publication blocks against tiny local archives."""
import hashlib
import io
import os
from pathlib import Path
import subprocess
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('lane', ['goose', 'opencode'])
@pytest.mark.parametrize('failure', ['extract', 'run', 'none'])
def test_candidate_must_extract_and_run_before_replacing_installed_binary(tmp_path, lane, failure):
    dest = tmp_path / 'installed'
    (dest / 'bin').mkdir(parents=True)
    binary = dest / 'bin' / lane
    binary.write_bytes(b'original working binary')
    candidate = b'#!/bin/sh\n' + (b'exit 1\n' if failure == 'run' else b'echo 1.48.0\n')
    archive = tmp_path / 'fixture.tgz'
    if failure == 'extract':
        archive.write_bytes(b'broken archive')
    else:
        with tarfile.open(archive, 'w:gz') as tf:
            info = tarfile.TarInfo('./goose' if lane == 'goose' else 'package/bin/opencode')
            info.size, info.mode = len(candidate), 0o755
            tf.addfile(info, io.BytesIO(candidate))
    source = (ROOT / 'scripts' / f'install_{lane}.sh').read_text()
    helper = ''
    if lane == 'goose':
        helper = source[source.index('goose_run() {'):source.index('# ── --check')]
        block = source[source.index('  GOOSE_STAGE='):source.index('  say "installed: goose')]
    else:
        helper = source[source.index('opencode_run() {'):source.index('# ── pin reader')]
        block = source[source.index('  OPENCODE_STAGE='):source.index('  say "installed: opencode')]
    script = '''set -euo pipefail
say() { :; }
warn() { :; }
die() { echo "$*" >&2; exit 1; }
sha256_of() { shasum -a 256 "$1" | awk '{print $1}'; }
''' + helper + '\nrun_candidate() {\n' + block + '\n}\nrun_candidate\n'
    result = subprocess.run(['/bin/bash', '-c', script], cwd=tmp_path,
        env=dict(os.environ, DEST=str(dest), BIN=str(binary), TGZ=str(archive), tgz=str(archive),
                 HOMEDIR=str(dest / 'home'), LOG=str(tmp_path / 'log'), GOOSE_TAG='v1.48.0',
                 GOOSE_BIN_SHA256=hashlib.sha256(candidate).hexdigest(), pin='1.48.0'),
        capture_output=True, text=True, timeout=15)
    assert (result.returncode == 0) == (failure == 'none'), result.stderr
    assert binary.read_bytes() == (candidate if failure == 'none' else b'original working binary')
    assert not list(dest.glob(f'.{lane}-install.*'))
