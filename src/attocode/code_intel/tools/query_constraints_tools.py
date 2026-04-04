"""Query constraints MCP tools.

Supports fff-style query constraints for filtering search results:
- git:modified, git:staged, git:deleted, git:renamed, git:untracked, git:ignored
- !pattern - exclude files matching pattern
- path/ - filter by directory
- ./**/*.py - glob patterns
- *.py - extension filters

Example queries:
  "git:modified *.py" - Modified Python files
  "!test/ src/**/*.rs" - Rust files not in test directories
  "git:staged !vendor/" - Staged files excluding vendor
"""

from __future__ import annotations

import subprocess

from attocode.code_intel._shared import _get_project_dir, mcp


def _get_constraint_processor():
    """Get the constraint processor."""
    from attocode.integrations.context.query_constraints import (
        QueryConstraintProcessor,
    )

    project_dir = _get_project_dir()
    return QueryConstraintProcessor(project_dir=project_dir)


def _run_git_status() -> dict[str, str]:
    """Run git status --porcelain to get all file statuses.

    Returns:
        Dict mapping file path to status code.
    """
    project_dir = _get_project_dir()

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )

        statuses: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if len(line) < 3:
                continue
            x_status = line[0]  # index (staging area)
            y_status = line[1]  # worktree
            file_path = line[3:].strip()
            # Prefer index status if meaningful, otherwise use worktree
            if x_status not in (" ", "?"):
                statuses[file_path] = x_status
            elif y_status != " ":
                statuses[file_path] = y_status
            else:
                statuses[file_path] = x_status  # handles '??' etc.

        return statuses

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {}


@mcp.tool()
def parse_query_with_constraints(query: str) -> str:
    """Parse a query with fff-style constraints.

    Shows how the query is decomposed into the main search term
    and any constraints.

    Supported constraints:
    - git:modified, git:staged, git:deleted, git:renamed, git:untracked, git:ignored
    - !pattern - exclude files matching pattern
    - path/ - filter by directory
    - ./**/*.py - glob patterns
    - *.py - extension filters

    Args:
        query: Query string to parse.

    Returns:
        Parsed constraint breakdown.
    """
    from attocode.integrations.context.query_constraints import parse_query_constraints

    parsed = parse_query_constraints(query)

    lines = [
        f"Query: '{query}'",
        "\nParsed components:",
        f"  Main query: '{parsed.query}'" if parsed.query else "  Main query: (empty)",
        f"\n  Constraints ({len(parsed.constraints)}):",
    ]

    if not parsed.constraints:
        lines.append("    (none)")
    else:
        for i, c in enumerate(parsed.constraints, 1):
            neg_str = " (negated)" if c.negated else ""
            lines.append(f"    {i}. [{c.type}] '{c.value}'{neg_str}")

    lines.append("\nExamples of valid queries:")
    lines.append('  "git:modified *.py" - Find modified Python files')
    lines.append('  "!test/ src/**/*.rs" - Rust files not in test/')
    lines.append('  "git:staged !vendor/" - Staged files except vendor')

    return "\n".join(lines)


@mcp.tool()
def filter_files_with_constraints(
    query: str,
    files: str,
) -> str:
    """Filter a list of files using query constraints.

    Takes a query with constraints and a list of files, then returns
    only the files that match all constraints.

    Args:
        query: Query with constraints (e.g., "git:modified *.py")
        files: Newline-separated list of file paths to filter.

    Returns:
        Filtered list of files.
    """
    from attocode.integrations.context.query_constraints import (
        GitStatus,
        matches_constraints,
        parse_query_constraints,
    )

    file_list = [f.strip() for f in files.splitlines() if f.strip()]

    if not file_list:
        return "No files provided."

    parsed = parse_query_constraints(query)

    if not parsed.constraints:
        return f"No constraints found in query '{query}'."

    # Get git statuses
    git_statuses_raw = _run_git_status()
    git_statuses: dict[str, GitStatus] = {}

    status_map = {
        "M": GitStatus.MODIFIED,
        "A": GitStatus.STAGED,
        "D": GitStatus.DELETED,
        "R": GitStatus.RENAMED,
        "?": GitStatus.UNTRACKED,
        "!": GitStatus.IGNORED,
    }

    for file_path, status_char in git_statuses_raw.items():
        git_statuses[file_path] = status_map.get(status_char, GitStatus.MODIFIED)

    # Filter files
    filtered = []
    for file_path in file_list:
        git_status = git_statuses.get(file_path)
        if matches_constraints(file_path, parsed.constraints, git_status):
            filtered.append(file_path)

    if not filtered:
        return (
            f"No files matched constraints from query '{query}'.\n"
            f"Tried to filter {len(file_list)} files."
        )

    lines = [
        f"Filtered {len(filtered)} files (from {len(file_list)} input files):",
        f"Query: '{query}'\n",
    ]
    lines.extend(filtered)

    return "\n".join(lines)


@mcp.tool()
def list_modified_files() -> str:
    """List all git-modified files in the project.

    Returns:
        List of modified files with their status.
    """
    project_dir = _get_project_dir()

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )

        files_by_status: dict[str, list[str]] = {}

        status_map = {
            "M": "modified",
            "A": "staged",
            "D": "deleted",
            "R": "renamed",
            "?": "untracked",
            "!": "ignored",
        }

        for line in result.stdout.splitlines():
            if len(line) < 3:
                continue

            x_status = line[0]  # index (staging area)
            y_status = line[1]  # worktree
            file_path = line[3:].strip()

            # Add file under each applicable status
            statuses_to_add: list[str] = []
            if x_status not in (" ", "?", "!"):
                statuses_to_add.append(
                    status_map.get(x_status, f"unknown({x_status})")
                )
            if y_status not in (" ", "?", "!"):
                name = status_map.get(y_status, f"unknown({y_status})")
                if name not in statuses_to_add:
                    statuses_to_add.append(name)
            # Handle untracked/ignored (both columns are the same char)
            if x_status == "?":
                statuses_to_add.append("untracked")
            elif x_status == "!":
                statuses_to_add.append("ignored")

            for status_name in statuses_to_add:
                if status_name not in files_by_status:
                    files_by_status[status_name] = []
                files_by_status[status_name].append(file_path)

        if not files_by_status:
            return "No modified files."

        lines = ["Modified files:"]
        for status_name, files in files_by_status.items():
            lines.append(f"\n{status_name.upper()}:")
            for f in sorted(files):
                lines.append(f"  {f}")

        return "\n".join(lines)

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return f"Error running git: {e}"
