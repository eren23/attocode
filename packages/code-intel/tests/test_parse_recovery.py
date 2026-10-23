"""Failed grammar evidence and bounded recovery of an unchanged selected file."""
from unittest.mock import patch

import pytest
from attocode_intel._internal.integrations.context import ast_service, ts_parser
from attocode_intel._internal.integrations.context.codebase_ast import parse_file
from attocode_intel.request_context import RequestContext, bind_request, current_request
from attocode_intel.service import CodeIntelService
from attocode_intel.symbol_inspection import inspect_symbol_data


@pytest.fixture(autouse=True)
def selected_workspace(tmp_path):
    # Match gateway dispatch so composed test suggestions use this workspace,
    # rather than starting unrelated global/CWD hydration during a parser mock.
    with bind_request(RequestContext(str(tmp_path), str(tmp_path))):
        yield


def make_service(tmp_path):
    service = CodeIntelService(str(tmp_path))
    current_request.get().stores['service'] = service
    return service


def test_native_failure_is_reported_without_calling_it_a_timeout():
    parser = ts_parser._get_parser('lua')
    with patch.object(ts_parser, 'PARSE_TIMEOUT_MICROS', 1):
        result = parse_file('slow.lua', 'function greet()\n' + ' local value = 1\n' * 10000 + 'end\n')
    assert result.parsing_tier != 'tree_sitter'
    assert result.parse_failures
    failure = result.parse_failures[0]
    assert failure.outcome in {'no_tree', 'parser_error'}
    assert failure.limit_micros == 1 and failure.elapsed_micros >= 0
    assert failure.error_type in {'', 'ValueError'}
    assert ts_parser.bounded_parse(parser, b'function fresh() end') is not None


def degraded_service(tmp_path):
    (tmp_path/'sample.lua').write_text('function target() return 1 end\n' + 'local x = 1\n'*10000 + 'function caller() return target() end\n')
    service = make_service(tmp_path)
    with patch.object(ts_parser, 'PARSE_TIMEOUT_MICROS', 1):
        ast = service._get_ast_service(indexing_depth='eager')
    assert not ast.find_symbol('target')
    return service, ast


def test_selected_file_recovers_definition_and_references_without_edit(tmp_path):
    service, ast = degraded_service(tmp_path)
    try:
        result = inspect_symbol_data(service, 'target', 'sample.lua')
        assert result['status'] == 'found'
        assert result['definition']['start_line'] == 1
        assert any(r['line'] == 10002 for r in result['references'])
        assert 'sample.lua' in ast._reference_indexed_files
        assert ast._store.stats()['symbols'] >= 2
    finally:
        service._get_ast_service().stop_hydration()
        service._get_ast_service()._store.close()

    for _ in range(2):
        reopened = make_service(tmp_path)
        reopened._ast_service = ast_service.ASTService(str(tmp_path))
        reopened._ast_service.initialize_skeleton(indexing_depth='eager')
        reopened._context_mgr = reopened._ast_service._context_mgr
        try:
            reopened._get_ast_service(indexing_depth='eager')
            assert reopened._get_ast_service() is not ast
            result = inspect_symbol_data(reopened, 'target', 'sample.lua')
            assert result['status'] == 'found'
            assert any(r['line'] == 10002 for r in result['references'])
        finally:
            reopened._get_ast_service().stop_hydration()
            reopened._get_ast_service()._store.close()


def test_failed_selected_recovery_is_not_repeated_for_same_source(tmp_path):
    service, ast = degraded_service(tmp_path)
    try:
        with patch.object(ast_service, 'parse_file', return_value=ast._ast_cache['sample.lua']) as parse:
            first = inspect_symbol_data(service, 'target', 'sample.lua')
            again = inspect_symbol_data(service, 'target', 'sample.lua')
        assert first['status'] == again['status'] == 'not_found'
        assert first['parse_state']['recovery_attempted'] is True
        assert first['parse_state']['refresh']['command'] == 'attocode-code-intel notify'
        assert parse.call_count == 1
    finally:
        service._get_ast_service().stop_hydration()
        service._get_ast_service()._store.close()


