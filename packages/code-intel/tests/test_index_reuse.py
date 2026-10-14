"""Restart reuse must preserve evidence and reject changed or incomplete caches."""

import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from attocode_intel._internal.integrations.context import ast_service
from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel._internal.integrations.context.index_store import (
    SNAPSHOT_KEY,
    SQLITE_BUSY_TIMEOUT_MS,
    IndexSchemaVersionError,
    IndexStore,
    StoredFile,
)
from attocode_intel.freshness import FreshnessTracker
from attocode_intel.symbol_inspection import select_definitions


def repository(root):
    (root / "helper.py").write_text("def helper():\n    return 1\n")
    (root / "caller.py").write_text("from helper import helper\ndef caller():\n    return helper()\n")
    (root / "empty.py").write_text("# no definitions\n")


def close(service):
    service.stop_hydration()
    service._store.close()


def test_index_store_waits_for_short_cross_process_writes(tmp_path):
    db_path = str(tmp_path / "symbols.db")
    store = IndexStore(db_path=db_path)
    try:
        assert store._get_conn().execute("PRAGMA busy_timeout").fetchone()[0] == SQLITE_BUSY_TIMEOUT_MS
        with sqlite3.connect(db_path) as writer, ThreadPoolExecutor(max_workers=1) as pool:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("UPDATE metadata SET value = value WHERE key = 'schema_version'")
            waiting_write = pool.submit(store.set_meta, "after_lock", "saved")
            time.sleep(0.05)
            assert not waiting_write.done()
            writer.commit()
            waiting_write.result(timeout=2)
        assert store.get_meta("after_lock") == "saved"
    finally:
        store.close()


