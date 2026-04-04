"""Fuzzy search MCP tools for typo-resistant text matching.

Uses Smith-Waterman algorithm for local sequence alignment to find
matches even with typos and character swaps.
"""

from __future__ import annotations

from pathlib import Path

from attocode.code_intel._shared import _get_project_dir, mcp


def _get_fuzzy_matcher(pattern: str, case_sensitive: bool = False, min_score: float = 30.0):
    """Create a fuzzy matcher for the given pattern."""
    from attocode.integrations.context.fuzzy import FuzzyMatcher

    return FuzzyMatcher(
        pattern=pattern,
        case_sensitive=case_sensitive,
        min_score=min_score,
    )


@mcp.tool()
def fuzzy_search(
    pattern: str,
    path: str = "",
    max_results: int = 50,
    case_sensitive: bool = False,
    min_score: float = 30.0,
) -> str:
    """Search using fuzzy matching (typo-resistant).

    Unlike regex search which requires exact character matching, fuzzy search
    can find "mtxlk" matching "mutex_lock". Uses the Smith-Waterman
    algorithm for local sequence alignment.

    Best for:
    - Finding files with typos in the name
    - Matching when character order is uncertain
    - Partial matches across word boundaries

    Args:
        pattern: The search pattern (can contain typos).
        path: Subdirectory to search in (relative to project root).
        max_results: Maximum number of results to return.
        case_sensitive: Whether matching is case-sensitive.
        min_score: Minimum match quality score (0-100, default 30).

    Returns:
        Matching lines with their fuzzy scores.
    """
    project_dir = _get_project_dir()
    root = Path(project_dir)
    if path:
        root = root / path
    root = root.resolve()

    if not root.exists():
        return f"Error: Path not found: {root}"

    # Get files to search
    if root.is_file():
        files = [root]
    else:
        files = sorted(root.rglob("*"))
        try:
            from attocode.integrations.utilities.ignore import IgnoreManager

            ignore_mgr = IgnoreManager(root=Path(project_dir))
            files = [
                f
                for f in files
                if f.is_file()
                and not f.name.startswith(".")
                and not ignore_mgr.is_ignored(
                    str(f.relative_to(Path(project_dir)))
                )
            ]
        except (ImportError, ValueError):
            files = [
                f for f in files if f.is_file() and not f.name.startswith(".")
            ]

    matcher = _get_fuzzy_matcher(pattern, case_sensitive, min_score)

    results: list[tuple[str, int, float, str]] = []  # (rel_path, line_num, score, line)

    for file in files:
        if len(results) >= max_results * 3:
            break

        try:
            content = file.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue

        for i, line in enumerate(content.splitlines(), 1):
            if matcher.matches(line):
                score = matcher.get_score(line)
                try:
                    rel = str(file.relative_to(Path(project_dir)))
                except ValueError:
                    rel = str(file)
                results.append((rel, i, score, line.strip()))

                if len(results) >= max_results:
                    break

    if not results:
        return f"No fuzzy matches found for '{pattern}'"

    # Sort by score descending
    results.sort(key=lambda x: x[2], reverse=True)

    # Format output
    lines = [f"Fuzzy search: '{pattern}' ({len(results)} matches)"]
    lines.append(f"Min score: {min_score}, Case sensitive: {case_sensitive}\n")

    for rel_path, line_num, score, line_content in results[:max_results]:
        lines.append(f"{rel_path}:{line_num}: [{score:.1f}] {line_content}")

    if len(results) > max_results:
        lines.append(f"\n... (limited to {max_results} results)")

    return "\n".join(lines)


@mcp.tool()
def fuzzy_filename_search(
    pattern: str,
    path: str = "",
    max_results: int = 20,
) -> str:
    """Find files with fuzzy-matched filenames.

    Useful when you know part of a filename but not the exact spelling.
    For example, "mtxlk" could match "mutex_lock.rs".

    Args:
        pattern: Partial filename to search for.
        path: Subdirectory to search in.
        max_results: Maximum number of results.

    Returns:
        Matching files with their match scores.
    """
    project_dir = _get_project_dir()
    root = Path(project_dir)
    if path:
        root = root / path
    root = root.resolve()

    if not root.exists():
        return f"Error: Path not found: {root}"

    # Get all files
    if root.is_file():
        files = [root]
    else:
        files = sorted(root.rglob("*"))
        try:
            from attocode.integrations.utilities.ignore import IgnoreManager

            ignore_mgr = IgnoreManager(root=Path(project_dir))
            files = [
                f
                for f in files
                if f.is_file()
                and not f.name.startswith(".")
                and not ignore_mgr.is_ignored(
                    str(f.relative_to(Path(project_dir)))
                )
            ]
        except (ImportError, ValueError):
            files = [
                f for f in files if f.is_file() and not f.name.startswith(".")
            ]

    from attocode.integrations.context.fuzzy import fuzzy_match_filename

    scored_files: list[tuple[str, float, str]] = []

    for file in files:
        filename = file.name
        score = fuzzy_match_filename(pattern, filename)
        if score > 30.0:  # Only include reasonable matches
            try:
                rel = str(file.relative_to(Path(project_dir)))
            except ValueError:
                rel = str(file)
            scored_files.append((rel, score, filename))

    if not scored_files:
        return f"No files matching '{pattern}'"

    # Sort by score descending
    scored_files.sort(key=lambda x: x[1], reverse=True)

    # Format output
    lines = [f"Filename fuzzy search: '{pattern}' ({len(scored_files)} matches)\n"]

    for rel_path, score, _filename in scored_files[:max_results]:
        lines.append(f"  [{score:.1f}] {rel_path}")

    if len(scored_files) > max_results:
        lines.append(f"\n... (limited to {max_results} results)")

    return "\n".join(lines)


@mcp.tool()
def fuzzy_score(text: str, pattern: str, case_sensitive: bool = False) -> str:
    """Calculate the fuzzy match score between text and pattern.

    Useful for testing and debugging fuzzy matching behavior.

    Args:
        text: The text to match against.
        pattern: The pattern to search for.
        case_sensitive: Whether matching is case-sensitive.

    Returns:
        The fuzzy match score (0-100) and matched indices.
    """
    from attocode.integrations.context.fuzzy import fuzzy_match

    match = fuzzy_match(pattern, text, case_sensitive=case_sensitive, min_score=0.0)

    if match is None:
        return f"'{pattern}' does not match '{text}' (score below threshold)"

    lines = [
        f"Pattern: '{pattern}'",
        f"Text: '{text}'",
        f"Score: {match.score:.2f}/100",
        f"Matched at indices: {match.matched_indices}",
    ]

    # Show highlighted match
    if match.matched_indices:
        highlighted = list(text)
        for i in match.matched_indices:
            if i < len(highlighted):
                highlighted[i] = f"[{highlighted[i]}]"
        lines.append(f"Highlighted: {''.join(highlighted)}")

    return "\n".join(lines)
