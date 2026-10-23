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
