"""Restart evidence and frozen timing gates, exercised only on CI."""
import hashlib
import json

import pytest
from mcp.types import CallToolResult, TextContent

from eval.quality import restart_experiment as trial
from eval.quality.experiment_evidence import Journal


@pytest.mark.parametrize('close_fails', [False, True])
async def test_failed_phase_retains_success_and_failing_response_before_validation(tmp_path, monkeypatch, close_fails):
    from attocode_intel import gateway

    class Peer:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        async def execute(self, operation, arguments):
            if operation == 'search_symbols' and arguments == {'name': '__quality_initialize__'}:
                return CallToolResult(content=[TextContent(type='text', text='initialize')])
            if operation == 'capabilities':
                return CallToolResult(content=[TextContent(type='text', text='ready')], structuredContent={
                    'capabilities': {'coverage': {'phase': 'ready', 'total_files': 1,
                    'parsed_files': 1, 'reference_indexed_files': 1, 'discovery_truncated': False}}})
            self.calls += 1
            if self.calls == 1:
                return CallToolResult(content=[TextContent(type='text', text='definition')],
                    structuredContent={'data': [{'file_path': 'sample.go', 'start_line': 1, 'name': 'target'}]})
            return CallToolResult(isError=True, content=[TextContent(type='text', text='preserve failure')])

        async def close(self):
            if close_fails:
                raise RuntimeError('close failed too')

    monkeypatch.setattr(gateway, 'OperationGateway', Peer)
    spec = {'symbol': 'target', 'file': 'sample.go', 'definition_line': 1, 'anchor': 'func target('}
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    journal = Journal(evidence / 'journal', 128 * 1024)
    with pytest.raises(RuntimeError if close_fails else ValueError):
        await trial.navigate(tmp_path, spec, evidence, journal)
    report = json.loads((evidence / 'phase.json').read_bytes())
    events = [json.loads(line) for line in (evidence / 'journal/events.jsonl').read_text().splitlines()]
    responses = [json.loads((evidence / 'journal' / e['response']['path']).read_bytes())
                 for e in events if e['request']['event'] == 'operation']
    assert report['status'] == 'incomplete' and report['operations'][0]['label'] == 'definition'
    assert len(responses) == 2 and responses[1]['isError'] is True
    assert responses[1]['content'][0]['text'] == 'preserve failure'
    assert report.get('close_failure') == ('RuntimeError' if close_fails else None)


def test_canonical_evidence_preserves_symbol_and_retrieval_result_order():
    ordered = [{'name': 'b'}, {'name': 'a'}]
    assert trial.canonical('search_symbols', ordered) == ordered
    first = trial.canonical('semantic_search', {'results': ordered, 'ranking': {'index': 'cold'}})
    second = trial.canonical('semantic_search', {'results': list(reversed(ordered)), 'ranking': {'index': 'warm'}})
    assert first != second


@pytest.mark.parametrize('operation,data,expected', [
    ('inspect_symbol', {'status': 'found', 'total_reference_candidates': 70},
     {'status': 'found', 'total_reference_candidates': 70}),
    ('dependencies', {'path': 'source.py', 'total_imports': 3}, {'path': 'source.py', 'total_imports': 3}),
    ('semantic_search', {'results': [], 'ranking': {'method': 'keyword', 'index': {'status': 'warming'}}},
     {'results': [], 'ranking': {'method': 'keyword'}}),
])
def test_canonical_retains_visible_counts_and_ranking_evidence(operation, data, expected):
    assert trial.canonical(operation, data) == expected


def records(*, cold=105, restart=30):
    return [{'arm': arm, 'number': number, 'phases': {
        phase: {'seconds': value, 'evidence_sha256': 'a' * 64} for phase, value in
        [('cold', 100 if arm == 'baseline' else cold), ('restart', 40 if arm == 'baseline' else restart)]}}
        for arm, number in [('baseline', 0), ('candidate', 0), ('candidate', 1), ('baseline', 1), ('baseline', 2), ('candidate', 2)]]


@pytest.mark.parametrize('cold,restart,expected', [(105, 30, 'retain'), (105.01, 30, 'reject'), (105, 30.01, 'reject')])
def test_restart_and_cold_median_thresholds_both_apply(cold, restart, expected):
    result = trial.decide(records(cold=cold, restart=restart), 'a' * 64)
    assert result['status'] == 'complete' and result['decision'] == expected


@pytest.mark.parametrize('damage', ['missing', 'order', 'canonical'])
def test_incomplete_or_different_phase_evidence_never_earns_performance_verdict(damage):
    rows = records()
    if damage == 'missing':
        rows.pop()
    elif damage == 'order':
        rows[0], rows[1] = rows[1], rows[0]
    else:
        rows[0]['phases']['restart']['evidence_sha256'] = 'b' * 64
    result = trial.decide(rows, 'a' * 64)
    assert result['status'] == 'incomplete' and result['decision'] is None