def test_failed_selected_recovery_retries_after_cooldown_without_edit(tmp_path, monkeypatch):
    service, ast = degraded_service(tmp_path)
    clock = [100.0]
    monkeypatch.setattr(ast_service, '_parse_recovery_now', lambda: clock[0], raising=False)
    original = ast_service.parse_file
    try:
        with patch.object(ast_service, 'parse_file', wraps=original) as parse:
            with patch.object(ts_parser, 'PARSE_TIMEOUT_MICROS', 1):
                assert inspect_symbol_data(service, 'target', 'sample.lua')['status'] == 'not_found'
            assert inspect_symbol_data(service, 'target', 'sample.lua')['status'] == 'not_found'
            clock[0] = 100.999
            assert inspect_symbol_data(service, 'target', 'sample.lua')['status'] == 'not_found'
            assert parse.call_count == 1
            clock[0] = 101.0
            recovered = inspect_symbol_data(service, 'target', 'sample.lua')
            assert recovered['status'] == 'found'
            assert any(row['line'] == 10002 for row in recovered['references'])
            assert parse.call_count == 2
            assert inspect_symbol_data(service, 'target', 'sample.lua')['status'] == 'found'
            assert parse.call_count == 2
    finally:
        ast.stop_hydration()
        ast._store.close()


def test_persistent_selected_parse_failure_is_limited_to_one_attempt_per_cooldown(tmp_path, monkeypatch):
    service, ast = degraded_service(tmp_path)
    clock = [100.0]
    monkeypatch.setattr(ast_service, '_parse_recovery_now', lambda: clock[0], raising=False)
    try:
        with patch.object(ast_service, 'parse_file', return_value=ast._ast_cache['sample.lua']) as parse:
            for _ in range(3):
                assert inspect_symbol_data(service, 'target', 'sample.lua')['status'] == 'not_found'
            assert parse.call_count == 1
            clock[0] = 101.0
            assert inspect_symbol_data(service, 'target', 'sample.lua')['status'] == 'not_found'
            assert parse.call_count == 2
            for _ in range(3):
                assert inspect_symbol_data(service, 'target', 'sample.lua')['status'] == 'not_found'
            assert parse.call_count == 2
    finally:
        ast.stop_hydration()
        ast._store.close()


def test_expired_parse_recovery_cooldown_cannot_bless_an_unrelated_edit(tmp_path, monkeypatch):
    other = tmp_path / 'other.py'
    other.write_text('def before(): return 1\n')
    service, ast = degraded_service(tmp_path)
    clock = [100.0]
    monkeypatch.setattr(ast_service, '_parse_recovery_now', lambda: clock[0], raising=False)
    try:
        with patch.object(ast_service, 'parse_file', return_value=ast._ast_cache['sample.lua']) as parse:
            assert inspect_symbol_data(service, 'target', 'sample.lua')['status'] == 'not_found'
            assert parse.call_count == 1
            other.write_text('def after(): return 2\n')
            clock[0] = 101.0
            assert inspect_symbol_data(service, 'target', 'sample.lua')['status'] == 'not_found'
            assert parse.call_count == 1
    finally:
        ast.stop_hydration()
        ast._store.close()


def test_new_parser_generation_permits_a_new_bounded_attempt(tmp_path):
    from attocode_intel._internal.integrations.context import ast_snapshot

    service, ast = degraded_service(tmp_path)
    try:
        with patch.object(ast_service, 'parse_file', return_value=ast._ast_cache['sample.lua']) as parse:
            assert inspect_symbol_data(service, 'target', 'sample.lua')['status'] == 'not_found'
            assert inspect_symbol_data(service, 'target', 'sample.lua')['status'] == 'not_found'
        assert parse.call_count == 1
        with patch.object(ast_snapshot, 'parser_identity', return_value='changed-installed-grammar'):
            assert inspect_symbol_data(service, 'target', 'sample.lua')['status'] == 'found'
    finally:
        ast.stop_hydration()
        ast._store.close()


