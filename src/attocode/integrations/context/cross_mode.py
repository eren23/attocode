"""Cross-mode search suggestions.

When one search mode returns no results, automatically query the other mode
and suggest those results:
- File search with no results → shows grep/content match suggestions
- Grep with no results → shows file name suggestions

This is a "did you mean" feature for search.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class SearchSuggestion:
    """A suggested result from the alternate search mode."""
    file_path: str
    line_number: int | None  # None for file suggestions
    matched_text: str | None  # The text that matched (for grep suggestions)
    score: float  # Relevance score


@dataclass
class CrossModeResult:
    """Result of a cross-mode search."""
    original_query: str
    original_mode: str  # "file" or "grep"
    suggestions: list[SearchSuggestion]
    mode_used: str  # The mode that provided suggestions


# ---------------------------------------------------------------------------
# Cross-mode search
# ---------------------------------------------------------------------------


def suggest_grep_for_filename_query(
    query: str,
    project_dir: str,
    max_suggestions: int = 10,
) -> list[SearchSuggestion]:
    """When filename search finds nothing, suggest grep matches.

    Args:
        query: The original filename search query.
        project_dir: Project root directory.
        max_suggestions: Maximum suggestions to return.

    Returns:
        List of grep-based suggestions.
    """
    suggestions: list[SearchSuggestion] = []

    # Use simple grep-like search for the query in file contents
    pattern = re.escape(query)
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        # If query is not a valid regex, do literal search
        pattern_literal = query.lower()
        regex = None

    project_path = Path(project_dir)

    # Set up gitignore filtering
    try:
        from attocode.integrations.utilities.ignore import IgnoreManager

        ignore_mgr = IgnoreManager(root=project_path)
    except ImportError:
        ignore_mgr = None

    # Walk files and search for matches
    for file in project_path.rglob("*"):
        if not file.is_file() or file.name.startswith("."):
            continue

        try:
            rel_path = str(file.relative_to(project_path))
        except ValueError:
            rel_path = str(file)

        if ignore_mgr is not None and ignore_mgr.is_ignored(rel_path):
            continue

        # Skip binary and large files
        try:
            if file.stat().st_size > 1_000_000:  # 1MB
                continue
            content = file.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError):
            continue

        # Search line by line
        for i, line in enumerate(content.splitlines(), 1):
            match = regex.search(line) if regex else pattern_literal in line.lower()

            if match:
                suggestions.append(SearchSuggestion(
                    file_path=rel_path,
                    line_number=i,
                    matched_text=line.strip(),
                    score=100.0,
                ))

                if len(suggestions) >= max_suggestions:
                    break

        if len(suggestions) >= max_suggestions:
            break

    return suggestions[:max_suggestions]


def suggest_files_for_grep_query(
    query: str,
    project_dir: str,
    max_suggestions: int = 10,
) -> list[SearchSuggestion]:
    """When grep finds nothing, suggest files with matching names.

    Args:
        query: The original grep search query.
        project_dir: Project root directory.
        max_suggestions: Maximum suggestions to return.

    Returns:
        List of filename-based suggestions.
    """
    suggestions: list[SearchSuggestion] = []

    # Parse query - could be a regex or plain text
    # Extract meaningful parts from the query
    # Remove regex special chars for literal matching
    literal_query = re.sub(r'[\^\$\.\|\(\)\[\]\+\*\?\\]', '', query)
    literal_query = literal_query.strip()

    if not literal_query:
        return suggestions

    project_path = Path(project_dir)

    # Set up gitignore filtering
    try:
        from attocode.integrations.utilities.ignore import IgnoreManager

        ignore_mgr = IgnoreManager(root=project_path)
    except ImportError:
        ignore_mgr = None

    # Walk files and look for name matches
    for file in project_path.rglob("*"):
        if not file.is_file() or file.name.startswith("."):
            continue

        if ignore_mgr is not None:
            try:
                rel = str(file.relative_to(project_path))
            except ValueError:
                continue
            if ignore_mgr.is_ignored(rel):
                continue

        name = file.name.lower()
        name_without_ext = file.stem.lower()

        # Check if query matches filename
        score = 0.0
        if literal_query in name:
            score = 50.0 + (len(literal_query) / len(name)) * 50.0
        elif literal_query in name_without_ext:
            score = 30.0 + (len(literal_query) / len(name_without_ext)) * 40.0
        else:
            # Fuzzy-ish matching: check if all chars appear in order
            if _chars_in_order(literal_query, name_without_ext):
                score = 20.0

        if score > 20.0:
            try:
                rel_path = str(file.relative_to(project_path))
            except ValueError:
                rel_path = str(file)

            suggestions.append(SearchSuggestion(
                file_path=rel_path,
                line_number=None,
                matched_text=file.name,
                score=score,
            ))

    # Sort by score descending
    suggestions.sort(key=lambda s: s.score, reverse=True)
    return suggestions[:max_suggestions]


def _chars_in_order(pattern: str, text: str) -> bool:
    """Check if all chars in pattern appear in text in order.

    Args:
        pattern: Characters to find.
        text: Text to search in.

    Returns:
        True if all pattern chars found in order.
    """
    pi = 0
    for c in text:
        if pi >= len(pattern):
            break
        if c == pattern[pi]:
            pi += 1
    return pi >= len(pattern)


# ---------------------------------------------------------------------------
# Unified cross-mode search
# ---------------------------------------------------------------------------


class CrossModeSearcher:
    """Provides cross-mode search suggestions."""

    def __init__(self, project_dir: str) -> None:
        self.project_dir = project_dir

    def suggest_content_matches(
        self,
        query: str,
        max_suggestions: int = 10,
    ) -> list[SearchSuggestion]:
        """Suggest content/grep matches when file-name search fails.

        Args:
            query: The file search query.
            max_suggestions: Maximum suggestions.

        Returns:
            Content-based suggestions (grep results).
        """
        return suggest_grep_for_filename_query(
            query=query,
            project_dir=self.project_dir,
            max_suggestions=max_suggestions,
        )

    def suggest_filename_matches(
        self,
        query: str,
        max_suggestions: int = 10,
    ) -> list[SearchSuggestion]:
        """Suggest filename matches when grep/content search fails.

        Args:
            query: The grep query.
            max_suggestions: Maximum suggestions.

        Returns:
            Filename-based suggestions.
        """
        return suggest_files_for_grep_query(
            query=query,
            project_dir=self.project_dir,
            max_suggestions=max_suggestions,
        )
