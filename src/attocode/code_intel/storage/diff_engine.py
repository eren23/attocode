"""Unified diff computation from DB-stored content.

Computes line-level diffs between two branch manifests using
BranchOverlay.diff_branches() for file-level changes and
difflib.unified_diff() for line-level hunks.
"""

from __future__ import annotations

import difflib
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DiffLine:
    origin: str  # '+'/'-'/' '
    content: str
    old_lineno: int | None = None
    new_lineno: int | None = None


@dataclass(slots=True)
class DiffHunk:
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    header: str
    lines: list[DiffLine] = field(default_factory=list)


@dataclass(slots=True)
class PatchEntry:
    path: str
    status: str  # added|modified|deleted
    old_path: str | None = None
    additions: int = 0
    deletions: int = 0
    hunks: list[DiffHunk] = field(default_factory=list)


def _compute_hunks(old_text: str, new_text: str, path: str) -> list[DiffHunk]:
    """Compute unified diff hunks between two text contents."""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    diff_lines = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{path}", tofile=f"b/{path}",
        lineterm="",
    ))

    hunks: list[DiffHunk] = []
    current_hunk: DiffHunk | None = None

    for line in diff_lines:
        if line.startswith("@@"):
            # Parse hunk header: @@ -old_start,old_lines +new_start,new_lines @@
            parts = line.split("@@")
            header = line.strip()
            ranges = parts[1].strip().split()
            old_range = ranges[0][1:]  # remove '-'
            new_range = ranges[1][1:]  # remove '+'

            old_start = int(old_range.split(",")[0]) if "," in old_range else int(old_range)
            old_count = int(old_range.split(",")[1]) if "," in old_range else 1
            new_start = int(new_range.split(",")[0]) if "," in new_range else int(new_range)
            new_count = int(new_range.split(",")[1]) if "," in new_range else 1

            current_hunk = DiffHunk(
                old_start=old_start, old_lines=old_count,
                new_start=new_start, new_lines=new_count,
                header=header,
            )
            hunks.append(current_hunk)
        elif current_hunk is not None:
            if line.startswith("---") or line.startswith("+++"):
                continue
            if line.startswith("+"):
                current_hunk.lines.append(DiffLine(
                    origin="+", content=line[1:],
                ))
            elif line.startswith("-"):
                current_hunk.lines.append(DiffLine(
                    origin="-", content=line[1:],
                ))
            else:
                current_hunk.lines.append(DiffLine(
                    origin=" ", content=line[1:] if line.startswith(" ") else line,
                ))

    # Assign line numbers
    for hunk in hunks:
        old_ln = hunk.old_start
        new_ln = hunk.new_start
        for dl in hunk.lines:
            if dl.origin == "-":
                dl.old_lineno = old_ln
                dl.new_lineno = None
                old_ln += 1
            elif dl.origin == "+":
                dl.old_lineno = None
                dl.new_lineno = new_ln
                new_ln += 1
            else:
                dl.old_lineno = old_ln
                dl.new_lineno = new_ln
                old_ln += 1
                new_ln += 1

    return hunks


async def compute_branch_diff(
    session: AsyncSession,
    branch_a_id: uuid.UUID,
    branch_b_id: uuid.UUID,
    path_filter: str = "",
    max_files: int = 1000,
) -> list[PatchEntry]:
    """Compute line-level diff between two branches using DB-stored content.

    Args:
        session: Async DB session.
        branch_a_id: Base branch UUID.
        branch_b_id: Target branch UUID.
        path_filter: Optional path prefix to filter files.
        max_files: Maximum number of files to diff (prevents OOM on huge repos).

    Returns:
        List of PatchEntry with file-level status and line-level hunks.
    """
    from attocode.code_intel.storage.branch_overlay import BranchOverlay
    from attocode.code_intel.storage.content_store import ContentStore

    overlay = BranchOverlay(session)
    content_store = ContentStore(session)

    # Get file-level diff
    file_diff = await overlay.diff_branches(branch_a_id, branch_b_id)

    # Apply path filter
    if path_filter:
        file_diff = {p: s for p, s in file_diff.items() if p.startswith(path_filter)}

    # Limit to max_files
    paths = sorted(file_diff.keys())[:max_files]

    # Resolve both manifests for content lookup
    manifest_a = await overlay.resolve_manifest(branch_a_id)
    manifest_b = await overlay.resolve_manifest(branch_b_id)

    patches: list[PatchEntry] = []

    for path in paths:
        status = file_diff[path]
        sha_a = manifest_a.get(path)
        sha_b = manifest_b.get(path)

        old_text = ""
        new_text = ""

        if sha_a:
            data = await content_store.get(sha_a)
            if data:
                try:
                    old_text = data.decode("utf-8", errors="replace")
                except Exception:
                    old_text = ""

        if sha_b:
            data = await content_store.get(sha_b)
            if data:
                try:
                    new_text = data.decode("utf-8", errors="replace")
                except Exception:
                    new_text = ""

        # Compute hunks
        hunks = _compute_hunks(old_text, new_text, path)

        additions = sum(
            1 for h in hunks for dl in h.lines if dl.origin == "+"
        )
        deletions = sum(
            1 for h in hunks for dl in h.lines if dl.origin == "-"
        )

        patches.append(PatchEntry(
            path=path,
            status=status,
            additions=additions,
            deletions=deletions,
            hunks=hunks,
        ))

    return patches
