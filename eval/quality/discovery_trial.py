"""Temporary exact-inventory capacity source-policy regression controller."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from eval.quality.runner import REPO, write_json

DESIGN = Path(__file__).with_name('experiments') / 'discovery.json'


def run(root):
    env = os.environ.copy()
    code = subprocess.run([sys.executable, '-m', 'eval.quality.discovery_trial',
                           '--pytest', str(root)], cwd=REPO, env=env).returncode
    cases = list(ET.fromstring((root / 'evidence/followup.xml').read_bytes()).iter('testcase'))
    frozen = json.loads(DESIGN.read_bytes())
    failed = [c for c in cases if c.find('failure') is not None]
    write_json(root / 'evidence/followup-verdict.json', {
        'exit_code': code, 'cases': len(cases), 'failures': [c.get('name') for c in failed],
        'stage': frozen['stage'], 'expected_failures': frozen['expected_failures']})
    if (len(cases) != frozen['expected_cases']
            or len({(c.get('classname'), c.get('name')) for c in cases}) != len(cases)
            or any(c.find(tag) is not None for c in cases for tag in ('error', 'skipped'))
            or {c.get('name') for c in failed} != set(frozen['expected_failures'])
            or code != (1 if frozen['expected_failures'] else 0)):
        raise ValueError('followup control inventory/outcome mismatch; preserve original attempt')


if __name__ == '__main__':
    import pytest

    from eval.quality.experiments import TESTS

    parser = argparse.ArgumentParser()
    parser.add_argument('--pytest', type=Path, required=True)
    root = parser.parse_args().pytest
    tests = list(dict.fromkeys([*TESTS, 'test_discovery_ceiling.py']))
    selected = ['packages/code-intel/tests/' + name for name in tests]
    raise SystemExit(pytest.main(['-c', 'packages/code-intel/pyproject.toml',
        '--confcutdir=packages/code-intel/tests', '-q',
        '--basetemp=' + str(root / 'work/pytest'), '-o', 'cache_dir=' + str(root / 'work/pytest-cache'),
        '--junitxml=' + str(root / 'evidence/followup.xml'),
        '-p', 'eval.quality.experiment_origin', *selected]))
