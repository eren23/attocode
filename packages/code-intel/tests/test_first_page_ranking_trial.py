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


@pytest.mark.parametrize('change', ['valid', 'identity', 'cleanup', 'scratch', 'deadline',
                                   'diagnostic', 'eligibility_type', 'supervision', 'truncated'])
def test_only_final_outer_admission_authorizes_eligibility(change):
    outer = {'status': 'complete', 'cleanup_verified': True, 'owned_scratch_removed': True,
             'seconds': 10., 'limits': {'seconds': 900},
             'supervision': {'status': 'passed', 'exit_code': 0, 'cleanup_verified': True,
                             'log_truncated': False}}
    diagnostic = {'status': 'complete', 'eligibility': True}
    if change == 'identity':
        outer['status'] = 'incomplete'
    elif change == 'cleanup':
        outer['cleanup_verified'] = False
    elif change == 'scratch':
        outer['owned_scratch_removed'] = False
    elif change == 'deadline':
        outer['seconds'] = 901.
    elif change == 'diagnostic':
        diagnostic['status'] = 'incomplete'
    elif change == 'eligibility_type':
        diagnostic['eligibility'] = 'true'
    elif change == 'supervision':
        outer['supervision']['status'] = 'failed'
    elif change == 'truncated':
        outer['supervision']['log_truncated'] = True
    result = decision().admit_diagnostic(outer, diagnostic)
    assert result == ('eligible_for_fixed_candidate' if change == 'valid' else None)


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


def test_operator_registration_is_synchronous_and_source_bound():
    from eval.quality.experiments import load_operator
    assert importlib.util.find_spec('eval.quality.first_page_ranking_trial') is not None
    operator = load_operator('first-page-ranking')
    assert operator.__name__ == 'run' and not inspect.iscoroutinefunction(operator)


def test_owner_replay_distinguishes_definitions_from_repeated_rows():
    hit = {'file': 'a.py', 'kind': 'function', 'name': 'parse', 'start': 0, 'end': 0,
           'definition_start': 1, 'definition_end': 3}
    other = {**hit, 'definition_start': 5, 'definition_end': 7}
    generation = [{'stage': 'keyword', 'results': [hit, deepcopy(hit), other]},
                  {'stage': 'body', 'results': [{**hit, 'name': 'answer', 'start': 10, 'end': 12}]}]
    owners = decision().owner_credit(generation, 20, 1.15)
    assert owners['a.py|function|parse']['keyword_votes'] == 2
    assert owners['a.py|function|parse']['score'] == round(1/21 + 1/23, 6)
    assert owners['a.py|function|answer']['score'] == round(1.15/21, 6)


@pytest.mark.parametrize('change,expected', [('valid', True), ('missing_fact', False),
                                           ('wrong_file', False), ('wrong_lines', False),
                                           ('truncated_last_line', False), ('multiline_valid', True),
                                           ('multiline_gap', False)])
def test_complete_answer_requires_every_visible_source_fact(change, expected):
    question = {'answers': [{'file': 'a.py', 'proofs': [{'line': 3, 'quote': 'if ready:'},
                                                     {'line': 4, 'quote': 'return data'}]}]}
    row = {'file_path': 'a.py', 'snippet': 'if ready:\n    return data',
           'snippet_start_line': 3, 'snippet_end_line': 4}
    if change == 'missing_fact':
        row['snippet'] = 'if ready:'
    elif change == 'wrong_file':
        row['file_path'] = 'b.py'
    elif change == 'wrong_lines':
        row['snippet_start_line'], row['snippet_end_line'] = 30, 31
    elif change == 'truncated_last_line':
        row['snippet'] = 'if ready: return data\n    ret'
    elif change in {'multiline_valid', 'multiline_gap'}:
        question['answers'][0]['proofs'] = [{'line': 3, 'quote': 'if ready:\n    return data'}]
        if change == 'multiline_gap':
            row.update(snippet='if ready:\n    other()\n    return data', snippet_end_line=5)
    result = decision().page_metrics(question, [row])
    assert result['answer'] is expected


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


@pytest.mark.asyncio
async def test_supervised_worker_records_and_admits_synthetic_source(tmp_path, monkeypatch):
    import hashlib
    import json
    from pathlib import Path
    import attocode_intel
    from eval.quality import runner
    from eval.quality.first_page_ranking_trial import worker
    source = tmp_path / 'work/source'
    source.mkdir(parents=True)
    body = 'def quota():\n    return "quota capacity"\n'
    (source / 'a.py').write_text(body)
    (tmp_path / 'evidence/synthetic').mkdir(parents=True)
    control = tmp_path / 'operator/eval/quality'
    control.mkdir(parents=True)
    question = {'category': 'short', 'split': 'development', 'query': 'quota capacity',
                'answers': [{'file': 'a.py', 'definition_start': 1, 'definition_end': 2,
                             'source_sha256': hashlib.sha256(body.encode()).hexdigest(),
                             'proofs': [{'line': 2, 'quote': 'return "quota capacity"'}]}]}
    manifest = {'repositories': [{'pack': 'synthetic', 'questions': [
        {**question, 'id': f'synthetic-{n}'} for n in range(4)]}]}
    manifest['repositories'][0]['questions'][0] = {
        **question, 'id': 'synthetic-0', 'answers': [{**question['answers'][0], 'proofs': [
            {'line': 1, 'quote': 'def quota():\n    return "quota capacity"'}]}]}
    (control / 'first_page_ranking_questions.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(runner, 'REPO', tmp_path / 'operator')
    monkeypatch.setenv('ATTOCODE_EXPERIMENT_ENGINE', str(Path(attocode_intel.__file__).parent))
    await worker(tmp_path, 'synthetic')
    report = json.loads((tmp_path / 'evidence/synthetic/worker.json').read_text())
    assert report['status'] == 'complete' and report['source_unchanged']
    assert len(report['cases']) == 4
    assert all(c['owner_score_replay'] for c in report['cases'])
