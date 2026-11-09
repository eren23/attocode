"""Expected RED is evidence only when every declared failure is accounted for."""
import importlib.util
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


def checker(record_property):
    source = Path(__file__).resolve().parents[1] / 'scripts/check_expected_regression.py'
    record_property('qualification', 'classifier-api-absence')
    assert source.is_file(), 'REGRESSION: expected regression classifier missing'
    spec = importlib.util.spec_from_file_location('expected_regression', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def contract():
    return {'schema_version': 1, 'profile': 'unit',
            'paths': ['packages/code-intel/tests/test_example.py'],
            'cases': ['test_example::test_regression', 'test_example::test_control'],
            'failures': {'test_example::test_regression': {
                'message': 'REGRESSION: receiver identity',
                'properties': {'qualified_input': 'true'}}}}


XML = b'''<testsuites><testsuite tests="2" failures="1" errors="0" skipped="0">
<testcase classname="tests.test_example" name="test_regression">
<properties><property name="qualified_input" value="true"/></properties>
<failure message="AssertionError: REGRESSION: receiver identity">AssertionError: REGRESSION: receiver identity</failure>
</testcase><testcase classname="tests.test_example" name="test_control"/>
</testsuite></testsuites>'''


def test_exact_failure_and_control_are_admitted(record_property):
    module = checker(record_property)
    result = module.validate_result(XML, 1, contract())
    assert result == {'status': 'expected-regression-observed',
                      'cases': sorted(contract()['cases']),
                      'failures': ['test_example::test_regression']}


@pytest.mark.parametrize('fault', [
    'unexpected-pass', 'extra-failure', 'missing', 'extra', 'duplicate', 'skip',
    'error', 'teardown-error', 'wrong-message', 'wrong-exception', 'missing-property',
    'wrong-property', 'duplicate-property', 'doctype', 'malformed', 'oversized',
    'exit-zero', 'exit-two', 'exit-five', 'signal',
])
def test_invalid_run_is_rejected(record_property, fault):
    module = checker(record_property)
    root = ET.fromstring(XML)
    suite = root.find('testsuite')
    first, control = suite.findall('testcase')
    failure = first.find('failure')
    code = 1
    if fault == 'unexpected-pass':
        first.remove(failure)
    elif fault == 'extra-failure':
        ET.SubElement(control, 'failure', message='AssertionError: different')
    elif fault == 'missing':
        suite.remove(control)
    elif fault == 'extra':
        ET.SubElement(suite, 'testcase', classname='tests.test_example', name='test_extra')
    elif fault == 'duplicate':
        suite.append(ET.fromstring(ET.tostring(control)))
    elif fault in {'skip', 'error', 'teardown-error'}:
        ET.SubElement(control, 'skipped' if fault == 'skip' else 'error')
    elif fault in {'wrong-message', 'wrong-exception'}:
        message = ('AssertionError: unrelated' if fault == 'wrong-message'
                   else 'TypeError: REGRESSION: receiver identity')
        failure.set('message', message)
        failure.text = message
    elif fault == 'missing-property':
        first.remove(first.find('properties'))
    elif fault == 'wrong-property':
        first.find('properties/property').set('value', 'false')
    elif fault == 'duplicate-property':
        ET.SubElement(first.find('properties'), 'property', name='qualified_input', value='true')
    elif fault.startswith('exit-'):
        code = {'exit-zero': 0, 'exit-two': 2, 'exit-five': 5}[fault]
    elif fault == 'signal':
        code = -11
    raw = ET.tostring(root)
    if fault == 'doctype':
        raw = b'<!DOCTYPE testsuites []>' + raw
    elif fault == 'malformed':
        raw = b'<testsuites>'
    elif fault == 'oversized':
        raw = b' ' * (4 * 2**20 + 1)
    with pytest.raises(ValueError):
        module.validate_result(raw, code, contract())


@pytest.mark.parametrize('fault', ['profile', 'no-failures', 'unknown-failure',
                                 'duplicate-case', 'traversal', 'absolute', 'option',
                                 'empty-marker', 'no-qualification', 'unknown-key'])
def test_invalid_contract_is_rejected(record_property, fault, tmp_path):
    module = checker(record_property)
    value = contract()
    path = tmp_path / value['paths'][0]
    path.parent.mkdir(parents=True)
    path.write_text('')
    if fault == 'profile':
        value['profile'] = 'shell'
    elif fault == 'no-failures':
        value['failures'] = {}
    elif fault == 'unknown-failure':
        value['failures']['test_missing::test_missing'] = value['failures'].pop(value['cases'][0])
    elif fault == 'duplicate-case':
        value['cases'].append(value['cases'][0])
    elif fault in {'traversal', 'absolute', 'option'}:
        value['paths'] = {'traversal': ['packages/code-intel/tests/../../secret.py'],
                          'absolute': ['/tmp/test.py'], 'option': ['--override-ini=addopts='] }[fault]
    elif fault == 'empty-marker':
        value['failures'][value['cases'][0]]['message'] = ''
    elif fault == 'no-qualification':
        value['failures'][value['cases'][0]]['properties'] = {}
    elif fault == 'unknown-key':
        value['command'] = 'true'
    with pytest.raises(ValueError):
        module.load_contract(json.dumps(value).encode(), tmp_path)


def test_valid_contract_preserves_literal_ids(record_property, tmp_path):
    module = checker(record_property)
    value = contract()
    path = tmp_path / value['paths'][0]
    path.parent.mkdir(parents=True)
    path.write_text('')
    assert module.load_contract(json.dumps(value).encode(), tmp_path) == value


@pytest.mark.parametrize('fault', ['exit', 'status', 'grammar', 'source', 'cleanup', 'coverage', 'head'])
def test_native_acquisition_or_lifecycle_failure_is_rejected(record_property, fault):
    module = checker(record_property)
    report = {'exit_code': 1, 'status': 'incomplete', 'head': 'a' * 40,
              'before': {'go': 'same'}, 'after': {'go': 'same'},
              'source_unchanged': True, 'owned_scratch_removed': True,
              'coverage': {'status': 'rejected'}}
    report.update({'exit': {'exit_code': 2}, 'status': {'status': 'complete'},
                   'grammar': {'after': {'go': 'changed'}}, 'source': {'source_unchanged': False},
                   'cleanup': {'owned_scratch_removed': False},
                   'coverage': {'coverage': {'status': 'passed'}}, 'head': {'head': 'b' * 40}}[fault])
    with pytest.raises(ValueError):
        module.validate_native(report, 'a' * 40)


def test_native_expected_red_preserves_lifecycle(record_property):
    module = checker(record_property)
    report = {'exit_code': 1, 'status': 'incomplete', 'head': 'a' * 40,
              'before': {'go': 'same'}, 'after': {'go': 'same'},
              'source_unchanged': True, 'owned_scratch_removed': True,
              'coverage': {'status': 'rejected'}}
    module.validate_native(report, 'a' * 40)


@pytest.mark.parametrize('fault', ['missing', 'extra', 'duplicate'])
def test_native_contract_requires_maintained_inventory(record_property, tmp_path, fault):
    module = checker(record_property)
    value = contract()
    value.update(profile='native', paths=[])
    inventory = list(value['cases'])
    if fault == 'missing':
        inventory.append('test_required::test_control')
    elif fault == 'extra':
        value['cases'].append('test_unexpected::test_control')
    else:
        inventory.append(inventory[0])
    path = tmp_path / 'packages/code-intel/scripts/optional_grammar_cases.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'cases': inventory}))
    record_property('qualified_input', 'true')
    rejected = False
    try:
        module.load_contract(json.dumps(value).encode(), tmp_path)
    except ValueError:
        rejected = True
    assert rejected, 'REGRESSION: native inventory mismatch admitted'
