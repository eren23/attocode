"""The frozen candidate uses unique retained files, never labels as ranking inputs."""
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


@pytest.mark.parametrize('broken', ['questions', 'source', 'candidate', 'passed', 'checks', 'count'])
def test_validation_refuses_stale_or_unqualified_body_choice(broken):
    from eval.quality.retrieval_cycle import check_body_choice

    choice = {'questions_sha256': 'q', 'source_sha256': 's', 'candidate': 'body_file',
              'development': {'passed': True, 'checks': {str(i): True for i in range(5)},
                              'baseline': {'queries': 48}}}
    check_body_choice(choice, 'q', 's')
    if broken in ('questions', 'source'):
        choice[broken + '_sha256'] = 'different'
    elif broken == 'candidate':
        choice['candidate'] = 'new'
    elif broken == 'passed':
        choice['development']['passed'] = False
    elif broken == 'checks':
        choice['development']['checks'] = {}
    else:
        choice['development']['baseline']['queries'] = 47
    with pytest.raises(ValueError):
        check_body_choice(choice, 'q', 's')
