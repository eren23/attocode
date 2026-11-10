"""One source-exposed diagnostic; immutable inputs and no candidate comparison."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import patch

from eval.quality.corpus_capture import RecordedGateway, digest
from eval.quality.experiment_evidence import Journal, assert_engine
from eval.quality.fixture_identity import source_manifest
from eval.quality.mcp_search import decode, engine_identity, evidence_hits, observe
from eval.quality.runner import REPO, write_json

SENTINEL = 'numeric_query_readiness_control_20261110'
ROLES = {'primary': (10, 2000), 'deep': (24, 8000), 'scoped': (5, 4000), 'numeric': (10, 2000)}


def git_provenance(source, commit, tree):
    """Retain immutable Git objects before the acquisition clone is removed."""
    def git(*args):
        return subprocess.check_output(['git', '-C', str(source), *args])
    def object_id(kind, raw):
        return hashlib.sha1(kind.encode()+b' '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    raw_commit = git('cat-file', 'commit', commit)
    assert object_id('commit', raw_commit) == commit
    root_tree = raw_commit.splitlines()[0].decode().removeprefix('tree ')
    assert root_tree == tree['tree']
    listing = git('ls-tree', '-r', '-t', '-z', commit)
    tree_ids, entries = {root_tree}, {}
    for record in listing.split(b'\0'):
        if record:
            metadata, path = record.split(b'\t', 1)
            mode, kind, oid = metadata.decode().split()
            if kind == 'tree':
                tree_ids.add(oid)
            else:
                entries[os.fsdecode(path)] = [mode, oid]
    assert entries == {p:[m,o] for p,m,o,_ in tree['entries']}
    objects = {}
    for oid in sorted(tree_ids):
        raw = git('cat-file', 'tree', oid)
        assert object_id('tree', raw) == oid
        objects[oid] = base64.b64encode(raw).decode()
    from eval.matrix.run import _stored
    return {'commit':commit, 'root_tree':root_tree,
            'raw_commit_base64':base64.b64encode(raw_commit).decode(),
            'raw_trees_base64':objects, 'entries':tree['entries'],
            'stored_paths':[e[0] for e in tree['entries'] if _stored(e)],
            'omitted_entries':[e for e in tree['entries'] if not _stored(e)],
            'policy':'Unchanged matrix._stored: symlinks; regular100644/100755 files0..1MB excluding SKIP_EXTENSIONS/SKIP_FILENAMES. Unavailable oversized blobs and submodules omitted; ordinary discovery applies further exclusions.',
            'materialized_modes':'Original Git modes retained here; helper materializes regular bytes without preserving executable bits. Source is never executed.'}


def materialize_bound(spec, fixture, cache, journal):
    from eval.quality import corpus
    original, captures = corpus.read_tree, []
    def capture(source, commit, cache, recipe, *, remote=False):
        tree = original(source, commit, cache, recipe, remote=remote)
        proof = git_provenance(source, commit, tree)
        captures.append(journal.response({'event':'git_provenance','repo_id':spec['id']}, proof))
        return tree
    pinned = {}
    with patch.object(corpus, 'read_tree', capture):
        tree = corpus.materialize(spec, fixture, cache, receipt=pinned)
    assert len(captures) == 1, 'Expected one owned immutable Git acquisition'
    return tree, pinned, captures[0]


async def collect_pages(cases, gateways, journal, report, checkpoint):
    """Global primary barrier; fsync every role's issue before its request."""
    rows = {c['id']: {**c, 'pages': {}} for c in cases}
    report['cases'] = list(rows.values())
    phases = [[(c, 'primary') for c in cases],
              [(c, role) for c in cases for role in ['deep', 'scoped', 'numeric']]]
    for phase in phases:
        for case, role in phase:
            top_k, budget = ROLES[role]
            file_filter = case['evidence'][0]['file'] if role == 'scoped' else ''
            query = case['numeric_query'] if role == 'numeric' else case['query']
            arguments = {'query': query, 'top_k': top_k, 'max_tokens': budget,
                         'mode': 'auto', 'file_filter': file_filter}
            ref = journal.response({'event': 'consume_request', 'id': case['id'],
                                    'repo_id': case['repo_id'], 'role': role}, arguments)
            report.setdefault('issued', []).append({'id': case['id'], 'role': role, 'ref': ref})
            checkpoint()
            page = await observe(gateways[case['repo_id']], query, top_k=top_k,
                                 budget=budget, file_filter=file_filter, capture_generation=True)
            page['hits'] = evidence_hits(page['response']['data']['results'], case['evidence'])
            rows[case['id']]['pages'][role] = page
            checkpoint()


async def close_gateways(gateways):
    """Close every opened peer even when another peer's close fails."""
    errors = []
    for name, gateway in gateways.items():
        try:
            await gateway.close()
        except BaseException as error:
            errors.append({'repo_id': name, 'type': type(error).__name__})
    return errors


