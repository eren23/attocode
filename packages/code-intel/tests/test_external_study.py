import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'evals'))
    import external_benchmarks
    return external_benchmarks


def test_external_prompt_does_not_serialize_grading_fields(adapter, tmp_path):
    task = {'id': 'case', 'kind': 'qa', 'repo': 'owner/repo',
            'prompt': 'Analyze /app; mkdir -p /logs/agent; save /logs/agent/answer.txt',
            'workdir': '/app', 'timeout': 1200, 'reference_answer': 'private gold', 'rubric': 'secret rubric',
            'FAIL_TO_PASS': ['hidden_test.py'], 'patch': 'private patch'}
    rendered = adapter.prompt_for(task, tmp_path)
    assert str(tmp_path / '.benchmark/answer.txt') in rendered
    assert f'mkdir -p {tmp_path / ".benchmark"}' in rendered
    assert '/logs/agent' not in rendered
    for secret in ('private gold', 'secret rubric', 'hidden_test.py', 'private patch'):
        assert secret not in rendered


def test_runtime_helper_preserves_arguments_and_mount_boundary(adapter, monkeypatch, tmp_path):
    import subprocess
    seen = []
    monkeypatch.setattr(adapter, 'shell', lambda argv, **kwargs: seen.append(argv))
    adapter.start_runtime({'workdir': '/app', 'image': 'sha256:pinned', 'shm_size': '4g'}, tmp_path, 'test-runtime')
    argv = seen[0]
    assert argv[argv.index('--network') + 1] == 'none'
    assert argv[argv.index('--shm-size') + 1] == '4g'
    assert argv[argv.index('--mount') + 1] == f'type=bind,source={tmp_path},target=/app'
    code = (tmp_path / '.benchmark/run.py').read_text()
    monkeypatch.setattr('sys.argv', ['run.py', '--', 'printf', '%s', '$(do-not-execute); with spaces'])
    calls = []
    monkeypatch.setattr(subprocess, 'call', lambda value: calls.append(value) or 0)
    with pytest.raises(SystemExit) as result:
        exec(compile(code, 'run.py', 'exec'), {})
    assert result.value.code == 0
    assert calls[0][-2] == '-c'
    assert calls[0][-1] == "printf %s '$(do-not-execute); with spaces'"


def test_source_fingerprint_never_reads_symlink_target(adapter, tmp_path):
    from external_study import source_fingerprint
    source = tmp_path / 'source'
    source.mkdir()
    secret = tmp_path / 'secret'
    secret.write_text('one')
    (source / 'link').symlink_to(secret)
    before = source_fingerprint(source)
    secret.write_text('two')
    assert source_fingerprint(source) == before
    (source / 'code.py').write_text('value = 1')
    assert source_fingerprint(source) != before


def test_plain_text_is_opt_in_and_structured_flags_remain(adapter, tmp_path):
    from study_clients import command
    for client, flag in [('codex', '--output-schema'), ('claude', '--json-schema')]:
        kwargs = (client, 'explicit-model', tmp_path, tmp_path / client, {}, 'prompt')
        assert flag in command(*kwargs)
        assert flag not in command(*kwargs, plain_text=True)


def test_claude_plain_answer_capture_preserves_prose(adapter, monkeypatch, tmp_path):
    import study_clients
    def capture(argv, root, directory, timeout, env):
        (directory / 'events.jsonl').write_text(json.dumps({'event': {'type': 'result', 'result': 'Plain answer.'},
                                                         'received_seconds': 1}) + '\n')
        (directory / 'trace.jsonl').write_text('')
        return {'exit_code': 0, 'seconds': 1, 'quota_exhausted': False}
    monkeypatch.setattr(study_clients, 'capture', capture)
    result = study_clients.invoke('claude', 'explicit-model', tmp_path, tmp_path / 'run', {}, 'question', 10, {}, plain_text=True)
    assert result['answer_text'] == 'Plain answer.'
    assert result['output'] == {}


def test_interrupted_external_attempt_is_not_replaced(adapter, monkeypatch, tmp_path):
    import external_study
    row = {'id': 'case:codex:0:native', 'client': 'codex', 'task': 'case', 'lane': 'native'}
    monkeypatch.setattr(external_study, 'load', lambda _: {'study_id': 'frozen', 'schedule': [row]})
    monkeypatch.setattr(external_study, 'invoke', lambda *a, **kw: pytest.fail('Must not reinvoke'))
    (tmp_path / 'preparation.json').write_text(json.dumps({'study_id': 'frozen', 'passed': True}))
    folder = tmp_path / 'runs' / row['id'].replace(':', '-')
    folder.mkdir(parents=True)
    external_study.run(SimpleNamespace(study=tmp_path, clients=None, tasks=None, max_runs=4))
    assert json.loads((folder / 'result.json').read_text())['status'] == 'interrupted'


