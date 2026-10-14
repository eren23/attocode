"""Gitignore-compatible path filtering using pathspec."""

from __future__ import annotations

from pathlib import Path

import pathspec

# Default ignore directories
DEFAULT_IGNORES = {
    # VCS
    ".git", ".svn", ".hg",
    # Python
    "__pycache__", ".venv", "venv", "env", ".env",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".tox", ".nox", ".eggs", "*.egg-info",
    "site-packages",
    # JS/TS
    "node_modules", "bower_components",
    ".next", ".nuxt", ".svelte-kit", ".parcel-cache",
    # Build output
    "dist", "build", "out", "output", "target",
    "_build", "cmake-build-debug", "cmake-build-release",
    # Coverage / test artifacts
    "coverage", ".coverage", "htmlcov", ".nyc_output",
    # IDE / editor
    ".idea", ".vscode", ".vs",
    # OS
    ".DS_Store", "Thumbs.db",
    # Containers / infra
    ".terraform", ".vagrant",
    # Misc generated
    ".cache", ".tmp", "tmp",
    "vendor",  # Go/PHP/Ruby vendor dirs
    ".gradle", ".maven",
}

class IgnoreManager:
    """Manages .gitignore-style path filtering.

    Loads patterns from .gitignore files and provides matching.
    """

    def __init__(self, root: str | Path = ".", *, default_dirs=None) -> None:
        self._root = Path(root)
        self._default_dirs = DEFAULT_IGNORES if default_dirs is None else default_dirs
        self._spec: pathspec.PathSpec | None = None
        self._load()

    def _load(self) -> None:
        """Load .gitignore patterns from the root directory."""
        patterns: list[str] = [name + "/" for name in sorted(self._default_dirs)]

        # Baseline exclusions; explicit project negations may admit source directories.
        patterns.extend([
            ".git/",
            "node_modules/",
            "__pycache__/",
            ".venv/",
            "*.pyc",
            ".DS_Store",
        ])

        # Load project .gitignore
        gitignore = self._root / ".gitignore"
        if gitignore.is_file():
            try:
                with gitignore.open(encoding="utf-8", errors="replace") as stream:
                    text = stream.read(1_000_000)
                for line in text.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        patterns.append(line)
            except OSError:
                pass

        self._spec = pathspec.PathSpec.from_lines("gitignore", patterns)

    def is_ignored(self, path: str | Path) -> bool:
        """Check if a path should be ignored."""
        if self._spec is None:
            return False
        rel = str(path)
        # pathspec expects forward slashes
        rel = rel.replace("\\", "/")
        return self._spec.match_file(rel)

    def filter_paths(self, paths: list[str]) -> list[str]:
        """Filter a list of paths, returning only non-ignored ones."""
        return [p for p in paths if not self.is_ignored(p)]

    def reload(self) -> None:
        """Reload patterns from disk."""
        self._load()
