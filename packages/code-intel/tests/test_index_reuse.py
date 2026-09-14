"""Restart reuse must preserve evidence and reject changed or incomplete caches."""

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from attocode_intel._internal.integrations.context import ast_service
from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel.freshness import FreshnessTracker
from attocode_intel.symbol_inspection import select_definitions


def repository(root):
    (root / "helper.py").write_text("def helper():\n    return 1\n")
    (root / "caller.py").write_text("from helper import helper\ndef caller():\n    return helper()\n")
    (root / "empty.py").write_text("# no definitions\n")


def close(service):
    service.stop_hydration()
    service._store.close()


def test_restart_restores_complete_index_beyond_skeleton_budget(tmp_path, monkeypatch):
    repository(tmp_path)
    monkeypatch.setattr(ast_service, "skeleton_budget", lambda *_: 1)
    first = ASTService(str(tmp_path))
    first.initialize_skeleton()
    first._run_hydration()
    expected = first._store.stats()
    assert expected["dependencies"] > 0
    assert first._store.get_meta("structural_snapshot_v1")
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
        assert not second._store.get_meta("structural_snapshot_v1")
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
