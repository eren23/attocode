"""Ablations retain source judgments and cannot invent candidates during fusion."""
from eval.quality.retrieval_ablation import file_fusion, metrics, token_expansion


def test_token_expansion_does_not_match_substrings_or_discard_query():
    assert token_expansion('capitalize output') == 'capitalize output'
    assert token_expansion('authenticate ciphertext') == 'authenticate ciphertext'
    expanded = token_expansion('auth middleware')
    assert expanded.startswith('auth middleware ') and 'password' in expanded


def test_file_fusion_retains_only_frozen_candidates_and_test_intent():
    trace = {'keyword': ['tests/test_read.py', 'read.py'], 'body': ['tests/test_read.py', 'write.py']}
    assert file_fusion(trace, 'read values') == ['write.py', 'read.py', 'tests/test_read.py']
    assert file_fusion(trace, 'read tests')[0] == 'tests/test_read.py'
    assert set(file_fusion(trace, 'read')) == set(trace['keyword']) | set(trace['body'])


def test_multiple_source_labels_are_counted_without_judging_unlabeled_files():
    score = metrics(['unjudged.py', 'one.py', 'two.py'], {'one.py', 'two.py'})
    assert score == {'first_rank': 2, 'hit5': True, 'hit24': True, 'labeled_recall5': 1.0}
