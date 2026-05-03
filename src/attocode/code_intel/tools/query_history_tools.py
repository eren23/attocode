"""Query history MCP tools for tracking search-result selections.

Tracks which files are selected after which queries, enabling
combo boosting to prioritize commonly co-occurring results.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from attocode.code_intel._shared import _get_project_dir, mcp
from attocode.code_intel.tools.pin_tools import pin_stamped

if TYPE_CHECKING:
    from attocode.integrations.context.query_history import QueryHistoryTracker


def _get_query_tracker() -> QueryHistoryTracker:
    """Get the query history tracker instance."""
    from attocode.integrations.context.query_history import get_query_tracker

    project_dir = _get_project_dir()
    db_path = Path(project_dir) / ".attocode" / "query_history"
    return get_query_tracker(db_path=db_path)


@mcp.tool()
def track_query_result(query: str, file_path: str) -> str:
    """Track that a user selected a file after searching.

    Call this whenever a user searches for something and then opens
    a file from the results. This builds up combo boosting to help
    prioritize commonly selected files for future searches.

    Args:
        query: The search query that led to the selection.
        file_path: The file that was selected/opened.

    Returns:
        Confirmation message.
    """
    tracker = _get_query_tracker()
    tracker.track_selection(query, file_path)

    # Check if this triggers combo boost
    boost = tracker.get_combo_boost(query, file_path)
    if boost > 0:
        return (
            f"Tracked: '{query}' -> {file_path}\n"
            f"Combo boost activated: +{boost:.0f}"
        )
    return f"Tracked: '{query}' -> {file_path}"


@mcp.tool()
def get_query_combo_boost(query: str, file_path: str) -> str:
    """Get the combo boost score for a query+file pair.

    Args:
        query: The search query.
        file_path: The file path to check.

    Returns:
        Combo boost score and metadata.
    """
    tracker = _get_query_tracker()
    boost = tracker.get_combo_boost(query, file_path)

    if boost == 0:
        return (
            f"No combo boost for '{query}' -> {file_path}\n"
            f"(Need 3+ selections to activate boost)"
        )

    return (
        f"Combo boost: +{boost:.0f}\n"
        f"Query: '{query}'\n"
        f"File: {file_path}"
    )


@mcp.tool()
@pin_stamped
def get_top_results_for_query(query: str, limit: int = 10) -> str:
    """Get the top files commonly selected for a query.

    Args:
        query: The search query.
        limit: Maximum number of results to return.

    Returns:
        Top files for this query with selection counts.
    """
    tracker = _get_query_tracker()
    top_files = tracker.get_top_files_for_query(query, limit=limit)

    if not top_files:
        return f"No history for query: '{query}'"

    lines = [
        f"Top results for: '{query}'",
        f"(Based on {limit} historical selections)\n",
    ]

    for i, (file_path, count, combo_score) in enumerate(top_files, 1):
        boost_str = f" (+{combo_score:.0f} boost)" if combo_score > 0 else ""
        lines.append(f"{i}. [{count}x] {file_path}{boost_str}")

    return "\n".join(lines)


@mcp.tool()
def get_query_history_stats() -> str:
    """Get overall query history statistics.

    Returns:
        Statistics about tracked queries and selections.
    """
    tracker = _get_query_tracker()
    stats = tracker.get_stats()

    lines = [
        "Query History Statistics",
        "=" * 40,
        f"Total selections tracked: {stats.total_selections}",
        f"Total query entries: {stats.total_queries}",
        f"Unique queries: {stats.unique_queries}",
        f"Unique files: {stats.unique_files}",
        f"Files with combo boost: {stats.combo_boosts}",
    ]

    return "\n".join(lines)


@mcp.tool()
def clear_query_history(query: str | None = None, file_path: str | None = None) -> str:
    """Clear query history.

    Args:
        query: Optional specific query to clear. If None, clears all.
        file_path: Optional specific file to clear (requires query).

    Returns:
        Confirmation message.
    """
    tracker = _get_query_tracker()

    if query is None:
        tracker.clear()
        return "All query history cleared."

    count = tracker.clear(query, file_path)
    if count > 0:
        if file_path:
            return f"Cleared history for '{query}' -> {file_path}"
        return f"Cleared {count} entries for query: '{query}'"
    return f"No history found for query: '{query}'"
