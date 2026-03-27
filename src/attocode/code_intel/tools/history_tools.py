"""History tools for the code-intel MCP server.

Tools: code_evolution, recent_changes, change_coupling, churn_hotspots,
merge_risk.

Local mode uses git subprocess calls directly.
Service mode queries the Commit + CommitFileStat DB tables.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from collections import defaultdict
from datetime import datetime, timezone

from attocode.code_intel._shared import (
    _get_project_dir,
    mcp,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers — git subprocess for local mode
# ---------------------------------------------------------------------------


def _run_git(args: list[str], cwd: str) -> str:
    """Run a git command and return stdout, or empty string on error."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.debug("git %s failed: %s", " ".join(args), result.stderr.strip())
            return ""
        return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.debug("git command error: %s", exc)
        return ""


def _parse_evolution_output(raw: str) -> list[dict]:
    """Parse git log output with --numstat --format=%H|%an|%ae|%aI|%s.

    Returns a list of commit dicts with per-file stats.
    """
    if not raw.strip():
        return []

    commits: list[dict] = []
    current: dict | None = None

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue

        # Header line: sha|author_name|author_email|date|subject
        if "|" in line and line.count("|") >= 4:
            parts = line.split("|", 4)
            if len(parts) == 5 and len(parts[0]) >= 7:
                if current is not None:
                    commits.append(current)
                current = {
                    "sha": parts[0],
                    "author": parts[1],
                    "email": parts[2],
                    "date": parts[3],
                    "subject": parts[4],
                    "files": [],
                }
                continue

        # Numstat line: added\tremoved\tpath
        if current is not None and "\t" in line:
            parts = line.split("\t")
            if len(parts) >= 3:
                try:
                    added = int(parts[0]) if parts[0] != "-" else 0
                    removed = int(parts[1]) if parts[1] != "-" else 0
                except ValueError:
                    continue
                file_path = parts[2]
                # Handle renames: old => new
                if " => " in file_path:
                    file_path = file_path.split(" => ")[-1].rstrip("}")
                    if "{" in file_path:
                        # Handle partial rename like src/{old => new}/file.py
                        file_path = file_path.replace("{", "").replace("}", "")
                current["files"].append({
                    "path": file_path,
                    "added": added,
                    "removed": removed,
                })

    if current is not None:
        commits.append(current)

    return commits


