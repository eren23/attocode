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

import logging
import os
import re
from pathlib import Path
from typing import Any

from attocode.integrations.context.codebase_ast import (
    ClassDef,
    FileAST,
    FunctionDef,
    ImportDef,
    diff_file_ast,
    diff_imports,
    parse_file,
)
from attocode.integrations.context.codebase_context import (
    CodebaseContextManager,
    DependencyGraph,
)
from attocode.integrations.context.cross_references import (
    CrossRefIndex,
    SymbolLocation,
    SymbolRef,
)

logger = logging.getLogger(__name__)

# Singleton registry: root_dir -> ASTService
_instances: dict[str, "ASTService"] = {}


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

    def __init__(self, root_dir: str) -> None:
        self._root_dir = os.path.abspath(root_dir)
        self._context_mgr = CodebaseContextManager(root_dir=self._root_dir)
        self._index = CrossRefIndex()
        self._ast_cache: dict[str, FileAST] = {}   # rel_path -> FileAST
        self._initialized = False

    @classmethod
    def get_instance(cls, root_dir: str) -> "ASTService":
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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Full scan: discover files, parse ASTs, build cross-ref index."""
        files = self._context_mgr.discover_files()
        self._index = CrossRefIndex()
        self._ast_cache.clear()

        for fi in files:
            if fi.language not in ("python", "javascript", "typescript"):
                continue
            try:
                ast = parse_file(fi.path)
            except Exception:
                continue
            rel = fi.relative_path
            self._ast_cache[rel] = ast
            self._index_file(rel, ast)

        # Copy dependency graph edges into the cross-ref index
        dep_graph = self._context_mgr.dependency_graph
        if dep_graph:
            for src, targets in dep_graph.forward.items():
                for tgt in targets:
                    self._index.add_file_dependency(src, tgt)

        self._initialized = True
        logger.debug(
            "ASTService initialized: %d files, %d definitions",
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
            dep_changes = diff_imports(old_ast, new_ast)
        else:
            symbol_changes = []
            dep_changes = None

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
        rel = self._to_rel(path)
        qnames = self._index.file_symbols.get(rel, set())
        result: list[SymbolLocation] = []
        for qn in qnames:
            result.extend(self._index.definitions.get(qn, []))
        return result

    def find_symbol(self, name: str) -> list[SymbolLocation]:
        """Find definitions for *name* (exact or suffix match)."""
        return self._index.get_definitions(name)

    def get_callers(self, symbol: str) -> list[SymbolRef]:
        """Return all call sites / references for *symbol*."""
        return self._index.get_references(symbol)

    def get_dependencies(self, path: str) -> set[str]:
        """Files that *path* imports from."""
        rel = self._to_rel(path)
        return self._index.get_dependencies(rel)

    def get_dependents(self, path: str) -> set[str]:
        """Files that import *path*."""
        rel = self._to_rel(path)
        return self._index.get_dependents(rel)

    def get_impact(self, changed: list[str]) -> set[str]:
        """Compute transitive impact set — all files affected by changes.

        Uses BFS on the reverse dependency graph starting from *changed*.
        """
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
        related: set[str] = set()
        target_set = {self._to_rel(p) for p in target}

        for t in target_set:
            related.update(self._index.get_dependencies(t))
            related.update(self._index.get_dependents(t))

        # Remove the target files themselves
        related -= target_set
        return sorted(related)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

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
        """Index all symbols and references from a parsed FileAST."""
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
        # Only scan for symbols that are actually defined somewhere
        for i, line in enumerate(content.split("\n"), 1):
            # Find function/method calls: name(
            for m in re.finditer(r"\b(\w+)\s*\(", line):
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
            for m in re.finditer(r"\b\w+\.(\w+)\s*\(", line):
                attr_name = m.group(1)
                if attr_name in known_symbols:
                    ref = SymbolRef(
                        symbol_name=attr_name,
                        ref_kind="attribute",
                        file_path=rel_path,
                        line=i,
                    )
                    self._index.add_reference(ref)
