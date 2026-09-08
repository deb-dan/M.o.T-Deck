"""A reload that disconnects during scrollback must still detach the live child."""
import asyncio
from types import SimpleNamespace

import pytest

from bridge import pty_aider
from bridge.routers import aider, goose


@pytest.mark.parametrize('lane', ['aider', 'goose'])
def test_failed_scrollback_delivery_releases_the_socket_subscription(monkeypatch, lane):
    router = aider if lane == 'aider' else goose
    backend = router._pty if lane == 'aider' else router._goose
    session = pty_aider.PtySession([], '.', {})
    session.proc = SimpleNamespace(pid=12345, poll=lambda: None)
    session._buf.extend(b'previous terminal output')
    session.start_relay = lambda: None
    monkeypatch.setattr(backend, 'current', lambda: session)
    monkeypatch.setattr(router, '_bridge_port', lambda: 8700)
    monkeypatch.setattr(router, '_grace_s', lambda: 600)
    monkeypatch.setattr(router, '_' + lane + '_log', lambda message: None)
    detached = []

    def detach(callback, **kwargs):
        assert session._sub is callback
        session._sub = None
        detached.append(kwargs)
        return True

    session.detach = detach

    class Socket:
        headers = {'origin': 'http://127.0.0.1:8700'}
        query_params = {}

        async def accept(self):
            pass

        async def send_bytes(self, data):
            raise ConnectionError('viewer disappeared during replay')

        async def close(self, **kwargs):
            pass

    async def journey():
        try:
            await (router.aider_pty(Socket()) if lane == 'aider'
                   else router.goose_pty(Socket()))
        except ConnectionError:
            pass
        assert not session.attached()
        assert len(detached) == 1 and detached[0]['grace'] == 600
        assert session.alive()

    asyncio.run(journey())
