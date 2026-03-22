"""Navigation tools for the code-intel MCP server.

Tools: repo_map, symbols, search_symbols, explore_codebase,
project_summary, bootstrap.
"""

from __future__ import annotations

import os
from collections import deque

from attocode.code_intel.helpers import (
    _analyze_conventions,
    _classify_layers,
    _detect_build_system,
    _detect_project_name,
    _detect_tech_stack,
    _find_entry_points,
    _find_hub_files,
    _format_conventions,
    _summarize_directories,
)
from attocode.code_intel.server import (
    _get_ast_service,
    _get_context_mgr,
    _get_project_dir,
    mcp,
)


@mcp.tool()
def repo_map(
    include_symbols: bool = True,
    max_tokens: int = 6000,
) -> str:
    """Get a token-budgeted repository map showing file structure and key symbols.

    Returns a tree view of the project with the most important files annotated
    with their top-level symbols (functions, classes). Files are tiered by
    importance: high-importance files show symbols, medium show names only,
    low-importance files are collapsed.

    Args:
        include_symbols: Whether to annotate files with top-level symbols.
        max_tokens: Token budget for the output (default 6000).
    """
    ctx = _get_context_mgr()
    repo = ctx.get_repo_map(include_symbols=include_symbols, max_tokens=max_tokens)

    lines = [repo.tree]
    lines.append("")
    lines.append(
        f"({repo.total_files} files, {repo.total_lines:,} lines, "
        f"{len(repo.languages)} languages)"
    )
    return "\n".join(lines)


@mcp.tool()
def symbols(path: str) -> str:
    """List all symbols (functions, classes, methods) defined in a file.

    Args:
        path: File path (relative to project root or absolute).
    """
    svc = _get_ast_service()
    locs = svc.get_file_symbols(path)

    if not locs:
        return f"No symbols found in {path}"

    lines = [f"Symbols in {path}:"]
    for loc in sorted(locs, key=lambda s: s.start_line):
        lines.append(f"  {loc.kind} {loc.qualified_name}  (L{loc.start_line}-{loc.end_line})")
    return "\n".join(lines)


@mcp.tool()
def search_symbols(name: str) -> str:
    """Search for symbol definitions across the entire codebase.

    Finds functions, classes, and methods matching the given name
    (exact or suffix match).

    Args:
        name: Symbol name to search for (e.g. "parse_file", "AgentBuilder").
    """
    svc = _get_ast_service()
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


@mcp.tool()
def explore_codebase(
    path: str = "",
    max_items: int = 30,
    importance_threshold: float = 0.3,
) -> str:
    """Explore the codebase one directory level at a time.

    Returns directories with file counts and languages, and files with
    importance scores and top symbols. Use for drill-down navigation
    on large codebases instead of the full repo map.

    Args:
        path: Relative directory path ("" for root, e.g. "src/attocode/integrations").
        max_items: Maximum items (dirs + files) to return (default 30).
        importance_threshold: Minimum file importance to show (0.0-1.0, default 0.3).
    """
    from attocode.code_intel.server import _get_explorer

    explorer = _get_explorer()
    result = explorer.explore(
        path,
        max_items=max_items,
        importance_threshold=importance_threshold,
    )
    return explorer.format_result(result)