def _filter_by_symbol(commits: list[dict], symbol: str) -> list[dict]:
    """Filter commits to only those whose subject or file paths mention the symbol."""
    if not symbol:
        return commits
    symbol_lower = symbol.lower()
    filtered = []
    for commit in commits:
        if symbol_lower in commit["subject"].lower():
            filtered.append(commit)
            continue
        # Check if any changed file might contain the symbol
        # (heuristic: symbol name appears in the path)
        for f in commit["files"]:
            if symbol_lower in f["path"].lower():
                filtered.append(commit)
                break
    return filtered


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def code_evolution(
    path: str,
    symbol: str = "",
    since: str = "",
    max_results: int = 20,
) -> str:
    """Show change history for a file or symbol.

    Traces how a file (or a specific symbol within it) has evolved over
    time, showing commits with line-level change statistics. Useful for
    understanding why code looks the way it does and who changed it.

    Args:
        path: File path (relative to project root or absolute).
        symbol: Optional symbol name to filter commits mentioning it.
        since: Optional date filter (e.g. "2024-01-01", "3 months ago").
        max_results: Maximum number of commits to return (default 20).
    """
    project_dir = _get_project_dir()

    # Resolve path relative to project
    if os.path.isabs(path):
        try:
            rel_path = os.path.relpath(path, project_dir)
        except ValueError:
            rel_path = path
    else:
        rel_path = path

    # Build git log command
    git_args = [
        "log",
        "--follow",
        "--numstat",
        "--format=%H|%an|%ae|%aI|%s",
        f"-{max_results * 2}",  # fetch extra to account for filtering
    ]
    if since:
        git_args.append(f"--since={since}")
    git_args.extend(["--", rel_path])

    raw = _run_git(git_args, project_dir)
    if not raw.strip():
        return f"No commit history found for '{rel_path}'."

    commits = _parse_evolution_output(raw)

    # Filter by symbol if requested
    if symbol:
        commits = _filter_by_symbol(commits, symbol)

    commits = commits[:max_results]

    if not commits:
        msg = f"No commits found for '{rel_path}'"
        if symbol:
            msg += f" mentioning symbol '{symbol}'"
        return msg + "."

    # Format output
    lines = [f"Change history for {rel_path}"]
    if symbol:
        lines[0] += f" (symbol: {symbol})"
    lines.append(f"({len(commits)} commits shown)\n")

    for i, commit in enumerate(commits, 1):
        sha_short = commit["sha"][:8]
        date_str = commit["date"][:10] if len(commit["date"]) >= 10 else commit["date"]
        lines.append(
            f"  {i:>3}. {sha_short}  {date_str}  {commit['author']}"
        )
        lines.append(f"       {commit['subject']}")

        # Show file stats
        total_added = 0
        total_removed = 0
        for f in commit["files"]:
            total_added += f["added"]
            total_removed += f["removed"]

        if len(commit["files"]) == 1:
            f = commit["files"][0]
            lines.append(f"       +{f['added']} -{f['removed']}  {f['path']}")
        elif commit["files"]:
            lines.append(f"       +{total_added} -{total_removed} across {len(commit['files'])} files")
            # Show the target file specifically if among many
            for f in commit["files"]:
                if rel_path in f["path"] or f["path"] in rel_path:
                    lines.append(f"         +{f['added']} -{f['removed']}  {f['path']}")
                    break

        lines.append("")

    # Summary
    total_commits = len(commits)
    all_authors = sorted(set(c["author"] for c in commits))
    lines.append(f"Summary: {total_commits} commits by {len(all_authors)} author(s)")
    if len(all_authors) <= 5:
        lines.append(f"Authors: {', '.join(all_authors)}")
    else:
        lines.append(f"Top authors: {', '.join(all_authors[:5])}, +{len(all_authors) - 5} more")

    return "\n".join(lines)


