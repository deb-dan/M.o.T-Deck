"""Disposable real-socket transfer; never registers or removes a user model."""
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile

import httpx
from bridge.routers import downloads as D


async def _journey(monkeypatch):
    payload = bytes(range(256)) * 8192
    offsets = []
    first_closed = asyncio.Event()

    async def serve(reader, writer):
        offset = 0
        try:
            headers = (await reader.readuntil(b'\r\n\r\n')).decode()
            for line in headers.splitlines():
                if line.lower().startswith('range:'):
                    offset = int(line.split('bytes=')[1].split('-')[0])
            offsets.append(offset)
            code = '206 Partial Content' if offset else '200 OK'
            writer.write(f'HTTP/1.1 {code}\r\nContent-Length: {len(payload)-offset}\r\nConnection: close\r\n\r\n'.encode())
            if not offset:
                writer.write(payload[:1 << 20])
                await writer.drain()
                await reader.read()  # client Pause must close the stalled socket
            else:
                writer.write(payload[offset:])
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            if not offset:
                first_closed.set()

    server = await asyncio.start_server(serve, '127.0.0.1', 0)
    monkeypatch.setattr(D, '_DL_BASE', f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}')
    monkeypatch.setattr(D, 'DOWNLOADS', {})
    registrations = []
    monkeypatch.setattr(D, '_registry_add', registrations.append)
    monkeypatch.setattr(D, '_modeltools', None)
    with tempfile.TemporaryDirectory(prefix='motdeck-download-journey-') as raw:
        dest = Path(raw) / 'disposable-transfer.gguf'
        async with server, httpx.AsyncClient(timeout=10) as client:
            monkeypatch.setattr(D, '_DL', client)
            entry = D._mk_download('disposable/transfer', [{
                'name': dest.name, 'url': '/payload', 'dest': str(dest),
                'total': len(payload), 'done': 0,
                'sha256': hashlib.sha256(payload).hexdigest(),
            }], 'disposable-transfer', 'gguf')
            async def first_chunk():
                while entry['files'][0]['done'] < 1 << 20:
                    await asyncio.sleep(.01)
            await asyncio.wait_for(first_chunk(), 5)
            old = entry['task']
            await asyncio.wait_for(D.dl_pause(entry['id']), 5)
            await asyncio.wait_for(first_closed.wait(), 5)
            assert old.done() and entry['state'] == 'paused'
            await asyncio.gather(D.dl_resume(entry['id']), D.dl_resume(entry['id']))
            await asyncio.wait_for(entry['task'], 10)
            assert offsets == [0, 1 << 20], offsets
            assert dest.read_bytes() == payload
            assert entry['state'] == 'done' and len(registrations) == 1
            print(json.dumps({'transport': 'real loopback HTTP/1.1 and httpx',
                              'bytes_verified': len(payload), 'range_offsets': offsets,
                              'stalled_socket_closed_on_pause': True,
                              'duplicate_resume_created_one_transfer': True,
                              'real_registry_writes': 0}))


def test_real_http_pause_closes_stalled_connection_and_resume_preserves_bytes(monkeypatch):
    asyncio.run(_journey(monkeypatch))
