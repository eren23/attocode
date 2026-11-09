"""CI-only admission of prospectively declared, qualified pytest failures."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _path(repo, name, prefix, suffix):
    if not isinstance(name, str):
        raise ValueError('Expected relative path')
    path = PurePosixPath(name)
    if (path.is_absolute() or '..' in path.parts or '\\' in name
            or not name.startswith(prefix) or path.suffix != suffix
            or path.as_posix() != name):
        raise ValueError('Unsafe evidence/test path')
    target = repo / name
    if (not target.is_file() or not target.resolve().is_relative_to(repo.resolve())
            or any(p.is_symlink() for p in [target, *target.parents] if p != repo.parent)):
        raise ValueError('Missing or symlinked evidence/test path')
    return target


def load_contract(raw, repo):
    if len(raw) > 65536:
        raise ValueError('Oversized regression contract')
    try:
        value = json.loads(raw, object_pairs_hook=_unique)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('Malformed regression contract') from error
    keys = {'schema_version', 'profile', 'paths', 'cases', 'failures'}
    if (not isinstance(value, dict) or set(value) != keys
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or value['profile'] not in {'unit', 'native'}):
        raise ValueError('Unknown regression contract')
    paths, cases, failures = value['paths'], value['cases'], value['failures']
    if not isinstance(paths, list) or len(paths) > 30 or any(not isinstance(p, str) for p in paths):
        raise ValueError('Invalid test paths')
    if len(set(paths)) != len(paths) or bool(paths) != (value['profile'] == 'unit'):
        raise ValueError('Profile/test path mismatch')
    for path in paths:
        _path(repo, path, 'packages/code-intel/tests/', '.py')
        if not PurePosixPath(path).name.startswith('test_'):
            raise ValueError('Expected Python test file')
    if (not isinstance(cases, list) or not 1 <= len(cases) <= 500
            or any(not isinstance(c, str) or '::' not in c or not c.startswith('test_') for c in cases)
            or len(set(cases)) != len(cases)):
        raise ValueError('Invalid complete case inventory')
    if not isinstance(failures, dict) or not failures or not set(failures) <= set(cases):
        raise ValueError('Invalid expected failure inventory')
    if value['profile'] == 'native':
        inventory = json.loads((repo / 'packages/code-intel/scripts/optional_grammar_cases.json').read_bytes())['cases']
        if not inventory or len(inventory) != len(set(inventory)) or set(inventory) != set(cases):
            raise ValueError('Native contract differs from maintained case inventory')
    for failure in failures.values():
        if not isinstance(failure, dict) or set(failure) != {'message', 'properties'}:
            raise ValueError('Invalid failure declaration')
        message, properties = failure['message'], failure['properties']
        if (not isinstance(message, str) or not message.startswith('REGRESSION: ')
                or len(message) > 300 or '\n' in message or '\r' in message):
            raise ValueError('Expected semantic regression marker')
        if (not isinstance(properties, dict) or not properties
                or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v
                       for k, v in properties.items())):
            raise ValueError('Expected qualification properties')
    return value


def validate_result(raw, returncode, contract):
    if type(returncode) is not int or returncode != 1:
        raise ValueError('Expected pytest test-failure exit code 1')
    if len(raw) > 4 * 2**20 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('Unsafe or oversized pytest XML')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise ValueError('Malformed pytest XML') from error
    if root.tag not in {'testsuite', 'testsuites'} or list(root.iter('error')) or list(root.iter('skipped')):
        raise ValueError('Collection, setup, teardown errors or skipped cases')
    actual, failed = [], []
    for case in root.iter('testcase'):
        parts = case.get('classname', '').split('.')
        start = next((i for i, part in enumerate(parts) if part.startswith('test_')), None)
        if start is None or not case.get('name'):
            raise ValueError('Unnamed testcase')
        identity = '.'.join(parts[start:]) + '::' + case.get('name')
        actual.append(identity)
        failures = case.findall('failure')
        expected = contract['failures'].get(identity)
        if bool(failures) != (expected is not None) or len(failures) > 1:
            raise ValueError('Unexpected failure or unexpected pass: ' + identity)
        if expected is None:
            continue
        message = failures[0].get('message', '').splitlines()
        if not message or message[0] != 'AssertionError: ' + expected['message']:
            raise ValueError('Wrong assertion failure: ' + identity)
        properties = {}
        for item in case.findall('properties/property'):
            name = item.get('name')
            if not name or name in properties:
                raise ValueError('Unnamed or duplicate testcase property')
            properties[name] = item.get('value')
        if any(properties.get(k) != v for k, v in expected['properties'].items()):
            raise ValueError('Unqualified regression input: ' + identity)
        failed.append(identity)
    if len(actual) != len(set(actual)) or set(actual) != set(contract['cases']):
        raise ValueError('Missing, duplicate or unexpected testcases')
    if len(list(root.iter('failure'))) != len(failed) or set(failed) != set(contract['failures']):
        raise ValueError('Unexpected failures outside declared testcases')
    return {'status': 'expected-regression-observed', 'cases': sorted(actual), 'failures': sorted(failed)}


def validate_native(report, head):
    if (report.get('head') != head or report.get('exit_code') != 1
            or report.get('status') != 'incomplete' or not report.get('before')
            or report.get('before') != report.get('after')
            or report.get('source_unchanged') is not True
            or report.get('owned_scratch_removed') is not True
            or report.get('coverage', {}).get('status') != 'rejected'):
        raise ValueError('Native acquisition/source/grammar/cleanup contract failed')


def _sources(repo):
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=repo).decode().split('\0')
    return {name: hashlib.sha256((repo / name).read_bytes()).hexdigest()
            for name in names if name and (repo / name).is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--profile', action='store_true')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[3]
    manifest = _path(repo, args.contract, '.github/regressions/', '.json')
    contract = load_contract(manifest.read_bytes(), repo)
    if args.profile:
        print('profile=' + contract['profile'])
        return 0
    if not os.environ.get('GITHUB_ACTIONS') or args.output is None:
        parser.error('Execution requires Actions and a new runner temporary output directory')
    output = args.output.resolve()
    runner = Path(os.environ['RUNNER_TEMP']).resolve()
    if output == runner or not output.is_relative_to(runner):
        parser.error('Output must be within RUNNER_TEMP')
    output.mkdir(parents=True, exist_ok=False)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    before = _sources(repo)
    proof = {'status': 'rejected', 'head': head, 'contract': args.contract,
             'contract_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(), 'sources': before}
    (output / 'contract.json').write_bytes(manifest.read_bytes())
    native = contract['profile'] == 'native'
    xml = output / 'native/optional-depth.xml' if native else output / 'pytest.xml'
    command = [sys.executable]
    if native:
        command += ['packages/code-intel/scripts/check_optional_grammars.py',
                    '--cache', str(output / 'grammars'), '--depth-evidence', str(output / 'native')]
    else:
        command += ['-m', 'pytest', '-c', 'packages/code-intel/pyproject.toml',
                    '--confcutdir=packages/code-intel/tests', *contract['paths'], '-q',
                    '--junitxml=' + str(xml), '--basetemp=' + str(output / 'pytest-scratch')]
    proof['command'] = command
    try:
        if head != os.environ['GITHUB_SHA']:
            raise ValueError('Checkout differs from dispatched head')
        with (output / 'pytest.log').open('wb') as log:
            process = subprocess.Popen(command, cwd=repo, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            try:
                code = process.wait(timeout=900 if native else 300)
            except subprocess.TimeoutExpired as error:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise ValueError('Regression command exceeded deadline') from error
        proof['exit_code'] = code
        proof.update(validate_result(xml.read_bytes(), code, contract))
        if native:
            validate_native(json.loads((output / 'native/report.json').read_bytes()), head)
        if _sources(repo) != before:
            raise ValueError('Tracked source changed during regression run')
        print('Expected regression observed; strict product GREEN is still required before merging.')
        return 0
    except (ValueError, OSError, KeyError) as error:
        proof.update(status='rejected', reason=str(error))
        print('Regression evidence rejected: ' + str(error), file=sys.stderr)
        return 1
    finally:
        (output / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
