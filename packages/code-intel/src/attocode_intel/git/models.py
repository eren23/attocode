"""Data models for git operations."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class BranchInfo:
    """Information about a git branch."""

    name: str
    commit: str
    is_default: bool = False
    ahead: int = 0
    behind: int = 0


@dataclass(slots=True)
class DiffEntry:
    """A single file change in a diff."""

    path: str
    status: str  # added|modified|deleted|renamed
    old_path: str | None = None  # For renames
    additions: int = 0
    deletions: int = 0


@dataclass(slots=True)
class TreeEntry:
    """An entry in a git tree (file or directory)."""

    name: str
    path: str
    type: str  # blob|tree
    size: int = 0
    oid: str = ""


@dataclass(slots=True)
class CommitInfo:
    """Information about a git commit."""

    oid: str
    message: str
    author_name: str
    author_email: str
    timestamp: int
    parent_oids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BlameHunk:
    """A contiguous block of lines attributed to one commit."""

    commit_oid: str
    author_name: str
    author_email: str
    timestamp: int
    start_line: int
    end_line: int


@dataclass(slots=True)
class DiffLine:
    """A single line in a diff hunk."""

    origin: str  # '+'/'-'/' '
    content: str
    old_lineno: int | None = None
    new_lineno: int | None = None


@dataclass(slots=True)
class DiffHunk:
    """A hunk within a patch."""

    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    header: str
    lines: list[DiffLine] = field(default_factory=list)


@dataclass(slots=True)
class PatchEntry:
    """A file change with full diff hunks."""

    path: str
    status: str
    old_path: str | None = None
    additions: int = 0
    deletions: int = 0
    hunks: list[DiffHunk] = field(default_factory=list)
