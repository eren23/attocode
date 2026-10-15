"""Persisted summaries must preserve navigation and reject stale/invalid inputs."""
import json
from dataclasses import asdict
from unittest.mock import patch

import pytest
from attocode_intel._internal.integrations.context import (
    ast_service,
    ast_snapshot,
    codebase_ast,
    codebase_context,
)
from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel._internal.integrations.context.index_store import AST_SNAPSHOT_KEY, SNAPSHOT_KEY


def close(service):
    service.stop_hydration()
    service._store.close()


def seed(root, count=4):
    for i in range(count):
        (root / f'file{i}.py').write_text(
            f'class Sample{i}:\n    """Example."""\n    def method(self, value: int = 1) -> int:\n'
            '        return value\n\ndef helper():\n    return 2\n')
    svc = ASTService(str(root))
    svc.initialize_skeleton(indexing_depth='eager')
    assert svc._store.get_meta(SNAPSHOT_KEY)
    return svc


@pytest.mark.parametrize(('name', 'source'), [
    ('example.py', 'from typing import List\nclass Example:\n    def method(self, values: List[int] = []) -> int:\n        return len(values)\n'),
    ('example.go', 'package example\nimport "fmt"\ntype Thing struct {}\nfunc (t *Thing) Method(x int) int { fmt.Println(x); return x }\n'),
    ('example.ts', 'import { readFile } from "fs";\nexport class Example { method(value: string): string { return value; } }\n'),
])
def test_restart_preserves_complete_ast_and_symbols_without_parse(tmp_path, name, source):
    (tmp_path / name).write_text(source)
    first = ASTService(str(tmp_path))
    first.initialize_skeleton(indexing_depth='eager')
    expected = {k: asdict(v) for k, v in first._ast_cache.items()}
    definitions = first._index.definitions.copy()
    counts = first._store.stats()
    close(first)
    second = ASTService(str(tmp_path))
    try:
        with (patch.object(ast_service, 'parse_file', side_effect=AssertionError('restart reparsed')),
              patch.object(codebase_ast, 'parse_file', side_effect=AssertionError('discovery reparsed'))):
            assert second.initialize_skeleton().phase == 'ready'
        assert {k: asdict(v) for k, v in second._ast_cache.items()} == expected
        assert second._index.definitions == definitions
        assert second._store.stats() == counts
    finally:
        close(second)


@pytest.mark.parametrize('damage', ['missing', 'json', 'binding', 'parser', 'scalar', 'path', 'oversized'])
def test_invalid_summary_falls_back_to_identical_parse(tmp_path, damage, monkeypatch):
    first = seed(tmp_path)
    expected = {k: asdict(v) for k, v in first._ast_cache.items()}
    raw = first._store.get_meta(AST_SNAPSHOT_KEY)
    data = json.loads(raw)
    if damage == 'missing':
        raw = ''
    elif damage == 'json':
        raw = '{bad json'
    elif damage == 'binding':
        data['snapshot'] = 'wrong'
    elif damage == 'parser':
        monkeypatch.setattr(ast_snapshot, 'parser_identity', lambda _: 'changed')
    elif damage == 'scalar':
        data['files']['file0.py']['functions'][0]['start_line'] = True
    elif damage == 'path':
        data['files']['file0.py']['path'] = '/outside/file0.py'
    else:
        monkeypatch.setattr(ast_snapshot, 'MAX_CACHE_BYTES', 32)
    if damage not in {'missing', 'json'}:
        raw = json.dumps(data)
    first._store.set_meta(AST_SNAPSHOT_KEY, raw)
    close(first)
    second = ASTService(str(tmp_path))
    try:
        with patch.object(ast_service, 'parse_file', wraps=ast_service.parse_file) as parse:
            second.initialize_skeleton()
        assert parse.call_count == (1 if damage in {'scalar', 'path'} else 4)
        assert {k: asdict(v) for k, v in second._ast_cache.items()} == expected
    finally:
        close(second)


