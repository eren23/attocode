"""Frozen two-repository baseline diagnostic; no production candidate."""
from __future__ import annotations
import asyncio
import base64
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time
import traceback
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from eval.quality.corpus_capture import RecordedGateway, digest
from eval.quality.experiment_evidence import Journal, assert_engine
from eval.quality.fixture_identity import source_manifest
from eval.quality.mcp_search import decode, engine_identity, observe
from eval.quality.runner import REPO, write_json

ROLES = {'primary': (10, 2000), 'deep': (24, 8000), 'scoped': (5, 4000)}
SENTINEL = 'body_row_eligibility_readiness_control_20261122'

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

async def close_gateways(gateways):
    """Close every opened peer even when another peer's close fails."""
    errors = []
    for name, gateway in gateways.items():
        try:
            await gateway.close()
        except BaseException as error:
            errors.append({'repo_id': name, 'type': type(error).__name__})
    return errors


def execution_role(ref):
    allowed = {'refs/heads/diagnose/body-row-eligibility-controls-0139': 'controls',
               'refs/heads/diagnose/body-row-eligibility-real-0139': 'real'}
    if ref not in allowed:
        raise ValueError('unfrozen diagnostic invocation')
    return allowed[ref]


def validate_witness(root, witness):
    root = Path(root).resolve()
    path = (root / witness['file']).resolve()
    if not path.is_relative_to(root):
        raise ValueError('witness outside fixture')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != witness['source_sha256']:
        raise ValueError('witness source identity mismatch')
    first, last = witness['start_line'], witness['end_line']
    if '\n'.join(raw.decode().splitlines()[first - 1:last]) != witness['quote']:
        raise ValueError('witness source coordinates mismatch')
    return raw


def evidence_flags(case, hits):
    witnesses = case['evidence']
    complete = bool(witnesses) and all(any(
        hit['file_path'] == w['file'] and w['quote'] in hit.get('snippet', '')
        and 0 < (hit.get('snippet_start_line') or 0) <= w['start_line']
        <= w['end_line'] <= (hit.get('snippet_end_line') or 0)
        for hit in hits) for w in witnesses)
    targets = [case['target'], *case.get('accepted_equivalent_implementation_locations', [])]
    direct = any(hit['file_path'] == target['file']
                 and hit.get('name') in {target['symbol'], target['symbol'].split('.')[-1]}
                 and target['start_line'] <= (hit.get('line') or 0)
                 <= (hit.get('end_line') or 0) <= target['end_line']
                 for target in targets for hit in hits)
    return {'target_file': any(h['file_path'] == case['target']['file'] for h in hits),
            'complete_quotes': complete, 'direct_location': direct}


def admit_rows(rows, top_k):
    owners, primary, additional = set(), [], []
    for row in rows:
        owner = tuple(row[:3])
        (additional if owner in owners else primary).append(row)
        owners.add(owner)
    selected, seen, counts = [], set(), Counter()
    stats = {'per_file_rejected': 0, 'duplicate_key_rejected': 0,
             'owner_deferred': len(additional), 'stopped_at_top_k': False}
    for row in primary + additional:
        key = tuple(row[:5])
        if key in seen:
            stats['duplicate_key_rejected'] += 1
            continue
        if counts[row[0]] >= 8:
            stats['per_file_rejected'] += 1
            continue
        selected.append(row); seen.add(key); counts[row[0]] += 1
        if len(selected) >= top_k:
            stats['stopped_at_top_k'] = True
            break
    stats['underfilled'] = len(selected) < top_k
    return selected, stats


def target_rows(case, prefix, expanded, top_k):
    original, _ = admit_rows(prefix, top_k)
    # Preserve occurrence ordinal through the unchanged admission algorithm;
    # equal prefix/tail values must not relabel the selected prefix occurrence.
    indexed = [list(row) + [i] for i, row in enumerate(expanded, 1)]
    selected, _ = admit_rows(indexed, top_k)
    def carries(row):
        return all(row[0] == w['file'] and row[3] <= w['start_line'] <= w['end_line'] <= row[4]
                   and w['quote'] in row[5] for w in case['evidence'])
    bound = [{'ordinal': row[-1], 'row': row[:-1]}
             for row in selected if row[-1] > len(prefix) and carries(row)]
    return {'original_target_file_absent': not any(r[0] == case['target']['file'] for r in original),
            'post_prefix_admitted_target_rows': bound}


