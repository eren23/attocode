"""Diff utilities using Python's difflib."""

from __future__ import annotations

import difflib


def unified_diff(
    old: str,
    new: str,
    *,
    old_name: str = "before",
    new_name: str = "after",
    context_lines: int = 3,
) -> str:
    """Generate a unified diff between two strings.

    Returns the diff as a string, or empty string if no changes.
    """
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=old_name,
        tofile=new_name,
        n=context_lines,
    )
    return "".join(diff)


def context_diff(
    old: str,
    new: str,
    *,
    old_name: str = "before",
    new_name: str = "after",
    context_lines: int = 3,
) -> str:
    """Generate a context diff between two strings."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)

    diff = difflib.context_diff(
        old_lines,
        new_lines,
        fromfile=old_name,
        tofile=new_name,
        n=context_lines,
    )
    return "".join(diff)


def count_changes(old: str, new: str) -> tuple[int, int, int]:
    """Count lines added, removed, and modified.

    Returns (added, removed, modified).
    """
    old_lines = old.splitlines()
    new_lines = new.splitlines()

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    added = 0
    removed = 0
    modified = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            modified += max(i2 - i1, j2 - j1)
        elif tag == "insert":
            added += j2 - j1
        elif tag == "delete":
            removed += i2 - i1

    return added, removed, modified


def similarity_ratio(old: str, new: str) -> float:
    """Calculate similarity ratio between two strings (0.0 to 1.0)."""
    if not old and not new:
        return 1.0
    return difflib.SequenceMatcher(None, old, new).ratio()
