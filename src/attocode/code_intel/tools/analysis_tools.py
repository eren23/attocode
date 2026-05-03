"""Analysis tools for the code-intel MCP server.

Tools: file_analysis, impact_analysis, dependency_graph, hotspots,
cross_references, dependencies, graph_query, graph_dsl, find_related,
community_detection, repo_map_ranked, bug_scan.
"""

from __future__ import annotations

from attocode.code_intel._shared import (
    _get_code_analyzer,
    _get_context_mgr,
    _get_project_dir,
    _get_remote_service,
    _get_service,
    mcp,
)
from attocode.code_intel.tools.pin_tools import pin_stamped


@mcp.tool()
def file_analysis(path: str) -> str:
    """Get detailed analysis of a single file including code chunks, imports, and exports.

    Extracts structured information about functions, classes, methods,
    imports, and exports using AST parsing (tree-sitter or regex fallback).

    Args:
        path: File path (relative to project root or absolute).
    """
    return _get_service().file_analysis(path)


@mcp.tool()
def impact_analysis(changed_files: list[str]) -> str:
    """Analyze the transitive impact of changing one or more files.

    Uses BFS on the reverse dependency graph to find all files that
    could be affected by changes to the given files. This is useful
    for understanding the blast radius of a code change.

    Args:
        changed_files: List of file paths that were changed.
    """
    return _get_service().impact_analysis(changed_files)


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
    return _get_service().dependency_graph(start_file, depth=depth)


@mcp.tool()
def hotspots(top_n: int = 15) -> str:
    """Identify files with highest complexity, coupling, and risk.

    Ranks files by a composite score combining size, symbol count,
    fan-in (dependents), fan-out (dependencies), and symbol density.
    Also categorizes files as god-files, hubs, coupling magnets, or orphans.

    Args:
        top_n: Number of top hotspots to show (default 15).
    """
    return _get_service().hotspots(top_n=top_n)


@mcp.tool()
def cross_references(symbol_name: str) -> str:
    """Find where a symbol is defined and all places it is referenced.

    Shows both the definition locations and all call sites, imports,
    and attribute accesses for the given symbol.

    Args:
        symbol_name: Name of the symbol to look up.
    """
    return _get_service().cross_references(symbol_name)


@mcp.tool()
def call_graph(
    symbol: str,
    direction: str = "callees",
    depth: int = 1,
) -> str:
    """Function-level call-graph traversal — who calls whom.

    With ``direction="callees"``, returns symbols called by ``symbol``
    (forward edges). With ``direction="callers"``, returns symbols that
    call ``symbol`` (reverse edges). ``depth`` caps the BFS hops.

    Edges are populated from tree-sitter parsing during indexing and
    optionally enriched by LSP. The set of edges grows monotonically
    as more files get indexed; rerun after a full ``reindex`` for
    completeness.

    Args:
        symbol: Function or method name (qualified or bare).
        direction: "callees" (forward) or "callers" (reverse).
        depth: Maximum BFS hops (default 1).
    """
    return _get_service().call_graph(symbol, direction=direction, depth=depth)


@mcp.tool()
def dependencies(path: str) -> str:
    """Get import/dependency relationships for a file.

    Shows both what the file imports from (dependencies) and what files
    import it (dependents/importers).

    Args:
        path: File path (relative to project root or absolute).
    """
    return _get_service().dependencies(path)


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
    return _get_service().graph_query(
        file=file,
        edge_type=edge_type,
        direction=direction,
        depth=depth,
    )


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
    remote = _get_remote_service()
    if remote is not None:
        return remote.graph_dsl(query)

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
    return _get_service().find_related(file=file, top_k=top_k)


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
    return _get_service().community_detection(
        min_community_size=min_community_size,
        max_communities=max_communities,
    )


@mcp.tool()
@pin_stamped
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
    remote = _get_remote_service()
    if remote is not None:
        return remote.repo_map_ranked(
            task_context=task_context,
            token_budget=token_budget,
            exclude_tests=exclude_tests,
        )

    from attocode.code_intel.repo_ranker import format_repo_map, rank_repo_files

    ctx_mgr = _get_context_mgr()

    # Build adjacency from the dependency graph
    adjacency: dict[str, list[str]] = {}
    symbols_by_file: dict[str, list[str]] = {}
    dep_graph = ctx_mgr._dep_graph
    for fi in ctx_mgr._files:
        rel = fi.relative_path
        if dep_graph is not None:
            deps = dep_graph.get_imports(rel)
            adjacency[rel] = list(deps)
        else:
            adjacency[rel] = []

        # Extract symbols if available
        try:
            analyzer = _get_code_analyzer()
            result = analyzer.analyze_file(fi.full_path)
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
    remote = _get_remote_service()
    if remote is not None:
        return remote.bug_scan(base_branch=base_branch, min_confidence=min_confidence)

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
