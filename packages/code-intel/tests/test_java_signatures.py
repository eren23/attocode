"""Java signature metadata must survive native parsing and AST conversion."""

import pytest
from attocode_intel._internal.integrations.context.codebase_ast import parse_file
from attocode_intel._internal.integrations.context.syntax_evidence import syntax_tree
from attocode_intel._internal.integrations.context.ts_parser import ts_parse_file


def java_method(source, name='collect'):
    tree = syntax_tree('Signature.java', source, 'java')
    assert tree is not None and not tree.root_node.has_error
    assert tree.root_node.end_byte == len(source.encode())
    raw = ts_parse_file('Signature.java', source, 'java')
    native_class = next(c for c in raw['classes'] if c['name'] == 'Signature')
    native_method = next(m for m in native_class['methods'] if m['name'] == name)
    ast = parse_file('Signature.java', source)
    assert ast.parsing_tier == 'tree_sitter'
    cls = next(c for c in ast.classes if c.name == 'Signature')
    return native_method, next(m for m in cls.methods if m.name == name)


@pytest.mark.parametrize('declaration,component_type,name', [
    ('String... values', 'String', 'values'),
    ('int... values', 'int', 'values'),
    ('java.util.List<String>... values', 'java.util.List<String>', 'values'),
    ('String[]... values', 'String[]', 'values'),
    ('@Sensitive final String... values', 'String', 'values'),
    ('@Sensitive final /* type comment */ String... values', 'String', 'values'),
    ('@Sensitive final // type comment\nString... values', 'String', 'values'),
    ('String... $values', 'String', '$values'),
])
def test_java_varargs_name_type_and_rest_flag(declaration, component_type, name):
    source = ('@interface Sensitive {}\nclass Signature {\n'
              '  Object collect(String label, ' + declaration + ') { return null; }\n}\n')
    raw, method = java_method(source)
    assert raw['parameters'] == ['label', name]
    assert raw['param_types'] == {'label': 'String', name: component_type}
    assert [(p.name, p.type_annotation, p.is_rest) for p in method.parameters] == [
        ('label', 'String', False), (name, component_type, True),
    ]


@pytest.mark.parametrize('written,suffix,expected,body', [
    ('void', '', 'void', ''),
    ('int', '', 'int', 'return 0;'),
    ('java.util.List<T>', '', 'java.util.List<T>', 'return null;'),
    ('T[]', '', 'T[]', 'return null;'),
    ('T', '[]', 'T[]', 'return null;'),
])
def test_java_method_return_type(written, suffix, expected, body):
    source = 'class Signature<T> {\n  ' + written + ' collect()' + suffix + ' { ' + body + ' }\n}\n'
    raw, method = java_method(source)
    assert raw['return_type'] == method.return_type == expected
    assert method.parameters == []


def test_java_constructor_varargs_has_no_return_type():
    raw, constructor = java_method('class Signature {\n  Signature(String... values) {}\n}\n', 'Signature')
    assert raw['return_type'] == constructor.return_type == ''
    assert [(p.name, p.type_annotation, p.is_rest) for p in constructor.parameters] == [('values', 'String', True)]


def test_java_annotated_trailing_return_dimensions():
    source = ('@java.lang.annotation.Target(java.lang.annotation.ElementType.TYPE_USE)\n'
              '@interface Sensitive {}\nclass Signature<T> {\n'
              '  T collect() @Sensitive [] { return null; }\n}\n')
    raw, method = java_method(source)
    assert raw['return_type'] == method.return_type == 'T @Sensitive []'


def test_java_array_parameter_is_not_varargs():
    raw, method = java_method('class Signature {\n  void collect(String[] values, int count) {}\n}\n')
    assert raw['parameters'] == ['values', 'count']
    assert [(p.name, p.type_annotation, p.is_rest) for p in method.parameters] == [
        ('values', 'String[]', False), ('count', 'int', False),
    ]


def test_java_signature_reaches_method_chunk_metadata():
    from attocode_intel._internal.integrations.context.ast_chunker import chunk_file

    source = 'class Signature {\n  String[] collect(String first, String... remaining) { return null; }\n}\n'
    chunks = chunk_file('Signature.java', 'Signature.java', content=source)
    method = next(c for c in chunks if c.chunk_type == 'method' and c.name == 'Signature.collect')
    assert 'collect(first, remaining)' in method.metadata
    assert '-> String[]' in method.metadata


@pytest.mark.parametrize('path,source,expected', [
    ('typed.py', 'def collect(label: str, count: int) -> str:\n    return label\n', [('label', 'str'), ('count', 'int')]),
    ('typed.ts', 'export function collect(label: string, count: number): string { return label; }\n', [('label', 'string'), ('count', 'number')]),
])
def test_existing_typed_parameter_and_return_paths(path, source, expected):
    ast = parse_file(path, source)
    method = next(f for f in ast.functions if f.name == 'collect')
    assert [(p.name, p.type_annotation) for p in method.parameters] == expected
    assert method.return_type == expected[0][1]
