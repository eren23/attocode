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
    symbols: dict[str, list[str]] = field(default_factory=dict)  # rel_path -> symbol names


@dataclass(slots=True)
class DependencyGraph:
    """Forward and reverse dependency graph between files."""

    forward: dict[str, set[str]] = field(default_factory=dict)  # file -> files it imports
    reverse: dict[str, set[str]] = field(default_factory=dict)  # file -> files that import it

    def add_edge(self, source: str, target: str) -> None:
        """Add a dependency edge: source imports target."""
        self.forward.setdefault(source, set()).add(target)
        self.reverse.setdefault(target, set()).add(source)

    def get_importers(self, file_path: str) -> set[str]:
        """Get files that import the given file."""
        return self.reverse.get(file_path, set())

    def get_imports(self, file_path: str) -> set[str]:
        """Get files that the given file imports."""
        return self.forward.get(file_path, set())

    def hub_score(self, file_path: str) -> float:
        """Score based on how many files depend on this file (0.0-0.2)."""
        count = len(self.reverse.get(file_path, set()))
        return min(0.2, count * 0.04)

    def to_import_graph(self) -> dict[str, list[str]]:
        """Convert to the dict format expected by CodeSelector.ranked_search."""
        return {k: list(v) for k, v in self.forward.items()}


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


def _resolve_python_import(module: str, source_file: str, file_index: dict[str, str]) -> str | None:
    """Resolve a Python import module name to a relative file path.

    Args:
        module: Module name (e.g. 'os', 'mypackage.utils', '.sibling').
        source_file: Relative path of the importing file.
        file_index: Mapping of relative paths (normalized with /) to relative paths.

    Returns:
        Resolved relative path or None if not found.
    """
    # Skip stdlib / third-party (no dots in path and not found locally)
    parts = module.split(".")

    # Handle relative imports (leading dots)
    if module.startswith("."):
        # Strip leading dots and compute base directory
        dots = len(module) - len(module.lstrip("."))
        base = Path(source_file).parent
        for _ in range(dots - 1):
            base = base.parent
        parts = [p for p in module.lstrip(".").split(".") if p]
        if parts:
            candidate = str(base / "/".join(parts))
        else:
            candidate = str(base / "__init__")
    else:
        candidate = "/".join(parts)

    # Try candidate.py, candidate/__init__.py
    for suffix in (".py", "/__init__.py"):
        key = candidate + suffix
        normalized = key.replace(os.sep, "/")
        if normalized in file_index:
            return file_index[normalized]

    return None


