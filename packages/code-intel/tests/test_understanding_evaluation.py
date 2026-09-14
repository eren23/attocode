import json
from pathlib import Path

import pytest


@pytest.fixture
def scoring(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'evals'))
    import understanding_scoring
    return understanding_scoring


def answer():
    return {'schema_version':1,'predictions':[{'id':'one','predicted_json':'{"value": 1}',
             'explanation':'The branch returns an integer.','references':['source']}],
            'impacts':[{'id':'one','changed':False,'explanation':'The guard excludes this input.','references':['source']}],
            'diagnosis':'','references':[{'id':'source','path':'source.py','start_line':1,'end_line':1}],
            'test_files':['test_alternative.py']}


def test_prediction_accuracy_is_independent_of_bad_citation_and_alternative_tests(scoring, tmp_path):
    (tmp_path / 'source.py').write_text('return 1\n')
    (tmp_path / 'test_alternative.py').write_text('assert result == 1\n')
    a = answer()
    a['references'][0]['start_line'] = 99
    grade = scoring.grade(tmp_path, {'kind':'analysis','required_tests':['test_authored.py']}, a,
                          {'one':{'value':1}}, {'one':False})
    assert grade['analysis']['score'] == 1
    assert not grade['references'][0]['location_valid']
    assert grade['alternative_tests_for_review'] == ['test_alternative.py']
    assert grade['prose_review'] == 'pending'


@pytest.mark.parametrize('attack', ['missing','duplicate','boolean','wrong_impact','non_json'])
def test_omitted_duplicate_and_contradictory_predictions(scoring, tmp_path, attack):
    a = answer()
    if attack == 'missing':
        a['predictions'] = []
    elif attack == 'duplicate':
        a['predictions'] *= 2
    elif attack == 'boolean':
        a['predictions'][0]['predicted_json'] = '{"value": true}'
    elif attack == 'wrong_impact':
        a['impacts'][0]['changed'] = True
    else:
        a['predictions'][0]['predicted_json'] = 'unknown'
    grade = scoring.grade(tmp_path, {'kind':'analysis'}, a, {'one':{'value':1}}, {'one':False})
    assert grade['analysis']['score'] == .5


def test_trace_protocol_distinguishes_execution_and_ambiguous_reads(scoring, tmp_path):
    calls = [{'id':'run','name':'Bash','arguments':{'command':'node script.js'}},
             {'id':'outside','name':'Read','arguments':{'file_path':'../private/case_pack.py'}},
             {'id':'inspect','name':'shell','arguments':{'command':'python -c "print(open(\'source.py\').read())"'}}]
    audit = scoring.protocol_audit(tmp_path, calls, 'analysis', [])
    assert audit['status'] == 'violation'
    assert {v['call'] for v in audit['violations']} == {'run','outside'}
    assert any(r['call'] == 'inspect' for r in audit['review_required'])


def test_submission_preserves_independent_tests_even_when_agent_disables_them(scoring, tmp_path):
    from understanding_study import reconstruct_submission
    clean, submitted = tmp_path / 'clean', tmp_path / 'submitted'
    for root in (clean, submitted):
        (root / 'src').mkdir(parents=True)
        (root / 'src/main.py').write_text('value = 1\n')
        (root / 'test_main.py').write_text('assert value == 1\n')
    (submitted / 'src/main.py').write_text('value = 2\n')
    (submitted / 'test_main.py').write_text('pass\n')
    reconstruct_submission(clean, submitted, ['src'])
    assert (clean / 'src/main.py').read_text() == 'value = 2\n'
    assert (clean / 'test_main.py').read_text() == 'assert value == 1\n'
    (submitted / 'src/escape.py').symlink_to(tmp_path / 'secret.py')
    with pytest.raises(ValueError, match='Symlink'):
        reconstruct_submission(clean, submitted, ['src'])


def test_source_and_private_pack_fingerprints_detect_non_python_drift(scoring, tmp_path):
    from study import tree_hash
    (tmp_path / 'probe.js').write_text('console.log(1);')
    initial = tree_hash(tmp_path)
    (tmp_path / 'probe.js').write_text('console.log(2);')
    assert tree_hash(tmp_path) != initial


def test_interrupted_trial_is_preserved_without_reinvocation(scoring, tmp_path, monkeypatch):
    from types import SimpleNamespace

    import understanding_study as runner
    row = {'id':'repo:repair:codex:0:current','client':'codex','task':'repo:repair','lane':'current'}
    manifest = {'study_id':'frozen','schedule':[row]}
    monkeypatch.setattr(runner, 'load', lambda _: (manifest, None))
    monkeypatch.setattr(runner, 'invoke', lambda *a, **k: pytest.fail('Interrupted trial must not rerun'))
    (tmp_path / 'preparation.json').write_text(json.dumps({'study_id':'frozen','tasks':{'case':{'passed':True}}}))
    directory = tmp_path / 'runs' / row['id'].replace(':','-')
    directory.mkdir(parents=True)
    runner.run(SimpleNamespace(study=tmp_path, clients=None, tasks=None, max_runs=6))
    assert json.loads((directory / 'result.json').read_text())['status'] == 'interrupted'


def test_private_controls_never_reach_public_prompt_renderer(scoring):
    from types import SimpleNamespace

    from understanding_study import public_prompt
    task = {'id':'repo:analysis','repo':'repo','kind':'analysis', 'required_tests':['hidden.py'],
            'counterfactual':[{'path':'source.py','before':'a','after':'b',
                              'expected_changes':['secret_answer'],'preserved_controls':['secret_control']}]}
    rendered = public_prompt(SimpleNamespace(prompt=lambda value: json.dumps(value)), task)
    assert 'secret_answer' not in rendered and 'secret_control' not in rendered and 'hidden.py' not in rendered
    assert 'source.py' in rendered