def test_new_implementation_included_but_adapter_output_excluded(adapter, tmp_path):
    (tmp_path / 'code.py').write_text('value = 1\n')
    (tmp_path / '.benchmark').mkdir()
    (tmp_path / '.benchmark/run.py').write_text('# helper\n')
    adapter.initialize_git(tmp_path)
    (tmp_path / 'new.py').write_text('value = 2\n')
    (tmp_path / '.benchmark/answer.txt').write_text('private answer')
    patch, changed = adapter.submitted_patch(tmp_path)
    assert changed == ['new.py']
    assert 'value = 2' in patch and 'private answer' not in patch


def test_quota_expiry_stops_external_invocation(adapter, monkeypatch, tmp_path):
    import external_study
    from study_clients import quota_ready
    monkeypatch.setattr(external_study, 'preflight', lambda client, quota, env: {'ready': quota_ready(client, quota)})
    path = tmp_path / 'quota.json'
    path.write_text(json.dumps({'codex': {'subscription_only': True, 'extra_usage_disabled': True,
                                        'remaining': True, 'checked_at': 1}}))
    with pytest.raises(RuntimeError, match='blocked'):
        external_study.ready(SimpleNamespace(quota=path), 'codex')


def test_pack_rejects_unverified_reference_and_missing_negative_control(adapter, tmp_path):
    tasks = []
    for index, kind in enumerate(('qa', 'qa', 'feature', 'feature')):
        identity = f'task-{index}'
        (tmp_path / 'sources' / identity).mkdir(parents=True)
        tasks.append({'id': identity, 'repo': f'repo-{index}', 'kind': kind, 'image': 'sha256:pinned',
                      'timeout': 1200 if kind == 'qa' else 3600,
                      'preparation': {'passed': True, 'rubric_verified': True, 'runtime_verified': True,
                                      'reference_passed': True, 'starting_feature_failed': True,
                                      'existing_behavior_passed': True}})
    adapter.validate_pack({'tasks': tasks}, tmp_path)
    for key in ('reference_passed', 'existing_behavior_passed', 'starting_feature_failed'):
        tasks[-1]['preparation'][key] = False
        with pytest.raises(ValueError, match='controls'):
            adapter.validate_pack({'tasks': tasks}, tmp_path)
        tasks[-1]['preparation'][key] = True


def test_external_report_cannot_authorize_release(adapter):
    from release_gate import evaluate
    result = evaluate({'manifest': {'mode': 'external'}, 'runs': []}, 'candidate')
    assert not result['passed']
    assert any('development evidence' in reason for reason in result['reasons'])


def test_external_socket_permission_is_scoped_and_opt_in(adapter, tmp_path):
    import tomllib

    from study_clients import command
    ordinary = command('codex', 'model', tmp_path, tmp_path / 'ordinary', {}, 'prompt')
    external = command('codex', 'model', tmp_path, tmp_path / 'external', {}, 'prompt', runtime_socket='/tmp/docker.sock')
    assert '--sandbox' in ordinary and '--sandbox' not in external
    settings = next(v for v in external if v.startswith('permissions='))
    profile = tomllib.loads(settings)['permissions']['external_benchmark']
    assert profile['extends'] == ':workspace'
    assert profile['network']['unix_sockets'] == {'/tmp/docker.sock': 'allow'}
    assert profile['network']['domains'] == {} and profile['network']['mode'] == 'limited'
    assert not profile['network'].get('dangerously_allow_all_unix_sockets')
    assert 'web_search="disabled"' in external


@pytest.mark.parametrize('corruption', ['changed_answer', 'changed_patch', 'missing_commit', 'wrong_identity'])
def test_external_report_rejects_corrupted_submissions(adapter, monkeypatch, tmp_path, corruption):
    import external_study
    from study import digest

    row = {'id': 'case:codex:0:native', 'client': 'codex', 'task': 'case', 'lane': 'native', 'repeat': 0}
    monkeypatch.setattr(external_study, 'load', lambda _: {'study_id': 'frozen', 'schedule': [row]})
    folder = tmp_path / 'runs' / row['id'].replace(':', '-')
    folder.mkdir(parents=True)
    record = {**row, 'study_id': 'frozen', 'status': 'completed'}
    if corruption == 'wrong_identity':
        record['lane'] = 'current'
    (folder / 'result.json').write_text(json.dumps(record))
    (folder / 'committed-answer.json').write_text(json.dumps({
        'text': 'changed' if corruption == 'changed_answer' else 'original', 'sha256': digest('original')}))
    (folder / 'submitted.diff').write_text('changed' if corruption == 'changed_patch' else 'patch')
    if corruption != 'missing_commit':
        (folder / 'committed-patch.json').write_text(json.dumps({'sha256': digest('patch')}))
    with pytest.raises(ValueError, match='submission|schedule'):
        external_study.report(SimpleNamespace(study=tmp_path))
    assert not (tmp_path / 'report.json').exists()


