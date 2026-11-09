"""Go signature syntax must reach raw metadata, FileAST and chunk consumers."""

import re

import pytest
from attocode_intel._internal.integrations.context.codebase_ast import parse_file
from attocode_intel._internal.integrations.context.syntax_evidence import syntax_tree
from attocode_intel._internal.integrations.context.ts_parser import ts_parse_file


def type_tokens(text):
    return re.findall(r'[A-Za-z_]\w*|\d+|[^\s]', text)


PREFIX = ('package sample\ntype Context struct{}\ntype Item struct{}\n'
          'type item int\ntype Receiver struct{}\n')


def go_function(declaration, record_property):
    source = PREFIX + declaration + '\n'
    tree = syntax_tree('signature.go', source, 'go')
    assert tree is not None and not tree.root_node.has_error
    assert tree.root_node.end_byte == len(source.encode())
    raw = ts_parse_file('signature.go', source, 'go')
    ast = parse_file('signature.go', source)
    assert ast.parsing_tier == 'tree_sitter'
    functions = [*raw['functions'], *(m for c in raw['classes'] for m in c['methods'])]
    converted = [*ast.functions, *(m for c in ast.classes for m in c.methods)]
    function = next(f for f in functions if f['name'] == 'consume')
    record_property('go_native_tree', str(tree.root_node))
    record_property('go_raw_function', repr(function))
    return function, next(f for f in converted if f.name == 'consume')


def assert_parameters(raw, function, expected):
    assert raw['parameters'] == [name for name, _, _ in expected]
    assert [p.name for p in function.parameters] == [name for name, _, _ in expected]
    assert set(raw.get('rest_parameters', [])) == {name for name, _, rest in expected if rest}
    for parameter, (name, annotation, rest) in zip(function.parameters, expected, strict=True):
        assert type_tokens(raw['param_types'][name]) == type_tokens(annotation)
        assert type_tokens(parameter.type_annotation) == type_tokens(annotation)
        assert parameter.is_rest is rest and not parameter.is_kwargs
        assert '/*' not in parameter.type_annotation and '//' not in parameter.type_annotation


@pytest.mark.parametrize('parameters,expected', [
    ('count int, label string', [('count', 'int', False), ('label', 'string', False)]),
    ('start, end int', [('start', 'int', False), ('end', 'int', False)]),
    ('values ...string', [('values', 'string', True)]),
    ('ctx *Context, callback func(value int) error',
     [('ctx', '*Context', False), ('callback', 'func(value int) error', False)]),
    ('values []string, lookup map[string]*Item',
     [('values', '[]string', False), ('lookup', 'map[string]*Item', False)]),
    ('receive <-chan int, send chan<- int', [('receive', '<-chan int', False), ('send', 'chan<- int', False)]),
    ('self int, cls string', [('self', 'int', False), ('cls', 'string', False)]),
    ('first /* name */, second /* type */ int', [('first', 'int', False), ('second', 'int', False)]),
    ('lookup map[/* key */string] /* pointer */ *Item', [('lookup', 'map[string]*Item', False)]),
    ('handlers ...func(value int) error', [('handlers', 'func(value int) error', True)]),
    ('item item', [('item', 'item', False)]),
    ('values [3]int', [('values', '[3]int', False)]),
    ('reader interface { Read(buffer []byte) (int, error) }',
     [('reader', 'interface { Read(buffer []byte) (int, error) }', False)]),
    ('_, count int, _ string', [('count', 'int', False)]),
    ('items []struct { Value int }', [('items', '[]struct { Value int }', False)]),
    ('callback func(first, second int) (value int, err error)',
     [('callback', 'func(first, second int) (value int, err error)', False)]),
])
def test_go_named_grouped_and_variadic_parameters(parameters, expected, record_property):
    raw, function = go_function('func consume(' + parameters + ') {}', record_property)
    assert_parameters(raw, function, expected)


@pytest.mark.parametrize('parameters', ['', 'int, string', '_ int, _ string', '...string'])
def test_go_unnamed_or_blank_parameters_do_not_invent_bindings(parameters, record_property):
    raw, function = go_function('func consume(' + parameters + ') {}', record_property)
    assert_parameters(raw, function, [])


@pytest.mark.parametrize('result,expected', [
    ('', ''), ('int', 'int'), ('*Item', '*Item'), ('(int, error)', '(int, error)'),
    ('(count int, err error)', '(count int, err error)'), ('<-chan int', '<-chan int'),
    ('map[string]*Item', 'map[string]*Item'),
    ('(value /* type */ int, err error)', '(value int, err error)'),
])
def test_go_source_written_result_types(result, expected, record_property):
    raw, function = go_function('func consume() ' + result + ' { panic("unused") }', record_property)
    assert_parameters(raw, function, [])
    assert type_tokens(raw['return_type']) == type_tokens(expected)
    assert type_tokens(function.return_type) == type_tokens(expected)


def test_go_type_parameters_are_not_value_parameters(record_property):
    raw, function = go_function('func consume[T any](value T, values []T) T { panic("unused") }', record_property)
    assert_parameters(raw, function, [('value', 'T', False), ('values', '[]T', False)])
    assert raw['return_type'] == function.return_type == 'T'


@pytest.mark.parametrize('receiver', ['r *Receiver', 'r Receiver'])
def test_go_receiver_is_not_an_input_parameter(receiver, record_property):
    raw, function = go_function('func (' + receiver + ') consume(value int) string { panic("unused") }', record_property)
    assert_parameters(raw, function, [('value', 'int', False)])
    assert raw['return_type'] == function.return_type == 'string'


def test_go_interface_method_signature(record_property):
    raw, function = go_function('type Service interface { consume(first, second int, remaining ...string) (int, error) }', record_property)
    assert_parameters(raw, function, [('first', 'int', False), ('second', 'int', False), ('remaining', 'string', True)])
    assert type_tokens(raw['return_type']) == type_tokens(function.return_type) == type_tokens('(int, error)')


def test_go_signature_reaches_chunk_metadata():
    from attocode_intel._internal.integrations.context.ast_chunker import chunk_file

    source = 'package sample\nfunc consume(count int, label string) (int, error) { panic("unused") }\n'
    chunks = chunk_file('signature.go', 'signature.go', content=source)
    function = next(c for c in chunks if c.chunk_type == 'function' and c.name == 'consume')
    assert 'consume(count, label)' in function.metadata and '-> (int, error)' in function.metadata
