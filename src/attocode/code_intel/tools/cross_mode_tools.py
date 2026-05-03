"""Cross-mode search MCP tools.

When one search mode finds nothing, suggests results from the other mode.
- File search → grep suggestions if no files match
- Grep search → file suggestions if no content matches
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from attocode.code_intel._shared import _get_project_dir, mcp
from attocode.code_intel.tools.pin_tools import pin_stamped

if TYPE_CHECKING:
    from attocode.integrations.context.cross_mode import CrossModeSearcher


def _get_cross_mode_searcher() -> CrossModeSearcher:
    """Get cross-mode searcher instance."""
    from attocode.integrations.context.cross_mode import CrossModeSearcher

    project_dir = _get_project_dir()
    return CrossModeSearcher(project_dir=project_dir)


@mcp.tool()
def suggest_when_file_search_finds_nothing(
    query: str,
    max_suggestions: int = 10,
) -> str:
    """Suggest grep results when file search finds no matching files.

    Use this when you searched for a file but got no results.
    It will search file contents for your query.

    Args:
        query: The file search query that returned no results.
        max_suggestions: Maximum suggestions to return (default 10).

    Returns:
        Suggested grep matches with line numbers.
    """
    searcher = _get_cross_mode_searcher()
    suggestions = searcher.suggest_content_matches(query, max_suggestions)

    if not suggestions:
        return (
            f"No grep suggestions for '{query}' either.\n"
            "The query might not appear in any file content."
        )

    lines = [
        f"File search found nothing for '{query}'.",
        f"But these files contain that text ({len(suggestions)} matches):\n",
    ]

    current_file = None
    for s in suggestions:
        if s.file_path != current_file:
            lines.append(f"\n{s.file_path}:")
            current_file = s.file_path
        if s.line_number is not None:
            lines.append(f"  {s.line_number}: {s.matched_text[:100]}")

    return "\n".join(lines)


@mcp.tool()
def suggest_when_grep_finds_nothing(
    query: str,
    max_suggestions: int = 10,
) -> str:
    """Suggest files when grep finds no matching content.

    Use this when you grepped for text but got no results.
    It will suggest files with similar names to your query.

    Args:
        query: The grep query that returned no results.
        max_suggestions: Maximum suggestions to return (default 10).

    Returns:
        Suggested files with matching names.
    """
    searcher = _get_cross_mode_searcher()
    suggestions = searcher.suggest_filename_matches(query, max_suggestions)

    if not suggestions:
        return (
            f"No file suggestions for '{query}' either.\n"
            "Try a different search term."
        )

    lines = [
        f"Grep found nothing for '{query}'.",
        f"But these files have similar names ({len(suggestions)} suggestions):\n",
    ]

    for i, s in enumerate(suggestions, 1):
        lines.append(f"{i}. [{s.score:.0f}] {s.file_path}")

    return "\n".join(lines)


@mcp.tool()
@pin_stamped
def cross_mode_search(
    query: str,
    prefer_mode: str = "file",
    max_suggestions: int = 10,
) -> str:
    """Try both file search and grep, return results from both.

    Useful when you're not sure which approach will work.
    Shows results from both modes if one finds nothing.

    Args:
        query: The search query.
        prefer_mode: Which mode to try first - "file" or "grep".
        max_suggestions: Maximum suggestions per mode.

    Returns:
        Results from both modes with cross-mode suggestions.
    """
    searcher = _get_cross_mode_searcher()

    if prefer_mode == "file":
        # File-name search preferred — fall back to content search
        content_suggestions = searcher.suggest_content_matches(query, max_suggestions)
        filename_suggestions = searcher.suggest_filename_matches(query, max_suggestions)

        if content_suggestions:
            lines = [
                f"Content matches for '{query}' ({len(content_suggestions)} matches):\n",
            ]
            for s in content_suggestions[:5]:
                lines.append(f"  {s.file_path}:{s.line_number}: {s.matched_text[:60]}")
            if len(content_suggestions) > 5:
                lines.append(f"  ... and {len(content_suggestions) - 5} more")
        elif filename_suggestions:
            lines = [
                f"No content matches for '{query}'.",
                f"But these files have similar names ({len(filename_suggestions)} suggestions):\n",
            ]
            for s in filename_suggestions:
                lines.append(f"  [{s.score:.0f}] {s.file_path}")
        else:
            return f"No results found for '{query}' in either mode."
    else:
        # Grep/content search preferred — fall back to filename search
        filename_suggestions = searcher.suggest_filename_matches(query, max_suggestions)
        content_suggestions = searcher.suggest_content_matches(query, max_suggestions)

        if filename_suggestions:
            lines = [
                f"Filename matches for '{query}' ({len(filename_suggestions)} suggestions):\n",
            ]
            for s in filename_suggestions:
                lines.append(f"  [{s.score:.0f}] {s.file_path}")
        elif content_suggestions:
            lines = [
                f"No filename matches for '{query}'.",
                f"But these files contain that text ({len(content_suggestions)} matches):\n",
            ]
            for s in content_suggestions[:5]:
                lines.append(f"  {s.file_path}:{s.line_number}: {s.matched_text[:60]}")
            if len(content_suggestions) > 5:
                lines.append(f"  ... and {len(content_suggestions) - 5} more")
        else:
            return f"No results found for '{query}' in either mode."

    return "\n".join(lines)
