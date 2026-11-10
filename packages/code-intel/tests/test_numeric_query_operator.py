"""Synthetic online controls; never issue any frozen pilot question."""
import base64
import hashlib
import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from eval.quality import numeric_query_experiment as operator
from eval.quality.experiment_evidence import Journal


@pytest.fixture
def git_source(tmp_path):
    from eval.quality.sources import read_tree

    root = tmp_path/'synthetic-git'
    root.mkdir()
    subprocess.run(['git','init','-q',str(root)],check=True)
    (root/'nested').mkdir()
    script = root/'nested/source.py'
    script.write_text('def synthetic_fixture():\n    return 1\n')
    script.chmod(0o755)
    (root/'alias.py').symlink_to('nested/source.py')
    (root/'image.png').write_bytes(b'controlled non-source image')
    (root/'oversized.py').write_bytes(b'#' * 1_000_001)
    subprocess.run(['git','-C',str(root),'add','.'],check=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=Control','-c',
                    'user.email=control@example.invalid','commit','-qm','synthetic'],check=True)
    commit = subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    tree = read_tree(root,commit,tmp_path/'cache',{})
    return root, commit, tree


def test_git_provenance_preserves_complete_tree_and_omission_policy(git_source):
    root, commit, tree = git_source
    proof = operator.git_provenance(root,commit,tree)
    raw = base64.b64decode(proof['raw_commit_base64'])
    assert hashlib.sha1(b'commit '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == commit
    assert raw.splitlines()[0] == b'tree '+proof['root_tree'].encode()
    decoded, visited = {}, set()
    def walk(oid, prefix=''):
        raw = base64.b64decode(proof['raw_trees_base64'][oid])
        assert hashlib.sha1(b'tree '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == oid
        visited.add(oid)
        offset = 0
        while offset < len(raw):
            end = raw.index(b'\0',offset)
            mode,name = raw[offset:end].split(b' ',1)
            child = raw[end+1:end+21].hex()
            path = prefix+os.fsdecode(name)
            if mode == b'40000':
                walk(child,path+'/')
            else:
                decoded[path] = [mode.decode(),child]
            offset = end+21
    walk(proof['root_tree'])
    assert visited == set(proof['raw_trees_base64'])
    assert decoded == {p:[m,o] for p,m,o,_ in proof['entries']}
    assert {p for p in proof['stored_paths']} == {'alias.py','nested/source.py'}
    assert {p for p,_,_,_ in proof['omitted_entries']} == {'image.png','oversized.py'}
    assert decoded['nested/source.py'][0] == '100755' and decoded['alias.py'][0] == '120000'


@pytest.mark.parametrize('corruption',['commit','root','entries'])
def test_git_provenance_rejects_wrong_immutable_binding(git_source, corruption):
    root, commit, tree = git_source
    tree = json.loads(json.dumps(tree))
    if corruption == 'commit':
        commit = tree['tree']  # An existing tree object cannot stand in for a commit.
    elif corruption == 'root':
        tree['tree'] = 'f'*40
    else:
        tree['entries'] = tree['entries'][1:]
    with pytest.raises((AssertionError, subprocess.CalledProcessError)):
        operator.git_provenance(root,commit,tree)


def cases():
    return [{'id':f'control-{i}', 'repo_id':f'repo{i//2}', 'query':f'synthetic control {i}', 'numeric_query':str(610+i),
             'evidence':[]} for i in range(4)]


@pytest.mark.asyncio
async def test_all_primary_requests_precede_every_diagnostic(tmp_path, monkeypatch, record_property):
    journal = Journal(tmp_path/'journal', 2**20)
    report, calls = {}, []
    async def observe(gateway, query, **kwargs):
        events = [json.loads(line) for line in (journal.root/'events.jsonl').read_bytes().splitlines()]
        event = events[-1]
        raw = (journal.root/event['response']['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == event['response']['sha256']
        issue = json.loads(raw)
        assert event['request']['event'] == 'consume_request' and issue['query'] == query
        assert issue['top_k'] == kwargs['top_k'] and issue['max_tokens'] == kwargs['budget']
        calls.append((query, kwargs['top_k'], kwargs['budget'], kwargs['file_filter']))
        return {'response':{'data':{'results':[]}}}
    monkeypatch.setattr(operator, 'observe', observe)
    rows = cases()
    for c in rows:
        c['evidence'] = [{'file':'controlled.py','line':1,'quote':'unmatched'}]
    await operator.collect_pages(rows, {f'repo{i}':object() for i in range(2)}, journal, report, lambda:None)
    assert calls[:4] == [(c['query'],10,2000,'') for c in rows]
    assert len(report['issued']) == len(calls) and len(calls) >= 4
    record_property('qualified_input', 'true')
    assert len(calls) == 16, 'REGRESSION: numeric diagnostic requests were not issued'
    assert calls[4:] == [(q,k,b,f) for c in rows for q,k,b,f in [
        (c['query'],24,8000,''),(c['query'],5,4000,'controlled.py'),
        (c['numeric_query'],10,2000,'')]]
    assert len(report['issued']) == 16
    assert all(set(c['pages']) == {'primary','deep','scoped','numeric'} for c in report['cases'])


@pytest.mark.asyncio
async def test_failed_request_stays_durably_consumed_without_replay(tmp_path, monkeypatch):
    journal = Journal(tmp_path/'journal', 2**20)
    report, calls = {'status':'incomplete','decision':None}, []
    async def observe(gateway, query, **kwargs):
        calls.append(query)
        if len(calls) == 2:
            raise RuntimeError('synthetic response failure')
        return {'response':{'data':{'results':[]}}}
    monkeypatch.setattr(operator, 'observe', observe)
    with pytest.raises(RuntimeError, match='synthetic response failure'):
        await operator.collect_pages(cases(), {f'repo{i}':object() for i in range(2)}, journal, report, lambda:None)
    assert calls == ['synthetic control 0','synthetic control 1']
    assert [(r['id'],r['role']) for r in report['issued']] == [('control-0','primary'),('control-1','primary')]
    assert len((journal.root/'events.jsonl').read_bytes().splitlines()) == 2
    assert set(report['cases'][0]['pages']) == {'primary'} and report['cases'][1]['pages'] == {}
    assert report['status'] == 'incomplete' and report['decision'] is None


@pytest.mark.asyncio
async def test_close_failure_does_not_abandon_other_gateways():
    closed = []
    class Peer:
        def __init__(self, name):self.name=name
        async def close(self):
            closed.append(self.name)
            if self.name == 'one':
                raise RuntimeError('synthetic close error')
    errors = await operator.close_gateways({name:Peer(name) for name in ['one','two','three']})
    assert closed == ['one','two','three']
    assert errors == [{'repo_id':'one','type':'RuntimeError'}]


@pytest.mark.asyncio
async def test_partial_failure_captures_sources_and_closes_all_peers(tmp_path, monkeypatch):
    import attocode_intel.gateway

    from eval.quality import corpus
    from eval.quality.fixture_identity import source_manifest

    repo, root = tmp_path/'operator', tmp_path/'attempt'
    (repo/'eval/quality').mkdir(parents=True)
    (root/'evidence').mkdir(parents=True)
    raw = b'def fixture_helper():\n    return 1\n'
    rows = cases()
    for c in rows:
        c['evidence'] = [{'file':'control.py','line':1,'quote':'def fixture_helper():',
                          'source_sha256':hashlib.sha256(raw).hexdigest()}]
    manifest = {'engine_commit':'0'*40,'cases':rows,
                'repositories':[{'id':f'repo{i}','repo':f'synthetic/repo{i}','commit':'f'*40} for i in range(2)]}
    protocol = {'engine_commit':'0'*40,**{k:{'top_k':v[0],'max_tokens':v[1]} for k,v in operator.ROLES.items()}}
    (repo/'eval/quality/numeric_query_questions.json').write_text(json.dumps(manifest))
    (repo/'eval/quality/numeric_query_protocol.json').write_text(json.dumps(protocol))
    monkeypatch.setattr(operator,'REPO',repo)
    monkeypatch.setattr(operator.subprocess,'run',lambda *a,**k:None)
    monkeypatch.setattr(operator,'assert_engine',lambda _: {'controlled':'origin'})
    monkeypatch.setattr(operator,'engine_identity',lambda:'controlled-engine')
    def materialize(spec, destination, cache, journal):
        (destination/'control.py').write_bytes(raw)
        ref = journal.response({'event':'synthetic_git_control'}, {'fixture':'synthetic'})
        return 'f'*40, source_manifest(destination), ref
    monkeypatch.setattr(operator,'materialize_bound',materialize)
    closed = []
    class Peer:
        def __init__(self, project, *a,**kw):self.project=project
        async def close(self):closed.append(self.project)
    monkeypatch.setattr(attocode_intel.gateway,'OperationGateway',Peer)
    async def ready(*a,**kw):
        data = {'data':{'ranking':{'index':{'status':'ready','body_index_available':True,'body_index_ready':True}}}}
        return SimpleNamespace(isError=False,content=[SimpleNamespace(text=json.dumps(data))]), {}
    monkeypatch.setattr(corpus,'ready_search',ready)
    calls = []
    async def observe(gateway, query, **kwargs):
        calls.append(query)
        raise RuntimeError('synthetic payload error')
    monkeypatch.setattr(operator,'observe',observe)
    with pytest.raises(RuntimeError,match='synthetic payload error'):
        await operator.run_async(root)
    report = json.loads((root/'evidence/pilot.json').read_bytes())
    assert len(closed) == 2 and report['gateways_closed']
    assert report['source_unchanged'] and report['engine_unchanged']
    assert report['status'] == 'incomplete' and report['decision'] is None
    assert calls == ['synthetic control 0'] and len(report['issued']) == 1
    events = [json.loads(line)['request'] for line in (root/'evidence/journal/events.jsonl').read_bytes().splitlines()]
    assert {e['repo_id'] for e in events if e['event']=='source_after'} == {'repo0','repo1'}
    assert sum(e['event']=='gateway_close' for e in events) == 2


@pytest.mark.asyncio
async def test_actual_public_producer_and_raw_source_capture(tmp_path):
    from attocode_intel.gateway import OperationGateway

    from eval.quality.corpus import ready_search
    from eval.quality.corpus_capture import RecordedGateway

    fixture = tmp_path/'fixture'
    fixture.mkdir()
    raw = b'def pilot_public_control():\n    """Synthetic public producer control."""\n    return 1\n'
    path = fixture/'controlled.py'
    path.write_bytes(raw)
    journal = Journal(tmp_path/'journal', 4*2**20)
    gateway = RecordedGateway(OperationGateway(str(fixture),'daily',watch=False),fixture,journal)
    try:
        await ready_search(gateway, {'query':'pilot_control_index_readiness','top_k':1,'max_tokens':2000},timeout=30)
        page = await operator.observe(gateway,'pilot_public_control',top_k=10,budget=2000,capture_generation=True)
        assert any(r['file_path']=='controlled.py' for r in page['response']['data']['results'])
        assert page['generation_diagnostic'] and page['pre_hydration_diagnostic']
    finally:
        await gateway.close()
    assert path.read_bytes() == raw
    events = [json.loads(line) for line in (journal.root/'events.jsonl').read_bytes().splitlines()]
    assert any(e['request']['event']=='source_validation' for e in events)
    for event in events:
        ref = event['response']
        body = (journal.root/ref['path']).read_bytes()
        assert len(body) == ref['bytes'] and hashlib.sha256(body).hexdigest() == ref['sha256']


@pytest.mark.asyncio
async def test_numeric_stage_arguments_are_observed_without_changing_public_output(tmp_path):
    from attocode_intel.gateway import OperationGateway

    from eval.quality.corpus import ready_search
    from eval.quality.corpus_capture import RecordedGateway
    from eval.quality.mcp_search import decode

    fixture = tmp_path/'numeric-control'
    fixture.mkdir()
    raw = b'def synthetic_response_control():\n    marker = 613\n    return marker\n'
    (fixture/'controlled.py').write_bytes(raw)
    journal = Journal(tmp_path/'journal', 4*2**20)
    gateway = RecordedGateway(OperationGateway(str(fixture),'daily',watch=False),fixture,journal)
    try:
        await ready_search(gateway, {'query':'numeric_control_readiness','top_k':1,'max_tokens':2000},timeout=30)
        mixed = await operator.observe(gateway,'synthetic 613 control',top_k=10,budget=2000,capture_generation=True)
        direct = decode(await gateway.execute_mcp('semantic_search', mixed['request']))
        assert mixed['response']['data']['results'] == direct['data']['results']
        stages = {row['stage']:row for row in mixed['generation_diagnostic']}
        assert set(stages) == {'keyword','body','file_bm25'}
        assert '613' not in stages['keyword']['arguments'][0].split()
        assert '613' not in stages['body']['arguments'][0]
        assert '613' not in stages['file_bm25']['arguments'][0]
        numeric = await operator.observe(gateway,'613',top_k=10,budget=2000,capture_generation=True)
        stages = {row['stage']:row for row in numeric['generation_diagnostic']}
        assert stages['keyword']['arguments'][0] == '613'
        assert stages['body']['arguments'][0] == ['613']
        assert stages['file_bm25']['arguments'][0] == ['613']
        assert any(row['file_path']=='controlled.py' for row in numeric['response']['data']['results'])
    finally:
        await gateway.close()
    assert (fixture/'controlled.py').read_bytes() == raw