def phase_capture(tmp_path):
    evidence = tmp_path / 'evidence'
    journal = Journal(evidence / 'journal', 128 * 1024)
    spec = {'symbol': 'target', 'file': 'sample.go', 'definition_line': 1, 'anchor': 'func target('}
    (tmp_path / 'sample.go').write_text('func target() {}\n')
    initialized = CallToolResult(content=[TextContent(type='text', text='initialize')]).model_dump(mode='json')
    journal.response({'event': 'readiness_initialize', 'operation': 'search_symbols',
                      'arguments': {'name': '__quality_initialize__'}}, initialized)
    ready = CallToolResult(content=[TextContent(type='text', text='ready')], structuredContent={
        'capabilities': {'coverage': {'phase': 'ready', 'total_files': 1, 'parsed_files': 1,
                         'reference_indexed_files': 1, 'discovery_truncated': False}}}).model_dump(mode='json')
    ready_ref = journal.response({'event': 'readiness_poll', 'operation': 'capabilities', 'arguments': {}}, ready)
    rows = []
    for label, operation, arguments in trial.navigation_requests(spec):
        if operation == 'search_symbols':
            data = [{'name': 'target', 'file_path': 'sample.go', 'start_line': 1}]
        elif operation == 'inspect_symbol':
            data = {'status': 'found', 'definition': {'name': 'target', 'file_path': 'sample.go', 'start_line': 1},
                    'source': {'text': 'func target() {}', 'start_line': 1, 'end_line': 1}}
        elif operation == 'semantic_search':
            data = {'results': [{'file_path': 'sample.go'}]}
        else:
            data = {}
        raw = CallToolResult(content=[TextContent(type='text', text='raw')], structuredContent={'data': data}).model_dump(mode='json')
        ref = journal.response({'event': 'operation', 'label': label, 'operation': operation, 'arguments': arguments}, raw)
        rows.append({'label': label, 'operation': operation, 'arguments': arguments, 'response_ref': ref,
                     'canonical_sha256': trial.digest(trial.canonical(operation, data))})
    journal.response({'event': 'gateway_close'}, {'status': 'complete'})
    summary = {'status': 'complete', 'operations': rows,
               'readiness': {'polls': 1, 'seconds': .25, 'poll_interval_seconds': 1.0, 'response_ref': ready_ref},
               'evidence_sha256': trial.digest({r['label']: r['canonical_sha256'] for r in rows})}
    return evidence, spec, summary


def test_phase_summary_replays_from_valid_bound_raw_responses(tmp_path):
    evidence, spec, summary = phase_capture(tmp_path)
    assert trial.admit_phase(evidence, tmp_path, spec, summary) == summary['evidence_sha256']


@pytest.mark.parametrize('damage', ['missing', 'corrupt', 'binding', 'summary'])
def test_phase_admission_rejects_damaged_or_rebound_raw_capture(tmp_path, damage):
    evidence, spec, summary = phase_capture(tmp_path)
    rows = summary['operations']
    ref = rows[0]['response_ref']
    blob = evidence / 'journal' / ref['path']
    if damage == 'missing':
        blob.unlink()
    elif damage == 'corrupt':
        blob.write_bytes(blob.read_bytes() + b' ')
    elif damage == 'binding':
        rows[0]['arguments']['name'] = 'a different name'
    else:
        rows[0]['canonical_sha256'] = hashlib.sha256(b'changed summary').hexdigest()
    with pytest.raises((ValueError, FileNotFoundError)):
        trial.admit_phase(evidence, tmp_path, spec, summary)


