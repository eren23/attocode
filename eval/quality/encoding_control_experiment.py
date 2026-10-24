"""Online serialization controls; expected baseline RED is data in a successful job."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

from eval.quality.runner import REPO, write_json


def run(root):
    from eval.quality.experiments import TESTS

    design = json.loads((REPO / 'eval/quality/experiments/encoding_control.json').read_bytes())
    evidence = root / 'evidence/controls'
    evidence.mkdir()
    baseline = design['stage'] == 'baseline'
    names = ['test_snapshot_encoding.py'] if baseline else [*TESTS, 'test_snapshot_encoding.py']
    env = dict(os.environ, ATTOCODE_EXPERIMENT_EVIDENCE=str(evidence),
               ENCODING_CONTROL_EVIDENCE=str(evidence / 'work'))
    command = [sys.executable, '-m', 'pytest', '-c', 'packages/code-intel/pyproject.toml',
               '--confcutdir=packages/code-intel/tests', '-q', '-p', 'eval.quality.experiment_origin',
               '--basetemp=' + str(root / 'work/pytest'), '-o', 'cache_dir=' + str(root / 'work/cache'),
               '--junitxml=' + str(evidence / 'controls.xml'),
               *['packages/code-intel/tests/' + name for name in names]]
    result = subprocess.run(command, cwd=REPO, env=env, check=False)
    tree = ET.parse(evidence / 'controls.xml').getroot()
    failures = [(c, c.find('failure')) for c in tree.iter('testcase') if c.find('failure') is not None]
    if any(list(tree.iter(k)) for k in ('error', 'skipped')):
        raise ValueError('error/skipped serialization controls')
    if baseline:
        if (result.returncode != 1 or len(failures) != 1
                or failures[0][0].get('name') != 'test_serializer_reduces_interpreted_call_work'
                or 'bounded serialization still uses excessive interpreted work' not in failures[0][1].get('message', '')):
            raise ValueError('baseline did not produce the exact expected work-control assertion')
    elif result.returncode != 0 or failures:
        raise ValueError('candidate correctness/work controls failed')
    write_json(evidence / 'admission.json', {'complete': True, 'stage': design['stage'],
               'expected_assertion_failures': int(baseline), 'cases': len(list(tree.iter('testcase'))),
               'work': json.loads((evidence / 'work/work.json').read_bytes())})
