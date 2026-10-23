"""Exercise the real interpreter profiler with executor tasks, not corpus data."""
import json
import sys

import pytest


def test_executor_profiles_forward_results_and_errors_without_competing_profiler(tmp_path, monkeypatch):
    from attocode_intel import gateway

    from eval.quality import broad_cost_experiment as diagnostic

    expected = ValueError('owned external failure')
    def external_run(*args, **kwargs):
        def value():
            return 'observed value'
        def failure():
            raise expected
        with gateway.ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(value).result(timeout=10) == 'observed value'
            with pytest.raises(ValueError) as error:
                executor.submit(failure).result(timeout=10)
            assert error.value is expected
    monkeypatch.setattr(diagnostic.runpy, 'run_module', external_run)
    monkeypatch.setattr(sys, 'argv', ['owned-test'])
    diagnostic.worker_entry(tmp_path, [])
    rows = [json.loads(path.read_bytes()) for path in sorted(tmp_path.glob('workspace-*.json'))]
    assert len(rows) == 2 and [row['sequence'] for row in rows] == [0, 1]
    assert all(row['diagnostic_only'] and row['total_calls'] > 0 and row['by_cumulative'] for row in rows)
    assert all(path.stat().st_size > 0 for path in tmp_path.glob('workspace-*.prof'))
