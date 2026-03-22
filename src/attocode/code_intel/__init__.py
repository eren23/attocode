"""Attocode Code Intelligence MCP Server.

Exposes AST parsing, cross-references, dependency graphs, impact analysis,
and repo maps as MCP tools for Claude Code, Cursor, Windsurf, etc.
"""

from attocode.code_intel.bug_finder import BugReport, Finding, scan_diff, scan_text
from attocode.code_intel.repo_ranker import (
    RepoMapResult,
    format_repo_map,
    pagerank,
    rank_repo_files,
)

__all__ = [
    "BugReport",
    "Finding",
    "RepoMapResult",
    "format_repo_map",
    "pagerank",
    "rank_repo_files",
    "scan_diff",
    "scan_text",
]
