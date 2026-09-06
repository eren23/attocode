"""Query constraints parser and processor.

Supports fff-style query constraints:
- git:modified, git:staged, git:deleted, git:renamed, git:untracked, git:ignored
- !pattern (negation)
- test/ (path filter)
- ./{glob} (glob patterns)
- Extension filters: *.py, *.{rs,lua}

Based on fff.nvim's constraints.rs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# ---------------------------------------------------------------------------
# Constraint types
# ---------------------------------------------------------------------------


class GitStatus(Enum):
    """Git status filter types."""
    MODIFIED = "modified"
    STAGED = "staged"
    DELETED = "deleted"
    RENAMED = "renamed"
    UNTRACKED = "untracked"
    IGNORED = "ignored"


@dataclass
class Constraint:
    """A parsed constraint."""
    type: str  # "git", "path", "negation", "glob", "extension"
    value: str
    negated: bool = False


@dataclass
class ParsedQuery:
    """A query with extracted constraints."""
    query: str  # The remaining search pattern after constraints
    constraints: list[Constraint]


# ---------------------------------------------------------------------------
# Constraint parsing
# ---------------------------------------------------------------------------


def parse_query_constraints(query: str) -> ParsedQuery:
    """Parse a query with fff-style constraints.

    Args:
        query: The query string with possible constraints.

    Returns:
        ParsedQuery with the main query and list of constraints.
    """
    constraints: list[Constraint] = []
    remaining_parts: list[str] = []

    parts = query.split()

    for part in parts:
        if not part:
            continue

        # Check for git: constraint
        if part.startswith("git:"):
            status_str = part[4:]  # Remove "git:"
            if status_str.startswith("!"):
                negated = True
                status_str = status_str[1:]
            else:
                negated = False

            try:
                status = GitStatus(status_str)
                constraints.append(Constraint(
                    type="git",
                    value=status.value,
                    negated=negated,
                ))
            except ValueError:
                # Not a valid git status, treat as regular query
                remaining_parts.append(part)
            continue

        # Check for negation: !something
        if part.startswith("!"):
            negated = True
            part = part[1:]
            if part:
                constraints.append(Constraint(
                    type="negation",
                    value=part.lower(),
                    negated=negated,
                ))
            continue

        # Check for path filter: test/
        if "/" in part and not part.startswith("./"):
            # This looks like a path filter
            constraints.append(Constraint(
                type="path",
                value=part.rstrip("/"),
                negated=False,
            ))
            continue

        # Check for glob pattern: ./**/*.py
        if part.startswith("./") or "*" in part or "{" in part:
            constraints.append(Constraint(
                type="glob",
                value=part,
                negated=False,
            ))
            continue

        # Check for extension filter: *.py or *.{rs,lua}
        if part.startswith("*."):
            constraints.append(Constraint(
                type="extension",
                value=part[1:],  # Remove leading *
                negated=False,
            ))
            continue

        # Regular query part
        remaining_parts.append(part)

    return ParsedQuery(
        query=" ".join(remaining_parts),
        constraints=constraints,
    )


# ---------------------------------------------------------------------------
# Constraint matching
# ---------------------------------------------------------------------------


def matches_constraints(
    file_path: str,
    constraints: list[Constraint],
    git_status: GitStatus | None = None,
) -> bool:
    """Check if a file matches the given constraints.

    Args:
        file_path: Path to check.
        constraints: List of constraints to match.
        git_status: Current git status of the file (if known).

    Returns:
        True if all constraints pass, False otherwise.
    """
    path_obj = Path(file_path)

    for constraint in constraints:
        if constraint.type == "git":
            if constraint.negated:
                if git_status is not None and git_status.value == constraint.value:
                    return False
            else:
                if git_status is None or git_status.value != constraint.value:
                    return False

        elif constraint.type == "negation":
            # Check if file path contains the negated pattern
            if constraint.value in file_path.lower():
                return False

        elif constraint.type == "path":
            path_filter = constraint.value
            if constraint.negated:
                # Negated path filter - file should NOT be in this path
                if path_filter in file_path:
                    return False
            else:
                # Positive path filter - file MUST be in this path
                if path_filter not in file_path:
                    return False

        elif constraint.type == "glob":
            # Simple glob matching
            if not _matches_glob(file_path, constraint.value):
                return False

        elif constraint.type == "extension":
            ext = constraint.value
            if not ext.startswith("."):
                ext = "." + ext
            if path_obj.suffix != ext:
                return False

    return True


def _matches_glob(path: str, pattern: str) -> bool:
    """Simple glob matching for path patterns.

    Supports:
    - **/*.py (recursive)
    - *.py (single segment)
    - *.{rs,lua} (brace expansion)

    Args:
        path: Path to check.
        pattern: Glob pattern.

    Returns:
        True if path matches pattern.
    """
    import fnmatch

    # Convert fff-style glob to fnmatch pattern
    # ./**/*.py -> **/*.py -> match recursively
    # *.py -> *.py -> match in single directory

    if pattern.startswith("./"):
        pattern = pattern[2:]

    # Handle brace expansion *.{rs,lua}
    if "{" in pattern and "}" in pattern:
        # Try each alternative
        brace_match = re.match(r'^(.*)\{([^}]+)\}(.*)$', pattern)
        if brace_match:
            prefix, alternatives, suffix = brace_match.groups()
            for alt in alternatives.split(","):
                alt_pattern = f"{prefix}{alt}{suffix}"
                if _matches_glob(path, alt_pattern):
                    return True
            return False

    # Handle ** for recursive matching
    if "**" in pattern:
        # Convert **/* to recursive fnmatch
        pattern = pattern.replace("**", "*")
        # But ** matches any path, so we need to check if path ends with the pattern
        pattern = pattern.lstrip("*/")

        if pattern.startswith("*"):
            # Ends with something - check if path contains it
            pattern = pattern.lstrip("*")
            return pattern in path

        return fnmatch.fnmatch(path, f"*/{pattern}") or fnmatch.fnmatch(path, pattern)

    return fnmatch.fnmatch(Path(path).name, pattern)