async def run_async(root):
    from attocode_intel.gateway import OperationGateway

    from eval.quality import corpus

    questions_path = REPO/'eval/quality/numeric_query_questions.json'
    protocol_path = REPO/'eval/quality/numeric_query_protocol.json'
    manifest = json.loads(questions_path.read_bytes())
    protocol = json.loads(protocol_path.read_bytes())
    assert manifest['engine_commit'] == protocol['engine_commit']
    assert all((protocol[role]['top_k'], protocol[role]['max_tokens']) == values
               for role, values in ROLES.items())
    baseline = manifest['engine_commit']
    # Dispatcher registration and this diagnostic may differ; selected product
    # and all existing capture/materialization helpers must equal released33.
    subprocess.run(['git', 'diff', '--quiet', baseline, 'HEAD', '--',
                    'packages/code-intel/src', 'packages/code-intel/pyproject.toml', 'uv.lock',
                    'eval/matrix', 'eval/quality/mcp_search.py', 'eval/quality/corpus.py',
                    'eval/quality/corpus_capture.py', 'eval/quality/experiment_evidence.py',
                    'eval/quality/fixture_identity.py', 'eval/quality/sources.py',
                    'eval/quality/runner.py'], cwd=REPO, check=True)
    assert len(manifest['cases']) == 4 and len(manifest['repositories']) == 2
    assert len({c['id'] for c in manifest['cases']}) == 4
    assert all(sum(c['repo_id'] == r['id'] for c in manifest['cases']) == 2
               for r in manifest['repositories'])
    engine = REPO/'packages/code-intel/src/attocode_intel'
    evidence = root/'evidence'
    journal = Journal(evidence/'journal', 48 * 2**20)
    report = {'status': 'incomplete', 'decision': None, 'engine_commit': baseline,
              'questions_sha256': hashlib.sha256(questions_path.read_bytes()).hexdigest(),
              'protocol_sha256': hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
              'sentinel': SENTINEL, 'cases': [], 'issued': [], 'repositories': []}
    write_json(evidence/'questions.json', manifest)
    write_json(evidence/'protocol.json', protocol)
    def checkpoint():
        write_json(evidence/'pilot.json', report)
    checkpoint()
    engine_hash = engine_identity()
    journal.response({'event': 'engine_before'}, {'origins': assert_engine(engine), 'sha256': engine_hash})
    # No historical or shared fixture cache is consulted on the runner.
    old_sources = corpus.HISTORY, corpus.CLONES
    corpus.HISTORY, corpus.CLONES = root/'cache/history', root/'cache/unavailable-clones'
    fixtures, inventories, gateways = {}, {}, {}
    try:
        for spec in manifest['repositories']:
            name = spec['id']
            assert name and all(c.isalnum() or c in '-_' for c in name)
            fixture = root/'work/fixtures'/name
            fixture.mkdir(parents=True, exist_ok=False)
            fixtures[name] = fixture
            tree, pinned, git_ref = materialize_bound(spec, fixture, root/'cache/sources', journal)
            inventory = source_manifest(fixture)
            assert inventory == pinned and not (fixture/'.attocode').exists()
            inventories[name] = inventory
            for case in [c for c in manifest['cases'] if c['repo_id'] == name]:
                for witness in case['evidence']:
                    source = fixture/witness['file']
                    assert source.resolve().is_relative_to(fixture.resolve())
                    raw = source.read_bytes()
                    assert hashlib.sha256(raw).hexdigest() == witness['source_sha256']
                    assert raw.decode().splitlines()[witness['line']-1] == witness['quote']
            for path, entry in inventory.items():
                if entry['kind'] == 'file':
                    raw = (fixture/path).read_bytes()
                    assert all(c['query'].encode() not in raw for c in manifest['cases'])
            with tarfile.open(evidence/('source-'+name+'.tar'), 'w') as archive:
                for path in sorted(inventory):
                    archive.add(fixture/path, arcname=path, recursive=False)
            journal.response({'event': 'source_before', 'repo_id': name,
                              'repo': spec['repo'], 'commit': spec['commit'], 'tree': tree}, inventory)
            row = {**spec, 'tree': tree, 'source_inventory_sha256': digest(inventory),
                   'source_files': len(inventory), 'git_provenance_ref':git_ref}
            report['repositories'].append(row)
            row['gateway_generation'] = len(gateways)
            gateway = RecordedGateway(OperationGateway(str(fixture), 'daily', watch=False),
                                      fixture, journal, generation=row['gateway_generation'])
            gateways[name] = gateway
            response, warmup = await corpus.ready_search(gateway, {
                'query': SENTINEL, 'top_k': 1, 'max_tokens': 2000}, timeout=180)
            index = decode(response)['data']['ranking']['index']
            assert index['status'] == 'ready' and index['body_index_available'] and index['body_index_ready']
            row.update(warmup=warmup, index=index)
            checkpoint()
        await collect_pages(manifest['cases'], gateways, journal, report, checkpoint)
        assert len(report['issued']) == 16
        assert all(set(c['pages']) == set(ROLES) for c in report['cases'])
    finally:
        corpus.HISTORY, corpus.CLONES = old_sources
        errors = await close_gateways(gateways)
        report['gateway_close_errors'] = errors
        report['gateways_closed'] = not errors
        source_ok = True
        for name, before in inventories.items():
            after = source_manifest(fixtures[name])
            journal.response({'event': 'source_after', 'repo_id': name}, after)
            source_ok = source_ok and before == after
        report['source_unchanged'] = source_ok
        after_hash = engine_identity()
        journal.response({'event': 'engine_after'}, {'origins': assert_engine(engine), 'sha256': after_hash})
        report['engine_unchanged'] = after_hash == engine_hash
        checkpoint()
        assert not errors and source_ok and report['engine_unchanged']
    report['status'] = 'complete'
    checkpoint()


def run(root):
    assert os.environ.get('GITHUB_ACTIONS') == 'true', 'Runtime only in GitHub Actions'
    asyncio.run(run_async(Path(root)))
