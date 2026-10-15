"""Cold optimizations preserve extraction and never reuse stale source."""
import hashlib
import os
import sys
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from attocode_intel._internal.integrations.context import codebase_ast, ts_parser
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
