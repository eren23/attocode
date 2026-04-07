"""Unit tests for search_tools MCP tools.

Tests the following tools:
- semantic_search
- semantic_search_status
- security_scan
- fast_search

Run:
    pytest tests/unit/code_intel/tools/test_search_tools.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestSearchTools:
    """Tests for search_tools.py functions."""

    @pytest.fixture(autouse=True)
    def _setup(self, tool_test_project, mock_ast_service,
               mock_code_intel_service, mock_context_manager):
        """Setup mocks for search tool tests."""
        import attocode.code_intel._shared as ci_shared
        import attocode.code_intel.server as srv
        import attocode.code_intel.tools.search_tools as st

        # Reset singletons
        ci_shared._ast_service = None
        ci_shared._context_mgr = None
        ci_shared._service = None

        srv._ast_service = mock_ast_service
        srv._context_mgr = mock_context_manager

        # Mock semantic search manager
        sem_mock = MagicMock()
        sem_mock.search.return_value = []
        sem_mock.format_results.return_value = "No results found."
        progress_mock = MagicMock()
        progress_mock.total_files = 2
        progress_mock.indexed_files = 2
        progress_mock.failed_files = 0
        progress_mock.status = "complete"
        progress_mock.provider_name = "bm25"
        progress_mock.coverage = 1.0
        progress_mock.elapsed_seconds = 0.1
        sem_mock.get_index_progress.return_value = progress_mock
        sem_mock.provider_name = "bm25"
        sem_mock.is_available = True
        sem_mock.is_index_ready.return_value = True
        st._semantic_search = sem_mock

        # Mock security scanner
        sec_mock = MagicMock()
        sec_mock.scan.return_value = MagicMock(
            findings=[], score=100,
            summary="No security issues found.",
        )
        sec_mock.format_report.return_value = "Security score: 100/100\nNo issues found."
        st._security_scanner = sec_mock

        # Mock trigram index
        tri_mock = MagicMock()
        tri_mock.query.return_value = [
            MagicMock(path="src/main.py", line=5, text="    helper(42)", score=1.0),
        ]
        tri_mock.built = True
        st._trigram_index = tri_mock

        self._srv = srv
        self._st = st

        yield

        # Cleanup
        srv._ast_service = None
        srv._context_mgr = None
        st._semantic_search = None
        st._security_scanner = None
        st._trigram_index = None

    def test_semantic_search(self):
        """Test semantic_search returns a string."""
        from attocode.code_intel.tools.search_tools import semantic_search

        result = semantic_search(query="helper function", top_k=5)
        assert isinstance(result, str)

    def test_semantic_search_status(self):
        """Test semantic_search_status returns a string."""
        from attocode.code_intel.tools.search_tools import semantic_search_status

        result = semantic_search_status()
        assert isinstance(result, str)

    def test_security_scan(self):
        """Test security_scan returns a string."""
        from attocode.code_intel.tools.search_tools import security_scan

        result = security_scan(mode="full")
        assert isinstance(result, str)

    def test_fast_search(self):
        """Test fast_search returns a string."""
        from attocode.code_intel.tools.search_tools import fast_search

        result = fast_search(pattern="helper", max_results=10)
        assert isinstance(result, str)


class TestRegexSearch:
    """Tests for the regex_search tool."""

    @pytest.fixture(autouse=True)
    def _setup(self, tool_test_project, mock_ast_service,
               mock_code_intel_service, mock_context_manager):
        """Setup mocks for regex_search tests."""
        import attocode.code_intel._shared as ci_shared
        import attocode.code_intel.server as srv
        import attocode.code_intel.tools.search_tools as st

        # Reset singletons
        ci_shared._ast_service = None
        ci_shared._context_mgr = None
        ci_shared._service = None

        srv._ast_service = mock_ast_service
        srv._context_mgr = mock_context_manager

        # Force brute-force mode (no trigram index)
        st._trigram_index = None

        self._st = st
        self._project = tool_test_project

        yield

        # Cleanup
        srv._ast_service = None
        srv._context_mgr = None
        st._trigram_index = None

    def test_regex_search_returns_string(self):
        """Test regex_search returns a string."""
        from attocode.code_intel.tools.search_tools import regex_search

        result = regex_search(pattern="helper")
        assert isinstance(result, str)

    def test_regex_search_finds_matches(self):
        """Test regex_search finds known content with file:line: format."""
        from attocode.code_intel.tools.search_tools import regex_search

        # Write a file with known content
        target = self._project / "src" / "searchable.py"
        target.write_text("alpha\nbeta\ngamma\nalpha_two\n")

        result = regex_search(pattern="alpha")
        assert isinstance(result, str)
        assert "searchable.py" in result
        # Verify file:line: format
        assert "src/searchable.py:1:" in result
        assert "src/searchable.py:4:" in result
        assert "alpha_two" in result

    def test_regex_search_case_insensitive(self):
        """Test case_insensitive=True finds matches regardless of case."""
        from attocode.code_intel.tools.search_tools import regex_search

        target = self._project / "src" / "case_test.py"
        target.write_text("Hello World\nhello world\nHELLO WORLD\n")

        # Case-sensitive should not find uppercase when searching lowercase
        result_sensitive = regex_search(pattern="^hello", case_insensitive=False)
        assert "case_test.py:2:" in result_sensitive
        assert "case_test.py:1:" not in result_sensitive

        # Case-insensitive should find all three
        result_insensitive = regex_search(pattern="^hello", case_insensitive=True)
        assert "case_test.py:1:" in result_insensitive
        assert "case_test.py:2:" in result_insensitive
        assert "case_test.py:3:" in result_insensitive

    def test_regex_search_max_results(self):
        """Test that results are capped at max_results."""
        from attocode.code_intel.tools.search_tools import regex_search

        # Write a file with many matching lines
        target = self._project / "src" / "many_lines.py"
        lines = [f"match_line_{i}" for i in range(100)]
        target.write_text("\n".join(lines) + "\n")

        result = regex_search(pattern="match_line_", max_results=5)
        assert "limited to 5 results" in result
        # Count the file:line: entries — should be exactly 5
        match_lines = [l for l in result.splitlines() if "many_lines.py:" in l]
        assert len(match_lines) == 5

    def test_regex_search_no_matches(self):
        """Test that a pattern matching nothing returns 'No matches found.'."""
        from attocode.code_intel.tools.search_tools import regex_search

        result = regex_search(pattern="zzz_nonexistent_pattern_xyz")
        assert result == "No matches found."

    def test_regex_search_invalid_regex(self):
        """Test that an invalid regex returns an error message."""
        from attocode.code_intel.tools.search_tools import regex_search

        result = regex_search(pattern="[invalid(")
        assert result.startswith("Error: Invalid regex pattern:")

    def test_regex_search_path_filter(self):
        """Test that path parameter restricts search to a subdirectory."""
        from attocode.code_intel.tools.search_tools import regex_search

        # Write files in two different directories
        sub = self._project / "sub"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / "found.py").write_text("unique_marker_alpha\n")
        (self._project / "src" / "other.py").write_text("unique_marker_alpha\n")

        # Search only within 'sub' directory
        result = regex_search(pattern="unique_marker_alpha", path="sub")
        assert "found.py" in result
        assert "other.py" not in result
