"""Unit tests for server-level MCP tools.

Tests the notify_file_changed tool from server.py.

Run:
    pytest tests/unit/code_intel/tools/test_server_tools.py -v
"""

from __future__ import annotations

import pytest


class TestServerTools:
    """Tests for server-level tools."""

    @pytest.fixture(autouse=True)
    def _setup(self, tool_test_project, mock_ast_service,
               mock_code_intel_service, mock_context_manager):
        """Setup mocks for server tool tests."""
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

    def test_notify_file_changed(self):
        """Test notify_file_changed returns a string."""
        from attocode.code_intel.server import notify_file_changed

        result = notify_file_changed(files=["src/main.py"])
        assert isinstance(result, str)
