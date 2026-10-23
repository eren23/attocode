"""Bounded compatibility captures preserve the first failure and stop safely."""
import hashlib
import json
import sys

import pytest
from mcp.types import CallToolResult, TextContent

from eval.quality.experiment_evidence import Journal


def journal_rows(root):
    return [(e['request'], json.loads((root / e['response']['path']).read_bytes()))
            for e in map(json.loads, (root / 'events.jsonl').read_text().splitlines())]


@pytest.mark.parametrize('failure', ['malformed', 'budget'])
async def test_broad_raw_mcp_is_durable_before_json_and_budget_rejection(tmp_path, failure):
    from eval.quality.corpus_capture import RecordedGateway

    text = '{broken' if failure == 'malformed' else json.dumps({'data': 'x' * 10000})
    class ExternalPeer:
        async def execute_mcp(self, tool, arguments):
            return CallToolResult(content=[TextContent(type='text', text=text)])
    journal = Journal(tmp_path / 'journal', 128 * 1024)
    gateway = RecordedGateway(ExternalPeer(), tmp_path, journal)
    with pytest.raises(ValueError):
        await gateway.execute_mcp('search_symbols', {'name': 'alpha', 'max_tokens': 2000})
    rows = journal_rows(tmp_path / 'journal')
    assert rows[-1][0]['tool'] == 'search_symbols' and rows[-1][1]['content'][0]['text'] == text


async def test_broad_metadata_hit_keeps_description_without_claiming_source(tmp_path):
    from attocode_intel import gateway as providers
    from attocode_intel import search_evidence
    from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchResult

    from eval.quality.corpus_capture import RecordedGateway

    (tmp_path / 'source.py').write_bytes(b'alpha\r\n\xff beta\r\n')
    candidate = SemanticSearchResult(file_path='source.py', chunk_type='file', name='source.py', score=1, text='class Metadata')
    class ExternalPeer:
        async def execute_mcp(self, tool, arguments):
            selected = providers.hydrate_selected_sources(str(tmp_path), [candidate])[0]
            hit = {'file_path': selected.file_path, 'name': selected.name, 'chunk_type': selected.chunk_type,
                   'score': selected.score, 'line': selected.start_line or None, 'end_line': selected.end_line or None,
                   **search_evidence.search_snippet(selected, 'alpha beta', 320)}
            return CallToolResult(content=[TextContent(type='text', text=json.dumps({'data': {'results': [hit]}}))])
    journal = Journal(tmp_path / 'journal', 128 * 1024)
    wrapper = RecordedGateway(ExternalPeer(), tmp_path, journal)
    response = await wrapper.execute_mcp('semantic_search', {'query': 'alpha beta', 'max_tokens': 2000})
    assert json.loads(response.content[0].text)['data']['results'][0]['snippet'] == 'class Metadata'
    validated = [v for req, v in journal_rows(tmp_path / 'journal') if req['event'] == 'source_validation']
    assert validated[-1] == [{'kind': 'metadata_only', 'spans': []}]


async def test_broad_warming_responses_are_kept_before_ready_result(tmp_path):
    from eval.quality.corpus import ready_search
    from eval.quality.corpus_capture import RecordedGateway

    class ExternalPeer:
        calls = 0
        async def execute_mcp(self, tool, arguments):
            self.calls += 1
            index = {'status': 'warming' if self.calls == 1 else 'ready'}
            return CallToolResult(content=[TextContent(type='text', text=json.dumps({'data': {'results': [], 'ranking': {'index': index}}}))])
    journal = Journal(tmp_path / 'journal', 128 * 1024)
    wrapper = RecordedGateway(ExternalPeer(), tmp_path, journal)
    _response, warm = await ready_search(wrapper, {'query': 'alpha', 'max_tokens': 2000})
    assert warm['warming_responses'] == 1
    raw = [v for req, v in journal_rows(tmp_path / 'journal') if req['event'] == 'mcp_response']
    assert len(raw) == 2 and json.loads(raw[0]['content'][0]['text'])['data']['ranking']['index']['status'] == 'warming'


async def test_broad_cursor_requests_remain_bound_to_their_own_responses(tmp_path):
    from eval.quality.corpus_capture import RecordedGateway

    class ExternalPeer:
        async def execute_mcp(self, tool, arguments):
            data = {'references': [], 'next_cursor': None if arguments.get('cursor') else 'next'}
            return CallToolResult(content=[TextContent(type='text', text=json.dumps({'data': data}))])
    journal = Journal(tmp_path / 'journal', 128 * 1024)
    wrapper = RecordedGateway(ExternalPeer(), tmp_path, journal)
    for arguments in ({'symbol_name': 'alpha', 'max_tokens': 4000}, {'symbol_name': 'alpha', 'max_tokens': 4000, 'cursor': 'next'}):
        await wrapper.execute_mcp('cross_references', arguments)
    rows = [(r, v) for r, v in journal_rows(tmp_path / 'journal') if r['event'] == 'mcp_response']
    assert len(rows) == 2 and rows[1][0]['arguments']['cursor'] == 'next'
    assert json.loads(rows[0][1]['content'][0]['text'])['data']['next_cursor'] == 'next'


