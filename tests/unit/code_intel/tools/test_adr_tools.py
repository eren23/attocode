"""Unit tests for adr_tools MCP tools.

Tests the following tools:
- record_adr
- list_adrs
- get_adr
- update_adr_status

Run:
    pytest tests/unit/code_intel/tools/test_adr_tools.py -v
"""

from __future__ import annotations

import pytest


class TestADRTools:
    """Tests for adr_tools.py functions."""

    @pytest.fixture(autouse=True)
    def _setup(self, tool_test_project, mock_ast_service,
               mock_code_intel_service, mock_context_manager):
        """Setup mocks for ADR tool tests."""
        import attocode.code_intel._shared as ci_shared
        import attocode.code_intel.server as srv
        import attocode.code_intel.tools.adr_tools as at

        # Reset singletons
        ci_shared._ast_service = None
        ci_shared._context_mgr = None
        ci_shared._service = None

        srv._ast_service = mock_ast_service
        srv._context_mgr = mock_context_manager

        # Ensure .attocode dir exists for SQLite stores
        (tool_test_project / ".attocode").mkdir(exist_ok=True)

        # Reset ADR store singleton
        at._adr_store = None

        self._srv = srv
        self._at = at

        yield

        # Cleanup
        srv._ast_service = None
        srv._context_mgr = None
        at._adr_store = None

    def test_record_adr(self):
        """Test record_adr returns a string with ADR info."""
        from attocode.code_intel.tools.adr_tools import record_adr

        result = record_adr(
            title="Use PostgreSQL",
            context="Need a relational database",
            decision="Use PostgreSQL for all storage",
            consequences="Must maintain migrations",
        )
        assert isinstance(result, str)
        # Should contain some indication of the ADR
        assert "ADR" in result or "adr" in result.lower() or "#" in result

    def test_list_adrs(self):
        """Test list_adrs returns a string."""
        from attocode.code_intel.tools.adr_tools import record_adr, list_adrs

        record_adr(title="Test ADR", context="ctx", decision="dec")
        result = list_adrs()
        assert isinstance(result, str)

    def test_get_adr(self):
        """Test get_adr returns a string."""
        from attocode.code_intel.tools.adr_tools import record_adr, get_adr

        record_adr(title="Test ADR", context="ctx", decision="dec")
        result = get_adr(number=1)
        assert isinstance(result, str)

    def test_update_adr_status(self):
        """Test update_adr_status returns a string."""
        from attocode.code_intel.tools.adr_tools import record_adr, update_adr_status

        record_adr(title="Test ADR", context="ctx", decision="dec")
        result = update_adr_status(number=1, status="accepted")
        assert isinstance(result, str)
