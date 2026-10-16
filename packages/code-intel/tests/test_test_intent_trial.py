"""Scope and acceptance checks for the frozen test-intent candidate."""
from types import SimpleNamespace

import pytest
from attocode_intel.query_ranking import demote_tests

from eval.quality.test_intent_trial import baseline_partition, candidate_partition, decide


def test_only_short_test_intent_changes_stable_order():
    rows = [SimpleNamespace(file_path=p, score=1 - i / 10) for i, p in enumerate([
        'src/parser.py', 'tests/fixture.py', 'src/lexer.py', 'src/jvmTest/kotlin/Helper.kt'])]
    assert candidate_partition('parser tests', rows) == [rows[i] for i in (1, 3, 0, 2)]
    assert demote_tests('parser tests', rows) == candidate_partition('parser tests', rows)
    assert baseline_partition('parser tests', rows) is rows
    for query in ['parse nested syntax', 'contest parser', 'test ' + ' '.join(f'word{i}' for i in range(25))]:
        assert candidate_partition(query, rows) == baseline_partition(query, rows)
        assert demote_tests(query, rows) == candidate_partition(query, rows)
    assert {id(r) for r in candidate_partition('tests', rows)} == {id(r) for r in rows}


def observations():
    rows = []
    for i in range(12):
        label = f'label{i}'
        rows.append({'id':str(i), 'pack':str(i % 4), 'intent':'test' if i < 8 else 'production',
                     'labels':[label], 'arms':{a:{'files':(['noise'] * 5 + [label] if a == 'baseline' and i < 2 else [label]),
                                               'results':[], 'seconds':.01,
                                               'stages':dict.fromkeys(('keyword','body','file_bm25','chunk_fused'), [label])}
                                            for a in ('baseline','candidate')}})
    return rows


def test_gate_requires_gains_in_multiple_repositories():
    rows = observations()
    assert decide(rows, [str(i) for i in range(12)])['passed']
    rows[1]['pack'] = rows[0]['pack']
    assert not decide(rows, [str(i) for i in range(12)])['passed']


@pytest.mark.parametrize('failure', ['loss', 'control', 'generation', 'latency'])
def test_gate_rejects_individual_regressions(failure):
    rows = observations()
    if failure == 'loss':
        rows[3]['arms']['candidate']['files'] = ['wrong']
    elif failure == 'control':
        rows[8]['arms']['candidate']['results'] = ['changed']
    elif failure == 'generation':
        rows[0]['arms']['candidate']['stages']['body'] = ['changed']
    else:
        rows[0]['arms']['candidate']['seconds'] = .06
    assert not decide(rows, [str(i) for i in range(12)])['passed']


def test_gate_rejects_missing_pairs():
    with pytest.raises(ValueError, match='twelve'):
        decide(observations()[:-1], [str(i) for i in range(12)])
