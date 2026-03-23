"""Tests for CrossRefIndex multi-strategy symbol search."""

from __future__ import annotations

import pytest

from attocode.integrations.context.cross_references import (
    CrossRefIndex,
    SymbolLocation,
    _split_name_tokens,
)


# ------------------------------------------------------------------
# _split_name_tokens
# ------------------------------------------------------------------

class TestSplitNameTokens:
    def test_snake_case(self):
        assert _split_name_tokens("parse_config") == ["parse", "config"]

    def test_camel_case(self):
        assert _split_name_tokens("parseConfig") == ["parse", "config"]

    def test_pascal_case(self):
        assert _split_name_tokens("ParseConfig") == ["parse", "config"]

    def test_upper_acronym(self):
        assert _split_name_tokens("HTTPServer") == ["http", "server"]

    def test_html_parser(self):
        assert _split_name_tokens("HTMLParser") == ["html", "parser"]

    def test_all_caps(self):
        assert _split_name_tokens("MAX_RETRIES") == ["max", "retries"]

    def test_leading_underscore(self):
        assert _split_name_tokens("_main") == ["main"]

    def test_double_underscore(self):
        assert _split_name_tokens("__init__") == ["init"]

    def test_single_word(self):
        assert _split_name_tokens("Router") == ["router"]

    def test_short_name(self):
        assert _split_name_tokens("IO") == ["io"]

    def test_mixed(self):
        tokens = _split_name_tokens("getHTTPResponse_v2")
        assert "get" in tokens
        assert "http" in tokens
        assert "response" in tokens
        assert "v2" in tokens


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _loc(
    name: str,
    qname: str,
    kind: str = "function",
    path: str = "src/mod.py",
    start: int = 1,
    end: int = 10,
) -> SymbolLocation:
    return SymbolLocation(
        name=name,
        qualified_name=qname,
        kind=kind,
        file_path=path,
        start_line=start,
        end_line=end,
    )


def _build_index() -> CrossRefIndex:
    """Build a test index with diverse symbols."""
    idx = CrossRefIndex()
    idx.add_definition(_loc("Router", "Router", "class", "src/router.py"))
    idx.add_definition(_loc("AppRouter", "AppRouter", "class", "src/app.py"))
    idx.add_definition(_loc("parseConfig", "parseConfig", "function", "src/config.py"))
    idx.add_definition(_loc("parse_config", "parse_config", "function", "src/utils.py"))
    idx.add_definition(_loc("parse_file", "parse_file", "function", "src/parser.py"))
    idx.add_definition(_loc("discover_files", "CodebaseContextManager.discover_files", "method", "src/ctx.py"))
    idx.add_definition(_loc("_internal", "_internal", "function", "src/private.py"))
    idx.add_definition(_loc("HTTPServer", "HTTPServer", "class", "src/server.py"))
    idx.add_definition(_loc("exitCode", "exitCode", "variable", "cmd/main.go"))
    idx.add_definition(_loc("IO", "cats.effect.IO", "class", "core/io.scala"))
    return idx


# ------------------------------------------------------------------
# search_definitions
# ------------------------------------------------------------------

