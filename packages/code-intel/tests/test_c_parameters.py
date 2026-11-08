"""Modern C named parameters must survive native parsing and AST conversion."""

import re

import pytest
from attocode_intel._internal.integrations.context.codebase_ast import parse_file
from attocode_intel._internal.integrations.context.syntax_evidence import syntax_tree
from attocode_intel._internal.integrations.context.ts_parser import ts_parse_file


def type_tokens(text):
    # Whitespace may vary; separate C identifier tokens must remain separate.
    return re.findall(r'[A-Za-z_]\w*|\d+|[^\s]', text)


def c_function(parameters):
    source = 'typedef int item;\nvoid consume(' + parameters + ') {}\n'
    tree = syntax_tree('parameters.c', source, 'c')
    assert tree is not None and not tree.root_node.has_error
    assert tree.root_node.end_byte == len(source.encode())
    raw = ts_parse_file('parameters.c', source, 'c')
    function = next(f for f in raw['functions'] if f['name'] == 'consume')
    ast = parse_file('parameters.c', source)
    assert ast.parsing_tier == 'tree_sitter'
    return function, next(f for f in ast.functions if f.name == 'consume'), str(tree.root_node)


@pytest.mark.parametrize('parameters,expected', [
    ('int count, const char *label', [('count', 'int'), ('label', 'const char*')]),
    ('char **values, void *context', [('values', 'char**'), ('context', 'void*')]),
    ('const unsigned char bytes[64]', [('bytes', 'const unsigned char[64]')]),
    ('int n, int values[n]', [('n', 'int'), ('values', 'int[n]')]),
    ('int (*callback)(const char *value), int state', [('callback', 'int (*)(const char *value)'), ('state', 'int')]),
    ('item item', [('item', 'item')]),
    ('register /* storage note */ const unsigned char *bytes', [('bytes', 'const unsigned char*')]),
    ('unsigned /* type note */ char *bytes', [('bytes', 'unsigned char*')]),
    ('int self, int cls', [('self', 'int'), ('cls', 'int')]),
    ('int (* /* name note */ callback)(int ignored)', [('callback', 'int (*)(int ignored)')]),
    ('const unsigned char bytes[static restrict 16]', [('bytes', 'const unsigned char[static restrict 16]')]),
    ('const char *label, ...', [('label', 'const char*')]),
    ('int count [[maybe_unused]], const char *label', [('count', 'int'), ('label', 'const char*')]),
    ('int (*callback)(register int ignored)', [('callback', 'int (*)(int ignored)')]),
    ('int (count), int ((size))', [('count', 'int'), ('size', 'int')]),
])
def test_c_named_parameter_names_types_and_order(parameters, expected, record_property):
    raw, function, tree = c_function(parameters)
    record_property('c_native_tree', tree)
    record_property('c_raw_function', repr(raw))
    assert raw['parameters'] == [name for name, _ in expected]
    assert [p.name for p in function.parameters] == [name for name, _ in expected]
    for parameter, (name, annotation) in zip(function.parameters, expected, strict=True):
        assert type_tokens(raw['param_types'][name]) == type_tokens(annotation)
        assert type_tokens(parameter.type_annotation) == type_tokens(annotation)
        assert not parameter.is_rest and not parameter.is_kwargs
        assert '/*' not in parameter.type_annotation and '//' not in parameter.type_annotation


@pytest.mark.parametrize('parameters', ['', 'void', 'int, const char *'])
def test_c_unnamed_or_void_parameters_do_not_invent_names(parameters):
    raw, function, _ = c_function(parameters)
    assert raw['parameters'] == [] and function.parameters == []


def test_c_names_reach_function_chunk_metadata():
    from attocode_intel._internal.integrations.context.ast_chunker import chunk_file

    source = 'void consume(int count, const char *label) {}\n'
    chunks = chunk_file('parameters.c', 'parameters.c', content=source)
    function = next(c for c in chunks if c.chunk_type == 'function' and c.name == 'consume')
    assert 'consume(count, label)' in function.metadata
