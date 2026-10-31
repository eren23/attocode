"""Temporary sensitivity and acceptance check for the existing fallback boundary."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from eval.quality.runner import REPO, write_json

DESIGN = Path(__file__).with_name('experiments') / 'boundary.json'


def run(root):
    frozen = json.loads(DESIGN.read_bytes())
    code = subprocess.run([sys.executable, '-m', 'eval.quality.boundary_trial',
                           '--pytest', str(root)], cwd=REPO).returncode
    cases = list(ET.fromstring((root / 'evidence/boundary.xml').read_bytes()).iter('testcase'))
    failed = [c for c in cases if c.find('failure') is not None]
    write_json(root / 'evidence/boundary-verdict.json', {
        'exit_code': code, 'cases': len(cases), 'failures': [c.get('name') for c in failed],
        'stage': frozen['stage'], 'expected_failures': frozen['expected_failures']})
    if (len(cases) != frozen['expected_cases']
            or len({(c.get('classname'), c.get('name')) for c in cases}) != len(cases)
            or any(c.find(tag) is not None for c in cases for tag in ('error', 'skipped'))
            or {c.get('name') for c in failed} != set(frozen['expected_failures'])
            or code != (1 if frozen['expected_failures'] else 0)
            or any('boundary:' not in ''.join(c.find('failure').itertext()) for c in failed)):
        raise ValueError('boundary sensitivity inventory/outcome mismatch; retain original attempt')


if __name__ == '__main__':
    import pytest

    from eval.quality.experiments import TESTS

    parser = argparse.ArgumentParser()
    parser.add_argument('--pytest', type=Path, required=True)
    root = parser.parse_args().pytest
    frozen = json.loads(DESIGN.read_bytes())

    class BoundarySensitivity:
        def pytest_sessionstart(self, session):
            from attocode_intel._internal.integrations.context import codebase_ast

            applied = frozen['stage'] == 'mutation-499'
            original = codebase_ast._bounded_fallback_end
            if applied:
                def shortened(lines, start):
                    return original(lines[:start + 499], start)
                codebase_ast._bounded_fallback_end = shortened
            write_json(root / 'evidence/boundary-mutation.json', {
                'stage': frozen['stage'], 'applied': applied,
                'method': 'in-memory input truncated at start+499; product files unchanged',
                'original_source': codebase_ast.__file__,
            })

    raise SystemExit(pytest.main(['-c', 'packages/code-intel/pyproject.toml',
        '--confcutdir=packages/code-intel/tests', '-q',
        '--basetemp=' + str(root / 'work/pytest'), '-o', 'cache_dir=' + str(root / 'work/cache'),
        '--junitxml=' + str(root / 'evidence/boundary.xml'),
        '-p', 'eval.quality.experiment_origin',
        *['packages/code-intel/tests/' + name for name in TESTS]], plugins=[BoundarySensitivity()]))
