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

# File extensions to skip (non-source, binary, generated)
SKIP_EXTENSIONS = {
    # Compiled / bytecode
    ".pyc", ".pyo", ".class", ".o", ".obj", ".so", ".dylib", ".dll",
    ".a", ".lib", ".exe", ".wasm",
    # Archives
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".rar", ".7z", ".jar", ".war",
    # Media
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".webm",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    # Data / DB
    ".db", ".sqlite", ".sqlite3",
    ".parquet", ".feather", ".hdf5", ".h5",
    # Lock files (large, generated)
    ".lock",
    # Maps
    ".map",
    # Certificates
    ".pem", ".crt", ".key", ".p12",
}

# Filenames to skip (exact match)
SKIP_FILENAMES = {
    ".DS_Store", "Thumbs.db", ".gitkeep", ".npmrc",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Pipfile.lock", "poetry.lock", "uv.lock",
    "composer.lock", "Gemfile.lock", "Cargo.lock",
    "go.sum",
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

    Supports incremental updates: after file edits, call
    ``mark_file_dirty()`` then ``update_dirty_files()`` to
    re-parse only changed files instead of a full ``discover_files()``.
    """

    root_dir: str
    max_files: int = 2000
    max_context_tokens: int = 8000
    ignore_patterns: set[str] = field(default_factory=lambda: set(DEFAULT_IGNORES))
    _files: list[FileInfo] = field(default_factory=list, repr=False)
    _repo_map: RepoMap | None = field(default=None, repr=False)
    _dep_graph: DependencyGraph | None = field(default=None, repr=False)
    _file_mtimes: dict[str, float] = field(default_factory=dict, repr=False)
    _dirty_files: set[str] = field(default_factory=set, repr=False)
    _ast_cache: dict[str, Any] = field(default_factory=dict, repr=False)

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
                if filename in SKIP_FILENAMES:
                    continue
                ext = Path(filename).suffix.lower()
                if ext in SKIP_EXTENSIONS:
                    continue

                full_path = os.path.join(dirpath, filename)
                try:
                    rel_path = os.path.relpath(full_path, root)
                except ValueError:
                    continue

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

    def get_repo_map(
        self,
        *,
        include_symbols: bool = False,
        max_tokens: int | None = None,
    ) -> RepoMap:
        """Generate a repository map.

        Args:
            include_symbols: If True, annotate files with top-level symbols.
            max_tokens: When set, produce a token-budgeted tree using
                importance tiers.  Files are partitioned into:
                - **Tier 1** (importance >= 0.7): shown WITH symbols (up to 5)
                - **Tier 2** (importance >= 0.4): shown WITHOUT symbols
                - **Tier 3** (below 0.4): collapsed as ``... +N files`` per dir
                When ``None`` (default), the full unbounded tree is returned
                (backward-compatible).

        Returns:
            RepoMap with tree view and file information.
        """
        if self._repo_map is not None and not include_symbols and max_tokens is None:
            return self._repo_map

        if not self._files:
            self.discover_files()

        # Collect symbols per file if requested
        file_symbols: dict[str, list[str]] = {}
        if include_symbols:
            file_symbols = self._collect_symbols()

        # Build tree — budgeted or full
        if max_tokens is not None:
            tree, included_symbols = self._build_budgeted_tree(
                max_tokens, file_symbols,
            )
            # Narrow symbols dict to only included files
            file_symbols = included_symbols
        else:
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

        if not include_symbols and max_tokens is None:
            self._repo_map = repo_map

        return repo_map

    def get_preseed_map(self, max_tokens: int = 6000) -> RepoMap:
        """Convenience wrapper for preseed injection.

        Returns a token-budgeted repo map suitable for injecting into
        the initial system context without blowing up the context window.

        Args:
            max_tokens: Token budget for the tree + symbols output.
        """
        return self.get_repo_map(include_symbols=True, max_tokens=max_tokens)

    def _collect_symbols(self) -> dict[str, list[str]]:
        """Collect top-level symbols for all parseable files.

        Prefers the ASTService cache (if available and initialized)
        over re-parsing each file.
        """
        file_symbols: dict[str, list[str]] = {}

        # Try ASTService cache first
        ast_cache: dict[str, Any] | None = None
        try:
            from attocode.integrations.context.ast_service import ASTService
            svc = ASTService.get_instance(self.root_dir)
            if svc.initialized:
                ast_cache = svc._ast_cache
        except Exception:
            pass

        from attocode.integrations.context.codebase_ast import parse_file as _parse_file

        for f in self._files:
            if f.language not in ("python", "javascript", "typescript"):
                continue
            try:
                # Use cached AST when available
                if ast_cache and f.relative_path in ast_cache:
                    ast = ast_cache[f.relative_path]
                else:
                    ast = _parse_file(f.path)
                syms = ast.get_symbols()
                if syms:
                    file_symbols[f.relative_path] = syms[:8]  # Cap at 8 symbols
            except Exception:
                pass
        return file_symbols

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

    # --- Incremental update API ---

    def mark_file_dirty(self, file_path: str) -> None:
        """Mark a file as needing re-analysis after edit.

        Args:
            file_path: Absolute or relative path of the edited file.
        """
        # Normalize to relative path
        try:
            rel = os.path.relpath(file_path, self.root_dir)
        except ValueError:
            rel = file_path
        self._dirty_files.add(rel)

    def invalidate_file(self, file_path: str) -> None:
        """Remove cached AST and analysis for a specific file.

        Args:
            file_path: Path of the file to invalidate.
        """
        try:
            rel = os.path.relpath(file_path, self.root_dir)
        except ValueError:
            rel = file_path
        self._ast_cache.pop(rel, None)
        self._ast_cache.pop(file_path, None)
        # Also invalidate repo map cache since it may reference stale symbols
        self._repo_map = None

    def update_dirty_files(self) -> list[Any]:
        """Re-parse only dirty files and update the dependency graph incrementally.

        Returns:
            List of FileChangeResult objects describing what changed.
        """
        if not self._dirty_files:
            return []

        from attocode.integrations.context.codebase_ast import (
            DependencyChanges,
            FileChangeResult,
            SymbolChange,
            diff_file_ast,
            diff_imports,
            parse_file,
        )

        results: list[Any] = []
        file_index: dict[str, str] = {}
        for f in self._files:
            normalized = f.relative_path.replace(os.sep, "/")
            file_index[normalized] = f.relative_path

        for rel_path in list(self._dirty_files):
            # Find absolute path
            abs_path = os.path.join(self.root_dir, rel_path)

            # Handle deleted files
            if not Path(abs_path).exists():
                old_ast = self._ast_cache.pop(rel_path, None)
                # Emit removal changes for all symbols in old AST
                if old_ast is not None:
                    for func in old_ast.functions:
                        results.append(FileChangeResult(
                            file_path=rel_path,
                            symbol_changes=[SymbolChange(
                                kind="removed", symbol_name=func.name,
                                symbol_kind="function", file_path=rel_path,
                                previous=func,
                            )],
                            dependency_changes=DependencyChanges(),
                            was_incremental=True,
                        ))
                    for cls in old_ast.classes:
                        results.append(FileChangeResult(
                            file_path=rel_path,
                            symbol_changes=[SymbolChange(
                                kind="removed", symbol_name=cls.name,
                                symbol_kind="class", file_path=rel_path,
                                previous=cls,
                            )],
                            dependency_changes=DependencyChanges(),
                            was_incremental=True,
                        ))
                # Remove dependency edges
                if self._dep_graph is not None:
                    old_imports = self._dep_graph.forward.pop(rel_path, set())
                    for target in old_imports:
                        rev = self._dep_graph.reverse.get(target)
                        if rev:
                            rev.discard(rel_path)
                            if not rev:
                                del self._dep_graph.reverse[target]
                    # Also remove as a reverse dep target
                    self._dep_graph.reverse.pop(rel_path, None)
                self._file_mtimes.pop(rel_path, None)
                continue

            # Get old AST from cache
            old_ast = self._ast_cache.get(rel_path)

            # Parse new content
            try:
                new_ast = parse_file(abs_path)
            except Exception:
                continue

            # Compute diffs
            if old_ast is not None:
                symbol_changes = diff_file_ast(old_ast, new_ast)
                dep_changes = diff_imports(old_ast, new_ast)
            else:
                symbol_changes = []
                dep_changes = DependencyChanges()

            # Update AST cache
            self._ast_cache[rel_path] = new_ast

            # Update dependency graph incrementally
            if self._dep_graph is not None and dep_changes:
                # Remove old edges for this file
                old_imports = self._dep_graph.forward.pop(rel_path, set())
                for target in old_imports:
                    rev = self._dep_graph.reverse.get(target)
                    if rev:
                        rev.discard(rel_path)
                        if not rev:
                            del self._dep_graph.reverse[target]

                # Add new edges
                for imp in new_ast.imports:
                    if new_ast.language == "python":
                        target = _resolve_python_import(
                            imp.module, rel_path, file_index
                        )
                    else:
                        target = _resolve_js_import(
                            imp.module, rel_path, file_index
                        )
                    if target is not None and target != rel_path:
                        self._dep_graph.add_edge(rel_path, target)

            # Update file mtime
            try:
                self._file_mtimes[rel_path] = os.path.getmtime(abs_path)
            except OSError:
                pass

            results.append(FileChangeResult(
                file_path=rel_path,
                symbol_changes=symbol_changes,
                dependency_changes=dep_changes,
                was_incremental=True,
            ))

        # Invalidate repo map (symbols may have changed)
        self._repo_map = None
        self._dirty_files.clear()

        return results

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

    # ------ Budgeted tree helpers ------

    def _build_budgeted_tree(
        self,
        max_tokens: int,
        file_symbols: dict[str, list[str]],
    ) -> tuple[str, dict[str, list[str]]]:
        """Build a token-budgeted tree using importance tiers.

        Files are partitioned into three tiers based on importance:
        - **Tier 1** (>= 0.7): appear in tree WITH up to 5 symbols each
        - **Tier 2** (>= 0.4): appear in tree WITHOUT symbols
        - **Tier 3** (< 0.4): collapsed as ``... +N files`` per directory

        The builder tracks estimated token count and stops adding entries
        once *max_tokens* is reached.

        Returns:
            ``(tree_text, included_symbols)`` — the rendered tree string
            and the symbols dict narrowed to only Tier 1 files.
        """
        from attocode.integrations.utilities.token_estimate import estimate_tokens

        tier1: list[FileInfo] = []
        tier2: list[FileInfo] = []
        tier3: list[FileInfo] = []

        for f in self._files:
            if f.importance >= 0.7:
                tier1.append(f)
            elif f.importance >= 0.4:
                tier2.append(f)
            else:
                tier3.append(f)

        # Build included set (Tier 1 + Tier 2 files shown individually)
        included_set = {f.relative_path for f in tier1} | {f.relative_path for f in tier2}

        # Narrow symbols to Tier 1 only, capped at 5 per file
        included_symbols: dict[str, list[str]] = {}
        for f in tier1:
            syms = file_symbols.get(f.relative_path, [])
            if syms:
                included_symbols[f.relative_path] = syms[:5]

        # Count omitted files per directory for collapse annotations
        omitted_per_dir = self._count_omitted_per_dir(
            [f.relative_path for f in self._files], included_set,
        )

        # Build tree dict from included files
        root = Path(self.root_dir)
        tree_dict: dict[str, Any] = {}
        leaf_rel_paths: dict[str, str] = {}
        max_depth = 4

        for f in tier1 + tier2:
            parts = Path(f.relative_path).parts
            if len(parts) > max_depth + 1:
                parts = parts[:max_depth] + ("...",)
            current = tree_dict
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = None
            leaf_rel_paths[parts[-1]] = f.relative_path

        # Inject collapse markers (``... +N files``) into directory nodes
        for dir_path, count in sorted(omitted_per_dir.items()):
            parts = Path(dir_path).parts if dir_path != "." else ()
            current = tree_dict
            for part in parts:
                if part not in current:
                    current[part] = {}
                current = current[part]
                if current is None:
                    break
            if isinstance(current, dict):
                current[f"... +{count} files"] = None

        lines = [str(root.name) + "/"]
        self._format_tree_dict(
            tree_dict, lines, prefix="",
            file_symbols=included_symbols, leaf_rel_paths=leaf_rel_paths,
        )

        tree_text = "\n".join(lines)

        # Truncate to budget if still over
        tokens = estimate_tokens(tree_text)
        if tokens > max_tokens:
            # Progressively trim lines from the end (least important)
            while lines and estimate_tokens("\n".join(lines)) > max_tokens:
                lines.pop()
            if lines:
                lines.append(f"... (truncated, {len(self._files)} total files)")
            tree_text = "\n".join(lines)

        return tree_text, included_symbols

    @staticmethod
    def _count_omitted_per_dir(
        all_paths: list[str],
        included_set: set[str],
    ) -> dict[str, int]:
        """Count how many files per directory were omitted (Tier 3).

        Returns:
            ``{dir_relative_path: count}`` for directories with omitted files.
        """
        counts: dict[str, int] = {}
        for path in all_paths:
            if path not in included_set:
                parent = str(Path(path).parent)
                counts[parent] = counts.get(parent, 0) + 1
        return counts

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
