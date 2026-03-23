"""Analysis tools for the code-intel MCP server.

Tools: file_analysis, impact_analysis, dependency_graph, hotspots,
cross_references, dependencies, graph_query, graph_dsl, find_related,
community_detection, repo_map_ranked, bug_scan.
"""

from __future__ import annotations

import os
from collections import Counter, deque

from attocode.code_intel.helpers import (
    _compute_file_metrics,
    _compute_function_hotspots,
    _get_churn_scores,
)
from attocode.code_intel.server import (
    _get_ast_service,
    _get_code_analyzer,
    _get_context_mgr,
    _get_project_dir,
    mcp,
)


@mcp.tool()
def file_analysis(path: str) -> str:
    """Get detailed analysis of a single file including code chunks, imports, and exports.

    Extracts structured information about functions, classes, methods,
    imports, and exports using AST parsing (tree-sitter or regex fallback).

    Args:
        path: File path (relative to project root or absolute).
    """
    analyzer = _get_code_analyzer()
    project_dir = _get_project_dir()

    # Resolve to absolute path if relative
    if not os.path.isabs(path):
        path = os.path.join(project_dir, path)

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


@mcp.tool()
def impact_analysis(changed_files: list[str]) -> str:
    """Analyze the transitive impact of changing one or more files.

    Uses BFS on the reverse dependency graph to find all files that
    could be affected by changes to the given files. This is useful
    for understanding the blast radius of a code change.

    Args:
        changed_files: List of file paths that were changed.
    """
    svc = _get_ast_service()
    impacted = svc.get_impact(changed_files)

    if not impacted:
        return f"No other files are impacted by changes to {', '.join(changed_files)}"

    lines = [f"Impact analysis for {', '.join(changed_files)}:"]
    lines.append(f"\n  {len(impacted)} files affected:")
    for f in sorted(impacted):
        lines.append(f"    {f}")
    return "\n".join(lines)


@mcp.tool()
def dependency_graph(start_file: str, depth: int = 2) -> str:
    """Get the dependency graph starting from a file.

    Shows the import tree radiating outward from the given file,
    including both forward dependencies (what it imports) and
    reverse dependencies (what imports it).

    Args:
        start_file: File path to start from.
        depth: How many hops to traverse (default 2).
    """
    svc = _get_ast_service()
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


@mcp.tool()
def hotspots(top_n: int = 15) -> str:
    """Identify files with highest complexity, coupling, and risk.

    Ranks files by a composite score combining size, symbol count,
    fan-in (dependents), fan-out (dependencies), and symbol density.
    Also categorizes files as god-files, hubs, coupling magnets, or orphans.

    Args:
        top_n: Number of top hotspots to show (default 15).
    """
    ctx = _get_context_mgr()
    files = ctx._files

    if not files:
        return "No files discovered in this project."

    svc = _get_ast_service()
    index = svc._index
    ast_cache = svc._ast_cache
    project_dir = _get_project_dir()
    churn_scores = _get_churn_scores(project_dir, files)

    all_metrics = _compute_file_metrics(files, index, ast_cache, churn_scores)
    if not all_metrics:
        return "No analyzable files found."

    # Sort by composite score
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

    # Function-level hotspots
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

    # Orphan detection
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


@mcp.tool()
def cross_references(symbol_name: str) -> str:
    """Find where a symbol is defined and all places it is referenced.

    Shows both the definition locations and all call sites, imports,
    and attribute accesses for the given symbol.

    Args:
        symbol_name: Name of the symbol to look up.
    """
    svc = _get_ast_service()
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
        for ref in references[:50]:  # Cap at 50 to avoid huge output
            lines.append(f"    [{ref.ref_kind}] {ref.file_path}:{ref.line}")
        if len(references) > 50:
            lines.append(f"    ... and {len(references) - 50} more")
    else:
        lines.append("    (none found)")

    return "\n".join(lines)


@mcp.tool()
def dependencies(path: str) -> str:
    """Get import/dependency relationships for a file.

    Shows both what the file imports from (dependencies) and what files
    import it (dependents/importers).

    Args:
        path: File path (relative to project root or absolute).
    """
    svc = _get_ast_service()
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


@mcp.tool()
def graph_query(
    file: str,
    edge_type: str = "IMPORTS",
    direction: str = "outbound",
    depth: int = 2,
) -> str:
    """BFS traversal over typed dependency edges.

    Walks the import graph from a starting file, following edges of the
    specified type and direction.

    Args:
        file: Starting file path (relative to project root or absolute).
        edge_type: Edge type to follow. One of: IMPORTS, IMPORTED_BY.
        direction: "outbound" follows imports, "inbound" follows importers.
        depth: Maximum BFS hops (default 2, max 5).
    """
    valid_edge_types = {"IMPORTS", "IMPORTED_BY"}
    valid_directions = {"outbound", "inbound"}
    if edge_type not in valid_edge_types:
        opts = ", ".join(sorted(valid_edge_types))
        return f"Error: invalid edge_type '{edge_type}'. Must be one of: {opts}"
    if direction not in valid_directions:
        opts = ", ".join(sorted(valid_directions))
        return f"Error: invalid direction '{direction}'. Must be one of: {opts}"

    svc = _get_ast_service()
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


