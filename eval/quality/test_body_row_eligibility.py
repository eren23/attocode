"""Prospective operator controls; execute only in GitHub Actions."""
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from eval.quality.body_row_eligibility import (
    RawConnection, admit_rows, close_gateways, collect_pages, evidence_flags,
    execution_role, git_provenance, validate_witness,
    supervise_run,
    target_rows, index_inventory, diagnose_primary,
)
from eval.quality.experiment_evidence import Journal
from eval.quality.corpus_capture import journal_events
from eval.quality.body_row_control_gate import admit_controls


def test_raw_capture_delegates_original_sql_parameters_and_rows(tmp_path):
    conn = sqlite3.connect(tmp_path / 'index.db')
    conn.execute('CREATE TABLE body_fts(file_path, chunk_type, name, start_line, end_line, body)')
    conn.execute("INSERT INTO body_fts VALUES('a.py','function','f',1,2,'literal')")
    sql = 'SELECT body_fts.file_path, chunk_type, name, start_line, end_line, body FROM body_fts WHERE file_path=?'
    recorded = []
    proxy = RawConnection(conn, lambda sql, params, rows: recorded.append((sql, params, rows)))
    rows = proxy.execute(sql, ('a.py',)).fetchall()
    assert rows == [('a.py', 'function', 'f', 1, 2, 'literal')]
    assert recorded == [(sql, ['a.py'], [list(rows[0])])]
    assert conn.execute('SELECT count(*) FROM body_fts').fetchone()[0] == 1
    proxy.close()


def test_bounded_reconstruction_preserves_owner_priority_and_counts_file_rejects():
    def row(path, name, line): return [path, 'function', name, line, line, 'evidence', -1.0, 7, 9]
    raw = [row('a.py', 'f', n) for n in range(1, 17)] + [row('a.py', 'g', 30), row('b.py', 'h', 1)]
    selected, stats = admit_rows(raw, 72)
    assert [(r[0], r[2]) for r in selected[:3]] == [('a.py', 'f'), ('a.py', 'g'), ('b.py', 'h')]
    assert len(selected) == 9 and stats['per_file_rejected'] == 9
    assert stats['duplicate_key_rejected'] == 0 and stats['underfilled']
    selected, stats = admit_rows(raw, 2)
    assert len(selected) == 2 and not stats['underfilled'] and stats['stopped_at_top_k']


def test_target_already_admitted_cannot_be_attributed_to_raw_limit():
    case = {'target': {'file': 'b.py'}, 'evidence': [{'file': 'b.py', 'start_line': 1, 'end_line': 1, 'quote': 'effect'}]}
    row = ['b.py', 'function', 'f', 1, 1, 'effect', -1., 7, 9]
    result = target_rows(case, [row], [row, list(row)], 72)
    assert not result['original_target_file_absent']
    assert not result['post_prefix_admitted_target_rows']


def test_specific_post_prefix_target_must_itself_survive_admission():
    case = {'target': {'file': 'b.py'}, 'evidence': [{'file': 'b.py', 'start_line': 9, 'end_line': 9, 'quote': 'effect'}]}
    def row(line): return ['b.py', 'function', 'f', line, line, 'effect', -1., 7, 9]
    result = target_rows(case, [row(n) for n in range(1, 9)], [row(n) for n in range(1, 10)], 72)
    assert not result['post_prefix_admitted_target_rows']