def index_inventory(manager, root, target_paths):
    from attocode_intel._internal.integrations.context.codebase_context import CodebaseContextManager
    root = Path(root).resolve()
    context = CodebaseContextManager(str(root), max_files=manager.max_files)
    context.discover_files()
    discovered, expected_kw, expected_body = [], {}, {}
    for file in context._files:
        path = Path(file.path).resolve()
        if not path.is_relative_to(root):
            raise ValueError('discovered source outside fixture')
        info = path.stat()
        discovered.append({'path': file.relative_path, 'mtime': info.st_mtime,
                           'mtime_ns': info.st_mtime_ns, 'bytes': info.st_size})
        expected_kw[file.relative_path] = info.st_mtime
        if info.st_size <= 512 * 1024:
            expected_body[file.relative_path] = [info.st_mtime_ns, info.st_size]
    connection = manager._open_body_db()
    try:
        kw = dict(connection.execute('SELECT file_path,mtime FROM kw_files ORDER BY file_path'))
        body = {p: [m, s] for p, m, s in connection.execute('SELECT file_path,mtime_ns,size FROM body_files ORDER BY file_path')}
    finally:
        connection.close()
    return {'discovery': discovered, 'discovery_truncated': context.discovery_truncated,
            'expected_keyword': expected_kw, 'expected_body': expected_body,
            'actual_keyword': kw, 'actual_body': body, 'keyword_complete_current': kw == expected_kw,
            'body_complete_current': body == expected_body,
            'targets_indexed': all(p in kw and p in body for p in target_paths),
            'body_policy': 'contained discovered paths, readable current stat, <=512KiB; all other discovered paths stay keyword metadata only'}


class RawCursor:
    def __init__(self, cursor, callback, sql, parameters):
        self.cursor, self.callback, self.sql, self.parameters = cursor, callback, sql, list(parameters)
    def fetchall(self):
        rows = self.cursor.fetchall()
        self.callback(self.sql, self.parameters, [list(row) for row in rows])
        return rows
    def __getattr__(self, name):
        return getattr(self.cursor, name)


class RawConnection:
    def __init__(self, connection, callback):
        self.connection, self.callback = connection, callback
    def execute(self, sql, parameters=()):
        cursor = self.connection.execute(sql, parameters)
        if sql.startswith('SELECT body_fts.file_path, chunk_type, name, start_line, end_line, '):
            return RawCursor(cursor, self.callback, sql, parameters)
        return cursor
    def __getattr__(self, name):
        return getattr(self.connection, name)


async def observe_page(peer, case, role, pending):
    from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager
    original_open = SemanticSearchManager._open_body_db
    pending['raw_sql_refs'] = []
    pending['raw_sql_stats_refs'] = []
    def capture(sql, parameters, rows):
        ref = peer.journal.response({'event': 'body_sql_rows', 'id': case['id'], 'role': role},
                                   {'sql': sql, 'parameters': parameters, 'rows': rows})
        pending['raw_sql_refs'].append(ref)
        stats = {}
        for row in rows:
            path = (peer.root / row[0]).resolve()
            if not path.is_relative_to(peer.root.resolve()):
                raise ValueError('raw SQL path outside fixture')
            info = path.stat(); stats[row[0]] = [info.st_mtime_ns, info.st_size]
        ref = peer.journal.response({'event': 'body_sql_source_stats', 'id': case['id'], 'role': role}, stats)
        pending['raw_sql_stats_refs'].append(ref)
    def opened(manager):
        connection = original_open(manager)
        return RawConnection(connection, capture) if connection is not None else None
    top_k, budget = ROLES[role]
    scope = case['target']['file'] if role == 'scoped' else ''
    with patch.object(SemanticSearchManager, '_open_body_db', opened):
        page = await observe(peer, case['query'], top_k=top_k, budget=budget,
                             file_filter=scope, mode='auto', capture_generation=True)
    pending.update(page)
    pending['flags'] = evidence_flags(case, page['response']['data']['results'])


