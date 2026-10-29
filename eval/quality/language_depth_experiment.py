"""Temporary causal native coverage operator; all real execution stays in GHA."""
from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from eval.quality.native_experiment import distribution_identity, grammar_identity
from eval.quality.runner import REPO, write_json


def run(root):
    from eval.quality.experiments import TESTS
    design = json.loads((REPO / 'eval/quality/experiments/languagedepth.json').read_bytes())
    cache = root / 'cache/grammars'
    shutil.copytree(Path(os.environ['QUALITY_GRAMMAR_CACHE']), cache)
    os.environ['QUALITY_GRAMMAR_CACHE'] = str(cache)
    grammar = grammar_identity(cache)
    crystal = importlib.metadata.distribution('tree-sitter-crystal')
    direct = json.loads(crystal.read_text('direct_url.json'))
    assert direct['vcs_info']['commit_id'] == design['crystal_source']
    before = {'grammar': grammar, 'crystal': distribution_identity(('tree-sitter-crystal',)), 'direct_url': direct}
    write_json(root / 'evidence/grammar-before.json', before)
    tests = [*TESTS, 'test_optional_language_depth.py']
    xml = root / 'evidence/languagedepth-controls.xml'
    environment = {**os.environ, 'QUALITY_LANGUAGE_DEPTH': '1',
                   'QUALITY_LANGUAGE_EVIDENCE': str(root / 'evidence/native-depth')}
    # Cache configuration is process-local. Pytest must share the configured loader.
    command = ('import os,sys; import tree_sitter_language_pack as p; '
               'p.configure(cache_dir=os.environ["QUALITY_GRAMMAR_CACHE"]); '
               'import pytest; sys.exit(pytest.main(sys.argv[1:]))')
    result = subprocess.run([sys.executable, '-c', command,
        '-c', 'packages/code-intel/pyproject.toml', '--confcutdir=packages/code-intel/tests',
        *['packages/code-intel/tests/' + name for name in tests],
        '-p', 'eval.quality.experiment_origin', '-q',
        '--basetemp=' + str(root / 'work/pytest'), '-o', 'cache_dir=' + str(root / 'work/cache'),
        '--junitxml=' + str(xml)], env=environment, cwd=REPO)
    data = ET.fromstring(xml.read_bytes())
    cases = list(data.iter('testcase'))
    failures = [case for case in cases if case.find('failure') is not None]
    failed = {case.get('name') for case in failures}
    # Write the observed verdict first; unexpected failures never disappear.
    write_json(root / 'evidence/languagedepth-control-verdict.json', {
        'stage': design['stage'], 'cases': len(cases), 'failed': sorted(failed),
        'errors': len(list(data.iter('error'))), 'skipped': len(list(data.iter('skipped'))),
        'exit_code': result.returncode})
    after = {'grammar': grammar_identity(cache), 'crystal': distribution_identity(('tree-sitter-crystal',)), 'direct_url': direct}
    write_json(root / 'evidence/grammar-after.json', after)
    assert before == after
    assert len(cases) == design['expected_cases'] and len({(c.get('classname'), c.get('name')) for c in cases}) == len(cases)
    assert not list(data.iter('error')) and not list(data.iter('skipped'))
    if design['stage'] == 'baseline':
        assert set(design['mandatory_failures']) <= failed <= set(design['new_native_cases'])
        assert all('language coverage:' in ''.join(case.find('failure').itertext()) for case in failures)
        assert result.returncode == 1
    else:
        assert design['stage'] == 'green' and not failures and result.returncode == 0
