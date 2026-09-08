"""Unknown history metadata must never authorize the empty-session cleanup."""
import asyncio
import json

import pytest

from bridge import pty_goose
from bridge.routers import goose


@pytest.mark.parametrize('count', [None, 'unavailable', -1, 0.5, False, float('inf')])
def test_unreadable_message_count_is_unknown(count):
    rows = pty_goose.parse_sessions(json.dumps([
        {'id': '20260908_1', 'message_count': count},
        {'id': '20260908_2', 'message_count': 0},
    ]))
    assert rows[0]['messages'] is None
    assert rows[1]['messages'] == 0


def test_prune_does_not_delete_history_with_unknown_count(monkeypatch):
    backend = goose._goose
    monkeypatch.setattr(backend, 'list_sessions', lambda root: ([
        {'id': '20260908_1', 'messages': None},
    ], ''))
    monkeypatch.setattr(backend, 'current', lambda: None)
    removed = []
    monkeypatch.setattr(backend, 'remove_session',
                        lambda root, sid: (removed.append(sid) or True, 'deleted'))

    class Request:
        async def json(self):
            return {'ids': ['20260908_1']}

    response = asyncio.run(goose.goose_sessions_prune_empty(Request()))
    assert response.status_code == 409
    assert not removed


@pytest.mark.parametrize('output,error', [('[broken', ''), ('{}', ''),
                                          ('[]', 'store unavailable')])
def test_invalid_or_failed_list_does_not_claim_empty_history(monkeypatch, output, error):
    monkeypatch.setattr(pty_goose, 'is_installed', lambda root: (True, 'goose', ''))
    monkeypatch.setattr(pty_goose, '_run_fenced', lambda *args: (output, error))
    rows, message = pty_goose.list_sessions('.')
    assert rows == []
    assert message