def test_partial_cache_bound_keeps_all_files_and_parses_only_misses(tmp_path, monkeypatch):
    monkeypatch.setattr(ast_snapshot, 'MAX_CACHE_BYTES', 4096)
    first = seed(tmp_path, count=20)
    expected = {k: asdict(v) for k, v in first._ast_cache.items()}
    raw = first._store.get_meta(AST_SNAPSHOT_KEY)
    assert len(raw.encode()) <= 4096
    retained = len(json.loads(raw)['files'])
    assert 0 < retained < 20
    close(first)
    second = ASTService(str(tmp_path))
    try:
        with patch.object(ast_service, 'parse_file', wraps=ast_service.parse_file) as parse:
            state = second.initialize_skeleton()
        assert state.parsed_files == 20 and parse.call_count == 20 - retained
        assert {k: asdict(v) for k, v in second._ast_cache.items()} == expected
    finally:
        close(second)


def test_file_bound_and_unsupported_tier_fall_back(tmp_path, monkeypatch):
    first = seed(tmp_path)
    asts = first._ast_cache
    raw = first._store.get_meta(SNAPSHOT_KEY)
    monkeypatch.setattr(ast_snapshot, 'MAX_FILE_BYTES', 10)
    assert not json.loads(ast_snapshot.encode_summaries(asts, raw))['files']
    monkeypatch.setattr(ast_snapshot, 'MAX_FILE_BYTES', 2**20)
    for ast in asts.values():
        ast.parsing_tier = 'ctags'
    assert not json.loads(ast_snapshot.encode_summaries(asts, raw))['files']
    close(first)


def test_source_digest_rejects_changed_file_even_with_rebound_snapshot(tmp_path):
    first = seed(tmp_path)
    raw = first._store.get_meta(SNAPSHOT_KEY)
    (tmp_path / 'file0.py').write_text('def replacement(): return 3\n')
    restored = ast_snapshot.restore_summaries(first._store, raw, first._context_mgr._files)
    assert 'file0.py' not in restored and len(restored) == 3
    close(first)


def test_cancellation_propagates_without_committing_snapshot(tmp_path):
    (tmp_path / 'example.py').write_text('def example(): return 1\n')
    first = ASTService(str(tmp_path))
    try:
        with (patch.object(ast_snapshot, 'encode_summaries', side_effect=KeyboardInterrupt),
              pytest.raises(KeyboardInterrupt)):
            first.initialize_skeleton()
        assert not first._store.get_meta(SNAPSHOT_KEY)
    finally:
        close(first)


def test_metadata_limit_is_bytes_and_clear_removes_summaries(tmp_path):
    svc = seed(tmp_path)
    try:
        svc._store.set_meta('utf8', '\u00e9' * 4)
        assert svc._store.get_meta('utf8', max_bytes=7) is None
        assert svc._store.get_meta('utf8', max_bytes=8) == '\u00e9' * 4
        svc._store.clear_all()
        assert svc._store.get_meta(AST_SNAPSHOT_KEY) is None
        assert svc._store.get_meta(SNAPSHOT_KEY) is None
    finally:
        close(svc)


def test_old_cache_is_upgraded_once(tmp_path):
    first = seed(tmp_path)
    first._store.set_meta(AST_SNAPSHOT_KEY, '')
    close(first)
    second = ASTService(str(tmp_path))
    try:
        with patch.object(ast_service, 'parse_file', wraps=ast_service.parse_file) as parse:
            second.initialize_skeleton()
        assert parse.call_count == 4
        assert second._store.get_meta(AST_SNAPSHOT_KEY)
    finally:
        close(second)
    third = ASTService(str(tmp_path))
    try:
        with patch.object(ast_service, 'parse_file', side_effect=AssertionError('repeated upgrade')):
            third.initialize_skeleton()
    finally:
        close(third)