def test_older_client_refuses_newer_schema_without_deleting_data(tmp_path):
    db_path = str(tmp_path / "symbols.db")
    store = IndexStore(db_path=db_path)
    store.save_file(StoredFile(
        path="sentinel.py", mtime=1, size=1, language="python",
        line_count=1, content_hash="sentinel",
    ))
    store.close()
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE metadata SET value = '999' WHERE key = 'schema_version'")
        conn.commit()

    with pytest.raises(IndexSchemaVersionError, match="newer than this client's"):
        IndexStore(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone() == ("999",)
        assert conn.execute("SELECT path FROM files").fetchall() == [("sentinel.py",)]


def test_restart_restores_complete_index_beyond_skeleton_budget(tmp_path, monkeypatch):
    repository(tmp_path)
    monkeypatch.setattr(ast_service, "skeleton_budget", lambda *_: 1)
    first = ASTService(str(tmp_path))
    first.initialize_skeleton()
    first._run_hydration()
    expected = first._store.stats()
    assert expected["dependencies"] > 0
    assert first._store.get_meta(SNAPSHOT_KEY)
    close(first)
    second = ASTService(str(tmp_path))
    try:
        with patch.object(second, "_index_references", side_effect=AssertionError("reindexed")):
            state = second.initialize_skeleton()
        assert state.phase == "ready"
        assert state.parsed_files == state.reference_indexed_files == 3
        assert len(second.find_symbol("helper")) == 1
        assert second._index.get_references("helper")
        assert second._index.get_dependencies("caller.py") == {"helper.py"}
        assert second._context_mgr.dependency_graph.get_importers("helper.py") == {"caller.py"}
        assert "empty.py" in second._ast_cache
        assert second._store.stats() == expected
    finally:
        close(second)


@pytest.mark.parametrize("mutation", ["edit", "rename", "delete", "add", "ignore"])
def test_restart_rejects_changed_snapshot(tmp_path, mutation):
    repository(tmp_path)
    first = ASTService(str(tmp_path))
    first.initialize_skeleton()
    close(first)
    helper = tmp_path / "helper.py"
    if mutation == "edit":
        stat = helper.stat()
        helper.write_text("def newest():\n    return 1\n")  # same size, restored mtime
        os.utime(helper, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    elif mutation == "rename":
        helper.rename(tmp_path / "renamed.py")
    elif mutation == "delete":
        helper.unlink()
    elif mutation == "add":
        (tmp_path / "added.py").write_text("def newest(): return 2\n")
    else:
        (tmp_path / ".gitignore").write_text("helper.py\n")
    second = ASTService(str(tmp_path))
    try:
        with patch.object(second, "_index_references", wraps=second._index_references) as refs:
            second.initialize_skeleton()
        assert refs.call_count > 0
        if mutation in {"edit", "delete", "ignore"}:
            assert not second.find_symbol("helper")
        if mutation in {"edit", "add"}:
            assert second.find_symbol("newest")
        if mutation == "rename":
            assert second.find_symbol("helper")[0].file_path == "renamed.py"
        assert {f.path for f in second._store.get_all_files()} == set(second._ast_cache)
    finally:
        close(second)


def test_incomplete_cache_is_not_restored(tmp_path, monkeypatch):
    repository(tmp_path)
    first = ASTService(str(tmp_path))
    first.initialize_skeleton()
    first._store.clear_all()
    close(first)
    monkeypatch.setattr(ast_service, "skeleton_budget", lambda *_: 1)
    second = ASTService(str(tmp_path))
    try:
        assert second.initialize_skeleton().phase == "skeleton"
        assert not second._store.get_meta(SNAPSHOT_KEY)
    finally:
        close(second)


def test_explicit_file_selection_parses_outside_skeleton_once(tmp_path, monkeypatch):
    repository(tmp_path)
    monkeypatch.setattr(ast_service, "skeleton_budget", lambda *_: 0)
    ast = ASTService(str(tmp_path))
    ast.initialize_skeleton()
    service = SimpleNamespace(project_dir=str(tmp_path), _get_ast_service=lambda: ast)
    try:
        assert len(select_definitions(service, "helper", "helper.py")) == 1
        assert len(select_definitions(service, "helper", "helper.py")) == 1
        assert ast.hydration_snapshot()["parsed_files"] == 1
        with pytest.raises(ValueError, match="inside"):
            select_definitions(service, "helper", "../helper.py")
    finally:
        close(ast)


def test_scan_reuses_filters_but_detects_immediate_changes(tmp_path):
    repository(tmp_path)
    tracker = FreshnessTracker(str(tmp_path))
    before = tracker.scan_manifest()
    with patch.object(tracker._ignore, "is_ignored", side_effect=AssertionError("rematched")):
        assert tracker.scan_manifest() == before
        helper = tmp_path / "helper.py"
        stat = helper.stat()
        helper.write_text("def newest():\n    return 1\n")
        os.utime(helper, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        assert tracker.scan_manifest()["helper.py"] != before["helper.py"]
    (tmp_path / ".gitignore").write_text("helper.py\n")
    assert "helper.py" not in tracker.scan_manifest()
    (tmp_path / ".gitignore").unlink()
    assert "helper.py" in tracker.scan_manifest()
    (tmp_path / "helper.py").rename(tmp_path / "renamed.py")
    renamed = tracker.scan_manifest()
    assert "helper.py" not in renamed and "renamed.py" in renamed
    (tmp_path / "renamed.py").unlink()
    assert "renamed.py" not in tracker.scan_manifest()


def test_analysis_batches_are_atomic_bounded_and_preserve_definition_keys(tmp_path):
    from attocode_intel._internal.integrations.context.cross_references import (
        CrossRefIndex,
        SymbolLocation,
        SymbolRef,
    )
    store = IndexStore(db_path=str(tmp_path / 'batch.db'))
    index = CrossRefIndex()
    index.set_store(store)
    paths = {f'{i}.py' for i in range(205)}
    try:
        store.save_files_batch([StoredFile(path=p,mtime=1,size=1,language='python',line_count=1,content_hash='x') for p in paths])
        for path in paths:
            index.add_definition(SymbolLocation('helper','helper','function',path,1,2))
            index.add_reference(SymbolRef('helper','call',path,2,definition_key='selected-identity'))
        statements = []
        store._get_conn().set_trace_callback(statements.append)
        index.persist_files(paths)
        assert sum(s == 'COMMIT' for s in statements) == 3
        assert len(store.load_symbols()) == len(store.load_references()) == 205
        assert {r.definition_key for r in store.load_references()} == {'selected-identity'}
        before_symbols, before_refs = store.load_symbols(), store.load_references()
        with pytest.raises(sqlite3.IntegrityError):
            store.save_analysis_batch([
                ('0.py', [], []),
                ('missing.py', [], [{'symbol_name':'invalid-foreign-key'}]),
            ])
        assert store.load_symbols() == before_symbols
        assert store.load_references() == before_refs
        # Definition-only callers retain refs, and reference-only callers retain definitions.
        store.save_symbols('0.py', [])
        assert len(store.load_references('0.py')) == 1
        store.save_references('1.py', [])
        assert len(store.load_symbols('1.py')) == 1
    finally:
        store.close()


@pytest.mark.parametrize("entrypoint", ["initialize", "initialize_skeleton"])
def test_full_initialization_has_bounded_commits_and_complete_evidence(tmp_path, entrypoint):
    for i in range(205):
        source = "" if i == 0 else "from f0 import helper0\n"
        source += f"def helper{i}():\n    return " + ("0\n" if i == 0 else "helper0()\n")
        (tmp_path / f"f{i}.py").write_text(source)
    service = ASTService(str(tmp_path))
    statements = []
    service._store._get_conn().set_trace_callback(statements.append)
    try:
        getattr(service, entrypoint)()
        # Includes metadata and file/dependency writes, not just symbol batches.
        # A per-file commit loop exceeds this budget on this modest repository.
        assert sum(s == "COMMIT" for s in statements) <= 20
        assert len(service._store.load_symbols()) == 205
        refs = service._store.load_references()
        assert {r.file_path for r in refs} == {f"f{i}.py" for i in range(1, 205)}
        assert {r.ref_kind for r in refs} >= {"import", "call"}
        assert service._store._get_conn().execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        close(service)


def test_hydration_reuses_parsed_files_for_deferred_dependencies(tmp_path, monkeypatch):
    from attocode_intel._internal.integrations.context import codebase_ast
    from attocode_intel._internal.integrations.context.codebase_context import DependencyGraph

    repository(tmp_path)
    service = ASTService(str(tmp_path))
    try:
        service.initialize_skeleton(indexing_depth="minimal")
        service._context_mgr._dep_graph = DependencyGraph()
        # ASTService holds its own parser binding for phase 2a. Re-parsing from
        # the deferred dependency builder would unnecessarily read every file again.
        def redundant_parse(*args, **kwargs):
            raise AssertionError("Deferred dependencies reparsed hydrated source")
        monkeypatch.setattr(codebase_ast, "parse_file", redundant_parse)
        service._run_hydration()
        assert service._hydration_state.phase == "ready"
        assert service._index.get_dependencies("caller.py") == {"helper.py"}
        assert service._index.get_references("helper")
        assert len(service._store.get_all_files()) == 3
    finally:
        close(service)


def test_known_name_snapshot_reuse_and_definition_mutations(tmp_path):
    from attocode_intel._internal.integrations.context.codebase_ast import parse_file
    from attocode_intel._internal.integrations.context.cross_references import (
        CrossRefIndex,
        SymbolLocation,
    )

    index = CrossRefIndex()
    empty = index.known_symbol_names()
    assert empty == frozenset() and index.known_symbol_names() is empty
    index.add_definition(SymbolLocation("helper", "helper", "function", "a.py", 1, 2))
    original = index.known_symbol_names()
    assert original == {"helper"} and index.known_symbol_names() is original
    index.add_definition(SymbolLocation("helper", "Thing.helper", "method", "b.py", 1, 2))
    assert index.known_symbol_names() is original
    index.remove_file("a.py")
    assert index.known_symbol_names() is original  # second definition still owns the name
    index.remove_file("b.py")
    assert index.known_symbol_names() == frozenset()
    assert original == {"helper"}  # an in-flight reader's view stays immutable

    (tmp_path / "caller.py").write_text("def caller():\n    return fresh()\n")
    service = ASTService(str(tmp_path))
    try:
        ast = parse_file(str(tmp_path / "caller.py"))
        service._index = index
        service._index_references("caller.py", ast)
        assert not index.get_references("fresh")
        index.add_definition(SymbolLocation("fresh", "fresh", "function", "fresh.py", 1, 2))
        service._index_references("caller.py", ast)
        assert {r.file_path for r in index.get_references("fresh")} == {"caller.py"}
        index.remove_file("fresh.py")
        index.remove_file("caller.py")
        service._index_references("caller.py", ast)
        assert not index.get_references("fresh")
    finally:
        close(service)
