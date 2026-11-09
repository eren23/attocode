"""Native Go receiver identity belongs to the method's own source file."""
import json
from dataclasses import asdict

import pytest
from attocode_intel._internal.integrations.context import ts_parser
from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel._internal.integrations.context.codebase_ast import diff_file_ast, parse_file
from attocode_intel._internal.integrations.context.syntax_evidence import syntax_tree

CASES = [{'id': 'value-receiver-other-file',
  'files': {'type.go': 'package p\ntype R struct{}\n',
            'method.go': 'package p\nfunc (r R) M(v int) int { return v }\n'},
  'expected_index': [{'file_path': 'method.go',
                      'qualified_name': 'R.M',
                      'name': 'M',
                      'kind': 'method',
                      'start_line': 2,
                      'end_line': 2}],
  'expected_ast_container': 'functions',
  'expected_written_parameter_type': 'int'},
 {'id': 'pointer-receiver-other-file',
  'files': {'type.go': 'package p\ntype R struct{}\n',
            'method.go': 'package p\nfunc (r *R) M(v int) int { return v }\n'},
  'expected_index': [{'file_path': 'method.go',
                      'qualified_name': 'R.M',
                      'name': 'M',
                      'kind': 'method',
                      'start_line': 2,
                      'end_line': 2}],
  'expected_ast_container': 'functions',
  'expected_written_parameter_type': 'int'},
 {'id': 'generic-value-other-file',
  'files': {'type.go': 'package p\ntype Box[T any] struct{}\n',
            'method.go': 'package p\nfunc (r Box[T]) M(v T) T { return v }\n'},
  'expected_index': [{'file_path': 'method.go',
                      'qualified_name': 'Box.M',
                      'name': 'M',
                      'kind': 'method',
                      'start_line': 2,
                      'end_line': 2}],
  'expected_ast_container': 'functions',
  'expected_written_parameter_type': 'T'},
 {'id': 'generic-pointer-other-file',
  'files': {'type.go': 'package p\ntype Box[T any] struct{}\n',
            'method.go': 'package p\nfunc (r *Box[T]) M(v T) T { return v }\n'},
  'expected_index': [{'file_path': 'method.go',
                      'qualified_name': 'Box.M',
                      'name': 'M',
                      'kind': 'method',
                      'start_line': 2,
                      'end_line': 2}],
  'expected_ast_container': 'functions',
  'expected_written_parameter_type': 'T'},
 {'id': 'parenthesized-pointer-other-file',
  'files': {'type.go': 'package p\ntype R struct{}\n',
            'method.go': 'package p\nfunc (r (*R)) M(v int) int { return v }\n'},
  'expected_index': [{'file_path': 'method.go',
                      'qualified_name': 'R.M',
                      'name': 'M',
                      'kind': 'method',
                      'start_line': 2,
                      'end_line': 2}],
  'expected_ast_container': 'functions',
  'expected_written_parameter_type': 'int'},
 {'id': 'unicode-owner-other-file',
  'files': {'type.go': 'package p\ntype Ω struct{}\n',
            'method.go': 'package p\nfunc (r *Ω) M(v int) int { return v }\n'},
  'expected_index': [{'file_path': 'method.go',
                      'qualified_name': 'Ω.M',
                      'name': 'M',
                      'kind': 'method',
                      'start_line': 2,
                      'end_line': 2}],
  'expected_ast_container': 'functions',
  'expected_written_parameter_type': 'int'},
 {'id': 'private-method-other-file',
  'files': {'type.go': 'package p\ntype R struct{}\n',
            'method.go': 'package p\nfunc (r *R) read(v string) string { return v }\n'},
  'expected_index': [{'file_path': 'method.go',
                      'qualified_name': 'R.read',
                      'name': 'read',
                      'kind': 'method',
                      'start_line': 2,
                      'end_line': 2}],
  'expected_ast_container': 'functions',
  'expected_written_parameter_type': 'string'},
 {'id': 'same-file-placement-control',
  'files': {'method.go': 'package p\ntype R struct{}\nfunc (r *R) M(v int) int { return v }\n'},
  'expected_index': [{'file_path': 'method.go',
                      'qualified_name': 'R.M',
                      'name': 'M',
                      'kind': 'method',
                      'start_line': 3,
                      'end_line': 3}],
  'expected_ast_container': 'classes.methods',
  'expected_written_parameter_type': 'int'},
 {'id': 'distinct-receivers-same-bare-method',
  'files': {'type.go': 'package p\ntype A struct{}\ntype B struct{}\n',
            'method.go': 'package p\n'
                         'func (a A) M(v int) int { return v }\n'
                         'func (b B) M(v int) int { return v }\n'},
  'expected_index': [{'file_path': 'method.go',
                      'qualified_name': 'A.M',
                      'name': 'M',
                      'kind': 'method',
                      'start_line': 2,
                      'end_line': 2},
                     {'file_path': 'method.go',
                      'qualified_name': 'B.M',
                      'name': 'M',
                      'kind': 'method',
                      'start_line': 3,
                      'end_line': 3}],
  'no_definition_collapse': True},
 {'id': 'same-receiver-name-distinct-packages',
  'files': {'one/type.go': 'package one\ntype R struct{}\n',
            'one/method.go': 'package one\nfunc (r R) M(v int) int { return v }\n',
            'two/type.go': 'package two\ntype R struct{}\n',
            'two/method.go': 'package two\nfunc (r R) M(v int) int { return v }\n'},
  'expected_index': [{'file_path': 'one/method.go',
                      'qualified_name': 'R.M',
                      'name': 'M',
                      'kind': 'method',
                      'start_line': 2,
                      'end_line': 2},
                     {'file_path': 'two/method.go',
                      'qualified_name': 'R.M',
                      'name': 'M',
                      'kind': 'method',
                      'start_line': 2,
                      'end_line': 2}],
  'exact_file_selection_required': True,
  'unfiltered_lookup_ambiguous': True},
 {'id': 'diff-one-of-two-same-name-receiver-methods',
  'files_before': {'type.go': 'package p\ntype A struct{}\ntype B struct{}\n',
                   'method.go': 'package p\n'
                                'func (a A) M(v int) int { return v }\n'
                                'func (b B) M(v int) int { return v }\n'},
  'files_after': {'type.go': 'package p\ntype A struct{}\ntype B struct{}\n',
                  'method.go': 'package p\n'
                               'func (a A) M(v string) string { return v }\n'
                               'func (b B) M(v int) int { return v }\n'},
  'expected_diff': [{'kind': 'modified', 'symbol_name': 'A.M', 'symbol_kind': 'method'}],
  'unaffected_method': 'B.M'},
 {'id': 'diff-receiver-only-identity-move',
  'files_before': {'type.go': 'package p\ntype A struct{}\ntype B struct{}\n',
                   'method.go': 'package p\nfunc (r A) M(v int) int { return v }\n'},
  'files_after': {'type.go': 'package p\ntype A struct{}\ntype B struct{}\n',
                  'method.go': 'package p\nfunc (r B) M(v int) int { return v }\n'},
  'expected_diff_set': [{'kind': 'removed', 'symbol_name': 'A.M', 'symbol_kind': 'method'},
                        {'kind': 'added', 'symbol_name': 'B.M', 'symbol_kind': 'method'}]}]