async def collect_pages(cases, gateways, journal, report, checkpoint, *, observer=None):
    observer = observer or observe_page
    rows = {case['id']: {**case, 'pages': {}} for case in cases}
    report['cases'] = list(rows.values())
    phases = [[(case, 'primary') for case in cases],
              [(case, role) for case in cases for role in ('deep', 'scoped')]]
    for phase in phases:
        for case, role in phase:
            top_k, budget = ROLES[role]
            request = {'query': case['query'], 'top_k': top_k, 'max_tokens': budget,
                       'mode': 'auto', 'file_filter': case['target']['file'] if role == 'scoped' else ''}
            ref = journal.response({'event': 'consume_request', 'id': case['id'],
                                    'repo_id': case['repo_id'], 'role': role}, request)
            report.setdefault('issued', []).append({'id': case['id'], 'role': role, 'ref': ref})
            pending = rows[case['id']]['pages'][role] = {'request': request}
            checkpoint()
            try:
                await observer(gateways[case['repo_id']], case, role, pending)
            finally:
                checkpoint()


def read_ref(journal, ref):
    raw = (journal.root / ref['path']).read_bytes()
    assert len(raw) == ref['bytes'] and hashlib.sha256(raw).hexdigest() == ref['sha256']
    return json.loads(raw)


async def diagnose_primary(case, peer, journal, report, checkpoint):
    primary = case['pages']['primary']
    assert len(primary['raw_sql_refs']) == 1
    captured = read_ref(journal, primary['raw_sql_refs'][0])
    assert len(primary['raw_sql_stats_refs']) == 1
    captured_stats = read_ref(journal, primary['raw_sql_stats_refs'][0])
    real = peer.peer
    key = next(iter(real._stores))
    manager = real._stores[key]['service']._get_semantic_search()
    body_stage = next(s for s in primary['generation_diagnostic'] if s['stage'] == 'body')
    top_k = body_stage['arguments'][1]
    def diagnostic():
        connection = manager._open_body_db()
        try:
            parameters = list(captured['parameters']); parameters[-1] = 2048
            rows = [list(r) for r in connection.execute(captured['sql'], parameters).fetchall()]
            ref = journal.response({'event': 'bounded_body_enumeration', 'id': case['id']},
                                   {'sql': captured['sql'], 'parameters': parameters, 'rows': rows})
            primary['bounded_body_ref'] = ref
            stats = {}
            for row in rows:
                path = (peer.root / row[0]).resolve()
                assert path.is_relative_to(peer.root.resolve())
                info = path.stat(); stats[row[0]] = [info.st_mtime_ns, info.st_size]
                assert stats[row[0]] == row[7:9]
            stats_ref = journal.response({'event': 'bounded_body_source_stats', 'id': case['id']}, stats)
            primary['bounded_body_stats_ref'] = stats_ref
            return rows, stats, parameters
        finally:
            connection.close()
    rows, stats, parameters = await asyncio.get_running_loop().run_in_executor(real._workers[key], diagnostic)
    assert rows[:len(captured['rows'])] == captured['rows']
    assert all(captured_stats[r[0]] == r[7:9] for r in captured['rows'])
    prefix_selected, prefix_counts = admit_rows(captured['rows'], top_k)
    expanded_selected, expanded_counts = admit_rows(rows, top_k)
    stage_keys = [(r['file'], r['kind'], r['name'], r['start'], r['end']) for r in body_stage['results']]
    assert stage_keys == [tuple(r[:5]) for r in prefix_selected]
    bound_targets = target_rows(case, captured['rows'], rows, top_k)
    other_files = set()
    for stage in primary['generation_diagnostic']:
        if stage['stage'] in {'keyword', 'file_bm25'}:
            other_files.update(r if isinstance(r, str) else r['file'] for r in stage['results'])
    tests = {'original_raw_saturated': len(captured['rows']) == captured['parameters'][-1],
             'original_producer_underfilled': prefix_counts['underfilled'],
             'actual_per_file_rejections': prefix_counts['per_file_rejected'] > 0,
             'original_body_target_file_absent': bound_targets['original_target_file_absent'],
             'same_post_prefix_target_admitted_within_output_budget': bool(bound_targets['post_prefix_admitted_target_rows']),
             'no_keyword_or_whole_file_target': case['target']['file'] not in other_files,
             'primary_not_complete_quotes': not primary['flags']['complete_quotes'],
             'primary_no_direct_location': not primary['flags']['direct_location'],
             'scoped_recovered': case['pages']['scoped']['flags']['complete_quotes']}
    case['mechanism'] = {'tests': tests, 'automatic_eligible_signal': all(tests.values()),
                         'prefix_admission': prefix_counts, 'expanded_admission': expanded_counts,
                         'bound_targets': bound_targets,
                         'bounded_enumeration_saturated': len(rows) == 2048,
                         'manual_actionability_and_equivalents_required': True}
    checkpoint()


