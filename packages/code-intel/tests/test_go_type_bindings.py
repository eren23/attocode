"""Native Go named types retain module scope, individual ranges and method ownership."""
import json
from dataclasses import asdict

import pytest
from attocode_intel._internal.integrations.context import ts_parser
from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel._internal.integrations.context.codebase_ast import parse_file
from attocode_intel._internal.integrations.context.syntax_evidence import syntax_tree


@pytest.mark.parametrize('case', [
    pytest.param({'source': 'type Item struct{}\n',
                  'types': [('Item', 'type Item struct{}', 1)]}, id='single-struct'),
    pytest.param({'source': 'type Reader interface {\n Read(data []byte) (n int, err error)\n}\n',
                  'types': [('Reader', 'type Reader interface {', 3)], 'methods': {'Reader': ['Read']},
                  'signature': {'Reader.Read': {'params': ['data'], 'types': {'data': '[]byte'},
                                               'return': '(n int, err error)', 'visibility': 'public'}}},
                 id='single-interface'),
    pytest.param({'source': 'type Count int\n', 'types': [('Count', 'type Count int', 1)]},
                 id='single-primitive'),
    pytest.param({'source': 'type Copy = int\n', 'types': [('Copy', 'type Copy = int', 1)]},
                 id='single-alias'),
    pytest.param({'source': 'type (\n First struct{}\n Second struct{}\n)\n',
                  'types': [('First', ' First struct{}', 1), ('Second', ' Second struct{}', 1)]},
                 id='grouped-structs'),
    pytest.param({'source': 'type (\n Reader interface {\n  Read(data []byte) int\n }\n'
                           ' Writer interface {\n  Write(data []byte) int\n }\n)\n',
                  'types': [('Reader', ' Reader interface {', 3), ('Writer', ' Writer interface {', 3)],
                  'methods': {'Reader': ['Read'], 'Writer': ['Write']}}, id='grouped-interfaces'),
    pytest.param({'source': 'type (\n Item struct{}\n Runner interface {\n  Run()\n }\n)\n',
                  'types': [('Item', ' Item struct{}', 1), ('Runner', ' Runner interface {', 3)],
                  'methods': {'Runner': ['Run']}}, id='mixed-group'),
    pytest.param({'source': 'type (\n)\n', 'types': []}, id='empty-group'),
    pytest.param({'source': 'type (\n First = int\n Second = string\n)\n',
                  'types': [('First', ' First = int', 1), ('Second', ' Second = string', 1)]},
                 id='grouped-aliases'),
    pytest.param({'source': 'type (\n Item struct{}\n Copy = Item\n)\n',
                  'types': [('Item', ' Item struct{}', 1), ('Copy', ' Copy = Item', 1)]},
                 id='alias-and-definition'),
    pytest.param({'source': 'type _ struct{}\n', 'types': []}, id='blank-type'),
    pytest.param({'source': 'type (\n _ struct{}\n Visible int\n)\n',
                  'types': [('Visible', ' Visible int', 1)]}, id='blank-and-visible'),
    pytest.param({'source': 'func outer() {\n type Hidden struct{}\n}\n',
                  'types': [], 'functions': ['outer']}, id='function-local'),
    pytest.param({'source': 'type Shared struct{}\nfunc outer() {\n type Shared int\n}\n',
                  'types': [('Shared', 'type Shared struct{}', 1)], 'functions': ['outer']},
                 id='local-shadow'),
    pytest.param({'source': 'func outer() {\n if true {\n  type Hidden struct{}\n }\n}\n',
                  'types': [], 'functions': ['outer']}, id='nested-local'),
    pytest.param({'source': 'var Handler = func() {\n type Hidden struct{}\n}\n', 'types': []},
                 id='initializer-local'),
    pytest.param({'source': 'type Box[T any] struct{ Value T }\n',
                  'types': [('Box', 'type Box[T any] struct{ Value T }', 1)]}, id='generic-type-name'),
    pytest.param({'source': 'type Container struct {\n Named struct{ Value int }\n'
                           ' Embedded interface {\n  Hidden()\n }\n}\n',
                  'types': [('Container', 'type Container struct {', 6)]}, id='rhs-field-decoys'),
    pytest.param({'source': 'func (v *Thing) Run(value int) string { return "" }\ntype Thing struct{}\n',
                  'types': [('Thing', 'type Thing struct{}', 1)], 'methods': {'Thing': ['Run']}},
                 id='forward-receiver'),
    pytest.param({'source': 'type (\n First struct{}\n Second struct{}\n)\nfunc (v *Second) Run() {}\n',
                  'types': [('First', ' First struct{}', 1), ('Second', ' Second struct{}', 1)],
                  'methods': {'Second': ['Run']}}, id='group-receiver-owner'),
    pytest.param({'source': 'func (v *Elsewhere) Run() {}\n', 'types': [], 'functions': ['Run']},
                 id='unmatched-receiver'),
    pytest.param({'source': 'type Sealed interface {\n seal()\n}\n',
                  'types': [('Sealed', 'type Sealed interface {', 3)], 'methods': {'Sealed': ['seal']},
                  'signature': {'Sealed.seal': {'params': [], 'types': {}, 'return': '', 'visibility': 'private'}}},
                 id='private-interface-method'),
    pytest.param({'source': '// Shared declaration.\ntype (\n // First has its own doc.\n First struct{}\n'
                           ' Second struct{}\n)\n',
                  'types': [('First', ' First struct{}', 1), ('Second', ' Second struct{}', 1)],
                  'docs': {'First': 'First has its own doc.', 'Second': 'Shared declaration.'}},
                 id='individual-and-shared-docs'),
    pytest.param({'source': 'func (v *Second) Run() {}\ntype (\n First struct{}\n Second struct{}\n)\n',
                  'types': [('First', ' First struct{}', 1), ('Second', ' Second struct{}', 1)],
                  'methods': {'Second': ['Run']}, 'full_traversal': True}, id='query-fallback'),
    pytest.param({'source': 'type (\n Café struct{}\n Ω = int\n)\n',
                  'types': [('Café', ' Café struct{}', 1), ('Ω', ' Ω = int', 1)]}, id='unicode-names'),
    pytest.param({'source': 'type (\n A int // A trailing comment.\n B string\n)\n',
                  'types': [('A', ' A int // A trailing comment.', 1), ('B', ' B string', 1)],
                  'docs': {'A': '', 'B': ''}}, id='trailing-group-comment'),
    pytest.param({'source': 'type (\n A int // A trailing comment.\n // B has its own doc.\n B string\n)\n',
                  'types': [('A', ' A int // A trailing comment.', 1), ('B', ' B string', 1)],
                  'docs': {'A': '', 'B': 'B has its own doc.'}}, id='trailing-before-leading-doc'),
    pytest.param({'source': '// Shared declaration.\ntype (\n A int // A trailing comment.\n B string\n)\n',
                  'types': [('A', ' A int // A trailing comment.', 1), ('B', ' B string', 1)],
                  'docs': {'A': 'Shared declaration.', 'B': 'Shared declaration.'}}, id='trailing-with-shared-doc'),
    pytest.param({'source': 'type A int // A trailing comment.\ntype B string\n',
                  'types': [('A', 'type A int // A trailing comment.', 1), ('B', 'type B string', 1)],
                  'docs': {'A': '', 'B': ''}}, id='trailing-between-declarations'),
    pytest.param({'source': 'var X int // X trailing comment.\nfunc Run() {}\n', 'types': [],
                  'functions': ['Run'], 'function_docs': {'Run': ''}}, id='trailing-before-function'),
    pytest.param({'source': 'type Reader (interface {\n Read(p []byte) int\n})\n',
                  'types': [('Reader', 'type Reader (interface {', 3)], 'methods': {'Reader': ['Read']},
                  'signature': {'Reader.Read': {'params': ['p'], 'types': {'p': '[]byte'},
                                               'return': 'int', 'visibility': 'public'}}}, id='parenthesized-interface'),
    pytest.param({'source': 'type Reader = (interface {\n Read(p []byte) int\n})\n',
                  'types': [('Reader', 'type Reader = (interface {', 3)], 'methods': {'Reader': ['Read']}},
                 id='parenthesized-alias-interface'),
    pytest.param({'source': 'type Reader ( /* transparent */ (interface {\n Read(p []byte) int\n}))\n',
                  'types': [('Reader', 'type Reader ( /* transparent */ (interface {', 3)],
                  'methods': {'Reader': ['Read']}}, id='nested-parentheses-comment'),
    pytest.param({'source': 'type Handler (func() interface {\n Hidden()\n})\n',
                  'types': [('Handler', 'type Handler (func() interface {', 3)]}, id='parenthesized-rhs-decoy'),
    pytest.param({'source': '// Item on its own line.\ntype\nItem struct{}\n',
                  'types': [('Item', 'Item struct{}', 1)], 'docs': {'Item': 'Item on its own line.'}},
                 id='multiline-single-name-range'),
])
def test_go_named_types_reach_metadata_and_index(tmp_path, monkeypatch, record_property, case):
    name = 'types.go'
    source = 'package sample\nfunc Sentinel() {}\n' + case['source']
    if case.get('full_traversal'):
        monkeypatch.setattr(ts_parser, '_go_declaration_paths', lambda *args: None)
    expected = []
    lines = source.splitlines()
    for symbol, header, span in case['types']:
        assert lines.count(header) == 1, 'Fixture header must locate a unique literal declaration'
        start = lines.index(header) + 1
        expected.append((symbol, start, start + span - 1))
    tree = syntax_tree(name, source, 'go')
    record_property('native_tree', str(tree.root_node) if tree else '')
    assert tree is not None and not tree.root_node.has_error
    assert tree.root_node.end_byte == len(source.encode())
    raw = ts_parser.ts_parse_file(name, source, 'go')
    ast = parse_file(name, source)
    assert ast.parsing_tier == 'tree_sitter' and any(f.name == 'Sentinel' for f in ast.functions)
    record_property('expected_types', json.dumps(expected))
    record_property('raw_classes', json.dumps(raw['classes']))
    record_property('raw_functions', json.dumps(raw['functions']))
    record_property('ast_classes', json.dumps([asdict(c) for c in ast.classes]))
    record_property('ast_functions', json.dumps([asdict(f) for f in ast.functions]))
    record_property('expected_methods', json.dumps(case.get('methods', {})))
    record_property('expected_functions', json.dumps(['Sentinel'] + case.get('functions', [])))
    (tmp_path / name).write_text(source)
    service = ASTService(str(tmp_path))
    try:
        service.initialize_skeleton(indexing_depth='eager')
        locations = service.get_file_symbols(name)
        record_property('indexed_symbols', json.dumps([asdict(loc) for loc in locations]))
        record_property('cached_classes', json.dumps([asdict(c) for c in service._ast_cache[name].classes]))
        record_property('cached_functions', json.dumps([asdict(f) for f in service._ast_cache[name].functions]))
        assert any(loc.name == 'Sentinel' and loc.kind == 'function' for loc in locations)
        assert [(c['name'], c['start_line'], c['end_line']) for c in raw['classes']] == expected
        assert [(c.name, c.start_line, c.end_line) for c in ast.classes] == expected
        assert [asdict(c) for c in service._ast_cache[name].classes] == [asdict(c) for c in ast.classes]
        assert [asdict(f) for f in service._ast_cache[name].functions] == [asdict(f) for f in ast.functions]
        assert sorted((loc.name, loc.start_line, loc.end_line) for loc in locations if loc.kind == 'class') == sorted(expected)
        assert [f['name'] for f in raw['functions']] == [f.name for f in ast.functions] == ['Sentinel'] + case.get('functions', [])
        for cls, raw_cls in zip(ast.classes, raw['classes'], strict=True):
            methods = case.get('methods', {}).get(cls.name, [])
            assert [m.name for m in cls.methods] == [m['name'] for m in raw_cls['methods']] == methods
            assert all(m['parent_class'] == cls.name for m in raw_cls['methods'])
            for method in methods:
                assert any(loc.qualified_name == cls.name + '.' + method and loc.kind == 'method' for loc in locations)
            if cls.name in case.get('docs', {}):
                assert cls.docstring == raw_cls.get('docstring', '') == case['docs'][cls.name]
            for method, raw_method in zip(cls.methods, raw_cls['methods'], strict=True):
                signature = case.get('signature', {}).get(cls.name + '.' + method.name)
                if signature is not None:
                    assert raw_method['parameters'] == [p.name for p in method.parameters] == signature['params']
                    assert raw_method.get('param_types', {}) == {p.name: p.type_annotation for p in method.parameters} == signature['types']
                    assert raw_method['return_type'] == method.return_type == signature['return']
                    assert raw_method['visibility'] == method.visibility == signature['visibility']
        for function, raw_function in zip(ast.functions, raw['functions'], strict=True):
            if function.name in case.get('function_docs', {}):
                assert function.docstring == raw_function.get('docstring', '') == case['function_docs'][function.name]
    finally:
        service.stop_hydration()
        service._store.close()
