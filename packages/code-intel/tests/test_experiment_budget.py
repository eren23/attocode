"""Online controller/resource accounting controls for bounded experiments."""
import subprocess
import sys
import time

from eval.quality import runner
from eval.quality.experiment_budget import BudgetGuard


def limits(**changes):
    return dict({'rss_bytes': 2**40, 'disk_bytes': 2**40, 'evidence_bytes': 2**40}, **changes)


def test_aggregate_disk_includes_external_evidence_and_atomic_temporary_file(tmp_path):
    scratch, evidence = tmp_path / 'scratch', tmp_path / 'evidence'
    scratch.mkdir()
    evidence.mkdir()
    (scratch / 'source').write_bytes(b'x' * 4096)
    (evidence / 'report.tmp').write_bytes(b'y' * 4096)
    cap = max(runner.disk_bytes(scratch), runner.disk_bytes(evidence)) + 1
    guard = BudgetGuard([scratch, evidence], evidence, limits(disk_bytes=cap), time.monotonic() + 10)
    guard.sample()
    assert guard.violation == 'disk_bytes_budget'
    assert guard.peaks['disk_bytes'] == runner.disk_bytes(scratch) + runner.disk_bytes(evidence)


def test_controller_rss_is_part_of_aggregate_memory_budget(tmp_path):
    guard = BudgetGuard([tmp_path], tmp_path, limits(rss_bytes=1), time.monotonic() + 10)
    guard.sample()
    assert guard.violation == 'rss_bytes_budget'
    assert guard.peaks['rss_bytes'] > 1


def test_complete_deadline_kills_only_owned_child_and_preserves_evidence(tmp_path):
    marker = tmp_path / 'retained.txt'
    marker.write_text('retain')
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'])
    guard = BudgetGuard([tmp_path], tmp_path, limits(), time.monotonic() + .1)
    guard.start()
    try:
        child.wait(timeout=3)
        assert guard.violation == 'complete_deadline'
        assert marker.read_text() == 'retain'
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)
        guard.close()
