"""Attocode Code Intelligence MCP Server.

Exports are lazy-loaded to avoid pulling in heavy dependencies (tree-sitter,
numpy, AST parsing) at import time.  Basic sessions that only use grep/glob
tools pay no startup cost for code-intel.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "BugReport",
    "Finding",
    "ReadinessEngine",
    "ReadinessReport",
    "RepoMapResult",
    "format_repo_map",
    "pagerank",
    "rank_repo_files",
    "scan_diff",
    "scan_text",
]

# Lazy-load map: attribute name -> (module_path, attribute_name)
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "BugReport": ("attocode.code_intel.bug_finder", "BugReport"),
    "Finding": ("attocode.code_intel.bug_finder", "Finding"),
    "scan_diff": ("attocode.code_intel.bug_finder", "scan_diff"),
    "scan_text": ("attocode.code_intel.bug_finder", "scan_text"),
    "ReadinessEngine": ("attocode.code_intel.readiness", "ReadinessEngine"),
    "ReadinessReport": ("attocode.code_intel.readiness", "ReadinessReport"),
    "RepoMapResult": ("attocode.code_intel.repo_ranker", "RepoMapResult"),
    "format_repo_map": ("attocode.code_intel.repo_ranker", "format_repo_map"),
    "pagerank": ("attocode.code_intel.repo_ranker", "pagerank"),
    "rank_repo_files": ("attocode.code_intel.repo_ranker", "rank_repo_files"),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_IMPORTS:
        module_path, attr = _LAZY_IMPORTS[name]
        mod = importlib.import_module(module_path)
        value = getattr(mod, attr)
        # Cache on the module so subsequent accesses are fast
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
