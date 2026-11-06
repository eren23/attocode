"""Compact metadata need not serialize a complete ranking index twice."""
import json
from copy import deepcopy

import pytest
from attocode_intel import output


def page():
    index = {'status': 'ready', 'body_index_available': True, 'body_index_ready': True,
             'body_index_coverage': .99, 'discovery_truncated': False, 'vector_status': 'idle',
             'vector_coverage': 0., 'keyword_indexed_files': 9000, 'body_indexed_files': 8910,
             'discovery_selected_files': 9000, 'discovery_discovered_files': 9000,
             'discovery_max_files': 50000, 'warmup_reused_asts': 8000, 'warmup_stage': 'ready',
             'warmup_seconds': 12.123, 'keyword_seconds': 7.123, 'body_seconds': 5.0,
             'importance_seconds': .001, 'keyword_index_ready': True}
    ranking = {'method': 'source_aware_deterministic', 'provider': 'off', 'index': index,
               'candidate_pool_count': 1, 'returned_count': 1, 'delivered_count': 1}
    metadata = {'workspace': '/repo', 'source': 'local', 'revision': 'working-tree',
                'freshness': 'working_tree', 'truncated': False, 'ranking': deepcopy(ranking)}
    data = {'query': 'quota', 'ranking': ranking, 'results': [
        {'file_path': 'a.py', 'name': 'quota', 'chunk_type': 'function', 'score': .5,
         'line': 1, 'end_line': 2, 'snippet': 'def quota():\n    return 3\n',
         'snippet_start_line': 1, 'snippet_end_line': 2, 'snippet_truncated': False,
         'matched_terms': ['quota'], 'match_fields': ['source_body']}]}
    return metadata, data


def legacy(monkeypatch, metadata, data, budget):
    with monkeypatch.context() as patch:
        if hasattr(output, '_compact_search_ranking'):
            patch.setattr(output, '_compact_search_ranking', lambda result, _budget: result)
        return output.bounded_search(metadata, data, budget, all_results=data['results'])


def test_duplicate_index_summary_keeps_entire_data(monkeypatch):
    metadata, data = page()
    before = legacy(monkeypatch, metadata, data, 8000)
    result = output.bounded_search(metadata, data, 8000, all_results=data['results'])
    old, new = (json.loads(r.content[0].text) for r in (before, result))
    assert new['data'] == old['data'] == data
    summary = new['metadata']['ranking']['index']
    assert summary['details_in'] == 'data.ranking.index'
    assert all(summary[k] == data['ranking']['index'][k] for k in (
        'status', 'body_index_available', 'body_index_ready', 'body_index_coverage',
        'discovery_truncated', 'vector_status', 'vector_coverage'))
    assert {k:v for k,v in new['metadata']['ranking'].items() if k != 'index'} == {
        k:v for k,v in old['metadata']['ranking'].items() if k != 'index'}
    assert output.response_tokens(result) < output.response_tokens(before)


@pytest.mark.parametrize('budget', [800, 1200, 2000, 8000])
def test_budget_and_full_data_floor_are_identical(monkeypatch, budget):
    metadata, data = page()
    before = legacy(monkeypatch, metadata, data, budget)
    result = output.bounded_search(metadata, data, budget, all_results=data['results'])
    old, new = (json.loads(r.content[0].text) for r in (before, result))
    assert new['data'] == old['data']
    assert output.response_tokens(result) <= output.response_tokens(before) <= budget
    assert {k:v for k,v in new['metadata'].items() if k != 'ranking'} == {
        k:v for k,v in old['metadata'].items() if k != 'ranking'}


@pytest.mark.parametrize('kind', ['missing', 'divergent', 'tiny', 'non_mapping'])
def test_unrelated_or_nonbeneficial_alias_is_byte_identical(monkeypatch, kind):
    metadata, data = page()
    if kind == 'missing':
        metadata.pop('ranking')
    elif kind == 'divergent':
        metadata['ranking']['method'] = 'different stage'
    elif kind == 'tiny':
        metadata['ranking']['index'] = data['ranking']['index'] = {'status': 'ready'}
    else:
        metadata['ranking']['index'] = data['ranking']['index'] = 'ready'
    expected = legacy(monkeypatch, metadata, data, 8000)
    actual = output.bounded_search(metadata, data, 8000, all_results=data['results'])
    assert actual.model_dump() == expected.model_dump()


def test_input_objects_are_not_mutated():
    metadata, data = page()
    saved = deepcopy((metadata,data))
    output.bounded_search(metadata,data,8000,all_results=data['results'])
    assert (metadata,data) == saved


@pytest.mark.asyncio
async def test_real_gateway_preserves_payload_and_readiness(monkeypatch, tmp_path):
    from attocode_intel.gateway import OperationGateway

    from eval.quality.corpus import ready_search

    (tmp_path/'quota.py').write_text('def quota():\n    return "quota limit"\n')
    gateway=OperationGateway(str(tmp_path),profile='daily',watch=False)
    args={'query':'quota limit','top_k':10,'max_tokens':2000}
    try:
        await ready_search(gateway, {'query':'neutral readiness','top_k':1,'max_tokens':2000})
        with monkeypatch.context() as patch:
            if hasattr(output,'_compact_search_ranking'):
                patch.setattr(output,'_compact_search_ranking',lambda result,_budget:result)
            old=await gateway.execute_mcp('semantic_search',args)
        new=await gateway.execute_mcp('semantic_search',args)
        a,b=(json.loads(r.content[0].text) for r in (old,new))
        assert a['data']==b['data']
        assert b['metadata']['ranking']['index']['details_in']=='data.ranking.index'
        assert b['metadata']['ranking']['index']['status']==b['data']['ranking']['index']['status']
        assert output.response_tokens(new)<output.response_tokens(old)<=2000
    finally:
        await gateway.close()
