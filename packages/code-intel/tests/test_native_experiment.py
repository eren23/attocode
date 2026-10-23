"""CI observer controls, with a native double and the real bounded wrapper."""
import hashlib
import json
import subprocess
import sys
import threading

import pytest
from attocode_intel._internal.integrations.context import ts_parser

from eval.quality.experiment_evidence import Journal
from eval.quality.native_experiment import ParserObserver


@pytest.mark.parametrize('outcome', ['tree', 'no_tree', 'ValueError', 'RuntimeError'])
def test_native_observer_retains_actual_outcome_before_bounded_fallback(tmp_path, outcome):
    tree = object()
    class Native:
        timeout_micros = 0
        resets = 0
        def parse(self, source):
            assert source == b'fixture source'
            assert self.timeout_micros == 100_000
            if outcome in {'ValueError', 'RuntimeError'}:
                raise {'ValueError': ValueError, 'RuntimeError': RuntimeError}[outcome]('native diagnostic')
            return tree if outcome == 'tree' else None
        def reset(self):
            # The native result is durable before bounded_parse reaches finally.
            event = json.loads((tmp_path / 'trace/events.jsonl').read_text().splitlines()[-1])
            saved = json.loads((tmp_path / 'trace' / event['response']['path']).read_bytes())
            assert saved['outcome'] == outcome
            self.resets += 1
    journal = Journal(tmp_path / 'trace', 64 * 1024)
    native = Native()
    proxy = ParserObserver(native, journal.response, 'fixture')
    if outcome == 'RuntimeError':
        with pytest.raises(RuntimeError, match='native diagnostic'):
            ts_parser.bounded_parse(proxy, b'fixture source')
    else:
        actual = ts_parser.bounded_parse(proxy, b'fixture source')
        assert actual is (tree if outcome == 'tree' else None)
    assert native.resets == 1 and native.timeout_micros == 100_000
    events = [json.loads(line) for line in (tmp_path / 'trace/events.jsonl').read_text().splitlines()]
    rows = [json.loads((tmp_path / 'trace' / e['response']['path']).read_bytes()) for e in events]
    parsed = next(r for r in rows if r.get('stage') == 'parse')
    assert parsed['source_sha256'] == hashlib.sha256(b'fixture source').hexdigest()
    assert parsed['parser_id'] == id(native) and parsed['thread_id'] == threading.get_ident()
    assert parsed['wall_ns'] >= 0 and parsed['thread_cpu_ns'] >= 0
    assert parsed['limit_micros'] == 100_000
    assert parsed['error'] == ({'type': outcome, 'message': 'native diagnostic'}
                               if outcome in {'ValueError', 'RuntimeError'} else None)
    assert [r['stage'] for r in rows] == ['timeout_set', 'parse', 'reset']


@pytest.mark.parametrize('corruption', [None, 'truncated', 'source_identity', 'selected_caller'])
async def test_native_rust_trace_admission_checks_actual_fixture_capture(tmp_path, monkeypatch, corruption):
    from test_lsp_diagnostics import existing_flow

    from eval.quality.lsp_admission import expected_sources, verify_diagnostic

    monkeypatch.setenv('RA_LOG', 'rust_analyzer=info')
    _peer, path = await existing_flow(tmp_path, monkeypatch)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if corruption == 'truncated':
        rows[-1]['truncated'] = True
    elif corruption == 'source_identity':
        rows[0]['sources']['eval/quality/lsp_trace.py'] = '0' * 64
    elif corruption == 'selected_caller':
        selected = next(row for row in rows if row['kind'] == 'inspection' and row['stage'] == 'selected_original')
        selected['response']['data']['references'] = []
    raw = ''.join(json.dumps(row) + '\n' for row in rows).encode()
    if corruption:
        with pytest.raises(ValueError):
            verify_diagnostic(raw, expected_sources())
    else:
        result = verify_diagnostic(raw, expected_sources())
        assert result['status'] == 'passed' and result['inspections'] == 4


def test_zero_exit_rust_worker_with_incomplete_capture_stops_before_next_launch(tmp_path):
    from eval.quality.native_experiment import run_rust_trials

    evidence, work = tmp_path / 'evidence', tmp_path / 'work'
    evidence.mkdir()
    work.mkdir()
    def command(name, arguments, env):
        # Only the external worker is replaced; launch/zero-exit and emitted
        # incomplete evidence are real, and sequencing/admission stay real.
        trial = evidence / name
        result = subprocess.run([sys.executable, '-c',
            'import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.mkdir(); '
            '(p/"lsp-diagnostic-rust.jsonl").write_text(\'{"kind":"trace_start"}\\n\'); '
            '(p/"rust.xml").write_text(\'<testsuite><testcase classname="test_real_language_server" '
            'name="test_real_server_warmed_selected_definition_and_edit[rust]"/></testsuite>\')',
            str(trial)], env=env, check=True)
        return trial, {'name': name, 'exit_code': result.returncode, 'status': 'incomplete'}
    frozen = {'rust': {'processes': 6, 'test': 'required-rust-test'}}
    with pytest.raises(ValueError):
        run_rust_trials(frozen, evidence, work, command)
    assert sorted(p.name for p in evidence.iterdir()) == ['rust-1']
    assert (evidence / 'rust-1/lsp-diagnostic-rust.jsonl').read_bytes() == b'{"kind":"trace_start"}\n'
