"""Kill real publication/recovery processes; compare every preserved asset byte."""
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

HELPER = Path(__file__).resolve().parents[2] / "scripts/oo_plugin_install.py"
spec = importlib.util.spec_from_file_location("office_publisher", HELPER)
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for name in publisher.ITEMS
            for p in ([root/name] if (root/name).is_file() else (root/name).rglob('*'))
            if p.is_file()}


def payload(root, label):
    for rel in ('ai/index.html', 'ai/nested/config.json', 'v1/plugins.js',
                'v1/plugins-ui.js', 'SOURCES.txt', 'INSTALLED'):
        p = root/rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(label + ':' + rel)


PROGRAM = '''
import importlib.util,os,signal,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('publisher',sys.argv[1])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
dest,stage=Path(sys.argv[2]),Path(sys.argv[3])
fd=m._lock_fd(dest)
point=sys.argv[4]
original_move=m._move
count=0
def move(source,destination):
    global count
    original_move(source,destination)
    count+=1
    if point==str(count): os.kill(os.getpid(),signal.SIGKILL)
m._move=move
original_write=m._write
def write(stage,record):
    original_write(stage,record)
    if point==record['phase']: os.kill(os.getpid(),signal.SIGKILL)
m._write=write
if sys.argv[5]=='publish':
    m.publish(dest,stage)
    m.cleanup(dest,stage)
else:
    m.recover(dest)
'''


def child(dest, stage, point, operation='publish'):
    return subprocess.run([sys.executable, '-c', PROGRAM, str(HELPER), str(dest),
                           str(stage), str(point), operation], capture_output=True,
                          text=True, timeout=10)


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('point', ['prepared', '1', '2', '3', '4', 'committed', '5', '6', '7', '8', '9'])
def test_killed_publication_recovers_and_can_install_again(tmp_path, existing, point):
    dest = tmp_path/'installed'
    dest.mkdir()
    if existing:
        payload(dest, 'original')
    before = files(dest)
    stage = publisher.prepare(dest)
    payload(stage/'new', 'candidate')
    candidate = files(stage/'new')
    result = child(dest, stage, point)
    assert result.returncode in (0, -signal.SIGKILL), result.stderr
    # For a first install there are four publication moves, versus eight for a
    # replacement. A kill during cleanup follows the durable commit marker.
    committed = point == 'committed' or (point.isdigit() and int(point) > (8 if existing else 4))
    publisher.recover(dest)
    assert files(dest) == (candidate if committed else before)
    assert not list(dest.glob('.plugin-install.*'))
    assert not list(dest.glob('.plugin-cleanup.*'))
    # Recovery retired the crashed transaction; an actual subsequent publication
    # must succeed, rather than merely displaying an honest refusal forever.
    stage = publisher.prepare(dest)
    payload(stage/'new', 'next installation')
    wanted = files(stage/'new')
    assert child(dest, stage, 'none').returncode == 0
    assert files(dest) == wanted


@pytest.mark.parametrize('point', [1, 2, 3, 4, 5])
def test_recovery_can_itself_be_killed_and_resumed(tmp_path, point):
    dest = tmp_path/'installed'
    dest.mkdir()
    payload(dest, 'original')
    before = files(dest)
    stage = publisher.prepare(dest)
    payload(stage/'new', 'candidate')
    assert child(dest, stage, 8).returncode == -signal.SIGKILL
    result = child(dest, stage, point, 'recover')
    assert result.returncode == -signal.SIGKILL, result.stderr
    publisher.recover(dest)
    assert files(dest) == before


def test_kernel_lock_survives_exec_and_is_released_on_death(tmp_path):
    dest = tmp_path/'installed'
    ready = tmp_path/'ready'
    script = tmp_path/'holder.sh'
    script.write_text('echo ready > ' + str(ready) + '\nexec sleep 10\n')
    process = subprocess.Popen([sys.executable, str(HELPER), 'run', str(dest), str(script)])
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            assert process.poll() is None
            time.sleep(.01)
        assert ready.exists()
        with pytest.raises(ValueError, match='still active'):
            publisher._lock_fd(dest)
        process.kill()
        process.wait(timeout=5)
        fd = publisher._lock_fd(dest)
        os.close(fd)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_foreign_replacement_is_preserved_with_original_recovery_files(tmp_path):
    dest = tmp_path/'installed'
    dest.mkdir()
    payload(dest, 'original')
    stage = publisher.prepare(dest)
    payload(stage/'new', 'candidate')
    assert child(dest, stage, 5).returncode == -signal.SIGKILL
    # Simulate a different owner replacing the published directory, rather than
    # deleting somebody else's changes merely to complete our rollback.
    (dest/'ai').rename(tmp_path/'displaced')
    (dest/'ai').mkdir()
    (dest/'ai/user-file').write_text('user bytes')
    with pytest.raises(ValueError, match='changed outside'):
        publisher.recover(dest)
    assert (dest/'ai/user-file').read_text() == 'user bytes'
    assert (stage/'old/ai/index.html').read_text() == 'original:ai/index.html'


def test_surviving_installer_child_keeps_lock_until_it_exits(tmp_path):
    dest, ready, release = tmp_path/'installed', tmp_path/'ready', tmp_path/'release'
    worker = tmp_path/'worker.py'
    worker.write_text('import pathlib,time\n'
        + 'ready=pathlib.Path(' + repr(str(ready)) + ')\n'
        + 'release=pathlib.Path(' + repr(str(release)) + ')\n'
        + 'ready.touch()\nend=time.monotonic()+8\n'
        + 'while not release.exists() and time.monotonic()<end: time.sleep(.01)\n')
    script = tmp_path/'holder.sh'
    import shlex
    script.write_text(shlex.quote(sys.executable)+' '+shlex.quote(str(worker))+' &\nwait\n')
    process = subprocess.Popen([sys.executable, str(HELPER), 'run', str(dest), str(script)])
    try:
        deadline = time.monotonic()+5
        while not ready.exists() and time.monotonic()<deadline:
            assert process.poll() is None
            time.sleep(.01)
        assert ready.exists()
        process.kill()
        process.wait(timeout=5)
        with pytest.raises(ValueError, match='still active'):
            publisher._lock_fd(dest)
        release.touch()
        while time.monotonic()<deadline:
            try:
                fd = publisher._lock_fd(dest)
            except ValueError:
                time.sleep(.01)
            else:
                os.close(fd)
                break
        else:
            pytest.fail('finished installer child stranded the kernel lock')
    finally:
        release.touch()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_kill_before_first_journal_does_not_strand_next_install(tmp_path):
    stage = tmp_path/(publisher.PREFIX+'interrupted')
    stage.mkdir()
    (stage/'.journal-incomplete').write_text('{')
    publisher.recover(tmp_path)
    assert not stage.exists()
