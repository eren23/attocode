"""Unit tests for distill_tools MCP tool.

Tests the distill tool at different levels:
- signatures
- structure
- full

Run:
    pytest tests/unit/code_intel/tools/test_distill_tools.py -v
"""

from __future__ import annotations

import pytest


class TestDistillTools:
    """Tests for distill_tools.py functions."""

    @pytest.fixture(autouse=True)
    def _setup(self, tool_test_project, mock_ast_service,
               mock_code_intel_service, mock_context_manager):
        """Setup mocks for distill tool tests."""
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

    def test_distill_signatures_level(self):
        """Test distill at signatures level returns a string."""
        from attocode.code_intel.tools.distill_tools import distill

        result = distill(level="signatures", max_tokens=2000)
        assert isinstance(result, str)

    def test_distill_structure_level(self):
        """Test distill at structure level returns a string."""
        from attocode.code_intel.tools.distill_tools import distill

        result = distill(level="structure", max_tokens=2000)
        assert isinstance(result, str)

    def test_distill_full_level(self):
        """Test distill at full level returns a string."""
        from attocode.code_intel.tools.distill_tools import distill

        result = distill(level="full", max_tokens=2000)
        assert isinstance(result, str)