@pytest.mark.parametrize('case', CASES, ids=[case['id'] for case in CASES])
def test_go_crossfile_method_identity(tmp_path, record_property, case):
    versions = [case['files']] if 'files' in case else [case['files_before'], case['files_after']]
    parsed, trees, raw = [], [], []
    for files in versions:
        asts, native, extracted = {}, {}, {}
        for name, source in files.items():
            tree = syntax_tree(name, source, 'go')
            assert tree is not None
            native[name] = {'tree': str(tree.root_node), 'has_error': tree.root_node.has_error,
                            'end_byte': tree.root_node.end_byte, 'bytes': len(source.encode())}
            assert not tree.root_node.has_error and tree.root_node.end_byte == len(source.encode())
            asts[name] = parse_file(str(tmp_path / name), source)
            assert asts[name].parsing_tier == 'tree_sitter' and not asts[name].parse_failures
            extracted[name] = ts_parser.ts_parse_file(name, source, 'go')
        parsed.append(asts)
        trees.append(native)
        raw.append(extracted)
    record_property('sources', json.dumps(versions))
    record_property('native_trees', json.dumps(trees))
    record_property('raw', json.dumps(raw))
    record_property('asts', json.dumps([{k: asdict(v) for k, v in asts.items()} for asts in parsed]))
    record_property('qualified_input', 'true')
    if 'files_before' in case:
        changes = diff_file_ast(parsed[0]['method.go'], parsed[1]['method.go'])
        actual = sorted((c.kind, c.symbol_name, c.symbol_kind) for c in changes)
        wanted = case.get('expected_diff', case.get('expected_diff_set'))
        expected = sorted((c['kind'], c['symbol_name'], c['symbol_kind']) for c in wanted)
        record_property('diff', json.dumps([asdict(c) for c in changes]))
        assert actual == expected, 'REGRESSION: Go cross-file method identity'
        return
    for name, source in case['files'].items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    service = ASTService(str(tmp_path))
    try:
        service.initialize_skeleton(indexing_depth='eager')
        expected = case['expected_index']
        names = {row['name'] for row in expected}
        actual = [{key: getattr(loc, key) for key in expected[0]}
                  for name in case['files'] for loc in service.get_file_symbols(name) if loc.name in names]
        record_property('symbols', json.dumps(actual))
        assert actual == expected, 'REGRESSION: Go cross-file method identity'
        for row in expected:
            ast = parsed[0][row['file_path']]
            methods = [f for f in ast.functions if f.name == row['name']]
            if case.get('expected_ast_container') == 'classes.methods':
                assert not methods
                methods = [m for c in ast.classes for m in c.methods if m.name == row['name']]
            else:
                assert any(f.qualified_name == row['qualified_name'] and f.is_method for f in methods)
            method = next(f for f in methods if f.start_line == row['start_line'])
            assert method.end_line == row['end_line']
            parameter_type = case.get('expected_written_parameter_type', 'int')
            assert method.parameters[0].type_annotation == method.return_type == parameter_type
            assert any(loc.file_path == row['file_path'] and loc.start_line == row['start_line']
                       for loc in service.find_symbol(row['qualified_name']))
        if case.get('unfiltered_lookup_ambiguous'):
            assert len(service.find_symbol('R.M')) == 2
        if case.get('expected_ast_container') == 'functions':
            assert not parsed[0]['method.go'].classes
    finally:
        service.stop_hydration()
        service._store.close()