class TestSearchDefinitions:
    def test_exact_qualified_name(self):
        idx = _build_index()
        results = idx.search_definitions("Router")
        assert len(results) >= 1
        names = [loc.qualified_name for loc, _ in results]
        assert "Router" in names
        # Exact match should score highest
        top_loc, top_score = results[0]
        assert top_loc.qualified_name == "Router"
        assert top_score > 0.95

    def test_bare_name_match(self):
        idx = _build_index()
        results = idx.search_definitions("discover_files")
        names = [loc.qualified_name for loc, _ in results]
        assert "CodebaseContextManager.discover_files" in names

    def test_case_insensitive(self):
        idx = _build_index()
        results = idx.search_definitions("router")
        names = [loc.qualified_name for loc, _ in results]
        assert "Router" in names

    def test_prefix_match(self):
        idx = _build_index()
        results = idx.search_definitions("parse")
        names = [loc.qualified_name for loc, _ in results]
        assert "parseConfig" in names
        assert "parse_config" in names
        assert "parse_file" in names

    def test_substring_match(self):
        idx = _build_index()
        results = idx.search_definitions("Config")
        names = [loc.qualified_name for loc, _ in results]
        assert "parseConfig" in names
        assert "parse_config" in names

    def test_token_overlap(self):
        """'parse_config' should find 'parseConfig' via shared tokens."""
        idx = _build_index()
        results = idx.search_definitions("parse_config")
        names = [loc.qualified_name for loc, _ in results]
        # Exact match on parse_config
        assert "parse_config" in names
        # Token overlap should also find parseConfig
        assert "parseConfig" in names

    def test_ranking_order(self):
        """Exact matches should score higher than fuzzy matches."""
        idx = _build_index()
        results = idx.search_definitions("Router")
        scores = {loc.qualified_name: score for loc, score in results}
        # Exact "Router" should score > prefix/substring "AppRouter"
        assert scores["Router"] > scores["AppRouter"]

    def test_kind_filter(self):
        idx = _build_index()
        results = idx.search_definitions("Router", kind_filter="class")
        assert all(loc.kind == "class" for loc, _ in results)
        # Variable should not appear
        results_var = idx.search_definitions("exitCode", kind_filter="class")
        assert len(results_var) == 0

    def test_limit(self):
        idx = _build_index()
        results = idx.search_definitions("parse", limit=2)
        assert len(results) <= 2

    def test_no_results(self):
        idx = _build_index()
        results = idx.search_definitions("nonexistent_xyz")
        assert results == []

    def test_private_symbol_ranked_lower(self):
        idx = _build_index()
        # Add a public function with similar name
        idx.add_definition(_loc("internal", "internal", "function", "src/pub.py"))
        results = idx.search_definitions("internal")
        scores = {loc.qualified_name: score for loc, score in results}
        # Public "internal" should rank higher than "_internal"
        assert scores["internal"] > scores["_internal"]

    def test_class_ranked_higher_than_function(self):
        idx = CrossRefIndex()
        idx.add_definition(_loc("Config", "Config", "class", "a.py"))
        idx.add_definition(_loc("Config", "Config2.Config", "function", "b.py"))
        results = idx.search_definitions("Config")
        # Both found, class should be first
        assert results[0][0].kind == "class"


# ------------------------------------------------------------------
# remove_file cleans up inverted indexes
# ------------------------------------------------------------------

class TestRemoveFileCleanup:
    def test_remove_cleans_inverted_index(self):
        idx = CrossRefIndex()
        idx.add_definition(_loc("Router", "Router", "class", "src/router.py"))
        idx.add_definition(_loc("AppRouter", "AppRouter", "class", "src/app.py"))

        # Both findable
        assert len(idx.search_definitions("Router")) >= 2

        # Remove router.py
        idx.remove_file("src/router.py")

        # Router qname should be gone from definitions
        assert "Router" not in idx.definitions

        # But AppRouter should still be findable
        results = idx.search_definitions("AppRouter")
        assert len(results) >= 1
        assert results[0][0].qualified_name == "AppRouter"

        # "Router" search should still find AppRouter (via substring/token)
        results = idx.search_definitions("Router")
        names = [loc.qualified_name for loc, _ in results]
        assert "AppRouter" in names
        assert "Router" not in names

    def test_remove_all_files_empties_indexes(self):
        idx = CrossRefIndex()
        idx.add_definition(_loc("Foo", "Foo", "class", "a.py"))
        idx.remove_file("a.py")
        assert idx._name_to_qnames == {}
        assert idx._lower_to_qnames == {}
        assert idx._tokens_to_qnames == {}


# ------------------------------------------------------------------
# get_definitions backward compat
# ------------------------------------------------------------------

class TestGetDefinitionsBackwardCompat:
    def test_exact_match(self):
        idx = _build_index()
        locs = idx.get_definitions("Router")
        assert len(locs) == 1
        assert locs[0].qualified_name == "Router"

    def test_suffix_match(self):
        idx = _build_index()
        locs = idx.get_definitions("discover_files")
        assert len(locs) == 1
        assert locs[0].qualified_name == "CodebaseContextManager.discover_files"