@mcp.tool()
def project_summary(max_tokens: int = 4000) -> str:
    """Get a high-level project summary suitable for bootstrapping understanding.

    Produces a structured overview including project identity, stats,
    entry points, core architecture, directory layout, dependency layers,
    tech stack, test structure, and build system. Ideal as a first tool
    call when approaching an unknown codebase.

    Args:
        max_tokens: Token budget for the output (default 4000).
    """
    ctx = _get_context_mgr()
    files = ctx._files

    if not files:
        return "No files discovered in this project."

    project_dir = _get_project_dir()

    # Gather data
    repo = ctx.get_repo_map(include_symbols=False, max_tokens=500)
    svc = _get_ast_service()
    index = svc._index
    ast_cache = svc._ast_cache

    # Build sections as (header, text) pairs -- drop least-critical if over budget
    # (header, text, priority) -- lower priority = drop first
    sections: list[tuple[str, str, int]] = []

    # 1. Project identity + stats
    name = _detect_project_name(project_dir)
    top_langs = sorted(repo.languages.items(), key=lambda x: -x[1])[:8]
    lang_str = ", ".join(f"{lang} ({count})" for lang, count in top_langs)
    identity = (
        f"Project: {name}\n"
        f"Files: {repo.total_files}, Lines: {repo.total_lines:,}\n"
        f"Languages: {lang_str or 'unknown'}"
    )
    sections.append(("Overview", identity, 10))

    # 2. Entry points
    entries = _find_entry_points(files, index)
    if entries:
        entry_lines = [f"  {path} — {reason}" for path, reason in entries[:10]]
        sections.append(("Entry Points", "\n".join(entry_lines), 9))

    # 3. Core architecture (hub files)
    if index.file_dependents:
        hubs = _find_hub_files(files, index, top_n=10)
        if hubs:
            hub_lines = [f"  {path} (fan-in={fi}, fan-out={fo})" for path, fi, fo in hubs]
            sections.append(("Core Files (by dependents)", "\n".join(hub_lines), 8))

    # 4. Key directories
    dirs = _summarize_directories(files)
    total_files = len(files)
    dir_lines = []
    for d, count, lines_count in dirs[:15]:
        pct = count / total_files * 100 if total_files else 0
        # Filter out docs/site unless significant
        if d in ("site", "docs", "doc", ".git") and pct < 10:
            continue
        dir_lines.append(f"  {d}/ — {count} files, {lines_count:,} lines ({pct:.0f}%)")
    if dir_lines:
        sections.append(("Directory Layout", "\n".join(dir_lines), 7))

    # 5. Dependency layers
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

    # 6. Tech stack
    if ast_cache:
        stack = _detect_tech_stack(ast_cache)
        if stack:
            sections.append(("Tech Stack", "  " + ", ".join(stack), 6))

    # 7. Test structure
    test_files = [f for f in files if f.is_test]
    if test_files:
        has_prefix = any(
            "test_" in os.path.basename(f.relative_path)
            for f in test_files
        )
        test_pat = "test_*.py" if has_prefix else "*_test.py"
        sections.append(("Tests", f"  {len(test_files)} test files (pattern: {test_pat})", 4))

    # 8. Build system
    build = _detect_build_system(files)
    if build != "unknown":
        sections.append(("Build System", f"  {build}", 3))

    # Token budget: progressively drop lowest-priority sections
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


@mcp.tool()
def bootstrap(task_hint: str = "", max_tokens: int = 8000) -> str:
    """All-in-one codebase orientation -- the best first tool call.

    Detects codebase size and returns an optimized bundle:
    - Project summary (identity, stats, entry points, architecture)
    - Repository map OR hierarchical exploration (size-dependent)
    - Coding conventions (25-file sample)
    - Relevant search results (if task_hint provided)
    - Navigation guidance tailored to codebase size

    Replaces 2-4 sequential calls (project_summary + repo_map + conventions
    + semantic_search) with a single call. Inspired by Stripe's pre-hydration
    pattern.

    Args:
        task_hint: Optional description of what you're trying to do.
            When provided, includes semantic search results for relevant code.
        max_tokens: Token budget for the entire output (default 8000).
    """
    from attocode.code_intel.server import _get_explorer
    from attocode.code_intel.tools.search_tools import _get_semantic_search

    ctx = _get_context_mgr()
    files = ctx._files

    if not files:
        return "No files discovered in this project."

    total_files = len(files)

    # Determine codebase size tier
    import os
    _file_cap = int(os.environ.get("ATTOCODE_FILE_CAP", "5000"))
    if total_files < 100:
        size_tier = "small"
    elif total_files < _file_cap:
        size_tier = "medium"
    else:
        size_tier = "large"

    # Budget allocation: summary 38%, structure 38%, conventions 12%, search 12%
    summary_budget = int(max_tokens * 0.38)
    structure_budget = int(max_tokens * 0.38)
    conventions_budget = int(max_tokens * 0.12)
    search_budget = int(max_tokens * 0.12) if task_hint else 0
    # Redistribute search budget if no task_hint
    if not task_hint:
        summary_budget = int(max_tokens * 0.40)
        structure_budget = int(max_tokens * 0.44)
        conventions_budget = int(max_tokens * 0.16)

    sections: list[str] = []

    # Section 1: Project summary
    summary_text = project_summary(max_tokens=summary_budget)
    sections.append(summary_text)

    # Section 2: Structure (size-dependent)
    if size_tier == "small":
        # Full repo map for small codebases
        map_text = repo_map(include_symbols=True, max_tokens=structure_budget)
        sections.append(f"## Repository Map\n{map_text}")
    elif size_tier == "medium":
        # Repo map without symbols + top hotspots
        from attocode.code_intel.tools.analysis_tools import hotspots as _hotspots

        map_text = repo_map(include_symbols=True, max_tokens=int(structure_budget * 0.7))
        hs_text = _hotspots(top_n=10)
        sections.append(f"## Repository Map\n{map_text}")
        sections.append(f"## Hotspots\n{hs_text}")
    else:
        # Large: hierarchical exploration + hotspots (no full map)
        from attocode.code_intel.tools.analysis_tools import hotspots as _hotspots

        explorer = _get_explorer()
        root_result = explorer.explore("", max_items=20, importance_threshold=0.3)
        explore_text = explorer.format_result(root_result)
        hs_text = _hotspots(top_n=10)
        sections.append(f"## Top-Level Structure\n{explore_text}")
        sections.append(f"## Hotspots\n{hs_text}")

    # Section 3: Conventions (small sample)
    svc = _get_ast_service()
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
            # Truncate if over budget
            conv_chars = conventions_budget * 4  # ~3.5 chars per token
            if len(conv_text) > conv_chars:
                conv_text = conv_text[:conv_chars] + "\n  ..."
            sections.append(f"## Conventions\n{conv_text}")

    # Section 4: Task-relevant search (if task_hint provided)
    if task_hint:
        try:
            mgr = _get_semantic_search()
            results = mgr.search(task_hint, top_k=5)
            if results:
                search_text = mgr.format_results(results)
                # Truncate if over budget
                search_chars = search_budget * 4
                if len(search_text) > search_chars:
                    search_text = search_text[:search_chars] + "\n  ..."
                sections.append(f"## Relevant Code for: {task_hint}\n{search_text}")
        except Exception:
            pass  # Graceful degradation -- search is optional

    # Navigation guidance
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


