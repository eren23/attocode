"""Distinct definitions and fallback windows survive retrieval and persistence."""
import sqlite3
from dataclasses import replace

import pytest
from attocode_intel._internal.integrations.context.semantic_search import (
    SemanticSearchManager,
    SemanticSearchResult,
)
from attocode_intel.search_evidence import hydrate_selected_sources, source_body

JAVA = """public class Parser {
    public int parse(String text) {
        return text.length();
    }
    public int parse(byte[] bytes) {
        return bytes.length;
    }
}
"""


def warm(manager):
    manager.search("warmup", top_k=24)
    assert manager.wait_for_body_index(timeout=10)


def spans(hits, name):
    return {(h.start_line, h.end_line) for h in hits if h.name == name}


def test_java_overloads_fuse_individually_and_reopen_without_losing_metadata(tmp_path):
    (tmp_path / "Parser.java").write_text(JAVA)
    for _ in range(2):
        manager = SemanticSearchManager(str(tmp_path))
        try:
            warm(manager)
            methods = [d for d in manager._kw_docs if d.name == "Parser.parse"]
            assert len({d.id for d in methods}) == 2
            assert {(d.start_line, d.end_line) for d in methods} == {(2, 4), (5, 7)}
            body = manager._body_search(["parse"], 24, "Parser.java")
            hits = manager.search_candidates("parse", 24, "Parser.java")
            assert spans(body, "Parser.parse") == spans(hits, "Parser.parse") == {(2, 4), (5, 7)}
            assert len([h for h in hits if h.name == "Parser.parse"]) == 2  # no cross-list duplicates
            metadata = manager._keyword_search("parse", 24, "Parser.java")
            hydrated = hydrate_selected_sources(str(tmp_path), metadata)
            assert spans(hydrated, "Parser.parse") == {(2, 4), (5, 7)}
            assert all("return" in source_body(h) for h in hydrated if h.name == "Parser.parse")
        finally:
            manager.close()


@pytest.mark.parametrize("language", ["javascript", "rust"])
def test_anonymous_and_macro_windows_keep_distinct_source_ranges(tmp_path, language):
    filename = "callbacks.js" if language == "javascript" else "cases.rs"
    template = 'it("retry quota case{n}", function() {{\n  expect(quota).toEqual({n});\n}});\n' if language == "javascript" else 'rgtest!(retry_quota_{n}, |dir, cmd| {{\n  cmd.arg("quota");\n}});\n'
    (tmp_path / filename).write_text("".join(template.format(n=n) for n in range(40)))
    manager = SemanticSearchManager(str(tmp_path))
    try:
        warm(manager)
        conn = manager._open_body_db()
        try:
            stored = conn.execute("SELECT start_line,end_line FROM body_fts WHERE file_path=?", (filename,)).fetchall()
        finally:
            conn.close()
        assert len(stored) >= 4
        body = manager._body_search(["retry", "quota"], 24, filename)
        assert len({(h.start_line, h.end_line) for h in body}) >= 4
        hits = manager.search_candidates("retry quota", 24, filename)
        assert len({(h.start_line, h.end_line) for h in hits if h.start_line}) >= 4
    finally:
        manager.close()


def test_long_named_method_keeps_windows_and_keyword_boost_once(tmp_path):
    (tmp_path / "worker.py").write_text("class Worker:\n    def quota(self):\n" + "        quota = 1\n" * 100)
    manager = SemanticSearchManager(str(tmp_path))
    try:
        warm(manager)
        hits = manager.search_candidates("quota", 24, "worker.py")
        named = [h for h in hits if h.name == "Worker.quota"]
        assert len(named) >= 3
        assert len({(h.start_line, h.end_line) for h in named}) == len(named)
        assert all(h.end_line - h.start_line < 32 for h in named)
    finally:
        manager.close()


@pytest.mark.parametrize("change", ["edit", "rename", "delete"])
def test_span_cache_after_changes_matches_current_source(tmp_path, change):
    path = tmp_path / "Parser.java"
    path.write_text(JAVA)
    manager = SemanticSearchManager(str(tmp_path))
    warm(manager)
    manager.close()
    if change == "edit":
        path.write_text("\n\n" + JAVA)
    elif change == "rename":
        path.rename(tmp_path / "Renamed.java")
    else:
        path.unlink()
    manager = SemanticSearchManager(str(tmp_path))
    try:
        warm(manager)
        hits = manager.search_candidates("parse", 24)
        methods = [h for h in hits if h.name == "Parser.parse"]
        expected = {(4, 6), (7, 9)} if change == "edit" else {(2, 4), (5, 7)} if change == "rename" else set()
        assert spans(methods, "Parser.parse") == expected
        if change == "rename":
            assert all(h.file_path == "Renamed.java" for h in hits)
    finally:
        manager.close()


