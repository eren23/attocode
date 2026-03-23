"""AST Service — singleton per project for structural code intelligence.

Wraps ``codebase_ast.parse_file`` / ``diff_file_ast`` and
``CodebaseContextManager.discover_files`` to provide:

* Full symbol index (definitions + cross-references)
* Incremental updates on file changes
* Impact analysis (transitive dependents of changed files)
* Conflict detection for parallel task allocation (swarm)
* Related file suggestions
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any

from attocode.integrations.context.codebase_ast import (
    FileAST,
    diff_file_ast,
    diff_imports,
    parse_file,
)
from attocode.integrations.context.codebase_context import (
    CodebaseContextManager,
)
from attocode.integrations.context.cross_references import (
    CrossRefIndex,
    SymbolLocation,
    SymbolRef,
)
from attocode.integrations.context.index_store import IndexStore, StoredFile

logger = logging.getLogger(__name__)

# Singleton registry: root_dir -> ASTService
_instances: dict[str, ASTService] = {}

# Default location for the persistent index
_INDEX_DIR = ".attocode/index"
_INDEX_DB = "symbols.db"


class ASTService:
    """Singleton per project.  NOT passed to prompts — used programmatically
    by the orchestrator and agent internals.

    Usage::

        svc = ASTService.get_instance("/path/to/repo")
        svc.initialize()              # full scan (once)
        svc.notify_file_changed(path) # after edits
        impact = svc.get_impact(["src/auth.py"])
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self, root_dir: str, *, store: IndexStore | None = None) -> None:
        self._root_dir = os.path.abspath(root_dir)
        self._context_mgr = CodebaseContextManager(root_dir=self._root_dir)
        self._index = CrossRefIndex()
        self._ast_cache: dict[str, FileAST] = {}   # rel_path -> FileAST
        self._initialized = False
        # Persistent index store
        if store is not None:
            self._store = store
        else:
            db_path = os.path.join(self._root_dir, _INDEX_DIR, _INDEX_DB)
            self._store = IndexStore(db_path=db_path)
        self._index.set_store(self._store)

    @classmethod
    def get_instance(cls, root_dir: str) -> ASTService:
        """Return (or create) the singleton for *root_dir*."""
        key = os.path.abspath(root_dir)
        if key not in _instances:
            _instances[key] = cls(key)
        return _instances[key]

    @classmethod
    def clear_instances(cls) -> None:
        """Reset all singletons (for testing)."""
        _instances.clear()

    @property
    def root_dir(self) -> str:
        return self._root_dir

    @property
    def index(self) -> CrossRefIndex:
        return self._index

    @property
    def initialized(self) -> bool:
        return self._initialized

    def _ensure_initialized(self) -> None:
        """Auto-initialize if not yet done.  Called by all query methods."""
        if not self._initialized:
            self.initialize()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self, *, force: bool = False) -> None:
        """Discover files, parse ASTs, build cross-ref index.

        When a persistent ``IndexStore`` is available and *force* is False,
        loads cached symbols/refs from SQLite and only re-parses files whose
        mtime has changed (incremental mode).  Otherwise does a full scan.
        """
        files = self._context_mgr.discover_files()
        self._index = CrossRefIndex()
        self._index.set_store(self._store)
        self._ast_cache.clear()

        # Supported languages
        _ts_langs: set[str] = set()
        try:
            from attocode.integrations.context.ts_parser import supported_languages
            _ts_langs = set(supported_languages())
        except ImportError:
            pass
        _supported = {"python", "javascript", "typescript", "shell"} | _ts_langs

        # Build mtime map for parseable files
        parseable: list[Any] = []
        mtime_map: dict[str, float] = {}
        for fi in files:
            lang = fi.language
            if lang == "shell":
                lang = "bash"
            if lang not in _supported:
                continue
            parseable.append(fi)
            try:
                mtime_map[fi.relative_path] = os.path.getmtime(fi.path)
            except OSError:
                mtime_map[fi.relative_path] = 0.0

        # Try incremental load from store
        last_scan = self._store.get_last_scan_time() if not force else None
        if last_scan is not None and not force:
            # Load cached data
            loaded = self._index.load_from_store()
            if loaded > 0:
                stale = self._store.get_stale_files(mtime_map)
                deleted = self._store.get_deleted_files(set(mtime_map.keys()))

                # Remove deleted files
                for d in deleted:
                    self._index.remove_file(d)

                # Re-parse stale files
                stale_set = set(stale)
                for fi in parseable:
                    rel = fi.relative_path
                    if rel in stale_set:
                        try:
                            ast = parse_file(fi.path)
                        except Exception:
                            continue
                        self._index.remove_file(rel)
                        self._ast_cache[rel] = ast
                        self._index_definitions(rel, ast)

                # Phase 2 for stale files only
                for rel in stale_set:
                    ast = self._ast_cache.get(rel)
                    if ast:
                        self._index_references(rel, ast)
                        self._index.persist_file(rel)
                        # Update stored file metadata
                        self._store.save_file(StoredFile(
                            path=rel,
                            mtime=mtime_map.get(rel, 0.0),
                            size=0,
                            language="",
                            line_count=ast.line_count if hasattr(ast, "line_count") else 0,
                            content_hash="",
                        ))

                # Reload dependency graph edges
                dep_graph = self._context_mgr.dependency_graph
                if dep_graph:
                    for src, targets in dep_graph.forward.items():
                        for tgt in targets:
                            self._index.add_file_dependency(src, tgt)

                self._initialized = True
                self._store.record_scan_time()
                logger.debug(
                    "ASTService incremental init: %d cached, %d stale, %d deleted",
                    loaded, len(stale), len(deleted),
                )
                return

        # Full scan fallback
        self._store.clear_all()
        for fi in parseable:
            try:
                ast = parse_file(fi.path)
            except Exception:
                continue
            rel = fi.relative_path
            self._ast_cache[rel] = ast
            self._index_definitions(rel, ast)

        # Phase 2: index references
        for rel, ast in self._ast_cache.items():
            self._index_references(rel, ast)

        # Persist all to store
        stored_files: list[StoredFile] = []
        for rel, ast in self._ast_cache.items():
            self._index.persist_file(rel)
            stored_files.append(StoredFile(
                path=rel,
                mtime=mtime_map.get(rel, 0.0),
                size=0,
                language="",
                line_count=ast.line_count if hasattr(ast, "line_count") else 0,
                content_hash="",
            ))
        if stored_files:
            self._store.save_files_batch(stored_files)

        # Copy dependency graph edges
        dep_graph = self._context_mgr.dependency_graph
        if dep_graph:
            edges: list[tuple[str, str]] = []
            for src, targets in dep_graph.forward.items():
                for tgt in targets:
                    self._index.add_file_dependency(src, tgt)
                    edges.append((src, tgt))
            if edges:
                self._store.save_dependencies_batch(edges)

        self._store.record_scan_time()
        self._initialized = True
        logger.debug(
            "ASTService full init: %d files, %d definitions",
            len(self._ast_cache),
            sum(len(v) for v in self._index.definitions.values()),
        )

    def force_reindex(self) -> None:
        """Force a full re-scan, ignoring cached data."""
        self.initialize(force=True)

    async def async_initialize(self, batch_size: int = 50) -> None:
        """Async version of initialize that parses files in batches.

        Uses ``asyncio.to_thread`` to avoid blocking the event loop
        on large repositories.  Files are parsed in batches of
        *batch_size* concurrently.
        """
        files = self._context_mgr.discover_files()
        self._index = CrossRefIndex()
        self._ast_cache.clear()

        _ts_langs: set[str] = set()
        try:
            from attocode.integrations.context.ts_parser import supported_languages
            _ts_langs = set(supported_languages())
        except ImportError:
            pass
        _supported = {"python", "javascript", "typescript"} | _ts_langs

        parseable = [fi for fi in files if fi.language in _supported]

        def _parse_one(fi_path: str) -> tuple[str, FileAST | None]:
            try:
                return fi_path, parse_file(fi_path)
            except Exception:
                return fi_path, None

        # Phase 1: Parse all files and index definitions
        for i in range(0, len(parseable), batch_size):
            batch = parseable[i:i + batch_size]
            tasks = [
                asyncio.to_thread(_parse_one, fi.path)
                for fi in batch
            ]
            results = await asyncio.gather(*tasks)
            for fi, (_, ast) in zip(batch, results, strict=False):
                if ast is not None:
                    rel = fi.relative_path
                    self._ast_cache[rel] = ast
                    self._index_definitions(rel, ast)

        # Phase 2: Index references (now known_symbols is complete)
        for rel, ast in self._ast_cache.items():
            self._index_references(rel, ast)

        dep_graph = self._context_mgr.dependency_graph
        if dep_graph:
            for src, targets in dep_graph.forward.items():
                for tgt in targets:
                    self._index.add_file_dependency(src, tgt)

        self._initialized = True
        logger.debug(
            "ASTService async_initialized: %d files, %d definitions",
            len(self._ast_cache),
            sum(len(v) for v in self._index.definitions.values()),
        )

    def notify_file_changed(self, path: str) -> list[Any]:
        """Incrementally update AST and index for a changed file.

        Returns a list of ``SymbolChange`` objects (from ``diff_file_ast``).
        """
        from attocode.integrations.context.codebase_ast import (
            SymbolChange,
        )

        rel = self._to_rel(path)
        abs_path = os.path.join(self._root_dir, rel)

        # Handle deletion
        if not Path(abs_path).exists():
            self._index.remove_file(rel)
            old_ast = self._ast_cache.pop(rel, None)
            if old_ast is None:
                return []
            changes: list[SymbolChange] = []
            for f in old_ast.functions:
                changes.append(SymbolChange(
                    kind="removed", symbol_name=f.name,
                    symbol_kind="function", file_path=rel, previous=f,
                ))
            for c in old_ast.classes:
                changes.append(SymbolChange(
                    kind="removed", symbol_name=c.name,
                    symbol_kind="class", file_path=rel, previous=c,
                ))
            return changes

        # Parse new content
        try:
            new_ast = parse_file(abs_path)
        except Exception:
            return []

        old_ast = self._ast_cache.get(rel)

        # Compute diffs
        if old_ast is not None:
            symbol_changes = diff_file_ast(old_ast, new_ast)
            _dep_changes = diff_imports(old_ast, new_ast)
        else:
            symbol_changes = []
            _dep_changes = None

        # Update index: remove old entries, re-index
        self._index.remove_file(rel)
        self._ast_cache[rel] = new_ast
        self._index_file(rel, new_ast)

        # Update dependency edges from dependency graph
        self._context_mgr.mark_file_dirty(path)
        self._context_mgr.update_dirty_files()
        dep_graph = self._context_mgr.dependency_graph
        if dep_graph:
            for tgt in dep_graph.forward.get(rel, set()):
                self._index.add_file_dependency(rel, tgt)

        # Persist changes to store
        self._index.persist_file(rel)
        try:
            mtime = os.path.getmtime(abs_path)
        except OSError:
            mtime = 0.0
        self._store.save_file(StoredFile(
            path=rel, mtime=mtime, size=0, language="",
            line_count=new_ast.line_count if hasattr(new_ast, "line_count") else 0,
            content_hash="",
        ))

        return symbol_changes

    def refresh(self) -> list[Any]:
        """Detect changed files (mtime) and update incrementally.

        Returns aggregated list of ``SymbolChange`` from all changed files.
        """
        all_changes: list[Any] = []
        for rel, cached_ast in list(self._ast_cache.items()):
            abs_path = os.path.join(self._root_dir, rel)
            if not Path(abs_path).exists():
                all_changes.extend(self.notify_file_changed(abs_path))
                continue
            try:
                new_ast = parse_file(abs_path)
            except Exception:
                continue
            changes = diff_file_ast(cached_ast, new_ast)
            if changes:
                all_changes.extend(self.notify_file_changed(abs_path))
        return all_changes

    # ------------------------------------------------------------------
    # Symbol queries
    # ------------------------------------------------------------------

    def get_file_symbols(self, path: str) -> list[SymbolLocation]:
        """Return all symbols defined in *path*."""
        self._ensure_initialized()
        rel = self._to_rel(path)
        qnames = self._index.file_symbols.get(rel, set())
        result: list[SymbolLocation] = []
        for qn in qnames:
            result.extend(self._index.definitions.get(qn, []))
        return result

    def find_symbol(self, name: str) -> list[SymbolLocation]:
        """Find definitions for *name* (exact or suffix match)."""
        self._ensure_initialized()
        return self._index.get_definitions(name)

    def search_symbol(
        self,
        name: str,
        *,
        limit: int = 50,
        kind_filter: str = "",
    ) -> list[tuple[SymbolLocation, float]]:
        """Enhanced symbol search with multi-strategy matching and scoring.

        Searches by exact match, bare name, case-insensitive, prefix,
        substring, and camelCase/snake_case token overlap.  Results are
        ranked by match quality and symbol importance.
        """
        self._ensure_initialized()
        return self._index.search_definitions(
            name, limit=limit, kind_filter=kind_filter,
        )

    def get_callers(self, symbol: str) -> list[SymbolRef]:
        """Return all call sites / references for *symbol*."""
        self._ensure_initialized()
        return self._index.get_references(symbol)

    def get_dependencies(self, path: str) -> set[str]:
        """Files that *path* imports from."""
        self._ensure_initialized()
        rel = self._to_rel(path)
        return self._index.get_dependencies(rel)

    def get_dependents(self, path: str) -> set[str]:
        """Files that import *path*."""
        self._ensure_initialized()
        rel = self._to_rel(path)
        return self._index.get_dependents(rel)

    def get_impact(self, changed: list[str]) -> set[str]:
        """Compute transitive impact set — all files affected by changes.

        Uses BFS on the reverse dependency graph starting from *changed*.
        """
        self._ensure_initialized()
        visited: set[str] = set()
        queue = [self._to_rel(p) for p in changed]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            for dep in self._index.get_dependents(current):
                if dep not in visited:
                    queue.append(dep)
        # Remove the seed files themselves (they're the *cause*, not the impact)
        for p in changed:
            visited.discard(self._to_rel(p))
        return visited

    # ------------------------------------------------------------------
    # LSP enrichment
    # ------------------------------------------------------------------

    def ingest_lsp_results(
        self,
        tool_name: str,
        file_path: str,
        results: list[Any],
    ) -> int:
        """Ingest LSP results into the cross-reference index.

        Called by LSPManager's on_result_callback. Converts LSP locations
        to SymbolLocation/SymbolRef with ``source="lsp"`` and merges them
        into the index.

        Returns the number of new entries added.
        """
        if not self._initialized:
            return 0

        rel = self._to_rel(file_path)
        definitions: list[SymbolLocation] = []
        references: list[SymbolRef] = []

        for item in results:
            # LSPLocation has .uri, .range (.start.line, .start.character)
            if not hasattr(item, "range"):
                continue

            item_file = file_path
            if hasattr(item, "uri"):
                uri = item.uri
                if uri.startswith("file://"):
                    item_file = uri[7:]
                item_rel = self._to_rel(item_file)
            else:
                item_rel = rel

            line = item.range.start.line + 1  # LSP is 0-indexed

            # Look up symbol name from AST cache at this line
            name, qname, kind = self._resolve_symbol_at_line(item_rel, line)
            if not name:
                # Can't determine symbol name — skip to avoid polluting index
                continue

            if tool_name == "definition":
                loc = SymbolLocation(
                    name=name,
                    qualified_name=qname,
                    kind=kind,
                    file_path=item_rel,
                    start_line=line,
                    end_line=item.range.end.line + 1,
                    source="lsp",
                )
                definitions.append(loc)
            elif tool_name == "references":
                ref = SymbolRef(
                    symbol_name=name,
                    ref_kind="call",
                    file_path=item_rel,
                    line=line,
                    source="lsp",
                )
                references.append(ref)

        if definitions or references:
            return self._index.merge_lsp_results(rel, definitions, references)
        return 0

    # ------------------------------------------------------------------
    # Task allocation (swarm-specific)
    # ------------------------------------------------------------------

    def detect_conflicts(
        self,
        a_files: list[str],
        b_files: list[str],
    ) -> list[dict[str, Any]]:
        """Detect potential conflicts between two parallel task file sets.

        Returns a list of conflict descriptors::

            [{"file": "src/auth.py", "kind": "direct", "symbols": [...]}]

        Conflict kinds:
        - ``direct``: both tasks touch the same file
        - ``symbol``: tasks modify different files but share a symbol
        - ``dependency``: one task's output file is imported by the other's
        """
        self._ensure_initialized()
        a_set = {self._to_rel(p) for p in a_files}
        b_set = {self._to_rel(p) for p in b_files}
        conflicts: list[dict[str, Any]] = []

        # Direct overlap
        overlap = a_set & b_set
        for f in sorted(overlap):
            syms = sorted(self._index.file_symbols.get(f, set()))
            conflicts.append({
                "file": f,
                "kind": "direct",
                "symbols": syms,
            })

        # Dependency conflicts: a_file imports from b_file or vice versa
        for af in a_set - overlap:
            a_deps = self._index.get_dependencies(af)
            for bf in b_set - overlap:
                if bf in a_deps:
                    conflicts.append({
                        "file": af,
                        "depends_on": bf,
                        "kind": "dependency",
                    })
                b_deps = self._index.get_dependencies(bf)
                if af in b_deps:
                    conflicts.append({
                        "file": bf,
                        "depends_on": af,
                        "kind": "dependency",
                    })

        # Symbol-level overlap (same symbol modified in different files)
        a_symbols: set[str] = set()
        for af in a_set:
            a_symbols.update(self._index.file_symbols.get(af, set()))
        b_symbols: set[str] = set()
        for bf in b_set:
            b_symbols.update(self._index.file_symbols.get(bf, set()))
        shared_symbols = a_symbols & b_symbols
        if shared_symbols and not overlap:
            # Only report if it's NOT already a direct overlap
            conflicts.append({
                "kind": "symbol",
                "shared_symbols": sorted(shared_symbols),
            })

        return conflicts

    def suggest_related_files(self, target: list[str]) -> list[str]:
        """Suggest files related to *target* that a worker may also need.

        Uses the dependency graph (imports + imported-by) up to 1 hop.
        """
        self._ensure_initialized()
        related: set[str] = set()
        target_set = {self._to_rel(p) for p in target}

        for t in target_set:
            related.update(self._index.get_dependencies(t))
            related.update(self._index.get_dependents(t))

        # Remove the target files themselves
        related -= target_set
        return sorted(related)

    # ------------------------------------------------------------------
    def to_rel(self, path: str) -> str:
        """Normalize *path* to a relative path from root (public API)."""
        return self._to_rel(path)

    def get_symbol_names(self, file_path: str) -> list[str]:
        """Return all symbol names defined in the cached AST for *file_path*."""
        rel = self._to_rel(file_path)
        ast = self._ast_cache.get(rel)
        if ast is None:
            return []
        return ast.get_symbols()

    # Internals
    # ------------------------------------------------------------------

    def _resolve_symbol_at_line(
        self, rel_path: str, line: int,
    ) -> tuple[str, str, str]:
        """Find the symbol name at a given line from the AST cache.

        Returns (name, qualified_name, kind) or ("", "", "") if not found.
        """
        ast = self._ast_cache.get(rel_path)
        if ast is None:
            return ("", "", "")

        # Check functions
        for func in ast.functions:
            if func.start_line <= line <= func.end_line:
                return (func.name, func.name, "function")

        # Check classes and their methods
        for cls in ast.classes:
            if cls.start_line <= line <= cls.end_line:
                for method in cls.methods:
                    if method.start_line <= line <= method.end_line:
                        return (method.name, f"{cls.name}.{method.name}", "method")
                return (cls.name, cls.name, "class")

        return ("", "", "")

    def _to_rel(self, path: str) -> str:
        """Normalize *path* to a relative path from root."""
        if os.path.isabs(path):
            try:
                return os.path.relpath(path, self._root_dir)
            except ValueError:
                return path
        # Already relative — treat as relative to root_dir
        return path

    def _index_file(self, rel_path: str, ast: FileAST) -> None:
        """Index all symbols and references from a parsed FileAST.

        Convenience wrapper that calls both phases.  Used by
        ``notify_file_changed`` for incremental updates where most
        symbols are already known.
        """
        self._index_definitions(rel_path, ast)
        self._index_references(rel_path, ast)

    def _index_definitions(self, rel_path: str, ast: FileAST) -> None:
        """Phase 1: Index all *definitions* (functions, classes, methods)."""
        # Top-level functions
        for func in ast.functions:
            loc = SymbolLocation(
                name=func.name,
                qualified_name=func.name,
                kind="function",
                file_path=rel_path,
                start_line=func.start_line,
                end_line=func.end_line,
            )
            self._index.add_definition(loc)

        # Classes and their methods
        for cls in ast.classes:
            cls_loc = SymbolLocation(
                name=cls.name,
                qualified_name=cls.name,
                kind="class",
                file_path=rel_path,
                start_line=cls.start_line,
                end_line=cls.end_line,
            )
            self._index.add_definition(cls_loc)

            for method in cls.methods:
                method_loc = SymbolLocation(
                    name=method.name,
                    qualified_name=f"{cls.name}.{method.name}",
                    kind="method",
                    file_path=rel_path,
                    start_line=method.start_line,
                    end_line=method.end_line,
                )
                self._index.add_definition(method_loc)

        # Top-level variables/constants
        for var_name in ast.top_level_vars:
            var_loc = SymbolLocation(
                name=var_name,
                qualified_name=var_name,
                kind="variable",
                file_path=rel_path,
                start_line=0,
                end_line=0,
            )
            self._index.add_definition(var_loc)

    def _index_references(self, rel_path: str, ast: FileAST) -> None:
        """Phase 2: Index import references and call-site references.

        Should be called after all definitions are indexed so that
        ``known_symbols`` is complete.
        """
        # Import references
        for imp in ast.imports:
            for name in imp.names:
                ref = SymbolRef(
                    symbol_name=name,
                    ref_kind="import",
                    file_path=rel_path,
                    line=imp.line,
                )
                self._index.add_reference(ref)

        # Extract call-site references from source (lightweight regex scan)
        abs_path = os.path.join(self._root_dir, rel_path)
        try:
            content = Path(abs_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return

        # Collect known symbol names for targeted scanning
        known_symbols: set[str] = set()
        for qname_list in self._index.definitions.values():
            for loc in qname_list:
                known_symbols.add(loc.name)

        if not known_symbols:
            return

        # Build a regex pattern for call sites: symbol_name(
        # Only scan for symbols that are actually defined somewhere.
        # Skip comment lines and string literals to reduce false positives.
        in_multiline_string = False
        for i, line in enumerate(content.split("\n"), 1):
            stripped = line.lstrip()

            # Track triple-quote multiline strings
            triple_count = line.count('"""') + line.count("'''")
            if in_multiline_string:
                if triple_count % 2 == 1:
                    in_multiline_string = False
                continue
            if triple_count % 2 == 1:
                in_multiline_string = True
                continue

            # Skip single-line comments
            if stripped.startswith("#"):
                continue

            # Strip inline comments and string literals for matching
            # Remove quoted strings to avoid matching inside them
            clean_line = re.sub(r'(["\'])(?:(?!\1).)*\1', '""', line)

            # Find function/method calls: name(
            for m in re.finditer(r"\b(\w+)\s*\(", clean_line):
                name = m.group(1)
                if name in known_symbols and name not in ("if", "for", "while", "return", "print"):
                    ref = SymbolRef(
                        symbol_name=name,
                        ref_kind="call",
                        file_path=rel_path,
                        line=i,
                    )
                    self._index.add_reference(ref)

            # Find attribute access: obj.method(
            for m in re.finditer(r"\b\w+\.(\w+)\s*\(", clean_line):
                attr_name = m.group(1)
                if attr_name in known_symbols:
                    ref = SymbolRef(
                        symbol_name=attr_name,
                        ref_kind="attribute",
                        file_path=rel_path,
                        line=i,
                    )
                    self._index.add_reference(ref)
