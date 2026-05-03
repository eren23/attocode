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
from typing import TYPE_CHECKING

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print(
        "Error: 'mcp' package not installed. "
        "Reinstall with: uv tool install --force --reinstall --from . attocode",
        file=sys.stderr,
    )
    sys.exit(1)

if TYPE_CHECKING:
    from attocode.code_intel.api.providers.remote_provider import RemoteTextService
    from attocode.code_intel.service import CodeIntelService
    from attocode.integrations.context.ast_service import ASTService
    from attocode.integrations.context.code_analyzer import CodeAnalyzer
    from attocode.integrations.context.codebase_context import CodebaseContextManager
    from attocode.integrations.context.frecency import FrecencyTracker
    from attocode.integrations.context.hierarchical_explorer import HierarchicalExplorer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastMCP instance (singleton)
# ---------------------------------------------------------------------------

mcp = FastMCP("attocode-code-intel")

# ---------------------------------------------------------------------------
# Lazily initialized singletons
# ---------------------------------------------------------------------------

_ast_service: ASTService | None = None
_context_mgr: CodebaseContextManager | None = None
_code_analyzer: CodeAnalyzer | None = None
_semantic_search: object | None = None  # Backward compat: tests may set this directly
_memory_store: object | None = None  # Backward compat: tests may set this directly
_explorer: HierarchicalExplorer | None = None
_service: CodeIntelService | None = None
_remote_service: RemoteTextService | None = None


def _check_server_override(name: str) -> object | None:
    """Return the value of *name* from ``server.__dict__`` if set there.

    Tests (and some internal code) set e.g. ``server._ast_service = mock``
    directly. Since getters live here, we must check the server module's
    __dict__ so those overrides are respected. Uses sys.modules to avoid
    a circular import.
    """
    srv = sys.modules.get("attocode.code_intel.server")
    if srv is not None and name in srv.__dict__:
        return srv.__dict__[name]  # type: ignore[no-any-return]
    return None


# Project-directory discovery lives in the neutral ``project_dir``
# module so HTTP providers can import it without dragging in the MCP
# runtime. Re-export here for backward compatibility with the existing
# ~25 call sites that do ``from attocode.code_intel._shared import
# _get_project_dir`` (or access it as ``_shared._get_project_dir``).
from attocode.code_intel.project_dir import (  # noqa: F401, E402
    _get_project_dir,
    _walk_up,
)


def _get_ast_service() -> ASTService:
    """Lazily initialize and return the ASTService singleton."""
    global _ast_service
    override = _check_server_override("_ast_service")
    if override is not None:
        return override  # type: ignore[return-value]
    if _ast_service is None:
        from attocode.integrations.context.ast_service import ASTService

        project_dir = _get_project_dir()
        _ast_service = ASTService.get_instance(project_dir)
        if not _ast_service.initialized:
            logger.info("Initializing ASTService (skeleton) for %s...", project_dir)
            _ast_service.initialize_skeleton(indexing_depth="auto")
            if (
                _ast_service._hydration_state
                and _ast_service._hydration_state.phase != "ready"
            ):
                _ast_service.start_hydration()
            logger.info(
                "ASTService ready: %d files indexed (skeleton/hydration)",
                len(_ast_service._ast_cache),
            )
    return _ast_service


def _get_context_mgr() -> CodebaseContextManager:
    """Lazily initialize and return the CodebaseContextManager."""
    global _context_mgr
    override = _check_server_override("_context_mgr")
    if override is not None:
        return override  # type: ignore[return-value]
    if _context_mgr is None:
        from attocode.integrations.context.codebase_context import CodebaseContextManager

        project_dir = _get_project_dir()
        _context_mgr = CodebaseContextManager(root_dir=project_dir)
        _context_mgr.discover_files()
    return _context_mgr


def _get_code_analyzer() -> CodeAnalyzer:
    """Lazily initialize and return the CodeAnalyzer."""
    global _code_analyzer
    override = _check_server_override("_code_analyzer")
    if override is not None:
        return override  # type: ignore[return-value]
    if _code_analyzer is None:
        from attocode.integrations.context.code_analyzer import CodeAnalyzer

        _code_analyzer = CodeAnalyzer()
    return _code_analyzer


def _get_service() -> CodeIntelService | RemoteTextService:
    """Lazily initialize and return the CodeIntelService singleton."""
    global _service
    srv = sys.modules.get("attocode.code_intel.server")
    if srv is not None and "_service" in srv.__dict__:
        override = srv.__dict__["_service"]
        if override is None:
            _service = None
        else:
            return override  # type: ignore[no-any-return]
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


def _get_remote_service() -> RemoteTextService | None:
    """Return the configured remote text service, if any."""
    srv = sys.modules.get("attocode.code_intel.server")
    if srv is not None and "_remote_service" in srv.__dict__:
        return srv.__dict__["_remote_service"]  # type: ignore[no-any-return]
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


def _get_explorer() -> HierarchicalExplorer:
    """Lazily initialize the hierarchical explorer."""
    global _explorer
    override = _check_server_override("_explorer")
    if override is not None:
        return override  # type: ignore[return-value]
    if _explorer is None:
        from attocode.integrations.context.hierarchical_explorer import HierarchicalExplorer
        ctx = _get_context_mgr()
        ast_svc = _get_ast_service()
        _explorer = HierarchicalExplorer(ctx, ast_service=ast_svc)
    return _explorer


def _get_frecency_tracker() -> FrecencyTracker:
    """Get shared frecency tracker (thread-safe via get_tracker lock)."""
    from attocode.integrations.context.frecency import get_tracker

    project_dir = _get_project_dir()
    db_path = os.path.join(project_dir, ".attocode", "frecency")
    return get_tracker(db_path=db_path)
