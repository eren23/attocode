"""Configured request discovery must survive every lexical entry path."""

from pathlib import Path

import pytest
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager
from attocode_intel.request_context import RequestContext, bind_request
from attocode_intel.service import CodeIntelService


def request_manager(root, monkeypatch, limit="3000"):
    monkeypatch.setenv("ATTOCODE_INTEL_MAX_FILES", limit)
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_PROVIDER", "off")
    with bind_request(RequestContext(str(root), str(root))):
        service = CodeIntelService(str(root))
        manager = service._get_semantic_search()
    assert service._ast_service is None, "search configuration eagerly initialized AST"
    return manager


def mixed_sources(root):
    # Hand-derived:1001 Python sources+1100 documents+one final document=2102.
    for i in range(1001):
        (root / f"module_{i}.py").write_text(f"def operation_{i}(): return {i}\n")
    for i in range(1100):
        (root / f"note_{i}.md").write_text("ordinary documentation\n")
    (root / "zz_uniquepolicyneedle.md").write_text("uniquepolicyneedle\n")


@pytest.mark.parametrize("entry", ["keyword", "body", "importance", "warm"])
def test_request_policy_reaches_each_fresh_lexical_context(tmp_path, monkeypatch, entry):
    mixed_sources(tmp_path)
    manager = request_manager(tmp_path, monkeypatch)
    try:
        if entry == "keyword":
            manager._build_keyword_index()
            found = manager._keyword_search("uniquepolicyneedle", 5, "zz_uniquepolicyneedle.md")
        elif entry == "body":
            manager._sync_body_index()
            found = manager._body_search(["uniquepolicyneedle"], 5, "zz_uniquepolicyneedle.md")
        elif entry == "importance":
            manager._load_importance_scores()
            found = manager._get_importance("zz_uniquepolicyneedle.md") > 0
        else:
            manager._warm_candidate_indexes()
            found = manager.search_candidates("uniquepolicyneedle", 5, "zz_uniquepolicyneedle.md")
        assert found, f"coverage boundary: {entry} lost a configured eligible document"
    finally:
        manager.close()


def test_search_diagnostics_expose_effective_discovery_selection(tmp_path, monkeypatch):
    (tmp_path / "main.py").write_text("def policyneedle(): return 1\n")
    manager = request_manager(tmp_path, monkeypatch)
    try:
        manager._warm_candidate_indexes()
        state = manager.candidate_diagnostics()
        assert state.get("discovery_max_files") == 3000, "coverage boundary: configured limit hidden"
        assert state["discovery_discovered_files"] == state["discovery_selected_files"] == 1
        assert state["discovery_truncated"] is False
        assert state["status"] == "ready" and state["body_index_coverage"] == 1.0
    finally:
        manager.close()


def test_invalidated_discovery_does_not_publish_old_completed_counts(tmp_path, monkeypatch):
    source = tmp_path / "main.py"
    source.write_text("def policyneedle(): return 1\n")
    manager = request_manager(tmp_path, monkeypatch)
    try:
        manager._warm_candidate_indexes()
        source.write_text("def changedneedle(): return 2\n")
        manager.invalidate_file(str(source))
        state = manager.candidate_diagnostics()
        assert state["status"] == "warming"
        assert state.get("discovery_selected_files") == 0, "coverage boundary: invalidated inventory not cleared"
        manager._warm_candidate_indexes()
        assert manager.candidate_diagnostics()["discovery_selected_files"] == 1
        assert manager.search_candidates("changedneedle", 5, "main.py")
        assert not manager.search_candidates("policyneedle", 5, "main.py")
    finally:
        manager.close()


def test_cancelled_discovery_never_claims_complete_inventory(tmp_path, monkeypatch):
    (tmp_path / "main.py").write_text("def policyneedle(): return 1\n")
    manager = request_manager(tmp_path, monkeypatch)
    try:
        manager._closed = True
        manager._warm_candidate_indexes()
        state = manager.candidate_diagnostics()
        assert state["status"] == "warming" and state["body_index_ready"] is False
        assert state.get("discovery_selected_files", 0) == 0
    finally:
        manager.close()


def test_standalone_default_keeps_its_existing_composition_bound(tmp_path):
    mixed_sources(tmp_path)
    manager = SemanticSearchManager(str(tmp_path))
    try:
        manager._warm_candidate_indexes()
        conn = manager._open_body_db()
        try:
            assert conn.execute("SELECT count(*) FROM kw_files").fetchone()[0] == 2000
        finally:
            conn.close()
        assert not manager.search_candidates("uniquepolicyneedle", 5, "zz_uniquepolicyneedle.md")
    finally:
        manager.close()


def test_configured_search_preserves_source_exclusions(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "main.py").write_text("def visiblepolicy(): return 1\n")
    (root / ".gitignore").write_text("ignored.py\n")
    (root / "ignored.py").write_text("def secretpolicy(): return 2\n")
    (root / "huge.py").write_bytes(b"#" * 1_000_001)
    outside = tmp_path / "outside.py"
    outside.write_text("def secretpolicy(): return 3\n")
    (root / "escape.py").symlink_to(outside)
    manager = request_manager(root, monkeypatch)
    try:
        manager._warm_candidate_indexes()
        conn = manager._open_body_db()
        try:
            assert {r[0] for r in conn.execute("SELECT file_path FROM kw_files")} == {"main.py"}
            assert {r[0] for r in conn.execute("SELECT file_path FROM body_files")} == {"main.py"}
        finally:
            conn.close()
        assert manager.search_candidates("visiblepolicy", 5, "main.py")
        for excluded in ("ignored.py", "huge.py", "escape.py"):
            assert not manager.search_candidates("secretpolicy", 5, excluded)
        assert Path(manager.root_dir).resolve() == root.resolve()
    finally:
        manager.close()