@pytest.mark.asyncio
async def test_installed_auto_observer_passivity_and_complete_index_oracle(tmp_path):
    import hashlib
    from attocode_intel.gateway import OperationGateway
    from eval.quality.corpus_capture import RecordedGateway
    from eval.quality.mcp_search import decode, observe
    from eval.quality.runner import write_json
    root = tmp_path / 'fixture'; root.mkdir()
    unit = 'def execute(value):\n    return "sapphire quartz"\n\n'
    (root / 'a.py').write_text(unit * 16); (root / 'b.py').write_text(unit)
    output = Path(os.environ.get('BODY_ELIGIBILITY_CONTROL_EVIDENCE', str(tmp_path / 'retained')))
    (output / 'source').mkdir(parents=True)
    for name in ('a.py', 'b.py'): (output / 'source' / name).write_bytes((root / name).read_bytes())
    journal = Journal(output / 'journal', 8 * 1024**2)
    peer = RecordedGateway(OperationGateway(str(root), 'daily', watch=False), root, journal)
    case = {'id': 'synthetic-control', 'repo_id': 'control', 'query': 'sapphire quartz',
            'target': {'file': 'b.py', 'symbol': 'execute', 'start_line': 1, 'end_line': 2},
            'evidence': [{'file': 'b.py', 'start_line': 2, 'end_line': 2,
                          'quote': '    return "sapphire quartz"', 'source_sha256': hashlib.sha256(unit.encode()).hexdigest()}]}
    report = {}
    try:
        decode(await peer.execute_mcp('semantic_search', {'query': 'synthetic readiness control', 'top_k': 1, 'max_tokens': 2000}))
        real = peer.peer; key = next(iter(real._stores)); manager = real._stores[key]['service']._get_semantic_search()
        assert await asyncio.get_running_loop().run_in_executor(real._workers[key], lambda: manager.wait_for_body_index(timeout=30))
        await collect_pages([case], {'control': peer}, journal, report,
                            lambda: write_json(output / 'control.json', report))
        observed = report['cases'][0]
        await diagnose_primary(observed, peer, journal, report, lambda: write_json(output / 'control.json', report))
        plain = await observe(peer, case['query'], top_k=10, budget=2000, mode='auto', capture_generation=True)
        assert plain['response']['data'] == observed['pages']['primary']['response']['data']
        assert plain['generation_diagnostic'] == observed['pages']['primary']['generation_diagnostic']
        # No SourceTracker, rank/producer or SQL wrappers on this direct call.
        direct = await real.execute_mcp('semantic_search', observed['pages']['primary']['request'])
        write_json(output / 'unwrapped-public.json', direct.model_dump(mode='json'))
        assert decode(direct)['data'] == observed['pages']['primary']['response']['data']
        assert not observed['mechanism']['automatic_eligible_signal']
        assert observed['pages']['primary']['flags']['direct_location']
        def check_index():
            good = index_inventory(manager, root, ['b.py'])
            write_json(output / 'index-good.json', good)
            assert good['keyword_complete_current'] and good['body_complete_current'] and good['targets_indexed']
            connection = manager._open_body_db()
            try:
                connection.execute("DELETE FROM body_files WHERE file_path='b.py'"); connection.commit()
            finally: connection.close()
            bad = index_inventory(manager, root, ['b.py']); write_json(output / 'index-damaged.json', bad)
            assert not bad['body_complete_current'] and not bad['targets_indexed']
        await asyncio.get_running_loop().run_in_executor(real._workers[key], check_index)
        write_json(output / 'untraced.json', plain)
    finally:
        await peer.close()


def test_exact_method_pointer_is_actionable_without_full_quote_bundle():
    case = {'target': {'file': 'a.py', 'symbol': 'C.run', 'start_line': 1, 'end_line': 20},
            'accepted_equivalent_implementation_locations': [],
            'evidence': [{'file': 'a.py', 'start_line': 15, 'end_line': 16, 'quote': 'guard\neffect'}]}
    hit = {'file_path': 'a.py', 'name': 'C.run', 'line': 2, 'end_line': 5,
           'snippet_start_line': 2, 'snippet_end_line': 5, 'snippet': 'partial'}
    flags = evidence_flags(case, [hit])
    assert flags['direct_location'] and not flags['complete_quotes']


def test_collective_excerpts_satisfy_guard_effect_bundle():
    case = {'target': {'file': 'a.py', 'symbol': 'f', 'start_line': 1, 'end_line': 20},
            'accepted_equivalent_implementation_locations': [],
            'evidence': [{'file': 'a.py', 'start_line': 2, 'end_line': 2, 'quote': 'guard'},
                         {'file': 'a.py', 'start_line': 16, 'end_line': 16, 'quote': 'effect'}]}
    hits = [{'file_path': 'a.py', 'name': 'file', 'snippet': q['quote'],
             'snippet_start_line': q['start_line'], 'snippet_end_line': q['end_line']} for q in case['evidence']]
    assert evidence_flags(case, hits)['complete_quotes']


def test_issuance_is_durable_on_failed_response_and_partial_evidence_retained(tmp_path):
    journal = Journal(tmp_path / 'journal', 1024 * 1024)
    case = {'id': 'control', 'repo_id': 'a', 'query': 'synthetic control',
            'target': {'file': 'a.py'}, 'evidence': []}
    report = {}; checkpoints = []
    async def observer(peer, case, role, pending):
        assert journal_events(journal.root)[0][0]['event'] == 'consume_request'
        pending['retained_raw_control'] = 'failure evidence'
        raise ValueError('controlled source validation failure')
    with pytest.raises(ValueError, match='controlled'):
        asyncio.run(collect_pages([case], {'a': object()}, journal, report,
                                  lambda: checkpoints.append(True), observer=observer))
    assert report['issued'][0]['id'] == 'control' and report['issued'][0]['role'] == 'primary'
    assert report['cases'][0]['pages']['primary']['retained_raw_control'] == 'failure evidence'
    assert checkpoints and len(journal_events(journal.root)) == 1


def test_all_primaries_precede_any_label_guided_roles(tmp_path):
    journal = Journal(tmp_path / 'journal', 1024 * 1024); report = {}; order = []
    cases = [{'id': str(n), 'repo_id': str(n % 2), 'query': 'synthetic control',
              'target': {'file': 'a.py'}, 'evidence': []} for n in range(4)]
    async def observer(peer, case, role, pending):
        order.append((case['id'], role)); pending['complete'] = True
    asyncio.run(collect_pages(cases, {'0': object(), '1': object()}, journal, report,
                              lambda: None, observer=observer))
    assert order[:4] == [(str(n), 'primary') for n in range(4)]
    assert len(order) == 12 and len(journal_events(journal.root)) == 12


