"""Unified code intelligence service.

Used by both the MCP server (server.py) and HTTP API (api/app.py) as a
single source of truth for all 27 tool operations.
"""

from __future__ import annotations

import logging
import os
import threading
from collections import Counter, deque
from pathlib import Path

from attocode.code_intel.config import CodeIntelConfig

logger = logging.getLogger(__name__)

# Registry of service instances by project_dir
_instances: dict[str, CodeIntelService] = {}
_instances_lock = threading.Lock()


class CodeIntelService:
    """Unified code intelligence service wrapping all tool operations."""

    def __init__(self, project_dir: str, config: CodeIntelConfig | None = None) -> None:
        self._project_dir = os.path.abspath(project_dir)
        self._config = config or CodeIntelConfig(project_dir=self._project_dir)

        # Lazy singletons
        self._init_lock = threading.Lock()
        self._ast_service = None
        self._context_mgr = None
        self._code_analyzer = None
        self._lsp_manager = None
        self._explorer = None
        self._security_scanner = None
        self._semantic_search = None
        self._memory_store = None

    @classmethod
    def get_instance(cls, project_dir: str, config: CodeIntelConfig | None = None) -> CodeIntelService:
        """Get or create a service instance for the given project directory."""
        abs_dir = os.path.abspath(project_dir)
        if abs_dir not in _instances:
            with _instances_lock:
                if abs_dir not in _instances:
                    _instances[abs_dir] = cls(abs_dir, config)
        return _instances[abs_dir]

    @classmethod
    def _reset_instances(cls) -> None:
        """Clear all cached instances. For test isolation only."""
        with _instances_lock:
            _instances.clear()

    @property
    def project_dir(self) -> str:
        return self._project_dir

    # ------------------------------------------------------------------
    # Lazy initializers
    # ------------------------------------------------------------------

    def _get_ast_service(self):
        if self._ast_service is None:
            with self._init_lock:
                if self._ast_service is None:
                    from attocode.integrations.context.ast_service import ASTService

                    svc = ASTService.get_instance(self._project_dir)
                    if not svc.initialized:
                        logger.info("Initializing ASTService for %s...", self._project_dir)
                        svc.initialize()
                        logger.info(
                            "ASTService ready: %d files indexed",
                            len(svc._ast_cache),
                        )
                    self._ast_service = svc
        return self._ast_service

    def _get_context_mgr(self):
        if self._context_mgr is None:
            with self._init_lock:
                if self._context_mgr is None:
                    from attocode.integrations.context.codebase_context import CodebaseContextManager

                    mgr = CodebaseContextManager(root_dir=self._project_dir)
                    mgr.discover_files()
                    self._context_mgr = mgr
        return self._context_mgr

    def _get_code_analyzer(self):
        if self._code_analyzer is None:
            with self._init_lock:
                if self._code_analyzer is None:
                    from attocode.integrations.context.code_analyzer import CodeAnalyzer

                    self._code_analyzer = CodeAnalyzer()
        return self._code_analyzer

    def _get_lsp_manager(self):
        if self._lsp_manager is None:
            with self._init_lock:
                if self._lsp_manager is None:
                    from attocode.integrations.lsp.client import LSPConfig, LSPManager

                    config = LSPConfig(
                        enabled=True,
                        root_uri=f"file://{self._project_dir}",
                    )
                    self._lsp_manager = LSPManager(config=config)
        return self._lsp_manager

    def _get_explorer(self):
        if self._explorer is None:
            # Initialize deps outside the lock to avoid reentrant deadlock
            ctx = self._get_context_mgr()
            ast_svc = self._get_ast_service()
            with self._init_lock:
                if self._explorer is None:
                    from attocode.integrations.context.hierarchical_explorer import HierarchicalExplorer

                    self._explorer = HierarchicalExplorer(ctx, ast_service=ast_svc)
        return self._explorer

    def _get_security_scanner(self):
        if self._security_scanner is None:
            with self._init_lock:
                if self._security_scanner is None:
                    from attocode.integrations.security.scanner import SecurityScanner

                    self._security_scanner = SecurityScanner(root_dir=self._project_dir)
        return self._security_scanner

    def _get_semantic_search(self):
        if self._semantic_search is None:
            with self._init_lock:
                if self._semantic_search is None:
                    from attocode.integrations.context.semantic_search import SemanticSearchManager

                    self._semantic_search = SemanticSearchManager(root_dir=self._project_dir)
        return self._semantic_search

    def _get_memory_store(self):
        if self._memory_store is None:
            with self._init_lock:
                if self._memory_store is None:
                    from attocode.integrations.context.memory_store import MemoryStore

                    self._memory_store = MemoryStore(self._project_dir)
        return self._memory_store

    # ------------------------------------------------------------------
    # Tool operations — same signatures as server.py tool functions
    # ------------------------------------------------------------------

    def repo_map(self, *, include_symbols: bool = True, max_tokens: int = 6000) -> str:
        ctx = self._get_context_mgr()
        repo = ctx.get_repo_map(include_symbols=include_symbols, max_tokens=max_tokens)
        lines = [repo.tree, ""]
        lines.append(
            f"({repo.total_files} files, {repo.total_lines:,} lines, "
            f"{len(repo.languages)} languages)"
        )
        return "\n".join(lines)

    def symbols(self, path: str) -> str:
        svc = self._get_ast_service()
        locs = svc.get_file_symbols(path)
        if not locs:
            return f"No symbols found in {path}"
        lines = [f"Symbols in {path}:"]
        for loc in sorted(locs, key=lambda s: s.start_line):
            lines.append(f"  {loc.kind} {loc.qualified_name}  (L{loc.start_line}-{loc.end_line})")
        return "\n".join(lines)

    def search_symbols(self, name: str) -> str:
        svc = self._get_ast_service()
        locs = svc.find_symbol(name)
        if not locs:
            return f"No definitions found for '{name}'"
        lines = [f"Definitions of '{name}':"]
        for loc in locs:
            lines.append(
                f"  {loc.kind} {loc.qualified_name}  "
                f"in {loc.file_path}:{loc.start_line}-{loc.end_line}"
            )
        return "\n".join(lines)

    def dependencies(self, path: str) -> str:
        svc = self._get_ast_service()
        deps = svc.get_dependencies(path)
        dependents = svc.get_dependents(path)
        lines = [f"Dependencies for {path}:"]
        lines.append(f"\n  Imports from ({len(deps)} files):")
        if deps:
            for d in sorted(deps):
                lines.append(f"    {d}")
        else:
            lines.append("    (none)")
        lines.append(f"\n  Imported by ({len(dependents)} files):")
        if dependents:
            for d in sorted(dependents):
                lines.append(f"    {d}")
        else:
            lines.append("    (none)")
        return "\n".join(lines)

    def impact_analysis(self, changed_files: list[str]) -> str:
        svc = self._get_ast_service()
        impacted = svc.get_impact(changed_files)
        if not impacted:
            return f"No other files are impacted by changes to {', '.join(changed_files)}"
        lines = [f"Impact analysis for {', '.join(changed_files)}:"]
        lines.append(f"\n  {len(impacted)} files affected:")
        for f in sorted(impacted):
            lines.append(f"    {f}")
        return "\n".join(lines)

    def cross_references(self, symbol_name: str) -> str:
        svc = self._get_ast_service()
        definitions = svc.find_symbol(symbol_name)
        references = svc.get_callers(symbol_name)
        lines = [f"Cross-references for '{symbol_name}':"]
        lines.append(f"\n  Definitions ({len(definitions)}):")
        if definitions:
            for loc in definitions:
                lines.append(
                    f"    {loc.kind} {loc.qualified_name}  "
                    f"in {loc.file_path}:{loc.start_line}"
                )
        else:
            lines.append("    (none found)")
        lines.append(f"\n  References ({len(references)}):")
        if references:
            for ref in references[:50]:
                lines.append(f"    [{ref.ref_kind}] {ref.file_path}:{ref.line}")
            if len(references) > 50:
                lines.append(f"    ... and {len(references) - 50} more")
        else:
            lines.append("    (none found)")
        return "\n".join(lines)

    def file_analysis(self, path: str) -> str:
        analyzer = self._get_code_analyzer()
        if not os.path.isabs(path):
            path = os.path.join(self._project_dir, path)
        result = analyzer.analyze_file(path)
        lines = [f"Analysis of {result.path}:"]
        lines.append(f"  Language: {result.language}")
        lines.append(f"  Lines: {result.line_count}")
        if result.imports:
            lines.append(f"\n  Imports ({len(result.imports)}):")
            for imp in result.imports:
                lines.append(f"    {imp}")
        if result.exports:
            lines.append(f"\n  Exports ({len(result.exports)}):")
            for exp in result.exports:
                lines.append(f"    {exp}")
        if result.chunks:
            lines.append(f"\n  Code chunks ({len(result.chunks)}):")
            for chunk in result.chunks:
                sig = f" — {chunk.signature}" if chunk.signature else ""
                parent = f" (in {chunk.parent})" if chunk.parent else ""
                lines.append(
                    f"    {chunk.kind} {chunk.name}{parent}{sig}  "
                    f"L{chunk.start_line}-{chunk.end_line}"
                )
        return "\n".join(lines)

    def dependency_graph(self, start_file: str, depth: int = 2) -> str:
        svc = self._get_ast_service()
        rel = svc._to_rel(start_file)
        lines = [f"Dependency graph for {rel} (depth={depth}):"]

        # Forward BFS
        lines.append("\n  Imports (forward):")
        visited_fwd: set[str] = set()
        queue_fwd: deque[tuple[str, int]] = deque([(rel, 0)])
        while queue_fwd:
            current, d = queue_fwd.popleft()
            if current in visited_fwd or d > depth:
                continue
            visited_fwd.add(current)
            indent = "    " + "  " * d
            if d > 0:
                lines.append(f"{indent}{current}")
            deps = svc.get_dependencies(current)
            for dep in sorted(deps):
                if dep not in visited_fwd:
                    queue_fwd.append((dep, d + 1))
        if len(visited_fwd) <= 1:
            lines.append("    (none)")

        # Reverse BFS
        lines.append("\n  Imported by (reverse):")
        visited_rev: set[str] = set()
        queue_rev: deque[tuple[str, int]] = deque([(rel, 0)])
        while queue_rev:
            current, d = queue_rev.popleft()
            if current in visited_rev or d > depth:
                continue
            visited_rev.add(current)
            indent = "    " + "  " * d
            if d > 0:
                lines.append(f"{indent}{current}")
            dependents = svc.get_dependents(current)
            for dep in sorted(dependents):
                if dep not in visited_rev:
                    queue_rev.append((dep, d + 1))
        if len(visited_rev) <= 1:
            lines.append("    (none)")

        return "\n".join(lines)

    def graph_query(
        self,
        file: str,
        edge_type: str = "IMPORTS",
        direction: str = "outbound",
        depth: int = 2,
    ) -> str:
        valid_edge_types = {"IMPORTS", "IMPORTED_BY"}
        valid_directions = {"outbound", "inbound"}
        if edge_type not in valid_edge_types:
            return f"Error: invalid edge_type '{edge_type}'. Must be one of: {', '.join(sorted(valid_edge_types))}"
        if direction not in valid_directions:
            return f"Error: invalid direction '{direction}'. Must be one of: {', '.join(sorted(valid_directions))}"

        svc = self._get_ast_service()
        rel = svc._to_rel(file)
        depth = min(depth, 5)
        use_dependents = edge_type == "IMPORTED_BY" or direction == "inbound"

        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(rel, 0)])
        result_by_depth: dict[int, list[str]] = {}

        while queue:
            current, d = queue.popleft()
            if current in visited or d > depth:
                continue
            visited.add(current)
            if d > 0:
                result_by_depth.setdefault(d, []).append(current)
            neighbors = svc.get_dependents(current) if use_dependents else svc.get_dependencies(current)
            for n in sorted(neighbors):
                if n not in visited:
                    queue.append((n, d + 1))

        label = "importers" if use_dependents else "imports"
        lines = [f"Graph query: {rel} ({label}, depth={depth})"]
        if not result_by_depth:
            lines.append("  (no results)")
        else:
            for d in sorted(result_by_depth):
                lines.append(f"\n  Hop {d}:")
                for f_path in result_by_depth[d]:
                    lines.append(f"    {'>' * d} {f_path}")
        lines.append(f"\nTotal: {len(visited) - 1} files reachable")
        return "\n".join(lines)

    def find_related(self, file: str, top_k: int = 10) -> str:
        svc = self._get_ast_service()
        rel = svc._to_rel(file)
        idx = svc._index

        if rel not in idx.file_symbols and rel not in idx.file_dependencies:
            return f"Error: file '{rel}' not found in the project index."

        neighbors: Counter[str] = Counter()
        direct_deps = idx.get_dependencies(rel)
        direct_importers = idx.get_dependents(rel)
        all_direct = direct_deps | direct_importers

        for n in all_direct:
            neighbors[n] += 3
        for n in all_direct:
            for nn in idx.get_dependencies(n):
                if nn != rel:
                    neighbors[nn] += 1
            for nn in idx.get_dependents(n):
                if nn != rel:
                    neighbors[nn] += 1

        my_deps = idx.get_dependencies(rel)
        if my_deps:
            candidate_files = set(neighbors.keys())
            for other_file in candidate_files:
                other_deps_set = idx.file_dependencies.get(other_file, set())
                if not other_deps_set:
                    continue
                overlap = len(my_deps & other_deps_set)
                if overlap > 0:
                    union = len(my_deps | other_deps_set)
                    jaccard = overlap / union if union else 0
                    neighbors[other_file] += round(jaccard * 5)

        top = neighbors.most_common(top_k)
        lines = [f"Files related to {rel}:"]
        if not top:
            lines.append("  (no related files found)")
        else:
            for path, score in top:
                rel_type = "direct" if path in all_direct else "transitive"
                lines.append(f"  [{score:>3}] {path}  ({rel_type})")
        return "\n".join(lines)

    def community_detection(self, min_community_size: int = 3, max_communities: int = 20) -> str:
        from collections import Counter as _Counter

        svc = self._get_ast_service()
        idx = svc._index

        all_files: set[str] = set()
        all_files.update(idx.file_dependencies.keys())
        all_files.update(idx.file_dependents.keys())
        all_files.update(f for deps in idx.file_dependencies.values() for f in deps)

        adj: dict[str, set[str]] = {f: set() for f in all_files}
        weights: dict[tuple[str, str], float] = {}
        for src, deps in idx.file_dependencies.items():
            for tgt in deps:
                adj.setdefault(src, set()).add(tgt)
                adj.setdefault(tgt, set()).add(src)
                key = (min(src, tgt), max(src, tgt))
                is_bidi = tgt in idx.file_dependencies and src in idx.file_dependencies.get(tgt, set())
                weights[key] = 2.0 if is_bidi else 1.0

        # Try Louvain, fall back to BFS connected components
        try:
            from attocode.code_intel.community import louvain_communities as _louvain
            communities, modularity_score = _louvain(all_files, adj, weights)
            method = "louvain"
        except ImportError:
            from attocode.code_intel.community import bfs_connected_components
            communities, modularity_score = bfs_connected_components(all_files, adj)
            method = "connected-components"

        communities.sort(key=len, reverse=True)
        communities = [c for c in communities if len(c) >= min_community_size][:max_communities]

        lines = [
            f"Community detection ({method}): {len(communities)} communities "
            f"(min size {min_community_size}, modularity={modularity_score:.3f})"
        ]
        for i, community in enumerate(communities, 1):
            dirs = [os.path.dirname(f) for f in community if os.path.dirname(f)]
            theme = _Counter(dirs).most_common(1)[0][0] if dirs else "(root)"

            internal_edges = sum(
                1 for f in community for n in adj.get(f, set()) if n in community
            ) // 2
            external_edges = sum(
                1 for f in community for n in adj.get(f, set()) if n not in community
            )

            def _int_deg(f: str) -> int:
                return sum(1 for n in adj.get(f, set()) if n in community)

            hub = max(community, key=_int_deg)
            lines.append(f"\n  Community {i} ({len(community)} files) — theme: {theme}")
            lines.append(f"    Internal edges: {internal_edges}, External edges: {external_edges}")
            lines.append(f"    Hub: {hub} (internal degree {_int_deg(hub)})")
            sample = sorted(community)[:5]
            for f in sample:
                lines.append(f"    - {f} (internal degree {_int_deg(f)})")
            if len(community) > 5:
                lines.append(f"    ... and {len(community) - 5} more")
        return "\n".join(lines)

    def relevant_context(
        self,
        files: list[str],
        depth: int = 1,
        max_tokens: int = 4000,
        include_symbols: bool = True,
    ) -> str:
        svc = self._get_ast_service()
        ctx = self._get_context_mgr()
        ast_cache = svc._ast_cache
        all_files = {fi.relative_path: fi for fi in ctx._files}

        depth = min(depth, 2)
        center_rels: list[str] = []
        for f in files:
            rel = svc._to_rel(f)
            if rel:
                center_rels.append(rel)
        if not center_rels:
            return "No valid files provided."

        visited: dict[str, tuple[int, str]] = {}
        queue: deque[tuple[str, int, str]] = deque()
        for rel in center_rels:
            visited[rel] = (0, "center")
            queue.append((rel, 0, "center"))

        while queue:
            current, d, _rel_type = queue.popleft()
            if d >= depth:
                continue
            for dep in svc.get_dependencies(current):
                if dep not in visited:
                    relationship = "imported-by-center" if d == 0 else "transitive-import"
                    visited[dep] = (d + 1, relationship)
                    queue.append((dep, d + 1, relationship))
            for dep in svc.get_dependents(current):
                if dep not in visited:
                    relationship = "imports-center" if d == 0 else "transitive-importer"
                    visited[dep] = (d + 1, relationship)
                    queue.append((dep, d + 1, relationship))

        def _sort_key(item):
            rel, (dist, _) = item
            fi = all_files.get(rel)
            importance = fi.importance if fi else 0.0
            return (dist, -importance)

        sorted_files = sorted(visited.items(), key=_sort_key)
        sections: list[str] = []
        token_est = 0

        for rel, (dist, relationship) in sorted_files:
            fi = all_files.get(rel)
            file_ast = ast_cache.get(rel)
            lang = fi.language if fi else ""
            line_count = fi.line_count if fi else 0
            importance = fi.importance if fi else 0.0

            header = f"{'  ' * dist}{rel}"
            meta = f"  {lang}, {line_count}L, importance={importance:.2f}, {relationship}"
            file_section = [header, meta]

            if include_symbols and file_ast:
                max_sym = 8 if dist == 0 else 5
                sym_lines: list[str] = []
                for fn in file_ast.functions[:max_sym]:
                    params = ", ".join(p.name for p in fn.parameters[:4])
                    ret = f" -> {fn.return_type}" if fn.return_type else ""
                    sym_lines.append(f"    fn {fn.name}({params}){ret}")
                for cls in file_ast.classes[:max_sym]:
                    bases = f"({', '.join(cls.bases[:3])})" if cls.bases else ""
                    methods_preview = ", ".join(m.name for m in cls.methods[:4])
                    sym_lines.append(f"    class {cls.name}{bases}: {methods_preview}")
                remaining = max_sym - len(sym_lines)
                if remaining < 0:
                    sym_lines = sym_lines[:max_sym]
                    sym_lines.append("    ... and more")
                file_section.extend(sym_lines)

            section_text = "\n".join(file_section)
            section_tokens = int(len(section_text) / 3.5)
            if token_est + section_tokens > max_tokens and sections:
                sections.append(f"  ... and {len(sorted_files) - len(sections)} more files (truncated)")
                break
            sections.append(section_text)
            token_est += section_tokens

        header_text = (
            f"Subgraph capsule for {', '.join(center_rels)} "
            f"(depth={depth}, {len(visited)} files):\n"
        )
        return header_text + "\n".join(sections)

    def project_summary(self, max_tokens: int = 4000) -> str:
        # Import the synthesis helpers from helpers module
        from attocode.code_intel.helpers import (
            _classify_layers,
            _detect_build_system,
            _detect_project_name,
            _detect_tech_stack,
            _find_entry_points,
            _find_hub_files,
            _summarize_directories,
        )

        ctx = self._get_context_mgr()
        files = ctx._files
        if not files:
            return "No files discovered in this project."

        repo = ctx.get_repo_map(include_symbols=False, max_tokens=500)
        svc = self._get_ast_service()
        index = svc._index
        ast_cache = svc._ast_cache

        sections: list[tuple[str, str, int]] = []

        name = _detect_project_name(self._project_dir)
        top_langs = sorted(repo.languages.items(), key=lambda x: -x[1])[:8]
        lang_str = ", ".join(f"{lang} ({count})" for lang, count in top_langs)
        identity = (
            f"Project: {name}\n"
            f"Files: {repo.total_files}, Lines: {repo.total_lines:,}\n"
            f"Languages: {lang_str or 'unknown'}"
        )
        sections.append(("Overview", identity, 10))

        entries = _find_entry_points(files, index)
        if entries:
            entry_lines = [f"  {path} — {reason}" for path, reason in entries[:10]]
            sections.append(("Entry Points", "\n".join(entry_lines), 9))

        if index.file_dependents:
            hubs = _find_hub_files(files, index, top_n=10)
            if hubs:
                hub_lines = [f"  {path} (fan-in={fi}, fan-out={fo})" for path, fi, fo in hubs]
                sections.append(("Core Files (by dependents)", "\n".join(hub_lines), 8))

        dirs = _summarize_directories(files)
        total_files = len(files)
        dir_lines = []
        for d, count, loc in dirs[:15]:
            pct = count / total_files * 100 if total_files else 0
            if d in ("site", "docs", "doc", ".git") and pct < 10:
                continue
            dir_lines.append(f"  {d}/ — {count} files, {loc:,} lines ({pct:.0f}%)")
        if dir_lines:
            sections.append(("Directory Layout", "\n".join(dir_lines), 7))

        if index.file_dependents:
            layers = _classify_layers(files, index)
            layer_lines = []
            for layer_name, layer_files in layers.items():
                if layer_files:
                    examples = ", ".join(layer_files[:5])
                    more = f" (+{len(layer_files) - 5})" if len(layer_files) > 5 else ""
                    layer_lines.append(f"  {layer_name}: {len(layer_files)} files — {examples}{more}")
            if layer_lines:
                sections.append(("Dependency Layers", "\n".join(layer_lines), 5))

        if ast_cache:
            stack = _detect_tech_stack(ast_cache)
            if stack:
                sections.append(("Tech Stack", "  " + ", ".join(stack), 6))

        test_files = [f for f in files if f.is_test]
        if test_files:
            has_prefix = any("test_" in os.path.basename(f.relative_path) for f in test_files)
            test_pat = "test_*.py" if has_prefix else "*_test.py"
            sections.append(("Tests", f"  {len(test_files)} test files (pattern: {test_pat})", 4))

        build = _detect_build_system(files)
        if build != "unknown":
            sections.append(("Build System", f"  {build}", 3))

        sections.sort(key=lambda x: x[2], reverse=True)
        output_parts: list[str] = []
        token_est = 0
        for header, text, _prio in sections:
            section_text = f"## {header}\n{text}"
            section_tokens = int(len(section_text) / 3.5)
            if token_est + section_tokens > max_tokens and output_parts:
                break
            output_parts.append(section_text)
            token_est += section_tokens
        return "\n\n".join(output_parts)

    def bootstrap(self, task_hint: str = "", max_tokens: int = 8000) -> str:
        from attocode.code_intel.helpers import _analyze_conventions, _format_conventions

        ctx = self._get_context_mgr()
        files = ctx._files
        if not files:
            return "No files discovered in this project."

        total_files = len(files)
        if total_files < 100:
            size_tier = "small"
        elif total_files < 2000:
            size_tier = "medium"
        else:
            size_tier = "large"

        summary_budget = int(max_tokens * 0.38)
        structure_budget = int(max_tokens * 0.38)
        conventions_budget = int(max_tokens * 0.12)
        search_budget = int(max_tokens * 0.12) if task_hint else 0
        if not task_hint:
            summary_budget = int(max_tokens * 0.40)
            structure_budget = int(max_tokens * 0.44)
            conventions_budget = int(max_tokens * 0.16)

        sections: list[str] = []
        sections.append(self.project_summary(max_tokens=summary_budget))

        if size_tier == "small":
            map_text = self.repo_map(include_symbols=True, max_tokens=structure_budget)
            sections.append(f"## Repository Map\n{map_text}")
        elif size_tier == "medium":
            map_text = self.repo_map(include_symbols=True, max_tokens=int(structure_budget * 0.7))
            hs_text = self.hotspots(top_n=10)
            sections.append(f"## Repository Map\n{map_text}")
            sections.append(f"## Hotspots\n{hs_text}")
        else:
            explorer = self._get_explorer()
            root_result = explorer.explore("", max_items=20, importance_threshold=0.3)
            explore_text = explorer.format_result(root_result)
            hs_text = self.hotspots(top_n=10)
            sections.append(f"## Top-Level Structure\n{explore_text}")
            sections.append(f"## Hotspots\n{hs_text}")

        svc = self._get_ast_service()
        ast_cache = svc._ast_cache
        if ast_cache:
            candidates = sorted(
                [fi for fi in files if fi.relative_path in ast_cache],
                key=lambda fi: fi.importance,
                reverse=True,
            )
            sample_rels = [fi.relative_path for fi in candidates[:25]]
            if sample_rels:
                stats = _analyze_conventions(ast_cache, sample_rels)
                conv_text = _format_conventions(stats)
                conv_chars = conventions_budget * 4
                if len(conv_text) > conv_chars:
                    conv_text = conv_text[:conv_chars] + "\n  ..."
                sections.append(f"## Conventions\n{conv_text}")

        if task_hint:
            try:
                mgr = self._get_semantic_search()
                results = mgr.search(task_hint, top_k=5)
                if results:
                    search_text = mgr.format_results(results)
                    search_chars = search_budget * 4
                    if len(search_text) > search_chars:
                        search_text = search_text[:search_chars] + "\n  ..."
                    sections.append(f"## Relevant Code for: {task_hint}\n{search_text}")
            except Exception:
                pass

        if size_tier == "small":
            guidance = (
                "## Navigation Guidance\n"
                "Small codebase — the repo map above shows everything.\n"
                "Next: `symbols(file)` or `file_analysis(file)` on files of interest."
            )
        elif size_tier == "medium":
            guidance = (
                "## Navigation Guidance\n"
                "Medium codebase — use `explore_codebase(dir)` to drill into directories.\n"
                "For specific symbols: `search_symbols(name)` or `semantic_search(query)`.\n"
                "Before modifying: `impact_analysis([files])` to check blast radius."
            )
        else:
            guidance = (
                "## Navigation Guidance\n"
                "Large codebase — do NOT request full `repo_map`, it wastes tokens.\n"
                "Use `explore_codebase(dir)` to drill down level by level.\n"
                "For specific symbols: `search_symbols(name)` or `semantic_search(query)`.\n"
                "Use `relevant_context([file])` to understand a file with its neighbors.\n"
                "Before modifying: `impact_analysis([files])` to check blast radius."
            )
        sections.append(guidance)
        return "\n\n".join(sections)

    def hotspots(self, top_n: int = 15) -> str:
        from attocode.code_intel.helpers import _compute_file_metrics, _compute_function_hotspots

        ctx = self._get_context_mgr()
        files = ctx._files
        if not files:
            return "No files discovered in this project."

        svc = self._get_ast_service()
        index = svc._index
        ast_cache = svc._ast_cache

        all_metrics = _compute_file_metrics(files, index, ast_cache)
        if not all_metrics:
            return "No analyzable files found."

        all_metrics.sort(key=lambda m: m.composite, reverse=True)
        lines = [f"Top {min(top_n, len(all_metrics))} hotspots by complexity/coupling:\n"]
        for i, m in enumerate(all_metrics[:top_n], 1):
            tags = f"  [{', '.join(m.categories)}]" if m.categories else ""
            lines.append(
                f"  {i:2d}. {m.path}\n"
                f"      {m.line_count} lines, {m.symbol_count} symbols, "
                f"pub={m.public_symbols}, "
                f"fan-in={m.fan_in}, fan-out={m.fan_out}, "
                f"density={m.density}%, score={m.composite}{tags}"
            )

        fn_hotspots = _compute_function_hotspots(ast_cache, top_n=10)
        if fn_hotspots:
            lines.append("\nLongest functions:")
            for i, fm in enumerate(fn_hotspots, 1):
                pub_mark = "" if fm.is_public else " (private)"
                ret_mark = "" if fm.has_return_type else " [no return type]"
                lines.append(
                    f"  {i:2d}. {fm.name} — {fm.line_count} lines, "
                    f"{fm.param_count} params{pub_mark}{ret_mark}\n"
                    f"      {fm.file_path}"
                )

        orphans = [
            m for m in all_metrics
            if m.fan_in == 0 and m.fan_out == 0 and m.line_count >= 20
            and not any(fi.is_test for fi in files if fi.relative_path == m.path)
        ]
        if orphans:
            lines.append(f"\nOrphan files (no imports/importers, {len(orphans)} found):")
            for m in orphans[:10]:
                lines.append(f"  {m.path} ({m.line_count} lines, {m.symbol_count} symbols)")
            if len(orphans) > 10:
                lines.append(f"  ... and {len(orphans) - 10} more")
        return "\n".join(lines)

    def conventions(self, sample_size: int = 50, path: str = "") -> str:
        from attocode.code_intel.helpers import _analyze_conventions, _format_conventions

        svc = self._get_ast_service()
        ast_cache = svc._ast_cache
        if not ast_cache:
            return "No files parsed — cannot detect conventions."

        ctx = self._get_context_mgr()
        files = ctx._files
        path_prefix = path.rstrip("/") + "/" if path else ""

        if path_prefix:
            scoped_candidates = sorted(
                [
                    fi for fi in files
                    if fi.relative_path in ast_cache
                    and fi.relative_path.startswith(path_prefix)
                ],
                key=lambda fi: fi.importance,
                reverse=True,
            )
            scoped_rels = [fi.relative_path for fi in scoped_candidates[:sample_size]]
            if not scoped_rels:
                return f"No parsed files found in '{path}'."

            scoped_stats = _analyze_conventions(ast_cache, scoped_rels)
            global_candidates = sorted(
                [fi for fi in files if fi.relative_path in ast_cache],
                key=lambda fi: fi.importance,
                reverse=True,
            )
            global_rels = [fi.relative_path for fi in global_candidates[:sample_size]]
            global_stats = _analyze_conventions(ast_cache, global_rels)

            header = f"Conventions in {path}/ ({len(scoped_rels)} files):\n"
            scoped_text = _format_conventions(scoped_stats)

            comparison_parts: list[str] = []
            scoped_fn = scoped_stats["total_functions"]
            global_fn = global_stats["total_functions"]
            if scoped_fn > 0 and global_fn > 0:
                scoped_type_pct = scoped_stats["typed_return"] / scoped_fn * 100
                global_type_pct = global_stats["typed_return"] / global_fn * 100
                if abs(scoped_type_pct - global_type_pct) > 10:
                    comparison_parts.append(
                        f"  Type hints: {scoped_type_pct:.0f}% here vs {global_type_pct:.0f}% project-wide"
                    )
                scoped_doc_pct = scoped_stats["has_docstring_fn"] / scoped_fn * 100
                global_doc_pct = global_stats["has_docstring_fn"] / global_fn * 100
                if abs(scoped_doc_pct - global_doc_pct) > 10:
                    comparison_parts.append(
                        f"  Docstrings: {scoped_doc_pct:.0f}% here vs {global_doc_pct:.0f}% project-wide"
                    )
                scoped_async_pct = scoped_stats["async_count"] / scoped_fn * 100
                global_async_pct = global_stats["async_count"] / global_fn * 100
                if abs(scoped_async_pct - global_async_pct) > 10:
                    comparison_parts.append(
                        f"  Async: {scoped_async_pct:.0f}% here vs {global_async_pct:.0f}% project-wide"
                    )

            if comparison_parts:
                header += scoped_text + "\n\nDivergence from project conventions:\n" + "\n".join(comparison_parts)
            else:
                header += scoped_text + "\n\n(Matches project-wide conventions.)"
            return header

        candidates = sorted(
            [fi for fi in files if fi.relative_path in ast_cache],
            key=lambda fi: fi.importance,
            reverse=True,
        )
        sample_rels = [fi.relative_path for fi in candidates[:sample_size]]
        if not sample_rels:
            return "No parsed files available for convention analysis."

        stats = _analyze_conventions(ast_cache, sample_rels)
        dir_groups: dict[str, list[str]] = {}
        for rel in sample_rels:
            parts = rel.split("/")
            dirname = parts[0] if len(parts) > 1 else "(root)"
            dir_groups.setdefault(dirname, []).append(rel)

        dir_stats: dict[str, dict] = {}
        for dirname, dir_rels in dir_groups.items():
            if len(dir_rels) >= 3:
                dir_stats[dirname] = _analyze_conventions(ast_cache, dir_rels)

        header = f"Conventions detected across {len(sample_rels)} files:\n"
        return header + _format_conventions(stats, dir_stats=dir_stats)

    async def lsp_definition(self, file: str, line: int, col: int = 0) -> str:
        lsp = self._get_lsp_manager()
        if not os.path.isabs(file):
            file = os.path.join(self._project_dir, file)
        try:
            loc = await lsp.get_definition(file, line, col)
        except Exception as e:
            return f"LSP not available: {e}"
        if loc is None:
            return f"No definition found at {file}:{line}:{col}"
        uri = loc.uri
        if uri.startswith("file://"):
            uri = uri[7:]
        try:
            uri = os.path.relpath(uri, self._project_dir)
        except ValueError:
            pass
        return f"Definition: {uri}:{loc.range.start.line + 1}:{loc.range.start.character + 1}"

    async def lsp_references(
        self, file: str, line: int, col: int = 0, include_declaration: bool = True,
    ) -> str:
        lsp = self._get_lsp_manager()
        if not os.path.isabs(file):
            file = os.path.join(self._project_dir, file)
        try:
            locs = await lsp.get_references(file, line, col, include_declaration=include_declaration)
        except Exception as e:
            return f"LSP not available: {e}"
        if not locs:
            return f"No references found at {file}:{line}:{col}"
        lines = [f"References ({len(locs)}):"]
        for loc in locs[:50]:
            uri = loc.uri
            if uri.startswith("file://"):
                uri = uri[7:]
            try:
                uri = os.path.relpath(uri, self._project_dir)
            except ValueError:
                pass
            lines.append(f"  {uri}:{loc.range.start.line + 1}:{loc.range.start.character + 1}")
        if len(locs) > 50:
            lines.append(f"  ... and {len(locs) - 50} more")
        return "\n".join(lines)

    async def lsp_hover(self, file: str, line: int, col: int = 0) -> str:
        lsp = self._get_lsp_manager()
        if not os.path.isabs(file):
            file = os.path.join(self._project_dir, file)
        try:
            info = await lsp.get_hover(file, line, col)
        except Exception as e:
            return f"LSP not available: {e}"
        if info is None:
            return f"No hover information at {file}:{line}:{col}"
        return f"Hover at {file}:{line}:{col}:\n{info}"

    def lsp_diagnostics(self, file: str) -> str:
        lsp = self._get_lsp_manager()
        if not os.path.isabs(file):
            file = os.path.join(self._project_dir, file)
        try:
            diags = lsp.get_diagnostics(file)
        except Exception as e:
            return f"LSP not available: {e}"
        if not diags:
            return f"No diagnostics for {file}"
        lines = [f"Diagnostics ({len(diags)}):"]
        for d in diags[:30]:
            source = f" [{d.source}]" if d.source else ""
            code = f" ({d.code})" if d.code else ""
            lines.append(
                f"  [{d.severity}]{source}{code} "
                f"L{d.range.start.line + 1}:{d.range.start.character + 1}: "
                f"{d.message}"
            )
        if len(diags) > 30:
            lines.append(f"  ... and {len(diags) - 30} more")
        return "\n".join(lines)

    def explore_codebase(
        self, path: str = "", max_items: int = 30, importance_threshold: float = 0.3,
    ) -> str:
        explorer = self._get_explorer()
        result = explorer.explore(path, max_items=max_items, importance_threshold=importance_threshold)
        return explorer.format_result(result)

    def security_scan(self, mode: str = "full", path: str = "") -> str:
        scanner = self._get_security_scanner()
        report = scanner.scan(mode=mode, path=path)
        return scanner.format_report(report)

    def semantic_search(self, query: str, top_k: int = 10, file_filter: str = "") -> str:
        mgr = self._get_semantic_search()
        results = mgr.search(query, top_k=top_k, file_filter=file_filter)
        return mgr.format_results(results)

    def start_indexing(self) -> dict:
        """Start background embedding indexing."""
        mgr = self._get_semantic_search()
        progress = mgr.start_background_indexing()
        return {
            "provider": mgr.provider_name,
            "available": mgr.is_available,
            "status": progress.status,
            "total_files": progress.total_files,
            "indexed_files": progress.indexed_files,
            "failed_files": progress.failed_files,
            "coverage": progress.coverage,
            "elapsed_seconds": progress.elapsed_seconds,
            "vector_search_active": mgr.is_index_ready(),
        }

    def indexing_status(self) -> dict:
        """Get current indexing status."""
        mgr = self._get_semantic_search()
        progress = mgr.get_index_progress()
        return {
            "provider": mgr.provider_name,
            "available": mgr.is_available,
            "status": progress.status,
            "total_files": progress.total_files,
            "indexed_files": progress.indexed_files,
            "failed_files": progress.failed_files,
            "coverage": progress.coverage,
            "elapsed_seconds": progress.elapsed_seconds,
            "vector_search_active": mgr.is_index_ready(),
        }

    def recall(self, query: str, scope: str = "", max_results: int = 10) -> str:
        store = self._get_memory_store()
        results = store.recall(query, scope=scope, max_results=max_results)
        if not results:
            return "No relevant learnings found for this project."
        lines = [f"## Project Learnings ({len(results)} relevant)\n"]
        for r in results:
            lines.append(f"- **[{r['type']}]** (confidence: {r['confidence']:.0%}, id: {r['id']})")
            lines.append(f"  {r['description']}")
            if r["details"]:
                lines.append(f"  _{r['details']}_")
        for r in results:
            try:
                store.record_applied(r["id"])
            except Exception:
                logger.debug("Failed to record_applied for learning %d", r["id"])
        return "\n".join(lines)

    def record_learning(
        self,
        type: str,
        description: str,
        details: str = "",
        scope: str = "",
        confidence: float = 0.7,
    ) -> str:
        store = self._get_memory_store()
        try:
            learning_id = store.add(
                type=type, description=description,
                details=details, scope=scope, confidence=confidence,
            )
        except ValueError as e:
            return f"Error: {e}"
        return f"Recorded learning #{learning_id}: [{type}] {description}"

    def learning_feedback(self, learning_id: int, helpful: bool) -> str:
        store = self._get_memory_store()
        store.record_feedback(learning_id, helpful)
        action = "boosted" if helpful else "reduced"
        return f"Feedback recorded — confidence {action} for learning #{learning_id}."

    def list_learnings(self, status: str = "active", type: str = "", scope: str = "") -> str:
        store = self._get_memory_store()
        results = store.list_all(status=status, type=type or None)
        if scope:
            results = [r for r in results if r["scope"].startswith(scope) or r["scope"] == ""]
        if not results:
            return "No learnings found matching the filters."
        lines = [f"## Learnings ({len(results)} total)\n"]
        lines.append("| ID | Type | Description | Confidence | Applied | Scope |")
        lines.append("|---|---|---|---|---|---|")
        for r in results:
            desc = r["description"][:60] + ("..." if len(r["description"]) > 60 else "")
            lines.append(
                f"| {r['id']} | {r['type']} | {desc} "
                f"| {r['confidence']:.0%} | {r['apply_count']}x "
                f"| {r['scope'] or '(global)'} |"
            )
        return "\n".join(lines)

    def notify_file_changed(self, files: list[str]) -> str:
        if not files:
            return "No files specified."
        svc = self._get_ast_service()
        updated = 0
        for f in files:
            try:
                p = Path(f)
                if p.is_absolute():
                    rel = os.path.relpath(str(p), self._project_dir)
                else:
                    rel = str(p)
                rel = os.path.normpath(rel)
                if rel.startswith(".."):
                    continue
                svc.notify_file_changed(rel)
                try:
                    smgr = self._get_semantic_search()
                    abs_path = os.path.join(self._project_dir, rel)
                    smgr.invalidate_file(abs_path)
                except Exception:
                    pass
                updated += 1
            except Exception as exc:
                logger.debug("notify_file_changed: error for %s: %s", f, exc)
        return f"Updated {updated} file(s). AST index refreshed."
