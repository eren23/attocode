"""Prospective serializer trial guards; clocks are process lifetime, not admission."""
import subprocess
import sys

import pytest

from eval.quality import encoding_experiment as trial


def records(cold=100, restart=35):
    return [{'arm': arm, 'number': n, 'status': 'complete', 'phases': {
        kind: {'status': 'complete', 'process_seconds': value, 'evidence_sha256': 'a'*64}
        for kind, value in [('cold', 100 if arm == 'baseline' else cold),
                            ('restart', 40 if arm == 'baseline' else restart)]}}
        for arm, n in [('baseline', 0), ('candidate', 0), ('candidate', 1),
                       ('baseline', 1), ('baseline', 2), ('candidate', 2)]]


@pytest.mark.parametrize('cold,restart,want', [
    (105, 36, 'retain'), (105.01, 36, 'reject'), (105, 36.01, 'reject'), (100, 35, 'retain'),
])
def test_process_median_thresholds_apply_at_frozen_boundaries(cold, restart, want):
    assert trial.decide(records(cold, restart), 'a'*64)['decision'] == want


def test_one_slower_round_cannot_hide_behind_faster_median():
    rows = records(restart=30)
    rows[2]['phases']['restart']['process_seconds'] = 41
    result = trial.decide(rows, 'a'*64)
    assert result['status'] == 'complete' and result['decision'] == 'reject'
    assert result['ratios']['restart'] == .75 and not result['every_restart_round_faster']


@pytest.mark.parametrize('damage', ['missing', 'order', 'hash', 'bool', 'nan', 'incomplete'])
def test_missing_or_invalid_evidence_never_earns_a_verdict(damage):
    rows = records()
    if damage == 'missing':
        rows.pop()
    elif damage == 'order':
        rows.reverse()
    elif damage == 'hash':
        rows[0]['phases']['cold']['evidence_sha256'] = 'b'*64
    elif damage == 'bool':
        rows[0]['phases']['restart']['process_seconds'] = True
    elif damage == 'nan':
        rows[0]['phases']['cold']['process_seconds'] = float('nan')
    else:
        rows[0]['status'] = 'incomplete'
    result = trial.decide(rows, 'a'*64)
    assert result['status'] == 'incomplete' and result['decision'] is None


def test_admission_clock_cannot_change_the_primary_process_verdict():
    rows = records(restart=35)
    for row in rows:
        for phase in row['phases'].values():
            phase['seconds'] = 1000 if row['arm'] == 'candidate' else 1
    result = trial.decide(rows, 'a'*64)
    assert result['decision'] == 'retain' and result['ratios']['restart'] == .875


@pytest.mark.parametrize('kind', ['timeout', 'launch'])
def test_failed_process_retains_attempt_boundaries(tmp_path, kind):
    row, saved = {}, []
    command = ([sys.executable, '-c', 'import time;time.sleep(30)'] if kind == 'timeout'
               else [str(tmp_path / 'missing-command')])
    with pytest.raises(subprocess.TimeoutExpired if kind == 'timeout' else FileNotFoundError):
        trial.run_process(command, tmp_path, .1, row, lambda: saved.append(dict(row)))
    assert saved and row['status'] == 'incomplete' and row['error_type']
    assert row['parent_exit_ns'] > row['parent_spawn_ns']
    assert row['timed_out'] is (kind == 'timeout')
