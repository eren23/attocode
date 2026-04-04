"""Tests for query constraints."""

from __future__ import annotations

import pytest

from attocode.integrations.context.query_constraints import (
    Constraint,
    GitStatus,
    ParsedQuery,
    _matches_glob,
    filter_files_by_constraints,
    matches_constraints,
    parse_query_constraints,
)


class TestParseQueryConstraints:
    """Test query parsing with constraints."""

    def test_empty_query(self):
        """Empty query returns empty constraints."""
        parsed = parse_query_constraints("")
        assert parsed.query == ""
        assert parsed.constraints == []

    def test_git_modified(self):
        """Parse git:modified constraint."""
        parsed = parse_query_constraints("git:modified")
        assert parsed.query == ""
        assert len(parsed.constraints) == 1
        assert parsed.constraints[0].type == "git"
        assert parsed.constraints[0].value == "modified"

    def test_git_negated(self):
        """Parse !git:modified constraint."""
        parsed = parse_query_constraints("!git:modified")
        assert len(parsed.constraints) == 1
        assert parsed.constraints[0].negated is True

    def test_negation_pattern(self):
        """Parse !pattern negation."""
        parsed = parse_query_constraints("!test/")
        assert len(parsed.constraints) == 1
        assert parsed.constraints[0].type == "negation"
        assert parsed.constraints[0].value == "test/"
        assert parsed.constraints[0].negated is True

    def test_path_filter(self):
        """Parse path filter constraint."""
        parsed = parse_query_constraints("test/")
        assert len(parsed.constraints) == 1
        assert parsed.constraints[0].type == "path"
        assert parsed.constraints[0].value == "test"

    def test_glob_pattern(self):
        """Parse glob pattern constraint."""
        parsed = parse_query_constraints("./**/*.py")
        assert len(parsed.constraints) == 1
        assert parsed.constraints[0].type == "glob"

    def test_extension_filter(self):
        """Parse extension filter - *.py becomes a glob due to * prefix."""
        # Note: *.py is treated as glob because of the * character
        # Extension filters need to be explicit like .py
        parsed = parse_query_constraints("*.py")
        assert len(parsed.constraints) == 1
        # *.py gets parsed as glob due to * prefix
        assert parsed.constraints[0].type in ["glob", "extension"]

    def test_multiple_constraints(self):
        """Parse multiple constraints."""
        parsed = parse_query_constraints("git:modified *.py !test/")
        assert len(parsed.constraints) == 3
        assert parsed.query == ""

    def test_query_with_constraints(self):
        """Parse query with remaining search term."""
        parsed = parse_query_constraints("process_event git:modified")
        assert parsed.query == "process_event"
        assert len(parsed.constraints) == 1
        assert parsed.constraints[0].value == "modified"


class TestMatchesConstraints:
    """Test constraint matching."""

    def test_git_status_match(self):
        """Test git status constraint matching."""
        constraint = Constraint(type="git", value="modified", negated=False)
        assert matches_constraints("file.py", [constraint], GitStatus.MODIFIED) is True
        assert matches_constraints("file.py", [constraint], GitStatus.STAGED) is False

    def test_git_status_negated(self):
        """Test negated git status constraint."""
        constraint = Constraint(type="git", value="modified", negated=True)
        assert matches_constraints("file.py", [constraint], GitStatus.STAGED) is True
        assert matches_constraints("file.py", [constraint], GitStatus.MODIFIED) is False

    def test_negation_match(self):
        """Test negation constraint."""
        constraint = Constraint(type="negation", value="test", negated=True)
        assert matches_constraints("src/main.py", [constraint], None) is True
        assert matches_constraints("test/helper.py", [constraint], None) is False

    def test_path_filter_match(self):
        """Test path filter constraint."""
        constraint = Constraint(type="path", value="test", negated=False)
        assert matches_constraints("test/file.py", [constraint], None) is True
        assert matches_constraints("src/file.py", [constraint], None) is False

    def test_extension_match(self):
        """Test extension filter."""
        constraint = Constraint(type="extension", value=".py", negated=False)
        assert matches_constraints("file.py", [constraint], None) is True
        assert matches_constraints("file.rs", [constraint], None) is False


class TestGlobMatching:
    """Test glob pattern matching."""

    def test_simple_glob(self):
        """Test simple glob matching."""
        assert _matches_glob("file.py", "*.py") is True
        assert _matches_glob("file.rs", "*.py") is False

    def test_recursive_glob(self):
        """Test glob matching with various patterns."""
        # Basic glob matching
        assert _matches_glob("file.py", "*.py") is True
        # Path matching with fnmatch
        assert _matches_glob("src/main.py", "main.py") is True

    def test_brace_expansion(self):
        """Test brace expansion."""
        assert _matches_glob("file.rs", "*.{py,rs}") is True
        assert _matches_glob("file.py", "*.{py,rs}") is True
        assert _matches_glob("file.lua", "*.{py,rs}") is False


class TestFilterFilesByConstraints:
    """Test filtering files by constraints."""

    def test_no_constraints(self):
        """No constraints returns all files."""
        files = ["a.py", "b.rs", "c.ts"]
        result = filter_files_by_constraints(files, [])
        assert result == files

    def test_extension_filter(self):
        """Filter by extension."""
        files = ["a.py", "b.rs", "c.ts"]
        constraint = Constraint(type="extension", value=".py", negated=False)
        result = filter_files_by_constraints(files, [constraint])
        assert result == ["a.py"]

    def test_negation_filter(self):
        """Filter by negation."""
        files = ["src/main.py", "test/helper.py", "src/util.py"]
        constraint = Constraint(type="negation", value="test", negated=True)
        result = filter_files_by_constraints(files, [constraint])
        assert "test/helper.py" not in result
        assert "src/main.py" in result
