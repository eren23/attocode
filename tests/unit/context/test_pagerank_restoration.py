"""Tests for CodebaseContextManager.get_top_files_by_importance().

Verifies that the PageRank-boosted file restoration method correctly
ranks, limits, budgets, and excludes files.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from attocode.integrations.context.codebase_context import (
    CodebaseContextManager,
    FileInfo,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(files: list[FileInfo] | None = None) -> CodebaseContextManager:
    """Build a manager with pre-loaded files and no staleness refresh."""
    mgr = CodebaseContextManager(root_dir="/tmp/test-repo")
    if files is not None:
        mgr._files = files
    # Prevent _ensure_fresh from triggering discover_files
    mgr._last_refresh_time = float("inf")
    return mgr


def _fi(
    rel_path: str,
    importance: float = 0.5,
    size: int = 100,
) -> FileInfo:
    """Shorthand for creating a FileInfo."""
    return FileInfo(
        path=f"/tmp/test-repo/{rel_path}",
        relative_path=rel_path,
        size=size,
        importance=importance,
    )


# ---------------------------------------------------------------------------
# Test 7a: returns files ranked by importance
# ---------------------------------------------------------------------------


def test_returns_ranked_files():
    """Files should be returned in order of their importance scores."""
    files = [
        _fi("core.py", importance=0.9, size=100),
        _fi("utils.py", importance=0.7, size=100),
        _fi("tests.py", importance=0.3, size=100),
    ]
    mgr = _make_manager(files)

    result = mgr.get_top_files_by_importance(max_files=10, max_tokens=999_999)

    assert len(result) == 3
    # Result should follow the order of _files (already sorted by importance desc)
    assert result[0] == ("core.py", 0.9)
    assert result[1] == ("utils.py", 0.7)
    assert result[2] == ("tests.py", 0.3)


# ---------------------------------------------------------------------------
# Test 7b: respects max_files
# ---------------------------------------------------------------------------


def test_respects_max_files():
    """max_files=2 should limit the returned list to exactly 2 items."""
    files = [
        _fi("a.py", importance=0.9, size=100),
        _fi("b.py", importance=0.8, size=100),
        _fi("c.py", importance=0.7, size=100),
    ]
    mgr = _make_manager(files)

    result = mgr.get_top_files_by_importance(max_files=2, max_tokens=999_999)

    assert len(result) == 2
    assert result[0][0] == "a.py"
    assert result[1][0] == "b.py"


# ---------------------------------------------------------------------------
# Test 7c: respects token budget
# ---------------------------------------------------------------------------


def test_respects_token_budget():
    """Files that push total estimated tokens over budget should be skipped."""
    # Each file is 3500 bytes -> ~1000 tokens (3500 / 3.5)
    files = [
        _fi("big1.py", importance=0.9, size=3500),
        _fi("big2.py", importance=0.8, size=3500),
        _fi("small.py", importance=0.7, size=350),  # ~100 tokens
    ]
    mgr = _make_manager(files)

    # Budget allows ~1500 tokens: first file (1000 tokens) fits,
    # second file (1000 tokens) exceeds budget -> skip it,
    # third file (100 tokens) fits.
    result = mgr.get_top_files_by_importance(max_files=10, max_tokens=1500)

    paths = [r[0] for r in result]
    assert "big1.py" in paths
    assert "big2.py" not in paths  # too big once big1 is included
    assert "small.py" in paths  # small enough to fit remaining budget


# ---------------------------------------------------------------------------
# Test 7d: exclude_patterns work
# ---------------------------------------------------------------------------


def test_exclude_patterns_work():
    """Glob exclusion patterns should filter out matching files."""
    files = [
        _fi("src/core.py", importance=0.9, size=100),
        _fi("tests/test_core.py", importance=0.85, size=100),
        _fi("node_modules/dep.js", importance=0.8, size=100),
    ]
    mgr = _make_manager(files)

    result = mgr.get_top_files_by_importance(
        max_files=10,
        max_tokens=999_999,
        exclude_patterns=["tests/*", "node_modules/*"],
    )

    paths = [r[0] for r in result]
    assert "src/core.py" in paths
    assert "tests/test_core.py" not in paths
    assert "node_modules/dep.js" not in paths


# ---------------------------------------------------------------------------
# Test 7e: empty _files returns []
# ---------------------------------------------------------------------------


def test_empty_when_no_files():
    """An empty _files list should produce an empty result."""
    mgr = _make_manager(files=[])

    result = mgr.get_top_files_by_importance()

    assert result == []
