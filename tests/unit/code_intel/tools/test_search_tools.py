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
