"""The frozen candidate uses unique retained files, never labels as ranking inputs."""
import copy

import pytest

from eval.quality.retrieval_body_trial import body_file_fusion, evaluate


def test_body_fusion_cannot_invent_or_double_count_files():
    trace = {'keyword': ['one', 'one', 'two'], 'body': ['two', 'one']}
    assert body_file_fusion(trace, 'lookup') == ['two', 'one']
    assert body_file_fusion({'keyword': ['one', 'two'], 'body': ['two', 'one']}, 'lookup') == ['two', 'one']
    assert body_file_fusion({'keyword': ['tests/test_a.py'], 'body': ['tests/test_a.py', 'a.py']}, 'lookup') == ['a.py', 'tests/test_a.py']
    assert body_file_fusion({'keyword': [], 'body': [str(i) for i in range(30)]}, 'lookup') == [str(i) for i in range(24)]


def test_incomplete_consumed_development_is_rejected():
    with pytest.raises(ValueError):
        evaluate({'reports': {'development': [{'queries': []}], 'validation': []}})


def qualified_choice():
    return {'questions_sha256': 'q', 'source_sha256': 's', 'candidate': 'body_file',
            'development': {'passed': True, 'checks': {
                'net_hit5_at_least_four': True, 'gains_in_two_repos': True,
                'at_most_two_hit5_losses': True, 'no_individual_hit24_loss': True,
                'recall5_not_decreased': True},
                'baseline': {'queries': 48}, 'candidate': {'queries': 48}}}


@pytest.mark.parametrize('broken', ['questions', 'source', 'candidate', 'passed', 'checks', 'count',
                                    'renamed_check', 'string_check', 'integer_check', 'string_passed',
                                    'candidate_count', 'missing_development', 'null_development'])
def test_validation_refuses_stale_or_unqualified_body_choice(broken):
    from eval.quality.retrieval_cycle import check_body_choice

    choice = qualified_choice()
    check_body_choice(choice, 'q', 's')
    if broken in ('questions', 'source'):
        choice[broken + '_sha256'] = 'different'
    elif broken == 'candidate':
        choice['candidate'] = 'new'
    elif broken == 'passed':
        choice['development']['passed'] = False
    elif broken == 'checks':
        choice['development']['checks'] = {}
    elif broken == 'count':
        choice['development']['baseline']['queries'] = 47
    elif broken == 'renamed_check':
        choice['development']['checks'] = {str(i): True for i in range(5)}
    elif broken in ('string_check', 'integer_check'):
        choice['development']['checks']['no_individual_hit24_loss'] = 'false' if broken == 'string_check' else 1
    elif broken == 'string_passed':
        choice['development']['passed'] = 'false'
    elif broken == 'candidate_count':
        choice['development']['candidate']['queries'] = 47
    elif broken == 'missing_development':
        del choice['development']
    else:
        choice['development'] = None
    with pytest.raises(ValueError):
        check_body_choice(choice, 'q', 's')


@pytest.mark.parametrize('bad', [None, [], 'passed', True, 1])
def test_non_object_choice_is_rejected(bad):
    from eval.quality.retrieval_cycle import check_body_choice

    with pytest.raises(ValueError):
        check_body_choice(bad, 'q', 's')


def test_every_named_development_check_is_required():
    from eval.quality.retrieval_cycle import check_body_choice

    choice = qualified_choice()
    for check in choice['development']['checks']:
        broken = copy.deepcopy(choice)
        broken['development']['checks'][check] = False
        with pytest.raises(ValueError):
            check_body_choice(broken, 'q', 's')
