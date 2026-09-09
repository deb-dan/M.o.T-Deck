"""A preview belongs to its read version; undo never publishes a partial copy."""
import copy
import os
from pathlib import Path

import pytest

from bridge import office, office_ops as ops


@pytest.fixture(autouse=True)
def clear_state(monkeypatch):
    for name in ('_CHANGESETS', '_PENDING', '_SESSION_LINES', '_HEARTBEATS'):
        monkeypatch.setattr(ops, name, {})


def workbook(root, value):
    snapshot = office.empty_snapshot('book')
    snapshot['sheets']['sheet-01']['cellData'] = {'0': {'0': {'v': value, 't': 2}}}
    path = Path(office.office_dir(root)) / 'book.xlsx'
    office.write_snapshot(snapshot, path)
    return path


def test_preview_cannot_claim_timestamp_of_edit_after_read(tmp_path, monkeypatch):
    path = workbook(tmp_path, 1)
    read = office.snapshot_from_path

    def read_then_external_edit(target):
        snapshot = read(target)
        stamp = path.stat().st_mtime
        workbook(tmp_path, 99)
        os.utime(path, (stamp + 3, stamp + 3))
        return snapshot

    monkeypatch.setattr(office, 'snapshot_from_path', read_then_external_edit)
    proposal, error = ops.stage_changes(tmp_path, 's', 'book.xlsx', ops=[
        {'op': 'set', 'at': 'A1', 'values': [[2]]}])
    assert proposal and not error
    monkeypatch.setattr(office, 'snapshot_from_path', read)
    result, error = ops.apply_changeset(tmp_path, proposal['changeset_id'])
    assert result is None and 'changed on disk' in error
    assert read(path)['sheets']['sheet-01']['cellData']['0']['0']['v'] == 99


def test_create_proposal_cannot_overwrite_document_created_since_preview(tmp_path):
    proposal, error = ops.stage_changes(tmp_path, 's', 'book.xlsx', ops=[
        {'op': 'create_workbook'}, {'op': 'set', 'at': 'A1', 'values': [[2]]}])
    assert not error
    path = workbook(tmp_path, 99)
    before = path.read_bytes()
    result, error = ops.apply_changeset(tmp_path, proposal['changeset_id'])
    assert result is None and error
    assert path.read_bytes() == before


def test_partial_restore_keeps_current_workbook(tmp_path, monkeypatch):
    path = workbook(tmp_path, 1)
    checkpoint, error = ops.push_checkpoint(tmp_path, 'book.xlsx', 'test')
    assert not error
    workbook(tmp_path, 2)
    before = path.read_bytes()
    real_copy = ops.shutil.copy2
    source = ops.checkpoint_path(tmp_path, 'book.xlsx', 'test')

    def fail_copy(src, dst, *args, **kwargs):
        if str(src) == source:
            Path(dst).write_bytes(b'partial failed copy')
            raise OSError('disk full')
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(ops.shutil, 'copy2', fail_copy)
    result, error = ops.restore_checkpoint(tmp_path, 'book.xlsx', 'test', path.stat().st_mtime)
    assert result is None and 'disk full' in error
    assert path.read_bytes() == before


@pytest.mark.parametrize('before_cell,after_cell', [
    ({'v': '1', 't': 1}, {'v': 1, 't': 2}),
    ({'v': '=1+2', 't': 1}, {'f': '=1+2'}),
])
def test_preview_shows_type_change_with_identical_text(before_cell, after_cell):
    before = office.empty_snapshot('book')
    before['sheets']['sheet-01']['cellData'] = {'0': {'0': before_cell}}
    after = copy.deepcopy(before)
    after['sheets']['sheet-01']['cellData']['0']['0'] = after_cell
    preview, total = ops.snapshot_diff(before, after)
    assert total == 1 and preview[0]['before_display'] != preview[0]['after_display']


def test_style_total_counts_changes_beyond_preview_cap(tmp_path):
    workbook(tmp_path, 1)
    proposal, error = ops.stage_changes(tmp_path, 's', 'book.xlsx', ops=[
        {'op': 'style', 'at': 'A1:A500', 'set': {'bl': 1}}])
    assert not error and proposal['style_total'] == 500
    assert len(proposal['style_preview']) == ops.PREVIEW_MAX_CELLS


def test_aggregate_checks_populated_cells_not_every_coordinate(monkeypatch):
    snapshot = office.empty_snapshot('book')
    sh = snapshot['sheets']['sheet-01']
    sh['cellData'] = {'0': {'0': {'v': '$10', 't': 1}}}
    real_cell_at = ops.cell_at
    calls = 0

    def bounded_lookup(*args):
        nonlocal calls
        calls += 1
        assert calls < 100, 'aggregate scanned empty range instead of stored cells'
        return real_cell_at(*args)

    monkeypatch.setattr(ops, 'cell_at', bounded_lookup)
    warnings = ops.aggregate_warnings(snapshot, 'sheet-01', [
        {'op': 'set', 'r': 1, 'c': 0, 'values': [['=SUM(A1:XFD1048576)']]}])
    assert warnings[0]['count'] == 1
