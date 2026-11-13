"""Rejected-URL diagnostics and cancellation edge cases at public boundaries."""
import asyncio
import json
import subprocess
import sys

import pytest
import test_http_session
from mcp import ClientSession, types

peer = test_http_session.peer


def test_opt_in_init_redacts_parser_failure(tmp_path, record_property):
    result = subprocess.run([
        sys.executable, '-m', 'attocode_intel.entrypoint', 'init', '--client', 'codex',
        '--project', str(tmp_path), '--dry-run', '--http-cancellation',
        '--server', 'https://user:AUTHORED_MARKER@example.invalid\uff1a80',
    ], capture_output=True, text=True, timeout=10)
    (tmp_path / 'cli-result.json').write_text(json.dumps({
        'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}, indent=2))
    assert result.returncode == 1 and not result.stdout
    record_property('qualified_input', 'true')
    record_property('entrypoint', 'init_cli_opt_in')
    assert 'AUTHORED_MARKER' not in result.stderr, 'REGRESSION: Proxy initialization leaks rejected URL credentials'


async def test_cancel_before_start_does_not_send_an_unsent_tool_call(peer):
    from attocode_intel._http_session import http_session

    async with http_session('http://owned.invalid/mcp/', enable_cancellation=True) as session:
        await session.initialize()
        task = asyncio.create_task(session.call_tool('a', {}))
        task.cancel('cancelled before start')
        with pytest.raises(asyncio.CancelledError, match='cancelled before start'):
            await task
        assert not any(r['method'] in {'tools/call', 'notifications/cancelled'} for r, _ in peer.requests)
        assert (await session.call_tool('later', {})).content[0].text == 'later'


async def test_repeated_cancel_during_enqueue_preserves_first_cancellation(peer, monkeypatch):
    from attocode_intel._http_session import http_session

    original = ClientSession.send_notification
    entered = asyncio.Event()
    attempts = []

    async def blocked(self, notification, *args, **kwargs):
        if isinstance(notification.root, types.CancelledNotification):
            attempts.append(notification)
            entered.set()
            await asyncio.Event().wait()
        return await original(self, notification, *args, **kwargs)

    monkeypatch.setattr(ClientSession, 'send_notification', blocked)
    async with http_session('http://owned.invalid/mcp/', enable_cancellation=True) as session:
        await session.initialize()
        task = asyncio.create_task(session.call_tool('a', {}))
        await asyncio.wait_for(peer.entered['a'].wait(), 2)
        task.cancel('original cancellation')
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel('repeated cancellation')
        with pytest.raises(asyncio.CancelledError, match='original cancellation'):
            await asyncio.wait_for(task, 2)
        assert len(attempts) == 1
        peer.release['a'].set()
        assert (await session.call_tool('later', {})).content[0].text == 'later'