def test_close_all_continues_after_a_peer_failure():
    closed = []
    class Peer:
        def __init__(self, name, fail): self.name, self.fail = name, fail
        async def close(self):
            closed.append(self.name)
            if self.fail: raise ValueError('controlled close failure')
    errors = asyncio.run(close_gateways({'a': Peer('a', True), 'b': Peer('b', False)}))
    assert closed == ['a', 'b'] and errors == [{'repo_id': 'a', 'type': 'ValueError'}]


def test_witness_refuses_external_source_alias(tmp_path):
    root = tmp_path / 'root'; root.mkdir(); outside = tmp_path / 'outside.py'; outside.write_text('secret\n')
    (root / 'escape.py').symlink_to(outside)
    with pytest.raises(ValueError, match='outside'):
        validate_witness(root, {'file': 'escape.py', 'quote': 'secret', 'source_sha256': 'irrelevant', 'start_line': 1, 'end_line': 1})


def test_failed_worker_exports_partial_evidence_and_removes_owned_inputs(tmp_path, monkeypatch):
    from eval.quality import runner
    monkeypatch.setenv('TMPDIR', str(tmp_path))
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '1')
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/diagnose/body-row-eligibility-real-0139')
    roots = []
    def controlled_failure(command, **kwargs):
        root = kwargs['root']; roots.append(root)
        (root / 'fixtures').mkdir(); (root / 'fixtures/input').write_text('owned synthetic input')
        (kwargs['evidence_root'] / 'partial-raw.json').write_text('{"retained":true}')
        return {'status': 'failed', 'cleanup_verified': True, 'reason': 'controlled failure'}
    monkeypatch.setattr(runner, 'supervise', controlled_failure)
    output = tmp_path / 'retained'
    with pytest.raises(AssertionError): supervise_run(output)
    assert json.loads((output / 'partial-raw.json').read_text()) == {'retained': True}
    assert json.loads((output / 'supervision.json').read_text())['owned_root_removed']
    assert len(roots) == 1 and not roots[0].exists()


def test_git_objects_bind_nested_modes_and_refuse_wrong_tree(tmp_path):
    root = tmp_path / 'repo'; root.mkdir(); (root / 'nested').mkdir(); (root / 'nested/f.py').write_text('source\n')
    os.chmod(root / 'nested/f.py', 0o755); (root / 'alias.py').symlink_to('nested/f.py')
    def git(*a): return subprocess.check_output(['git', '-C', str(root), *a]).decode().strip()
    git('init', '-b', 'fixture'); git('config', 'user.name', 'Control'); git('config', 'user.email', 'control@example.invalid')
    git('add', '.'); git('-c', 'core.hooksPath=/dev/null', 'commit', '-m', 'source')
    commit, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    entries = []
    for item in subprocess.check_output(['git', '-C', str(root), 'ls-tree', '-rz', 'HEAD']).split(b'\0'):
        if item:
            meta, path = item.split(b'\t'); mode, _, oid = meta.decode().split(); entries.append([path.decode(), mode, oid, 7 if mode == '100755' else 11])
    proof = git_provenance(root, commit, {'tree': tree, 'entries': entries})
    assert {e[1] for e in proof['entries']} == {'100755', '120000'} and len(proof['raw_trees_base64']) == 2
    with pytest.raises(AssertionError): git_provenance(root, commit, {'tree': '0' * 40, 'entries': entries})


@pytest.mark.parametrize('suffix', ['other', 'real-0139/extra', 'controls-0138'])
def test_branch_mode_refuses_unfrozen_invocations(suffix):
    with pytest.raises(ValueError): execution_role('refs/heads/diagnose/body-row-eligibility-' + suffix)


def test_exact_control_gate_accepts_all_distinct_passed_instances():
    xml = b'<testsuites><testsuite><testcase classname="tests.test_control" name="test_ok[a]"/><testcase classname="tests.test_control" name="test_ok[b]"/></testsuite></testsuites>'
    assert admit_controls(xml, ['test_control::test_ok[a]', 'test_control::test_ok[b]'])['passed'] == 2


@pytest.mark.parametrize('damage', ['empty', 'omitted', 'skipped', 'duplicate', 'wrong_parameter'])
def test_exact_control_gate_refuses_incomplete_or_changed_instances(damage):
    a = '<testcase classname="test_control" name="test_ok[a]"/>'
    b = '<testcase classname="test_control" name="test_ok[b]"/>'
    rows = {'empty': '', 'omitted': a, 'skipped': a + b.replace('/>', '><skipped/></testcase>'),
            'duplicate': a + a, 'wrong_parameter': a + b.replace('[b]', '[c]')}[damage]
    with pytest.raises(ValueError):
        admit_controls(('<testsuites><testsuite>' + rows + '</testsuite></testsuites>').encode(),
                       ['test_control::test_ok[a]', 'test_control::test_ok[b]'])
