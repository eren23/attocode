"""Record the old observer's expected coverage failures without a failing CI job."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

from eval.quality.runner import REPO, write_json


def run(root):
    design = json.loads((REPO / 'eval/quality/experiments/startup-control.json').read_bytes())
    evidence = root / 'evidence/legacy'
    evidence.mkdir()
    env = dict(os.environ, STARTUP_LEGACY_CONTROL='1', ATTOCODE_EXPERIMENT_EVIDENCE=str(evidence))
    tests = 'packages/code-intel/tests/test_startup_profile.py'
    command = [sys.executable, '-m', 'pytest', '-c', 'packages/code-intel/pyproject.toml',
               '--confcutdir=packages/code-intel/tests', '-q', '-p', 'eval.quality.experiment_origin',
               '--basetemp=' + str(root / 'work/legacy'), '-o', 'cache_dir=' + str(root / 'work/legacy-cache'),
               '--junitxml=' + str(evidence / 'controls.xml'),
               *[tests + '::' + name for name in design['legacy_expected_failures']]]
    result = subprocess.run(command, cwd=REPO, env=env, check=False)
    cases = list(ET.parse(evidence / 'controls.xml').getroot().iter('testcase'))
    if (result.returncode != 1 or len(cases) != 2 or
            [c.get('name') for c in cases] != design['legacy_expected_failures'] or
            any(len(c.findall('failure')) != 1 or c.find('error') is not None or
                c.find('skipped') is not None for c in cases)):
        raise ValueError('legacy scope control did not produce the exact two expected assertion failures')
    for case in cases:
        if design['legacy_failure_markers'][case.get('name')] not in case.find('failure').get('message', ''):
            raise ValueError('legacy failed for an unrelated setup/runtime reason')
    write_json(evidence / 'admission.json', {'complete': True, 'diagnostic_only': True,
               'legacy_expected_failures_observed': design['legacy_expected_failures'],
               'pytest_exit_code': result.returncode, 'stage': design['stage']})