def _resolve_js_import(module: str, source_file: str, file_index: dict[str, str]) -> str | None:
    """Resolve a JS/TS import path to a relative file path.

    Args:
        module: Import path (e.g. './utils', '../lib/helpers').
        source_file: Relative path of the importing file.
        file_index: Mapping of relative paths (normalized with /) to relative paths.

    Returns:
        Resolved relative path or None if not found.
    """
    # Only resolve relative imports
    if not module.startswith("."):
        return None

    base = Path(source_file).parent
    resolved = str((base / module).as_posix())

    # Try with various extensions
    for suffix in ("", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.js"):
        key = resolved + suffix
        if key in file_index:
            return file_index[key]

    return None


def build_dependency_graph(
    files: list[FileInfo],
    root_dir: str,
) -> DependencyGraph:
    """Build a dependency graph from file imports.

    Parses each file's imports and resolves them to file paths
    to build forward (imports) and reverse (imported-by) graphs.

    Args:
        files: Discovered files with language info.
        root_dir: Repository root directory.

    Returns:
        DependencyGraph with forward and reverse edges.
    """
    from attocode.integrations.context.codebase_ast import parse_file

    graph = DependencyGraph()

    # Build index: normalized relative path -> relative path
    file_index: dict[str, str] = {}
    for f in files:
        normalized = f.relative_path.replace(os.sep, "/")
        file_index[normalized] = f.relative_path

    for f in files:
        if f.language not in ("python", "javascript", "typescript"):
            continue

        try:
            ast = parse_file(f.path)
        except Exception:
            continue

        for imp in ast.imports:
            if f.language == "python":
                target = _resolve_python_import(imp.module, f.relative_path, file_index)
            else:
                target = _resolve_js_import(imp.module, f.relative_path, file_index)

            if target is not None and target != f.relative_path:
                graph.add_edge(f.relative_path, target)

    return graph


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
    _dep_graph: DependencyGraph | None = field(default=None, repr=False)

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

        # Build dependency graph and boost hub files
        self._dep_graph = build_dependency_graph(files, self.root_dir)
        for f in files:
            hub_boost = self._dep_graph.hub_score(f.relative_path)
            if hub_boost > 0:
                f.importance = min(1.0, f.importance + hub_boost)

        # Sort by importance (highest first)
        files.sort(key=lambda f: f.importance, reverse=True)

        self._files = files
        return files

    @property
    def dependency_graph(self) -> DependencyGraph | None:
        """Get the dependency graph (available after discover_files)."""
        return self._dep_graph

    def get_repo_map(self, *, include_symbols: bool = False) -> RepoMap:
        """Generate a repository map.

        Args:
            include_symbols: If True, annotate files with top-level symbols.

        Returns:
            RepoMap with tree view and file information.
        """
        if self._repo_map is not None and not include_symbols:
            return self._repo_map

        if not self._files:
            self.discover_files()

        # Collect symbols per file if requested
        file_symbols: dict[str, list[str]] = {}
        if include_symbols:
            from attocode.integrations.context.codebase_ast import parse_file

            for f in self._files:
                if f.language in ("python", "javascript", "typescript"):
                    try:
                        ast = parse_file(f.path)
                        syms = ast.get_symbols()
                        if syms:
                            file_symbols[f.relative_path] = syms[:8]  # Cap at 8 symbols
                    except Exception:
                        pass

        # Build tree
        tree = self._build_tree(file_symbols=file_symbols)

        # Compute language stats
        languages: dict[str, int] = {}
        total_lines = 0
        for f in self._files:
            if f.language:
                languages[f.language] = languages.get(f.language, 0) + 1
            total_lines += f.line_count

        repo_map = RepoMap(
            tree=tree,
            files=self._files,
            total_files=len(self._files),
            total_lines=total_lines,
            languages=languages,
            symbols=file_symbols,
        )

        if not include_symbols:
            self._repo_map = repo_map

        return repo_map

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

    def _build_tree(
        self,
        max_depth: int = 4,
        file_symbols: dict[str, list[str]] | None = None,
    ) -> str:
        """Build a text tree view of the repository.

        Args:
            max_depth: Maximum directory nesting to display.
            file_symbols: Optional map of relative_path -> symbol names to show.
        """
        if not self._files:
            return "(no files discovered)"

        root = Path(self.root_dir)
        tree_dict: dict[str, Any] = {}
        # Track relative path per leaf for symbol lookup
        leaf_rel_paths: dict[str, str] = {}

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
            leaf_rel_paths[parts[-1]] = f.relative_path

        lines = [str(root.name) + "/"]
        self._format_tree_dict(tree_dict, lines, prefix="", file_symbols=file_symbols, leaf_rel_paths=leaf_rel_paths)
        return "\n".join(lines)

    def _format_tree_dict(
        self,
        d: dict[str, Any],
        lines: list[str],
        prefix: str,
        file_symbols: dict[str, list[str]] | None = None,
        leaf_rel_paths: dict[str, str] | None = None,
    ) -> None:
        """Recursively format tree dict into lines."""
        items = sorted(d.items(), key=lambda x: (x[1] is not None, x[0]))
        for i, (name, subtree) in enumerate(items):
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "
            suffix = "/" if subtree is not None else ""

            # Annotate leaf files with symbols
            sym_annotation = ""
            if file_symbols and subtree is None and leaf_rel_paths:
                rel_path = leaf_rel_paths.get(name, "")
                syms = file_symbols.get(rel_path, [])
                if syms:
                    sym_annotation = "  [" + ", ".join(syms) + "]"

            lines.append(f"{prefix}{connector}{name}{suffix}{sym_annotation}")

            if subtree is not None:
                next_prefix = prefix + ("    " if is_last else "│   ")
                self._format_tree_dict(subtree, lines, next_prefix, file_symbols, leaf_rel_paths)
