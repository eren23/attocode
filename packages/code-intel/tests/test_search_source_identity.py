"""Selected source labels must describe their whole window, after ranking."""
import hashlib
import json
from dataclasses import asdict

import pytest

from attocode_intel._internal.integrations.context import embeddings
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager, SemanticSearchResult
from attocode_intel.gateway import OperationGateway
from attocode_intel.search_evidence import source_body
from attocode_intel.service import CodeIntelService

SOURCE = ('class First:\n    amberneedle = "one"\n\nclass Second:\n'
          '    cobaltneedle = "two"\n    ballast = 1\n    ballast2 = 2\n'
          '    ballast3 = 3\n    ballast4 = 4\n')
MARKER = 'REGRESSION: selected source identity disagrees with verified class span'


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv('ATTOCODE_INTEL_RANKING_PROVIDER', 'off')
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    # The optional external embedding provider is outside this lexical contract.
    monkeypatch.setattr(embeddings, 'create_embedding_provider', lambda *a, **k: None)


def qualified(record_property, files, rows):
    record_property('inputs', json.dumps({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}))
    record_property('observed', json.dumps([asdict(row) for row in rows]))
    record_property('qualified_input', 'true')


def located(path, body, first, last, *, name='Wrong', kind='class', score=.75):
    return SemanticSearchResult(path, kind, name, f'{path}:{first}-{last}\n{body}', score, first, last)


@pytest.mark.parametrize('case', ['contained', 'crossing', 'nested', 'module', 'partial-line', 'valid', 'function'])
def test_selected_class_identity(tmp_path, record_property, case):
    source, first, last, name, kind = SOURCE, 1, 2, 'Wrong', 'class'
    expected = ('class', 'First')
    if case == 'crossing':
        last, expected = 9, ('file', 'sample.py')
    elif case == 'nested':
        source, first, last = 'class Outer:\n    token = 1\n    class Inner:\n        value = 2\n', 3, 4
        expected = ('class', 'Inner')
    elif case == 'module':
        source, first, last = 'MODULE = 1\nclass First:\n    value = 2\n', 1, 1
        expected = ('file', 'sample.py')
    elif case == 'valid':
        name = 'First'
    elif case == 'function':
        source, first, last, name, kind = 'def work():\n    return 1\n', 1, 2, 'work', 'function'
        expected = ('function', 'work')
    path = tmp_path/'sample.py'
    path.write_text(source)
    body = '\n'.join(source.splitlines()[first-1:last])
    if case == 'partial-line':
        body = body[:-3]
    row = located('sample.py', body, first, last, name=name, kind=kind)
    before = asdict(row)
    results, _ = CodeIntelService(str(tmp_path))._rank_search_results('amberneedle', [row], 1)
    qualified(record_property, [path], results)
    assert len(results) == 1 and row.score == results[0].score
    assert asdict(row) == before
    assert (results[0].text, results[0].start_line, results[0].end_line) == (row.text, first, last)
    assert (results[0].chunk_type, results[0].name) == expected, MARKER


def test_real_index_window_keeps_rank_and_source(tmp_path, record_property):
    path = tmp_path/'sample.py'
    path.write_text(SOURCE)
    manager = SemanticSearchManager(str(tmp_path), nl_mode='none')
    try:
        manager.warm()
        assert manager.wait_for_body_index(10) and manager._kw_index_built
        rows = manager._body_search(['amberneedle'], 10, 'sample.py')
        assert len(rows) == 1 and rows[0].name == 'Second'
        assert (rows[0].start_line, rows[0].end_line) == (1, 9)
        assert source_body(rows[0]) == SOURCE.rstrip('\n')
        before = [asdict(row) for row in rows]
        results, ranking = CodeIntelService(str(tmp_path))._rank_search_results('amberneedle', rows, 10)
        qualified(record_property, [path], results)
        assert [asdict(row) for row in rows] == before
        assert [(r.file_path, r.score, r.text, r.start_line, r.end_line) for r in results] == [
            (r.file_path, r.score, r.text, r.start_line, r.end_line) for r in rows]
        assert ranking['returned_count'] == 1 and ranking['provider'] == 'off'
        assert (results[0].chunk_type, results[0].name) == ('file', 'sample.py'), MARKER
    finally:
        manager.close()