def test_empty_and_syntax_error_trees_are_not_transient_native_failures(tmp_path):
    (tmp_path/'empty.py').write_text('')
    (tmp_path/'broken.py').write_text('def broken(:\n')
    service = make_service(tmp_path)
    try:
        ast = service._get_ast_service(indexing_depth='eager')
        with patch.object(ast_service, 'parse_file', side_effect=AssertionError('not a transient failure')):
            for file in ('empty.py', 'broken.py'):
                assert not ast._ast_cache[file].parse_failures
                result = inspect_symbol_data(service, 'missing', file)
                assert result['status'] == 'not_found'
                assert 'parse_state' not in result
    finally:
        service._get_ast_service().stop_hydration()
        service._get_ast_service()._store.close()


def test_missing_name_in_healthy_file_does_not_trigger_recovery(tmp_path):
    (tmp_path/'healthy.py').write_text('def present(): return 1\n')
    service = make_service(tmp_path)
    try:
        service._get_ast_service(indexing_depth='eager')
        with patch.object(ast_service, 'parse_file', side_effect=AssertionError('healthy file reparsed')):
            assert inspect_symbol_data(service, 'missing', 'healthy.py')['status'] == 'not_found'
    finally:
        service._get_ast_service().stop_hydration()
        service._get_ast_service()._store.close()


def test_selected_recovery_cannot_bless_an_unrelated_concurrent_edit(tmp_path):
    other = tmp_path/'other.py'
    other.write_text('def old(): return 1\n')
    service, ast = degraded_service(tmp_path)
    previous_identity = ast._snapshot_start
    original = ast_service.parse_file

    def parse_then_edit(path):
        result = original(path)
        other.write_text('def changed(): return 2\n')
        return result

    try:
        with patch.object(ast_service, 'parse_file', side_effect=parse_then_edit):
            result = inspect_symbol_data(service, 'target', 'sample.lua')
        assert result['status'] == 'not_found'
        assert ast._snapshot_start == previous_identity
        assert ast._snapshot_start != ast._snapshot_identity()
    finally:
        ast.stop_hydration()
        ast._store.close()


def test_explicit_line_miss_recovers_even_when_another_definition_has_same_name(tmp_path):
    (tmp_path/'sample.js').write_text('function target() { return 1; }\nclass C {\ntarget(\nx\n) { return x; }\n}\n'
                                    + 'const value = 1;\n'*10000)
    service = make_service(tmp_path)
    try:
        with patch.object(ts_parser, 'PARSE_TIMEOUT_MICROS', 1):
            ast = service._get_ast_service(indexing_depth='eager')
        assert ast._ast_cache['sample.js'].parsing_tier == 'regex'
        assert any(d.start_line == 1 for d in ast.get_file_symbols('sample.js') if d.name == 'target')
        selected = inspect_symbol_data(service, 'target', 'sample.js', line=3)
        assert selected['status'] == 'found'
        assert selected['definition']['start_line'] == 3
    finally:
        service._get_ast_service().stop_hydration()
        service._get_ast_service()._store.close()


def test_persistence_stage_edit_does_not_publish_recovered_live_state(tmp_path):
    from dataclasses import asdict

    other = tmp_path/'other.py'
    other.write_text('def old(): return 1\n')
    (tmp_path/'caller.py').write_text('def invoke(): return target()\n' + 'x = 1\n'*10000)
    service, ast = degraded_service(tmp_path)
    previous = ast._ast_cache['sample.lua']
    previous_caller = ast._ast_cache['caller.py']
    failures = [asdict(f) for f in previous_caller.parse_failures]
    assert any(f['stage'] == 'references' for f in failures)
    original = type(ast._store).save_files_batch

    def save_then_edit(store, files):
        original(store, files)
        other.write_text('def changed(): return 2\n')

    try:
        with patch.object(type(ast._store), 'save_files_batch', save_then_edit):
            result = inspect_symbol_data(service, 'target', 'sample.lua')
        assert result['status'] == 'not_found'
        assert ast._ast_cache['sample.lua'] is previous
        assert ast._ast_cache['caller.py'] is previous_caller
        assert [asdict(f) for f in previous_caller.parse_failures] == failures
        assert not ast.find_symbol('target')
        from attocode_intel._internal.integrations.context.index_store import SNAPSHOT_KEY
        assert ast._store.get_meta(SNAPSHOT_KEY) in (None, '')
    finally:
        ast.stop_hydration()
        ast._store.close()
