"""Repository management for SWE-Atlas QnA evaluation.

Clones and caches the 11 SWE-Atlas repos at their pinned commits.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".cache" / "attocode" / "sweatlas" / "repos"


def _repo_name(url: str) -> str:
    """Extract owner/repo from GitHub URL."""
    # "kovidgoyal/kitty" or "https://github.com/kovidgoyal/kitty"
    url = url.rstrip("/")
    if "/" in url:
        parts = url.split("/")
        return f"{parts[-2]}_{parts[-1]}"
    return url


def ensure_repo(
    repo_url: str,
    base_commit: str,
) -> Path:
    """Clone repo if needed and checkout the pinned commit.

    Uses full clone (not shallow) because SWE-Atlas pins arbitrary commits
    that GitHub won't serve via `git fetch <sha>`.

    Returns the local path to the repo.
    """
    name = _repo_name(repo_url)
    repo_dir = CACHE_DIR / name

    # Normalize URL to full GitHub URL if needed
    if not repo_url.startswith("http"):
        full_url = f"https://github.com/{repo_url}.git"
    else:
        full_url = repo_url
        if not full_url.endswith(".git"):
            full_url += ".git"

    if not repo_dir.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("Cloning %s to %s ...", full_url, repo_dir)
        subprocess.run(
            ["git", "clone", full_url, str(repo_dir)],
            check=True,
            capture_output=True,
            text=True,
        )

    # Ensure we have the target commit
    current = _get_head(repo_dir)
    if current != base_commit:
        logger.info("Checking out commit %s in %s ...", base_commit[:12], name)
        subprocess.run(
            ["git", "checkout", base_commit],
            cwd=repo_dir,
            check=True,
            capture_output=True,
            text=True,
        )

    return repo_dir


def _get_head(repo_dir: Path) -> str:
    """Get current HEAD commit SHA."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def cleanup_repo(repo_url: str) -> None:
    """Remove cached repo."""
    import shutil

    name = _repo_name(repo_url)
    repo_dir = CACHE_DIR / name
    if repo_dir.exists():
        shutil.rmtree(repo_dir)
        logger.info("Removed cached repo: %s", repo_dir)
