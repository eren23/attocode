"""Mock factories for code intelligence testing.

Provides standardized mock objects for CodeIntelService, ASTService,
and related components. Use these when you need to mock rather than
use real services.

Usage::

    from attocode.code_intel.testing.mocks import MockServiceFactory

    factory = MockServiceFactory()
    mock_service = factory.code_intel_service()
    mock_service.search_symbols.return_value = [...]
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, AsyncMock

if TYPE_CHECKING:
    from attocode.code_intel.service import CodeIntelService
    from attocode.integrations.context.ast_service import ASTService
    from attocode.integrations.context.codebase_context import CodebaseContextManager


class MockServiceFactory:
    """Factory for creating standardized mock services.

    Example::

        factory = MockServiceFactory()

        # Mock just the service
        mock_svc = factory.code_intel_service()

        # Mock with custom behavior
        mock_svc = factory.code_intel_service(
            search_symbols_return={"foo": [SymbolLocation(...)]}
        )
    """

    def code_intel_service(
        self,
        *,
        search_symbols_return: dict | None = None,
        search_code_return: str = "",
        get_repo_map_return: dict | None = None,
        get_dependencies_return: dict | None = None,
    ) -> "CodeIntelService":
        """Create a mock CodeIntelService.

        Args:
            search_symbols_return: Return value for search_symbols()
            search_code_return: Return value for search_code()
            get_repo_map_return: Return value for get_repo_map()
            get_dependencies_return: Return value for get_dependencies()
        """
        from attocode.code_intel.service import CodeIntelService

        mock = MagicMock(spec=CodeIntelService)

        if search_symbols_return is not None:
            mock.search_symbols.return_value = search_symbols_return
        else:
            mock.search_symbols.return_value = {}

        mock.search_code.return_value = search_code_return
        mock.get_repo_map.return_value = get_repo_map_return or {}
        mock.get_dependencies.return_value = get_dependencies_return or {}

        return mock

    def ast_service(self) -> "ASTService":
        """Create a mock ASTService."""
        from attocode.integrations.context.ast_service import ASTService

        mock = MagicMock(spec=ASTService)
        mock.initialized = True
        mock.get_file_ast.return_value = None
        mock.search_symbol.return_value = []
        return mock

    def context_manager(self) -> "CodebaseContextManager":
        """Create a mock CodebaseContextManager."""
        from attocode.integrations.context.codebase_context import CodebaseContextManager

        mock = MagicMock(spec=CodebaseContextManager)
        mock.discover_files.return_value = []
        return mock

    def cross_ref_index(self) -> "CrossRefIndex":
        """Create a mock CrossRefIndex."""
        from attocode.integrations.context.cross_references import CrossRefIndex

        mock = MagicMock(spec=CrossRefIndex)
        mock.search.return_value = []
        mock.get_definitions.return_value = []
        return mock


class AsyncMockServiceFactory(MockServiceFactory):
    """Factory for creating async mock services.

    Use this when testing async code paths.
    """

    def code_intel_service(self, **kwargs) -> "CodeIntelService":
        """Create an async mock CodeIntelService."""
        mock = super().code_intel_service(**kwargs)
        mock.search_symbols = AsyncMock(return_value=kwargs.get("search_symbols_return", {}))
        mock.search_code = AsyncMock(return_value=kwargs.get("search_code_return", ""))
        return mock
