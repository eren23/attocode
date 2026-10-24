"""Expected absence assertion / positive observer controls, all runtime online."""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

from eval.quality.runner import REPO, write_json


def run(root):
    from eval.quality.experiments import TESTS

    design = json.loads((REPO / 'eval/quality/experiments/stage_control.json').read_bytes())
    evidence = root / 'evidence/controls'
    evidence.mkdir()
    test = 'packages/code-intel/tests/test_unprofiled_stages.py'
    selected = [test + '::test_stage_observer_captures_real_nested_calls'] if design['stage'] == 'baseline' else [
        *['packages/code-intel/tests/' + name for name in TESTS], test]
    command = [sys.executable, '-m', 'pytest', '-c', 'packages/code-intel/pyproject.toml',
               '--confcutdir=packages/code-intel/tests', '-q', '--basetemp=' + str(root / 'work/pytest'),
               '-o', 'cache_dir=' + str(root / 'work/cache'), '--junitxml=' + str(evidence / 'controls.xml'),
               '-p', 'eval.quality.experiment_origin', *selected]
    result = subprocess.run(command, cwd=REPO, env=dict(os.environ, ATTOCODE_EXPERIMENT_EVIDENCE=str(evidence)))
    tree = ET.fromstring((evidence / 'controls.xml').read_bytes())
    cases = list(tree.iter('testcase'))
    failures = [(c, c.find('failure')) for c in cases if c.find('failure') is not None]
    if any(list(tree.iter(key)) for key in ('error', 'skipped')):
        raise ValueError('control errors or skips')
    if design['stage'] == 'baseline':
        if not (result.returncode == 1 and len(cases) == len(failures) == 1
                and failures[0][0].get('name') == 'test_stage_observer_captures_real_nested_calls'
                and 'unprofiled stage clock observer is unavailable' in failures[0][1].get('message', '')):
            raise ValueError('baseline absence assertion differs')
    elif result.returncode or failures or not cases:
        raise ValueError('positive observer controls failed')
    write_json(evidence / 'admission.json', {'stage': design['stage'], 'cases': len(cases),
               'passed': len(cases) - len(failures), 'expected_assertion_failures': len(failures)})