# ---------------------------------------------------------------------------
# Constraint application to search results
# ---------------------------------------------------------------------------


def filter_files_by_constraints(
    files: list[str],
    constraints: list[Constraint],
    git_statuses: dict[str, GitStatus] | None = None,
) -> list[str]:
    """Filter a list of files by constraints.

    Args:
        files: List of file paths to filter.
        constraints: Constraints to apply.
        git_statuses: Dict mapping file path to git status.

    Returns:
        Filtered list of files.
    """
    if not constraints:
        return files

    git_statuses = git_statuses or {}
    filtered: list[str] = []

    for file_path in files:
        git_status = git_statuses.get(file_path)
        if matches_constraints(file_path, constraints, git_status):
            filtered.append(file_path)

    return filtered


# ---------------------------------------------------------------------------
# High-level API
# ---------------------------------------------------------------------------


class QueryConstraintProcessor:
    """Process queries with constraints."""

    def __init__(self, project_dir: str) -> None:
        self.project_dir = project_dir

    def parse(self, query: str) -> ParsedQuery:
        """Parse a query with constraints."""
        return parse_query_constraints(query)

    def filter_files(
        self,
        files: list[str],
        constraints: list[Constraint],
        git_statuses: dict[str, GitStatus] | None = None,
    ) -> list[str]:
        """Filter files by constraints."""
        return filter_files_by_constraints(files, constraints, git_statuses)

    def get_git_status(self, file_path: str) -> GitStatus | None:
        """Get the git status for a file.

        Args:
            file_path: Path to check.

        Returns:
            GitStatus if file is tracked and status can be determined, None otherwise.
        """
        import subprocess

        try:
            result = subprocess.run(
                ["git", "status", "--porcelain", "--", file_path],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if not result.stdout.strip():
                return None

            status_char = result.stdout[0] if result.stdout else ""

            # Status codes:
            # M = modified
            # A = staged (added)
            # D = deleted
            # R = renamed
            # ?? = untracked
            # !! = ignored

            status_map = {
                "M": GitStatus.MODIFIED,
                "A": GitStatus.STAGED,
                "D": GitStatus.DELETED,
                "R": GitStatus.RENAMED,
                "?": GitStatus.UNTRACKED,
                "!": GitStatus.IGNORED,
            }

            return status_map.get(status_char)

        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return None
