"""Tests for the diff engine — unified diff from stored content."""

from __future__ import annotations

from attocode.code_intel.storage.diff_engine import (
    DiffHunk,
    DiffLine,
    PatchEntry,
    _compute_hunks,
)


def test_compute_hunks_modification():
    """Compute hunks for a modified file."""
    old = "line1\nline2\nline3\n"
    new = "line1\nmodified\nline3\n"
    hunks = _compute_hunks(old, new, "test.py")

    assert len(hunks) == 1
    hunk = hunks[0]
    assert hunk.old_start == 1
    assert hunk.new_start == 1

    additions = [ln for ln in hunk.lines if ln.origin == "+"]
    deletions = [ln for ln in hunk.lines if ln.origin == "-"]
    assert len(additions) == 1
    assert len(deletions) == 1
    assert "modified" in additions[0].content
    assert "line2" in deletions[0].content


def test_compute_hunks_addition():
    """Compute hunks for added content."""
    old = "line1\nline2\n"
    new = "line1\nline2\nnew_line\n"
    hunks = _compute_hunks(old, new, "test.py")

    assert len(hunks) >= 1
    all_additions = [
        ln for h in hunks for ln in h.lines if ln.origin == "+"
    ]
    assert any("new_line" in ln.content for ln in all_additions)


def test_compute_hunks_deletion():
    """Compute hunks for deleted content."""
    old = "line1\nline2\nline3\n"
    new = "line1\nline3\n"
    hunks = _compute_hunks(old, new, "test.py")

    assert len(hunks) >= 1
    all_deletions = [
        ln for h in hunks for ln in h.lines if ln.origin == "-"
    ]
    assert any("line2" in ln.content for ln in all_deletions)


def test_compute_hunks_empty_diff():
    """No hunks when content is identical."""
    content = "line1\nline2\nline3\n"
    hunks = _compute_hunks(content, content, "test.py")
    assert len(hunks) == 0


def test_compute_hunks_added_file():
    """Compute hunks for a completely new file."""
    hunks = _compute_hunks("", "new content\nline 2\n", "new.py")
    assert len(hunks) >= 1
    all_additions = [
        ln for h in hunks for ln in h.lines if ln.origin == "+"
    ]
    assert len(all_additions) >= 2


def test_compute_hunks_deleted_file():
    """Compute hunks for a completely deleted file."""
    hunks = _compute_hunks("old content\nline 2\n", "", "deleted.py")
    assert len(hunks) >= 1
    all_deletions = [
        ln for h in hunks for ln in h.lines if ln.origin == "-"
    ]
    assert len(all_deletions) >= 2


def test_compute_hunks_line_numbers():
    """Line numbers are correctly assigned."""
    old = "a\nb\nc\n"
    new = "a\nx\nc\n"
    hunks = _compute_hunks(old, new, "test.py")

    for hunk in hunks:
        for ln in hunk.lines:
            if ln.origin == "-":
                assert ln.old_lineno is not None
                assert ln.new_lineno is None
            elif ln.origin == "+":
                assert ln.old_lineno is None
                assert ln.new_lineno is not None
            else:
                assert ln.old_lineno is not None
                assert ln.new_lineno is not None