@pytest.mark.parametrize('damage', ['missing_initialize', 'missing_poll', 'partial_reference_counts', 'late_poll'])
def test_navigation_capture_requires_prior_complete_reference_readiness(tmp_path, damage):
    evidence, spec, summary = phase_capture(tmp_path)
    path = evidence / 'journal/events.jsonl'
    events = [json.loads(line) for line in path.read_text().splitlines()]
    if damage == 'missing_initialize':
        events = [e for e in events if e['request']['event'] != 'readiness_initialize']
    elif damage == 'missing_poll':
        events = [e for e in events if e['request']['event'] != 'readiness_poll']
    elif damage == 'late_poll':
        index = next(i for i,e in enumerate(events) if e['request']['event'] == 'readiness_poll')
        events.append(events.pop(index))
    else:
        event = next(e for e in events if e['request']['event'] == 'readiness_poll')
        blob = evidence / 'journal' / event['response']['path']
        value = json.loads(blob.read_bytes())
        value['structuredContent']['capabilities']['coverage']['reference_indexed_files'] = 0
        raw = (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
        sha = hashlib.sha256(raw).hexdigest()
        blob = evidence / 'journal/blobs' / (sha + '.json')
        blob.write_bytes(raw)
        event['response'] = {'path': 'blobs/' + sha + '.json', 'bytes': len(raw), 'sha256': sha}
        summary['readiness']['response_ref'] = event['response']
    path.write_text(''.join(json.dumps(e) + '\n' for e in events))
    with pytest.raises(ValueError):
        trial.admit_phase(evidence, tmp_path, spec, summary)


def test_correct_workspace_routes_compare_by_role_without_mutating_raw_data(tmp_path):
    import copy

    left, right = tmp_path / 'left', tmp_path / 'right'
    a = {'results': [{'file_path': 'source.go', 'score': .5}], 'ranking': {'index': {'status': 'ready'}, 'delivered_count': 1},
         'follow_up': {'tool': 'semantic_search', 'reruns_current_index': True,
                       'arguments': {'workspace': str(left.resolve()), 'query': 'target', 'top_k': 11}}}
    b = copy.deepcopy(a)
    b['follow_up']['arguments']['workspace'] = str(right.resolve())
    original = copy.deepcopy(a)
    assert a != b
    assert trial.canonical('semantic_search', a, workspace=left) == trial.canonical('semantic_search', b, workspace=right)
    assert a == original and a['follow_up']['arguments']['workspace'] == str(left.resolve())


@pytest.mark.parametrize('route', ['other-workspace', None, False, 7])
def test_wrong_or_malformed_workspace_route_cannot_be_normalized(tmp_path, route):
    data = {'results': [], 'follow_up': {'arguments': {'workspace': route}}}
    with pytest.raises(ValueError, match='workspace route'):
        trial.canonical('semantic_search', data, workspace=tmp_path)


def test_workspace_role_comparison_preserves_every_other_visible_field(tmp_path):
    import copy

    original = {'results': [{'file_path': 'a.go', 'score': .5}, {'file_path': 'b.go', 'score': .4}],
                'ranking': {'index': {'status': 'ready'}, 'candidate_pool_count': 2},
                'follow_up': {'tool': 'semantic_search', 'reruns_current_index': True,
                'arguments': {'workspace': str(tmp_path.resolve()), 'query': 'target', 'top_k': 11, 'max_tokens': 16000}}}
    expected = trial.canonical('semantic_search', original, workspace=tmp_path)
    assert expected['follow_up']['arguments']['workspace'] == '__quality_fixture_workspace__'
    for keys, value in [(('follow_up', 'tool'), 'inspect_symbol'),
                        (('follow_up', 'reruns_current_index'), False),
                        (('follow_up', 'arguments', 'query'), 'other'),
                        (('follow_up', 'arguments', 'top_k'), 12),
                        (('ranking', 'candidate_pool_count'), 3)]:
        changed = copy.deepcopy(original)
        target = changed
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = value
        assert trial.canonical('semantic_search', changed, workspace=tmp_path) != expected
    changed = copy.deepcopy(original)
    changed['results'].reverse()
    assert trial.canonical('semantic_search', changed, workspace=tmp_path) != expected
    assert trial.canonical('inspect_symbol', original, workspace=tmp_path) == original
    with pytest.raises(ValueError, match='workspace route'):
        trial.canonical('semantic_search', original)


@pytest.mark.asyncio
async def test_real_fresh_workspace_continuations_validate_exact_routes_before_comparison(tmp_path):
    import asyncio

    from attocode_intel.gateway import OperationGateway

    from eval.quality.readiness import wait_ready

    peers, pages = [], []
    journal = Journal(tmp_path / 'route-capture', 1024 * 1024)
    try:
        for label in ('first', 'second'):
            workspace = tmp_path / label
            workspace.mkdir()
            (workspace / 'sample.py').write_text(''.join(f'def target_{n}():\n    return "target {n}"\n\n' for n in range(12)))
            gateway = OperationGateway(str(workspace), 'daily', watch=False)
            peers.append(gateway)
            await asyncio.wait_for(wait_ready(gateway, journal), timeout=20)

            async def capture(peer=gateway):
                while True:
                    args = {'query': 'target', 'file_filter': 'sample.py', 'top_k': 1, 'max_tokens': 8000}
                    response = await peer.execute('semantic_search', args)
                    journal.response({'event': 'routing_control', 'arguments': args}, response.model_dump(mode='json'))
                    assert not response.isError
                    data = response.structuredContent['data']
                    if data.get('ranking', {}).get('index', {}).get('status') != 'warming':
                        return data
                    await asyncio.sleep(.1)

            data = await asyncio.wait_for(capture(), timeout=20)
            assert data['follow_up']['arguments']['workspace'] == str(workspace.resolve())
            pages.append(trial.canonical('semantic_search', data, workspace=workspace))
        assert pages[0] == pages[1]
    finally:
        for gateway in peers:
            await gateway.close()