def test_summaries_survive_a_fresh_process(tmp_path):
    import subprocess
    import sys

    first = seed(tmp_path)
    expected = first._store.stats()
    close(first)
    result = subprocess.run([sys.executable, '-c', '''
import json,sys
from unittest.mock import patch
from attocode_intel._internal.integrations.context import ast_service, codebase_ast
svc=ast_service.ASTService(sys.argv[1])
try:
 with (patch.object(ast_service, 'parse_file', side_effect=AssertionError('child reparsed')),
       patch.object(codebase_ast, 'parse_file', side_effect=AssertionError('child discovery reparsed'))):
  state=svc.initialize_skeleton()
 assert state.phase=='ready'
 print(json.dumps(svc._store.stats()))
finally:
 svc.stop_hydration();svc._store.close()
''', str(tmp_path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected


def test_edit_during_restore_cannot_publish_old_summary(tmp_path):
    first = seed(tmp_path)
    close(first)
    restore = ast_snapshot.restore_summaries

    def racing_restore(*args):
        result = restore(*args)
        (tmp_path / 'file0.py').write_text('def replacement(): return 3\n')
        return result

    second = ASTService(str(tmp_path))
    try:
        with patch.object(ast_snapshot, 'restore_summaries', side_effect=racing_restore):
            second.initialize_skeleton()
        assert not second.find_symbol('Sample0')
        assert second.find_symbol('replacement')
        assert not second._store.get_meta(SNAPSHOT_KEY)
    finally:
        close(second)


def test_summary_write_failure_leaves_no_complete_snapshot(tmp_path):
    import sqlite3

    (tmp_path / 'example.py').write_text('def example(): return 1\n')
    first = ASTService(str(tmp_path))
    original = type(first._store).set_meta

    def failing_write(store, key, value):
        if key == AST_SNAPSHOT_KEY:
            raise sqlite3.OperationalError('injected cache failure')
        original(store, key, value)

    try:
        with (patch.object(type(first._store), 'set_meta', failing_write),
              pytest.raises(sqlite3.OperationalError, match='injected')):
            first.initialize_skeleton()
        assert not first._store.get_meta(SNAPSHOT_KEY)
    finally:
        close(first)
    second = ASTService(str(tmp_path))
    try:
        assert second.initialize_skeleton().phase == 'ready'
        assert second.find_symbol('example')
    finally:
        close(second)


def test_restart_discovery_preserves_inventory_order_scores_and_import_graph(tmp_path):
    (tmp_path / 'helper.py').write_text('def helper(): return 1\n')
    (tmp_path / 'client.py').write_text('from helper import helper\ndef client(): return helper()\n')
    first = ASTService(str(tmp_path))
    try:
        first.initialize_skeleton(indexing_depth='eager')
        inventory = [asdict(fi) for fi in first._context_mgr._files]
        graph = asdict(first._context_mgr.dependency_graph)
    finally:
        close(first)
    second = ASTService(str(tmp_path))
    try:
        with patch.object(codebase_ast, 'parse_file', side_effect=AssertionError('discovery reparsed')):
            assert second.initialize_skeleton().phase == 'ready'
        assert [asdict(fi) for fi in second._context_mgr._files] == inventory
        assert asdict(second._context_mgr.dependency_graph) == graph
    finally:
        close(second)


def test_edit_during_discovery_rejects_preloaded_summaries(tmp_path, monkeypatch):
    first = seed(tmp_path, count=1)
    close(first)
    original = codebase_context.CodebaseContextManager.discover_files
    def edit_after_discovery(self, **kwargs):
        files = original(self, **kwargs)
        (tmp_path / 'file0.py').write_text('def changed_after_summary(): return 3\n')
        return files
    monkeypatch.setattr(codebase_context.CodebaseContextManager, 'discover_files', edit_after_discovery)
    second = ASTService(str(tmp_path))
    try:
        second.initialize_skeleton()
        assert second.find_symbol('changed_after_summary')
        assert not second.find_symbol('Sample0')
        assert not second._store.get_meta(SNAPSHOT_KEY)  # Concurrent edit cannot bless a snapshot.
    finally:
        close(second)


def test_completion_change_revalidates_preloaded_cache_binding(tmp_path, monkeypatch):
    first = seed(tmp_path, count=1)
    close(first)
    second = ASTService(str(tmp_path))
    original = codebase_context.CodebaseContextManager.discover_files
    def change_completion(self, **kwargs):
        files = original(self, **kwargs)
        raw = second._store.get_meta(SNAPSHOT_KEY)
        second._store.set_meta(SNAPSHOT_KEY, raw + ' ')
        return files
    monkeypatch.setattr(codebase_context.CodebaseContextManager, 'discover_files', change_completion)
    try:
        with patch.object(ast_service, 'parse_file', wraps=ast_service.parse_file) as parse:
            second.initialize_skeleton()
        assert parse.call_count == 1
        assert second.find_symbol('Sample0')
    finally:
        close(second)
