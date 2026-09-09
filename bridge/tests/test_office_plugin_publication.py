"""Run the Office plugin installer with pinned local fixture bytes, never the live install."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('failure', ['sdk', 'layout', 'guid', 'publish', 'crash', 'none'])
def test_complete_candidate_required_before_installed_plugin_changes(tmp_path, failure):
    dest = tmp_path / 'installed'
    cache = tmp_path / 'cache'
    cache.mkdir()
    for rel, data in {'ai/original': b'old plugin', 'v1/plugins.js': b'old sdk',
                      'INSTALLED': b'old receipt', 'SOURCES.txt': b'old sources'}.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    original = {str(p.relative_to(dest)): p.read_bytes() for p in dest.rglob('*') if p.is_file()}
    sdk = {'plugins.js': b'old sdk', 'plugins-ui.js': b'fixture UI', 'plugins.css': b'fixture CSS'}
    for name, data in sdk.items():
        (dest / 'v1' / name).write_bytes(data)
        original['v1/' + name] = data
    if failure == 'sdk':
        (dest / 'v1/plugins.css').unlink()
        original.pop('v1/plugins.css')
    guid = 'asc.{9DC93CDB-B576-4F0C-B55E-FCC9C48DD007}'
    with zipfile.ZipFile(cache / 'ai.plugin', 'w') as z:
        z.writestr('config.json', json.dumps({'guid': 'bad' if failure == 'guid' else guid, 'version': '3.2.2'}))
        z.writestr('index.html', '<script src="./../v1/plugins.js"></script>')
        z.writestr('scripts/engine/local_storage.js', '// fixture')
        if failure != 'layout':
            z.writestr('scripts/engine/providers/provider.js', '// fixture')
    source = (ROOT / 'scripts/install_oo_ai_plugin.sh').read_text()
    # Only fixture pins differ; every installer operation executes unchanged.
    source = re.sub(r'PLUGIN_SHA256="[a-f0-9]+"',
        'PLUGIN_SHA256="' + hashlib.sha256((cache / 'ai.plugin').read_bytes()).hexdigest() + '"', source)
    for name, data in sdk.items():
        key = 'SDK_SHA_' + name.replace('.', '_').replace('-', '_')
        source = re.sub(key + r'="[a-f0-9]+"', key + '="' + hashlib.sha256(data).hexdigest() + '"', source)
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    script = scripts / 'install_oo_ai_plugin.sh'
    script.write_text(source)
    # Wrap the real publication helper, recording each move and injecting one
    # ordinary failure. Candidate verification and recovery execute unchanged.
    helper = scripts / 'oo_plugin_install.py'
    helper.write_text("import importlib.util, os\nfrom pathlib import Path\n"
        + "spec=importlib.util.spec_from_file_location('publisher', "
        + repr(str(ROOT / 'scripts/oo_plugin_install.py')) + ")\n"
        + "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\n"
        + "original=m._move\n"
        + "def move(source,destination):\n"
        + "    dest=Path(os.environ['OOP_DEST'])\n"
        + "    if source in [dest/x for x in m.ITEMS[:-1]] or destination in [dest/x for x in m.ITEMS[:-1]]:\n"
        + "        assert not (dest/'INSTALLED').exists(), 'premature receipt'\n"
        + "    if destination == dest/'INSTALLED':\n"
        + "        assert all((dest/x).exists() for x in m.ITEMS[:-1]), 'incomplete publication'\n"
        + "    if source.name=='v1' and source.parent.name=='new' and os.environ.get('FAIL_PUBLISH')=='1':\n"
        + "        raise OSError('injected publication failure')\n"
        + "    if source.name=='ai' and source.parent.name=='new' and os.environ.get('FAIL_PUBLISH')=='crash':\n"
        + "        original(source,destination)\n"
        + "        os.kill(os.getppid(),9);os.kill(os.getpid(),9)\n"
        + "    return original(source,destination)\n"
        + "m._move=move\nm.main()\n")
    env = dict(os.environ, OOP_DEST=str(dest), OOP_ZIP_DIR=str(cache), OOP_OFFLINE='1',
               FAIL_PUBLISH='1' if failure == 'publish' else ('crash' if failure == 'crash' else ''))
    result = subprocess.run(['/bin/bash', str(script), '--force'], cwd=tmp_path,
        env=env, capture_output=True, text=True, timeout=20)
    if failure == 'crash':
        assert result.returncode == -9
        assert list(dest.glob('.plugin-install.*'))
        result = subprocess.run(['/bin/bash', str(script), '--force'], cwd=tmp_path,
            env=dict(env, FAIL_PUBLISH=''), capture_output=True, text=True, timeout=20)
        failure = 'none'
    assert (result.returncode == 0) == (failure == 'none'), result.stdout + result.stderr
    after = {str(p.relative_to(dest)): p.read_bytes() for p in dest.rglob('*') if p.is_file() and p.name != '.install.lock'}
    if failure != 'none':
        assert after == original, result.stdout + result.stderr
    else:
        assert (dest / 'ai/config.json').is_file()
        assert 'plugin_version 3.2.2' in (dest / 'INSTALLED').read_text()
        assert not (dest / 'ai/original').exists()
    assert not list(dest.glob('.plugin-install.*'))
    assert not (dest / '.install-lock').exists()
