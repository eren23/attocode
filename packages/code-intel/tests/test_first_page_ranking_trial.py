"""Prospective admission controls; synthetic data never consumes corpus questions."""
from copy import deepcopy
import importlib
import importlib.util
import inspect

import pytest


def decision():
    name = 'eval.quality.first_page_ranking_decision'
    assert importlib.util.find_spec(name) is not None, 'missing prospective decision implementation'
    return importlib.import_module(name)


def sample():
    design = {'questions': {str(i): {'query': str(i), 'pack': f'p{i % 6}'} for i in range(24)},
              'engines': {'baseline': 'b', 'candidate': 'c'}, 'source_sha256': 'source'}
    rows = []
    for role in ('baseline', 'candidate'):
        for repetition in range(3):
            for i in range(24):
                for page in ('default', 'deep', 'scoped'):
                    hit = role == 'candidate' or i >= 3 or page != 'default'
                    rows.append({'id': str(i), 'query': str(i), 'pack': f'p{i % 6}',
                                 'role': role, 'round': repetition, 'page': page,
                                 'engine': design['engines'][role], 'source_sha256': 'source',
                                 'answer': hit, 'files': [str(i)] if hit else [],
                                 'visible': [str(i)] if hit else [], 'first_rank': 1 if hit else None,
                                 'seconds': .02, 'complete': True})
    return design, rows


def test_complete_stable_gain_promotes():
    design, rows = sample()
    result = decision().evaluate_split(rows, design)
    assert result['complete'] and result['decision'] == 'promote'
    assert result['stable_gains'] == ['0', '1', '2']


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'query', 'source', 'engine', 'round',
                                    'page', 'type', 'complete'])
def test_invalid_or_incomplete_inventory_has_null_decision(change):
    design, rows = sample()
    if change == 'missing':
        rows.pop()
    elif change == 'duplicate':
        rows.append(deepcopy(rows[0]))
    else:
        field, value = {'query': ('query', 'other'), 'source': ('source_sha256', 'other'),
                        'engine': ('engine', 'other'), 'round': ('round', 3),
                        'page': ('page', 'other'), 'type': ('answer', 'false'),
                        'complete': ('complete', False)}[change]
        rows[0][field] = value
    result = decision().evaluate_split(rows, design)
    assert not result['complete'] and result['decision'] is None


@pytest.mark.parametrize('change', ['answer', 'file', 'proof', 'gains', 'repos', 'p95', 'slow', 'unstable'])
def test_any_individual_loss_or_failed_guard_rejects(change):
    design, rows = sample()
    candidate = [r for r in rows if r['role'] == 'candidate']
    target = next(r for r in candidate if r['id'] == '5' and r['page'] == 'default')
    if change in {'answer', 'file', 'proof'}:
        target[{'answer': 'answer', 'file': 'files', 'proof': 'visible'}[change]] = False if change == 'answer' else []
    elif change == 'gains':
        for r in candidate:
            if r['id'] == '2' and r['page'] == 'default':
                r.update(answer=False, files=[], visible=[], first_rank=None)
    elif change == 'repos':
        for q in design['questions'].values():
            q['pack'] = 'one'
        for r in rows:
            r['pack'] = 'one'
    elif change == 'p95':
        for r in candidate:
            r['seconds'] = .30
    elif change == 'slow':
        target['seconds'] = 2.01
    else:
        next(r for r in candidate if r['id'] == '2' and r['page'] == 'default')['answer'] = False
    result = decision().evaluate_split(rows, design)
    assert result['complete'] and result['decision'] == 'reject'


def test_recording_option_is_explicit_and_disabled_by_default():
    from eval.quality.mcp_search import observe
    assert 'capture_owner_fusion' in inspect.signature(observe).parameters
    assert inspect.signature(observe).parameters['capture_owner_fusion'].default is False


@pytest.mark.asyncio
async def test_fusion_capture_preserves_delivery_and_restores_patches(tmp_path):
    from eval.quality.mcp_search import observe
    from attocode_intel.gateway import OperationGateway
    from attocode_intel._internal.integrations.context import semantic_search as module
    assert 'capture_owner_fusion' in inspect.signature(observe).parameters
    (tmp_path / 'sample.py').write_text('def quota():\n    return "quota capacity"\n')
    gateway = OperationGateway(str(tmp_path), profile='daily', watch=False)
    original = module.rerank_broad_candidates
    try:
        from eval.quality.corpus import ready_search
        await ready_search(gateway, {'query': 'neutral readiness', 'top_k': 1, 'max_tokens': 2000})
        ordinary = await observe(gateway, 'quota capacity', top_k=10, budget=2000)
        traced = await observe(gateway, 'quota capacity', top_k=10, budget=2000,
                               capture_generation=True, capture_owner_fusion=True)
        assert ordinary['response']['data']['results'] == traced['response']['data']['results']
        assert traced['owner_fusion_diagnostic']
        assert module.rerank_broad_candidates is original
    finally:
        await gateway.close()
    class Broken:
        async def execute_mcp(self, *_args):
            raise RuntimeError('synthetic interruption')
    with pytest.raises(RuntimeError, match='synthetic interruption'):
        await observe(Broken(), 'quota', top_k=10, budget=2000, capture_owner_fusion=True)
    assert module.rerank_broad_candidates is original
