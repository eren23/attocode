"""Run frozen expected baseline failures and candidate passes in one CI job."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from eval.quality.restart_experiment import archive_engine, engine_files, require
from eval.quality.runner import REPO, write_json


def run(root, design):
    evidence, work = root / 'evidence/control-pair', root / 'work/control-pair'
    evidence.mkdir()
    work.mkdir()
    candidate = Path(os.environ['ATTOCODE_EXPERIMENT_ENGINE'])
    test = REPO / design['test_file']
    test_hash = hashlib.sha256(test.read_bytes()).hexdigest()
    require(test_hash == design['test_sha256'], 'control test bytes changed')
    baseline = archive_engine(design['baseline_commit'], work / 'baseline-engine')
    engines = {'baseline': baseline, 'candidate': candidate}
    identities = {arm: engine_files(engine) for arm, engine in engines.items()}
    changed = sorted(name for name in identities['baseline'].keys() | identities['candidate'].keys()
                     if identities['baseline'].get(name) != identities['candidate'].get(name))
    require(changed == design['candidate_files'], 'paired product scope changed')
    expected = set(design['cases'])
    expected_red = set(design['baseline_failures'])
    require(expected_red and expected_red < expected, 'control needs failed baseline and passing control')
    report = {'status': 'incomplete', 'decision': None, 'test_sha256': test_hash,
              'baseline_commit': design['baseline_commit'], 'engines': identities, 'phases': []}
    write_json(evidence / 'control-pair.json', report)
    for arm, engine in engines.items():
        dest = evidence / arm
        dest.mkdir()
        scratch = work / (arm + '-tests')
        scratch.mkdir()
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(engine.parent), str(REPO)]),
                   ATTOCODE_EXPERIMENT_ENGINE=str(engine), ATTOCODE_EXPERIMENT_EVIDENCE=str(dest))
        command = [sys.executable, '-m', 'pytest', '-c', 'packages/code-intel/pyproject.toml',
                   '--confcutdir=packages/code-intel/tests', '-q',
                   '--basetemp=' + str(scratch / 'pytest'), '-o', 'pythonpath=',
                   '-o', 'cache_dir=' + str(scratch / 'cache'),
                   '--junitxml=' + str(dest / 'results.xml'), '-p', 'eval.quality.experiment_origin',
                   *[design['test_file'] + '::' + name for name in design['cases']]]
        with (dest / 'process.log').open('xb') as log:
            result = subprocess.run(command, cwd=REPO, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=120, check=False)
        raw = (dest / 'results.xml').read_bytes()
        require(b'<!DOCTYPE' not in raw.upper(), 'unexpected XML declarations')
        tree = ET.fromstring(raw)
        cases = list(tree.iter('testcase'))
        names = [case.get('name') for case in cases]
        require(len(names) == len(expected) and set(names) == expected, 'missing/repeated control cases')
        require(not list(tree.iter('error')) and not list(tree.iter('skipped')), 'control error or skip')
        failures = {case.get('name') for case in cases if case.find('failure') is not None}
        require(failures == (expected_red if arm == 'baseline' else set()), 'unexpected control outcome')
        require(result.returncode == (1 if arm == 'baseline' else 0), 'unexpected pytest exit')
        for case in cases:
            failure = case.find('failure')
            if failure is not None:
                detail = failure.get('message', '') + (failure.text or '')
                require('AssertionError' in detail
                        and design['baseline_failure_messages'][case.get('name')] in detail,
                        'baseline failed outside asserted behavior')
        origin = json.loads((dest / 'pytest-origin.json').read_bytes())
        require(origin['exitstatus'] == result.returncode and origin['pid'] > 0
                and origin['origins']['attocode_intel'] == '__init__.py', 'missing child origin')
        require(engine_files(engine) == identities[arm]
                and hashlib.sha256(test.read_bytes()).hexdigest() == test_hash, 'control input changed')
        report['phases'].append({'arm': arm, 'expected_outcome_admitted': True,
            'exit_code': result.returncode, 'failed_cases': sorted(failures), 'passed_cases': sorted(expected - failures),
            'xml_sha256': hashlib.sha256(raw).hexdigest(), 'pid': origin['pid'], 'origins': origin['origins']})
        write_json(evidence / 'control-pair.json', report)
    require(len({row['pid'] for row in report['phases']}) == 2, 'controls reused a process')
    report['status'] = 'complete'
    write_json(evidence / 'control-pair.json', report)
