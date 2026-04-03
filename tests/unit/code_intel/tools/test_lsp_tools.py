"""Unit tests for lsp_tools MCP tools.

Tests the following async tools:
- lsp_definition
- lsp_references
- lsp_hover
- lsp_diagnostics
- lsp_enrich
- lsp_completions
- lsp_workspace_symbol
- lsp_incoming_calls
- lsp_outgoing_calls

Run:
    pytest tests/unit/code_intel/tools/test_lsp_tools.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, AsyncMock

import pytest


class TestLSPTools:
    """Tests for lsp_tools.py async functions."""

    @pytest.fixture(autouse=True)
    def _setup(self, tool_test_project, mock_ast_service,
               mock_code_intel_service, mock_context_manager):
        """Setup mocks for LSP tool tests."""
        import attocode.code_intel._shared as ci_shared
        import attocode.code_intel.server as srv
        from attocode.code_intel.service import CodeIntelService

        # Reset singletons
        ci_shared._ast_service = None
        ci_shared._context_mgr = None
        ci_shared._service = None

        # Setup LSP manager mock
        lsp_mock = MagicMock()
        mock_location = MagicMock()
        mock_location.uri = f"file://{tool_test_project}/src/utils.py"
        mock_range = MagicMock()
        mock_range.start.line = 1
        mock_range.start.character = 0
        mock_range.end.line = 1
        mock_range.end.character = 10
        mock_location.range = mock_range

        lsp_mock.get_definition.return_value = mock_location
        lsp_mock.get_references.return_value = [mock_location]
        lsp_mock.get_hover.return_value = "def helper(value) -> str"
        lsp_mock.get_diagnostics.return_value = []

        srv._ast_service = mock_ast_service
        srv._context_mgr = mock_context_manager

        # Setup CodeIntelService with async LSP stubs
        cis = CodeIntelService.get_instance(str(tool_test_project))
        cis.lsp_completions = AsyncMock(return_value="stub:lsp_completions")
        cis.lsp_workspace_symbol = AsyncMock(return_value="stub:lsp_workspace_symbol")
        cis.lsp_incoming_calls = AsyncMock(return_value="stub:lsp_incoming_calls")
        cis.lsp_outgoing_calls = AsyncMock(return_value="stub:lsp_outgoing_calls")
        cis._lsp_manager = lsp_mock

        # Also set on lsp_tools module
        import attocode.code_intel.tools.lsp_tools as lt
        lt._lsp_manager = lsp_mock

        self._srv = srv
        self._cis = cis

        yield

        # Cleanup
        srv._ast_service = None
        srv._context_mgr = None
        cis._lsp_manager = None
        lt._lsp_manager = None

    @pytest.mark.asyncio
    async def test_lsp_definition(self):
        """Test lsp_definition returns a string."""
        from attocode.code_intel.tools.lsp_tools import lsp_definition

        result = await lsp_definition(file="src/main.py", line=5, col=4)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_lsp_references(self):
        """Test lsp_references returns a string."""
        from attocode.code_intel.tools.lsp_tools import lsp_references

        result = await lsp_references(file="src/utils.py", line=1, col=4)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_lsp_hover(self):
        """Test lsp_hover returns a string."""
        from attocode.code_intel.tools.lsp_tools import lsp_hover

        result = await lsp_hover(file="src/utils.py", line=1, col=4)
        assert isinstance(result, str)

    def test_lsp_diagnostics(self):
        """Test lsp_diagnostics returns a string."""
        from attocode.code_intel.tools.lsp_tools import lsp_diagnostics

        result = lsp_diagnostics(file="src/main.py")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_lsp_enrich(self):
        """Test lsp_enrich returns a string."""
        from attocode.code_intel.tools.lsp_tools import lsp_enrich

        result = await lsp_enrich(files=["src/main.py"])
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_lsp_completions(self):
        """Test lsp_completions returns stub result."""
        from attocode.code_intel.tools.lsp_tools import lsp_completions

        result = await lsp_completions(file="src/main.py", line=0, col=0, limit=10)
        assert isinstance(result, str)
        assert "stub:lsp_completions" in result

    @pytest.mark.asyncio
    async def test_lsp_workspace_symbol(self):
        """Test lsp_workspace_symbol returns stub result."""
        from attocode.code_intel.tools.lsp_tools import lsp_workspace_symbol

        result = await lsp_workspace_symbol(query="main", limit=5)
        assert isinstance(result, str)
        assert "stub:lsp_workspace_symbol" in result

    @pytest.mark.asyncio
    async def test_lsp_incoming_calls(self):
        """Test lsp_incoming_calls returns stub result."""
        from attocode.code_intel.tools.lsp_tools import lsp_incoming_calls

        result = await lsp_incoming_calls(file="src/main.py", line=4, col=0)
        assert isinstance(result, str)
        assert "stub:lsp_incoming_calls" in result

    @pytest.mark.asyncio
    async def test_lsp_outgoing_calls(self):
        """Test lsp_outgoing_calls returns stub result."""
        from attocode.code_intel.tools.lsp_tools import lsp_outgoing_calls

        result = await lsp_outgoing_calls(file="src/main.py", line=4, col=0)
        assert isinstance(result, str)
        assert "stub:lsp_outgoing_calls" in result