async def run_async(root, output):
    import attocode_intel
    from attocode_intel.gateway import OperationGateway
    from eval.quality import corpus
    questions_path = REPO / 'eval/quality/body_row_questions.json'
    protocol_path = REPO / 'eval/quality/body_row_protocol.json'
    manifest = json.loads(questions_path.read_bytes()); protocol = json.loads(protocol_path.read_bytes())
    baseline = manifest['engine_commit']
    assert baseline == protocol['engine_commit'] == 'ed74f9a6f2190186e2e59a4435860ed7a4a9fd7d'
    assert len(manifest['cases']) == 4 and len(manifest['repositories']) == 2
    assert len({c['id'] for c in manifest['cases']}) == 4
    assert all(sum(c['repo_id'] == r['id'] for c in manifest['cases']) == 2 for r in manifest['repositories'])
    assert all((protocol[r]['top_k'], protocol[r]['max_tokens']) == values for r, values in ROLES.items())
    subprocess.run(['git', 'diff', '--quiet', baseline, 'HEAD', '--', 'packages/code-intel', 'uv.lock',
                    'eval/matrix', 'eval/quality/mcp_search.py', 'eval/quality/corpus.py',
                    'eval/quality/corpus_capture.py', 'eval/quality/experiment_evidence.py',
                    'eval/quality/fixture_identity.py', 'eval/quality/sources.py', 'eval/quality/runner.py'], check=True)
    journal = Journal(output / 'journal', 48 * 2**20)
    report = {'status': 'incomplete', 'decision': None, 'engine_commit': baseline,
              'questions_sha256': hashlib.sha256(questions_path.read_bytes()).hexdigest(),
              'protocol_sha256': hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
              'sentinel': SENTINEL, 'cases': [], 'issued': [], 'repositories': []}
    write_json(output / 'questions.json', manifest); write_json(output / 'protocol.json', protocol)
    def checkpoint(): write_json(output / 'pilot.json', report)
    checkpoint()
    package_root = Path(attocode_intel.__file__).resolve().parent
    journal.response({'event': 'installed_origins_before'}, assert_engine(package_root))
    before_engine = engine_identity()
    old_sources = corpus.HISTORY, corpus.CLONES
    corpus.HISTORY, corpus.CLONES = root / 'cache/empty-history', root / 'cache/empty-clones'
    fixtures, inventories, gateways = {}, {}, {}
    try:
        for spec in manifest['repositories']:
            name = spec['id']; fixture = root / 'fixtures' / name
            fixture.mkdir(parents=True, exist_ok=False); fixtures[name] = fixture
            tree, pinned, git_ref = materialize_bound(spec, fixture, root / 'cache/sources', journal)
            assert tree == spec['tree']
            inventory = source_manifest(fixture); assert inventory == pinned
            assert all((fixture / path).resolve().is_relative_to(fixture.resolve())
                       for path, entry in inventory.items() if entry['kind'] == 'symlink')
            inventories[name] = inventory
            for case in [c for c in manifest['cases'] if c['repo_id'] == name]:
                for witness in case['evidence']: validate_witness(fixture, witness)
            with tarfile.open(output / ('source-' + name + '.tar.gz'), 'w:gz') as archive:
                for path in sorted(inventory): archive.add(fixture / path, arcname=path, recursive=False)
            journal.response({'event': 'source_before', 'repo_id': name, 'tree': tree}, inventory)
            row = {**spec, 'source_inventory_sha256': digest(inventory), 'source_files': len(inventory),
                   'git_provenance_ref': git_ref}
            report['repositories'].append(row)
            peer = RecordedGateway(OperationGateway(str(fixture), 'daily', watch=False), fixture, journal,
                                   generation=len(gateways))
            gateways[name] = peer
            response, warmup = await corpus.ready_search(peer, {
                'query': SENTINEL, 'top_k': 1, 'max_tokens': 2000, 'mode': 'auto'}, timeout=180)
            index = decode(response)['data']['ranking']['index']
            assert index['status'] == 'ready' and index['body_index_available'] and index['body_index_ready']
            assert not index['discovery_truncated']
            row.update(warmup=warmup, index=index); checkpoint()
            real = peer.peer; key = next(iter(real._stores))
            manager = real._stores[key]['service']._get_semantic_search()
            targets = [c['target']['file'] for c in manifest['cases'] if c['repo_id'] == name]
            indexed = await asyncio.get_running_loop().run_in_executor(
                real._workers[key], lambda: index_inventory(manager, fixture, targets))
            row['index_inventory_ref'] = journal.response({'event': 'complete_index_inventory', 'repo_id': name}, indexed)
            checkpoint()
            assert (not indexed['discovery_truncated'] and indexed['keyword_complete_current']
                    and indexed['body_complete_current'] and indexed['targets_indexed'])
        await collect_pages(manifest['cases'], gateways, journal, report, checkpoint)
        assert len(report['issued']) == 12
        for case in report['cases']:
            await diagnose_primary(case, gateways[case['repo_id']], journal, report, checkpoint)
        report['automatic_signal_ids'] = [c['id'] for c in report['cases'] if c['mechanism']['automatic_eligible_signal']]
    except BaseException:
        report['error'] = traceback.format_exc(); checkpoint()
        raise
    finally:
        corpus.HISTORY, corpus.CLONES = old_sources
        errors = await close_gateways(gateways)
        report['gateway_close_errors'] = errors; report['gateways_closed'] = not errors
        source_ok = True
        for name, before in inventories.items():
            after = source_manifest(fixtures[name]); source_ok = source_ok and before == after
            journal.response({'event': 'source_after', 'repo_id': name}, after)
        report['source_unchanged'] = source_ok
        journal.response({'event': 'installed_origins_after'}, assert_engine(package_root))
        report['engine_unchanged'] = engine_identity() == before_engine
        checkpoint()
        assert not errors and source_ok and report['engine_unchanged']
    report['status'] = 'complete'; checkpoint()