@mcp.tool()
def conventions(sample_size: int = 50, path: str = "") -> str:
    """Detect coding conventions and style patterns in the project.

    Analyzes function naming, type hints, docstrings, async usage,
    import style, popular decorators, class patterns, and module
    organization across a sample of the most important files.

    When ``path`` is set, only samples files within that directory subtree
    and appends a comparison to project-wide conventions. This follows
    Stripe's "scoped rules" pattern -- different directories may follow
    different conventions.

    Args:
        sample_size: Number of files to sample (default 50).
        path: Optional directory path to scope the analysis to (e.g. "src/core").
            When empty, analyzes the entire project.
    """
    svc = _get_ast_service()
    ast_cache = svc._ast_cache

    if not ast_cache:
        return "No files parsed — cannot detect conventions."

    ctx = _get_context_mgr()
    files = ctx._files

    # Filter by path if specified
    path_prefix = path.rstrip("/") + "/" if path else ""

    if path_prefix:
        # Scoped analysis: files in the target directory
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

        # Also compute global conventions for comparison
        global_candidates = sorted(
            [fi for fi in files if fi.relative_path in ast_cache],
            key=lambda fi: fi.importance,
            reverse=True,
        )
        global_rels = [fi.relative_path for fi in global_candidates[:sample_size]]
        global_stats = _analyze_conventions(ast_cache, global_rels)

        # Format scoped conventions with global comparison
        header = f"Conventions in {path}/ ({len(scoped_rels)} files):\n"
        scoped_text = _format_conventions(scoped_stats)

        # Build comparison section
        comparison_parts: list[str] = []
        scoped_fn = scoped_stats["total_functions"]
        global_fn = global_stats["total_functions"]

        if scoped_fn > 0 and global_fn > 0:
            scoped_type_pct = scoped_stats["typed_return"] / scoped_fn * 100
            global_type_pct = global_stats["typed_return"] / global_fn * 100
            if abs(scoped_type_pct - global_type_pct) > 10:
                comparison_parts.append(
                    f"  Type hints: {scoped_type_pct:.0f}% here"
                    f" vs {global_type_pct:.0f}% project-wide"
                )

            scoped_doc_pct = scoped_stats["has_docstring_fn"] / scoped_fn * 100
            global_doc_pct = global_stats["has_docstring_fn"] / global_fn * 100
            if abs(scoped_doc_pct - global_doc_pct) > 10:
                comparison_parts.append(
                    f"  Docstrings: {scoped_doc_pct:.0f}% here"
                    f" vs {global_doc_pct:.0f}% project-wide"
                )

            scoped_async_pct = scoped_stats["async_count"] / scoped_fn * 100
            global_async_pct = global_stats["async_count"] / global_fn * 100
            if abs(scoped_async_pct - global_async_pct) > 10:
                comparison_parts.append(
                    f"  Async: {scoped_async_pct:.0f}% here vs {global_async_pct:.0f}% project-wide"
                )

        if comparison_parts:
            divergence = "\n".join(comparison_parts)
            header += (
                scoped_text
                + "\n\nDivergence from project conventions:\n"
                + divergence
            )
        else:
            header += scoped_text + "\n\n(Matches project-wide conventions.)"
        return header

    # Global (unscoped) analysis
    candidates = sorted(
        [fi for fi in files if fi.relative_path in ast_cache],
        key=lambda fi: fi.importance,
        reverse=True,
    )
    sample_rels = [fi.relative_path for fi in candidates[:sample_size]]

    if not sample_rels:
        return "No parsed files available for convention analysis."

    stats = _analyze_conventions(ast_cache, sample_rels)

    # Per-directory convention analysis
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


