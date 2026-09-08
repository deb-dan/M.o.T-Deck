"""Session failures preserve local media; UTC recency survives client timezones."""
import asyncio
import base64
import json
import os
from pathlib import Path
import subprocess

import httpx
import pytest

from bridge.routers import ody, sidecars


@pytest.mark.parametrize('status', [200, 403, 404, 500, 'disconnected'])
def test_session_delete_preserves_sidecars_until_upstream_success(tmp_path, monkeypatch, status):
    monkeypatch.setattr(sidecars, 'ROOT', tmp_path)
    monkeypatch.setattr(sidecars, '_thinking_pruned', False)
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jWZkAAAAASUVORK5CYII=')
    for sid in ['target', 'neighbor']:
        sidecars.log_attachment(sid, sidecars.user_key('photo'), 'photo.png', 'image/png', png)
        sidecars.log_thinking(sid, 'answer', 'saved reasoning')
    aid = sidecars._attachment_rows('target')[0][1]

    async def upstream(*args, **kwargs):
        if status == 'disconnected':
            raise httpx.ConnectError('connection lost')
        return httpx.Response(status, json={'status': 'deleted'} if status == 200
                              else {'detail': 'session deletion refused'})

    monkeypatch.setattr(ody, '_ody_req', upstream)
    response = asyncio.run(ody.ody_session_delete('target'))
    assert json.loads(response.body)['ok'] is (status == 200)
    if status == 200:
        assert sidecars._attachment_rows('target') == []
        assert sidecars._thinking_rows('target') == []
    else:
        assert sidecars._attachment_get(aid) == ('photo.png', 'image/png', png)
        assert sidecars._thinking_rows('target') == [(sidecars.answer_hash('answer'), 'saved reasoning')]
    assert sidecars._attachment_rows('neighbor')
    assert sidecars._thinking_rows('neighbor')


@pytest.mark.parametrize('zone', ['UTC', 'Europe/Tallinn', 'America/New_York'])
@pytest.mark.parametrize('timestamp', [
    '2026-09-08T09:00:00', '2026-09-08T09:00:00.123456',
    '2026-09-08T12:00:00+03:00',
])
def test_upstream_utc_session_renders_as_now_in_each_client_timezone(monkeypatch, zone, timestamp):
    async def upstream(*args, **kwargs):
        return httpx.Response(200, json=[{'id': 'fixture', 'name': 'new session',
                                         'created_at': timestamp, 'message_count': 0}])

    monkeypatch.setattr(ody, '_ody_req', upstream)
    monkeypatch.setattr(ody, '_registry_models', lambda: [])
    monkeypatch.setattr(ody, 'cfg', lambda: {})
    row = json.loads(asyncio.run(ody.ody_sessions()).body)[0]
    html = (Path(__file__).parents[1] / 'panel/index.html').read_text()
    start = html.index('function relTime(iso)')
    end = html.index('\n}', start) + 2
    program = (html[start:end] + '\nDate.now = () => Date.parse("2026-09-08T09:00:05Z");'
               '\nconsole.log(relTime(process.argv[1]));')
    result = subprocess.run(['node', '-e', program, row['updated_at']],
                            env={**os.environ, 'TZ': zone}, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == 'now', (zone, timestamp, row, result.stdout)
