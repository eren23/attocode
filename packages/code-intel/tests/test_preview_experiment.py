"""Hand-selected synthetic wins/losses exercise the frozen scientific gates."""
import json
from pathlib import Path

import pytest

from eval.quality.preview_experiment import decide

DESIGN = Path(__file__).resolve().parents[1] / 'evals/designs/2026-10-23-preview-windows.json'


def reports(winners=('d-p1', 'd-r1', 'v-p1', 'v-r1'), *, candidate_ms=10):
    frozen = json.loads(DESIGN.read_bytes())
    found = []
    for pack in frozen['packs']:
        pages = []
        for round_number, arms in enumerate(frozen['rounds']):
            for arm in arms:
                for q in pack['questions']:
                    requests = [(5, 2000, ''), (5, 8000, ''), (24, 2000, ''), (24, 8000, ''), (5, 2000, q['file'])]
                    for depth, budget, scope in requests:
                        visible = q['kind'] == 'exact' or (arm == 'candidate' and q['id'] in winners)
                        pages.append({'round': round_number, 'arm': arm, 'question': q['id'],
                            'kind': q['kind'], 'split': q['split'],
                            'arguments': {'query': q['query'], 'top_k': depth, 'max_tokens': budget, 'file_filter': scope},
                            'judgment': {'file': q['kind'] != 'unrelated', 'visible': visible},
                            'identity': [] if q['kind'] == 'unrelated' else [{'file_path': q['file'], 'line': 1}],
                            'data_sha256': '0' * 64, 'milliseconds': candidate_ms if arm == 'candidate' else 10})
        found.append({'status': 'complete', 'pack': pack['id'], 'pages': pages})
    assert sum(len(r['pages']) for r in found) == 720
    return frozen, found


def test_both_splits_need_two_distinct_gains_and_one_from_each_repository():
    frozen, rows = reports()
    result = decide(rows, frozen)
    assert result['status'] == 'complete' and result['decision'] == 'retain'
    assert result['gain_gate'] is True


@pytest.mark.parametrize('winners', [
    ('d-p1', 'd-r1', 'v-p1'),
    ('d-p1', 'd-r1', 'v-p1', 'v-p2'),
])
def test_repeated_pages_or_same_repository_cannot_replace_validation_gains(winners):
    frozen, rows = reports(winners)
    result = decide(rows, frozen)
    assert result['decision'] == 'reject' and result['gain_gate'] is False


@pytest.mark.parametrize('failure', ['excerpt_loss', 'file_loss', 'identity_loss', 'control_change'])
def test_one_individual_scoped_or_deep_loss_cannot_be_hidden_by_aggregate_gains(failure):
    frozen, rows = reports()
    qid = 'd-p5' if failure == 'control_change' else 'd-p4'
    selected = [p for p in rows[0]['pages'] if p['question'] == qid and p['round'] == 0
                and p['arguments']['top_k'] == 5 and p['arguments']['file_filter']]
    assert len(selected) == 2
    old, new = selected
    if failure == 'excerpt_loss':
        old['judgment']['visible'], new['judgment']['visible'] = True, False
    elif failure == 'file_loss':
        old['judgment']['file'], new['judgment']['file'] = True, False
    elif failure == 'identity_loss':
        new['identity'] = []
    else:
        new['data_sha256'] = '1' * 64
    assert decide(rows, frozen)['decision'] == 'reject'


@pytest.mark.parametrize('broken', ['missing_page', 'duplicate_page', 'query_binding', 'missing_pack'])
def test_missing_or_misbound_capture_is_incomplete_without_quality_verdict(broken):
    frozen, rows = reports()
    if broken == 'missing_page':
        rows[0]['pages'].pop()
    elif broken == 'duplicate_page':
        rows[0]['pages'].append(rows[0]['pages'][0])
    elif broken == 'query_binding':
        rows[0]['pages'][0]['arguments']['query'] = 'a different query'
    else:
        rows.pop()
    result = decide(rows, frozen)
    assert result['status'] == 'incomplete' and result['decision'] is None


@pytest.mark.parametrize('milliseconds,decision', [(100, 'retain'), (100.1, 'reject')])
def test_warm_latency_gate_has_the_frozen_hundred_millisecond_floor(milliseconds, decision):
    frozen, rows = reports(candidate_ms=milliseconds)
    result = decide(rows, frozen)
    assert result['decision'] == decision


async def test_malformed_actual_mcp_shape_is_durable_before_json_rejection(tmp_path):
    from mcp import types

    from eval.quality.experiment_evidence import Journal
    from eval.quality.preview_experiment import request_page
    from eval.quality.preview_sources import SourceTracker

    class ExternalGateway:
        async def execute_mcp(self, name, arguments):
            assert name == 'semantic_search' and arguments == {'query': 'alpha', 'top_k': 5, 'max_tokens': 2000}
            return types.CallToolResult(content=[types.TextContent(type='text', text='{broken')])
    journal = Journal(tmp_path / 'evidence', 64 * 1024)
    tracker = SourceTracker(tmp_path, journal)
    with pytest.raises(json.JSONDecodeError):
        await request_page(ExternalGateway(), tracker, journal, {'query': 'alpha', 'top_k': 5, 'max_tokens': 2000})
    events = [json.loads(line) for line in (tmp_path / 'evidence/events.jsonl').read_text().splitlines()]
    response = next(e for e in events if e['request'].get('event') == 'mcp_response')
    raw = json.loads((tmp_path / 'evidence' / response['response']['path']).read_bytes())
    assert raw['content'][0]['text'] == '{broken' and raw['isError'] is False
