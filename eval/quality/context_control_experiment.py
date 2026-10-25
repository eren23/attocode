"""Temporary causal controls: expected feature absence is retained as successful data."""
from __future__ import annotations
import json, subprocess, sys, xml.etree.ElementTree as ET
from pathlib import Path
from eval.quality.runner import REPO, write_json


def run(root):
    design = json.loads((REPO / 'eval/quality/experiments/context_control.json').read_bytes())
    xml = root / 'evidence/context-controls.xml'
    result = subprocess.run([sys.executable, '-m', 'pytest', '-c', 'packages/code-intel/pyproject.toml',
        '--confcutdir=packages/code-intel/tests', 'packages/code-intel/tests/test_context_search.py',
        '-p', 'eval.quality.experiment_origin', '-q', '--basetemp='+str(root/'work/pytest'),
        '-o', 'cache_dir='+str(root/'work/cache'), '--junitxml='+str(xml)], cwd=REPO)
    tree=ET.fromstring(xml.read_bytes());cases=list(tree.iter('testcase'))
    assert cases and not list(tree.iter('error'))
    failures=[c for c in cases if c.find('failure') is not None]
    if design['expected']=='feature_absent':
        assert result.returncode==1 and len(cases)==20 and len(failures)==19
        assert {c.attrib['name'] for c in cases if c.find('failure') is None}=={'test_ordinary_search_needs_no_structural_initialization'}
        for c in failures:
            text=''.join(c.find('failure').itertext())
            assert any(t in text for t in ('context_file', 'allowed_paths')), (c.attrib,text)
    else:
        assert design['expected']=='all_pass' and result.returncode==0 and not failures and len(cases)==20
    write_json(root/'evidence/context-control-verdict.json', {'expected':design['expected'], 'cases':len(cases), 'failed':len(failures), 'exit_code':result.returncode})
