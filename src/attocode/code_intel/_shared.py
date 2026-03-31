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
_remote_service = None


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
    srv = sys.modules.get("attocode.code_intel.server")
    if srv is not None and "_service" in srv.__dict__:
        override = srv.__dict__["_service"]
        if override is None:
            _service = None
        else:
            return override
    if _remote_service is not None:
        return _remote_service
    if _service is not None:
        from attocode.code_intel import service as code_intel_service_module

        if _service.project_dir not in code_intel_service_module._instances:
            _service = None
    if _service is None:
        from attocode.code_intel.service import CodeIntelService

        project_dir = _get_project_dir()
        _service = CodeIntelService.get_instance(project_dir)
    return _service


def _get_remote_service():
    """Return the configured remote text service, if any."""
    srv = sys.modules.get("attocode.code_intel.server")
    if srv is not None and "_remote_service" in srv.__dict__:
        return srv.__dict__["_remote_service"]
    return _remote_service


def configure_remote_service(remote_url: str, remote_token: str, remote_repo_id: str) -> None:
    """Configure the shared service getter to proxy through a remote HTTP service."""
    global _remote_service, _service
    from attocode.code_intel.api.providers.remote_provider import RemoteTextService

    _service = None
    _remote_service = RemoteTextService(remote_url, remote_token, remote_repo_id)


def clear_remote_service() -> None:
    """Reset remote service wiring."""
    global _remote_service
    if _remote_service is not None:
        try:
            _remote_service.close()
        except Exception:
            pass
    _remote_service = None


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