def test_selected_order_scores_and_top_k_are_unchanged(tmp_path, record_property):
    path = tmp_path/'sample.py'
    path.write_text(SOURCE)
    rows = [located('sample.py', 'class Second:\n    cobaltneedle = "two"', 4, 5, score=.2),
            located('sample.py', 'class First:\n    amberneedle = "one"', 1, 2, score=.9)]
    before = [asdict(row) for row in rows]
    results, _ = CodeIntelService(str(tmp_path))._rank_search_results('needle', rows, 1)
    qualified(record_property, [path], results)
    assert [asdict(row) for row in rows] == before
    assert len(results) == 1 and results[0].score == .2 and results[0].start_line == 4
    assert (results[0].chunk_type, results[0].name) == ('class', 'Second'), MARKER


def test_same_size_current_source_mismatch_does_not_rebind(tmp_path, record_property):
    path = tmp_path/'sample.py'
    old = 'class First:\n    value = 1\n'
    new = 'class Other:\n    value = 2\n'
    assert len(old) == len(new)
    path.write_text(new)
    row = located('sample.py', old.rstrip('\n'), 1, 2)
    results, _ = CodeIntelService(str(tmp_path))._rank_search_results('value', [row], 1)
    qualified(record_property, [path], results)
    assert results == [row] and results[0] is row


@pytest.mark.parametrize('case', ['missing', 'escaping', 'oversized', 'invalid-range', 'nonutf8'])
def test_unavailable_source_is_not_relabelled(tmp_path, record_property, case):
    path = tmp_path/'sample.py'
    path.write_text(SOURCE)
    row = located('sample.py', SOURCE.rstrip('\n'), 1, 9)
    if case == 'missing':
        path.unlink()
    elif case == 'escaping':
        outside = tmp_path.parent/(tmp_path.name+'-outside.py')
        outside.write_text(SOURCE)
        path.unlink()
        path.symlink_to(outside)
    elif case == 'oversized':
        path.write_bytes(b'x'*1_000_001)
    elif case == 'invalid-range':
        row.end_line = 999
    elif case == 'nonutf8':
        path.write_bytes(b'\xff\xfe')
    try:
        results, _ = CodeIntelService(str(tmp_path))._rank_search_results('needle', [row], 1)
        qualified(record_property, [path] if path.exists() else [], results)
        assert results == [row] and results[0] is row
    finally:
        if case == 'escaping':
            outside.unlink()


@pytest.mark.parametrize('budget', ['files', 'bytes'])
def test_source_identity_validation_is_bounded(tmp_path, record_property, budget):
    source = 'class First:\n    value = 1\n'
    count, allowed = (9, 8) if budget == 'files' else (3, 2)
    if budget == 'bytes':
        source += '# padding\n' * 80_000
    paths, rows = [], []
    for index in range(count):
        path = tmp_path/f'sample{index}.py'
        path.write_text(source)
        paths.append(path)
        rows.append(located(path.name, 'class First:\n    value = 1', 1, 2))
    results, _ = CodeIntelService(str(tmp_path))._rank_search_results('value', rows, count)
    qualified(record_property, paths, results)
    assert [(r.file_path, r.score) for r in results] == [(r.file_path, r.score) for r in rows]
    assert [r.name for r in results] == ['First']*allowed + ['Wrong']*(count-allowed), MARKER


@pytest.mark.parametrize('route', ['service-keyword', 'service-auto', 'gateway-plain', 'gateway-compact'])
async def test_public_delivery_uses_whole_window_identity(tmp_path, record_property, route):
    path = tmp_path/'sample.py'
    path.write_text(SOURCE)
    gateway = OperationGateway(str(tmp_path), 'lean', watch=False)
    service = CodeIntelService(str(tmp_path))
    try:
        if route.startswith('service-'):
            text = service.semantic_search('amberneedle', top_k=10,
                mode='keyword' if route == 'service-keyword' else 'auto')
            record_property('delivered', text)
            actual = [('file', 'sample.py')] if '[file] sample.py:1-9 — sample.py' in text else []
        else:
            response = await gateway.execute('semantic_search', {'query':'amberneedle', 'top_k':10,
                'mode':'keyword', 'max_tokens':4000}, compact=route == 'gateway-compact')
            assert not response.isError, response.content
            if route == 'gateway-compact':
                payload = json.loads(response.content[0].text)
                record_property('delivered', json.dumps(payload))
                hits = [h for h in payload['data']['results'] if h['line'] == 1 and h['end_line'] == 9]
                actual = [(h['chunk_type'], h['name']) for h in hits]
            else:
                text = response.content[0].text
                record_property('delivered', text)
                actual = [('file', 'sample.py')] if '[file] sample.py:1-9 — sample.py' in text else []
        qualified(record_property, [path], [])
        assert actual == [('file', 'sample.py')], MARKER
    finally:
        await gateway.close()
        if service._semantic_search is not None:
            service._semantic_search.close()
