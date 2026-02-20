"""Codebase context system.

Provides intelligent code understanding through:
- File discovery with ignore patterns
- Repository map generation
- Lightweight tree view
- File importance scoring
- Context selection for prompts
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class FileInfo:
    """Information about a discovered file."""

    path: str
    relative_path: str
    size: int = 0
    language: str = ""
    importance: float = 0.0
    is_test: bool = False
    is_config: bool = False
    line_count: int = 0

    @property
    def extension(self) -> str:
        return Path(self.path).suffix


@dataclass(slots=True)
class RepoMap:
    """Repository map showing file structure and key definitions."""

    tree: str  # Text tree view
    files: list[FileInfo]
    total_files: int = 0
    total_lines: int = 0
    languages: dict[str, int] = field(default_factory=dict)  # lang -> file count


# Language detection by extension
EXTENSION_LANGUAGES: dict[str, str] = {
    ".py": "python", ".pyi": "python",
    ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".cs": "csharp",
    ".lua": "lua",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".yaml": "yaml", ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".md": "markdown",
    ".html": "html", ".htm": "html",
    ".css": "css", ".scss": "scss",
    ".sql": "sql",
    ".dockerfile": "docker",
}

# Patterns indicating test files
TEST_PATTERNS = (
    "test_", "_test.", ".test.", "tests/", "test/",
    "spec_", "_spec.", ".spec.", "specs/", "spec/",
    "__tests__/",
)

# Patterns indicating config files
CONFIG_PATTERNS = (
    "config.", ".config.", "settings.",
    "pyproject.toml", "package.json", "tsconfig",
    ".eslintrc", ".prettierrc", "Makefile", "Dockerfile",
    ".github/", ".gitlab-ci",
)

# Default ignore patterns
DEFAULT_IGNORES = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", ".next", ".nuxt",
    "coverage", ".coverage", "htmlcov",
    ".tox", ".nox", ".eggs", "*.egg-info",
    ".DS_Store", "Thumbs.db",
}


@dataclass
class CodebaseContextManager:
    """Manages codebase context for intelligent code understanding.

    Discovers files, builds repository maps, scores importance,
    and selects relevant context for LLM prompts.
    """

    root_dir: str
    max_files: int = 500
    max_context_tokens: int = 8000
    ignore_patterns: set[str] = field(default_factory=lambda: set(DEFAULT_IGNORES))
    _files: list[FileInfo] = field(default_factory=list, repr=False)
    _repo_map: RepoMap | None = field(default=None, repr=False)

    def discover_files(self) -> list[FileInfo]:
        """Discover all relevant files in the repository.

        Returns:
            List of FileInfo objects for discovered files.
        """
        root = Path(self.root_dir)
        files: list[FileInfo] = []

        for dirpath, dirnames, filenames in os.walk(root):
            # Filter ignored directories (in-place to prevent os.walk descent)
            dirnames[:] = [
                d for d in dirnames
                if d not in self.ignore_patterns and not d.startswith(".")
            ]

            for filename in filenames:
                if filename.startswith("."):
                    continue
                if any(filename.endswith(p) for p in (".pyc", ".pyo", ".class", ".o")):
                    continue

                full_path = os.path.join(dirpath, filename)
                try:
                    rel_path = os.path.relpath(full_path, root)
                except ValueError:
                    continue

                ext = Path(filename).suffix
                lang = EXTENSION_LANGUAGES.get(ext, "")

                try:
                    size = os.path.getsize(full_path)
                except OSError:
                    size = 0

                # Skip very large files
                if size > 1_000_000:  # 1MB
                    continue

                is_test = any(p in rel_path.lower() for p in TEST_PATTERNS)
                is_config = any(p in rel_path.lower() for p in CONFIG_PATTERNS)

                # Estimate line count
                line_count = 0
                if lang and size < 500_000:
                    try:
                        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                            line_count = sum(1 for _ in f)
                    except OSError:
                        pass

                files.append(FileInfo(
                    path=full_path,
                    relative_path=rel_path,
                    size=size,
                    language=lang,
                    is_test=is_test,
                    is_config=is_config,
                    line_count=line_count,
                ))

                if len(files) >= self.max_files:
                    break

            if len(files) >= self.max_files:
                break

        # Score importance
        for f in files:
            f.importance = self._score_importance(f)

        # Sort by importance (highest first)
        files.sort(key=lambda f: f.importance, reverse=True)

        self._files = files
        return files

    def get_repo_map(self) -> RepoMap:
        """Generate a repository map.

        Returns:
            RepoMap with tree view and file information.
        """
        if self._repo_map is not None:
            return self._repo_map

        if not self._files:
            self.discover_files()

        # Build tree
        tree = self._build_tree()

        # Compute language stats
        languages: dict[str, int] = {}
        total_lines = 0
        for f in self._files:
            if f.language:
                languages[f.language] = languages.get(f.language, 0) + 1
            total_lines += f.line_count

        self._repo_map = RepoMap(
            tree=tree,
            files=self._files,
            total_files=len(self._files),
            total_lines=total_lines,
            languages=languages,
        )
        return self._repo_map

    def get_tree_view(self, max_depth: int = 3) -> str:
        """Get a lightweight tree view of the repository.

        Args:
            max_depth: Maximum directory depth to show.

        Returns:
            Text tree view string.
        """
        return self._build_tree(max_depth=max_depth)

    def select_context(
        self,
        query: str = "",
        strategy: str = "importance",
        max_files: int = 20,
    ) -> list[FileInfo]:
        """Select the most relevant files for context.

        Args:
            query: Optional query to influence selection.
            strategy: Selection strategy ('importance', 'relevance', 'breadth').
            max_files: Maximum files to include.

        Returns:
            Selected files.
        """
        if not self._files:
            self.discover_files()

        if strategy == "relevance" and query:
            return self._select_by_relevance(query, max_files)
        elif strategy == "breadth":
            return self._select_by_breadth(max_files)
        else:
            # Default: importance-based
            return self._files[:max_files]

    def format_context(
        self,
        files: list[FileInfo] | None = None,
        include_content: bool = False,
        max_tokens: int | None = None,
    ) -> str:
        """Format selected files as context for LLM prompt.

        Args:
            files: Files to include (defaults to top by importance).
            include_content: Whether to include file contents.
            max_tokens: Token budget for context.

        Returns:
            Formatted context string.
        """
        if files is None:
            files = self.select_context(max_files=15)

        max_tok = max_tokens or self.max_context_tokens
        from attocode.integrations.utilities.token_estimate import estimate_tokens

        parts = ["## Repository Context\n"]
        parts.append(f"Files: {len(self._files)} | ")
        parts.append(f"Languages: {', '.join(sorted(self.get_repo_map().languages.keys()))}\n")
        parts.append(f"\n### Key Files\n")

        token_count = estimate_tokens("\n".join(parts))

        for f in files:
            entry = f"- `{f.relative_path}` ({f.line_count}L, {f.language})"
            entry_tokens = estimate_tokens(entry)

            if include_content and f.size < 50_000:
                try:
                    content = Path(f.path).read_text(encoding="utf-8", errors="ignore")
                    content_entry = f"\n```{f.language}\n# {f.relative_path}\n{content}\n```\n"
                    content_tokens = estimate_tokens(content_entry)
                    if token_count + content_tokens <= max_tok:
                        entry = entry + content_entry
                        entry_tokens += content_tokens
                except OSError:
                    pass

            if token_count + entry_tokens > max_tok:
                break

            parts.append(entry)
            token_count += entry_tokens

        return "\n".join(parts)

    def _score_importance(self, file: FileInfo) -> float:
        """Score file importance (0.0 - 1.0).

        Heuristic scoring based on:
        - Entry points (main, cli) score highest
        - Config files score high
        - Source files score by size (moderate = best)
        - Test files score lower
        """
        score = 0.5  # Base

        name = Path(file.relative_path).name.lower()
        rel = file.relative_path.lower()

        # Entry points
        if name in ("main.py", "main.ts", "app.py", "app.ts", "cli.py", "cli.ts"):
            score += 0.3
        elif name in ("__init__.py", "index.ts", "index.js"):
            score += 0.1

        # Config files
        if file.is_config:
            score += 0.2
        if name in ("pyproject.toml", "package.json", "cargo.toml"):
            score += 0.15

        # Source vs test
        if file.is_test:
            score -= 0.2

        # Moderate-size files are often more important
        if 50 < file.line_count < 500:
            score += 0.1
        elif file.line_count > 1000:
            score += 0.05
        elif file.line_count < 10:
            score -= 0.1

        # Depth penalty (deeply nested = less important)
        depth = file.relative_path.count(os.sep)
        score -= depth * 0.03

        # README and docs
        if name in ("readme.md", "readme.rst", "readme.txt"):
            score += 0.25

        return max(0.0, min(1.0, score))

    def _select_by_relevance(self, query: str, max_files: int) -> list[FileInfo]:
        """Select files by relevance to a query (simple keyword matching)."""
        query_lower = query.lower()
        keywords = query_lower.split()

        scored: list[tuple[float, FileInfo]] = []
        for f in self._files:
            rel_lower = f.relative_path.lower()
            match_score = sum(1 for kw in keywords if kw in rel_lower)
            if match_score > 0:
                scored.append((f.importance + match_score * 0.3, f))
            else:
                scored.append((f.importance, f))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [f for _, f in scored[:max_files]]

    def _select_by_breadth(self, max_files: int) -> list[FileInfo]:
        """Select files for broad coverage across directories."""
        seen_dirs: set[str] = set()
        selected: list[FileInfo] = []

        for f in self._files:
            parent = str(Path(f.relative_path).parent)
            if parent not in seen_dirs or len(selected) < max_files // 2:
                selected.append(f)
                seen_dirs.add(parent)
            if len(selected) >= max_files:
                break

        return selected

    def _build_tree(self, max_depth: int = 4) -> str:
        """Build a text tree view of the repository."""
        if not self._files:
            return "(no files discovered)"

        root = Path(self.root_dir)
        tree_dict: dict[str, Any] = {}

        for f in self._files:
            parts = Path(f.relative_path).parts
            if len(parts) > max_depth + 1:
                parts = parts[:max_depth] + ("...",)

            current = tree_dict
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = None  # Leaf file

        lines = [str(root.name) + "/"]
        self._format_tree_dict(tree_dict, lines, prefix="")
        return "\n".join(lines)

    def _format_tree_dict(
        self,
        d: dict[str, Any],
        lines: list[str],
        prefix: str,
    ) -> None:
        """Recursively format tree dict into lines."""
        items = sorted(d.items(), key=lambda x: (x[1] is not None, x[0]))
        for i, (name, subtree) in enumerate(items):
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "
            suffix = "/" if subtree is not None else ""
            lines.append(f"{prefix}{connector}{name}{suffix}")

            if subtree is not None:
                next_prefix = prefix + ("    " if is_last else "│   ")
                self._format_tree_dict(subtree, lines, next_prefix)
