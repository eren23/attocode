"""Unit tests for dead_code_tools MCP tool.

Tests the dead_code tool at different levels:
- symbol
- file
- module

Run:
    pytest tests/unit/code_intel/tools/test_dead_code_tools.py -v
"""

from __future__ import annotations

import pytest


class TestDeadCodeTools:
    """Tests for dead_code_tools.py functions."""

    @pytest.fixture(autouse=True)
    def _setup(self, tool_test_project, mock_ast_service,
               mock_code_intel_service, mock_context_manager):
        """Setup mocks for dead code tool tests."""
        import attocode.code_intel._shared as ci_shared
        import attocode.code_intel.server as srv

        # Reset singletons
        ci_shared._ast_service = None
        ci_shared._context_mgr = None
        ci_shared._service = None

        srv._ast_service = mock_ast_service
        srv._context_mgr = mock_context_manager

        self._srv = srv

        yield

        # Cleanup
        srv._ast_service = None
        srv._context_mgr = None

    def test_dead_code_symbol_level(self):
        """Test dead_code at symbol level returns a string."""
        from attocode.code_intel.tools.dead_code_tools import dead_code

        result = dead_code(level="symbol", top_n=10)
        assert isinstance(result, str)

    def test_dead_code_file_level(self):
        """Test dead_code at file level returns a string."""
        from attocode.code_intel.tools.dead_code_tools import dead_code

        result = dead_code(level="file", top_n=10)
        assert isinstance(result, str)

    def test_dead_code_module_level(self):
        """Test dead_code at module level returns a string."""
        from attocode.code_intel.tools.dead_code_tools import dead_code

        result = dead_code(level="module", top_n=10)
        assert isinstance(result, str)
