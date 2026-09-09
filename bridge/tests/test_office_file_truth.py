"""Real workbook round trips and exact document ownership."""
import os
from pathlib import Path

import openpyxl
import pytest

from bridge import office, oo


def test_literal_equals_text_remains_text_in_both_directions(tmp_path):
    source, result = tmp_path / 'source.xlsx', tmp_path / 'result.xlsx'
    wb = openpyxl.Workbook()
    for address, value in [('A1', '=not a formula'), ('A2', '#N/A')]:
        wb.active[address] = value
        wb.active[address].data_type = 's'
    wb.active['A3'] = '=1+2'
    wb.save(source)
    snapshot = office.snapshot_from_path(source)
    cells = snapshot['sheets']['sheet-01']['cellData']
    assert 'f' not in cells['0']['0']
    office.write_snapshot(snapshot, result)
    saved = openpyxl.load_workbook(result)
    assert saved.active['A1'].value == '=not a formula' and saved.active['A1'].data_type == 's'
    assert saved.active['A2'].value == '#N/A' and saved.active['A2'].data_type == 's'
    assert saved.active['A3'].data_type == 'f'


def test_sparse_sheet_does_not_materialize_empty_rectangle(monkeypatch):
    wb = openpyxl.Workbook()
    wb.active['A1'] = 'first'
    wb.active['XFD1048576'] = 'last'

    def refuse_rectangle(*args, **kwargs):
        pytest.fail('sparse sheet expanded into a trillion empty cells')

    monkeypatch.setattr(wb.active, 'iter_rows', refuse_rectangle)
    sheet = office.sheet_snapshot(wb.active, 's')
    assert sheet['cellData']['1048575']['16383']['v'] == 'last'
    assert len(wb.active._cells) == 2


@pytest.mark.parametrize('flag', ['truncated', 'unreadable'])
def test_incomplete_snapshot_cannot_replace_complete_workbook(tmp_path, flag):
    path = tmp_path / 'book.xlsx'
    path.write_bytes(b'original file')
    snapshot = office.empty_snapshot('book')
    snapshot['sheets']['sheet-01'][flag] = True
    with pytest.raises(office.OfficeError, match='incomplete'):
        office.write_snapshot(snapshot, path)
    assert path.read_bytes() == b'original file'


def test_backups_belong_to_exact_document(tmp_path):
    folder = Path(office.office_dir(tmp_path))
    for name in ['Budget.xlsx', 'Budget.docx', 'Budget.Other.xlsx',
                 'Budget.20260908.bak.xlsx', 'Budget.20260908.bak.docx',
                 'Budget.Other.20260908.bak.xlsx']:
        (folder / name).write_bytes(name.encode())
    assert office.delete_doc(tmp_path, 'Budget.xlsx', backups=True) == (True, None)
    assert not (folder / 'Budget.20260908.bak.xlsx').exists()
    assert (folder / 'Budget.20260908.bak.docx').exists()
    assert (folder / 'Budget.Other.20260908.bak.xlsx').exists()


def test_other_document_backup_is_not_reported(tmp_path):
    path = Path(office.office_dir(tmp_path)) / 'Budget.xlsx'
    path.write_bytes(b'workbook')
    (path.parent / 'Budget.20260908.bak.docx').write_bytes(b'document')
    assert office._any_backup(path) == ''


@pytest.mark.parametrize('editor', ['grid', 'rich'])
def test_save_refuses_another_edit_within_same_second(tmp_path, editor):
    name, error = office.create_doc(tmp_path, 'book.xlsx')
    assert not error
    path = Path(office.office_dir(tmp_path)) / name
    snapshot, error = office.open_doc(tmp_path, name)
    mtime = snapshot['file_mtime']
    original = path.read_bytes()
    os.utime(path, (mtime + .1, mtime + .1))
    if editor == 'grid':
        result, error = office.save_doc(tmp_path, name, snapshot, mtime)
    else:
        result, error = oo.writeback(office, tmp_path, name, original, mtime)
    assert result is None and error
    assert path.read_bytes() == original
    assert not list(path.parent.glob('*.bak.xlsx'))


@pytest.mark.parametrize('encoding', ['br;q=0', 'zebra', 'br;q=garbage', '*;q=1, br;q=0'])
def test_brotli_respects_actual_acceptance(tmp_path, encoding):
    path = tmp_path / 'asset.js'
    path.write_text('let x = 1')
    Path(str(path) + '.br').write_bytes(b'compressed')
    assert oo.brotli_sibling(path, encoding) == ''


@pytest.mark.parametrize('text', ['9007199254740993', '1234567890123456',
                                  '$9,007,199,254,740,993', '12.345678901234567'])
def test_numeric_text_that_exceeds_excel_precision_is_not_rounded(text):
    from bridge import office_ops
    assert office_ops.coerce_numeric(text) is None
    assert office_ops.parse_input(text)['v'] == text


def test_style_clear_survives_parser_and_workbook_roundtrip(tmp_path):
    from bridge import office_ops
    patch = office_ops.act_style_set({'bl': False, 'it': 0, 'ul': {'s': 0}, 'st': False})
    assert patch == {'bl': 0, 'it': 0, 'ul': {'s': 0}, 'st': {'s': 0}}
    assert office_ops.act_style_set({'bl': 'false', 'ul': 'true'}) is None
    wb = openpyxl.Workbook()
    cell = wb.active['A1']
    cell.value = 'plain'
    office.apply_style(cell, patch)
    path = tmp_path / 'cleared.xlsx'
    wb.save(path)
    font = openpyxl.load_workbook(path).active['A1'].font
    assert not font.bold and not font.italic and not font.underline and not font.strike
