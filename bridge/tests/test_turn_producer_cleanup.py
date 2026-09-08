"""A terminal turn must have released its actual producer and nested network stream."""
import asyncio

from bridge.core.turns import TurnStore
from bridge.routers import turns as routes
from bridge.routers import chat


def test_terminal_follows_nested_producer_cleanup(monkeypatch):
    async def run():
        closed = asyncio.Event()

        async def events(_body):
            async def gen():
                try:
                    yield 'data: {"delta":"done"}\n\n'
                    yield 'data: [DONE]\n\n'
                finally:
                    # Real producers may persist history while closing.
                    await asyncio.sleep(0)
                    closed.set()
            return gen()

        monkeypatch.setattr(chat, 'direct_events', events)
        store = TurnStore()
        body = {'lane': 'chat', 'session': 's', 'request_id': 'r', 'message': 'hello'}
        record, _ = await store.create(body)
        await store._run(record['id'], lambda: routes._producer(body, 'chat'))
        state = await store.metadata(record['id'])
        assert state['state'] == 'completed'
        assert closed.is_set(), 'terminal exposed before nested stream cleanup'

    asyncio.run(run())