def test_v2_keyword_cache_is_invalidated_and_newer_cache_is_not_modified(tmp_path):
    (tmp_path / "Parser.java").write_text(JAVA)
    manager = SemanticSearchManager(str(tmp_path))
    try:
        warm(manager)
        conn = sqlite3.connect(manager._kw_cache_db_path)
        conn.execute("UPDATE metadata SET value='2' WHERE key='schema_version'")
        conn.commit()
        conn.close()
        manager._kw_index_built = False
        warm(manager)
        assert len({d.id for d in manager._kw_docs if d.name == "Parser.parse"}) == 2
        conn = sqlite3.connect(manager._kw_cache_db_path)
        assert conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone() == ("4",)
        conn.execute("UPDATE metadata SET value='999' WHERE key='schema_version'")
        conn.commit()
        conn.close()
        assert manager._open_kw_cache_db() is None
    finally:
        manager.close()


def test_duplicate_retrieval_rows_do_not_multiply_rrf_evidence(tmp_path, monkeypatch):
    manager = SemanticSearchManager(str(tmp_path))
    manager._kw_index_built = True
    hit = SemanticSearchResult("worker.py", "method", "Worker.quota", "quota", 1, 2, 4)
    monkeypatch.setattr(SemanticSearchManager, "_keyword_search", lambda *args: [])
    monkeypatch.setattr(SemanticSearchManager, "_file_search", lambda *args: [])
    monkeypatch.setattr(SemanticSearchManager, "_body_search", lambda *args: [hit, replace(hit)])
    try:
        result = manager.search_candidates("quota", 24)
        assert len(result) == 1
        assert result[0].score == round(manager.scoring_config.body_weight / (manager.scoring_config.chunk_rrf_k + 1), 6)
    finally:
        manager.close()


def test_extra_windows_preserve_navigation_to_other_named_owners(tmp_path, monkeypatch):
    manager = SemanticSearchManager(str(tmp_path))
    manager._kw_index_built = True
    first = SemanticSearchResult("worker.py", "method", "Worker.quota", "quota", 1, 2, 30)
    later = replace(first, start_line=27, end_line=55)
    last = replace(first, start_line=52, end_line=80)
    other = SemanticSearchResult("worker.py", "method", "Worker.limit", "quota limit", 1, 90, 95)
    monkeypatch.setattr(SemanticSearchManager, "_keyword_search", lambda *args: [])
    monkeypatch.setattr(SemanticSearchManager, "_file_search", lambda *args: [])
    monkeypatch.setattr(SemanticSearchManager, "_body_search", lambda *args: [first, other, later, last])
    try:
        hits = manager.search_candidates("quota", 24)
        assert [h.name for h in hits[:2]] == ["Worker.quota", "Worker.limit"]
        assert spans(hits, "Worker.quota") == {(2, 30), (27, 55), (52, 80)}
        assert manager.search_candidates("quota", 2) == hits[:2]
    finally:
        manager.close()


def test_v3_keyword_cache_is_rebuilt_with_python_docstrings(tmp_path):
    # v3 caches were built while the tree-sitter path dropped Python docstrings.
    (tmp_path / "box.py").write_text('def pack(item):\n    """Wrap the parcel."""\n    return item\n')
    manager = SemanticSearchManager(str(tmp_path))
    try:
        warm(manager)
        conn = sqlite3.connect(manager._kw_cache_db_path)
        conn.execute("UPDATE metadata SET value='3' WHERE key='schema_version'")
        conn.execute("UPDATE kw_docs SET text='stale'")
        conn.commit()
        conn.close()
    finally:
        manager.close()
    manager = SemanticSearchManager(str(tmp_path))
    try:
        warm(manager)
        texts = [d.text for d in manager._kw_docs if d.name == "pack"]
        assert texts and all("Wrap the parcel" in t for t in texts)
    finally:
        manager.close()
