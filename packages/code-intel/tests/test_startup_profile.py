"""Actual gateway observer coverage; legacy failures are manual control data only."""
import contextlib
import json
import os
import threading
import time

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


def test_executor_preserves_return_and_exception_after_dumping_profile(tmp_path):
    # Break caught: observation changes task values/exceptions or loses failing-task statistics.
    from eval.quality.startup_profile import profile_call

    value = object()
    assert profile_call(tmp_path / 'ok.prof', 'return', lambda: value) is value

    def fail():
        raise LookupError('retained')

    with pytest.raises(LookupError, match='retained'):
        profile_call(tmp_path / 'bad.prof', 'failure', fail)
    row = json.loads((tmp_path / 'bad.json').read_bytes())
    assert row['status'] == 'failed' and row['error_type'] == 'LookupError'
    assert (tmp_path / 'bad.prof').stat().st_size > 0


def test_raw_profile_summary_matches_saved_function_statistics(tmp_path):
    # Break caught: summaries omit/change call counts or attribute observer work to the task.
    import pstats

    from eval.quality.startup_profile import profile_call

    def leaf():
        return 7

    def parent():
        return leaf() + leaf() + leaf()

    assert profile_call(tmp_path / 'calls.prof', 'nested', parent) == 21
    stats = pstats.Stats(str(tmp_path / 'calls.prof'))
    leaf_rows = [v for k, v in stats.stats.items() if k[2] == 'leaf']
    assert len(leaf_rows) == 1 and leaf_rows[0][0:2] == (3, 3)
    row = json.loads((tmp_path / 'calls.json').read_bytes())
    assert row['total_calls'] == stats.total_calls
    assert row['total_seconds'] == stats.total_tt
    assert row['thread_cpu_seconds'] >= 0 and row['scope_wall_seconds'] >= 0


def test_overlapping_main_and_workspace_profiles_are_rejected(tmp_path):
    # Break caught: concurrent cProfile instances corrupt global CPython3.12 monitoring attribution.
    from eval.quality.startup_profile import profile_call

    entered, finish = threading.Event(), threading.Event()
    errors = []

    def block():
        entered.set()
        assert finish.wait(5)

    def owner():
        try:
            profile_call(tmp_path / 'first.prof', 'first', block)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=owner)
    thread.start()
    try:
        assert entered.wait(5)
        with pytest.raises(RuntimeError, match='overlapping profile'):
            profile_call(tmp_path / 'overlap.prof', 'overlap', lambda: None)
    finally:
        finish.set()
        thread.join(5)
    assert not thread.is_alive() and not errors
    assert not (tmp_path / 'overlap.prof').exists()


def test_profile_serialization_time_is_separate_from_task_clocks(tmp_path, monkeypatch):
    # Break caught: profile data processing is accidentally charged to the original task scope.
    from eval.quality import startup_profile as observer

    original = observer.profile_summary
    points = []

    def delayed(path):
        points.append(time.monotonic_ns())
        time.sleep(.03)
        points.append(time.monotonic_ns())
        return original(path)

    monkeypatch.setattr(observer, 'profile_summary', delayed)
    assert observer.profile_call(tmp_path / 'timing.prof', 'timing', lambda: 42) == 42
    row = json.loads((tmp_path / 'timing.json').read_bytes())
    assert row['finished_ns'] <= points[0] < points[1] <= row['profile_dump_finished_ns']
    assert row['profile_serialization_seconds'] >= .03


def test_profile_output_refuses_overwrite(tmp_path):
    # Break caught: reruns replace original profile evidence before the caller notices.
    from eval.quality.startup_profile import profile_call

    path = tmp_path / 'existing.prof'
    path.write_bytes(b'original evidence')
    called = []
    with pytest.raises(FileExistsError):
        profile_call(path, 'replacement', lambda: called.append(True))
    assert path.read_bytes() == b'original evidence' and not called
