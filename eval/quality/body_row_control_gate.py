"""Exact JUnit admission before the real diagnostic; stdlib only."""
import json
from pathlib import Path
import sys
from xml.etree import ElementTree as ET


def admit_controls(xml_bytes, expected):
    root = ET.fromstring(xml_bytes)
    cases = list(root.iter('testcase'))
    identities = []
    for case in cases:
        if any(list(case.iter(name)) for name in ('failure', 'error', 'skipped')):
            raise ValueError('control did not pass')
        classname = case.attrib['classname']
        if 'test_' not in classname:
            raise ValueError('unknown control classname')
        identities.append(classname[classname.index('test_'):] + '::' + case.attrib['name'])
    if len(identities) != len(set(identities)):
        raise ValueError('duplicate control instance')
    if sorted(identities) != sorted(expected):
        raise ValueError('control identities differ')
    return {'passed': len(identities), 'identities': sorted(identities)}


if __name__ == '__main__':
    expected = json.loads(Path(sys.argv[2]).read_text())['identities']
    report = admit_controls(Path(sys.argv[1]).read_bytes(), expected)
    Path(sys.argv[3]).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'all_expected_controls_passed': report['passed']}))
