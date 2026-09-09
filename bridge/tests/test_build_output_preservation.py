"""Exercise the real builder's output routing without compiling/download side effects."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('options', [['--dmg', '--output-dir', 'builds/new candidate'],
                                   ['--output-dir', 'builds/new candidate', '--dmg']])
def test_new_output_preserves_old_builds_and_refuses_reuse(tmp_path, options):
    (tmp_path/'scripts').mkdir()
    shutil.copy2(ROOT/'scripts/build_app.sh', tmp_path/'scripts/build_app.sh')
    (tmp_path/'app').mkdir()
    (tmp_path/'VERSION').write_text('1.5.93\n')
    old = {'dist/MOT Deck.dmg': b'previous disk image',
           'dist/MOT Deck.app/Contents/MacOS/MOTDeck': b'previous app',
           'dist/.fatseed/keep': b'previous staging data'}
    for name, body in old.items():
        path = tmp_path/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    commands = tmp_path/'bin'
    commands.mkdir()
    for name, body in {
        'swiftc': '#!/bin/bash\nwhile [[ $# -gt 0 ]]; do\n if [[ "$1" == -o ]]; then shift; printf binary > "$1"; exit; fi\n shift\ndone\nexit 1\n',
        'hdiutil': '#!/bin/bash\nfor last in "$@"; do :; done\nprintf new-dmg > "$last"\n',
    }.items():
        path = commands/name
        path.write_text(body)
        path.chmod(0o755)
    env = dict(os.environ, PATH=str(commands)+':/usr/bin:/bin')
    argv = ['bash', str(tmp_path/'scripts/build_app.sh'), *options]
    result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout+result.stderr
    new = tmp_path/'builds/new candidate'
    assert (new/'MOT Deck.dmg').read_bytes() == b'new-dmg'
    assert (new/'MOT Deck.app/Contents/MacOS/MOTDeck').read_bytes() == b'binary'
    assert {name: (tmp_path/name).read_bytes() for name in old} == old
    again = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=10)
    assert again.returncode != 0
    assert 'must be new' in again.stderr
    assert (new/'MOT Deck.dmg').read_bytes() == b'new-dmg'
    assert {name: (tmp_path/name).read_bytes() for name in old} == old
