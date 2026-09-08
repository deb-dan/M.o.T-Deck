"""Rescanning local chat artifacts must not create ambiguous model ids."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location('local_identity_seed', ROOT / 'scripts/seed_registry.py')
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)


def row(tmp_path, name, ident='chat', source='download', **extra):
    path = tmp_path / name
    path.write_bytes(b'fixture')
    return dict(id=ident, source=source, format='gguf', path=str(path), **extra)


def test_download_and_rescan_of_same_artifact_keep_the_authoritative_row(tmp_path):
    downloaded = row(tmp_path, 'model.gguf', settings={'temperature': .3}, ctx=32768)
    fresh = dict(downloaded, source='local', settings=None, ctx=None)
    assert seed.merge([downloaded], [], [], [fresh]) == [downloaded]
    alias = tmp_path / 'alias.gguf'
    alias.symlink_to(downloaded['path'])
    assert seed.merge([downloaded], [], [], [dict(fresh, path=str(alias), id='scanned-name')]) == [downloaded]


def test_different_projectors_are_distinct_artifacts(tmp_path):
    first = row(tmp_path, 'main.gguf', mmproj=str(tmp_path / 'p1.gguf'))
    (tmp_path / 'p1.gguf').write_bytes(b'one')
    (tmp_path / 'p2.gguf').write_bytes(b'two')
    other = dict(first, source='local', mmproj=str(tmp_path / 'p2.gguf'))
    assert [r['id'] for r in seed.merge([first], [], [], [other])] == ['chat', 'chat-local']


def test_distinct_local_row_keeps_its_own_settings_on_repeated_scan(tmp_path):
    downloaded = row(tmp_path, 'download.gguf', settings={'temperature': .2}, ctx=32768)
    scanned = row(tmp_path, 'local.gguf', source='local')
    first = seed.merge([downloaded], [], [], [scanned])
    assert [r['id'] for r in first] == ['chat', 'chat-local']
    assert 'settings' not in first[1] and 'ctx' not in first[1]
    first[1].update(settings={'temperature': .8}, ctx=8192, hidden=True)
    second = seed.merge(first, [], [], [scanned])
    assert second == first
    assert seed.merge(second, [], [], [scanned]) == second


def test_suffix_collision_never_replaces_existing_download(tmp_path):
    first = row(tmp_path, 'one.gguf')
    occupied = row(tmp_path, 'two.gguf', ident='chat-local')
    scanned = row(tmp_path, 'three.gguf', source='local')
    result = seed.merge([first, occupied], [], [], [scanned])
    assert [r['id'] for r in result] == ['chat', 'chat-local', 'chat-local-2']
    assert result[:2] == [first, occupied]


def test_same_scan_artifact_is_not_added_twice_under_aliases(tmp_path):
    first = row(tmp_path, 'one.gguf', source='local')
    assert seed.merge([], [], [], [first, dict(first, id='alias')]) == [first]


def test_collision_does_not_steal_another_files_natural_name(tmp_path):
    downloaded = row(tmp_path, 'download.gguf')
    colliding = row(tmp_path, 'collision.gguf', source='local')
    natural = row(tmp_path, 'natural.gguf', ident='chat-local', source='local')
    for scanned in ([colliding, natural], [natural, colliding]):
        result = seed.merge([downloaded], [], [], scanned)
        by_path = {m['path']: m['id'] for m in result}
        assert by_path[colliding['path']] == 'chat-local-2'
        assert by_path[natural['path']] == 'chat-local'


def test_existing_artifact_id_and_settings_survive_new_natural_name(tmp_path):
    downloaded = row(tmp_path, 'download.gguf')
    colliding = row(tmp_path, 'collision.gguf', source='local')
    existing = seed.merge([downloaded], [], [], [colliding])
    existing[1]['settings'] = {'temperature': .6}
    natural = row(tmp_path, 'natural.gguf', ident='chat-local', source='local')
    for scanned in ([colliding, natural], [natural, colliding]):
        result = seed.merge(existing, [], [], scanned)
        by_path = {m['path']: m for m in result}
        assert by_path[colliding['path']]['id'] == 'chat-local'
        assert by_path[colliding['path']]['settings'] == {'temperature': .6}
        assert by_path[natural['path']]['id'] != 'chat-local'
        assert 'settings' not in by_path[natural['path']]