@mcp.tool()
def relevant_context(
    files: list[str],
    depth: int = 1,
    max_tokens: int = 4000,
    include_symbols: bool = True,
) -> str:
    """Get a subgraph capsule -- a file and its neighbors with symbols.

    BFS from center file(s) in both directions (imports and importers) up to
    `depth` hops. For each file shows: language, line count, importance,
    relationship to center, and top symbols. Replaces N+1 sequential calls
    (dependency_graph + symbols on each neighbor).

    Args:
        files: Center file paths (relative to project root or absolute).
        depth: How many hops to traverse (default 1, max 2).
        max_tokens: Token budget for the output (default 4000).
        include_symbols: Whether to include symbol lists (default True).
    """
    svc = _get_ast_service()
    ctx = _get_context_mgr()
    ast_cache = svc._ast_cache
    all_files = {fi.relative_path: fi for fi in ctx._files}

    depth = min(depth, 2)  # Cap at 2 to avoid explosion

    # Normalize center files to relative paths
    center_rels: list[str] = []
    for f in files:
        rel = svc._to_rel(f)
        if rel:
            center_rels.append(rel)

    if not center_rels:
        return "No valid files provided."

    # BFS in both directions
    visited: dict[str, tuple[int, str]] = {}  # rel -> (distance, relationship)
    queue: deque[tuple[str, int, str]] = deque()

    for rel in center_rels:
        visited[rel] = (0, "center")
        queue.append((rel, 0, "center"))

    while queue:
        current, d, _rel_type = queue.popleft()
        if d >= depth:
            continue

        # Forward: files this one imports
        for dep in svc.get_dependencies(current):
            if dep not in visited:
                relationship = "imported-by-center" if d == 0 else "transitive-import"
                visited[dep] = (d + 1, relationship)
                queue.append((dep, d + 1, relationship))

        # Reverse: files that import this one
        for dep in svc.get_dependents(current):
            if dep not in visited:
                relationship = "imports-center" if d == 0 else "transitive-importer"
                visited[dep] = (d + 1, relationship)
                queue.append((dep, d + 1, relationship))

    # Sort: center first, then by distance, then by importance
    def _sort_key(item: tuple[str, tuple[int, str]]) -> tuple[int, float]:
        rel, (dist, _) = item
        fi = all_files.get(rel)
        importance = fi.importance if fi else 0.0
        return (dist, -importance)

    sorted_files = sorted(visited.items(), key=_sort_key)

    # Build output with token budget
    sections: list[str] = []
    token_est = 0
    max_symbols_center = 8
    max_symbols_neighbor = 5

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
            max_sym = max_symbols_center if dist == 0 else max_symbols_neighbor
            sym_lines: list[str] = []
            for fn in file_ast.functions[:max_sym]:
                params = ", ".join(p.name for p in fn.parameters[:4])
                ret = f" -> {fn.return_type}" if fn.return_type else ""
                sym_lines.append(f"    fn {fn.name}({params}){ret}")
            for cls in file_ast.classes[:max_sym]:
                bases = f"({', '.join(cls.bases[:3])})" if cls.bases else ""
                methods_preview = ", ".join(m.name for m in cls.methods[:4])
                sym_lines.append(f"    class {cls.name}{bases}: {methods_preview}")
            # Trim if too many total
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
