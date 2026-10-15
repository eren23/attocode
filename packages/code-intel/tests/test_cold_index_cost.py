"""Cold optimizations preserve extraction and never reuse stale source."""
import hashlib
import os
import sqlite3
import sys
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from attocode_intel._internal.integrations.context import codebase_ast, ts_parser
from attocode_intel._internal.integrations.context import semantic_search as search
from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel._internal.integrations.context.semantic_search import (
    SemanticSearchManager,
    _BodySpanCache,
)
from attocode_intel.service import CodeIntelService

GO_CASES = [
    '''package sample
import (alias "example.org/a"; . "example.org/b"; _ "example.org/c")
// Receiver docs
type Receiver struct { Value int }
func (r *Receiver) Run(x int) int {
    type Local struct { N int }
    if x > 0 { const C = 2; var V int; _ = V }
    f := func() { type Inner interface { Call() }; var N int; _ = N }
    f(); return x
}
type Alias = Receiver
const ( A = 1; B = 2 )
var Top int
''',
    'package sample\nfunc Broken( { var X = 2; type T struct { V int }',
    'package sample\n// func Fake() {}\nvar S = "type Fake struct {}"\n',
    'package sample\ntype ( A struct{}; B interface { Method(int) error } )\n',
]


@pytest.mark.parametrize("source", GO_CASES)
def test_go_native_declaration_paths_equal_complete_traversal(source):
    if ts_parser._get_parser("go") is None:
        pytest.skip("Go grammar unavailable")
    optimized = ts_parser.ts_parse_file("sample.go", source)
    with patch.object(ts_parser, "_go_declaration_paths", return_value=None):
        complete = ts_parser.ts_parse_file("sample.go", source)
    assert optimized == complete


def test_go_extraction_avoids_per_expression_python_walk_and_falls_back(monkeypatch):
    if ts_parser._get_parser("go") is None:
        pytest.skip("Go grammar unavailable")
    source = 'package sample\nfunc Run(x int) int {\n' + 'x += 1; println(x)\n' * 800 + 'return x\n}'
    def measured():
        calls = 0
        def trace(frame, event, arg):
            nonlocal calls
            if event == "call" and frame.f_code.co_name == "_process_node":
                calls += 1
        previous = sys.getprofile()
        try:
            sys.setprofile(trace)
            result = ts_parser.ts_parse_file("sample.go", source)
        finally:
            sys.setprofile(previous)
        return result, calls
    optimized, fewer = measured()
    with patch.object(ts_parser, "_go_declaration_paths", return_value=None):
        complete, many = measured()
    assert optimized == complete and fewer < many / 10
    def unavailable(*args):
        raise RuntimeError("query unavailable")
    monkeypatch.setattr(ts_parser, "_go_declaration_query", unavailable)
    assert ts_parser.ts_parse_file("sample.go", source) == complete


def test_lexical_reuses_only_matching_structural_ast_and_keeps_documents(tmp_path, monkeypatch):
    source = tmp_path / "sample.py"
    source.write_text('class Catalog:\n    def find(self, key: str):\n        return key\n')
    content = source.read_text()
    parsed = codebase_ast.parse_file(str(source))
    assert parsed.content_sha256 == hashlib.sha256(content.encode()).hexdigest()
    structural = ASTService(str(tmp_path))
    structural._ast_cache['sample.py'] = parsed
    ctx = SimpleNamespace(_ensure_fresh=lambda: None, _files=[SimpleNamespace(
        path=str(source), relative_path='sample.py', is_test=False)])
    monkeypatch.setattr(SemanticSearchManager, '_load_kw_cache', lambda *a: None)
    monkeypatch.setattr(SemanticSearchManager, '_save_kw_cache', lambda *a: None)
    plain = SemanticSearchManager(str(tmp_path))
    reused = SemanticSearchManager(str(tmp_path), ast_lookup=structural.cached_file_ast)
    try:
        plain._build_keyword_index(ctx)
        expected = [asdict(doc) for doc in plain._kw_docs]
        expected_chunks = plain._body_chunks('sample.py', str(source))
        spans = _BodySpanCache()
        with patch.object(codebase_ast, 'parse_file', side_effect=AssertionError('redundant parse')):
            reused._build_keyword_index(ctx, spans)
            assert reused._body_chunks('sample.py', str(source), spans) == expected_chunks
            chunks, terms = reused._body_document(
                'sample.py', str(source), _BodySpanCache(0),
                ast_lookup=structural.cached_file_ast, include_file_terms=True,
            )
            assert chunks == expected_chunks and terms == ' '.join(search._tokenize(content))
        assert [asdict(doc) for doc in reused._kw_docs] == expected
        assert reused._warmup_reused_asts == 1
        stat = source.stat()
        source.write_text(content.replace('find', 'seek'))
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        with patch.object(codebase_ast, 'parse_file', wraps=codebase_ast.parse_file) as parse:
            reused._build_keyword_index(ctx, _BodySpanCache())
        assert parse.call_count == 1
        assert 'Catalog.seek' in {d.name for d in reused._kw_docs}
        assert 'Catalog.find' not in {d.name for d in reused._kw_docs}
        assert structural._ast_cache['sample.py'] is parsed
    finally:
        plain.close()
        reused.close()
        structural._store.close()


def test_search_lookup_does_not_initialize_structural_service(tmp_path):
    service = CodeIntelService(str(tmp_path))
    manager = service._get_semantic_search()
    try:
        assert manager.ast_lookup('missing.py', 'digest') is None
        assert service._ast_service is None
    finally:
        manager.close()


