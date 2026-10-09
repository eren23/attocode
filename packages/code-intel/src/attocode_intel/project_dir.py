"""Project-directory discovery — MCP-free neutral helpers.

These functions used to live in ``attocode_intel._shared``, but
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
    from attocode_intel.request_context import current_request
    if (request := current_request.get()) is not None:
        return request.project_dir
    project_dir = os.environ.get("ATTOCODE_PROJECT_DIR", "")
    if project_dir:
        return os.path.abspath(project_dir)
    return find_project_root(os.getcwd())


def find_project_root(start: str) -> str:
    """Return the nearest directory at or above ``start`` with a project marker.

    The markers are ``.git`` (a directory, or a file in a worktree) and
    ``.attocode``. The search skips the home directory: ``~/.attocode`` holds
    user-wide settings and caches, so it does not make home a project. Before
    this rule, a server started in a folder without markers indexed the whole
    home directory. Without a marker, ``start`` is the root.
    """
    home = os.path.realpath(os.path.expanduser("~"))
    for dir_path in [start, *_walk_up(start)]:
        if os.path.realpath(dir_path) == home:
            continue
        for marker in (".git", ".attocode"):
            if os.path.exists(os.path.join(dir_path, marker)):
                logger.debug(
                    "Auto-discovered project root: %s (marker: %s)",
                    dir_path, marker,
                )
                return dir_path

    logger.debug("No project marker found, falling back to %s", start)
    return start
