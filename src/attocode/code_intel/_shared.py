"""Shared dependencies for code-intel MCP tool modules.

Extracted from server.py to break the circular import:
  server.py → tool modules → server.py

Tool modules should import from here instead of server.py.
server.py re-exports these symbols for backward compatibility.

Note: Existing tests set ``server._ast_service = mock`` directly on the
server module's ``__dict__``. The ``_check_server_override`` helper
ensures the getters respect those overrides without requiring tests to
change.
"""

from __future__ import annotations

import logging
import os
import sys

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print(
        "Error: 'mcp' package not installed. "
        "Reinstall with: uv tool install --force --reinstall --from . attocode",
        file=sys.stderr,
    )
    sys.exit(1)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastMCP instance (singleton)
# ---------------------------------------------------------------------------

mcp = FastMCP("attocode-code-intel")

# ---------------------------------------------------------------------------
# Lazily initialized singletons
# ---------------------------------------------------------------------------

_ast_service = None
_context_mgr = None
_code_analyzer = None
_semantic_search = None  # Backward compat: tests may set this directly
_memory_store = None  # Backward compat: tests may set this directly
_explorer = None
_service = None


def _check_server_override(name: str):
    """Return the value of *name* from ``server.__dict__`` if set there.

    Tests (and some internal code) set e.g. ``server._ast_service = mock``
    directly. Since getters live here, we must check the server module's
    __dict__ so those overrides are respected. Uses sys.modules to avoid
    a circular import.
    """
    srv = sys.modules.get("attocode.code_intel.server")
    if srv is not None and name in srv.__dict__:
        return srv.__dict__[name]
    return None


def _get_project_dir() -> str:
    """Get the project directory from env var or raise."""
    project_dir = os.environ.get("ATTOCODE_PROJECT_DIR", "")
    if not project_dir:
        raise RuntimeError(
            "ATTOCODE_PROJECT_DIR not set. "
            "Pass --project <path> or set the environment variable."
        )
    return os.path.abspath(project_dir)


def _get_ast_service():
    """Lazily initialize and return the ASTService singleton."""
    global _ast_service
    override = _check_server_override("_ast_service")
    if override is not None:
        return override
    if _ast_service is None:
        from attocode.integrations.context.ast_service import ASTService

        project_dir = _get_project_dir()
        _ast_service = ASTService.get_instance(project_dir)
        if not _ast_service.initialized:
            logger.info("Initializing ASTService for %s...", project_dir)
            _ast_service.initialize()
            logger.info(
                "ASTService ready: %d files indexed",
                len(_ast_service._ast_cache),
            )
    return _ast_service


def _get_context_mgr():
    """Lazily initialize and return the CodebaseContextManager."""
    global _context_mgr
    override = _check_server_override("_context_mgr")
    if override is not None:
        return override
    if _context_mgr is None:
        from attocode.integrations.context.codebase_context import CodebaseContextManager

        project_dir = _get_project_dir()
        _context_mgr = CodebaseContextManager(root_dir=project_dir)
        _context_mgr.discover_files()
    return _context_mgr


def _get_code_analyzer():
    """Lazily initialize and return the CodeAnalyzer."""
    global _code_analyzer
    override = _check_server_override("_code_analyzer")
    if override is not None:
        return override
    if _code_analyzer is None:
        from attocode.integrations.context.code_analyzer import CodeAnalyzer

        _code_analyzer = CodeAnalyzer()
    return _code_analyzer


def _get_service():
    """Lazily initialize and return the CodeIntelService singleton."""
    global _service
    override = _check_server_override("_service")
    if override is not None:
        return override
    if _service is None:
        from attocode.code_intel.service import CodeIntelService

        project_dir = _get_project_dir()
        _service = CodeIntelService.get_instance(project_dir)
    return _service


def _get_explorer():
    """Lazily initialize the hierarchical explorer."""
    global _explorer
    override = _check_server_override("_explorer")
    if override is not None:
        return override
    if _explorer is None:
        from attocode.integrations.context.hierarchical_explorer import HierarchicalExplorer
        ctx = _get_context_mgr()
        ast_svc = _get_ast_service()
        _explorer = HierarchicalExplorer(ctx, ast_service=ast_svc)
    return _explorer
