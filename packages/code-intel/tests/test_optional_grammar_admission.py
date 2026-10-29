"""The maintained acquired-grammar gate rejects incomplete passing pytest runs."""
import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


def validator():
    source = Path(__file__).resolve().parents[1] / 'scripts/check_optional_grammars.py'
    spec = importlib.util.spec_from_file_location('optional_grammar_acquisition', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    check = getattr(module, 'validate_coverage', None)
    assert callable(check), 'language coverage: maintained gate lacks strict collection admission'
    return check


REQUIRED = {'test_fixture::test_a', 'test_fixture::test_b[x]'}
XML = b'<testsuites><testsuite><testcase classname="tests.test_fixture" name="test_a"/><testcase classname="tests.test_fixture" name="test_b[x]"/></testsuite></testsuites>'


def test_complete_grammar_collection_is_admitted():
    assert set(validator()(XML, REQUIRED)) == REQUIRED


@pytest.mark.parametrize('fault', ['missing', 'skipped', 'failure', 'error', 'duplicate', 'renamed', 'doctype', 'empty'])
def test_incomplete_grammar_collection_is_rejected(fault):
    root = ET.fromstring(XML)
    suite = root.find('testsuite')
    first = suite.find('testcase')
    if fault == 'missing':
        suite.remove(first)
    elif fault in {'skipped', 'failure', 'error'}:
        ET.SubElement(first, fault)
    elif fault == 'duplicate':
        suite.append(ET.fromstring(ET.tostring(first)))
    elif fault == 'renamed':
        first.set('name', 'unexpected')
    elif fault == 'empty':
        suite.clear()
    raw = ET.tostring(root)
    if fault == 'doctype':
        raw = b'<!DOCTYPE testsuites []>' + raw
    check = validator()
    with pytest.raises(ValueError):
        check(raw, REQUIRED)
