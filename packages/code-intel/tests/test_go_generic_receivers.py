"""Native same-file receiver ownership retains generic bases and signatures."""
import json
from dataclasses import asdict

import pytest
from attocode_intel._internal.integrations.context import ts_parser
from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel._internal.integrations.context.codebase_ast import parse_file
from attocode_intel._internal.integrations.context.syntax_evidence import syntax_tree


@pytest.mark.parametrize('case', [
    pytest.param({'source': 'type Box struct{}\nfunc (x Box) Run() {}\n',
                  'types': ['Box'], 'methods': {'Box': ['Run']}}, id='plain-value'),
    pytest.param({'source': 'type Box struct{}\nfunc (x *Box) Run() {}\n',
                  'types': ['Box'], 'methods': {'Box': ['Run']}}, id='plain-pointer'),
    pytest.param({'source': 'type Box[T any] struct{}\nfunc (x Box[T]) Run() {}\n',
                  'types': ['Box'], 'methods': {'Box': ['Run']}}, id='generic-value'),
    pytest.param({'source': 'type Box[T any] struct{}\nfunc (x *Box[T]) Run() {}\n',
                  'types': ['Box'], 'methods': {'Box': ['Run']}}, id='generic-pointer'),
    pytest.param({'source': 'func (x *Box[T]) Run() {}\ntype Box[T any] struct{}\n',
                  'types': ['Box'], 'methods': {'Box': ['Run']}}, id='forward-generic-pointer'),
    pytest.param({'source': 'type (\n First[T any] struct{}\n Second[T any] struct{}\n)\n'
                           'func (x *Second[T]) Run() {}\n',
                  'types': ['First', 'Second'], 'methods': {'Second': ['Run']}}, id='grouped-owner'),
    pytest.param({'source': 'type Pair[K comparable, V any] struct{}\n'
                           'func (x Pair[K, V]) Get(key K) V { var v V; return v }\n',
                  'types': ['Pair'], 'methods': {'Pair': ['Get']},
                  'signatures': {'Pair.Get': {'names': ['key'], 'types': {'key': 'K'}, 'return': 'V'}}},
                 id='multiple-type-parameters'),
    pytest.param({'source': 'type Box[T any] struct{}\n'
                           'func (x *Box[Element]) Get(value Element) Element { return value }\n',
                  'types': ['Box'], 'methods': {'Box': ['Get']},
                  'signatures': {'Box.Get': {'names': ['value'], 'types': {'value': 'Element'}, 'return': 'Element'}}},
                 id='renamed-receiver-type-parameter'),
    pytest.param({'source': 'type Box[T any] struct{}\nfunc (*Box[T]) Run() {}\n',
                  'types': ['Box'], 'methods': {'Box': ['Run']}}, id='unnamed-generic-receiver'),
    pytest.param({'source': 'type Box[T any] struct{}\nfunc (_ *Box[T]) Run() {}\n',
                  'types': ['Box'], 'methods': {'Box': ['Run']}}, id='blank-receiver-variable'),
    pytest.param({'source': 'type Box[T any] struct{}\n'
                           'func (x * /* pointer */ Box[ /* argument */ T]) Run() {}\n',
                  'types': ['Box'], 'methods': {'Box': ['Run']}}, id='receiver-comments'),
    pytest.param({'source': 'type Ωμέγα[Τ any] struct{}\nfunc (x Ωμέγα[Τ]) κρυφό() {}\n',
                  'types': ['Ωμέγα'], 'methods': {'Ωμέγα': ['κρυφό']},
                  'visibility': {'Ωμέγα.κρυφό': 'private'}}, id='unicode-private-method'),
    pytest.param({'source': 'type Δοχείο[T any] struct{}\nfunc (x *Δοχείο[T]) Read() {}\n',
                  'types': ['Δοχείο'], 'methods': {'Δοχείο': ['Read']}}, id='unicode-public-owner'),
    pytest.param({'source': 'type Argument struct{}\ntype Box[T any] struct{}\n'
                           'func (x *Box[Argument]) Get(value Argument) Argument { return value }\n',
                  'types': ['Argument', 'Box'], 'methods': {'Box': ['Get']},
                  'signatures': {'Box.Get': {'names': ['value'], 'types': {'value': 'Argument'}, 'return': 'Argument'}}},
                 id='type-argument-owner-decoy'),
    pytest.param({'source': 'type Box[T any] struct{}\n'
                           'func (x *Box[T]) Run() { type Box int; _ = Box(1) }\n',
                  'types': ['Box'], 'methods': {'Box': ['Run']}}, id='local-type-shadow'),
    pytest.param({'source': 'type Box[T any] struct{}\ntype Plain struct{}\n'
                           'func (x *Plain) Get(value Box[int]) Box[int] { return value }\n',
                  'types': ['Box', 'Plain'], 'methods': {'Plain': ['Get']},
                  'signatures': {'Plain.Get': {'names': ['value'], 'types': {'value': 'Box[int]'}, 'return': 'Box[int]'}}},
                 id='ordinary-owner-generic-signature'),
    pytest.param({'source': 'func (x *Box[T]) Run() {}\ntype Box[T any] struct{}\n',
                  'types': ['Box'], 'methods': {'Box': ['Run']}, 'full_traversal': True}, id='query-fallback'),
    pytest.param({'source': 'func (x *Elsewhere[T]) Run() {}\n', 'types': [], 'methods': {},
                  'functions': ['Run'], 'other_source': 'package sample\ntype Elsewhere[T any] struct{}\n'},
                 id='cross-file-owner-retains-fallback'),
    pytest.param({'source': 'func Run() {}\ntype Box[T any] struct{}\nfunc (x *Box[T]) Run() {}\n',
                  'types': ['Box'], 'methods': {'Box': ['Run']}, 'functions': ['Run']},
                 id='free-function-name-collision'),
    pytest.param({'source': 'type Box[T any] struct{}\n'
                           'func (x *Box[T]) Map(first, second T, rest ...T) (out T, ok bool) { return first, true }\n',
                  'types': ['Box'], 'methods': {'Box': ['Map']},
                  'signatures': {'Box.Map': {'names': ['first', 'second', 'rest'],
                                           'types': {'first': 'T', 'second': 'T', 'rest': 'T'},
                                           'return': '(out T, ok bool)', 'rest': ['rest']}}},
                 id='grouped-variadic-signature'),
    pytest.param({'source': 'type Box[T any] struct{}\nfunc (x (Box[T])) Run() {}\n',
                  'types': ['Box'], 'methods': {'Box': ['Run']}}, id='parenthesized-generic-value'),
    pytest.param({'source': 'type Box[T any] struct{}\nfunc (x (*Box[T])) Run() {}\n',
                  'types': ['Box'], 'methods': {'Box': ['Run']}}, id='parenthesized-generic-pointer'),
    pytest.param({'source': 'type Box[T any] struct{}\nfunc (x *(Box[T])) Run() {}\n',
                  'types': ['Box'], 'methods': {'Box': ['Run']}}, id='pointer-to-parenthesized-generic'),
    pytest.param({'source': 'type Box[T any] struct{}\n'
                           'func (x ( /* outer */ (* /* pointer */ (Box[T])))) Run() {}\n',
                  'types': ['Box'], 'methods': {'Box': ['Run']}}, id='nested-receiver-wrappers-comments'),
    pytest.param({'source': 'type Box struct{}\nfunc (x (Box)) Run() {}\n',
                  'types': ['Box'], 'methods': {'Box': ['Run']}}, id='parenthesized-plain-value'),
    pytest.param({'source': 'type Box struct{}\nfunc (x (*Box)) Run() {}\n',
                  'types': ['Box'], 'methods': {'Box': ['Run']}}, id='parenthesized-plain-pointer'),
])
def test_go_generic_receivers_reach_owner_and_index(tmp_path, monkeypatch, record_property, case):
    name = 'receivers.go'
    source = 'package sample\nfunc Sentinel() {}\n' + case['source']
    if case.get('full_traversal'):
        monkeypatch.setattr(ts_parser, '_go_declaration_paths', lambda *args: None)
    tree = syntax_tree(name, source, 'go')
    record_property('native_tree', str(tree.root_node) if tree else '')
    assert tree is not None and not tree.root_node.has_error
    assert tree.root_node.end_byte == len(source.encode())
    raw = ts_parser.ts_parse_file(name, source, 'go')
    ast = parse_file(str(tmp_path / name), source)
    assert ast.parsing_tier == 'tree_sitter' and any(f.name == 'Sentinel' for f in ast.functions)
    record_property('expected_types', json.dumps(case['types']))
    record_property('expected_methods', json.dumps(case['methods']))
    record_property('expected_functions', json.dumps(['Sentinel'] + case.get('functions', [])))
    record_property('raw_classes', json.dumps(raw['classes']))
    record_property('raw_functions', json.dumps(raw['functions']))
    record_property('ast_classes', json.dumps([asdict(c) for c in ast.classes]))
    record_property('ast_functions', json.dumps([asdict(f) for f in ast.functions]))
    record_property('native_receivers', json.dumps([
        {'name': node.child_by_field_name('name').text.decode(),
         'receiver_tree': str(node.child_by_field_name('receiver')),
         'extracted_owner': ts_parser._extract_go_receiver(node, source.encode())}
        for node in tree.root_node.named_children if node.type == 'method_declaration']))
    (tmp_path / name).write_text(source)
    if case.get('other_source'):
        (tmp_path / 'other.go').write_text(case['other_source'])
    service = ASTService(str(tmp_path))
    try:
        service.initialize_skeleton(indexing_depth='eager')
        locations = service.get_file_symbols(name)
        record_property('indexed_symbols', json.dumps([asdict(loc) for loc in locations]))
        record_property('cached_ast', json.dumps(asdict(service._ast_cache[name])))
        assert any(loc.name == 'Sentinel' and loc.kind == 'function' for loc in locations)
        assert [c['name'] for c in raw['classes']] == [c.name for c in ast.classes] == case['types']
        assert asdict(service._ast_cache[name]) == asdict(ast)
        assert [f['name'] for f in raw['functions']] == [f.name for f in ast.functions] == ['Sentinel'] + case.get('functions', [])
        for cls, raw_cls in zip(ast.classes, raw['classes'], strict=True):
            methods = case['methods'].get(cls.name, [])
            assert [m.name for m in cls.methods] == [m['name'] for m in raw_cls['methods']] == methods
            for method, raw_method in zip(cls.methods, raw_cls['methods'], strict=True):
                qualified = cls.name + '.' + method.name
                assert raw_method['parent_class'] == cls.name
                assert method.start_line == raw_method['start_line']
                assert method.end_line == raw_method['end_line']
                assert method.visibility == raw_method['visibility'] == case.get('visibility', {}).get(qualified, 'public')
                assert any(loc.qualified_name == qualified and loc.kind == 'method' and
                           loc.start_line == method.start_line and loc.end_line == method.end_line for loc in locations)
                signature = case.get('signatures', {}).get(qualified)
                if signature is not None:
                    assert raw_method['parameters'] == [p.name for p in method.parameters] == signature['names']
                    assert raw_method.get('param_types', {}) == {p.name: p.type_annotation for p in method.parameters} == signature['types']
                    assert raw_method['return_type'] == method.return_type == signature['return']
                    assert raw_method.get('rest_parameters', []) == signature.get('rest', [])
                    assert [p.name for p in method.parameters if p.is_rest] == signature.get('rest', [])
    finally:
        service.stop_hydration()
        service._store.close()
