"""Hermes relay completion must agree with its visible terminal frames."""
import asyncio
import json

import pytest

from bridge.core.hermesturn import HermesTurnStore
from bridge.routers import hermes


@pytest.mark.parametrize('failure', ['reported', 'raised', 'missing_done'])
def test_failed_relay_reports_failure_to_metadata_and_subscriber(failure):
    async def journey():
        store = HermesTurnStore()

        async def producer():
            yield 'data: {"delta":"partial answer"}\n\n'
            if failure == 'reported':
                yield 'data: {"type":"proxy_error","error":"fixture failure"}\n\n'
                yield 'data: [DONE]\n\n'
            elif failure == 'raised':
                raise RuntimeError('fixture failure')

        turn = store.start(sid='live', stored_sid='stored', request_id='request',
                           user='hello', image_name='', producer=producer())
        frames = [frame async for frame in turn.subscribe()]
        assert turn.state == 'failed'
        assert turn.error
        errors = [json.loads(frame[6:]) for frame in frames
                  if frame.startswith('data: {') and 'proxy_error' in frame]
        assert len(errors) == 1
        assert frames[-1] == 'data: [DONE]\n\n'
        assert sum('[DONE]' in frame for frame in frames) == 1

    asyncio.run(journey())


def test_done_is_published_after_producer_cleanup():
    async def journey():
        store = HermesTurnStore()
        closed = asyncio.Event()

        async def producer():
            try:
                yield 'data: [DONE]\n\n'
            finally:
                await asyncio.sleep(.01)
                closed.set()

        turn = store.start(sid='live', stored_sid='stored', request_id='request',
                           user='hello', image_name='', producer=producer())
        subscriber = turn.subscribe()
        assert await anext(subscriber) == 'data: [DONE]\n\n'
        assert closed.is_set()
        await subscriber.aclose()
        assert turn.state == 'completed'

    asyncio.run(journey())


def test_cancelling_rpc_drops_its_pending_reply():
    async def journey():
        client = hermes._HermesWS()
        sent = asyncio.Event()

        class Socket:
            async def send(self, message):
                sent.set()

        client._ws = Socket()
        task = asyncio.create_task(client.rpc('session.history', {}))
        await sent.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not client._pending

    asyncio.run(journey())


def test_bridge_shutdown_cancels_actual_relay_and_closes_its_queue(monkeypatch):
    async def journey():
        submitted = asyncio.Event()

        class Request:
            async def json(self):
                return {'session_id': 'live', 'stored_sid': 'stored',
                        'message': 'hello', 'request_id': 'shutdown'}

        class Gateway:
            queue = None

            def open_queue(self, sid):
                self.queue = asyncio.Queue()
                return self.queue

            def close_queue(self, sid):
                self.queue = None

            async def rpc(self, method, params, **kwargs):
                assert method == 'prompt.submit'
                submitted.set()
                return {}

        gateway, store = Gateway(), HermesTurnStore()
        monkeypatch.setattr(hermes, '_HERMES', gateway)
        monkeypatch.setattr(hermes, 'HERMES_TURNS', store)
        monkeypatch.setattr(hermes, '_office_ops', None)
        monkeypatch.setattr(hermes, 'cfg', lambda: {})
        await hermes.hermes_chat(Request())
        await submitted.wait()
        task = next(iter(store._tasks))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert gateway.queue is None
        assert store.find(request_id='shutdown').state == 'interrupted'

    asyncio.run(journey())
