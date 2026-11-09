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


@pytest.mark.parametrize('entrypoint', ['direct', 'readiness-first'])
@pytest.mark.parametrize('previous_identity', ['parser', 'navigation', 'missing-completion'])
def test_initialization_repairs_previous_binding_index(tmp_path, monkeypatch, record_property,
                                                     entrypoint, previous_identity):
    from contextlib import ExitStack
    from dataclasses import asdict, replace
    from unittest.mock import patch

    from attocode_intel._internal.integrations.context import ast_service, ast_snapshot
    from attocode_intel._internal.integrations.context.index_store import (
        AST_SNAPSHOT_KEY,
        SNAPSHOT_KEY,
    )
    from attocode_intel.readiness import ReadinessPhase
    from attocode_intel.service import CodeIntelService

    name = 'bindings.go'
    path = tmp_path / name
    source = 'package sample\nvar First, Second int\nfunc Format() { var local int; _ = local }\n'
    path.write_text(source)
    before = path.stat()
    tree = syntax_tree(name, source, 'go')
    assert tree is not None and not tree.root_node.has_error and tree.root_node.end_byte == len(source.encode())
    expected = ['First', 'Second']
    legacy = ['First', 'local']
    original_parse = ast_service.parse_file
    original_index = ASTService._index_definitions

    def previous_parse(*args, **kwargs):
        return replace(original_parse(*args, **kwargs), top_level_vars=legacy)

    def previous_index(service, rel, ast):
        original_index(service, rel, replace(ast, top_level_vars=legacy))

    first = ASTService(str(tmp_path))
    try:
        with ExitStack() as stack:
            if previous_identity == 'navigation':
                # Valid AST summaries, but an older indexer persisted wrong names.
                stack.enter_context(patch.object(ASTService, '_index_definitions', previous_index))
                stack.enter_context(patch.object(ast_snapshot, 'navigation_identity', return_value='previous-navigation'))
            else:
                # An older parser persisted both the old AST and its derived index.
                stack.enter_context(patch.object(ast_service, 'parse_file', previous_parse))
                stack.enter_context(patch.object(ast_snapshot, 'parser_identity', return_value='previous-parser'))
            first.initialize_skeleton(indexing_depth='eager')
        assert first._store.get_last_scan_time() is not None
        assert sorted(loc.name for loc in first.get_file_symbols(name) if loc.kind == 'variable') == sorted(legacy)
        assert first._ast_cache[name].top_level_vars == (expected if previous_identity == 'navigation' else legacy)
        if previous_identity == 'missing-completion':
            first._store.set_meta(SNAPSHOT_KEY, '')
        record_property('seed', json.dumps({'ast_bindings': first._ast_cache[name].top_level_vars,
                        'symbols': {k: [asdict(loc) for loc in v] for k, v in first._index.definitions.items()},
                        'completion': first._store.get_meta(SNAPSHOT_KEY),
                        'summaries': first._store.get_meta(AST_SNAPSHOT_KEY)}))
    finally:
        first.stop_hydration()
        first._store.close()

    monkeypatch.setattr(ast_service, '_instances', {})
    service = ASTService.get_instance(str(tmp_path))
    api = CodeIntelService(str(tmp_path))
    try:
        if entrypoint == 'direct':
            assert service.initialize() is None
        else:
            report = api.readiness_report_data(phases=[ReadinessPhase.BASELINE], tracer_bullets=False)
            record_property('readiness_report', json.dumps(report))
            assert report
        assert service.initialized and api._get_ast_service() is service
        names = sorted(loc.name for loc in service.get_file_symbols(name) if loc.kind == 'variable')
        record_property('restored_bindings', json.dumps(names))
        record_property('source_unchanged', path.read_text() == source and path.stat().st_mtime_ns == before.st_mtime_ns)
        record_property('current_parser', ast_snapshot.parser_identity('go'))
        record_property('current_navigation', ast_snapshot.navigation_identity())
        assert 'Format' in service._index.definitions
        assert names == sorted(expected)
        assert path.read_text() == source and path.stat().st_mtime_ns == before.st_mtime_ns
    finally:
        service.stop_hydration()
        service._store.close()


@pytest.mark.parametrize('force', [False, True], ids=['unchanged-reuse', 'force-rebuild'])
def test_direct_initialization_preserves_reuse_and_force(tmp_path, force, record_property):
    from unittest.mock import patch

    from attocode_intel._internal.integrations.context import ast_service

    name = 'bindings.go'
    source = 'package sample\nvar First, Second int\nfunc Format() {}\n'
    (tmp_path / name).write_text(source)
    first = ASTService(str(tmp_path))
    try:
        first.initialize()
        expected = first._index.definitions.copy()
        assert {'First', 'Second', 'Format'} <= set(expected)
    finally:
        first.stop_hydration()
        first._store.close()
    second = ASTService(str(tmp_path))
    try:
        with patch.object(ast_service, 'parse_file', wraps=ast_service.parse_file) as parse:
            assert second.initialize(force=force) is None
        record_property('definition_parse_calls', parse.call_count)
        assert (parse.call_count > 0) is force
        assert second._index.definitions == expected
        assert (tmp_path / name).read_text() == source
    finally:
        second.stop_hydration()
        second._store.close()


@pytest.mark.parametrize('scenario,count,tier,phase,parsed', [
    pytest.param('medium', 1000, 'medium', 'ready', 1000, id='medium-complete'),
    pytest.param('partial', 2, 'small', 'hydrating', 1, id='skipped-parse'),
    pytest.param('aborted', 1, 'unknown', 'unknown', 0, id='failed-persistence'),
])
def test_direct_initialization_reports_actual_progress(tmp_path, record_property,
                                                      scenario, count, tier, phase, parsed):
    from contextlib import ExitStack
    from unittest.mock import patch

    from attocode_intel._internal.integrations.context import ast_service

    for i in range(count):
        (tmp_path / f'entry{i}.go').write_text(f'package sample\nfunc Entry{i}() {{}}\n')
    service = ASTService(str(tmp_path))
    original_parse = ast_service.parse_file

    def skip_one(path, *args, **kwargs):
        if str(path).endswith('entry1.go'):
            raise RuntimeError('unexpected definition parse failure')
        return original_parse(path, *args, **kwargs)

    try:
        with ExitStack() as stack:
            if scenario == 'partial':
                stack.enter_context(patch.object(ast_service, 'parse_file', side_effect=skip_one))
            if scenario == 'aborted':
                stack.enter_context(patch.object(service._store, 'save_files_batch',
                                                side_effect=RuntimeError('persistence unavailable')))
                with pytest.raises(RuntimeError, match='persistence unavailable'):
                    service.initialize()
                assert not service.initialized
            else:
                assert service.initialize() is None and service.initialized
        status = service.hydration_snapshot()
        record_property('public_status', json.dumps(status))
        record_property('actual_cached_files', len(service._ast_cache))
        record_property('definition_count', len(service._index.definitions))
        assert status['tier'] == tier and status['phase'] == phase
        assert status['parsed_files'] == parsed
        if scenario != 'aborted':
            assert status['total_files'] == count
            assert 'Entry0' in service._index.definitions
            assert status['parse_coverage'] == parsed / count
        if scenario == 'medium':
            assert 'Entry999' in service._index.definitions
        if scenario == 'partial':
            assert 'Entry1' not in service._index.definitions
    finally:
        service.stop_hydration()
        service._store.close()
