"""Temporary exact-inventory RED/GREEN controller for the demonstrated MLI route."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from eval.quality.runner import REPO, write_json

DESIGN = Path(__file__).with_name('experiments') / 'ocaml-routing.json'


def run(root):
    cache = root / 'cache/grammars'
    shutil.copytree(Path(os.environ['QUALITY_GRAMMAR_CACHE']), cache)
    env = os.environ.copy()
    env.update(QUALITY_GRAMMAR_CACHE=str(cache), QUALITY_LANGUAGE_DEPTH='1',
               QUALITY_LANGUAGE_EVIDENCE=str(root / 'evidence/native-routing'))
    code = subprocess.run([sys.executable, '-m', 'eval.quality.ocaml_routing_experiment',
                           '--pytest', str(root)], cwd=REPO, env=env).returncode
    cases = list(ET.fromstring((root / 'evidence/routing.xml').read_bytes()).iter('testcase'))
    frozen = json.loads(DESIGN.read_bytes())
    failed = [c for c in cases if c.find('failure') is not None]
    write_json(root / 'evidence/routing-verdict.json', {
        'exit_code': code, 'cases': len(cases), 'failures': [c.get('name') for c in failed],
        'stage': frozen['stage'], 'expected_failures': frozen['expected_failures']})
    if (len(cases) != frozen['expected_cases']
            or len({(c.get('classname'), c.get('name')) for c in cases}) != len(cases)
            or any(c.find(tag) is not None for c in cases for tag in ('error', 'skipped'))
            or {c.get('name') for c in failed} != set(frozen['expected_failures'])
            or code != (1 if frozen['expected_failures'] else 0)
            or any('ocaml interface:' not in ''.join(c.find('failure').itertext()) for c in failed)):
        raise ValueError('routing control inventory/outcome mismatch; preserve original attempt')


if __name__ == '__main__':
    import pytest
    import tree_sitter_language_pack as pack

    from eval.quality.experiments import TESTS

    parser = argparse.ArgumentParser()
    parser.add_argument('--pytest', type=Path, required=True)
    root = parser.parse_args().pytest
    pack.configure(cache_dir=os.environ['QUALITY_GRAMMAR_CACHE'])
    tests = list(dict.fromkeys([*TESTS, 'test_ocaml_parser_routing.py']))
    selected = ['packages/code-intel/tests/' + name for name in tests]
    selected += ['packages/code-intel/tests/test_optional_language_depth.py::test_ocaml_interface_native_grammar_route',
                 'packages/code-intel/tests/test_optional_language_depth.py::test_ocaml_interface_native_value_signature_ranges']
    raise SystemExit(pytest.main(['-c', 'packages/code-intel/pyproject.toml',
        '--confcutdir=packages/code-intel/tests', '-q',
        '--basetemp=' + str(root / 'work/pytest'), '-o', 'cache_dir=' + str(root / 'work/pytest-cache'),
        '--junitxml=' + str(root / 'evidence/routing.xml'),
        '-p', 'eval.quality.experiment_origin', *selected]))
