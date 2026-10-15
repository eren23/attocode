"""Prevent holdout leakage, inflated fusion credit and incomplete gate decisions."""
import copy

import pytest

from eval.quality.retrieval_cycle import (
    check_choice,
    choose,
    complete_rows,
    dual_fusion,
    p95,
    validation_gate,
)


def row(index, baseline=8, literal=8, dual=8):
    return {'id': str(index), 'pack': str(index % 6), 'arms': {
        arm: {'seconds': .01, 'metrics': {'first_rank': rank, 'hit5': rank is not None and rank <= 5,
               'hit24': rank is not None, 'labeled_recall5': float(rank is not None and rank <= 5)}}
        for arm, rank in [('expanded', baseline), ('literal', literal), ('dual', dual)]}}


def test_equal_weight_unique_file_fusion_and_existing_test_intent():
    assert dual_fusion(['b', 'a'], ['a', 'b'], 'lookup') == ['a', 'b']
    assert dual_fusion(['b', 'b', 'a'], ['a', 'b'], 'lookup') == ['a', 'b']
    assert dual_fusion(['tests/test_a.py', 'a.py'], [], 'lookup') == ['a.py', 'tests/test_a.py']
    assert dual_fusion(['tests/test_a.py', 'a.py'], [], 'lookup tests')[0] == 'tests/test_a.py'
    assert len(dual_fusion([str(i) for i in range(40)], [], 'lookup')) == 24


def test_selection_needs_three_net_gains_and_ties_prefer_literal():
    rows = [row(i, literal=1 if i < 2 else 8, dual=1 if i < 2 else 8) for i in range(24)]
    assert choose(rows)['candidate'] == 'none'
    rows[2] = row(2, literal=1, dual=1)
    assert choose(rows)['candidate'] == 'literal'
    rows[3] = row(3, dual=1)
    assert choose(rows)['candidate'] == 'dual'
    rows[23] = row(23, dual=None)
    assert choose(rows)['candidate'] == 'literal'  # aggregate Hit@24 loss


def test_validation_is_conjunctive_and_rejects_individual_top24_loss():
    rows = [row(i, literal=1 if i < 3 else 8) for i in range(24)]
    assert validation_gate(rows, 'literal')['passed']
    rows[23] = row(23, literal=None)
    assert not validation_gate(rows, 'literal')['passed']
    assert validation_gate(rows, 'literal')['hit24_losses'] == ['23']
    assert not validation_gate(rows, 'none')['passed']


@pytest.mark.parametrize('failure', ['repos', 'losses', 'recall', 'latency'])
def test_validation_rejects_other_individual_failures(failure):
    rows = [row(i, literal=1 if i < 5 else 8) for i in range(24)]
    if failure == 'repos':
        for r in rows:
            r['pack'] = 'one'
    elif failure == 'losses':
        rows[6], rows[7] = row(6, baseline=1), row(7, baseline=1)
    elif failure == 'recall':
        for r in rows:
            r['arms']['literal']['metrics']['labeled_recall5'] = 0
        rows[20]['arms']['expanded']['metrics']['labeled_recall5'] = 1
    else:
        for r in rows:
            r['arms']['literal']['seconds'] = .051
    assert not validation_gate(rows, 'literal')['passed']


def test_freeze_identity_and_complete_split_are_required():
    choice = {'questions_sha256': 'q', 'source_sha256': 's', 'development_queries': 24, 'candidate': 'dual'}
    check_choice(choice, 'q', 's')
    for key, value in [('questions_sha256', 'other'), ('source_sha256', 'other'),
                       ('development_queries', 23), ('candidate', 'new')]:
        broken = copy.deepcopy(choice)
        broken[key] = value
        with pytest.raises(ValueError):
            check_choice(broken, 'q', 's')
    rows = [row(i) for i in range(24)]
    questions = {'repositories': [{'queries': [{'id': str(i), 'split': 'development'} for i in range(24)]}]}
    assert complete_rows([{'queries': rows}], questions, 'development') == rows
    for invalid in (rows[:-1], rows + [rows[0]], rows[:-1] + [rows[0]]):
        with pytest.raises(ValueError):
            complete_rows([{'queries': invalid}], questions, 'development')
    assert p95(list(range(1, 25))) == 23
