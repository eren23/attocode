"""Actual gateway observer coverage; legacy failures are manual control data only."""
import contextlib
import json
import os

import pytest


@contextlib.contextmanager
def capture(tmp_path, monkeypatch):
    from attocode_intel import gateway

    if os.environ.get('STARTUP_LEGACY_CONTROL') == '1':
        from eval.quality.navigation_profile import ProfileGateway

        rows = []
        peer = ProfileGateway(tmp_path, rows)
        yield peer, lambda: [{'task': 'OperationGateway._execute_sync:' + r['operation'],
                             'status': 'passed'} for r in rows]
    else:
        from eval.quality.startup_profile import WorkspaceProfiles

        with WorkspaceProfiles(tmp_path / '.attocode/profiles'):
            peer = gateway.OperationGateway(str(tmp_path), 'daily', watch=False)
            yield peer, lambda: [json.loads(p.read_bytes()) for p in
                                sorted((tmp_path / '.attocode/profiles').glob('task-*.json'))]


@pytest.mark.asyncio
async def test_actual_gateway_dispatch_warm_and_close_are_all_observed(tmp_path, monkeypatch):
    # Break caught: foreground-only observation silently omits queued warm/shutdown work.
    (tmp_path / 'sample.py').write_text('def sample():\n    return 1\n')
    with capture(tmp_path, monkeypatch) as (peer, records):
        try:
            response = await peer.execute('search_symbols', {'name': 'sample'})
            assert not response.isError
        finally:
            await peer.close()
    names = {r['task'].split(':')[0].split('.')[-1] for r in records()}
    assert {'_execute_sync', '_warm_search', '_close_stores'} <= names, 'missing dispatch/warm/close profile coverage'


@pytest.mark.asyncio
async def test_actual_failed_warm_task_is_retained_without_changing_response(tmp_path, monkeypatch):
    # Break caught: a background failure disappears from the profile's success-only output.
    from attocode_intel.gateway import OperationGateway

    def fail_warm(context):
        raise RuntimeError('controlled-warm-failure')

    monkeypatch.setattr(OperationGateway, '_warm_search', staticmethod(fail_warm))
    (tmp_path / 'sample.py').write_text('def sample():\n    return 1\n')
    with capture(tmp_path, monkeypatch) as (peer, records):
        try:
            response = await peer.execute('search_symbols', {'name': 'sample'})
            assert not response.isError
        finally:
            await peer.close()
    failed = [r for r in records() if r['task'].endswith('fail_warm')]
    assert len(failed) == 1, 'failed warm task was not retained'
    assert failed[0]['status'] == 'failed' and failed[0]['error_type'] == 'RuntimeError'
