"""Generate ground-truth search tasks from git history.

Mines commits for natural language queries (commit messages) paired with
relevant files (changed files in the commit). This augments hand-curated
ground truth with a larger, automatically-derived dataset.

Usage:
    python -m eval.meta_harness.git_dataset /path/to/repo --output queries.yaml
    python -m eval.meta_harness.git_dataset /path/to/repo --limit 50 --min-files 2
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(slots=True)
class GitQuery:
    """A search query derived from a git commit."""

    query: str
    relevant_files: list[str]
    commit_sha: str
    commit_date: str
    source: str = "git_derived"


# Patterns for filtering out unhelpful commits
_SKIP_PATTERNS = re.compile(
    r"^(merge |Merge |bump |chore\(deps\)|Revert |wip |WIP |fixup!|squash!|"
    r"release |v?\d+\.\d+|update changelog|auto-generated|"
    r"initial commit|first commit)",
    re.IGNORECASE,
)

# File extensions to include (source code only)
_CODE_EXTS = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".c", ".h",
    ".cpp", ".hpp", ".java", ".rb", ".swift", ".kt", ".scala", ".ex",
    ".exs", ".php", ".cs", ".lua", ".zig", ".nim", ".cr", ".pl",
})

# Files to always skip
_SKIP_FILES = frozenset({
    "package-lock.json", "yarn.lock", "go.sum", "Cargo.lock",
    "poetry.lock", "Gemfile.lock", "pnpm-lock.yaml",
})


def _run_git(repo_dir: str, *args: str, timeout: int = 30) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def _is_code_file(path: str) -> bool:
    """Check if a file path is a source code file."""
    basename = os.path.basename(path)
    if basename in _SKIP_FILES:
        return False
    ext = os.path.splitext(path)[1].lower()
    return ext in _CODE_EXTS


def _clean_message(msg: str) -> str:
    """Clean a commit message into a search query.

    Strips conventional commit prefixes, issue refs, etc.
    """
    # Remove conventional commit prefix: "fix(scope): " or "feat: "
    msg = re.sub(r"^(fix|feat|refactor|chore|docs|test|perf|ci|build|style)\s*(\([^)]+\))?\s*:\s*", "", msg, flags=re.IGNORECASE)
    # Remove issue references: (#123), fixes #123, closes #123
    msg = re.sub(r"\s*\(#\d+\)", "", msg)
    msg = re.sub(r"\s*(fixes|closes|resolves)\s+#\d+", "", msg, flags=re.IGNORECASE)
    # Remove trailing period
    msg = msg.strip().rstrip(".")
    return msg


def extract_queries(
    repo_dir: str,
    *,
    limit: int = 100,
    min_files: int = 2,
    max_files: int = 15,
    min_message_words: int = 3,
    since: str = "",
) -> list[GitQuery]:
    """Extract search queries from git commit history.

    Args:
        repo_dir: Path to the git repository.
        limit: Maximum number of commits to scan.
        min_files: Minimum changed code files per commit.
        max_files: Maximum changed code files (skip broad refactors).
        min_message_words: Minimum words in cleaned message.
        since: Git date filter (e.g. "6 months ago").

    Returns:
        List of GitQuery objects suitable for search evaluation.
    """
    # Get commit log: hash, date, subject (first line)
    git_args = [
        "log", f"--max-count={limit * 3}",  # scan more to filter
        "--format=%H|%aI|%s",
        "--no-merges",
    ]
    if since:
        git_args.append(f"--since={since}")

    raw_log = _run_git(repo_dir, *git_args, timeout=60)
    if not raw_log:
        return []

    queries: list[GitQuery] = []
    seen_messages: set[str] = set()

    for line in raw_log.strip().splitlines():
        if len(queries) >= limit:
            break

        parts = line.split("|", 2)
        if len(parts) < 3:
            continue

        sha, date, message = parts[0], parts[1], parts[2]

        # Skip unhelpful commits
        if _SKIP_PATTERNS.search(message):
            continue

        # Clean message
        cleaned = _clean_message(message)
        if len(cleaned.split()) < min_message_words:
            continue

        # Deduplicate similar messages
        msg_key = cleaned.lower()[:60]
        if msg_key in seen_messages:
            continue
        seen_messages.add(msg_key)

        # Get changed files
        diff_output = _run_git(repo_dir, "diff-tree", "--no-commit-id", "-r", "--name-only", sha)
        if not diff_output:
            continue

        changed_files = [
            f for f in diff_output.strip().splitlines()
            if _is_code_file(f)
        ]

        if len(changed_files) < min_files or len(changed_files) > max_files:
            continue

        queries.append(GitQuery(
            query=cleaned,
            relevant_files=changed_files,
            commit_sha=sha[:12],
            commit_date=date[:10],
        ))

    return queries


def to_ground_truth_yaml(queries: list[GitQuery], repo_name: str) -> dict:
    """Convert to the ground truth YAML format used by eval/search_quality.py."""
    return {
        "repo": repo_name,
        "source": "git_derived",
        "queries": [
            {
                "query": q.query,
                "relevant_files": q.relevant_files,
                "commit_sha": q.commit_sha,
            }
            for q in queries
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate search ground truth from git history",
    )
    parser.add_argument("repo_dir", help="Path to git repository")
    parser.add_argument("--output", "-o", help="Output YAML path (default: stdout)")
    parser.add_argument("--repo-name", help="Repository name (default: dirname)")
    parser.add_argument("--limit", type=int, default=50, help="Max queries to generate")
    parser.add_argument("--min-files", type=int, default=2, help="Min changed files per commit")
    parser.add_argument("--max-files", type=int, default=15, help="Max changed files per commit")
    parser.add_argument("--since", default="1 year ago", help="Git date filter")
    args = parser.parse_args()

    repo_dir = os.path.abspath(args.repo_dir)
    if not os.path.isdir(os.path.join(repo_dir, ".git")):
        print(f"Error: {repo_dir} is not a git repository", file=sys.stderr)
        sys.exit(1)

    repo_name = args.repo_name or os.path.basename(repo_dir)

    queries = extract_queries(
        repo_dir,
        limit=args.limit,
        min_files=args.min_files,
        max_files=args.max_files,
        since=args.since,
    )

    print(f"Extracted {len(queries)} queries from {repo_name}", file=sys.stderr)

    data = to_ground_truth_yaml(queries, repo_name)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        print(f"Saved to {args.output}", file=sys.stderr)
    else:
        yaml.dump(data, sys.stdout, default_flow_style=False, sort_keys=False)


if __name__ == "__main__":
    main()