@mcp.tool()
def recent_changes(
    days: int = 7,
    path: str = "",
    top_n: int = 20,
) -> str:
    """Show recently modified files and change frequency.

    Aggregates recent git activity to identify files with the most
    changes — useful for finding active development areas, understanding
    project velocity, and spotting potential merge conflict hotspots.

    Args:
        days: Look back this many days (default 7).
        path: Optional path prefix to filter (e.g. "src/api/").
        top_n: Number of top files to show (default 20).
    """
    project_dir = _get_project_dir()

    git_args = [
        "log",
        f"--since={days} days ago",
        "--numstat",
        "--format=%H|%aI|%s",
    ]
    if path:
        git_args.extend(["--", path])

    raw = _run_git(git_args, project_dir)
    if not raw.strip():
        scope = f" under '{path}'" if path else ""
        return f"No changes found in the last {days} day(s){scope}."

    # Parse and aggregate
    file_stats: dict[str, dict] = defaultdict(
        lambda: {"commits": 0, "added": 0, "removed": 0, "authors": set(), "last_date": ""}
    )
    commit_count = 0
    all_authors: set[str] = set()
    current_date = ""

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue

        # Header line
        if "|" in line and line.count("|") >= 2:
            parts = line.split("|", 2)
            if len(parts) == 3 and len(parts[0]) >= 7:
                commit_count += 1
                current_date = parts[1][:10] if len(parts[1]) >= 10 else parts[1]
                # Extract author from a separate git log if needed
                continue

        # Numstat line
        if "\t" in line:
            parts = line.split("\t")
            if len(parts) >= 3:
                try:
                    added = int(parts[0]) if parts[0] != "-" else 0
                    removed = int(parts[1]) if parts[1] != "-" else 0
                except ValueError:
                    continue
                file_path = parts[2]
                if " => " in file_path:
                    file_path = file_path.split(" => ")[-1].rstrip("}")
                    if "{" in file_path:
                        file_path = file_path.replace("{", "").replace("}", "")

                stats = file_stats[file_path]
                stats["commits"] += 1
                stats["added"] += added
                stats["removed"] += removed
                if current_date and (not stats["last_date"] or current_date > stats["last_date"]):
                    stats["last_date"] = current_date

    if not file_stats:
        scope = f" under '{path}'" if path else ""
        return f"No file changes found in the last {days} day(s){scope}."

    # Also get author info with a separate command
    author_args = [
        "log",
        f"--since={days} days ago",
        "--format=%an",
    ]
    if path:
        author_args.extend(["--", path])
    author_raw = _run_git(author_args, project_dir)
    if author_raw:
        all_authors = set(a.strip() for a in author_raw.splitlines() if a.strip())

    # Sort by commit frequency, then by total churn
    ranked = sorted(
        file_stats.items(),
        key=lambda kv: (kv[1]["commits"], kv[1]["added"] + kv[1]["removed"]),
        reverse=True,
    )[:top_n]

    # Format output
    scope_label = f" under '{path}'" if path else ""
    lines = [
        f"Recent changes (last {days} day(s){scope_label})",
        f"{commit_count} commits, {len(file_stats)} files modified, "
        f"{len(all_authors)} contributor(s)\n",
    ]

    # Table header
    lines.append(f"  {'#':>3}  {'Commits':>7}  {'Added':>6}  {'Removed':>7}  {'Last':>10}  File")
    lines.append(f"  {'':->3}  {'':->7}  {'':->6}  {'':->7}  {'':->10}  {'':->40}")

    for i, (fpath, stats) in enumerate(ranked, 1):
        last_date = stats["last_date"] if stats["last_date"] else "?"
        lines.append(
            f"  {i:>3}  {stats['commits']:>7}  "
            f"+{stats['added']:>5}  -{stats['removed']:>6}  "
            f"{last_date:>10}  {fpath}"
        )

    # Churn summary
    total_added = sum(s["added"] for s in file_stats.values())
    total_removed = sum(s["removed"] for s in file_stats.values())
    lines.append(f"\nTotal churn: +{total_added} -{total_removed} lines")

    if all_authors:
        sorted_authors = sorted(all_authors)
        if len(sorted_authors) <= 5:
            lines.append(f"Contributors: {', '.join(sorted_authors)}")
        else:
            lines.append(
                f"Contributors: {', '.join(sorted_authors[:5])}, "
                f"+{len(sorted_authors) - 5} more"
            )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Temporal coupling helpers
# ---------------------------------------------------------------------------

_temporal_analyzer = None
_temporal_lock = threading.Lock()


def _get_temporal_analyzer():
    """Lazily initialize the TemporalCouplingAnalyzer singleton."""
    global _temporal_analyzer
    if _temporal_analyzer is None:
        with _temporal_lock:
            if _temporal_analyzer is None:
                from attocode.integrations.context.temporal_coupling import (
                    TemporalCouplingAnalyzer,
                )

                project_dir = _get_project_dir()
                _temporal_analyzer = TemporalCouplingAnalyzer(project_dir=project_dir)
    return _temporal_analyzer


@mcp.tool()
def change_coupling(
    file: str,
    days: int = 90,
    min_coupling: float = 0.3,
    top_k: int = 20,
) -> str:
    """Find files that frequently change alongside a given file.

    Uses git history to build a co-change frequency matrix.  Files that
    appear in the same commit as the target file are scored by how often
    they co-occur relative to their individual change frequency.

    A coupling score of 1.0 means the files ALWAYS change together.
    A score of 0.5 means they change together half the time.

    Args:
        file: Target file path (relative to project root).
        days: Time window in days (default 90).
        min_coupling: Minimum coupling score to include (0.0-1.0, default 0.3).
        top_k: Maximum number of results (default 20).
    """
    analyzer = _get_temporal_analyzer()

    # Normalize path
    project_dir = _get_project_dir()
    if os.path.isabs(file):
        try:
            file = os.path.relpath(file, project_dir)
        except ValueError:
            pass

    results = analyzer.get_change_coupling(
        file, days=days, min_coupling=min_coupling, top_k=top_k,
    )

    if not results:
        return f"No temporal coupling found for '{file}' in the last {days} days."

    lines = [
        f"Change coupling for {file} (last {days} days)",
        f"({len(results)} coupled files, min_coupling={min_coupling})\n",
        f"  {'#':>3}  {'Score':>6}  {'Co-chg':>6}  {'Indiv':>5}  File",
        f"  {'':->3}  {'':->6}  {'':->6}  {'':->5}  {'':->40}",
    ]

    for i, entry in enumerate(results, 1):
        lines.append(
            f"  {i:>3}  {entry.coupling_score:>6.3f}  "
            f"{entry.co_changes:>6}  {entry.individual_changes:>5}  {entry.path}"
        )

    return "\n".join(lines)