@mcp.tool()
def graph_dsl(query: str) -> str:
    """Query the dependency graph with a simple graph query language.

    Supports a Cypher-inspired syntax for traversing import relationships
    with depth constraints, filters, and multi-hop chains.

    Example queries:
      MATCH "src/api/app.py" -[IMPORTS*1..3]-> target RETURN target
      MATCH file <-[IMPORTED_BY]- caller WHERE caller.language = "python" RETURN caller
      MATCH a -[IMPORTS]-> b -[IMPORTS]-> c RETURN a, c

    Syntax:
      MATCH node -[EDGE_TYPE*min..max]-> node [WHERE conditions] RETURN variables
      - Node: variable name (e.g. 'target') or quoted path ("src/app.py")
      - Edge types: IMPORTS, IMPORTED_BY
      - Direction: -> (outbound), <- (inbound with <-[TYPE]-)
      - Depth: *N (exact), *N..M (range), omit for 1
      - WHERE: variable.field op value (AND-separated)
        Fields: language, line_count, importance, path, fan_in, fan_out, is_test, is_config
        Operators: =, !=, >, <, >=, <=, LIKE
      - RETURN: comma-separated variable names, or variable.field, or COUNT

    Args:
        query: Graph DSL query string.
    """
    from attocode.code_intel.graph_query_parser import (
        GraphQueryExecutor,
        GraphQueryParser,
    )

    ctx = _get_context_mgr()
    dep_graph = ctx.dependency_graph
    files = ctx._files

    parser = GraphQueryParser()
    try:
        ast = parser.parse(query)
    except ValueError as exc:
        return f"Query syntax error: {exc}"

    executor = GraphQueryExecutor()
    try:
        results = executor.execute(ast, dep_graph, files)
    except Exception as exc:
        return f"Execution error: {exc}"

    if not results:
        return f"No results for query: {query}"

    lines = [f"Graph DSL results ({len(results)} matches):"]

    # Format results based on what's returned
    for i, row in enumerate(results, 1):
        parts = []
        for key, value in row.items():
            parts.append(f"{key}={value}")
        lines.append(f"  {i:3d}. {', '.join(parts)}")

    if len(results) >= executor.MAX_RESULTS:
        lines.append(f"\n  (results truncated at {executor.MAX_RESULTS})")

    return "\n".join(lines)


@mcp.tool()
def find_related(file: str, top_k: int = 10) -> str:
    """Find structurally related files by import-graph proximity.

    Combines 2-hop import neighbors with co-importer overlap
    (Jaccard-style) to find the most structurally related files.

    Args:
        file: File path (relative to project root or absolute).
        top_k: Number of results to return (default 10).
    """
    svc = _get_ast_service()
    rel = svc._to_rel(file)
    idx = svc._index

    # Check file exists in index
    if rel not in idx.file_symbols and rel not in idx.file_dependencies:
        return f"Error: file '{rel}' not found in the project index."

    # Collect 2-hop neighbors in both directions
    neighbors: Counter[str] = Counter()

    direct_deps = idx.get_dependencies(rel)
    direct_importers = idx.get_dependents(rel)
    all_direct = direct_deps | direct_importers

    for n in all_direct:
        neighbors[n] += 3  # Direct connection = high weight

    for n in all_direct:
        for nn in idx.get_dependencies(n):
            if nn != rel:
                neighbors[nn] += 1
        for nn in idx.get_dependents(n):
            if nn != rel:
                neighbors[nn] += 1

    # Co-importer overlap (Jaccard-style boost) — scoped to 2-hop neighbors only
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


def _louvain_communities(
    all_files: set[str],
    adj: dict[str, set[str]],
    weights: dict[tuple[str, str], float],
) -> tuple[list[set[str]], float]:
    """Run Louvain community detection using networkx."""
    from attocode.code_intel.community import louvain_communities
    return louvain_communities(all_files, adj, weights)


def _bfs_connected_components(
    all_files: set[str],
    adj: dict[str, set[str]],
) -> tuple[list[set[str]], float]:
    """Fallback: connected components via BFS. Modularity = 0."""
    from attocode.code_intel.community import bfs_connected_components
    return bfs_connected_components(all_files, adj)


