"""CI observer controls, with a native double and the real bounded wrapper."""
import hashlib
import json
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
