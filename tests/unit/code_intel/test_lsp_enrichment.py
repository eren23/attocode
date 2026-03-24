"""Tests for LSP → CrossRefIndex enrichment flow."""

from __future__ import annotations

import pytest

from attocode.integrations.context.cross_references import (
    CrossRefIndex,
    SymbolLocation,
    SymbolRef,
)


class TestMergeLspResults:
    """Test CrossRefIndex.merge_lsp_results()."""

    def _make_index(self) -> CrossRefIndex:
        idx = CrossRefIndex()
        # Add tree-sitter definitions
        idx.add_definition(SymbolLocation(
            name="parse", qualified_name="parse", kind="function",
            file_path="src/parser.py", start_line=10, end_line=20,
        ))
        idx.add_definition(SymbolLocation(
            name="Config", qualified_name="Config", kind="class",
            file_path="src/config.py", start_line=5, end_line=50,
        ))
        # Add tree-sitter references
        idx.add_reference(SymbolRef(
            symbol_name="parse", ref_kind="call",
            file_path="src/main.py", line=15,
        ))
        return idx

    def test_merge_adds_new_definitions(self):
        idx = self._make_index()
        added = idx.merge_lsp_results(
            "src/parser.py",
            definitions=[SymbolLocation(
                name="helper", qualified_name="helper", kind="function",
                file_path="src/parser.py", start_line=25, end_line=30,
            )],
            references=[],
        )
        assert added == 1
        # The new definition should be findable
        locs = idx.get_definitions("helper")
        assert len(locs) == 1
        assert locs[0].source == "lsp"

    def test_merge_replaces_tree_sitter_at_same_location(self):
        idx = self._make_index()
        # Add LSP definition at same location as tree-sitter one
        added = idx.merge_lsp_results(
            "src/parser.py",
            definitions=[SymbolLocation(
                name="parse", qualified_name="parse", kind="function",
                file_path="src/parser.py", start_line=10, end_line=20,
            )],
            references=[],
        )
        # Should replace, not add
        assert added == 0
        locs = idx.get_definitions("parse")
        assert len(locs) == 1
        assert locs[0].source == "lsp"

    def test_merge_adds_new_references(self):
        idx = self._make_index()
        added = idx.merge_lsp_results(
            "src/utils.py",
            definitions=[],
            references=[SymbolRef(
                symbol_name="parse", ref_kind="call",
                file_path="src/utils.py", line=8,
            )],
        )
        assert added == 1
        refs = idx.get_references("parse")
        lsp_refs = [r for r in refs if r.source == "lsp"]
        assert len(lsp_refs) == 1

    def test_merge_deduplicates_references(self):
        idx = self._make_index()
        # Add LSP reference at same location as tree-sitter one
        added = idx.merge_lsp_results(
            "src/main.py",
            definitions=[],
            references=[SymbolRef(
                symbol_name="parse", ref_kind="call",
                file_path="src/main.py", line=15,
            )],
        )
        assert added == 0  # duplicate, not added

    def test_lsp_source_tag_set(self):
        idx = self._make_index()
        idx.merge_lsp_results(
            "src/new.py",
            definitions=[SymbolLocation(
                name="new_func", qualified_name="new_func", kind="function",
                file_path="src/new.py", start_line=1, end_line=5,
                source="tree-sitter",  # should be overwritten to "lsp"
            )],
            references=[SymbolRef(
                symbol_name="Config", ref_kind="call",
                file_path="src/new.py", line=3,
                source="tree-sitter",
            )],
        )
        locs = idx.get_definitions("new_func")
        assert locs[0].source == "lsp"
        refs = idx.get_references("Config")
        lsp_refs = [r for r in refs if r.file_path == "src/new.py"]
        assert lsp_refs[0].source == "lsp"


class TestLspRankingBoost:
    """Test that LSP-sourced entries rank higher."""

    def test_lsp_source_ranks_higher(self):
        idx = CrossRefIndex()
        # Add same bare name from tree-sitter and LSP in different files
        # Both use qualified names that match via bare-name lookup (score 0.95)
        idx.add_definition(SymbolLocation(
            name="process", qualified_name="mod_a.process", kind="function",
            file_path="src/a.py", start_line=1, end_line=10,
            source="tree-sitter",
        ))
        idx.add_definition(SymbolLocation(
            name="process", qualified_name="mod_b.process", kind="function",
            file_path="src/b.py", start_line=1, end_line=10,
            source="lsp",
        ))

        results = idx.search_definitions("process", limit=10)
        assert len(results) == 2
        # LSP-sourced should rank higher due to +0.05 boost
        lsp_result = [(loc, score) for loc, score in results if loc.source == "lsp"]
        ts_result = [(loc, score) for loc, score in results if loc.source == "tree-sitter"]
        assert lsp_result[0][1] > ts_result[0][1]

    def test_source_field_defaults_to_tree_sitter(self):
        loc = SymbolLocation(
            name="x", qualified_name="x", kind="function",
            file_path="f.py", start_line=1, end_line=1,
        )
        assert loc.source == "tree-sitter"

        ref = SymbolRef(
            symbol_name="x", ref_kind="call",
            file_path="f.py", line=1,
        )
        assert ref.source == "tree-sitter"


class TestPersistenceWithStore:
    """Test that merge_lsp_results persists via store when available."""

    def test_persist_file_called_on_merge(self, tmp_path):
        from attocode.integrations.context.index_store import IndexStore, StoredFile

        db_path = str(tmp_path / "test.db")
        store = IndexStore(db_path=db_path)

        # Need a file entry for foreign key
        store.save_file(StoredFile(
            path="src/main.py", mtime=0, size=0,
            language="python", line_count=0, content_hash="",
        ))

        idx = CrossRefIndex()
        idx.set_store(store)

        # Add a tree-sitter definition first
        idx.add_definition(SymbolLocation(
            name="foo", qualified_name="foo", kind="function",
            file_path="src/main.py", start_line=1, end_line=5,
        ))
        idx.persist_file("src/main.py")

        # Now merge LSP results
        idx.merge_lsp_results(
            "src/main.py",
            definitions=[SymbolLocation(
                name="bar", qualified_name="bar", kind="function",
                file_path="src/main.py", start_line=10, end_line=15,
            )],
            references=[],
        )

        # Verify persisted to store
        stored = store.load_symbols("src/main.py")
        names = {s.name for s in stored}
        assert "foo" in names
        assert "bar" in names
        lsp_symbols = [s for s in stored if s.source == "lsp"]
        assert len(lsp_symbols) >= 1

        store.close()
