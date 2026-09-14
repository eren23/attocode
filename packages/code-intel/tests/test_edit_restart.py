"""Edited sessions must reopen with the same evidence as a clean index."""

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel._internal.integrations.context.index_store import IndexStore
from attocode_intel.freshness import FreshnessTracker


def populate(root):
    (root / "helper.py").write_text("def helper():\n    return 1\n")
    (root / "caller.py").write_text("from helper import helper\ndef caller():\n    return helper()\n")
    (root / "spare.py").write_text("def spare():\n    return 3\n")
    (root / "pending.py").write_text("def pending():\n    return future()\n")


def mutate(root, kind):
    if kind == "body":
        path = root / "helper.py"
        stat = path.stat()
        path.write_text("def helper():\n    return 2\n")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    elif kind == "symbol":
        (root / "helper.py").write_text("def renamed():\n    return 1\n")
    elif kind == "imports":
        (root / "caller.py").write_text("from spare import spare\ndef caller():\n    return spare()\n")
    elif kind == "add":
        (root / "future.py").write_text("def future():\n    return 4\n")
    elif kind == "rename":
        (root / "helper.py").rename(root / "renamed.py")
        (root / "caller.py").write_text("from renamed import helper\ndef caller():\n    return helper()\n")
    elif kind == "delete":
        (root / "helper.py").unlink()
    else:
        (root / ".gitignore").write_text("helper.py\n")


def evidence(ast):
    index = ast.index
    return {
        "definitions": sorted((d.file_path, d.qualified_name, d.kind, d.start_line, d.end_line)
                              for defs in index.definitions.values() for d in defs),
        "references": sorted((r.file_path, r.symbol_name, r.ref_kind, r.line, r.caller_qualified_name)
                             for refs in index.references.values() for r in refs),
        "dependencies": index.file_dependencies,
        "dependents": index.file_dependents,
        "calls": index.call_edges,
        "callers": index.callers_of,
        "unresolved": ast._context_mgr.dependency_graph.unresolved,
    }


@pytest.mark.parametrize("online", [False, True], ids=["edited-while-closed", "edited-in-session"])
@pytest.mark.parametrize("kind", ["body", "symbol", "imports", "add", "rename", "delete", "ignore"])
def test_edit_restart_matches_clean_index(tmp_path, online, kind):
    populate(tmp_path)
    first = ASTService(str(tmp_path))
    first.initialize_skeleton()
    if not online:
        first._store.close()
    mutate(tmp_path, kind)
    if online:
        assert first.repair_changed_files()
        assert first._last_snapshot_repair["reused_reference_files"] > 0
        assert first._store.get_meta("structural_snapshot_v1")
        first._store.close()

    reopened = ASTService(str(tmp_path))
    clean = ASTService(str(tmp_path), store=IndexStore(db_path=":memory:"))
    try:
        with patch.object(reopened, "_index_references", wraps=reopened._index_references) as extract:
            state = reopened.initialize_skeleton()
        assert state.phase == "ready"
        if online:
            assert extract.call_count == 0  # saved repair reopens directly
        else:
            assert reopened._last_snapshot_repair["reused_reference_files"] > 0
            assert extract.call_count < state.total_files
        clean.initialize_skeleton()
        assert evidence(reopened) == evidence(clean)
        assert reopened._store.stats() == clean._store.stats()
        if kind == "add":
            assert any(r.ref_kind == "call" and r.file_path == "pending.py"
                       for r in reopened.index.get_references("future"))
        assert reopened.hydration_snapshot()["parse_coverage"] == 1.0
    finally:
        reopened._store.close()
        clean._store.close()


def test_interrupted_repair_cannot_restore_partial_store(tmp_path):
    populate(tmp_path)
    first = ASTService(str(tmp_path))
    first.initialize_skeleton()
    mutate(tmp_path, "body")
    try:
        with (patch.object(IndexStore, "save_files_batch", side_effect=OSError("interrupted write")),
              pytest.raises(OSError, match="interrupted write")):
            first.repair_changed_files()
        assert not first._store.get_meta("structural_snapshot_v1")
    finally:
        first._store.close()
    reopened = ASTService(str(tmp_path))
    try:
        with patch.object(reopened, "_index_references", wraps=reopened._index_references) as extract:
            state = reopened.initialize_skeleton()
        assert state.phase == "ready"
        assert extract.call_count == state.total_files
        assert reopened._store.get_meta("structural_snapshot_v1")
    finally:
        reopened._store.close()


def test_failed_live_repair_retries_filesystem_changes(tmp_path):
    populate(tmp_path)
    ast = ASTService(str(tmp_path))
    ast.initialize_skeleton()
    service = SimpleNamespace(_ast_service=ast, _semantic_search=None)
    tracker = FreshnessTracker(str(tmp_path))
    tracker.refresh(service)
    before = tracker.manifest
    mutate(tmp_path, "symbol")
    try:
        with (patch.object(IndexStore, "save_files_batch", side_effect=OSError("interrupted write")),
              pytest.raises(OSError)):
            tracker.refresh(service)
        assert tracker.manifest == before
        tracker.refresh(service)
        assert tracker.manifest != before
        assert ast.find_symbol("renamed")
        assert not ast.find_symbol("helper")
        assert ast._store.get_meta("structural_snapshot_v1")
    finally:
        ast._store.close()


@pytest.mark.parametrize("extension", ["js", "ts"])
def test_javascript_family_offline_repair_matches_clean_index(tmp_path, extension):
    helper, caller = f"helper.{extension}", f"caller.{extension}"
    (tmp_path / helper).write_text("export function helper() { return 1; }\n")
    (tmp_path / caller).write_text("import { helper } from './helper';\nexport function caller() { return helper(); }\n")
    (tmp_path / f"spare.{extension}").write_text("export function spare() { return 3; }\n")
    first = ASTService(str(tmp_path))
    first.initialize_skeleton()
    first._store.close()
    (tmp_path / helper).rename(tmp_path / f"moved.{extension}")
    (tmp_path / caller).write_text("import { helper } from './moved';\nexport function caller() { return helper(); }\n")
    reopened = ASTService(str(tmp_path))
    clean = ASTService(str(tmp_path), store=IndexStore(db_path=":memory:"))
    try:
        reopened.initialize_skeleton()
        clean.initialize_skeleton()
        assert reopened._last_snapshot_repair["reused_reference_files"] == 1
        assert evidence(reopened) == evidence(clean)
        assert reopened.get_dependencies(caller) == {f"moved.{extension}"}
    finally:
        reopened._store.close()
        clean._store.close()
