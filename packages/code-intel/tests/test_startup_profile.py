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


@pytest.mark.asyncio
async def test_missing_warm_profile_cannot_be_silently_admitted(tmp_path, monkeypatch):
    # Break caught: an ignored warm future loses its record while later warm records hide it.
    from attocode_intel.gateway import OperationGateway

    from eval.quality import startup_profile as observer

    original = observer.profile_summary

    def failed_dump(path):
        if path.name == 'task-0001.prof':
            raise OSError('controlled profile serialization failure')
        return original(path)

    monkeypatch.setattr(observer, 'profile_summary', failed_dump)
    (tmp_path / 'sample.py').write_text('def sample():\n    return 1\n')
    rejected = False
    try:
        with observer.WorkspaceProfiles(tmp_path / '.attocode/profiles'):
            peer = OperationGateway(str(tmp_path), 'daily', watch=False)
            try:
                assert not (await peer.execute('search_symbols', {'name': 'sample'})).isError
                assert not (await peer.execute('capabilities', {})).isError
            finally:
                await peer.close()
    except RuntimeError as exc:
        assert 'task profile' in str(exc)
        rejected = True
    assert rejected, 'missing warm profile was silently admitted'


def test_timeout_retains_spawn_pid_exit_and_incomplete_phase(tmp_path):
    # Break caught: TimeoutExpired exits before any attempted-phase record is persisted.
    import subprocess
    import sys

    from eval.quality.startup_cost_experiment import run_process

    row, snapshots = {}, []
    with pytest.raises(subprocess.TimeoutExpired):
        run_process([sys.executable, '-c', 'import time; time.sleep(30)'], tmp_path, .1,
                    row, lambda: snapshots.append(dict(row)))
    assert snapshots and row.get('timed_out') is True and row.get('worker_pid'), 'timeout attempt metadata was lost'
    assert row['status'] == 'incomplete' and row['parent_exit_ns'] > row['parent_spawn_ns']


def test_launch_failure_retains_attempt_metadata(tmp_path):
    # Break caught: an executable launch failure loses even the known spawn/exit/error boundary.
    from eval.quality.startup_cost_experiment import run_process

    row, snapshots = {}, []
    with pytest.raises(FileNotFoundError):
        run_process([str(tmp_path / 'missing-executable')], tmp_path, 1,
                    row, lambda: snapshots.append(dict(row)))
    assert snapshots and row.get('error_type') == 'FileNotFoundError', 'launch attempt metadata was lost'
    assert row['status'] == 'incomplete' and row['worker_pid'] is None
    assert row['parent_exit_ns'] > row['parent_spawn_ns']
