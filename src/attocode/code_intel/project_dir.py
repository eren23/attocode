"""Project-directory discovery — MCP-free neutral helpers.

These functions used to live in ``attocode.code_intel._shared``, but
``_shared`` unconditionally imports ``mcp.server.fastmcp`` at module
load time and ``sys.exit(1)`` s if ``mcp`` isn't installed. The HTTP
API layer (``api/providers/``) needs to discover the current project
directory without dragging in the MCP runtime, so the logic is hosted
here.

``_shared`` re-exports both symbols for backward compatibility with
the 25-odd call sites that already import them via ``_shared``.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


def _walk_up(start: str, max_depth: int = 20) -> Iterator[str]:
    """Walk upward from start, yielding parent directories up to max_depth.

    Yields each ancestor directory starting from dirname(start) (the immediate
    parent), then climbing upward until filesystem root.
    """
    path = os.path.dirname(start)
    for _ in range(max_depth):
        yield path
        parent = os.path.dirname(path)
        if parent == path:
            break  # Reached filesystem root
        path = parent


def _get_project_dir() -> str:
    """Get the project directory from env var, CLI arg, or auto-discovery.

    Resolution order:
    1. ATTOCODE_PROJECT_DIR env var (set by --project CLI arg)
    2. Walk up from CWD looking for .git/ or .attocode/ marker
    3. Fall back to CWD
    """
    project_dir = os.environ.get("ATTOCODE_PROJECT_DIR", "")
    if project_dir:
        return os.path.abspath(project_dir)

    cwd = os.getcwd()
    markers = (".git", ".attocode")
    for dir_path in [cwd] + list(_walk_up(cwd)):
        for marker in markers:
            if os.path.isdir(os.path.join(dir_path, marker)):
                logger.debug(
                    "Auto-discovered project root: %s (marker: %s)",
                    dir_path, marker,
                )
                return dir_path

    logger.debug("No project marker found, falling back to CWD: %s", cwd)
    return cwd