@pytest.fixture
def operator_case(adapter, tmp_path):
    from external_study import operator_scores
    rubric = tmp_path / 'private/atlas/case/tests/rubrics.json'
    rubric.parent.mkdir(parents=True)
    rubric.write_text(json.dumps([
        {'id': 'correct_fact', 'annotations': {'type': 'positive hli verifier'}},
        {'id': 'invented_observation', 'annotations': {'type': 'negative hli verifier'}},
    ]))
    manifest = {'study_id': 'frozen', 'tasks': [{'id': 'case', 'kind': 'qa'}]}
    rows = [{'id': 'attempt', 'task': 'case'}]
    return operator_scores, manifest, rows


def test_operator_review_keeps_negative_criteria_and_protocol_separate(operator_case, tmp_path):
    score, manifest, rows = operator_case
    review = {'study_id': 'frozen', 'attempts': {'attempt': {
        'criteria': {'correct_fact': True, 'invented_observation': True}, 'protocol': 'violation'}}}
    path = tmp_path / 'operator-review.json'
    path.write_text(json.dumps(review))
    actual, scores, template = score(tmp_path, manifest, rows)
    assert scores['attempt'] == {'protocol': 'violation', 'qa': {
        'positive_met': 1, 'positive_total': 1, 'negative_triggered': 1, 'negative_total': 1}}
    assert actual == review == json.loads(path.read_text())
    assert all(v is None for v in template['attempts']['attempt']['criteria'].values())


@pytest.mark.parametrize('criteria', [None, {'correct_fact': True, 'invented_observation': None}])
def test_unreviewed_or_partial_qa_is_pending_not_zero(operator_case, tmp_path, criteria):
    score, manifest, rows = operator_case
    if criteria is not None:
        (tmp_path / 'operator-review.json').write_text(json.dumps({
            'study_id': 'frozen', 'attempts': {'attempt': {'criteria': criteria}}}))
    _, scores, _ = score(tmp_path, manifest, rows)
    assert scores['attempt']['qa'] is None


@pytest.mark.parametrize('criteria', [
    {'correct_fact': True},
    {'correct_fact': True, 'invented_observation': 'false'},
    {'correct_fact': True, 'invented_observation': False, 'extra': True},
])
def test_operator_review_requires_exact_boolean_rubric_verdicts(operator_case, tmp_path, criteria):
    score, manifest, rows = operator_case
    (tmp_path / 'operator-review.json').write_text(json.dumps({
        'study_id': 'frozen', 'attempts': {'attempt': {'criteria': criteria}}}))
    with pytest.raises(ValueError, match='criterion IDs and boolean'):
        score(tmp_path, manifest, rows)


def test_operator_review_cannot_cross_study_boundaries(operator_case, tmp_path):
    score, manifest, rows = operator_case
    (tmp_path / 'operator-review.json').write_text(json.dumps({'study_id': 'other', 'attempts': {}}))
    with pytest.raises(ValueError, match='different study'):
        score(tmp_path, manifest, rows)


def test_report_compares_reviewed_quality_without_overwriting_review(operator_case, monkeypatch, tmp_path):
    import external_study
    from study import digest

    _, manifest, _ = operator_case
    manifest.update(seed=9341, scope='diagnostic', grading='operator review')
    manifest['tasks'][0].update(repo='owner/repo', prompt='Question', workdir='/app', timeout=1200)
    manifest['schedule'] = [
        {'id': f'case:codex:0:{lane}', 'client': 'codex', 'task': 'case', 'lane': lane, 'repeat': 0}
        for lane in ('native', 'current')]
    attempts = {}
    for row in manifest['schedule']:
        folder = tmp_path / 'runs' / row['id'].replace(':', '-')
        folder.mkdir(parents=True)
        (folder / 'result.json').write_text(json.dumps({
            **row, 'study_id': 'frozen', 'status': 'completed', 'seconds': 10, 'stages': []}))
        (folder / 'committed-answer.json').write_text(json.dumps({'text': 'answer', 'sha256': digest('answer')}))
        (folder / 'committed-patch.json').write_text(json.dumps({'sha256': digest('')}))
        (folder / 'submitted.diff').write_text('')
        attempts[row['id']] = {'criteria': {'correct_fact': True, 'invented_observation': row['lane'] == 'current'}}
    review_path = tmp_path / 'operator-review.json'
    original = json.dumps({'study_id': 'frozen', 'attempts': attempts})
    review_path.write_text(original)
    monkeypatch.setattr(external_study, 'load', lambda _: manifest)
    external_study.report(SimpleNamespace(study=tmp_path))
    output = json.loads((tmp_path / 'report.json').read_text())
    groups = {g['lane']: g for g in output['groups'] if g['client'] == 'codex'}
    assert groups['native']['qa_negative_triggered'] == 0
    assert groups['current']['qa_negative_triggered'] == 1
    assert groups['current']['qa_positive_met'] == groups['native']['qa_positive_met'] == 1
    assert '1/1 positive; 0/1 negative | 1/1 positive; 1/1 negative' in (tmp_path / 'comparison.md').read_text()
    assert review_path.read_text() == original
