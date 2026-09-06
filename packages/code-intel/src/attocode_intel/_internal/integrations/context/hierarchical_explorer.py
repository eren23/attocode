"""Hierarchical BFS codebase explorer.

Provides drill-down navigation through the repository, showing one
directory level at a time with statistics and importance scoring.
This avoids overwhelming the LLM context with a flat repo map on
large codebases (1000+ files).
"""

from __future__ import annotations

import os
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DirectoryNode:
    """A directory in the explorer view."""

    name: str
    path: str
    file_count: int = 0
    total_lines: int = 0
    languages: dict[str, int] = field(default_factory=dict)
    subdirs: int = 0


@dataclass(slots=True)
class FileNode:
    """A file in the explorer view."""

    name: str
    path: str
    relative_path: str
    importance: float = 0.0
    line_count: int = 0
    language: str = ""
    top_symbols: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExplorerResult:
    """Result of exploring a directory."""

    path: str
    breadcrumbs: list[str]
    total_files: int
    total_lines: int
    directories: list[DirectoryNode]
    files: list[FileNode]
    omitted_files: int = 0
    omitted_dirs: int = 0


class HierarchicalExplorer:
    """Interactive BFS codebase explorer with drill-down navigation.

    Exactly ONE directory level deep per call, with predictable
    token cost (~500-2000 tokens per result).

    Usage::

        explorer = HierarchicalExplorer(codebase_context)

        # Top-level overview
        result = explorer.explore()

        # Drill into a directory
        result = explorer.explore("src/attocode/integrations")

        # With filters
        result = explorer.explore("src", max_items=50, importance_threshold=0.3)
    """

    def __init__(self, context_manager: Any, ast_service: Any = None) -> None:
        self._ctx = context_manager
        self._ast = ast_service
        self._cache: OrderedDict[str, ExplorerResult] = OrderedDict()
        self._max_cache = 100

    def explore(
        self,
        path: str = "",
        *,
        max_items: int = 30,
        importance_threshold: float = 0.3,
    ) -> ExplorerResult:
        """Explore one level of a directory.

        Args:
            path: Relative path to explore ("" for root).
            max_items: Maximum items (dirs + files) to return.
            importance_threshold: Minimum importance for files to be shown.

        Returns:
            ExplorerResult with dirs, files, and breadcrumbs.
        """
        cache_key = f"{path}|{max_items}|{importance_threshold}"
        if cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

        self._ctx._ensure_fresh()
        files = self._ctx._files

        # Normalize path
        path = path.strip("/").rstrip("/") if path else ""

        # Filter files to those in this directory (direct children or descendants)
        if path:
            prefix = path + "/"
            relevant = [f for f in files if f.relative_path.startswith(prefix)]
        else:
            relevant = list(files)

        if not relevant and path:
            # Try exact match (file, not directory)
            exact = [f for f in files if f.relative_path == path]
            if exact:
                return self._file_detail(exact[0], path)

        # Group into direct children (dirs and files at this level)
        dir_stats: dict[str, _DirAccum] = {}
        direct_files: list[Any] = []
        _depth = path.count("/") + 1 if path else 0

        for f in relevant:
            rel = f.relative_path
            child = rel[len(path) + 1:] if path else rel

            parts = child.split("/")
            if len(parts) == 1:
                # Direct file child
                direct_files.append(f)
            else:
                # In a subdirectory
                subdir_name = parts[0]
                subdir_path = f"{path}/{subdir_name}" if path else subdir_name
                if subdir_path not in dir_stats:
                    dir_stats[subdir_path] = _DirAccum(name=subdir_name, path=subdir_path)
                acc = dir_stats[subdir_path]
                acc.file_count += 1
                acc.total_lines += f.line_count
                if f.language:
                    acc.languages[f.language] = acc.languages.get(f.language, 0) + 1
                # Count unique immediate subdirectories within this subdir
                if len(parts) > 2:
                    acc.seen_subdirs.add(parts[1])

        # Build directory nodes
        directories: list[DirectoryNode] = []
        for _sp, acc in sorted(dir_stats.items()):
            directories.append(DirectoryNode(
                name=acc.name,
                path=acc.path,
                file_count=acc.file_count,
                total_lines=acc.total_lines,
                languages=dict(acc.languages),
                subdirs=len(acc.seen_subdirs),
            ))

        # Build file nodes (filtered by importance threshold)
        file_nodes: list[FileNode] = []
        for f in sorted(direct_files, key=lambda x: x.importance, reverse=True):
            if f.importance < importance_threshold and len(file_nodes) >= 5:
                break
            tags: list[str] = []
            if f.is_config:
                tags.append("config")
            if f.is_test:
                tags.append("test")
            name = os.path.basename(f.relative_path).lower()
            if name in ("main.py", "main.ts", "app.py", "cli.py", "__init__.py",
                         "index.ts", "index.js"):
                tags.append("entry")

            # Get top symbols if AST service is available
            top_syms: list[str] = []
            if self._ast and self._ast.initialized:
                cached = self._ast._ast_cache.get(f.relative_path)
                if cached:
                    top_syms = cached.get_symbols()[:5]

            file_nodes.append(FileNode(
                name=os.path.basename(f.relative_path),
                path=f.path,
                relative_path=f.relative_path,
                importance=round(f.importance, 2),
                line_count=f.line_count,
                language=f.language,
                top_symbols=top_syms,
                tags=tags,
            ))

        # Enforce max_items limit
        total_items = len(directories) + len(file_nodes)
        omitted_dir_count = 0
        if total_items > max_items:
            # Prioritize directories, then high-importance files
            dir_budget = min(len(directories), max_items // 2)
            file_budget = max_items - dir_budget
            omitted_dir_count = max(0, len(directories) - dir_budget)
            directories = directories[:dir_budget]
            file_nodes = file_nodes[:file_budget]

        omitted = len(direct_files) - len(file_nodes)

        # Build breadcrumbs
        breadcrumbs = ["(root)"]
        if path:
            parts = path.split("/")
            for i in range(len(parts)):
                breadcrumbs.append("/".join(parts[:i + 1]))

        result = ExplorerResult(
            path=path or "(root)",
            breadcrumbs=breadcrumbs,
            total_files=len(relevant),
            total_lines=sum(f.line_count for f in relevant),
            directories=directories,
            files=file_nodes,
            omitted_files=max(0, omitted),
            omitted_dirs=omitted_dir_count,
        )

        # Cache with LRU eviction
        self._cache[cache_key] = result
        if len(self._cache) > self._max_cache:
            self._cache.popitem(last=False)

        return result

    def _file_detail(self, file_info: Any, path: str) -> ExplorerResult:
        """Return a single file as an explorer result."""
        tags: list[str] = []
        if file_info.is_config:
            tags.append("config")
        if file_info.is_test:
            tags.append("test")
        fn = FileNode(
            name=os.path.basename(file_info.relative_path),
            path=file_info.path,
            relative_path=file_info.relative_path,
            importance=round(file_info.importance, 2),
            line_count=file_info.line_count,
            language=file_info.language,
            tags=tags,
        )
        return ExplorerResult(
            path=path,
            breadcrumbs=["(root)"] + path.split("/"),
            total_files=1,
            total_lines=file_info.line_count,
            directories=[],
            files=[fn],
        )

    def invalidate(self, path: str = "") -> None:
        """Invalidate cached results for a path or all paths."""
        if not path:
            self._cache.clear()
            return
        keys_to_remove = [k for k in self._cache if k.startswith(path + "|") or k.startswith(path + "/")]
        for k in keys_to_remove:
            del self._cache[k]

    def format_result(self, result: ExplorerResult) -> str:
        """Format an ExplorerResult as a human-readable string."""
        lines: list[str] = []

        # Header
        lines.append(f"{result.path} ({result.total_files} files, {result.total_lines:,} lines)")
        lines.append(f"Breadcrumb: {' > '.join(result.breadcrumbs)}")
        lines.append("")

        # Directories
        for d in result.directories:
            lang_str = ""
            if d.languages:
                top_langs = sorted(d.languages.items(), key=lambda x: -x[1])[:3]
                lang_str = f"  [{', '.join(line for line, _ in top_langs)}]"
            lines.append(
                f"  [dir] {d.name}/  "
                f"{d.file_count} files  {d.total_lines:,} lines{lang_str}"
            )

        # Files
        for f in result.files:
            tags_str = f"  [{', '.join(f.tags)}]" if f.tags else ""
            syms_str = ""
            if f.top_symbols:
                syms_str = f"  [{', '.join(f.top_symbols)}]"
            lines.append(
                f"  [file] {f.name}  "
                f"{f.line_count}L  imp={f.importance}{tags_str}{syms_str}"
            )

        if result.omitted_files > 0 or result.omitted_dirs > 0:
            parts = []
            if result.omitted_files > 0:
                parts.append(f"{result.omitted_files} more files")
            if result.omitted_dirs > 0:
                parts.append(f"{result.omitted_dirs} more directories")
            lines.append(f"  ... +{', '.join(parts)}")

        return "\n".join(lines)


@dataclass(slots=True)
class _DirAccum:
    """Accumulator for directory statistics."""

    name: str
    path: str
    file_count: int = 0
    total_lines: int = 0
    languages: dict[str, int] = field(default_factory=dict)
    seen_subdirs: set[str] = field(default_factory=set)
