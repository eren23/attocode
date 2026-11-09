"""Only declared Go module bindings belong in the global AST/index."""

import json

import pytest
from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel._internal.integrations.context.codebase_ast import parse_file
from attocode_intel._internal.integrations.context.syntax_evidence import syntax_tree
from attocode_intel._internal.integrations.context.ts_parser import ts_parse_file


@pytest.mark.parametrize('declaration,expected', [
    pytest.param('var Global int\n', ['Global'], id='single-var'),
    pytest.param('const Limit = 3\n', ['Limit'], id='single-const'),
    pytest.param('var First, Second int\n', ['First', 'Second'], id='grouped-vars'),
    pytest.param('const One, Two = 1, 2\n', ['One', 'Two'], id='grouped-consts'),
    pytest.param('var (\n First int\n Second string\n)\n', ['First', 'Second'], id='var-block'),
    pytest.param('const (\n One = iota\n Two\n)\n', ['One', 'Two'], id='const-block'),
    pytest.param('var (\n First, Second = 1, 2\n Third int\n)\n',
                 ['First', 'Second', 'Third'], id='grouped-var-block'),
    pytest.param('var _ = 1\nconst _ = 2\n', [], id='blank-bindings'),
    pytest.param('var _, Kept = 1, 2\nconst _, Also = 3, 4\n', ['Kept', 'Also'], id='mixed-blanks'),
    pytest.param('var Global int\nfunc consume() { var local int; const inner = 2; _ = local; _ = inner }\n',
                 ['Global'], id='function-locals'),
    pytest.param('var Global int\nfunc consume() { if true { var nested int; _ = nested }; '
                 'for i := 0; i < 1; i++ { const inner = 1; _ = inner } }\n',
                 ['Global'], id='nested-block-locals'),
    pytest.param('var Global int\ntype Box struct{}\nfunc (b *Box) consume() { var local int; _ = local }\n',
                 ['Global'], id='receiver-locals'),
    pytest.param('var Global int\nfunc consume() { var Global int; _ = Global }\n',
                 ['Global'], id='shadowed-global'),
    pytest.param('var Handler = func() { var hidden int; _ = hidden }\n', ['Handler'], id='initializer-closure'),
    pytest.param('var Global *Item\nvar Another = Global\nconst Label = "var Fake int"\n// var Comment int\n',
                 ['Global', 'Another', 'Label'], id='type-value-string-comment-decoys'),
    pytest.param('const First /* before */, Second /* type */ = 1, 2\n',
                 ['First', 'Second'], id='const-name-comments'),
    pytest.param('var ()\nconst ()\n', [], id='empty-blocks'),
    pytest.param('var Global int\nfunc consume() { callback := func() { var local int; _ = local }; _ = callback }\n',
                 ['Global'], id='nested-closure-local'),
    pytest.param('var Global int\nfunc consume() {\n var (\n local int\n other string\n )\n'
                 ' const (\n inner = 1\n extra = 2\n )\n _ = local; _ = other; _ = inner; _ = extra\n}\n',
                 ['Global'], id='local-declaration-blocks'),
    pytest.param('var (\n _ int\n Exported int\n)\nconst (\n _ = iota\n Visible = 1\n)\n',
                 ['Exported', 'Visible'], id='blank-and-real-block-bindings'),
])
def test_go_module_bindings_reach_raw_ast_and_index(tmp_path, declaration, expected, record_property):
    name = 'bindings.go'
    source = 'package sample\ntype Item struct { Value int }\n' + declaration
    tree = syntax_tree(name, source, 'go')
    record_property('native_tree', str(tree.root_node) if tree else '')
    assert tree is not None and not tree.root_node.has_error
    assert tree.root_node.end_byte == len(source.encode())
    raw = ts_parse_file(name, source, 'go')
    ast = parse_file(name, source)
    assert ast.parsing_tier == 'tree_sitter'
    assert any(c.name == 'Item' for c in ast.classes)
    record_property('raw_bindings', json.dumps(raw['top_level_vars']))
    record_property('ast_bindings', json.dumps(ast.top_level_vars))
    record_property('expected_bindings', json.dumps(expected))
    assert raw['top_level_vars'] == ast.top_level_vars == expected
    (tmp_path / name).write_text(source)
    service = ASTService(str(tmp_path))
    try:
        service.initialize_skeleton(indexing_depth='eager')
        variables = [loc for loc in service.get_file_symbols(name)
                     if loc.kind == 'variable' and loc.qualified_name == loc.name]
        record_property('indexed_bindings', json.dumps(sorted(loc.name for loc in variables)))
        assert sorted(loc.name for loc in variables) == sorted(expected)
        assert service._ast_cache[name].top_level_vars == expected
    finally:
        service.stop_hydration()
        service._store.close()
