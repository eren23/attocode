"""One online baseline/candidate correctness control; no performance measurement."""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = 'eb3b21d6925d27c1addfe106cbc23b828e2bf4cc'
PREFIX = 'packages/code-intel/src/'
TEST = 'packages/code-intel/tests/test_symbol_order.py'


def main():
    assert os.environ.get('GITHUB_ACTIONS') == 'true', 'ONLINE only'
    out = Path('quality-artifacts/symbol-order')
    out.mkdir(parents=True, exist_ok=False)
    scratch = Path(tempfile.mkdtemp(prefix='symbol-order-', dir=os.environ['RUNNER_TEMP']))
    result = {'status': 'incomplete', 'baseline': BASE, 'head': subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode().strip(),
              'test_sha256': hashlib.sha256(Path(TEST).read_bytes()).hexdigest(), 'phases': []}
    try:
        for arm, commit in [('baseline', BASE), ('candidate', result['head'])]:
            engine = scratch / arm
            raw = subprocess.check_output(['git', 'archive', commit, PREFIX + 'attocode_intel'], timeout=30)
            with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
                for item in archive:
                    if item.isfile():
                        relative = Path(item.name.removeprefix(PREFIX))
                        assert not relative.is_absolute() and '..' not in relative.parts
                        target = engine / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(archive.extractfile(item).read())
            result[arm + '_source'] = {p.relative_to(engine).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in sorted(engine.rglob('*')) if p.is_file()}
            xml = out / (arm + '.xml')
            program = '''
import pathlib,sys
sys.path.insert(0,sys.argv[1])
import attocode_intel,pytest
assert pathlib.Path(attocode_intel.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve())
code=pytest.main(['-c','packages/code-intel/pyproject.toml','--confcutdir=packages/code-intel/tests','-o','pythonpath=',sys.argv[2],'-q','-p','eval.quality.no_agent','--junitxml='+sys.argv[3]])
assert all(pathlib.Path(m.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve()) for n,m in sys.modules.items() if n.startswith('attocode_intel') and getattr(m,'__file__',None))
raise SystemExit(code)
'''
            with (out / (arm + '.log')).open('w') as log:
                process = subprocess.run([sys.executable, '-c', program, str(engine), TEST, str(xml)],
                    env=dict(os.environ, PYTHONPATH=str(engine) + os.pathsep + str(Path.cwd())),
                    stdout=log, stderr=subprocess.STDOUT, timeout=120)
            cases = ET.parse(xml).findall('.//testcase')
            failures = [c for c in cases if c.find('failure') is not None]
            row = {'arm': arm, 'exit_code': process.returncode, 'cases': len(cases),
                   'failed': [c.attrib['name'] for c in failures], 'xml_sha256': hashlib.sha256(xml.read_bytes()).hexdigest()}
            result['phases'].append(row)
            (out / 'result.json').write_text(json.dumps(result, indent=2)+'\n')
            assert len(cases) == 7 and not any(c.find('error') is not None or c.find('skipped') is not None for c in cases)
            if arm == 'baseline':
                assert process.returncode == 1
                expected = {f'test_equal_score_pages_ignore_definition_insertion_order[{limit}]' for limit in [1,5,30,50]}
                assert expected <= set(row['failed'])
                assert all('depends on insertion order' in c.find('failure').attrib['message'] or
                           'symbol page changed across persisted restore/hash seeds' in c.find('failure').attrib['message']
                           for c in failures)
            else:
                assert process.returncode == 0 and not failures
        result['status'] = 'passed'
    finally:
        shutil.rmtree(scratch)
        result['cleanup_verified'] = not scratch.exists()
        (out / 'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'status': result['status'], 'cleanup_verified': result['cleanup_verified']}))


if __name__ == '__main__':
    main()
