"""Conservative Go/Rust evidence after the observed native parser error boundary."""
import hashlib

import pytest
from attocode_intel._internal.integrations.context import ts_parser
from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel._internal.integrations.context.codebase_ast import parse_file
from attocode_intel._internal.integrations.context.cross_references import CrossRefIndex


@pytest.fixture
def native_abort(monkeypatch):
    class AbortingParser:
        timeout_micros = 0
        def parse(self, source):
            raise ValueError('Parsing failed')
        def reset(self):
            pass
    monkeypatch.setattr(ts_parser, '_get_parser', lambda language: AbortingParser())


DECOYS = {
    'go': 'package sample\n/*\nfunc CommentFake() {}\n*/\nvar text = `\nfunc StringFake() {}\n`\nfunc Target() {}\n',
    'rust': '/* outer /* nested */\nfn CommentFake() {}\n*/\nconst TEXT: &str = br##"\nfn StringFake() {}\n"##;\nfn Target() {}\n',
}


@pytest.mark.parametrize('language', ['go', 'rust'])
def test_native_abort_fallback_excludes_comment_and_raw_string_declarations(language, native_abort):
    source = DECOYS[language]
    ast = parse_file('sample.' + ('go' if language == 'go' else 'rs'), source)
    assert [f.name for f in ast.functions] == ['Target'], 'followup: fallback invented non-code declarations'
    assert ast.parsing_tier == 'regex' and ast.parse_failures[0].outcome == 'parser_error'
    assert ast.content_sha256 == hashlib.sha256(source.encode()).hexdigest()


SPANS = {
    'go': 'package sample\nfunc Target(\n x int,\n) int {\n text := "}"\n rune := \'{\'\n /* } */\n return x\n}\n',
    'rust': 'fn Target<\'a>(\n x: &\'a str,\n) -> &\'a str\n{\n let text = "}";\n let rune = \'{\';\n /* } */\n x\n}\n',
}


@pytest.mark.parametrize('language', ['go', 'rust'])
def test_native_abort_fallback_multiline_span_ignores_literal_braces(language, native_abort):
    ast = parse_file('sample.' + ('go' if language == 'go' else 'rs'), SPANS[language])
    expected = [('Target', 2, 9)] if language == 'go' else [('Target', 1, 9)]
    assert [(f.name, f.start_line, f.end_line) for f in ast.functions] == expected, 'followup: bounded fallback lost declaration body range'


def test_go_fallback_return_struct_type_does_not_end_function_span(native_abort):
    source = 'package sample\nfunc Target() struct{ X int } {\n return struct{ X int }{X: 1}\n}\n'
    ast = parse_file('sample.go', source)
    assert [(f.name, f.start_line, f.end_line) for f in ast.functions] == [('Target', 2, 4)], 'followup: return type braces ended function span'


CALLS = {
    'go': 'package sample\nfunc Target() {}\nfunc Caller() { Target() }\n// Target()\n/* Target() */\nvar text = `\nTarget()\n`\n',
    'rust': 'fn Target() {}\nfn Caller() { Target(); }\n// Target()\n/* outer /* nested */ Target() */\nconst TEXT: &str = r##"\nTarget()\n"##;\n',
}


@pytest.mark.parametrize('language', ['go', 'rust'])
def test_native_abort_reference_fallback_keeps_only_real_inline_call(tmp_path, language, native_abort):
    name = 'sample.' + ('go' if language == 'go' else 'rs')
    source = CALLS[language]
    (tmp_path / name).write_text(source)
    ast = parse_file(name, source)
    service = ASTService(str(tmp_path))
    index = CrossRefIndex()
    service._index_definitions(name, ast, index=index)
    service._index_references(name, ast, index=index)
    references = index.get_references('Target')
    expected_line = 3 if language == 'go' else 2
    assert [(r.line, r.caller_qualified_name, r.source) for r in references] == [(expected_line, 'Caller', 'regex')], 'followup: fallback reference includes declaration or non-code'
    assert any(f.stage == 'references' and f.outcome == 'parser_error' for f in ast.parse_failures)


@pytest.mark.parametrize('language', ['go', 'rust'])
def test_native_abort_fallback_keeps_existing_500_line_span_bound(language, native_abort):
    first = 'func Target() {' if language == 'go' else 'fn Target() {'
    source = first + '\n' + '\n' * 500 + '}\n'
    ast = parse_file('sample.' + ('go' if language == 'go' else 'rs'), source)
    assert [(f.name, f.start_line, f.end_line) for f in ast.functions] == [('Target', 1, 1)]


@pytest.mark.parametrize('language', ['go', 'rust'])
def test_native_abort_retains_ordinary_regex_symbols_and_error_receipt(language, native_abort):
    source = 'func Target() {}\n' if language == 'go' else 'pub async fn Target() {}\n'
    ast = parse_file('sample.' + ('go' if language == 'go' else 'rs'), source)
    assert [(f.name, f.start_line, f.end_line) for f in ast.functions] == [('Target', 1, 1)]
    assert ast.parsing_tier == 'regex' and len(ast.parse_failures) == 1
    assert ast.parse_failures[0].error_type == 'ValueError' and ast.parse_failures[0].limit_micros == 100000
