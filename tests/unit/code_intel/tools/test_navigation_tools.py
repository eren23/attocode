"""Unit tests for navigation_tools MCP tools.

Tests the following tools:
- repo_map
- symbols
- search_symbols
- explore_codebase
- project_summary
- bootstrap
- hydration_status
- conventions
- relevant_context
- reindex

Run:
    pytest tests/unit/code_intel/tools/test_navigation_tools.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock

import pytest


class TestNavigationTools:
    """Tests for navigation_tools.py functions."""

    @pytest.fixture(autouse=True)
    def _setup(self, tool_test_project, mock_ast_service,
               mock_code_intel_service, mock_context_manager):
        """Setup mocks for all navigation tool tests."""
        import attocode.code_intel._shared as ci_shared
        import attocode.code_intel.server as srv

        # Reset singletons
        ci_shared._ast_service = None
        ci_shared._context_mgr = None
        ci_shared._service = None

        # Setup explorer mock
        srv._ast_service = mock_ast_service
        srv._context_mgr = mock_context_manager
        srv._explorer = MagicMock()
        srv._explorer.explore.return_value = MagicMock(
            entries=[], total_files=2, total_dirs=1
        )
        srv._explorer.format_result.return_value = "src/\n  main.py\n  utils.py"

        self._srv = srv

        yield

        # Cleanup
        srv._ast_service = None
        srv._context_mgr = None
        srv._explorer = None

    def test_repo_map(self):
        """Test repo_map returns a string."""
        from attocode.code_intel.tools.navigation_tools import repo_map

        result = repo_map(include_symbols=True, max_tokens=2000)
        assert isinstance(result, str)

    def test_symbols(self):
        """Test symbols returns a string."""
        from attocode.code_intel.tools.navigation_tools import symbols

        result = symbols("src/main.py")
        assert isinstance(result, str)

    def test_search_symbols(self):
        """Test search_symbols returns a string."""
        from attocode.code_intel.tools.navigation_tools import search_symbols

        result = search_symbols("helper", limit=10)
        assert isinstance(result, str)

    def test_explore_codebase(self):
        """Test explore_codebase returns a string."""
        from attocode.code_intel.tools.navigation_tools import explore_codebase

        result = explore_codebase(path="", max_items=10)
        assert isinstance(result, str)

    def test_project_summary(self):
        """Test project_summary returns a string."""
        from attocode.code_intel.tools.navigation_tools import project_summary

        result = project_summary(max_tokens=2000)
        assert isinstance(result, str)

    def test_bootstrap(self):
        """Test bootstrap returns a string."""
        from attocode.code_intel.tools.navigation_tools import bootstrap

        result = bootstrap(task_hint="testing", max_tokens=4000)
        assert isinstance(result, str)

    def test_hydration_status(self):
        """Test hydration_status returns a string with tier info."""
        from attocode.code_intel.tools.navigation_tools import hydration_status

        result = hydration_status()
        assert isinstance(result, str)
        assert "Tier:" in result

    def test_conventions(self):
        """Test conventions returns a string."""
        from attocode.code_intel.tools.navigation_tools import conventions

        result = conventions(sample_size=10)
        assert isinstance(result, str)

    def test_relevant_context(self):
        """Test relevant_context returns a string."""
        from attocode.code_intel.tools.navigation_tools import relevant_context

        result = relevant_context(files=["src/main.py"], depth=1, max_tokens=2000)
        assert isinstance(result, str)

    def test_reindex(self):
        """Test reindex returns a string."""
        from attocode.code_intel.tools.navigation_tools import reindex

        result = reindex(force=False)
        assert isinstance(result, str)
