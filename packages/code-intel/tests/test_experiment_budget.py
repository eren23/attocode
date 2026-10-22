"""Online controller/resource accounting controls for bounded experiments."""
import json
import subprocess
import sys

from eval.quality import runner

PROBE = '''
import json, subprocess, sys, time
from pathlib import Path
from eval.quality import runner
from eval.quality.experiment_budget import BudgetGuard
root, scenario = Path(sys.argv[1]), sys.argv[2]
limits = {'rss_bytes':2**40, 'disk_bytes':2**40, 'evidence_bytes':2**40}
scratch, evidence = root/'scratch', root/'evidence'
scratch.mkdir(); evidence.mkdir()
marker = evidence/'retained.txt'; marker.write_text('retain')
child = None
deadline = time.monotonic()+10
if scenario == 'disk':
    (scratch/'source').write_bytes(b'x'*4096)
    (evidence/'report.tmp').write_bytes(b'y'*4096)
    limits['disk_bytes']=max(runner.disk_bytes(scratch),runner.disk_bytes(evidence))+1
elif scenario == 'rss':
    limits['rss_bytes']=1
else:
    child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(10)'])
    deadline=time.monotonic()+.1
guard=BudgetGuard([scratch,evidence],evidence,limits,deadline)
try:
    if child:
        guard.start(); child.wait(timeout=3)
    else:
        guard.sample()
finally:
    if child:
        if child.poll() is None: child.kill(); child.wait(timeout=2)
        guard.close()
print(json.dumps({'violation':guard.violation,'peaks':guard.peaks,
 'disk':runner.disk_bytes(scratch)+runner.disk_bytes(evidence),'marker':marker.read_text()}))
'''


def probe(root, scenario):
    # The probe controller owns only its own descendants, never another test's
    # session-scoped process or multiprocessing resource tracker.
    result = subprocess.run([sys.executable, '-c', PROBE, str(root), scenario], cwd=runner.REPO,
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_aggregate_disk_includes_external_evidence_and_atomic_temporary_file(tmp_path):
    result = probe(tmp_path, 'disk')
    assert result['violation'] == 'disk_bytes_budget'
    assert result['peaks']['disk_bytes'] == result['disk']


def test_controller_rss_is_part_of_aggregate_memory_budget(tmp_path):
    result = probe(tmp_path, 'rss')
    assert result['violation'] == 'rss_bytes_budget'
    assert result['peaks']['rss_bytes'] > 1


def test_complete_deadline_kills_only_owned_child_and_preserves_evidence(tmp_path):
    result = probe(tmp_path, 'deadline')
    assert result['violation'] == 'complete_deadline'
    assert result['marker'] == 'retain'
