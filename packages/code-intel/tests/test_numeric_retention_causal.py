"""Prospective numeric-admission assertions; run only in online proof workers."""
import hashlib
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from attocode_intel.gateway import OperationGateway

from eval.quality.corpus import ready_search
from eval.quality.corpus_capture import RecordedGateway
from eval.quality.experiment_evidence import Journal, assert_engine
from eval.quality.mcp_search import engine_identity, observe


@asynccontextmanager
async def fixture_gateway(tmp_path):
    root = tmp_path/'source'
    root.mkdir()
    raw = {
        'amber.py':b'def amber_control():\n    """Synthetic response control."""\n    return 613\n',
        'violet.py':b'def violet_control():\n    """Synthetic response control."""\n    return 617\n',
    }
    for path,content in raw.items():
        (root/path).write_bytes(content)
    journal = Journal(tmp_path/'journal',4*2**20)
    gateway = RecordedGateway(OperationGateway(str(root),'daily',watch=False),root,journal)
    try:
        await ready_search(gateway,{'query':'numeric_causal_readiness_sentinel','top_k':1,'max_tokens':2000},timeout=30)
        yield root,raw,gateway,journal
    finally:
        await gateway.close()
        assert all((root/path).read_bytes()==content for path,content in raw.items())


def stage_terms(page):
    rows = page['generation_diagnostic']
    assert [r['stage'] for r in rows]==['keyword','body','file_bm25']
    return {r['stage']:(r['arguments'][0].split() if isinstance(r['arguments'][0],str) else r['arguments'][0]) for r in rows}


@pytest.mark.parametrize('query,numbers',[
    ('control 613 response',{'613'}),
    ('control (613) response',{'613'}),
    ('control 613 613 response',{'613'}),
    ('control 613 617 response',{'613','617'}),
],ids=['plain','punctuation','duplicates','two-numbers'])
@pytest.mark.asyncio
async def test_mixed_query_retains_indexed_numeric_terms(tmp_path,query,numbers,record_property):
    import attocode_intel

    selected = Path(os.environ.get('ATTOCODE_EXPERIMENT_ENGINE',str(Path(attocode_intel.__file__).parent)))
    origins = assert_engine(selected)
    async with fixture_gateway(tmp_path) as (root,raw,gateway,journal):
        for number in sorted(numbers):
            page = await observe(gateway,number,top_k=10,budget=2000,capture_generation=True)
            assert all(number in terms for terms in stage_terms(page).values())
            body = next(r for r in page['generation_diagnostic'] if r['stage']=='body')
            expected_file = 'amber.py' if number=='613' else 'violet.py'
            assert any(r['file']==expected_file for r in body['results'])
        page = await observe(gateway,query,top_k=10,budget=2000,capture_generation=True)
        assert page['request']['query']==query
        actual = stage_terms(page)
        assert all({'control','response'}<=set(t) for t in actual.values())
        assert all((root/path).read_bytes()==content for path,content in raw.items())
        record_property('qualified_input','true')
        record_property('selected_engine_sha256',engine_identity())
        record_property('origins',json.dumps(origins,sort_keys=True))
        record_property('source_sha256',json.dumps({k:hashlib.sha256(v).hexdigest() for k,v in raw.items()},sort_keys=True))
        record_property('observed_stage_terms',json.dumps(actual,sort_keys=True))
        assert all(numbers<=set(t) for t in actual.values()), 'REGRESSION: mixed query discarded indexed numeric token'


@pytest.mark.parametrize('query,expected',[
    ('613 613',['613','613']),
    ('control 6 response',['control','response']),
    ('control v613 response',['control','response','v613']),
    ('control response',['control','response']),
],ids=['all-numeric','single-digit','alphanumeric','nonnumeric'])
@pytest.mark.asyncio
async def test_existing_admission_controls(tmp_path,query,expected):
    async with fixture_gateway(tmp_path) as (_root,_raw,gateway,_journal):
        page = await observe(gateway,query,top_k=10,budget=2000,capture_generation=True)
        assert page['request']['query']==query
        assert all(terms==expected for terms in stage_terms(page).values())
