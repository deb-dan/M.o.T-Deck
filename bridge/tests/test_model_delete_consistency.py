"""Deletion of missing artifacts and failed transactions preserve registry truth."""
import json
import threading

from bridge.core import modeldelete, modelreg
from bridge.tests.model_fixture import gguf_bytes


def _fixture(root, exists=True):
    target = root / 'data/models/owned.gguf'
    target.parent.mkdir(parents=True)
    if exists:
        target.write_bytes(gguf_bytes())
    registry = root / 'data/models.json'
    entry = {'id': 'owned', 'source': 'download', 'format': 'gguf', 'path': str(target)}
    modelreg.write_registry(str(registry), {'models': [entry]})
    return target, registry, entry


def test_delete_missing_owned_artifact_clears_stale_row_and_assignment(tmp_path):
    target, registry, entry = _fixture(tmp_path, exists=False)
    assignment = tmp_path / 'saved-model'
    assignment.write_text('owned')
    result = modeldelete.delete_owned_model_transaction(
        root=tmp_path, mid='owned', expected_target=str(target),
        assignments=[('runner.model', 'owned', lambda: assignment.write_text(''),
                      lambda: assignment.write_text('owned'))])
    assert result is None, result
    assert json.loads(registry.read_text())['models'] == []
    assert assignment.read_text() == ''
    assert not (target.parent / modeldelete.DELETE_JOURNAL).exists()


def test_failed_delete_cannot_erase_concurrent_registry_addition(tmp_path, monkeypatch):
    target, registry, entry = _fixture(tmp_path)
    completed = threading.Event()
    writers = []
    errors = []
    real_write = modelreg.write_registry

    def add_model():
        try:
            with modelreg.registry_lock(str(registry)):
                state = json.loads(registry.read_text())
                state['models'].append({'id': 'new-download'})
                real_write(str(registry), state)
        except Exception as exc:
            errors.append(exc)
        finally:
            completed.set()

    def observe_rollback(path, state):
        if state['models'] == [entry]:
            writer = threading.Thread(target=add_model)
            writers.append(writer)
            writer.start()
            # Before the fix, rollback has dropped the lock; the real second writer
            # commits now and then gets erased. With the fix it waits for rollback.
            completed.wait(0.3)
        return real_write(path, state)

    def fail_assignment():
        raise OSError('fixture assignment failure')

    monkeypatch.setattr(modeldelete, 'write_registry', observe_rollback)
    result = modeldelete.delete_owned_model_transaction(
        root=tmp_path, mid='owned', expected_target=str(target),
        assignments=[('runner.model', 'owned', fail_assignment, lambda: None)])
    for writer in writers:
        writer.join(timeout=3)
        assert not writer.is_alive()
    assert result and 'fixture assignment failure' in result
    assert not errors
    assert {row['id'] for row in json.loads(registry.read_text())['models']} == {'owned', 'new-download'}
    assert target.read_bytes() == gguf_bytes()