async def test_broad_first_failed_check_is_checkpointed_before_stopping(tmp_path, monkeypatch):
    from eval.quality import corpus

    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    (tmp_path / 'source.py').write_text('# helper is planned\ndef helpers(): return 1\n')
    journal = Journal(tmp_path / 'journal', 2**20)
    checkpoints = []
    spec = {'file': 'source.py', 'symbol': 'helper', 'anchor': '# helper', 'caller': None, 'importer': None, 'test': None}
    with pytest.raises(ValueError, match='failed compatibility check'):
        await corpus.evaluate(tmp_path, spec, journal=journal, checkpoint=lambda checks, retrieval: checkpoints.append(list(checks)))
    assert len(checkpoints[-1]) == 1 and checkpoints[-1][0]['outcome'] == 'failed'
    raw = [r for r, _ in journal_rows(tmp_path / 'journal') if r['event'] == 'mcp_response']
    assert len(raw) == 1 and raw[0]['tool'] == 'search_symbols'


async def test_broad_unsupported_and_limited_checks_remain_honest_outcomes(tmp_path, monkeypatch):
    from eval.quality import corpus

    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    (tmp_path / 'dist').mkdir()
    (tmp_path / 'dist/source.py').write_text('def helper(): return 1\n')
    journal = Journal(tmp_path / 'journal', 2**20)
    spec = {'file': 'dist/source.py', 'symbol': 'helper', 'anchor': 'def helper(', 'caller': None, 'importer': None, 'test': None}
    rows = await corpus.evaluate(tmp_path, spec, journal=journal)
    assert {r['name'] for r in rows if r['outcome'] == 'unsupported'} == {'definition', 'source', 'scoped_search', 'restart'}
    assert all(r['outcome'] in {'passed', 'limited', 'unsupported'} for r in rows)


@pytest.mark.parametrize('status', ['failed', 'incomplete'])
def test_broad_first_bad_pack_prevents_second_pack_launch(tmp_path, monkeypatch, status):
    import yaml

    from eval.quality import corpus

    monkeypatch.setenv('ATTOCODE_CORPUS_EVIDENCE', str(tmp_path / 'captures'))
    specs = [{'id': n, 'repo': 'owner/' + n, 'commit': 'a' * 40, 'language': 'python',
              'file': 'source.py', 'source_sha256': hashlib.sha256(b'pass\n').hexdigest(), 'queries': []} for n in ('one', 'two')]
    manifest = tmp_path / 'packs.yaml'
    manifest.write_text(yaml.safe_dump({'repositories': specs}))
    monkeypatch.setattr(corpus, 'PACK', manifest)
    monkeypatch.setattr(corpus, 'evidence_identity', lambda: {'pack_sha256': 'frozen'})
    seen = []
    def materialize(spec, root, cache, *, receipt=None):
        seen.append(spec['id'])
        (root / 'source.py').write_bytes(b'pass\n')
        if receipt is not None:
            receipt['source.py'] = {'kind': 'file', 'bytes': 5, 'sha256': hashlib.sha256(b'pass\n').hexdigest()}
        return 'tree'
    monkeypatch.setattr(corpus, 'materialize', materialize)
    monkeypatch.setattr(corpus, 'evaluate_isolated', lambda *a: {'status': status, 'error': 'first fault',
        'checks': [{'name': 'definition', 'outcome': 'failed', 'passed': False}], 'retrieval': []})
    output = tmp_path / 'result.json'
    monkeypatch.setattr(sys, 'argv', ['corpus', '--output', str(output)])
    assert corpus.main() == 1 and seen == ['one']
    result = json.loads(output.read_bytes())
    assert not result['passed'] and result['cleanup_verified']


def test_broad_wrong_worker_engine_stops_before_evaluate(tmp_path, monkeypatch):
    from eval.quality import corpus

    monkeypatch.setenv('ATTOCODE_CORPUS_EVIDENCE', str(tmp_path / 'captures'))
    monkeypatch.setenv('ATTOCODE_EXPERIMENT_ENGINE', str(tmp_path / 'wrong-package'))
    spec, output = tmp_path / 'spec.json', tmp_path / 'worker.json'
    spec.write_text('{"id":"toy"}')
    monkeypatch.setattr(sys, 'argv', ['corpus', '--worker', str(tmp_path), '--spec', str(spec), '--output', str(output)])
    called = []
    async def evaluate(*args, **kwargs):
        called.append(True)
        return []
    monkeypatch.setattr(corpus, 'evaluate', evaluate)
    with pytest.raises(ValueError, match='engine_origin'):
        corpus.main()
    assert called == []