def supervise_run(output):
    import shutil
    import tempfile
    from eval.quality.runner import supervise
    assert execution_role(os.environ['GITHUB_REF']) == 'real'
    assert os.environ['GITHUB_ACTIONS'] == 'true' and os.environ['GITHUB_RUN_ATTEMPT'] == '1'
    output.mkdir(parents=True, exist_ok=False)
    root = Path(tempfile.mkdtemp(prefix='body-row-real-', dir=os.environ['TMPDIR']))
    (root / 'tmp').mkdir()
    evidence = root / 'evidence'; evidence.mkdir()
    env = dict(os.environ, TMPDIR=str(root / 'tmp'), PYTHONPATH=str(REPO),
               QUALITY_ALLOW_DOWNLOADS='1', ATTOCODE_INTEL_MAX_FILES='10000')
    report = {}
    try:
        report = supervise([sys.executable, str(Path(__file__).resolve()), '--worker', str(root), str(evidence)],
                           cwd=REPO, env=env, root=root, log=evidence / 'worker.log',
                           deadline=time.monotonic() + 900, max_bytes=2 * 1024**3, max_rss=2 * 1024**3,
                           include_controller=True, evidence_root=evidence, max_evidence_bytes=64 * 1024**2)
    finally:
        # All payload inputs, evidence and logs were counted under one root.
        # Reclaim inputs before copying the bounded retained evidence for upload.
        for name in ('fixtures', 'cache', 'tmp'):
            if (root / name).exists(): shutil.rmtree(root / name)
        shutil.copytree(evidence, output, dirs_exist_ok=True)
        shutil.rmtree(root)
        report['owned_root_removed'] = not root.exists()
        write_json(output / 'supervision.json', report)
    assert report.get('status') == 'passed' and report.get('cleanup_verified') and report['owned_root_removed'], report


if __name__ == '__main__':
    if sys.argv[1] == '--worker':
        assert os.environ.get('GITHUB_ACTIONS') == 'true'
        asyncio.run(run_async(Path(sys.argv[2]), Path(sys.argv[3])))
    else:
        supervise_run(Path(sys.argv[1]))
