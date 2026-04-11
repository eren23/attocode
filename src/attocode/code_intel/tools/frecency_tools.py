"""Frecency MCP tools for tracking and querying file access patterns.

Exposes frecency tracking to AI agents so they can learn which files
are commonly accessed and boost their relevance in search results.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

from attocode.code_intel._shared import _get_frecency_tracker, _get_project_dir, mcp
from attocode.code_intel.tools.pin_tools import pin_stamped


def _get_git_status(file_path: str) -> tuple[bool, float | None]:
    """Check if a file has uncommitted changes and get modification time.

    Returns:
        (is_modified, modified_timestamp or None)
    """
    project_dir = _get_project_dir()

    try:
        # Get git status for the specific file
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", file_path],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )

        is_modified = bool(result.stdout.strip())

        # Get modification time
        abs_path = Path(project_dir) / file_path
        mtime = abs_path.stat().st_mtime if abs_path.exists() else None

        return is_modified, mtime

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False, None


@mcp.tool()
def track_file_access(path: str) -> str:
    """Track that a file was accessed (opened/viewed).

    Call this whenever an agent opens or reads a file. This builds up
    access patterns that improve file search relevance over time.

    Args:
        path: Path to the file that was accessed (relative to project root
              or absolute).

    Returns:
        Confirmation message with the file that was tracked.
    """
    tracker = _get_frecency_tracker()

    # Resolve to absolute path if needed
    project_dir = _get_project_dir()
    if os.path.isabs(path):
        try:
            rel_path = os.path.relpath(path, project_dir)
        except ValueError:
            rel_path = path
    else:
        rel_path = path

    tracker.track_access(rel_path)

    return f"Tracked access to: {rel_path}"


@mcp.tool()
def get_file_frecency(path: str, ai_mode: bool = True) -> str:
    """Get the frecency score for a file.

    Frecency combines how often and how recently a file was accessed.
    Higher scores indicate more frequently/recently accessed files.

    Args:
        path: Path to the file (relative to project root or absolute).
        ai_mode: Use AI mode decay (faster, 3-day half-life vs 10-day).

    Returns:
        Frecency score and metadata for the file.
    """
    tracker = _get_frecency_tracker()

    # Resolve path
    project_dir = _get_project_dir()
    if os.path.isabs(path):
        try:
            rel_path = os.path.relpath(path, project_dir)
        except ValueError:
            rel_path = path
    else:
        rel_path = path

    # Get git status for modification bonus
    is_modified, mtime = _get_git_status(rel_path)

    result = tracker.get_score(
        rel_path,
        modified_time=mtime,
        is_modified_git=is_modified,
        ai_mode=ai_mode,
    )

    # Format output
    mode_str = "AI" if result.is_ai_mode else "Human"
    last_access_str = "never"
    if result.last_access is not None:
        dt = datetime.fromtimestamp(result.last_access)
        last_access_str = dt.strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"Frecency score for: {rel_path}",
        f"Score: {result.score}",
        f"Access count: {result.accesses}",
        f"Last access: {last_access_str}",
        f"Mode: {mode_str}",
    ]

    if is_modified:
        lines.append("(Git modified bonus applied)")

    return "\n".join(lines)


@mcp.tool()
@pin_stamped
def get_frecency_leaderboard(top_n: int = 20, ai_mode: bool = True) -> str:
    """Get the top N most frequently accessed files.

    Args:
        top_n: Number of top files to return (default 20).
        ai_mode: Use AI mode decay (faster, 3-day half-life vs 10-day).

    Returns:
        Leaderboard of most accessed files.
    """
    tracker = _get_frecency_tracker()
    leaderboard = tracker.get_leaderboard(top_n=top_n, ai_mode=ai_mode)

    if not leaderboard:
        stats = tracker.get_stats()
        return (
            f"No files with positive frecency scores.\n"
            f"Database has {stats['entries']} tracked files.\n"
            f"Files need recent accesses to appear on the leaderboard."
        )

    mode_str = "AI (3-day decay)" if ai_mode else "Human (10-day decay)"
    lines = [
        f"Frecency Leaderboard (top {top_n}, {mode_str})",
        "=" * 50,
    ]

    for rank, (path, result) in enumerate(leaderboard, 1):
        last_str = "never"
        if result.last_access is not None:
            dt = datetime.fromtimestamp(result.last_access)
            last_str = dt.strftime("%Y-%m-%d %H:%M")
        lines.append(
            f"{rank:3d}. [{result.score:4d}] {path}  "
            f"({result.accesses} accesses, last: {last_str})"
        )

    return "\n".join(lines)


@mcp.tool()
def clear_frecency(path: str | None = None) -> str:
    """Clear frecency data.

    Args:
        path: Optional specific file path to clear. If not provided,
              all frecency data is cleared.

    Returns:
        Confirmation message.
    """
    tracker = _get_frecency_tracker()

    if path is None:
        tracker.clear()
        return "All frecency data cleared."
    else:
        count = tracker.clear(path)
        if count > 0:
            return f"Cleared frecency data for: {path}"
        else:
            return f"No frecency data found for: {path}"


@mcp.tool()
def get_frecency_stats() -> str:
    """Get overall frecency database statistics.

    Returns:
        Statistics about the frecency database.
    """
    tracker = _get_frecency_tracker()
    stats = tracker.get_stats()

    lines = [
        "Frecency Statistics",
        "=" * 40,
        f"Tracked files: {stats['entries']}",
        f"Mode: {'AI (3-day decay)' if stats['ai_mode'] else 'Human (10-day decay)'}",
        f"Database path: {stats.get('db_path', 'unknown')}",
    ]

    return "\n".join(lines)
