"""Tests for the shared pattern-matching iterator used by both security scanners.

The `iter_pattern_matches` generator in `matcher.py` is the single place where
comment-skip, language filtering, and per-pattern `scan_comments` opt-in are
applied. Both `scanner.py` (filesystem) and `security_scanner_db.py` (DB-backed)
depend on it, so a silent bug here breaks both code paths.
"""

from __future__ import annotations

import re

from attocode.integrations.security.matcher import iter_pattern_matches
from attocode.integrations.security.patterns import (
    Category,
    SecurityPattern,
    Severity,
)


def _make_pattern(
    name: str,
    regex: str,
    *,
    languages: list[str] | None = None,
    scan_comments: bool = False,
) -> SecurityPattern:
    return SecurityPattern(
        name=name,
        pattern=re.compile(regex),
        severity=Severity.HIGH,
        category=Category.ANTI_PATTERN,
        cwe_id="CWE-000",
        message="test",
        recommendation="test",
        languages=languages or [],
        scan_comments=scan_comments,
    )


def test_matches_a_simple_regex_on_single_line():
    content = "hello FINDME world"
    pat = _make_pattern("find", r"FINDME")
    matches = list(iter_pattern_matches(content, [pat], "python"))
    assert len(matches) == 1
    line_no, line, matched = matches[0]
    assert line_no == 1
    assert "FINDME" in line
    assert matched.name == "find"


def test_skips_comment_lines_by_default():
    """Lines starting with # or // are skipped unless scan_comments=True."""
    content = "\n".join([
        "# FINDME in python comment",
        "// FINDME in js comment",
        "x = FINDME  # matches this",
    ])
    pat = _make_pattern("find", r"FINDME")
    matches = list(iter_pattern_matches(content, [pat], "python"))
    # Only line 3 matches — lines 1 and 2 are comments
    assert len(matches) == 1
    assert matches[0][0] == 3


def test_scans_comments_when_pattern_opts_in():
    """scan_comments=True patterns run on comment lines."""
    content = "\n".join([
        "# FINDME in python comment",
        "// FINDME in js comment",
        "x = FINDME  # also matches",
    ])
    pat = _make_pattern("find", r"FINDME", scan_comments=True)
    matches = list(iter_pattern_matches(content, [pat], "python"))
    # All 3 lines match when scan_comments=True
    assert len(matches) == 3
    assert [m[0] for m in matches] == [1, 2, 3]


def test_language_filter_skips_non_matching_languages():
    content = "something FINDME something"
    py_pat = _make_pattern("py_find", r"FINDME", languages=["python"])
    matches_py = list(iter_pattern_matches(content, [py_pat], "python"))
    matches_js = list(iter_pattern_matches(content, [py_pat], "javascript"))
    assert len(matches_py) == 1
    assert len(matches_js) == 0


def test_language_empty_list_means_all_languages():
    content = "FINDME"
    pat = _make_pattern("find", r"FINDME", languages=[])
    assert len(list(iter_pattern_matches(content, [pat], "python"))) == 1
    assert len(list(iter_pattern_matches(content, [pat], "rust"))) == 1
    assert len(list(iter_pattern_matches(content, [pat], ""))) == 1


def test_one_line_can_yield_multiple_pattern_matches():
    content = "FIRST and SECOND on one line"
    p1 = _make_pattern("first", r"FIRST")
    p2 = _make_pattern("second", r"SECOND")
    matches = list(iter_pattern_matches(content, [p1, p2], "python"))
    names = {m[2].name for m in matches}
    assert names == {"first", "second"}
    assert all(m[0] == 1 for m in matches)


def test_empty_content_yields_no_matches():
    pat = _make_pattern("find", r"x")
    assert list(iter_pattern_matches("", [pat], "python")) == []


def test_no_trailing_newline_phantom_line():
    """splitlines() does not create a phantom empty line for trailing newline."""
    content = "line1\nline2\n"
    pat = _make_pattern("any", r".+")
    matches = list(iter_pattern_matches(content, [pat], "python"))
    assert len(matches) == 2
    assert [m[0] for m in matches] == [1, 2]


def test_comment_detection_is_leading_whitespace_tolerant():
    """Indented comments should still be recognised as comments."""
    content = "    # indented comment with FINDME\n    code with FINDME"
    pat = _make_pattern("find", r"FINDME")
    matches = list(iter_pattern_matches(content, [pat], "python"))
    # Only line 2 (code) matches; indented comment is correctly skipped
    assert len(matches) == 1
    assert matches[0][0] == 2
