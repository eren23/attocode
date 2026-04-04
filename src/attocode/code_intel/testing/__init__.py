"""Testing utilities for attocode-code-intel.

This module provides standardized fixtures, mocks, and helpers for
testing code intelligence tools and MCP integrations.

Example usage in tests::

    import pytest
    from attocode.code_intel.testing import (
        code_intel_service,
        ast_service,
        sample_project,
        MockServiceFactory,
        create_sample_project,
    )

    class TestSearchTools:
        @pytest.fixture(autouse=True)
        def setup(self, code_intel_service, ast_service):
            self.service = code_intel_service
            self.ast = ast_service

        def test_symbol_search(self):
            result = search_tools.symbol_search(symbol_name="foo")
            assert "foo" in result
"""

from attocode.code_intel.testing.fixtures import (
    ast_service,
    code_intel_service,
    sample_project,
)
from attocode.code_intel.testing.mocks import MockServiceFactory
from attocode.code_intel.testing.helpers import create_sample_project, get_tool_names

__all__ = [
    "ast_service",
    "code_intel_service",
    "sample_project",
    "MockServiceFactory",
    "create_sample_project",
    "get_tool_names",
]
