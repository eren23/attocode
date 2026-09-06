"""Fuzzy string matching using Smith-Waterman algorithm.

Provides typo-resistant search that can find "mtxlk" matching "mutex_lock".
Uses the Smith-Waterman algorithm for local sequence alignment with
affine gaps for optimal matching.

Based on fff.nvim's fuzzy grep implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------

_MATCH_SCORE: int = 2
_MISMATCH_SCORE: int = -1
_GAP_OPEN: int = -3
_GAP_EXTEND: int = -1

# Minimum score threshold (normalized to 0-100)
_MIN_SCORE_THRESHOLD: float = 30.0

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class FuzzyMatch:
    """A fuzzy match result."""
    text: str
    score: float  # 0-100 normalized score
    matched_indices: list[int]  # Positions in text that matched the pattern


@dataclass
class FuzzyResult:
    """Result of a fuzzy search."""
    query: str
    matches: list[FuzzyMatch]
    mode: str = "fuzzy"


# ---------------------------------------------------------------------------
# Smith-Waterman implementation
# ---------------------------------------------------------------------------


def _smith_waterman(
    pattern: str,
    text: str,
    *,
    case_sensitive: bool = True,
) -> tuple[float, list[int]]:
    """Perform Smith-Waterman local alignment.

    Args:
        pattern: The search pattern (query).
        text: The text to search in.
        case_sensitive: Whether to match case-sensitively.

    Returns:
        Tuple of (normalized_score 0-100, list of matched character indices).
    """
    if not pattern or not text:
        return 0.0, []

    p_len = len(pattern)
    t_len = len(text)

    # Convert to uppercase for case-insensitive matching
    if not case_sensitive:
        p_upper = pattern.upper()
        t_upper = text.upper()
    else:
        p_upper = pattern
        t_upper = text

    # Initialize matrices
    # We only need two rows for memory efficiency
    prev_row = [0] * (t_len + 1)
    curr_row = [0] * (t_len + 1)

    # Traceback matrix (only for matched indices)
    # Store: 0=end, 1=diag, 2=up, 3=left
    trace: list[list[int]] = [[0] * (t_len + 1) for _ in range(p_len + 1)]

    max_score = 0
    max_pos = (0, 0)

    # Fill matrices
    for i in range(1, p_len + 1):
        for j in range(1, t_len + 1):
            p_char = p_upper[i - 1]
            t_char = t_upper[j - 1]

            # Match/mismatch score
            if p_char == t_char:
                diag_score = prev_row[j - 1] + _MATCH_SCORE
            else:
                diag_score = prev_row[j - 1] + _MISMATCH_SCORE

            # Gap open (from top)
            up_score = prev_row[j] + _GAP_OPEN if prev_row[j] < 0 else prev_row[j] + _GAP_EXTEND

            # Gap extend (from left)
            left_score = curr_row[j - 1] + _GAP_OPEN if curr_row[j - 1] < 0 else curr_row[j - 1] + _GAP_EXTEND

            # Take maximum (local alignment allows 0)
            scores = [0, diag_score, up_score, left_score]
            curr_row[j] = max(scores)
            trace[i][j] = scores.index(curr_row[j])

            if curr_row[j] > max_score:
                max_score = curr_row[j]
                max_pos = (i, j)

        # Swap rows
        prev_row, curr_row = curr_row, prev_row

    if max_score <= 0:
        return 0.0, []

    # Traceback to find matched indices
    matched_indices: list[int] = []
    i, j = max_pos

    while trace[i][j] != 0 and i > 0 and j > 0:
        if trace[i][j] == 1:  # Diagonal (match/mismatch)
            matched_indices.append(j - 1)
            i -= 1
            j -= 1
        elif trace[i][j] == 2:  # Up (gap in text)
            i -= 1
        else:  # Left (gap in pattern)
            j -= 1

    matched_indices.reverse()

    # Normalize score to 0-100 range
    # Maximum possible score is len(pattern) * MATCH_SCORE
    max_possible = p_len * _MATCH_SCORE
    normalized = (max_score / max_possible) * 100.0 if max_possible > 0 else 0.0

    return normalized, matched_indices


def fuzzy_match(
    pattern: str,
    text: str,
    *,
    case_sensitive: bool = True,
    min_score: float = _MIN_SCORE_THRESHOLD,
) -> FuzzyMatch | None:
    """Check if pattern fuzzy-matches text.

    Args:
        pattern: The pattern to search for.
        text: The text to search in.
        case_sensitive: Whether matching is case-sensitive.
        min_score: Minimum score threshold (0-100).

    Returns:
        FuzzyMatch if score >= min_score, None otherwise.
    """
    score, indices = _smith_waterman(pattern, text, case_sensitive=case_sensitive)

    if score >= min_score:
        return FuzzyMatch(text=text, score=score, matched_indices=indices)
    return None


def fuzzy_match_in_lines(
    pattern: str,
    lines: Sequence[str],
    *,
    case_sensitive: bool = True,
    min_score: float = _MIN_SCORE_THRESHOLD,
    max_results: int = 100,
) -> list[FuzzyMatch]:
    """Find fuzzy matches of pattern in lines.

    Args:
        pattern: The pattern to search for.
        lines: Lines to search in.
        case_sensitive: Whether matching is case-sensitive.
        min_score: Minimum score threshold (0-100).
        max_results: Maximum number of results to return.

    Returns:
        List of FuzzyMatch objects for matching lines.
    """
    results: list[FuzzyMatch] = []

    for line in lines:
        match = fuzzy_match(pattern, line, case_sensitive=case_sensitive, min_score=min_score)
        if match is not None:
            results.append(match)
            if len(results) >= max_results:
                break

    # Sort by score descending
    results.sort(key=lambda m: m.score, reverse=True)
    return results


def fuzzy_search(
    pattern: str,
    text: str,
    *,
    case_sensitive: bool = False,
    min_score: float = _MIN_SCORE_THRESHOLD,
) -> FuzzyResult:
    """Perform fuzzy search on text.

    This splits text into lines and finds fuzzy matches.

    Args:
        pattern: The pattern to search for.
        text: The text to search in.
        case_sensitive: Whether matching is case-sensitive.
        min_score: Minimum score threshold (0-100).

    Returns:
        FuzzyResult with all matching lines.
    """
    lines = text.splitlines()
    matches = fuzzy_match_in_lines(
        pattern,
        lines,
        case_sensitive=case_sensitive,
        min_score=min_score,
    )
    return FuzzyResult(query=pattern, matches=matches)


# ---------------------------------------------------------------------------
# Quick pattern matching for file names
# ---------------------------------------------------------------------------


def fuzzy_match_filename(pattern: str, filename: str) -> float:
    """Check how well a pattern matches a filename.

    Uses a simpler scoring for filename matching.

    Args:
        pattern: The search pattern.
        filename: The filename to match against.

    Returns:
        Score 0-100 indicating match quality.
    """
    pattern_lower = pattern.lower()
    filename_lower = filename.lower()

    # Exact substring match gets high score
    if pattern_lower in filename_lower:
        # Longer patterns that match are better
        return 50.0 + (len(pattern) / len(filename)) * 50.0

    # Fall back to Smith-Waterman for fuzzy matching
    score, _ = _smith_waterman(pattern, filename, case_sensitive=False)
    return score


# ---------------------------------------------------------------------------
# High-level API for search integration
# ---------------------------------------------------------------------------


class FuzzyMatcher:
    """Fuzzy matcher for text search."""

    def __init__(
        self,
        pattern: str,
        *,
        case_sensitive: bool = False,
        min_score: float = _MIN_SCORE_THRESHOLD,
    ) -> None:
        self.pattern = pattern
        self.case_sensitive = case_sensitive
        self.min_score = min_score

    def matches(self, text: str) -> bool:
        """Check if text matches the pattern."""
        match = fuzzy_match(
            self.pattern,
            text,
            case_sensitive=self.case_sensitive,
            min_score=self.min_score,
        )
        return match is not None

    def get_score(self, text: str) -> float:
        """Get the match score for text."""
        match = fuzzy_match(
            self.pattern,
            text,
            case_sensitive=self.case_sensitive,
            min_score=0.0,  # Get score even if below threshold
        )
        return match.score if match else 0.0

    def search(self, lines: Sequence[str]) -> list[FuzzyMatch]:
        """Find all matching lines."""
        return fuzzy_match_in_lines(
            self.pattern,
            lines,
            case_sensitive=self.case_sensitive,
            min_score=self.min_score,
        )