@mcp.tool()
def churn_hotspots(
    days: int = 90,
    top_n: int = 20,
) -> str:
    """Rank files by change frequency and churn intensity.

    Combines commit frequency with line-level churn to identify the
    most actively modified files.  High-churn files are candidates for
    refactoring, increased test coverage, or architectural attention.

    Args:
        days: Time window in days (default 90).
        top_n: Number of top files to return (default 20).
    """
    analyzer = _get_temporal_analyzer()
    results = analyzer.get_churn_hotspots(days=days, top_n=top_n)

    if not results:
        return f"No file changes found in the last {days} days."

    lines = [
        f"Churn hotspots (last {days} days)",
        f"({len(results)} files shown)\n",
        f"  {'#':>3}  {'Score':>6}  {'Commits':>7}  {'Added':>6}  {'Removed':>7}  {'Authors':>7}  File",
        f"  {'':->3}  {'':->6}  {'':->7}  {'':->6}  {'':->7}  {'':->7}  {'':->40}",
    ]

    for i, entry in enumerate(results, 1):
        lines.append(
            f"  {i:>3}  {entry.churn_score:>6.4f}  {entry.commits:>7}  "
            f"+{entry.lines_added:>5}  -{entry.lines_removed:>6}  "
            f"{len(entry.authors):>7}  {entry.path}"
        )

    return "\n".join(lines)


@mcp.tool()
def merge_risk(
    files: list[str],
    days: int = 90,
) -> str:
    """Predict which other files will likely need changes.

    Given a set of files you're about to modify, predicts which other
    files are at risk of needing changes too — based on both temporal
    coupling (git co-change history) and structural coupling (import
    dependencies).

    Each prediction is annotated with its source ("temporal",
    "structural", or "both") and a confidence score.

    Args:
        files: List of file paths being modified.
        days: Time window for temporal coupling (default 90).
    """
    from attocode.code_intel._shared import _get_ast_service

    analyzer = _get_temporal_analyzer()
    project_dir = _get_project_dir()

    # Normalize paths
    normalized = []
    for f in files:
        if os.path.isabs(f):
            try:
                f = os.path.relpath(f, project_dir)
            except ValueError:
                pass
        normalized.append(f)

    # Get dependency graph from ASTService
    dep_forward: dict[str, set[str]] | None = None
    dep_reverse: dict[str, set[str]] | None = None
    try:
        ast_svc = _get_ast_service()
        dep_forward = ast_svc.index.file_dependencies
        dep_reverse = ast_svc.index.file_dependents
    except Exception:
        logger.debug("Could not load dependency graph for merge_risk")

    results = analyzer.get_merge_risk(
        normalized,
        days=days,
        dep_graph_forward=dep_forward,
        dep_graph_reverse=dep_reverse,
    )

    if not results:
        return f"No additional files predicted to need changes alongside {', '.join(normalized)}."

    # Determine overall risk level
    max_conf = max(e.confidence for e in results)
    if max_conf >= 0.7:
        risk_level = "HIGH"
    elif max_conf >= 0.4:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    lines = [
        f"Merge risk analysis for {', '.join(normalized)}",
        f"Overall risk: {risk_level} ({len(results)} predicted changes)\n",
        f"  {'#':>3}  {'Conf':>5}  {'Source':>10}  File",
        f"  {'':->3}  {'':->5}  {'':->10}  {'':->40}",
    ]

    for i, entry in enumerate(results, 1):
        lines.append(
            f"  {i:>3}  {entry.confidence:>5.3f}  {entry.reason:>10}  {entry.path}"
        )

    return "\n".join(lines)
