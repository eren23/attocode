"""Prospective controls for engine isolation and durable paired requests."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from eval.quality import numeric_retention_experiment as operator
from eval.quality.experiment_evidence import Journal
from eval.quality.fixture_identity import source_manifest


@pytest.fixture
def controlled_patch(monkeypatch):
    raw = b'before\n'
    def archive(_commit, dest):
        root = dest/'attocode_intel'
        root.mkdir(parents=True)
        (root/'module.py').write_bytes(raw)
        (root/'unchanged.py').write_bytes(b'constant = 1\n')
        return root
    monkeypatch.setattr(operator, 'archive_engine', archive)
    return {'path': 'module.py', 'before': 'before\n', 'after': 'after\n',
            'before_sha256': hashlib.sha256(raw).hexdigest(),
            'after_sha256': hashlib.sha256(b'after\n').hexdigest()}


def test_engine_derivation_preserves_baseline_and_other_files(tmp_path, controlled_patch):
    engines = operator.prepare_engines(tmp_path, controlled_patch)
    assert (engines['baseline']/'module.py').read_bytes() == b'before\n'
    assert (engines['candidate']/'module.py').read_bytes() == b'after\n'
    assert (engines['baseline']/'unchanged.py').read_bytes() == (engines['candidate']/'unchanged.py').read_bytes()


@pytest.mark.parametrize('field,value', [('before_sha256', '0'*64), ('after_sha256', '0'*64), ('path', '../outside.py')],
                         ids=['baseline-binding', 'candidate-binding', 'path-escape'])
def test_engine_derivation_rejects_bad_binding(tmp_path, controlled_patch, field, value):
    controlled_patch[field] = value
    with pytest.raises(ValueError):
        operator.prepare_engines(tmp_path, controlled_patch)
    assert (tmp_path/'engines/baseline/attocode_intel/module.py').read_bytes() == b'before\n'
    assert not (tmp_path/'engines/candidate/outside.py').exists()


def test_workunit_order_has_global_primary_barrier():
    rows = operator.trial_order(['amber', 'violet'])
    assert [(r['repo_id'], r['arm']) for r in rows[:4]] == [
        ('amber', 'baseline'), ('amber', 'candidate'), ('violet', 'candidate'), ('violet', 'baseline')]
    assert [r['phase'] for r in rows] == ['primary']*4+['diagnostic']*4
    assert len({r['id'] for r in rows}) == 8


def cases():
    return [{'id': str(i), 'query': 'synthetic control '+str(i),
             'evidence': [{'file': 'control.py', 'line': 1, 'quote': 'not a real question'}]} for i in range(2)]


@pytest.mark.parametrize('phase', ['primary', 'diagnostic'])
@pytest.mark.asyncio
async def test_requests_are_durable_and_use_frozen_query_scope(tmp_path, monkeypatch, phase):
    journal = Journal(tmp_path/'journal', 2**20)
    report = {'arm': 'candidate', 'repo_id': 'synthetic', 'issued': [], 'pages': []}
    calls = []
    async def observed(_gateway, query, **kwargs):
        event = json.loads((journal.root/'events.jsonl').read_text().splitlines()[-1])
        raw = (journal.root/event['response']['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == event['response']['sha256']
        arguments = json.loads(raw)
        assert event['request']['event'] == 'consume_request'
        assert arguments['query'] == query and arguments['top_k'] == kwargs['top_k']
        assert arguments['max_tokens'] == kwargs['budget'] and arguments['file_filter'] == kwargs['file_filter']
        calls.append((query, kwargs['top_k'], kwargs['budget'], kwargs['file_filter']))
        return {'response': {'data': {'results': []}}}
    monkeypatch.setattr(operator, 'observe', observed)
    await operator.collect_worker(object(), cases(), phase, journal, report, lambda: None)
    expected = [('synthetic control 0', 10, 2000, ''), ('synthetic control 1', 10, 2000, '')]
    if phase == 'diagnostic':
        expected = [('synthetic control 0', 24, 8000, ''), ('synthetic control 0', 5, 4000, 'control.py'),
                    ('synthetic control 1', 24, 8000, ''), ('synthetic control 1', 5, 4000, 'control.py')]
    assert calls == expected and len(report['issued']) == len(report['pages']) == len(expected)


@pytest.mark.asyncio
async def test_failed_request_is_consumed_and_not_retried(tmp_path, monkeypatch):
    journal = Journal(tmp_path/'journal', 2**20)
    report = {'arm': 'baseline', 'repo_id': 'synthetic', 'issued': [], 'pages': []}
    calls = []
    async def observed(_gateway, query, **_kwargs):
        calls.append(query)
        if len(calls) == 2:
            raise RuntimeError('controlled response failure')
        return {'response': {'data': {'results': []}}}
    monkeypatch.setattr(operator, 'observe', observed)
    with pytest.raises(RuntimeError, match='controlled response failure'):
        await operator.collect_worker(object(), cases(), 'primary', journal, report, lambda: None)
    assert calls == ['synthetic control 0', 'synthetic control 1']
    assert len(report['issued']) == 2 and len(report['pages']) == 1
    assert len((journal.root/'events.jsonl').read_bytes().splitlines()) == 2


def test_false_dispatch_does_not_acquire_or_issue_questions(tmp_path, monkeypatch, controlled_patch):
    inputs = tmp_path/'inputs'
    inputs.mkdir()
    (tmp_path/'evidence').mkdir()
    (inputs/'patch.json').write_text(json.dumps(controlled_patch))
    (inputs/'development-questions.json').write_text(json.dumps({
        'engine_commit': operator.BASELINE, 'cases': [{}]*4, 'repositories': [{}, {}]}))
    (inputs/'protocol.json').write_text(json.dumps({'scientific_calls': 24, 'roles': {
        'primary': {'top_k': 10, 'max_tokens': 2000}, 'deep': {'top_k': 24, 'max_tokens': 8000},
        'scoped': {'top_k': 5, 'max_tokens': 4000}}}))
    monkeypatch.setattr(operator, 'INPUTS', inputs)
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    monkeypatch.setenv('ATTOCODE_NUMERIC_ISSUE_DEVELOPMENT', 'false')
    monkeypatch.setattr(operator, 'qualify_candidate', lambda *_: None)
    def forbidden(*_args, **_kwargs):
        raise AssertionError('false dispatch reached a scientific source or worker')
    monkeypatch.setattr(operator, 'materialize_bound', forbidden)
    monkeypatch.setattr(operator, 'execute_workunits', forbidden)
    operator.run(tmp_path)
    report = json.loads((tmp_path/'evidence/trial.json').read_bytes())
    assert report['status'] == 'complete' and not report['scientific_allowed']
    assert report['scientific_requests'] == 0 and report['workers'] == []


def test_real_child_engines_are_isolated_and_capture_effective_terms(tmp_path):
    patch = json.loads((operator.INPUTS/'patch.json').read_bytes())
    engines = operator.prepare_engines(tmp_path, patch)
    raw = b'def amber_control():\n    """Synthetic response control."""\n    return 613\n'
    pids, outputs = [], {}
    for arm, engine in engines.items():
        workspace = tmp_path/('source-'+arm)
        workspace.mkdir()
        (workspace/'control.py').write_bytes(raw)
        evidence = tmp_path/('evidence-'+arm)
        evidence.mkdir()
        job = {'arm': arm, 'phase': 'primary', 'repo_id': 'synthetic',
               'source_sha256': operator.digest(source_manifest(workspace)),
               'engine_files': operator.engine_files(engine), 'cases': [{
                   'id': 'synthetic', 'query': 'control 613 response',
                   'evidence': [{'file': 'control.py', 'line': 3, 'quote': '    return 613'}]}]}
        job_path = evidence/'job.json'
        job_path.write_text(json.dumps(job))
        process = subprocess.run([os.sys.executable, '-m', 'eval.quality.numeric_retention_experiment',
            '--worker', '--workspace', str(workspace), '--job', str(job_path), '--evidence', str(evidence)],
            cwd=operator.REPO, env=operator.child_environment(engine), capture_output=True, text=True)
        assert process.returncode == 0, process.stderr
        report = json.loads((evidence/'worker.json').read_bytes())
        assert report['status'] == 'complete' and report['source_unchanged'] and report['engine_unchanged']
        pids.append(report['pid'])
        page = report['pages'][0]
        assert page['request']['query'] == 'control 613 response'
        stages = page['generation_diagnostic']
        assert [s['stage'] for s in stages] == ['keyword', 'body', 'file_bm25']
        for stage in stages:
            terms = stage['arguments'][0]
            terms = terms.split() if isinstance(terms, str) else terms
            assert ('613' in terms) == (arm == 'candidate')
            assert {'control', 'response'} <= set(terms)
        outputs[arm] = report['engine_sha256']
        assert (workspace/'control.py').read_bytes() == raw
    assert len(set(pids)) == 2 and outputs['baseline'] != outputs['candidate']


@pytest.mark.parametrize('bad', ['engine', 'source'])
@pytest.mark.asyncio
async def test_misbound_worker_fails_before_gateway_request(tmp_path, monkeypatch, bad):
    import attocode_intel
    import attocode_intel.gateway

    selected = Path(attocode_intel.__file__).parent
    monkeypatch.setenv('ATTOCODE_EXPERIMENT_ENGINE', str(selected))
    source = tmp_path/'source'
    source.mkdir()
    (source/'control.py').write_text('value = 613\n')
    dest = tmp_path/'evidence'
    dest.mkdir()
    job = {'engine_files':operator.engine_files(selected),
           'source_sha256':operator.digest(source_manifest(source))}
    job['engine_files' if bad=='engine' else 'source_sha256'] = {} if bad=='engine' else 'wrong'
    requests = []
    def forbidden(*_args, **_kwargs):
        requests.append('opened')
        raise AssertionError('misbound worker opened gateway')
    monkeypatch.setattr(attocode_intel.gateway,'OperationGateway',forbidden)
    with pytest.raises(ValueError,match='binding mismatch|differs from frozen arm'):
        await operator.worker_async(source,job,dest)
    assert requests==[] and not (dest/'journal').exists()


@pytest.mark.parametrize('failure', ['nonzero', 'incomplete'])
def test_failed_workunit_stops_followups_and_retains_partial_issue(tmp_path,monkeypatch,failure):
    from types import SimpleNamespace

    engines,fixtures,inventories = {},{},{}
    for arm in ['baseline','candidate']:
        engine=tmp_path/'engines'/arm
        engine.mkdir(parents=True)
        (engine/'control.py').write_text('value = 613\n')
        engines[arm]=engine
        for repo in ['amber','violet']:
            source=tmp_path/'fixtures'/(repo+'-'+arm)
            source.mkdir(parents=True)
            (source/'control.py').write_text('value = 613\n')
            fixtures[repo,arm]=source
            inventories[repo]=source_manifest(source)
    manifest={'repositories':[{'id':'amber'},{'id':'violet'}],
              'cases':[dict(c,repo_id=repo) for repo in ['amber','violet'] for c in cases()]}
    report={'workers':[]}
    calls=[]
    def failed(command,**_kwargs):
        dest=Path(command[command.index('--evidence')+1])
        calls.append(dest)
        journal=Journal(dest/'journal',2**20)
        ref=journal.response({'event':'consume_request','id':'0','role':'primary'},
                             {'query':'synthetic control 0'})
        (dest/'worker.json').write_text(json.dumps({'status':'incomplete','pid':123,
                                                   'issued':[{'id':'0','role':'primary','ref':ref}]}))
        return SimpleNamespace(returncode=1 if failure=='nonzero' else 0)
    monkeypatch.setattr(operator.subprocess,'run',failed)
    with pytest.raises(ValueError,match='worker failed|incomplete or reused worker'):
        operator.execute_workunits(tmp_path,manifest,engines,fixtures,inventories,report)
    assert len(calls)==len(report['workers'])==1
    retained=json.loads((calls[0]/'worker.json').read_bytes())
    assert retained['status']=='incomplete' and len(retained['issued'])==1
    ref=retained['issued'][0]['ref']
    raw=(calls[0]/'journal'/ref['path']).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==ref['sha256']
    assert json.loads(raw)['query']=='synthetic control 0'
    assert report['workers'][0]['status']=='incomplete'
    assert len(list((tmp_path/'evidence/workers').iterdir()))==1


@pytest.mark.asyncio
async def test_observation_failure_closes_gateway_and_attests_final_inputs(tmp_path,monkeypatch):
    from types import SimpleNamespace

    import attocode_intel
    import attocode_intel.gateway

    from eval.quality import corpus

    selected=Path(attocode_intel.__file__).parent
    monkeypatch.setenv('ATTOCODE_EXPERIMENT_ENGINE',str(selected))
    source=tmp_path/'source'
    source.mkdir()
    (source/'control.py').write_text('value = 613\n')
    dest=tmp_path/'evidence'
    dest.mkdir()
    job={'arm':'baseline','repo_id':'controlled','phase':'primary','cases':cases(),
         'engine_files':operator.engine_files(selected),'source_sha256':operator.digest(source_manifest(source))}
    closed=[]
    class Peer:
        def __init__(self,*_args,**_kwargs):pass
        async def close(self):closed.append(True)
    monkeypatch.setattr(attocode_intel.gateway,'OperationGateway',Peer)
    async def ready(*_args,**_kwargs):
        raw={'data':{'ranking':{'index':{'status':'ready','body_index_ready':True}}}}
        return SimpleNamespace(isError=False,content=[SimpleNamespace(text=json.dumps(raw))]),{}
    monkeypatch.setattr(corpus,'ready_search',ready)
    async def fail(*_args,**_kwargs):raise RuntimeError('controlled observe failure')
    monkeypatch.setattr(operator,'observe',fail)
    with pytest.raises(RuntimeError,match='controlled observe failure'):
        await operator.worker_async(source,job,dest)
    assert closed==[True]
    report=json.loads((dest/'worker.json').read_bytes())
    assert report['status']=='incomplete' and len(report['issued'])==1 and report['pages']==[]
    assert report['source_unchanged'] and report['engine_unchanged']
    events=[json.loads(line)['request']['event'] for line in (dest/'journal/events.jsonl').read_text().splitlines()]
    assert events==['engine_before','source_before','consume_request','gateway_close','source_after','engine_after']


def test_causal_pytest_respects_selected_engine_over_project_path(tmp_path):
    patch=json.loads((operator.INPUTS/'patch.json').read_bytes())
    engines=operator.prepare_engines(tmp_path,patch)
    proof=operator.qualify_candidate(tmp_path,engines['candidate'])
    assert proof['cases']==8 and proof['exit_code']==0
    xml=tmp_path/'evidence/causal-green/pytest.xml'
    import xml.etree.ElementTree as ET
    cases=list(ET.fromstring(xml.read_bytes()).iter('testcase'))
    qualified=[case for case in cases if case.get('name','').startswith('test_mixed_query')]
    assert len(qualified)==4
    expected=hashlib.sha256((engines['candidate']/'_internal/integrations/context/semantic_search.py').read_bytes()).hexdigest()
    assert expected==patch['after_sha256']
    for case in qualified:
        props={p.get('name'):p.get('value') for p in case.findall('properties/property')}
        assert props['qualified_input']=='true'
        assert '613' in json.loads(props['observed_stage_terms'])['body']
