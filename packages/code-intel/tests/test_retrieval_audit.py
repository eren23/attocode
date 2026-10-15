"""Saved-page audits cannot turn missing or truncated evidence into retrieval failure."""
from copy import deepcopy

import pytest

from eval.quality.retrieval_audit import audit


def report():
    return {'repositories': [{'id': 'sample', 'expected_questions': ['sample:1', 'sample:2'],
                              'retrieval': [{'id': 'sample:1', 'query': 'parse input',
                                             'ranked_files': ['other.py'], 'labeled_files': ['target.py'],
                                             'first_labeled_rank': None, 'hit_at_5': False,
                                             'hit_at_24': False, 'seconds': .01,
                                             'metadata': {'ranking': {'candidate_pool_count': 24,
                                                                      'index': {'status': 'ready'}}}}]}]}


def test_missing_questions_and_page_absence_remain_unresolved():
    result = audit(report())
    assert result['missing_questions'] == ['sample:2']
    assert result['categories'] == {'page_miss_unresolved': 1}
    assert result['observed_questions'] == 1


@pytest.mark.parametrize('incomplete', ['truncated', 'warming'])
def test_incomplete_response_cannot_be_scored_as_ready_miss(incomplete):
    data = report()
    metadata = data['repositories'][0]['retrieval'][0]['metadata']
    if incomplete == 'truncated':
        metadata['truncated'] = True
    else:
        metadata['ranking']['index']['status'] = 'warming'
    assert audit(data)['categories'] == {'incomplete': 1}


def test_rejects_conflicting_scores_and_duplicate_questions():
    data = report()
    data['repositories'][0]['retrieval'][0]['hit_at_5'] = True
    with pytest.raises(ValueError, match='Inconsistent'):
        audit(data)
    data = report()
    data['repositories'].append(deepcopy(data['repositories'][0]))
    with pytest.raises(ValueError, match='Duplicate'):
        audit(data)
