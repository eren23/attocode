"""Temporary unprofiled observer controls; execute only on GitHub runners."""
import hashlib
import importlib
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest


def observer():
    try:
        return importlib.import_module('eval.quality.stage_clocks')
    except ModuleNotFoundError as error:
        if error.name != 'eval.quality.stage_clocks':
            raise
        pytest.fail('unprofiled stage clock observer is unavailable')


def rows(path):
    return [json.loads(line) for line in (path / 'spans.jsonl').read_bytes().splitlines()]


def test_stage_observer_captures_real_nested_calls(tmp_path):
    module = observer()
    clocks = module.StageClocks(tmp_path / 'clock')
    token = object()
    assert clocks.call('outer', lambda: clocks.call('inner', lambda: token)) is token
    manifest = clocks.close()
    captured = module.admit_records(tmp_path / 'clock', manifest)
    outer, inner = sorted(captured, key=lambda row: row['id'])
    assert outer['parent'] is None and inner['parent'] == outer['id']
    assert outer['started_ns'] <= inner['started_ns'] < inner['finished_ns'] <= outer['finished_ns']
    assert outer['cpu_start_ns'] <= inner['cpu_start_ns'] <= inner['cpu_end_ns'] <= outer['cpu_end_ns']
    assert all(row['profile_active'] is False for row in captured)


def test_original_exception_identity_is_preserved_and_record_durable(tmp_path):
    clocks = observer().StageClocks(tmp_path / 'clock')
    failure = RuntimeError('original failure')

    def fail():
        raise failure

    with pytest.raises(RuntimeError) as caught:
        clocks.call('failure', fail)
    assert caught.value is failure
    clocks.close()
    row, = rows(tmp_path / 'clock')
    assert row['status'] == 'failed' and row['error_type'] == 'RuntimeError'


def test_threads_keep_distinct_stacks_and_can_overlap(tmp_path):
    module = observer()
    clocks = module.StageClocks(tmp_path / 'clock')
    barrier = threading.Barrier(2)

    def task():
        return clocks.call('parallel', lambda: barrier.wait(timeout=10))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(task) for _ in range(2)]
        assert sorted(f.result(timeout=10) for f in futures) == [0, 1]
    captured = module.admit_records(tmp_path / 'clock', clocks.close())
    assert len({row['native_thread_id'] for row in captured}) == 2
    assert all(row['parent'] is None for row in captured)
    assert max(row['started_ns'] for row in captured) < min(row['finished_ns'] for row in captured)


def test_recorder_never_installs_a_profile_callback(tmp_path, monkeypatch):
    clocks = observer().StageClocks(tmp_path / 'clock')
    before = sys.getprofile()

    def forbidden(*args, **kwargs):
        raise AssertionError('profiler callback installed')

    monkeypatch.setattr(sys, 'setprofile', forbidden)
    assert clocks.call('plain', lambda: 42) == 42
    clocks.close()
    assert sys.getprofile() is before


def test_active_span_cannot_be_declared_complete(tmp_path):
    clocks = observer().StageClocks(tmp_path / 'clock')

    def active():
        with pytest.raises(ValueError):
            clocks.close()

    clocks.call('active', active)
    assert clocks.close()['complete'] is True


def test_completed_span_is_flushed_before_later_work(tmp_path):
    clocks = observer().StageClocks(tmp_path / 'clock')
    clocks.call('completed', lambda: None)
    assert rows(tmp_path / 'clock')[0]['label'] == 'completed'
    clocks.close()


def test_record_bound_does_not_change_callable_result_but_blocks_admission(tmp_path):
    clocks = observer().StageClocks(tmp_path / 'clock', max_records=1)
    assert clocks.call('first', lambda: 1) == 1
    assert clocks.call('second', lambda: 2) == 2
    with pytest.raises(ValueError):
        clocks.close()
    assert json.loads((tmp_path / 'clock/manifest.json').read_bytes())['complete'] is False