@mcp.tool()
def community_detection(
    min_community_size: int = 3,
    max_communities: int = 20,
) -> str:
    """Detect file communities using Louvain algorithm on the import graph.

    Groups files into communities based on modularity optimization (Louvain),
    falling back to connected components when networkx is not installed.
    Reports community sizes, modularity, hub files, and directory themes.

    Args:
        min_community_size: Minimum files per community to report (default 3).
        max_communities: Maximum number of communities to return (default 20).
    """
    svc = _get_ast_service()
    idx = svc._index

    # Build undirected adjacency with weights
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
            # Bidirectional imports get weight 2, unidirectional weight 1
            key = (min(src, tgt), max(src, tgt))
            is_bidirectional = tgt in idx.file_dependencies and src in idx.file_dependencies.get(tgt, set())
            weights[key] = 2.0 if is_bidirectional else 1.0

    # Try Louvain, fall back to BFS connected components
    try:
        communities, modularity_score = _louvain_communities(all_files, adj, weights)
        method = "louvain"
    except ImportError:
        communities, modularity_score = _bfs_connected_components(all_files, adj)
        method = "connected-components"

    # Sort by size descending, filter by min size
    communities.sort(key=len, reverse=True)
    communities = [c for c in communities if len(c) >= min_community_size][:max_communities]

    lines = [
        f"Community detection ({method}): {len(communities)} communities "
        f"(min size {min_community_size}, modularity={modularity_score:.3f})"
    ]
    for i, community in enumerate(communities, 1):
        # Find common directory prefix as "theme"
        dirs = [os.path.dirname(f) for f in community if os.path.dirname(f)]
        if dirs:
            theme_counter: Counter[str] = Counter(dirs)
            common_theme = theme_counter.most_common(1)[0][0]
        else:
            common_theme = "(root)"

        # Internal vs external degree
        internal_edges = 0
        external_edges = 0
        for f in community:
            for neighbor in adj.get(f, set()):
                if neighbor in community:
                    internal_edges += 1
                else:
                    external_edges += 1
        internal_edges //= 2  # Each edge counted twice

        lines.append(f"\n  Community {i} ({len(community)} files) — theme: {common_theme}")
        lines.append(f"    Internal edges: {internal_edges}, External edges: {external_edges}")

        # Hub: highest internal degree (within community)
        def _internal_degree(f: str, _community: set[str] = community) -> int:
            return sum(1 for n in adj.get(f, set()) if n in _community)

        hub = max(community, key=_internal_degree)
        hub_deg = _internal_degree(hub)
        lines.append(f"    Hub: {hub} (internal degree {hub_deg})")

        # Show sample files
        sample = sorted(community)[:5]
        for f in sample:
            i_deg = _internal_degree(f)
            lines.append(f"    - {f} (internal degree {i_deg})")
        if len(community) > 5:
            lines.append(f"    ... and {len(community) - 5} more")

    return "\n".join(lines)


@mcp.tool()
def repo_map_ranked(
    task_context: str = "",
    token_budget: int = 1024,
    exclude_tests: bool = True,
) -> str:
    """Generate a graph-ranked repository map using PageRank.

    Ranks files by their importance in the dependency graph, weighted
    by relevance to the current task. Produces a token-budgeted map
    of the most important files and their key symbols.

    Args:
        task_context: Description of the current task for relevance scoring.
        token_budget: Maximum tokens for the output (default 1024).
        exclude_tests: Whether to exclude test files from ranking.
    """
    from attocode.code_intel.repo_ranker import format_repo_map, rank_repo_files

    ctx_mgr = _get_context_mgr()

    # Build adjacency from the dependency graph
    adjacency: dict[str, list[str]] = {}
    symbols_by_file: dict[str, list[str]] = {}

    for file_path in ctx_mgr.list_files():
        rel = os.path.relpath(file_path, _get_project_dir())
        deps = ctx_mgr.get_dependencies(file_path)
        adjacency[rel] = [os.path.relpath(d, _get_project_dir()) for d in deps]

        # Extract symbols if available
        try:
            analyzer = _get_code_analyzer()
            result = analyzer.analyze_file(file_path)
            symbols_by_file[rel] = [
                c.name for c in (result.chunks or []) if hasattr(c, "name") and c.name
            ][:10]
        except Exception:
            pass

    if not adjacency:
        return "No files indexed. Run bootstrap first."

    result = rank_repo_files(
        adjacency,
        task_context=task_context,
        token_budget=token_budget,
        symbols_by_file=symbols_by_file,
        exclude_tests=exclude_tests,
    )
    return format_repo_map(result)


@mcp.tool()
def bug_scan(base_branch: str = "main", min_confidence: float = 0.5) -> str:
    """Scan the diff between current branch and base for potential bugs.

    Analyzes added lines for common patterns: bare excepts, eval/exec usage,
    shell injection, swallowed exceptions, and more. Reports findings with
    severity and confidence levels.

    Args:
        base_branch: Base branch to diff against (default "main").
        min_confidence: Minimum confidence threshold for reported findings (0.0-1.0).
    """
    import subprocess

    from attocode.code_intel.bug_finder import scan_diff

    project_dir = _get_project_dir()

    try:
        result = subprocess.run(
            ["git", "diff", f"{base_branch}...HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        diff_text = result.stdout
    except FileNotFoundError:
        return "git not found. Install git to use bug_scan."
    except subprocess.TimeoutExpired:
        return "git diff timed out (>30s). Try a smaller diff range."
    except Exception as e:
        return f"Failed to get diff: {e}"

    if not diff_text.strip():
        return f"No diff found between {base_branch} and HEAD."

    report = scan_diff(diff_text)
    return report.format_report(min_confidence=min_confidence)