@pytest.mark.parametrize('content', [
    'class Outer:\n    def method(self):\n' + '        HTTPServer = camelCase_42\n' * 90,
    'prefix ' + 'LongIdentifier' * 300 + '\n' + 'Kİ unicode_HTTP2Response\r\n' * 40,
    'alpha\vBeta\fHTTPServer\x1cfooBar\x85otherValue\u2028lastToken\u2029endValue',
])
def test_shared_line_tokens_equal_original_window_and_whole_file_tokens(tmp_path, content):
    source = tmp_path / 'sample.py'
    source.write_text(content)
    chunks, file_terms = SemanticSearchManager._body_document(
        'sample.py', str(source), include_file_terms=True,
    )
    assert chunks
    assert file_terms == ' '.join(search._tokenize(source.read_text()))
    for _kind, _name, start, end, body, terms in chunks:
        assert 1 <= start <= end <= len(source.read_text().splitlines())
        assert terms == ' '.join(search._tokenize(body))


def test_overlapping_windows_and_file_search_tokenize_each_complete_line_once(tmp_path, monkeypatch):
    content = 'def useful_method():\n' + '    value = meaningfulHTTPResponse\n' * 100
    source = tmp_path / 'sample.py'
    source.write_text(content)
    original = search._tokenize
    scanned = []
    def counted(text):
        scanned.append(len(text))
        return original(text)
    monkeypatch.setattr(search, '_tokenize', counted)
    chunks, _ = SemanticSearchManager._body_document('sample.py', str(source), include_file_terms=True)
    assert len(chunks) >= 4
    assert len(scanned) == len(set(content.splitlines()))
    assert sum(scanned) <= len(content)


def test_body_batches_preserve_rows_bm25_and_rollback_after_mid_refresh_failure(tmp_path, monkeypatch):
    source = tmp_path / 'sample.py'
    source.write_text(''.join(f'def func_{i}():\n    return "NeedleToken {i}"\n' for i in range(200)))
    manager = SemanticSearchManager(str(tmp_path))
    original_open = SemanticSearchManager._open_body_db
    inserts = []
    fail = [False]
    class Connection:
        def __init__(self, conn):
            self.conn = conn
        def __getattr__(self, name):
            return getattr(self.conn, name)
        def execute(self, sql, parameters=()):
            if sql.startswith('INSERT INTO body_fts '):
                inserts.append(len(parameters) // 7)
                assert len(parameters) <= 64 * 7
                if fail[0] and len(inserts) == 2:
                    raise sqlite3.OperationalError('injected second batch failure')
            return self.conn.execute(sql, parameters)
    monkeypatch.setattr(SemanticSearchManager, '_open_body_db', lambda self: Connection(original_open(self)))
    ctx = SimpleNamespace(_ensure_fresh=lambda: None, _files=[SimpleNamespace(
        path=str(source), relative_path='sample.py')])
    try:
        manager._sync_body_index(ctx)
        assert manager._body_index_built
        assert len(inserts) == 4 and sum(inserts) == 200
        with original_open(manager) as conn:
            before = conn.execute('SELECT rowid,* FROM body_fts ORDER BY rowid').fetchall()
            metadata = conn.execute('SELECT * FROM body_files').fetchall()
            schema = conn.execute("SELECT sql FROM sqlite_master WHERE name='body_fts'").fetchone()[0]
            query = "SELECT rowid,bm25(body_fts) FROM body_fts WHERE body_fts MATCH 'needle' ORDER BY rowid"
            scores = conn.execute(query).fetchall()
        conn.close()
        with sqlite3.connect(':memory:') as reference:
            reference.execute(schema)
            chunks, _ = manager._body_document('sample.py', str(source))
            for chunk in chunks:
                reference.execute('INSERT INTO body_fts VALUES (?,?,?,?,?,?,?)', ('sample.py', *chunk))
            assert reference.execute('SELECT rowid,* FROM body_fts ORDER BY rowid').fetchall() == before
            assert reference.execute(query).fetchall() == scores
        reference.close()
        source.write_text(source.read_text().replace('NeedleToken', 'DifferentToken'))
        manager._body_index_built = False
        inserts.clear()
        fail[0] = True
        manager._sync_body_index(ctx)
        assert not manager._body_index_built and len(inserts) == 2
        with original_open(manager) as conn:
            assert conn.execute('SELECT rowid,* FROM body_fts ORDER BY rowid').fetchall() == before
            assert conn.execute('SELECT * FROM body_files').fetchall() == metadata
        conn.close()
        inserts.clear()
        fail[0] = False
        manager._sync_body_index(ctx)
        assert manager._body_index_built and len(inserts) == 4
        with original_open(manager) as conn:
            assert conn.execute(query).fetchall() == []
        conn.close()
    finally:
        manager.close()


def test_line_memo_is_per_file_bounded_and_preserves_truncated_unicode_terms(tmp_path, monkeypatch):
    original = search._tokenize
    calls = []
    def counted(text):
        calls.append(text)
        return original(text)
    monkeypatch.setattr(search, '_tokenize', counted)
    # Fill the entry/character budget, then repeat a late line: no unbounded memo.
    content = '\n'.join(f'uniqueIdentifier_{i} = someHTTPValue_{i}' for i in range(1500))
    content += '\n' + 'veryLateUnique = LastHTTPValue\n' * 20
    content += ('LongHTTPIdentifier' * 200 + ' Kİ\n') * 3
    source = tmp_path / 'data.txt'
    source.write_text(content)
    def build():
        return SemanticSearchManager._body_document('data.txt', str(source), include_file_terms=True)
    first = build()
    first_calls = list(calls)
    assert first_calls.count('veryLateUnique = LastHTTPValue') == 20
    assert first[1] == ' '.join(original(content))
    assert all(terms == ' '.join(original(body)) for *_, body, terms in first[0])
    calls.clear()
    assert build() == first and calls == first_calls  # No cross-file/global retention.