def test_logging_failure_does_not_mask_original_exception(tmp_path, monkeypatch):
    clocks = observer().StageClocks(tmp_path / 'clock')
    original = LookupError('original')

    def bad_write(*args):
        raise OSError('observer storage failure')

    def fail():
        raise original

    monkeypatch.setattr(clocks, '_write', bad_write)
    with pytest.raises(LookupError) as caught:
        clocks.call('failed', fail)
    assert caught.value is original
    with pytest.raises(ValueError):
        clocks.close()


@pytest.mark.parametrize('damage', ['parent', 'wall', 'cpu', 'profile'], ids=['parent', 'wall', 'cpu', 'profile'])
def test_rebound_or_invalid_clock_record_is_rejected(tmp_path, damage):
    module = observer()
    clocks = module.StageClocks(tmp_path / 'clock')
    clocks.call('one', lambda: 1)
    manifest = clocks.close()
    captured = rows(tmp_path / 'clock')
    row = captured[0]
    if damage == 'parent':
        row['parent'] = row['id']
    elif damage == 'wall':
        row['finished_ns'] = row['started_ns'] - 1
    elif damage == 'cpu':
        row['cpu_end_ns'] = row['cpu_start_ns'] - 1
    else:
        row['profile_active'] = True
    raw = (json.dumps(row) + '\n').encode()
    (tmp_path / 'clock/spans.jsonl').write_bytes(raw)
    manifest.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError):
        module.admit_records(tmp_path / 'clock', manifest)


def test_truncated_record_cannot_be_silently_omitted(tmp_path):
    module = observer()
    clocks = module.StageClocks(tmp_path / 'clock')
    clocks.call('one', lambda: 1)
    manifest = clocks.close()
    with (tmp_path / 'clock/spans.jsonl').open('ab') as stream:
        stream.write(b'{"incomplete":')
    with pytest.raises(ValueError):
        module.admit_records(tmp_path / 'clock', manifest)


def test_actual_gateway_executor_is_observed_and_original_restored(tmp_path):
    from attocode_intel import gateway

    module = observer()
    original = gateway.ThreadPoolExecutor
    clocks = module.StageClocks(tmp_path / 'clock')
    token = object()
    with module.WorkspaceStages(clocks), gateway.ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(lambda: token).result(timeout=10) is token
    assert gateway.ThreadPoolExecutor is original
    manifest = clocks.close()
    captured = module.admit_records(tmp_path / 'clock', manifest)
    assert len(manifest['tasks']) == 1
    assert len([row for row in captured if row['label'].startswith('executor:')]) == 1
    assert manifest['tasks'][0]['status'] == 'passed'


def test_stage_patch_restores_original_function_identity(tmp_path):
    from attocode_intel._internal.integrations.context.ast_service import ASTService

    module = observer()
    original = ASTService._save_snapshot
    clocks = module.StageClocks(tmp_path / 'clock')
    with module.WorkspaceStages(clocks):
        assert ASTService._save_snapshot is not original
    assert ASTService._save_snapshot is original
    # No executor task submitted in this focused patch-restoration control.
    assert clocks.close()['complete'] is True


def test_metadata_failure_keeps_original_result_and_blocks_completion(tmp_path, monkeypatch):
    module = observer()
    clocks = module.StageClocks(tmp_path / 'clock')

    def broken_metadata(function):
        raise OSError('metadata unavailable')

    monkeypatch.setattr(module, 'describe', broken_metadata)
    assert clocks.call('metadata', lambda: 42) == 42
    with pytest.raises(ValueError):
        clocks.close()


def test_keyword_arguments_are_forwarded_without_reserved_names(tmp_path):
    clocks = observer().StageClocks(tmp_path / 'clock')
    token = object()
    assert clocks.call('keyword', lambda **values: values['function'], function=token, label='original') is token
    clocks.close()


def test_external_callable_source_does_not_change_its_result(tmp_path):
    clocks = observer().StageClocks(tmp_path / 'clock')
    namespace = {}
    exec(compile('def value(): return 42', '/outside/source.py', 'exec'), namespace)
    assert clocks.call('external', namespace['value']) == 42
    clocks.close()
