"""Protect actual-page scoring and the frozen candidate's no-regression gate."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from eval.quality.search_usefulness import (
    _BASE_DIVERSITY,
    candidate_diversity,
    decide,
    observed_anchors,
    summarize,
)


def observations():
    rows = []
    for i in range(12):
        arms = {}
        for arm in ('baseline', 'candidate'):
            files = ['first', 'second'] if arm == 'candidate' or i >= 2 else ['first', 'noise']
            arms[arm] = {k: {'results': [{'file': f} for f in files], 'anchor_ranges': [0],
                            'seconds': .01, 'stages': {'fused': ['first', 'second']}}
                         for k in ('5', '24', 'scoped')}
            arms[arm]['scoped']['results'] = [{'file': 'first'}]
        rows.append({'id': str(i), 'pack': str(i % 4), 'category': 'tests' if i < 8 else 'configuration',
                     'labels': ['first', 'second'], 'arms': arms})
    return rows


def test_score_uses_five_delivered_slots_without_deduplicating_a_larger_page():
    row = observations()[0]
    row['arms']['baseline']['5']['results'] = [{'file': 'first'}] * 5
    row['arms']['baseline']['24']['results'] = [{'file': 'first'}] * 5 + [{'file': 'second'}]
    result = summarize([row], 'baseline')
    assert result['pairs5'] == 1
    assert result['all5'] == 0
    assert result['pairs24'] == 2
    assert result['all24'] == 1


def test_anchor_range_requires_same_file_and_real_source_lines():
    evidence = [{'file': 'a', 'line': 10}, {'file': 'b', 'line': 10}]
    assert observed_anchors([{'file': 'a', 'start_line': 10, 'end_line': 20}], evidence) == [0]
    assert observed_anchors([{'file': 'a', 'start_line': 0, 'end_line': 20}], evidence) == []


def test_gain_requires_multiple_repositories():
    rows = observations()
    assert decide(rows, [str(i) for i in range(12)])['passed']
    rows[1]['pack'] = rows[0]['pack']
    assert not decide(rows, [str(i) for i in range(12)])['passed']


@pytest.mark.parametrize('failure', ['label5', 'label24', 'anchor5', 'anchor24',
                                     'generation', 'production', 'scoped', 'latency'])
def test_gate_rejects_each_individual_regression(failure):
    rows = observations()
    arm = rows[3]['arms']['candidate']
    if failure.startswith('label'):
        arm[failure[5:]]['results'] = [{'file': 'first'}]
    elif failure.startswith('anchor'):
        arm[failure[6:]]['anchor_ranges'] = []
    elif failure == 'generation':
        arm['5']['stages'] = {'fused': ['changed']}
    elif failure == 'production':
        rows[8]['arms']['candidate']['5']['results'].reverse()
    elif failure == 'scoped':
        arm['scoped']['results'] = [{'file': 'other'}]
    else:
        arm['5']['seconds'] = .051
    assert not decide(rows, [str(i) for i in range(12)])['passed']


@pytest.mark.parametrize('failure', ['missing', 'duplicate', 'wrong_ids', 'missing_arm', 'missing_label'])
def test_gate_rejects_incomplete_or_mismatched_judgments(failure):
    rows = observations()
    if failure == 'missing':
        rows.pop()
    elif failure == 'duplicate':
        rows[1] = deepcopy(rows[0])
    elif failure == 'wrong_ids':
        rows[1]['id'] = 'unexpected'
    elif failure == 'missing_arm':
        rows[0]['arms'].pop('candidate')
    else:
        rows[0]['labels'].pop()
    with pytest.raises(ValueError, match='twelve'):
        decide(rows, [str(i) for i in range(12)])


def test_candidate_reorders_chunks_without_changing_first_file_order_or_scores():
    rows = [SimpleNamespace(file_path=f, score=1 / (i + 1))
            for i, f in enumerate(['tests/a', 'tests/a', 'tests/b', 'tests/a', 'tests/c'])]
    assert candidate_diversity('find response parsing tests', rows, 3, '') == [rows[0], rows[2], rows[4]]
    assert candidate_diversity('find response parsing tests', rows, 5, '') == [rows[i] for i in (0, 2, 4, 1, 3)]
    assert candidate_diversity('find response parsing tests', rows, 0, '') == []
    for query, scope in [('parse responses', ''), ('tests', ''), ('find response parsing tests', 'tests/a'),
                         ('tests ' + ' '.join(f'term{i}' for i in range(25)), '')]:
        assert candidate_diversity(query, rows, 3, scope) == _BASE_DIVERSITY(query, rows, 3, scope)


@pytest.mark.parametrize('split', ['development', 'validation'])
def test_recorded_decision_replays_from_every_frozen_question(split):
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / 'evals'
    questions = json.loads((root / 'designs' / f'2026-10-16-search-usefulness-{split}.json').read_text())
    rows = [r for group in questions['repositories'] for r in json.loads(
        (root / 'results' / f'2026-10-16-search-usefulness-{split}-{group["pack"]}.json').read_text())['queries']]
    expected = [q['id'] for group in questions['repositories'] for q in group['queries']]
    recorded = json.loads((root / 'results' / '2026-10-16-search-usefulness-decision.json').read_text())['splits'][split]
    actual = decide(rows, expected)
    assert actual == {k: v for k, v in recorded.items() if k != 'diagnosis'}
    assert actual['passed'] is False
