"""Gitignore-compatible path filtering using pathspec."""

from __future__ import annotations

from pathlib import Path

import pathspec


class IgnoreManager:
    """Manages .gitignore-style path filtering.

    Loads patterns from .gitignore files and provides matching.
    """

    def __init__(self, root: str | Path = ".") -> None:
        self._root = Path(root)
        self._spec: pathspec.PathSpec | None = None
        self._load()

    def _load(self) -> None:
        """Load .gitignore patterns from the root directory."""
        patterns: list[str] = []

        # Always ignore these
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
                text = gitignore.read_text(encoding="utf-8", errors="replace")
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
