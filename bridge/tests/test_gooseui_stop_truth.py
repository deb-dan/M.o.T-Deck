"""A refused or incomplete Stop preserves authority and blocks another launch."""
from types import SimpleNamespace

import pytest

from bridge.routers import gooseui as G


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(G, 'ROOT', tmp_path)
    p = SimpleNamespace(pid=123, poll=lambda: None)
    monkeypatch.setattr(G, '_PROC', p)
    monkeypatch.setattr(G, '_PROC_BIRTH', 'original-birth')
    monkeypatch.setattr(G, '_log', lambda *args: None)
    return p


def test_refused_stop_retains_handle_and_returns_conflict(state, monkeypatch):
    monkeypatch.setattr(G, 'is_ours', lambda pid: False)
    result = G.gooseui_stop()
    assert result.status_code == 409
    assert G._PROC is state and G._PROC_BIRTH == 'original-birth'


def test_refused_signal_retains_handle(state, monkeypatch):
    monkeypatch.setattr(G, 'is_ours', lambda pid: True)
    monkeypatch.setattr(G._ownership, 'signal_owned', lambda *args, **kwargs: (False, 'claim changed'))
    assert G._stop_locked('test') == 'not-ours'
    assert G._PROC is state and G._PROC_BIRTH == 'original-birth'


def test_orphan_claim_survives_term_until_confirmed_exit(state, monkeypatch):
    monkeypatch.setattr(G._ownership, 'read_claim', lambda *args: (123, 'birth'))
    monkeypatch.setattr(G._ownership, 'read_pid_report', lambda *args: 123)
    alive = [True]
    sent = []
    def signal(*args, **kwargs):
        sent.append(kwargs)
        if kwargs.get('force'):
            alive[0] = False
        return True, 'sent'
    ticks = iter(range(100))
    monkeypatch.setattr(G.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(G.time, 'sleep', lambda _: None)
    monkeypatch.setattr(G._ownership, 'signal_owned', signal)
    monkeypatch.setattr(G._ownership, 'process_birth', lambda _: 'birth' if alive[0] else '')
    retired = []
    def retire(*args):
        assert not alive[0], 'must not erase authority while still alive'
        retired.append(args)
    monkeypatch.setattr(G, '_clear_pidfile', retire)
    assert G._reap_orphan() is True
    assert len(sent) == 2 and all(call['retire'] is False for call in sent)
    assert retired == [(123, 'birth')]


def test_wedged_process_refusing_stop_cannot_be_replaced(state, monkeypatch):
    monkeypatch.setattr(G, '_alive', lambda: True)
    monkeypatch.setattr(G, '_probe', lambda _: False)
    times = iter([0, 6])
    monkeypatch.setattr(G.time, 'time', lambda: next(times))
    monkeypatch.setattr(G, '_stop_locked', lambda _: 'not-ours')
    monkeypatch.setattr(G, '_START_ERR', '')
    url, error = G._ensure()
    assert url == '' and 'could not be stopped' in error
    assert G._PROC is state
